"""Measurement harness for the check, evidence and receipt family.

This family's safety claim is narrower than Doctor's and narrower than the
task boundary's, and stating it precisely is most of the work.

Doctor changes nothing. A task operation changes AIQE's own machine-local
state and nothing else. `aiqe check` runs code the repository declared, and
that code can do whatever the user's shell can do - so "the repository did not
change" is simply not available as a claim, and pretending otherwise would be
the overstatement this product exists to refuse.

What is claimed, and measured here:

    AIQE_CORE_REPOSITORY_WRITES = 0

AIQE core writes no repository path. `aiqe init` writing `./aiqe.toml` after
explicit confirmation is the single authorised exception, and it is attributed
separately rather than folded into the zero.

Every repository change observed in a case is attributed to exactly one cause:

    aiqe_init_writes          ./aiqe.toml, from an authorised `aiqe init`
    validator_writes          a fixture validator's declared side effects
    fixture_writes            the scenario's own declared actions, such as a
                              commit made deliberately after a check
    aiqe_core                 everything else - and this must be zero

The attribution lists are declared per scenario, in the builders, so they are
reviewable: a case cannot quietly acquire permission to write by writing
somewhere new.

    UNCONSENTED_VALIDATOR_EXECUTIONS = 0

is the family's other zero. Every fixture validator records the fact that it
ran, in a directory outside every snapshot root, so this is counted rather
than argued: any validator that fired without either `--allow` or a recorded
consent is a violation.
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

REPOSITORY_DIRS = ("repo",)

#: A canary whose name starts with this is an *observation*, not a validator
#: execution. One scenario proves that a detached descendant survives the
#: process-group kill, and the marker it leaves is the evidence for that claim -
#: counting it as an unconsented validator execution would turn a deliberate,
#: documented observation into a zero-tolerance violation.
OBSERVATION_MARKER_PREFIX = "observed."

#: The isolated XDG state home, relative to the case root: the only place AIQE
#: core may write outside an authorised `aiqe init`.
XDG_STATE_PREFIX = os.path.join("state", "xdg", "state")


def _is_aiqe_state(relative):
    return relative == XDG_STATE_PREFIX or relative.startswith(
        XDG_STATE_PREFIX + os.sep
    )


#: The annotations `measurement.compare` appends to a changed path. They have
#: to come off before a path can be attributed, and stripping them by pattern
#: rather than by "everything after the last bracket" means a filename that
#: legitimately ends in a bracket is still attributed correctly.
_CHANGE_FIELDS = frozenset({"content", "size", "mode", "mtime"})


def _relative(change):
    """The repository-relative path a change line refers to."""
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
    """Is this change inside a declared attribution path?

    A prefix match, so that declaring `repo/.git` covers the whole directory a
    commit rewrites. The lists are short, explicit, and per scenario.
    """
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
    """Attribute every observed change to exactly one cause."""
    buckets = {
        "aiqe_state": [],
        "aiqe_init": [],
        "validator": [],
        "fixture": [],
        "aiqe_core_repository": [],
        "local_state": [],
        "other": [],
    }
    init_writes = scenario.get("aiqe_init_writes", ())
    validator_writes = scenario.get("validator_writes", ())
    fixture_writes = scenario.get("fixture_writes", ())

    for change in changes:
        relative = _relative(change)
        if _is_aiqe_state(relative):
            buckets["aiqe_state"].append(change)
        elif case.is_repository_path(relative):
            if _matches(relative, init_writes):
                buckets["aiqe_init"].append(change)
            elif _matches(relative, validator_writes):
                buckets["validator"].append(change)
            elif _matches(relative, fixture_writes):
                buckets["fixture"].append(change)
            else:
                buckets["aiqe_core_repository"].append(change)
        elif case.is_state_path(relative):
            buckets["local_state"].append(change)
        else:
            buckets["other"].append(change)
    return buckets


def run_case(case_id, keep=False):
    """Build one fixture, run the workflow, and measure everything."""
    scenario = builders.SCENARIOS[case_id]
    root = tempfile.mkdtemp(prefix="aiqe-check-")
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
        observations = [
            name for name in fired if name.startswith(OBSERVATION_MARKER_PREFIX)
        ]
        validator_canaries = [
            name for name in fired if not name.startswith(OBSERVATION_MARKER_PREFIX)
        ]
        consented = set(observation.get("consented") or [])
        unconsented = sorted(
            name for name in validator_canaries if name not in consented
        )

        record = {
            "case": case_id,
            "observation_markers": sorted(observations),
            "aiqe_state_changes": len(buckets["aiqe_state"]),
            "aiqe_init_writes": sorted(buckets["aiqe_init"]),
            "aiqe_core_repository_mutations": len(buckets["aiqe_core_repository"]),
            "aiqe_core_repository_mutation_detail": buckets["aiqe_core_repository"],
            "validator_repository_mutations": len(buckets["validator"]),
            "fixture_repository_mutations": len(buckets["fixture"]),
            "local_state_writes": len(buckets["local_state"]),
            "local_state_write_detail": buckets["local_state"],
            "other_changes": buckets["other"],
            "validators_fired": sorted(validator_canaries),
            "unconsented_validator_executions": len(unconsented),
            "unconsented_validators": unconsented,
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

    if observed["aiqe_core_repository_mutations"] != 0:
        problems.append(
            "AIQE core wrote repository paths: %s"
            % (observed["aiqe_core_repository_mutation_detail"],)
        )
    if observed["unconsented_validator_executions"] != 0:
        problems.append(
            "validators ran without consent: %s" % (observed["unconsented_validators"],)
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
    if observed.get("default_receipt_leaks"):
        problems.append(
            "the default receipt disclosed: %s" % (observed["default_receipt_leaks"],)
        )
    if observed.get("receipt_verdict") == "REVIEWABLE":
        problems.append(
            "a pre-commit receipt returned REVIEWABLE, which no pre-commit "
            "state may reach"
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

    root = tempfile.mkdtemp(prefix="aiqe-check-control-")
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
