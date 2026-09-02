"""`aiqe receipt`: what is proven, what is excluded, and what is unknown.

Two surfaces, and the difference between them is the point.

```
aiqe receipt            the default, correlation-minimised, meant to be shared
aiqe receipt --local    the richer local view, meant to be read here
```

The default receipt is the artifact a person pastes into a pull request, a
chat, or a screenshot, so it is built from counts, states, reason identifiers
and a verdict - and from nothing else. It carries no path, no filename, no
repository name, no remote, no branch, no commit identifier, no validator
command line, no validator output, no username and no hostname. Not because
any one of those is secret, but because together they are an inventory of
somebody's work, and an assurance artifact that quietly discloses one is not
a good trade for its user. The exclusion list is property-tested rather than
reviewed.

**A receipt never executes anything.** Freshness is decided by recomputing
bounded authority - the owned path binding, HEAD, the configuration bytes and
the validator definition digests - and comparing. Re-running validators to
answer "is this still true" would make the answer depend on running them
again, which is the question it was supposed to settle.

**`REVIEWABLE` cannot be reached here, and that is deliberate.** A completely
green pre-commit check produces:

```
Owned scope     CHECKED
Foreign staged  OBSERVED
Evidence        CURRENT
Commit          NONE
Verdict         INCOMPLETE
Reason          BOUNDED_COMMIT_NOT_CREATED
```

Every obligation that exists today is discharged, and the verdict is still
`INCOMPLETE`, because `REVIEWABLE` is a claim about a commit whose content is
provably the checked content - and no commit has been created. The words
`VERIFIED`, `EXCLUDED` and `CREATED` are absent from this surface for the same
reason. Emitting any of them now would mean the vocabulary had to be quietly
redefined later, and a verdict vocabulary that shifts is not a verdict
vocabulary.
"""

from . import classify as classify_module
from . import config as config_module
from . import evidence as evidence_module
from . import exits
from . import pathstate
from . import task as task_module
from . import taskstate
from . import validators as validators_module
from .textsafe import display_bytes, display_text

#: The shape of the default receipt. A consumer that reads this knows which
#: fields to expect.
RECEIPT_SCHEMA_VERSION = 1

#: What was redacted, and by which rule. Bound to the serialiser so that a
#: receipt cannot silently start carrying more than the policy it names.
DEFAULT_REDACTION_POLICY = "aiqe.receipt.default.v1"
LOCAL_REDACTION_POLICY = "aiqe.receipt.local.v1"

REVIEWABLE = "REVIEWABLE"
INCOMPLETE = "INCOMPLETE"
NOT_REVIEWABLE = "NOT_REVIEWABLE"

DECLARED = "DECLARED"
CHECKED = "CHECKED"
OBSERVED = "OBSERVED"
NONE = "NONE"
CURRENT = "CURRENT"
STALE = "STALE"

BOUNDED_COMMIT_NOT_CREATED = "BOUNDED_COMMIT_NOT_CREATED"
EVIDENCE_NONE = "EVIDENCE_NONE"
CONFIG_ABSENT = "CONFIG_ABSENT"
NO_ACTIVE_TASK = "NO_ACTIVE_TASK"
OWNED_PATH_UNRESOLVED = "OWNED_PATH_UNRESOLVED"

RECEIPT_PRODUCED = "RECEIPT_PRODUCED"
RECEIPT_REFUSED = "RECEIPT_REFUSED"


class ReceiptOutcome(object):
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


