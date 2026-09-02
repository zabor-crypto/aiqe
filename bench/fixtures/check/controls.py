"""Negative controls for the check, evidence and receipt family.

Each control is a reference naive implementation: the obvious way to build the
same feature, written the way a reasonable engineer would write it in an
afternoon. Each one produces a green result that is not justified, and the
harness records whether the failure actually reproduced this time.

A control that stops reproducing is not good news. It means the control has
decayed and must be redesigned, which is why `control_reproduces_failure` is
measured per control rather than assumed.

The four here are the reasons for the four decisions that cost the most to
implement:

    check-then-edit        -> why evidence binds owned content, and why a
                              receipt recomputes that binding instead of
                              trusting a stored verdict
    generic tests only     -> why an applicable contract with zero required
                              validators is a COVERAGE_GAP rather than a pass
    declared-is-authorised -> why executing a validator needs machine-local
                              consent, per definition digest
    self-editing validator -> why bounded authority is measured on both sides
                              of validator execution
"""

import json
import os
import subprocess
import tomllib

from ..repobuild import write
from . import builders

CHECK_THEN_EDIT = "check_then_edit"
GENERIC_TESTS_ONLY = "generic_tests_only"
DECLARED_IS_AUTHORISED = "declared_is_authorised"
SELF_EDITING_VALIDATOR = "self_editing_validator"

OWNED_RELATIVE = os.path.join("src", "strategy", "alpha.py")


def _declared_validators(root):
    """Read the validator argument vectors the way a naive tool would."""
    with open(os.path.join(root, "aiqe.toml"), "rb") as handle:
        document = tomllib.load(handle)
    return [entry["run"] for entry in document.get("validator", [])]


