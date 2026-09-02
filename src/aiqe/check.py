"""`aiqe check`: run what the repository declared, and say what remains unknown.

The order of operations is the design, so it is worth stating plainly.

```
1  the active task, and the commit it started from
2  the current state of every owned path, against that baseline
3  the configuration, parsed fail-closed
4  classification of the changed owned paths
5  which validators apply, and which of them have consent
6  bounded authority, measured
7  the validators run
8  bounded authority, measured again
9  coverage arithmetic
10 one evidence record, replacing the last
```

Steps 6 and 8 are the ones that are easy to leave out, and they are the reason
this command can say `CURRENT` at all. A validator is arbitrary code. The
naive shape of this feature - run the tests, record that they passed - cannot
tell the difference between a validator that checked the code and a validator
that edited the code and then reported success. AIQE measures the owned
binding, HEAD, the configuration bytes and the validator definitions on both
sides of execution, and if any of them moved, the result is not current
evidence. It is not a failure either: nothing was proven false. It is
`INCOMPLETE`, which is the honest word.

Step 1 has the same character. If HEAD moved since the task started, the
baseline the task was declared against is gone. AIQE does not silently
rebaseline onto the new commit - that would quietly redefine what "changed"
means, retroactively, in the user's favour.

**A fully green check does not produce a receipt verdict.** It produces an
internal `REVIEWABLE_CANDIDATE`: every pre-commit obligation is discharged,
and the thing that would make the work reviewable - a bounded commit whose
content is provably the checked content - has not been created, because
`aiqe commit` does not exist. Rendering that as `REVIEWABLE` would be exactly
the overstatement this product tells its users not to accept.
"""

import time

from . import classify as classify_module
from . import config as config_module
from . import evidence as evidence_module
from . import exits
from . import pathstate
from . import task as task_module
from . import taskstate
from . import validators as validators_module
from .textsafe import display_bytes, display_text

#: The internal completion state a fully green pre-commit check produces. Not
#: a verdict, and deliberately not the word `REVIEWABLE`.
REVIEWABLE_CANDIDATE = "REVIEWABLE_CANDIDATE"
INCOMPLETE = "INCOMPLETE"
NOT_REVIEWABLE = "NOT_REVIEWABLE"

CHECK_COMPLETE = "CHECK_COMPLETE"
CHECK_FAILED = "CHECK_FAILED"
CHECK_INCOMPLETE = "CHECK_INCOMPLETE"
CHECK_REFUSED = "CHECK_REFUSED"

NO_ACTIVE_TASK = "NO_ACTIVE_TASK"
TASK_BASELINE_MOVED = "TASK_BASELINE_MOVED"
AUTHORITY_CHANGED_DURING_CHECK = "AUTHORITY_CHANGED_DURING_CHECK"
UNKNOWN_VALIDATOR_ID = "UNKNOWN_VALIDATOR_ID"
REQUIRED_VALIDATOR_FAILED = "REQUIRED_VALIDATOR_FAILED"
REQUIRED_VALIDATOR_UNKNOWN = "REQUIRED_VALIDATOR_UNKNOWN"
REQUIRED_VALIDATOR_UNAVAILABLE = "REQUIRED_VALIDATOR_UNAVAILABLE"

#: What the user is told before being asked to let a repository-declared
#: command run as them. It is blunt because every word of it is true, and
#: because consent obtained by understating what is being consented to is not
#: consent.
CONSENT_DISCLOSURE = (
    "This validator is ordinary repository-defined code, and running it runs "
    "it as you.\n"
    "AIQE does not sandbox it. AIQE does not restrict its filesystem access. "
    "AIQE does not\nrestrict its network access. It can do anything your "
    "shell can do."
)


class CheckOutcome(object):
    """What a check invocation concluded, and what the process exits with."""

    __slots__ = ("code", "exit_code", "lines", "document")

    def __init__(self, code, exit_code, lines, document=None):
        self.code = code
        self.exit_code = exit_code
        self.lines = lines
        self.document = document

    def render(self):
        # Trailing spaces are column padding, not content. Left in, they
        # survive into anything that quotes this output and break on the first
        # editor that strips whitespace on save.
        return "\n".join(line.rstrip() for line in self.lines) + "\n"


