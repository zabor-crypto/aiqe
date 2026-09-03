"""`aiqe commit`: one bounded completion commit, and the proof that it is one.

The naive version of this command is three lines - stage the owned paths, run
`git commit`, report success - and every one of the guarantees this product
exists to make is absent from it. What is implemented instead is the smallest
thing that can honestly say `REVIEWABLE`.

The order of operations is the design:

```
 1  the active task, and no completion commit for it yet
 2  current green check evidence, at REVIEWABLE_CANDIDATE
 3  supported topology and operation state
 4  effective Git configuration, includes resolved
 5  commit policy: hooks, signing, external check-in filters
 6  the expected checked-in state of every owned path
 7  the expected parent-to-commit changed pathset
 8  staleness, recomputed immediately before the mutation window
 9  the authoritative foreign staged snapshot
10  transactional intent-to-add
11  the bounded commit
12  HEAD before and HEAD after, not the exit status
13  parent, pathset and content proof
14  the foreign staged snapshot again, against the same baseline
```

Steps 5 and 8 are the two that are easy to leave out.

Step 5 is a refusal, not a workaround. `--no-verify` and `--no-gpg-sign`
would each turn a refusal into a success, and each would mean AIQE had
overridden a policy its user set. AIQE v1 does not run hooks, does not sign
and does not execute check-in filters, and the honest form of that is exit 3.

Step 8 is the canonical check-edit-commit defence. Every expensive thing above
it - resolving configuration, hashing owned content, resolving attributes -
takes time, and an owned file edited during that time would otherwise be
committed with a green check that never saw it. So the bounded authority is
recomputed immediately before the first index mutation, and any drift stops
the operation with nothing written.

**Exit status is never the proof.** `git commit` can fail after creating a
commit and can succeed in ways the caller did not ask for, so what is recorded
is HEAD before and HEAD after, and every claim after that is a comparison
against a tree. If a commit exists and violates the construction, that is
reported - `NOT_REVIEWABLE`, exit 1 - and not concealed by resetting it away.

**AIQE never pushes.** No code path here can: the Git allowlist in `gitwrite`
contains no network subcommand. The receipt says
`Push = NOT_PERFORMED_BY_AIQE`, which is a statement about AIQE and
deliberately not a claim that nobody else pushed.
"""

import time

from . import checkin
from . import commitevidence
from . import commitpolicy
from . import config as config_module
from . import evidence as evidence_module
from . import exits
from . import gitwrite
from . import pathstate
from . import task as task_module
from . import taskstate
from . import validators as validators_module
from .textsafe import display_bytes

# --- Vocabulary ------------------------------------------------------------

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
EXCLUDED = "EXCLUDED"
UNKNOWN = "UNKNOWN"
BOUND = "BOUND"
NOT_BOUND = "NOT_BOUND"
CREATED = "CREATED"
NONE = "NONE"
NOT_PERFORMED_BY_AIQE = "NOT_PERFORMED_BY_AIQE"

REVIEWABLE = "REVIEWABLE"
INCOMPLETE = "INCOMPLETE"
NOT_REVIEWABLE = "NOT_REVIEWABLE"

COMMIT_CREATED = "COMMIT_CREATED"
COMMIT_INCOMPLETE = "COMMIT_INCOMPLETE"
COMMIT_FAILED = "COMMIT_FAILED"

NO_ACTIVE_TASK = "NO_ACTIVE_TASK"
COMPLETION_COMMIT_ALREADY_CREATED = "COMPLETION_COMMIT_ALREADY_CREATED"
CHECK_EVIDENCE_ABSENT = "CHECK_EVIDENCE_ABSENT"
CHECK_NOT_REVIEWABLE_CANDIDATE = "CHECK_NOT_REVIEWABLE_CANDIDATE"
TASK_BASELINE_MOVED = "TASK_BASELINE_MOVED"
NO_OWNED_CHANGES_TO_COMMIT = "NO_OWNED_CHANGES_TO_COMMIT"
ITA_ROLLBACK_INCOMPLETE = "ITA_ROLLBACK_INCOMPLETE"
ITA_FAILED = "ITA_FAILED"
COMMIT_NOT_CREATED = "COMMIT_NOT_CREATED"
POST_COMMIT_PARENT_INVALID = "POST_COMMIT_PARENT_INVALID"
POST_COMMIT_PATHSET_MISMATCH = "POST_COMMIT_PATHSET_MISMATCH"
CHECKED_CONTENT_NOT_BOUND = "CHECKED_CONTENT_NOT_BOUND"
FOREIGN_STAGED_UNKNOWN = "FOREIGN_STAGED_UNKNOWN"
POST_COMMIT_PROOF_UNAVAILABLE = "POST_COMMIT_PROOF_UNAVAILABLE"
UNBORN_HEAD_UNSUPPORTED = "UNBORN_HEAD_UNSUPPORTED"