def run(cwd, local=False, env=None):
    """Produce a receipt, or refuse deterministically."""
    from . import __version__

    repository, failure = task_module.discover(cwd, env)
    if failure is not None:
        return ReceiptOutcome(failure.code, failure.exit_code, failure.lines)

    try:
        state_directory = task_module._existing_state_directory(repository, env)
        record = taskstate.read_active(state_directory)
    except taskstate.CorruptState as error:
        return _refusal(
            error.code,
            exits.INCOMPLETE,
            [
                "aiqe: " + error.message,
                "Run `aiqe task end` to discard it and start again.",
            ],
        )
    except taskstate.StateError as error:
        return _refusal(error.code, exits.UNSUPPORTED, ["aiqe: " + error.message])

    if record is None:
        # Deterministic refusal rather than a fabricated receipt about nothing.
        return _refusal(
            NO_ACTIVE_TASK,
            exits.UNSUPPORTED,
            [
                "aiqe: no active task in this worktree.",
                "A receipt reports on a bounded unit of work. Start one with "
                "`aiqe task start --own <path>...`.",
            ],
        )

    baseline = record["start_head_sha"]
    owned_paths = task_module.decode_owned_paths(record)

    try:
        owned_states = pathstate.resolve(
            repository.runner, repository.worktree, owned_paths, baseline
        )
    except pathstate.PathStateError as error:
        # The refusal names no path. A receipt is the surface a user shares,
        # and an error string is still that surface.
        return _refusal(
            OWNED_PATH_UNRESOLVED,
            exits.UNSUPPORTED,
            [
                "aiqe: an owned path is no longer a regular file, a creation "
                "or a deletion, so its identity cannot be resolved.",
                "Run `aiqe check` for the detail, which names it locally.",
            ],
        )

    config = None
    config_digest = None
    if config_module.present(repository.worktree):
        try:
            config = config_module.load(repository.worktree)
        except config_module.ConfigError as error:
            return _refusal(
                error.code,
                exits.UNSUPPORTED,
                [
                    "aiqe: %s cannot be interpreted, so no receipt is "
                    "produced. Run `aiqe check` for the detail."
                    % (config_module.CONFIG_FILENAME,),
                ],
            )
        config_digest = config.digest

    changed = [state.path for state in owned_states if state.changed]
    if config is not None:
        try:
            classify_module.classify(config, changed)
        except classify_module.ConfigConflict:
            # Exit 3, and no receipt artifact at all. A partial rendering of a
            # configuration that says two things about one file would be worse
            # than no receipt.
            return _refusal(
                classify_module.CONFIG_CONFLICT,
                exits.UNSUPPORTED,
                [
                    "aiqe: a changed owned path is declared both quant and "
                    "non-quant, so no receipt is produced.",
                    "Run `aiqe check` for the detail, which names the path "
                    "and the declarations locally.",
                ],
            )

    try:
        stored = evidence_module.read(state_directory, record["task_id"])
    except taskstate.StateError as error:
        # The same refusal as everywhere else: AIQE will not read local state
        # it cannot trust, and a receipt built on it would be worse than none.
        return _refusal(
            error.code,
            exits.UNSUPPORTED,
            [
                "aiqe: " + error.message,
                "AIQE will not repair local state it did not create. Fix or "
                "remove it, then ask for the receipt again.",
            ],
        )

    definitions = (
        {
            validator.id: validators_module.definition_digest(validator)
            for validator in config.validators
        }
        if config is not None
        else {}
    )
    current = evidence_module.Authority(
        repository.head_sha,
        config_digest,
        pathstate.binding_digest(owned_states),
        definitions,
    )

    state = _assess(record, stored, current, config)
    document = _document(__version__, record, stored, owned_states, state, local)
    lines = _render_local(document) if local else _render_default(document)
    return ReceiptOutcome(RECEIPT_PRODUCED, state["exit_code"], lines, document)


def _refusal(code, exit_code, lines):
    return ReceiptOutcome(code, exit_code, lines, document=None)


# --- Adjudication ----------------------------------------------------------


def _assess(record, stored, current, config):
    """Decide the receipt's verdict from evidence and current authority."""
    reasons = []

    if stored is None:
        reasons.append(EVIDENCE_NONE)
        if config is None:
            reasons.append(CONFIG_ABSENT)
        return {
            "owned_scope": DECLARED,
            "evidence": NONE,
            "verdict": INCOMPLETE,
            "exit_code": exits.INCOMPLETE,
            "reasons": tuple(reasons),
            "staleness": (),
        }

    recorded = evidence_module.Authority.from_record(stored["authority"])
    staleness = recorded.differences(current)

    if staleness:
        return {
            "owned_scope": CHECKED,
            "evidence": STALE,
            "verdict": INCOMPLETE,
            "exit_code": exits.INCOMPLETE,
            "reasons": staleness,
            "staleness": staleness,
        }

    result = stored.get("result") or {}
    completion = result.get("completion")
    recorded_reasons = tuple(result.get("reasons") or ())

    if completion == "NOT_REVIEWABLE":
        return {
            "owned_scope": CHECKED,
            "evidence": CURRENT,
            "verdict": NOT_REVIEWABLE,
            "exit_code": exits.FAIL,
            "reasons": recorded_reasons,
            "staleness": (),
        }

    if completion == "REVIEWABLE_CANDIDATE":
        # Every pre-commit obligation discharged, and still INCOMPLETE. The
        # missing thing is a bounded commit, and it is named rather than
        # implied.
        return {
            "owned_scope": CHECKED,
            "evidence": CURRENT,
            "verdict": INCOMPLETE,
            "exit_code": exits.INCOMPLETE,
            "reasons": (BOUNDED_COMMIT_NOT_CREATED,),
            "staleness": (),
        }

    return {
        "owned_scope": CHECKED,
        "evidence": CURRENT,
        "verdict": INCOMPLETE,
        "exit_code": exits.INCOMPLETE,
        "reasons": recorded_reasons or (EVIDENCE_NONE,),
        "staleness": (),
    }