def _naive_run_all(root, env):
    """Run every declared validator. No consent, no binding, no timeout.

    This is the shape almost every "run the project's checks" feature has, and
    every line of it is defensible in isolation.
    """
    outcomes = []
    for argv in _declared_validators(root):
        completed = subprocess.run(
            argv,
            cwd=root,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        outcomes.append(completed.returncode)
    return outcomes


def _aiqe_check(root, env, allow=()):
    arguments = [b"check", b"--format", b"json"]
    for identifier in allow:
        arguments.extend([b"--allow", identifier.encode("ascii")])
    completed = builders.run_cli(root, env, *arguments)
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        document = {}
    return completed.returncode, document


def _aiqe_receipt(root, env):
    completed = builders.run_cli(root, env, b"receipt", b"--format", b"json")
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        document = {}
    return completed.returncode, document


# --- NC-CHECK-STALENESS ----------------------------------------------------


def run_check_then_edit(case, env):
    """The check-then-edit window: a passing result that outlives its subject.

    The naive tool records that the checks passed. Then the file changes. The
    naive tool has nothing to compare against, so its recorded result is still
    green - and it is green about bytes that no longer exist anywhere.
    """
    config = builders.config(
        [
            builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
            builders.NON_QUANT,
            builders.validator(
                "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
            ),
        ]
    )
    root = builders.build_repository(
        case, env, config, [builders.script("causality")]
    )

    # The naive workflow: run the checks, write down that they passed.
    naive_outcomes = _naive_run_all(root, env)
    naive_record = os.path.join(case.root, "naive-result.json")
    with open(naive_record, "w") as handle:
        json.dump({"green": all(code == 0 for code in naive_outcomes)}, handle)

    # And the product, on the same repository.
    builders.run_cli(root, env, b"task", b"start", b"--own", builders.OWNED)
    checked_exit, checked = _aiqe_check(root, env, allow=("causality",))

    # The edit that happens after every check, in every real workflow.
    write(os.path.join(root, OWNED_RELATIVE), "SIGNAL = 1\nEDITED_AFTER_CHECK = 1\n")

    with open(naive_record) as handle:
        naive_still_green = json.load(handle)["green"]
    receipt_exit, receipt = _aiqe_receipt(root, env)
    builders.run_cli(root, env, b"task", b"end")

    return {
        "naive_still_reports_green": naive_still_green,
        "aiqe_check_exit": checked_exit,
        "aiqe_check_completion": (checked.get("result") or {}).get("completion"),
        "aiqe_receipt_exit": receipt_exit,
        "aiqe_receipt_evidence": receipt.get("evidence"),
        "aiqe_receipt_verdict": receipt.get("verdict"),
        "aiqe_receipt_reasons": sorted(receipt.get("reasons") or []),
    }


# --- NC-MISSING-QUANT-VALIDATOR --------------------------------------------


def run_generic_tests_only(case, env):
    """Green generic tests over a quant surface nothing is required to check.

    The repository declares that `src/strategy/**` carries CAUSALITY. It has a
    unit suite, and the unit suite passes. Every tool in the ecosystem calls
    that green. Nothing in the repository was ever written to detect a
    lookahead defect, so the correct answer is that the contract is unmeasured.
    """
    config = builders.config(
        [
            builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
            builders.NON_QUANT,
            builders.validator("unit", ["./checks/unit.sh"], True, 60),
        ]
    )
    root = builders.build_repository(case, env, config, [builders.script("unit")])

    naive_outcomes = _naive_run_all(root, env)

    builders.run_cli(root, env, b"task", b"start", b"--own", builders.OWNED)
    checked_exit, checked = _aiqe_check(root, env, allow=("unit",))
    receipt_exit, receipt = _aiqe_receipt(root, env)
    builders.run_cli(root, env, b"task", b"end")

    coverage = {
        entry["contract"]: entry["state"] for entry in checked.get("coverage") or []
    }
    return {
        "naive_all_validators_passed": all(code == 0 for code in naive_outcomes),
        "naive_reports_green": all(code == 0 for code in naive_outcomes),
        "aiqe_check_exit": checked_exit,
        "aiqe_coverage": coverage,
        "aiqe_receipt_exit": receipt_exit,
        "aiqe_receipt_verdict": receipt.get("verdict"),
    }


# --- NC-CONSENT ------------------------------------------------------------


def run_declared_is_authorised(case, env):
    """Tracked configuration treated as authorization to execute.

    Anyone who can land a commit can add a `[[validator]]` block naming any
    command on the machine. The naive tool reads the file and runs it, because
    that is what the file is for. AIQE treats the declaration as a proposal
    and executes nothing without machine-local consent for that exact
    definition.
    """
    config = builders.config(
        [
            builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
            builders.NON_QUANT,
            builders.validator(
                "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
            ),
        ]
    )
    root = builders.build_repository(
        case, env, config, [builders.script("causality")]
    )

    _naive_run_all(root, env)
    naive_executed = "causality" in case.fired()

    # Clear the evidence of the naive run so the product's turn is measured on
    # its own. The marker is the observation, so it has to start empty.
    os.unlink(case.marker("causality"))

    builders.run_cli(root, env, b"task", b"start", b"--own", builders.OWNED)
    checked_exit, checked = _aiqe_check(root, env)
    aiqe_executed = "causality" in case.fired()
    builders.run_cli(root, env, b"task", b"end")

    outcomes = {
        entry["validator_id"]: entry["outcome"]
        for entry in checked.get("validators") or []
    }
    reasons = {
        entry["validator_id"]: entry.get("reason")
        for entry in checked.get("validators") or []
    }
    return {
        "naive_executed_declared_command": naive_executed,
        "aiqe_executed_declared_command": aiqe_executed,
        "aiqe_check_exit": checked_exit,
        "aiqe_outcomes": outcomes,
        "aiqe_reasons": reasons,
    }


# --- NC-VALIDATOR-MUTATES-OWNED --------------------------------------------


def run_self_editing_validator(case, env):
    """A validator that edits the file it checks, and then exits 0.

    Nothing about this is exotic: a formatter, a code generator, or a test
    that writes a fixture back to disk all do it. The naive tool records the
    exit status and calls the result current, so it is now green about source
    that no longer exists. AIQE measures the owned binding on both sides of
    execution and refuses to call the result current.
    """
    config = builders.config(
        [
            builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
            builders.NON_QUANT,
            builders.validator(
                "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
            ),
        ]
    )
    root = builders.build_repository(
        case,
        env,
        config,
        [
            builders.script(
                "causality",
                body="echo 'rewritten by the validator' >> %s\nexit 0" % (OWNED_RELATIVE,),
            )
        ],
    )

    owned = os.path.join(root, OWNED_RELATIVE)
    with open(owned) as handle:
        before = handle.read()
    naive_outcomes = _naive_run_all(root, env)
    with open(owned) as handle:
        after = handle.read()
    naive_green_and_current = all(code == 0 for code in naive_outcomes)

    builders.run_cli(root, env, b"task", b"start", b"--own", builders.OWNED)
    checked_exit, checked = _aiqe_check(root, env, allow=("causality",))
    receipt_exit, receipt = _aiqe_receipt(root, env)
    builders.run_cli(root, env, b"task", b"end")

    return {
        "validator_changed_the_file_it_checked": before != after,
        "naive_reports_green_and_current": naive_green_and_current,
        "aiqe_check_exit": checked_exit,
        "aiqe_check_reason": (checked.get("result") or {}).get("completion")
        or checked.get("reason"),
        "aiqe_receipt_exit": receipt_exit,
        "aiqe_receipt_evidence": receipt.get("evidence"),
        "aiqe_receipt_verdict": receipt.get("verdict"),
    }


CONTROLS = [
    {
        "id": "NC_CHECK_STALENESS",
        "description": (
            "Check, then edit. The naive tool records that the validators "
            "passed and has nothing to compare against afterwards, so its "
            "green result survives an edit to the very file it was about. "
            "AIQE binds the owned content at check time and recomputes it at "
            "receipt time, so the same sequence reports STALE."
        ),
        "invariant": "EVIDENCE_DESCRIBES_CURRENT_OWNED_CONTENT",
        "detects": CHECK_THEN_EDIT,
        "run": run_check_then_edit,
    },
    {
        "id": "NC_MISSING_QUANT_VALIDATOR",
        "description": (
            "Generic tests over a declared quant surface with no required "
            "validator bound to its contract. Every validator the repository "
            "declares passes, so the naive workflow is green - about a "
            "contract nothing in the repository was written to check. AIQE "
            "reports COVERAGE_GAP."
        ),
        "invariant": "APPLICABLE_CONTRACT_WITHOUT_REQUIRED_VALIDATOR_IS_A_GAP",
        "detects": GENERIC_TESTS_ONLY,
        "run": run_generic_tests_only,
    },
    {
        "id": "NC_CONSENT",
        "description": (
            "Tracked configuration treated as authorization. The naive tool "
            "reads aiqe.toml and runs what it declares, so anyone who can "
            "land a commit can run a command on the reviewer's machine. AIQE "
            "executes nothing without machine-local consent recorded for that "
            "exact validator definition."
        ),
        "invariant": "UNCONSENTED_VALIDATOR_EXECUTIONS = 0",
        "detects": DECLARED_IS_AUTHORISED,
        "run": run_declared_is_authorised,
    },
    {
        "id": "NC_VALIDATOR_MUTATES_OWNED",
        "description": (
            "A validator that edits the file it checks and exits 0. The naive "
            "tool records the exit status and calls the result current, so it "
            "is green about source that no longer exists. AIQE measures the "
            "owned binding on both sides of execution and refuses to produce "
            "current evidence."
        ),
        "invariant": "VALIDATOR_INDUCED_CHANGE_INVALIDATES_CURRENT_EVIDENCE",
        "detects": SELF_EDITING_VALIDATOR,
        "run": run_self_editing_validator,
    },
]


def violated(control, observation):
    """Did the naive implementation actually breach the invariant this time?"""
    if control["detects"] == CHECK_THEN_EDIT:
        return (
            observation["naive_still_reports_green"] is True
            and observation["aiqe_receipt_evidence"] == "STALE"
        )
    if control["detects"] == GENERIC_TESTS_ONLY:
        return (
            observation["naive_reports_green"] is True
            and observation["aiqe_coverage"].get("CAUSALITY") == "COVERAGE_GAP"
        )
    if control["detects"] == DECLARED_IS_AUTHORISED:
        return (
            observation["naive_executed_declared_command"] is True
            and observation["aiqe_executed_declared_command"] is False
        )
    if control["detects"] == SELF_EDITING_VALIDATOR:
        return (
            observation["validator_changed_the_file_it_checked"] is True
            and observation["naive_reports_green_and_current"] is True
            and observation["aiqe_receipt_evidence"] != "CURRENT"
        )
    raise ValueError("unknown control detection mode %r" % (control["detects"],))