class CommitOutcome(object):
    """What a commit invocation concluded, and what the process exits with."""

    __slots__ = ("code", "exit_code", "lines")

    def __init__(self, code, exit_code, lines):
        self.code = code
        self.exit_code = exit_code
        self.lines = lines

    def render(self):
        return "\n".join(line.rstrip() for line in self.lines) + "\n"


def _refusal(code, exit_code, lines):
    """Every refusal names itself.

    A refusal that only explains itself in prose is one a script cannot act
    on and a benchmark cannot count, so the machine identity is appended to
    any refusal that has not already rendered one.
    """
    rendered = list(lines)
    if not any(line.strip().startswith("Reason") for line in rendered):
        rendered.append("")
        rendered.append("  Commit          %s" % (NONE,))
        rendered.append("  Reason          %s" % (code,))
    return CommitOutcome(code, exit_code, rendered)


def _policy_refusal(error):
    lines = ["aiqe: " + error.message]
    lines.extend(error.detail)
    lines.append("")
    lines.append("  Commit          %s" % (NONE,))
    lines.append("  Reason          %s" % (error.code,))
    return CommitOutcome(error.code, exits.UNSUPPORTED, lines)


def _state_refusal(error):
    return CommitOutcome(
        error.code,
        exits.UNSUPPORTED,
        [
            "aiqe: " + error.message,
            "AIQE will not repair local state it did not create. Fix or "
            "remove it, then run the commit again.",
        ],
    )


# --- The command -----------------------------------------------------------