def run(cwd, allow=(), env=None, prompt=None):
    """Run one check. `prompt` is supplied only for an interactive terminal."""
    from . import __version__

    repository, failure = task_module.discover(cwd, env)
    if failure is not None:
        return CheckOutcome(failure.code, failure.exit_code, failure.lines)

    try:
        state_directory = task_module._existing_state_directory(repository, env)
        record = taskstate.read_active(state_directory)
    except taskstate.CorruptState as error:
        return CheckOutcome(
            error.code,
            exits.INCOMPLETE,
            [
                "aiqe: " + error.message,
                "Run `aiqe task end` to discard it and start again.",
            ],
        )
    except taskstate.StateError as error:
        return CheckOutcome(error.code, exits.UNSUPPORTED, ["aiqe: " + error.message])

    if record is None:
        return CheckOutcome(
            NO_ACTIVE_TASK,
            exits.UNSUPPORTED,
            [
                "aiqe: no active task in this worktree.",
                "A check reports on a bounded unit of work, so start one with "
                "`aiqe task start --own <path>...` first.",
            ],
        )

    baseline = record["start_head_sha"]
    if repository.head_state != "commit" or repository.head_sha != baseline:
        # Do not rebaseline. The task declared its scope against one commit,
        # and moving that baseline underneath it would redefine "changed"
        # retroactively, in whichever direction happened to be convenient.
        return CheckOutcome(
            TASK_BASELINE_MOVED,
            exits.INCOMPLETE,
            [
                "AIQE CHECK",
                "",
                "  HEAD has moved since this task started, so the commit the",
                "  task was declared against is no longer the commit you are",
                "  on. AIQE does not rebaseline a task silently.",
                "",
                "  Evidence        STALE",
                "  Completion      INCOMPLETE",
                "  Reason          " + TASK_BASELINE_MOVED,
                "",
                "  End the task and start a new one against the current commit.",
            ],
            document=_incomplete_document(
                (TASK_BASELINE_MOVED,), evidence="STALE"
            ),
        )

    try:
        config = config_module.load(repository.worktree)
    except config_module.ConfigError as error:
        return CheckOutcome(
            error.code, exits.UNSUPPORTED, ["aiqe: " + error.message]
        )

    unknown = [name for name in allow if config.validator(name) is None]
    if unknown:
        return CheckOutcome(
            UNKNOWN_VALIDATOR_ID,
            exits.UNSUPPORTED,
            [
                "aiqe: --allow names no declared validator: %s"
                % (", ".join(display_text(name) for name in sorted(set(unknown))),),
                "Declared validators: %s"
                % (
                    ", ".join(display_text(v.id) for v in config.validators)
                    or "none",
                ),
            ],
        )

    owned_paths = task_module.decode_owned_paths(record)

    try:
        owned_states = pathstate.resolve(
            repository.runner, repository.worktree, owned_paths, baseline
        )
    except pathstate.PathStateError as error:
        return CheckOutcome(
            error.code, exits.UNSUPPORTED, ["aiqe: " + error.message]
        )

    changed = [state.path for state in owned_states if state.changed]

    try:
        classification = classify_module.classify(config, changed)
    except classify_module.ConfigConflict as conflict:
        # Exit 3, and no new evidence. A partial result here would be a
        # rendering of a configuration that says two things at once.
        return CheckOutcome(
            classify_module.CONFIG_CONFLICT,
            exits.UNSUPPORTED,
            ["aiqe: " + conflict.message],
        )

    applicable, not_applicable = classify_module.applicable_validators(
        config, classification.applicable_contracts
    )

    definitions = {
        validator.id: validators_module.definition_digest(validator)
        for validator in config.validators
    }

    try:
        # Constructed before anything is executed. Recorded consent is the
        # authorization boundary for running repository-declared commands, so
        # a consent store AIQE cannot trust has to stop the operation rather
        # than be read past.
        consents = validators_module.ConsentStore(state_directory)
    except taskstate.StateError as error:
        return _state_refusal(error)

    before = _authority(repository, config, owned_states, definitions)
    outcomes = _execute(
        applicable, definitions, consents, repository, env, allow, prompt
    )

    drift = _drift(repository, config, owned_paths, baseline, definitions, before)
    if drift:
        # Something the conclusion rests on moved while the validators ran.
        # The previous record described a state that certainly no longer
        # holds, so it goes rather than being left to look current.
        try:
            evidence_module.remove(state_directory)
        except taskstate.StateError as error:
            return _state_refusal(error)
        return CheckOutcome(
            AUTHORITY_CHANGED_DURING_CHECK,
            exits.INCOMPLETE,
            _render_drift(drift),
            document=_incomplete_document(
                (AUTHORITY_CHANGED_DURING_CHECK,) + tuple(drift),
                evidence="NOT_CURRENT",
            ),
        )

    coverage_results = classify_module.coverage(
        classification.applicable_contracts, outcomes
    )

    completion, exit_code, reasons = _adjudicate(
        classification, coverage_results, outcomes
    )

    foreign = pathstate.foreign_staged_count(repository.runner, owned_paths)
    result = {
        "completion": completion,
        "exit_code": exit_code,
        "reasons": list(reasons),
        "evidence": "CURRENT",
    }
    try:
        _record_evidence(
            state_directory,
            record,
            __version__,
            config,
            before,
            owned_states,
            classification,
            outcomes,
            coverage_results,
            result,
            foreign,
        )
    except taskstate.StateError as error:
        return _state_refusal(error)

    document = _document(
        __version__,
        config,
        owned_states,
        classification,
        outcomes,
        not_applicable,
        coverage_results,
        result,
    )
    return CheckOutcome(
        _code_for(exit_code),
        exit_code,
        _render(
            owned_states,
            classification,
            outcomes,
            not_applicable,
            coverage_results,
            completion,
            reasons,
        ),
        document=document,
    )


