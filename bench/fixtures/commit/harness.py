"""Measurement harness for the BOUNDED_COMMIT family.

The zero this family claims is deliberately not the one Doctor claims, and
saying so precisely is most of the work.

Doctor changes nothing. A task operation changes AIQE's own machine-local
state. `aiqe commit` **creates a commit**, so "the repository did not change"
is not available as a claim and pretending otherwise would be the
overstatement this product exists to refuse. What a completion commit changes
is the index, the object database, HEAD and the reflog, and those are
attributed rather than denied.

What is claimed, and measured here:

```
AIQE_CORE_WORKTREE_MUTATIONS = 0
```

AIQE writes no worktree path. Not a tracked file, not an untracked one, not a
configuration file, not a hook. Every observed change is attributed to exactly
one cause:

```
aiqe_state              AIQE's machine-local XDG state
aiqe_commit_git         the completion commit's own Git writes, under .git
fixture_writes          the scenario's declared actions, such as a commit the
                        fixture makes deliberately after AIQE's
aiqe_core_worktree      everything else - and this must be zero
```

How many writes the second bucket contains is **not** a stable quantity, and
it is recorded as a diagnostic rather than as a result. Several cases race a
concurrent process against AIQE's own window on purpose, and Git legitimately
writes a different number of objects, lock files and reflog entries depending
on how that race lands. Two correct runs of this family differ there: 292 and
295 were observed on one machine minutes apart, from four cases.

What *is* stable, and is therefore what the record carries, is whether the
completion commit wrote through Git at all. That distinguishes a case that
committed from a case that refused, which is the thing the bucket was ever
evidence for. The raw count stays available under `diagnostics`, which no
comparison reads.

The family's other zeros:

```
POLICY_CANARY_EXECUTIONS = 0     no hook, filter driver or signer ever ran
RAW_TERMINAL_CONTROL_BYTES = 0   nothing repository-controlled reached a
                                 terminal unescaped
DEFAULT_RECEIPT_COMMIT_DISCLOSURES = 0
```

Every proof is read back with the harness's own Git invocations - parent,
changed pathset, blob and mode per path, staged delta before and after -
rather than from AIQE's rendering of them. A proof only the product can see is
not a proof.
"""

import json
import os
import shutil
import tempfile

