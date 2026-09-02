"""Measurement harness for the Task benchmark family.

Doctor's contract is that it changes nothing. A task operation's contract is
narrower and therefore needs a different measurement: it may change AIQE's own
private state, and nothing else. That claim has a name:

    TASK_WRITE_CONFINEMENT

and it is scoped deliberately. It says AIQE's own writes stay inside its
machine-local state home, `$XDG_STATE_HOME/aiqe/`. It does not say the
repository cannot change while AIQE runs - another process can do as it likes
- which is why fixtures are quiescent before they are measured.

Since task state moved out of Git metadata, the repository figure covers the
Git directory too: a task operation now changes nothing at all inside the
repository, including `.git`.

Four quantities come out of each case:

    aiqe_state_changes            changes in the machine-local state home,
                                  the only permitted write surface
    repository_mutations          changes anywhere in the repository, .git
                                  included
    local_state_writes            changes elsewhere under the isolated HOME
                                  and XDG tree
    repository_defined_executions canaries the repository installed that fired

Only the first may be non-zero.

Task operations run as real subprocesses through the installed entry point.
Concurrency, crash-atomicity and byte-preserving argv cannot be measured any
other way, and using the same path for every case means no case is proven
against a shortcut the user does not take.
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
#: Repository directories a task case may create under its case root.
REPOSITORY_DIRS = ("repo", "worktree-a", "worktree-b")

#: Where the isolated XDG state home lives, relative to the case root. This
#: mirrors what `measurement.Case.env` sets, and is the only place a task
#: operation may write.
XDG_STATE_PREFIX = os.path.join("state", "xdg", "state")


def _is_aiqe_state(relative):
    """Is this path inside the isolated XDG state home?

    Task state is machine-local now, so this is the whole permitted write
    surface. Anything under the isolated HOME or the other XDG directories is
    not: AIQE writes to its state home and nowhere else.
    """
    return relative == XDG_STATE_PREFIX or relative.startswith(
        XDG_STATE_PREFIX + os.sep
    )

def load_cases():
    with open(CASES_FILE) as handle:
        return json.load(handle)


def case_applies(case):
    return builders.platform_supports(case.get("platform"))


def _classify(case, changes):
    """Split observed changes into what is allowed and what is not."""
    allowed = []
    repository = []
    state = []
    other = []
    for change in changes:
        relative = change.split(": ", 1)[1]
        if _is_aiqe_state(relative):
            allowed.append(change)
        elif case.is_repository_path(relative):
            repository.append(change)
        elif case.is_state_path(relative):
            state.append(change)
        else:
            other.append(change)
    return allowed, repository, state, other


def run_case(case_id, keep=False):
    """Build one fixture, run its task operations, and measure everything."""
    scenario = builders.SCENARIOS[case_id]
    root = tempfile.mkdtemp(prefix="aiqe-task-")
    try:
        case = Case(case_id, root, REPOSITORY_DIRS)
        env = case.env()
        target = scenario["build"](case, env)

        wait_until_quiescent(root, case.canaries)
        before = snapshot(root, case.canaries)
        observation = scenario["operate"](case, env, target)
        after = snapshot(root, case.canaries)

        changes = compare(before, after)
        allowed, repository, state, other = _classify(case, changes)

        record = {
            "case": case_id,
            "aiqe_state_changes": len(allowed),
            "repository_mutations": len(repository),
            "repository_mutation_detail": repository,
            "local_state_writes": len(state),
            "local_state_write_detail": state,
            "other_changes": other,
            "repository_defined_executions": len(case.fired()),
            "fired_canaries": case.fired(),
        }
        record.update(observation)
        return record
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def check_expectations(observed, expected):
    """Compare one observed result against its recorded expectation."""
    problems = []

    for key, value in expected.items():
        if key in ("description",):
            continue
        actual = observed.get(key)
        if actual != value:
            problems.append("%s: expected %r, observed %r" % (key, value, actual))

    if observed["repository_mutations"] != 0:
        problems.append(
            "repository mutations outside AIQE state: %s"
            % (observed["repository_mutation_detail"],)
        )
    if observed["local_state_writes"] != 0:
        problems.append(
            "local state writes: %s" % (observed["local_state_write_detail"],)
        )
    if observed["other_changes"]:
        problems.append("changes outside the measured tree: %s" % (observed["other_changes"],))
    if observed["repository_defined_executions"] != 0:
        problems.append(
            "repository-defined executions: %s" % (observed["fired_canaries"],)
        )
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

    root = tempfile.mkdtemp(prefix="aiqe-task-control-")
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