def _incomplete_document(reasons, evidence):
    """A machine-readable result for an incompleteness with no coverage to report.

    A check that stopped before it could adjudicate still has a verdict, and a
    caller reading JSON should not have to tell "no classification happened"
    apart from "classification found nothing" by inspecting nulls. Refusals -
    exit 3 - deliberately produce no document at all: an invalid configuration
    is not a result.
    """
    return {
        "schema_version": evidence_module.EVIDENCE_SCHEMA_VERSION,
        "command": "check",
        "result": {
            "completion": INCOMPLETE,
            "exit_code": exits.INCOMPLETE,
            "reasons": sorted(reasons),
            "evidence": evidence,
        },
    }


def _record_evidence(
    state_directory,
    record,
    aiqe_version,
    config,
    authority,
    owned_states,
    classification,
    outcomes,
    coverage_results,
    result,
    foreign,
):
    evidence_module.write(
        state_directory,
        evidence_module.build_record(
            record,
            aiqe_version,
            config,
            authority,
            owned_states,
            classification,
            outcomes,
            coverage_results,
            result,
            foreign,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        ),
    )


def _state_refusal(error):
    """AIQE's own local state is outside its trust boundary.

    Exit 3 rather than a completion verdict: nothing was established about the
    repository, and the thing AIQE could not trust was its own filing cabinet.
    """
    return CheckOutcome(
        error.code,
        exits.UNSUPPORTED,
        ["aiqe: " + error.message, "AIQE will not repair local state it did "
         "not create. Fix or remove it, then run the check again."],
    )


# --- Authority -------------------------------------------------------------


def _authority(repository, config, owned_states, definitions):
    return evidence_module.Authority(
        repository.head_sha,
        config.digest,
        pathstate.binding_digest(owned_states),
        definitions,
    )


def _drift(repository, config, owned_paths, baseline, definitions, before):
    """Recompute the bounded authority and report what moved.

    HEAD is re-resolved rather than reused: a validator can commit, and a
    check whose evidence outlived the commit it was taken against is the
    staleness defect with extra steps.
    """
    resolved = repository.runner.run("rev-parse", "--verify", "--quiet", "HEAD")
    head = None
    if resolved.ok and resolved.lines():
        head = resolved.lines()[0].decode("ascii", "replace").strip()

    try:
        raw = config_module.read_raw(repository.worktree)
        digest = config_module.digest_bytes(raw)
    except config_module.ConfigError:
        digest = None

    try:
        states = pathstate.resolve(
            repository.runner, repository.worktree, owned_paths, baseline
        )
        binding = pathstate.binding_digest(states)
    except pathstate.PathStateError:
        # An owned path that became something unsupported while the validators
        # ran is a change to the very identity the evidence would bind.
        binding = None

    after = evidence_module.Authority(head, digest, binding, definitions)
    return before.differences(after)


def _render_drift(drift):
    lines = [
        "AIQE CHECK",
        "",
        "  The state this check rests on changed while the validators ran, so",
        "  the result does not describe the repository as it is now.",
        "",
    ]
    for reason in evidence_module.STALENESS_REASONS:
        if reason in drift:
            lines.append("  Changed         " + reason)
    lines.extend(
        [
            "",
            "  Evidence        NOT CURRENT",
            "  Completion      INCOMPLETE",
            "  Reason          " + AUTHORITY_CHANGED_DURING_CHECK,
            "",
            "  A validator that modifies what it checks cannot also be evidence",
            "  about it. Run `aiqe check` again once the worktree is settled.",
        ]
    )
    return lines