from . import builders
from . import controls
from ..measurement import (  # noqa: F401  (re-exported for the family's users)
    Case,
    compare,
    snapshot,
    wait_until_quiescent,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_FILE = os.path.join(HERE, "cases.json")

#: `linked` is the linked-worktree case's second checkout. It is a repository
#: under measurement in its own right.
REPOSITORY_DIRS = ("repo", "linked")

#: Canary markers that represent repository-defined code AIQE must never run.
#: The validator's own marker is not one of these: it runs, with consent, and
#: that is the check family's business rather than this one's.
POLICY_MARKER_PREFIXES = ("hook.", "filter.", "signer")

XDG_STATE_PREFIX = os.path.join("state", "xdg", "state")

_CHANGE_FIELDS = frozenset({"content", "size", "mode", "mtime"})


def _is_aiqe_state(relative):
    return relative == XDG_STATE_PREFIX or relative.startswith(
        XDG_STATE_PREFIX + os.sep
    )


def _is_git_administrative(relative):
    """Is this path inside a repository's Git directory?

    Both `repo/.git/...` and the linked worktree's `linked/.git` pointer file
    count. A completion commit writes into the Git directory by definition, so
    these changes are the operation working rather than a violation.
    """
    parts = relative.split(os.sep)
    return ".git" in parts


def _relative(change):
    body = change.split(": ", 1)[1]
    if not body.endswith(")"):
        return body
    head, separator, tail = body.rpartition(" (")
    if not separator or not head:
        return body
    inside = tail[:-1]
    if inside == "kind or content" or (
        inside and all(part in _CHANGE_FIELDS for part in inside.split(","))
    ):
        return head
    return body


def _matches(relative, declared):
    for prefix in declared:
        prefix = prefix.replace("/", os.sep)
        if relative == prefix or relative.startswith(prefix + os.sep):
            return True
    return False


def load_cases():
    with open(CASES_FILE) as handle:
        return json.load(handle)


def case_applies(case):
    return builders.platform_supports(case.get("platform"))


def _classify(case, scenario, changes):
    buckets = {
        "aiqe_state": [],
        "aiqe_commit_git": [],
        "fixture": [],
        "aiqe_core_worktree": [],
        "local_state": [],
        "other": [],
    }
    fixture_writes = scenario.get("fixture_writes", ())
    fixture_state_writes = scenario.get("fixture_state_writes", ())

    for change in changes:
        relative = _relative(change)
        if _matches(relative, fixture_state_writes):
            # A scenario that deliberately edits the isolated environment -
            # the fixture's own global Git configuration, say - declares it
            # here, so that the local-state zero keeps meaning "AIQE wrote
            # nothing outside its own state home".
            buckets["fixture"].append(change)
        elif _is_aiqe_state(relative):
            buckets["aiqe_state"].append(change)
        elif case.is_repository_path(relative):
            if _is_git_administrative(relative):
                buckets["aiqe_commit_git"].append(change)
            elif _matches(relative, fixture_writes):
                buckets["fixture"].append(change)
            else:
                buckets["aiqe_core_worktree"].append(change)
        elif case.is_state_path(relative):
            buckets["local_state"].append(change)
        else:
            buckets["other"].append(change)
    return buckets


def run_case(case_id, keep=False):
    """Build one fixture, run the workflow, and measure everything."""
    scenario = builders.SCENARIOS[case_id]
    # Resolved, because on macOS a temporary directory is reached through a
    # symlink and Git reports the resolved worktree root. Left unresolved, a
    # relative `--own` from a subdirectory silently resolves against the
    # worktree root instead - and the subdirectory case would prove nothing.
    root = os.path.realpath(tempfile.mkdtemp(prefix="aiqe-commit-"))
    try:
        case = Case(case_id, root, REPOSITORY_DIRS)
        env = case.env()
        target = scenario["build"](case, env)

        wait_until_quiescent(root, case.canaries)
        before = snapshot(root, case.canaries)
        observation = scenario["operate"](case, env, target)
        after = snapshot(root, case.canaries)

        buckets = _classify(case, scenario, compare(before, after))
        fired = case.fired()
        policy = [
            name
            for name in fired
            if name.startswith(POLICY_MARKER_PREFIXES)
        ]

        record = {
            "case": case_id,
            "aiqe_state_changes": len(buckets["aiqe_state"]),
            # Stable: did the completion commit write through Git at all.
            # The count itself is race-dependent and lives in `diagnostics`.
            "aiqe_commit_git_writes_observed": bool(buckets["aiqe_commit_git"]),
            # Non-authoritative. Nothing compares this, and nothing may start
            # comparing it: see `bench/compare-results.py`.
            "diagnostics": {
                "aiqe_commit_git_writes": len(buckets["aiqe_commit_git"]),
            },
            "aiqe_core_worktree_mutations": len(buckets["aiqe_core_worktree"]),
            "aiqe_core_worktree_mutation_detail": buckets["aiqe_core_worktree"],
            "fixture_repository_mutations": len(buckets["fixture"]),
            "local_state_writes": len(buckets["local_state"]),
            "local_state_write_detail": buckets["local_state"],
            "other_changes": buckets["other"],
            "canaries_fired": sorted(fired),
            "policy_canary_executions": len(policy),
            "policy_canaries": sorted(policy),
            "remotes_configured": _remote_count(target, env),
        }
        # Working values are stripped before the record is retained. The
        # artifact is a public document, and this project's own sanitisation
        # gate refuses commit identifiers in one - including a disposable
        # fixture's, because an exception carved into a gate is a gate with a
        # hole in it.
        record.update(
            {
                key: value
                for key, value in observation.items()
                if not key.startswith("_")
            }
        )
        return record
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def _remote_count(target, env):
    """How many remotes the fixture has. Always zero: nothing to push to.

    Not the push proof - that is the Git allowlist, which contains no network
    subcommand and is asserted directly. This is the belt to that pair of
    braces: a fixture with no remote could not have pushed even if the
    allowlist were wrong.
    """
    root = target["root"] if isinstance(target, dict) else target
    proc = builders._git_bytes(root, "remote", env=env)
    if proc.returncode != 0:
        return None
    return len([line for line in proc.stdout.split(b"\n") if line.strip()])


def check_expectations(observed, expected):
    """Compare one observed result against its recorded expectation."""
    problems = []

    for key, value in expected.items():
        if key in ("description",):
            continue
        actual = observed.get(key)
        if actual != value:
            problems.append("%s: expected %r, observed %r" % (key, value, actual))

    if observed["aiqe_core_worktree_mutations"] != 0:
        problems.append(
            "AIQE core wrote worktree paths: %s"
            % (observed["aiqe_core_worktree_mutation_detail"],)
        )
    if observed["policy_canary_executions"] != 0:
        problems.append(
            "repository-defined commit policy code ran: %s"
            % (observed["policy_canaries"],)
        )
    if observed["local_state_writes"] != 0:
        problems.append(
            "local state writes outside the AIQE state home: %s"
            % (observed["local_state_write_detail"],)
        )
    if observed["other_changes"]:
        problems.append(
            "changes outside the measured tree: %s" % (observed["other_changes"],)
        )
    if observed.get("remotes_configured"):
        problems.append("the fixture acquired a remote")
    if observed.get("receipt_discloses_commit_sha"):
        problems.append("the default receipt disclosed the commit identifier")

    for key, value in sorted(observed.items()):
        if key.endswith("_control_bytes") and value:
            problems.append(
                "%s: %r raw terminal control bytes reached a human surface"
                % (key, value)
            )

    if observed.get("commit_created"):
        if observed.get("parent_is_pre_commit_head") is not True:
            problems.append(
                "the completion commit's parent is not the pre-commit HEAD: %r"
                % (observed.get("commit_parents"),)
            )
        if sorted(observed.get("changed_paths") or []) != sorted(
            observed.get("expected_changed_paths") or []
        ):
            problems.append(
                "the commit changed %r, and the recorded expectation was %r"
                % (observed.get("changed_paths"), observed.get("expected_changed_paths"))
            )

    if observed.get("receipt_verdict") == "REVIEWABLE":
        # The one verdict that has to be earned. Every part of it is checked
        # here from the outside, so a rendering bug cannot produce it.
        if not observed.get("commit_created"):
            problems.append("REVIEWABLE without a commit")
        if observed.get("foreign_staged_preserved") is not True:
            problems.append("REVIEWABLE with foreign staged state not preserved")
        if observed.get("parent_is_pre_commit_head") is not True:
            problems.append("REVIEWABLE with an unexpected parent")
    return problems


def run_control(control_id, keep=False):
    """Build a control's fixture and run the naive workflow against it."""
    control = None
    for candidate in controls.CONTROLS:
        if candidate["id"] == control_id:
            control = candidate
            break
    if control is None:
        raise KeyError(control_id)

    root = os.path.realpath(tempfile.mkdtemp(prefix="aiqe-commit-control-"))
    try:
        case = Case(control["id"], root, REPOSITORY_DIRS)
        env = case.env()
        observation = control["run"](case, env)
        observation["control"] = control_id
        observation["description"] = control["description"]
        observation["invariant"] = control["invariant"]
        observation["control_reproduces_failure"] = controls.violated(
            control, observation
        )
        return observation
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