# --- The documents ---------------------------------------------------------


def _document(aiqe_version, record, stored, owned_states, state, local):
    """Build the receipt document.

    The default half is assembled first and is a strict subset of the local
    half. That ordering is not stylistic: it means the shareable surface
    cannot acquire a field by accident, because a field only reaches it by
    being written into this function above the `if local` line.
    """
    counts = _counts(stored, owned_states)

    document = {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "redaction_policy": DEFAULT_REDACTION_POLICY,
        "aiqe_version": aiqe_version,
        "command": "receipt",
        "owned_scope": state["owned_scope"],
        "owned_declared_count": len(owned_states),
        "owned_changed_count": sum(1 for entry in owned_states if entry.changed),
        "foreign_staged": OBSERVED,
        "evidence": state["evidence"],
        "commit": NONE,
        "verdict": state["verdict"],
        "reasons": list(state["reasons"]),
        "exit_code": state["exit_code"],
        "classification": counts["classification"],
        "coverage": counts["coverage"],
        "validators": counts["validators"],
    }
    if not local:
        return document

    document["redaction_policy"] = LOCAL_REDACTION_POLICY
    document["local"] = _local_detail(record, stored, owned_states, state)
    return document


def _counts(stored, owned_states):
    """Only counts. Every number here is a count of states, never a name."""
    classification = {
        "quant": 0,
        "non_quant": 0,
        "unclassified": 0,
        "applicable_contracts": 0,
    }
    coverage = {
        classify_module.COVERED: 0,
        classify_module.COVERAGE_GAP: 0,
        classify_module.CONTRACT_FAILED: 0,
        classify_module.CONTRACT_UNKNOWN: 0,
    }
    outcomes = {name: 0 for name in validators_module.OUTCOMES}
    required = {"total": 0, "passed": 0}

    if stored is not None:
        recorded = stored.get("classification") or {}
        classification["quant"] = recorded.get("quant_count", 0)
        classification["non_quant"] = recorded.get("non_quant_count", 0)
        classification["unclassified"] = recorded.get("unclassified_count", 0)
        classification["applicable_contracts"] = len(
            recorded.get("applicable_contracts") or []
        )
        for entry in stored.get("coverage") or []:
            if entry.get("state") in coverage:
                coverage[entry["state"]] += 1
        for entry in stored.get("validators") or []:
            outcome = entry.get("outcome")
            if outcome in outcomes:
                outcomes[outcome] += 1
            if entry.get("required"):
                required["total"] += 1
                if outcome == validators_module.PASS:
                    required["passed"] += 1

    return {
        "classification": classification,
        "coverage": coverage,
        "validators": {
            "applicable_total": sum(outcomes.values()),
            "outcomes": outcomes,
            "required_total": required["total"],
            "required_passed": required["passed"],
        },
    }


def _local_detail(record, stored, owned_states, state):
    """The richer local view. Still bounded, still allowlisted.

    What this adds over the default: task identity, the label the user typed,
    timestamps, the local commit identifiers, the owned pathset, the binding
    per path, and each validator's identity, definition digest, outcome and
    bounded output tail.

    What it still does not contain: the process environment, unbounded output,
    file contents, or anything scraped opportunistically from the repository.
    `--local` is a local terminal surface, not a verbose sharing surface.
    """
    detail = {
        "task_id": record["task_id"],
        "label": display_text(record["label"]) if record.get("label") else None,
        "started_at": record["started_at"],
        "start_head_sha": record["start_head_sha"],
        "owned_pathset_digest": record["owned_pathset_digest"],
        "foreign_staged_count_at_start": record.get(
            "foreign_staged_count_at_start"
        ),
        "owned": [
            {
                "path": display_bytes(entry.path),
                "state": entry.state,
                "content_digest": entry.content_digest,
                "mode": entry.mode,
            }
            for entry in owned_states
        ],
        "staleness": list(state["staleness"]),
        "checked_at": None,
        "config_digest": None,
        "current_head_sha": None,
        "foreign_staged_count": None,
        "applicable_contracts": [],
        "coverage": [],
        "validators": [],
    }
    if stored is None:
        return detail

    authority = stored.get("authority") or {}
    detail["checked_at"] = stored.get("checked_at")
    detail["config_digest"] = authority.get("config_digest")
    detail["current_head_sha"] = authority.get("head_sha")
    detail["foreign_staged_count"] = stored.get("foreign_staged_count")
    detail["applicable_contracts"] = list(
        (stored.get("classification") or {}).get("applicable_contracts") or []
    )
    detail["coverage"] = list(stored.get("coverage") or [])
    detail["validators"] = [
        {
            "validator_id": entry.get("validator_id"),
            "definition_digest": entry.get("definition_digest"),
            "required": entry.get("required"),
            "contracts": entry.get("contracts"),
            "outcome": entry.get("outcome"),
            "reason": entry.get("reason"),
            "exit_code": entry.get("exit_code"),
            "timed_out": entry.get("timed_out"),
            "duration_ms": entry.get("duration_ms"),
            "stdout_tail": entry.get("stdout_tail"),
            "stderr_tail": entry.get("stderr_tail"),
        }
        for entry in stored.get("validators") or []
    ]
    return detail