# --- Execution -------------------------------------------------------------


def _execute(applicable, definitions, consents, repository, env, allow, prompt):
    """Resolve consent for each applicable validator, then run what is allowed.

    Consent is decided before anything is spawned, and a validator without it
    is not executed at all - not started and killed, not run with its output
    discarded. `UNCONSENTED_VALIDATOR_EXECUTIONS = 0` is a statement about
    process creation, and it is only true if the decision happens here.
    """
    allowed_once = set(allow)
    outcomes = []

    for validator in applicable:
        digest = definitions[validator.id]

        if validator.id in allowed_once or consents.granted(digest):
            outcomes.append(
                validators_module.execute(
                    validator, digest, repository.worktree, env or {}
                )
            )
            continue

        if prompt is None:
            outcomes.append(
                validators_module.Outcome(
                    validator,
                    digest,
                    validators_module.UNKNOWN,
                    reason=validators_module.CONSENT_REQUIRED,
                )
            )
            continue

        if prompt(_consent_request(validator, digest)):
            consents.grant(digest, validator.id)
            outcomes.append(
                validators_module.execute(
                    validator, digest, repository.worktree, env or {}
                )
            )
        else:
            outcomes.append(
                validators_module.Outcome(
                    validator,
                    digest,
                    validators_module.UNKNOWN,
                    reason=validators_module.CONSENT_DECLINED,
                )
            )
    return outcomes


def _consent_request(validator, digest):
    """Exactly what is about to run, and exactly what AIQE does not promise.

    Every repository-controlled value here is escaped. This prompt is the one
    place AIQE prints an attacker-chosen argument vector next to a question it
    wants a truthful answer to, and an argv element carrying `ESC[2J` and a
    plausible second prompt is the obvious way to get the wrong answer to it.
    What the user sees is `\x1b[2J`, on the line where AIQE put it.
    """
    lines = [
        "",
        "  %s declares a validator AIQE has not been allowed to run here."
        % (config_module.CONFIG_FILENAME,),
        "",
        "    id        %s" % (display_text(validator.id),),
        "    command   %s"
        % (" ".join(display_text(argument) for argument in validator.argv),),
        "    timeout   %d seconds" % (validator.timeout,),
        "    required  %s" % ("yes" if validator.required else "no"),
        "    identity  %s" % (digest,),
        "",
    ]
    lines.extend("  " + line for line in CONSENT_DISCLOSURE.split("\n"))
    lines.append("")
    lines.append(
        "  Consent is recorded for this exact definition on this machine only."
    )
    lines.append("  Changing the command, timeout, required flag or contracts")
    lines.append("  revokes it.")
    return "\n".join(lines)


# --- Adjudication ----------------------------------------------------------


def _adjudicate(classification, coverage_results, outcomes):
    """Completion state, exit code and reason codes.

    A required failure outranks an incompleteness. Both are true at once
    often enough, and reporting the softer of the two would be the wrong
    round-off in the one direction that matters.
    """
    reasons = []

    failed = [
        outcome
        for outcome in outcomes
        if outcome.required and outcome.outcome == validators_module.FAIL
    ]
    unknown = [
        outcome
        for outcome in outcomes
        if outcome.required and outcome.outcome == validators_module.UNKNOWN
    ]
    unavailable = [
        outcome
        for outcome in outcomes
        if outcome.required and outcome.outcome == validators_module.UNAVAILABLE
    ]

    if failed:
        reasons.append(REQUIRED_VALIDATOR_FAILED)
    if unknown:
        reasons.append(REQUIRED_VALIDATOR_UNKNOWN)
    if unavailable:
        reasons.append(REQUIRED_VALIDATOR_UNAVAILABLE)
    if classification.has_gap:
        reasons.append(classify_module.CLASSIFICATION_GAP)

    counts = classify_module.coverage_counts(coverage_results)
    if counts[classify_module.COVERAGE_GAP]:
        reasons.append(classify_module.COVERAGE_GAP)
    if counts[classify_module.CONTRACT_FAILED]:
        reasons.append(classify_module.CONTRACT_FAILED)
    if counts[classify_module.CONTRACT_UNKNOWN]:
        reasons.append(classify_module.CONTRACT_UNKNOWN)

    if failed:
        return NOT_REVIEWABLE, exits.FAIL, tuple(reasons)
    if reasons:
        return INCOMPLETE, exits.INCOMPLETE, tuple(reasons)
    return REVIEWABLE_CANDIDATE, exits.OK, ()