def run(cwd, message, env=None):
    """Create one bounded completion commit, or refuse. Never pushes."""
    from . import __version__

    repository, failure = task_module.discover(cwd, env)
    if failure is not None:
        # Discovery reads the user's real configuration, so a `~/.gitconfig`
        # Git cannot parse makes every Git invocation fail - including the one
        # that answers "which repository is this". Reporting that as "no Git
        # repository here" would send the user looking in the wrong place, so
        # the cause is established before the symptom is reported.
        try:
            commitpolicy.resolve_effective_config(
                gitwrite.CommitGitRunner(cwd, env=env)
            )
        except commitpolicy.PolicyRefusal as error:
            return _policy_refusal(error)
        return CommitOutcome(failure.code, failure.exit_code, failure.lines)

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
        return _state_refusal(error)

    if record is None:
        return _refusal(
            NO_ACTIVE_TASK,
            exits.UNSUPPORTED,
            [
                "aiqe: no active task in this worktree.",
                "A completion commit closes a bounded unit of work, so start "
                "one with `aiqe task start --own <path>...` first.",
            ],
        )

    try:
        existing = commitevidence.read(state_directory, record["task_id"])
    except taskstate.StateError as error:
        return _state_refusal(error)
    if existing is not None:
        # One task, one completion commit. A second one would mean the
        # evidence bound to this task described only part of the work, and
        # amending or re-committing to hide that is exactly what this command
        # must not do.
        return _refusal(
            COMPLETION_COMMIT_ALREADY_CREATED,
            exits.UNSUPPORTED,
            [
                "aiqe: this task already has an AIQE completion commit.",
                "A task has one bounded completion commit. Run `aiqe receipt` "
                "to see it, or `aiqe task end` and start a new task for "
                "further work.",
            ],
        )

    if repository.head_state != "commit":
        return _refusal(
            UNBORN_HEAD_UNSUPPORTED,
            exits.UNSUPPORTED,
            ["aiqe: this repository has no commits, so there is no completion "
             "baseline to commit onto."],
        )

    baseline = record["start_head_sha"]
    if repository.head_sha != baseline:
        return _refusal(
            TASK_BASELINE_MOVED,
            exits.INCOMPLETE,
            _stale_lines(
                (TASK_BASELINE_MOVED,),
                "HEAD has moved since this task started, so the commit the "
                "check was taken against is no longer the commit a completion "
                "commit would sit on.",
            ),
        )

    try:
        config = config_module.load(repository.worktree)
    except config_module.ConfigError as error:
        return _refusal(
            error.code, exits.UNSUPPORTED, ["aiqe: " + error.message]
        )

    try:
        stored = evidence_module.read(state_directory, record["task_id"])
    except taskstate.StateError as error:
        return _state_refusal(error)

    if stored is None:
        return _refusal(
            CHECK_EVIDENCE_ABSENT,
            exits.INCOMPLETE,
            [
                "aiqe: there is no current check evidence for this task.",
                "A completion commit consumes a green check; it does not run "
                "one. Run `aiqe check` first.",
            ],
        )

    completion = (stored.get("result") or {}).get("completion")
    if completion != "REVIEWABLE_CANDIDATE":
        return _refusal(
            CHECK_NOT_REVIEWABLE_CANDIDATE,
            exits.INCOMPLETE,
            [
                "aiqe: the current check evidence is %s, not a fully "
                "discharged pre-commit state." % (completion or "absent",),
                "AIQE does not rerun validators here. Run `aiqe check` and "
                "resolve what it reports.",
            ],
        )

    try:
        owned_paths = task_module.decode_owned_paths(record)
        owned_states = pathstate.resolve(
            repository.runner, repository.worktree, owned_paths, baseline
        )
    except pathstate.PathStateError as error:
        return _refusal(
            error.code, exits.UNSUPPORTED, ["aiqe: " + error.message]
        )

    definitions = {
        validator.id: validators_module.definition_digest(validator)
        for validator in config.validators
    }
    recorded = evidence_module.Authority.from_record(stored["authority"])
    drift = recorded.differences(
        evidence_module.Authority(
            repository.head_sha,
            config.digest,
            pathstate.binding_digest(owned_states),
            definitions,
        )
    )
    if drift:
        return _refusal(
            drift[0],
            exits.INCOMPLETE,
            _stale_lines(
                drift,
                "The state the check evidence was taken against has changed, "
                "so committing now would bind a commit to content nothing "
                "checked.",
            ),
        )

    # Rooted at the worktree, not at wherever the user is standing. Owned
    # paths are repository-relative, and a Git pathspec is interpreted relative
    # to the process's working directory - so running from `src/` would make
    # `src/alpha.py` mean `src/src/alpha.py`. Every path this command passes to
    # Git is root-relative, so the process is too.
    runner = gitwrite.CommitGitRunner(repository.worktree, env=env)

    try:
        effective = commitpolicy.resolve_effective_config(runner)
        commitpolicy.require_supported_topology(
            runner, repository.git_dir, effective
        )
        commitpolicy.require_no_active_commit_hook(
            effective, repository.common_dir, repository.worktree
        )
        commitpolicy.require_no_automatic_signing(effective)
        present = [
            state.path
            for state in owned_states
            if state.state
            not in (pathstate.TRACKED_DELETED, pathstate.PENDING_ABSENT)
        ]
        commitpolicy.require_no_external_checkin_filter(
            runner, effective, present
        )
    except commitpolicy.PolicyRefusal as error:
        return _policy_refusal(error)

    preflight = {
        "effective_config": "RESOLVED",
        "active_commit_hook": "NONE",
        "commit_signing": "NOT_REQUIRED",
        "external_checkin_filter": "NONE",
        "file_mode_significant": checkin.file_mode_is_significant(effective),
    }

    try:
        expected = checkin.expected_states(
            runner, effective, repository.worktree, baseline, owned_states
        )
    except checkin.CheckinError as error:
        return _refusal(
            error.code, exits.INCOMPLETE, ["aiqe: " + error.message]
        )

    expected_changed = checkin.changed_paths(expected)
    if not expected_changed:
        # No `--allow-empty`. A commit that records nothing is not a bounded
        # completion commit; it is a marker pretending to be one.
        return _refusal(
            NO_OWNED_CHANGES_TO_COMMIT,
            exits.INCOMPLETE,
            [
                "AIQE COMMIT",
                "",
                "  Under the supported Git check-in semantics, none of this "
                "task's owned",
                "  paths would change the tree. AIQE does not create an empty "
                "completion",
                "  commit.",
                "",
                "  Commit          %s" % (NONE,),
                "  Verdict         %s" % (INCOMPLETE,),
                "  Reason          %s" % (NO_OWNED_CHANGES_TO_COMMIT,),
                "",
            ],
        )

    # --- The mutation window ------------------------------------------------
    #
    # Everything expensive is behind us, and everything below writes. The
    # authority is recomputed once more here, as close to the first index
    # mutation as it can be, because the gap between "checked" and "committed"
    # is the whole staleness attack surface.
    late = _late_drift(
        repository, config, owned_paths, baseline, definitions, recorded
    )
    if late:
        return _refusal(
            late[0],
            exits.INCOMPLETE,
            _stale_lines(
                late,
                "The state the check evidence was taken against changed while "
                "AIQE was preparing the commit. Nothing was written.",
            ),
        )

    try:
        foreign_pre = checkin.foreign_staged_delta(runner, baseline, owned_paths)
    except checkin.CheckinError as error:
        return _refusal(
            error.code, exits.INCOMPLETE, ["aiqe: " + error.message]
        )

    # Only the paths this commit will actually name. `git commit --only`
    # refuses a pathspec Git has never heard of, so a new file needs an index
    # entry - but an owned path that is *not* in the expected changed pathset
    # is not going to be named, and creating an index entry for it would leave
    # AIQE's own residue behind on a path it did not commit.
    changed = set(expected_changed)
    index = checkin.index_entries(runner, list(expected_changed))
    needs_ita = [
        entry.path
        for entry in expected
        if entry.kind == checkin.REGULAR
        and entry.path in changed
        and entry.path not in index
    ]

    created_ita = []
    for path in needs_ita:
        result = runner.run("add", "-N", "--", path)
        if result.ok:
            created_ita.append(path)
            continue
        return _rollback_outcome(
            runner,
            created_ita,
            ITA_FAILED,
            "an owned path could not be marked for addition, so no completion "
            "commit was attempted.",
            _git_lines(result),
        )

    head_before = _head(runner)
    commit_result = runner.run(
        "commit", "--only", "-m", message, "--", *expected_changed
    )
    head_after = _head(runner)

    if head_after is None or head_after == head_before:
        # No commit exists. The index is put back exactly as far as AIQE
        # moved it - and no further, because restoring a saved index file
        # would overwrite whatever a concurrent process staged.
        return _rollback_outcome(
            runner,
            created_ita,
            COMMIT_NOT_CREATED,
            "Git created no completion commit.",
            _git_lines(commit_result),
        )

    # A commit exists. From here on nothing is rolled back and nothing is
    # rewritten: the truth about what was created outranks the tidiness of
    # the index.
    try:
        proof = _prove(
            runner, baseline, head_after, expected, expected_changed,
            owned_paths, foreign_pre,
        )
    except checkin.CheckinError as error:
        return _refusal(
            POST_COMMIT_PROOF_UNAVAILABLE,
            exits.INCOMPLETE,
            [
                "aiqe: a completion commit was created, but its proof could "
                "not be read: " + error.message,
                "The commit exists. AIQE will not claim it is reviewable.",
            ],
        )

    state = _adjudicate(proof)
    result = {
        "owned_scope": state["owned_scope"],
        "foreign_staged": state["foreign_staged"],
        "checked_content": state["checked_content"],
        "commit": CREATED,
        "push": NOT_PERFORMED_BY_AIQE,
        "verdict": state["verdict"],
        "exit_code": state["exit_code"],
        "reasons": list(state["reasons"]),
    }

    try:
        commitevidence.write(
            state_directory,
            commitevidence.build_record(
                record,
                __version__,
                baseline,
                head_after,
                expected,
                expected_changed,
                proof["actual_changed"],
                proof["committed"],
                foreign_pre,
                proof["foreign_post"],
                preflight,
                result,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
    except taskstate.StateError as error:
        return _state_refusal(error)

    return CommitOutcome(
        _code_for(state["exit_code"]),
        state["exit_code"],
        _render(expected_changed, proof, state),
    )


# --- Staleness -------------------------------------------------------------


def _late_drift(repository, config, owned_paths, baseline, definitions, recorded):
    """Recompute the bounded authority immediately before the first mutation."""
    resolved = repository.runner.run("rev-parse", "--verify", "--quiet", "HEAD")
    head = None
    if resolved.ok and resolved.lines():
        head = resolved.lines()[0].decode("ascii", "replace").strip()

    try:
        digest = config_module.digest_bytes(
            config_module.read_raw(repository.worktree)
        )
    except config_module.ConfigError:
        digest = None

    try:
        states = pathstate.resolve(
            repository.runner, repository.worktree, owned_paths, baseline
        )
        binding = pathstate.binding_digest(states)
    except pathstate.PathStateError:
        binding = None

    return recorded.differences(
        evidence_module.Authority(head, digest, binding, definitions)
    )


def _stale_lines(reasons, explanation):
    lines = ["AIQE COMMIT", ""]
    for chunk in _wrap(explanation):
        lines.append("  " + chunk)
    lines.append("")
    lines.append("  Commit          %s" % (NONE,))
    lines.append("  Index           unchanged")
    lines.append("  Verdict         %s" % (INCOMPLETE,))
    lines.append("  Reason          %s" % (" · ".join(reasons),))
    lines.append("")
    lines.append("  AIQE does not rerun validators here. Run `aiqe check` "
                 "again.")
    lines.append("")
    return lines


def _wrap(text, width=68):
    words = text.split()
    out = []
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = word if not line else line + " " + word
    if line:
        out.append(line)
    return out


# --- Intent-to-add ---------------------------------------------------------


def _rollback_outcome(runner, created_ita, code, message, detail):
    """Undo exactly the index entries AIQE created, and prove it.

    Scope rollback, one path at a time. A whole-index restore would be
    simpler and would also silently discard anything a concurrent process
    staged while AIQE was working - trading a small failure for a large one.
    """
    residue = []
    for path in created_ita:
        removal = runner.run("update-index", "--force-remove", "--", path)
        if not removal.ok:
            residue.append(path)
    if created_ita:
        remaining = checkin.index_entries(runner, created_ita)
        for path in created_ita:
            if path in remaining and path not in residue:
                residue.append(path)

    if residue:
        lines = [
            "aiqe: %s" % (message,),
            "AIQE could not fully undo the index entries it created, so it "
            "will not claim the index is as it found it.",
        ]
        lines.extend("  " + display_bytes(path) for path in residue)
        lines.append("")
        lines.append("  Commit          %s" % (NONE,))
        lines.append("  Verdict         %s" % (INCOMPLETE,))
        lines.append("  Reason          %s" % (ITA_ROLLBACK_INCOMPLETE,))
        return CommitOutcome(ITA_ROLLBACK_INCOMPLETE, exits.INCOMPLETE, lines)

    lines = ["aiqe: %s" % (message,)]
    lines.extend(detail)
    lines.append("")
    lines.append("  Commit          %s" % (NONE,))
    lines.append("  Index           restored to its pre-commit state")
    lines.append("  Verdict         %s" % (INCOMPLETE,))
    lines.append("  Reason          %s" % (code,))
    return CommitOutcome(code, exits.INCOMPLETE, lines)


def _git_lines(result):
    text = result.stderr.decode("utf-8", "replace").strip()
    if not text:
        return ()
    from .textsafe import display_text

    return tuple("  " + display_text(line) for line in text.split("\n")[:6])


def _head(runner):
    result = runner.run("rev-parse", "--verify", "--quiet", "HEAD")
    if not result.ok or not result.lines():
        return None
    return result.lines()[0].decode("ascii", "replace").strip()


# --- Post-commit proof -----------------------------------------------------


def _prove(runner, parent, commit, expected, expected_changed, owned_paths,
           foreign_pre):
    """Everything that has to be true of a bounded completion commit."""
    parents = checkin.parents(runner, commit)
    delta = checkin.commit_changed_delta(runner, parent, commit)
    actual_changed = tuple(sorted(delta))
    committed = checkin.committed_states(
        runner, commit, [entry.path for entry in expected]
    )
    foreign_post = checkin.foreign_staged_delta(runner, parent, owned_paths)

    content_mismatch = []
    for entry in expected:
        kind, blob, mode = committed[entry.path]
        if not entry.matches(kind, blob, mode):
            content_mismatch.append(entry.path)

    return {
        "parents": parents,
        "parent_ok": len(parents) == 1 and parents[0] == parent,
        "actual_changed": actual_changed,
        "expected_changed": tuple(sorted(expected_changed)),
        "pathset_ok": tuple(sorted(actual_changed)) == tuple(sorted(expected_changed)),
        "unexpected_paths": tuple(
            sorted(set(actual_changed) - set(expected_changed))
        ),
        "missing_paths": tuple(
            sorted(set(expected_changed) - set(actual_changed))
        ),
        "committed": committed,
        "content_ok": not content_mismatch,
        "content_mismatch": tuple(content_mismatch),
        "foreign_post": foreign_post,
        # Any difference at all, in either direction. A foreign path that
        # appeared between the two snapshots counts: "it was not there before"
        # is not a reason to discard it, because the claim being made is that
        # the staged state AIQE did not own came through the commit unchanged.
        "foreign_preserved": checkin.delta_digest(foreign_pre)
        == checkin.delta_digest(foreign_post),
    }


def _adjudicate(proof):
    """Turn the proof into the vocabulary the receipt shares."""
    reasons = []
    if not proof["parent_ok"]:
        reasons.append(POST_COMMIT_PARENT_INVALID)
    if not proof["pathset_ok"]:
        reasons.append(POST_COMMIT_PATHSET_MISMATCH)
    if not proof["content_ok"]:
        reasons.append(CHECKED_CONTENT_NOT_BOUND)

    scope_ok = proof["parent_ok"] and proof["pathset_ok"]
    if reasons:
        # A proved construction defect outranks an unknown. Both are often
        # true at once, and reporting the softer of the two would be the wrong
        # round-off in the one direction that matters.
        return {
            "owned_scope": VERIFIED if scope_ok else UNVERIFIED,
            "foreign_staged": UNKNOWN,
            "checked_content": BOUND if proof["content_ok"] else NOT_BOUND,
            "verdict": NOT_REVIEWABLE,
            "exit_code": exits.FAIL,
            "reasons": tuple(reasons),
        }

    if not proof["foreign_preserved"]:
        # The owned scope is verified and the content is bound, and AIQE still
        # cannot say `EXCLUDED`: the staged state it did not own is not what it
        # was. AIQE does not claim it caused the drift, and does not claim it
        # did not.
        return {
            "owned_scope": VERIFIED,
            "foreign_staged": UNKNOWN,
            "checked_content": BOUND,
            "verdict": INCOMPLETE,
            "exit_code": exits.INCOMPLETE,
            "reasons": (FOREIGN_STAGED_UNKNOWN,),
        }

    return {
        "owned_scope": VERIFIED,
        "foreign_staged": EXCLUDED,
        "checked_content": BOUND,
        "verdict": REVIEWABLE,
        "exit_code": exits.OK,
        "reasons": (),
    }


def _code_for(exit_code):
    if exit_code == exits.OK:
        return COMMIT_CREATED
    if exit_code == exits.FAIL:
        return COMMIT_FAILED
    return COMMIT_INCOMPLETE


# --- Rendering -------------------------------------------------------------


def _render(expected_changed, proof, state):
    lines = ["AIQE COMMIT", ""]
    lines.append("  Owned scope     %s" % (state["owned_scope"],))
    lines.append("  Committed paths %d" % (len(expected_changed),))
    lines.append("  Foreign staged  %s" % (state["foreign_staged"],))
    lines.append("  Checked content %s" % (state["checked_content"],))
    lines.append("  Commit          %s" % (CREATED,))
    lines.append("  Push            %s" % (NOT_PERFORMED_BY_AIQE,))
    lines.append("")
    if proof["unexpected_paths"]:
        lines.append("  Paths the commit changed that the task did not own:")
        for path in proof["unexpected_paths"]:
            lines.append("      %s" % (display_bytes(path),))
        lines.append("")
    if proof["missing_paths"]:
        lines.append("  Owned paths the commit was expected to change and did "
                     "not:")
        for path in proof["missing_paths"]:
            lines.append("      %s" % (display_bytes(path),))
        lines.append("")
    if proof["content_mismatch"]:
        lines.append("  Owned paths whose committed content is not the checked "
                     "content:")
        for path in proof["content_mismatch"]:
            lines.append("      %s" % (display_bytes(path),))
        lines.append("")
    if not proof["foreign_preserved"]:
        lines.append("  The staged state AIQE does not own is not what it was "
                     "immediately")
        lines.append("  before the commit. AIQE cannot prove it was excluded, "
                     "and does not")
        lines.append("  claim it caused the change.")
        lines.append("")
    lines.append("  Verdict         %s" % (state["verdict"],))
    if state["reasons"]:
        lines.append("  Reasons         %s" % (" · ".join(state["reasons"]),))
    lines.append("")
    if state["verdict"] == REVIEWABLE:
        lines.append("  The commit contains exactly the owned changed pathset, "
                     "its content is")
        lines.append("  the checked content, and the staged work AIQE did not "
                     "own is unchanged.")
        lines.append("  See `aiqe receipt`.")
    elif state["verdict"] == INCOMPLETE:
        lines.append("  The commit itself is exactly what was expected. What "
                     "AIQE cannot")
        lines.append("  establish is that the staged work it does not own came "
                     "through")
        lines.append("  unchanged, so it does not say it did.")
    else:
        lines.append("  The commit exists. AIQE has not rewritten it, and will "
                     "not: an")
        lines.append("  incorrect commit that is reported is better than one "
                     "that is hidden.")
    lines.append("")
    return lines