# --- Rendering -------------------------------------------------------------


def _render_default(document):
    coverage = document["coverage"]
    outcomes = document["validators"]["outcomes"]
    lines = [
        "AIQE RECEIPT",
        "",
        "  Owned scope     %s" % (document["owned_scope"],),
        "  Owned paths     %d declared · %d changed"
        % (document["owned_declared_count"], document["owned_changed_count"]),
        "  Foreign staged  %s" % (document["foreign_staged"],),
        "  Evidence        %s" % (document["evidence"],),
        "  Commit          %s" % (document["commit"],),
        "",
        "  Classification  %d quant · %d non-quant · %d unclassified"
        % (
            document["classification"]["quant"],
            document["classification"]["non_quant"],
            document["classification"]["unclassified"],
        ),
        "  Contracts       %d applicable · %d covered · %d gap · %d failed · "
        "%d unknown"
        % (
            document["classification"]["applicable_contracts"],
            coverage[classify_module.COVERED],
            coverage[classify_module.COVERAGE_GAP],
            coverage[classify_module.CONTRACT_FAILED],
            coverage[classify_module.CONTRACT_UNKNOWN],
        ),
        "  Validators      %d applicable · %d pass · %d fail · %d unknown · "
        "%d unavailable"
        % (
            document["validators"]["applicable_total"],
            outcomes[validators_module.PASS],
            outcomes[validators_module.FAIL],
            outcomes[validators_module.UNKNOWN],
            outcomes[validators_module.UNAVAILABLE],
        ),
        "  Required        %d of them · %d passed"
        % (
            document["validators"]["required_total"],
            document["validators"]["required_passed"],
        ),
        "",
        "  Verdict         %s" % (document["verdict"],),
    ]
    if document["reasons"]:
        lines.append("  Reason          %s" % (" · ".join(document["reasons"]),))
    lines.append("")
    lines.append(
        "  Receipt schema  %d · policy %s"
        % (document["receipt_schema_version"], document["redaction_policy"])
    )
    lines.append("  AIQE            %s" % (document["aiqe_version"],))
    lines.append("")
    return lines


def _render_local(document):
    detail = document["local"]
    lines = _render_default(document)[:-1]
    lines.append("  Local detail    this view is not the shareable receipt")
    lines.append("")
    if detail["label"]:
        lines.append("  Label           %s" % (detail["label"],))
    lines.append("  Task            %s" % (detail["task_id"],))
    lines.append("  Started         %s" % (detail["started_at"],))
    lines.append(
        "  Checked         %s" % (detail["checked_at"] or "not checked",)
    )
    lines.append("  Start HEAD      %s" % (detail["start_head_sha"],))
    if detail["config_digest"]:
        lines.append("  Config digest   %s" % (detail["config_digest"],))
    staged = detail["foreign_staged_count"]
    if staged is not None:
        lines.append("  Foreign staged  %d entries (informational)" % (staged,))

    lines.append("")
    lines.append("  Owned paths")
    for entry in detail["owned"]:
        lines.append("      %-18s %s" % (entry["state"], entry["path"]))

    if detail["coverage"]:
        lines.append("")
        lines.append("  Contracts")
        for entry in detail["coverage"]:
            names = (
                ", ".join(
                    display_text(name)
                    for name in entry.get("required_validators") or []
                )
                or "none"
            )
            lines.append(
                "      %-22s %-14s %s"
                % (display_text(entry["contract"]), entry["state"], names)
            )

    if detail["validators"]:
        lines.append("")
        lines.append("  Validators")
        for entry in detail["validators"]:
            lines.append(
                "      %-22s %-9s %-12s %s"
                % (
                    display_text(entry["validator_id"] or ""),
                    "required" if entry["required"] else "optional",
                    entry["outcome"],
                    entry["reason"] or "",
                )
            )
            for stream in ("stdout_tail", "stderr_tail"):
                if entry.get(stream):
                    for line in entry[stream].split("\n"):
                        lines.append("          " + line)

    if detail["staleness"]:
        lines.append("")
        lines.append("  Stale because   %s" % (" · ".join(detail["staleness"]),))
    lines.append("")
    return lines