def _code_for(exit_code):
    if exit_code == exits.OK:
        return CHECK_COMPLETE
    if exit_code == exits.FAIL:
        return CHECK_FAILED
    return CHECK_INCOMPLETE


# --- Rendering -------------------------------------------------------------


def _render(
    owned_states,
    classification,
    outcomes,
    not_applicable,
    coverage_results,
    completion,
    reasons,
):
    changed = sum(1 for state in owned_states if state.changed)
    lines = ["AIQE CHECK", ""]
    lines.append(
        "  Owned paths     %d declared · %d changed" % (len(owned_states), changed)
    )
    lines.append(
        "  Classification  %d quant · %d non-quant · %d unclassified"
        % (
            classification.count(classify_module.QUANT_SURFACE),
            classification.count(classify_module.EXPLICIT_NON_QUANT_SURFACE),
            classification.count(classify_module.UNCLASSIFIED),
        )
    )

    unclassified = [
        entry.path
        for entry in classification.paths
        if entry.kind == classify_module.UNCLASSIFIED
    ]
    if unclassified:
        lines.append("")
        lines.append("  Unclassified changed paths - no [[surface]] matches:")
        for path in unclassified:
            lines.append("      %s" % (display_bytes(path),))

    if coverage_results:
        lines.append("")
        lines.append("  Contracts")
        for result in coverage_results:
            # Contract and validator identifiers are constrained by the
            # configuration grammar, so neither can carry a control character.
            # Escaped anyway: the grammar is one edit away from the rendering,
            # and a rendering that only works because of a check somewhere else
            # is a rendering nobody can review on its own.
            detail = (
                ", ".join(
                    display_text(name) for name in result.required_validator_ids
                )
                if result.required_validator_ids
                else "no required validator declares it"
            )
            lines.append(
                "      %-22s %-14s %s"
                % (display_text(result.contract), result.state, detail)
            )

    if outcomes:
        lines.append("")
        lines.append("  Validators")
        for outcome in outcomes:
            lines.append("      " + _validator_line(outcome))
    if not_applicable:
        lines.append("")
        lines.append(
            "  Not applicable  %s"
            % (
                ", ".join(
                    display_text(validator.id) for validator in not_applicable
                ),
            )
        )

    lines.append("")
    lines.append("  Evidence        CURRENT")
    lines.append("  Completion      %s" % (completion,))
    if reasons:
        lines.append("  Reasons         %s" % (" · ".join(reasons),))
    if completion == REVIEWABLE_CANDIDATE:
        lines.append("")
        lines.append(
            "  Every pre-commit obligation is discharged. This is not a"
        )
        lines.append(
            "  REVIEWABLE verdict: no bounded commit exists to bind this"
        )
        lines.append("  evidence to. See `aiqe receipt`.")
    lines.append("")
    return lines


def _validator_line(outcome):
    detail = ""
    if outcome.timed_out:
        detail = "timed out"
    elif outcome.exit_code:
        detail = "exit %d" % (outcome.exit_code,)
    elif outcome.reason:
        detail = outcome.reason
    return "%-22s %-9s %-12s %s" % (
        display_text(outcome.validator_id),
        "required" if outcome.required else "optional",
        outcome.outcome,
        detail,
    )


def _document(
    aiqe_version,
    config,
    owned_states,
    classification,
    outcomes,
    not_applicable,
    coverage_results,
    result,
):
    """The `--format json` document. Machine-readable, and local.

    `aiqe check` output is a local development surface, not the shareable
    receipt: it may name repository-relative paths and validator commands,
    because the user is looking at that repository. The correlation-minimised
    surface is `aiqe receipt`, and the two are deliberately different
    documents rather than one document with a flag.
    """
    return {
        "schema_version": evidence_module.EVIDENCE_SCHEMA_VERSION,
        "aiqe_version": aiqe_version,
        "command": "check",
        "config_schema": config.schema,
        "config_digest": config.digest,
        "owned": [state.as_record() for state in owned_states],
        "changed_owned_count": sum(1 for state in owned_states if state.changed),
        "classification": classification.as_record(),
        "coverage": [entry.as_record() for entry in coverage_results],
        "validators": [outcome.as_record() for outcome in outcomes],
        "validators_not_applicable": [
            {
                "validator_id": validator.id,
                "contracts": list(validator.contracts),
                "reason": validators_module.CONTRACT_NOT_APPLICABLE,
            }
            for validator in not_applicable
        ],
        "result": result,
    }
