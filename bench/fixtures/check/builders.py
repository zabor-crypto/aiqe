"""Deterministic fixtures for the CHECK_RECEIPT_EVIDENCE family.

Every fixture is built from nothing by the code in this file, every validator
is a two-line shell script whose behaviour is written here, and every AIQE
operation runs through the real command-line entry point as a subprocess.

Three construction rules make the measurements mean something.

**Validators announce themselves.** Every validator script's first action is to
write a marker into the case's canary directory, which lives outside every
snapshot root. So the harness does not have to infer whether a validator ran:
it can see it. That is what turns `UNCONSENTED_VALIDATOR_EXECUTIONS = 0` from
a claim about code into a measurement.

**Owned edits happen during construction, not during measurement.** A fixture
that modified a tracked file inside the measured window would show up as a
repository mutation and be indistinguishable from AIQE writing one. So the
owned file is edited before the snapshot is taken, and the cases that must
move something afterwards - a commit, a configuration edit - declare exactly
which paths they touch, so the harness can attribute those changes to the
fixture rather than to AIQE core.

**Validators that write declare it too.** One case exists specifically to
prove that a validator which edits the file it is checking does not produce
current evidence. Its writes are attributed to the validator. AIQE core's own
repository writes are the separate, zero-tolerance quantity, and the two are
never allowed to blur into one number.
"""

import json
import os
import platform
import sys

from ..repobuild import (  # noqa: F401  (re-exported: scenarios use these names)
    canary,
    commit_all,
    git,
    init_repo,
    platform_supports,
    write,
)
from ..task.builders import (  # noqa: F401
    read_active,
    run_cli,
    salt_exists,
    state_directory,
    terminal_safe,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SOURCE = os.path.join(ROOT, "src")

if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

from aiqe import contracts as contracts_module  # noqa: E402
from aiqe import evidence as evidence_module  # noqa: E402

#: The one path every scenario's task owns.
OWNED = b"src/strategy/alpha.py"
OWNED_TEXT = "src/strategy/alpha.py"


# --- Configuration text ----------------------------------------------------


def surface(paths, quant, contracts=None):
    lines = ["[[surface]]", "paths = [%s]" % (", ".join('"%s"' % p for p in paths),)]
    lines.append("quant = %s" % ("true" if quant else "false"))
    if contracts:
        lines.append("contracts = [%s]" % (", ".join('"%s"' % c for c in contracts),))
    return "\n".join(lines) + "\n"


def validator(identifier, run, required, timeout, contracts=None):
    lines = [
        "[[validator]]",
        'id = "%s"' % (identifier,),
        "run = [%s]" % (", ".join('"%s"' % part for part in run),),
        "required = %s" % ("true" if required else "false"),
        "timeout = %d" % (timeout,),
    ]
    if contracts:
        lines.append("contracts = [%s]" % (", ".join('"%s"' % c for c in contracts),))
    return "\n".join(lines) + "\n"


def config(blocks):
    return "schema = 1\n\n" + "\n".join(blocks)


#: The non-quant half of every fixture's configuration. Without it the
#: fixture's own scaffolding would classify as unclassified and every case
#: would carry a classification gap it was not built to test.
NON_QUANT = surface(
    ["tests/**", "docs/**", "checks/**", "aiqe.toml"], quant=False
)


# --- Repository construction -----------------------------------------------


def build_repository(case, env, config_text, scripts=(), edit_owned=True,
                     write_config=True):
    """A repository with one commit, a configuration, and validator scripts.

    `scripts` is a sequence of (id, shell body). Each becomes
    `checks/<id>.sh`, executable, whose first action records that it ran.
    """
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "src", "strategy", "alpha.py"), "SIGNAL = 1\n")
    write(os.path.join(root, "tests", "test_alpha.py"), "def test():\n    pass\n")
    write(os.path.join(root, "docs", "notes.md"), "notes\n")
    for identifier, body in scripts:
        canary(
            os.path.join(root, "checks", "%s.sh" % (identifier,)),
            case.marker(identifier),
            body=body,
        )
    if write_config:
        write(os.path.join(root, "aiqe.toml"), config_text)
    commit_all(root, "base", env)
    if edit_owned:
        # The change under check, made before the measurement window opens.
        write(
            os.path.join(root, "src", "strategy", "alpha.py"),
            "SIGNAL = 1\nADJUSTED = 2\n",
        )
    return root


def script(identifier, exit_code=0, body=None):
    if body is not None:
        return (identifier, body)
    return (identifier, "exit %d" % (exit_code,))


# --- Driving the product ---------------------------------------------------


def _allow_arguments(allow):
    arguments = []
    for identifier in allow:
        arguments.extend([b"--allow", identifier.encode("ascii")])
    return arguments


def workflow(case, env, root, allow=(), before_receipt=None):
    """task start, check, receipt, task end - and everything they said.

    `before_receipt` is a hook the staleness cases use to change something
    after the check and before the receipt. It runs inside the measured
    window, which is why those cases declare the paths it touches.
    """
    started = run_cli(root, env, b"task", b"start", b"--own", OWNED)
    allow_arguments = _allow_arguments(allow)

    machine = run_cli(root, env, b"check", *(allow_arguments + [b"--format", b"json"]))
    human = run_cli(root, env, b"check", *allow_arguments)
    evidence_after_check = _evidence_present(root, env)

    if before_receipt is not None:
        before_receipt()

    receipt_human = run_cli(root, env, b"receipt")
    receipt_machine = run_cli(root, env, b"receipt", b"--format", b"json")
    receipt_local = run_cli(root, env, b"receipt", b"--local")

    ended = run_cli(root, env, b"task", b"end")

    observation = {
        "start_exit": started.returncode,
        "check_exit": human.returncode,
        "check_json_exit": machine.returncode,
        "evidence_after_check": evidence_after_check,
        "receipt_exit": receipt_human.returncode,
        "receipt_json_exit": receipt_machine.returncode,
        "receipt_local_exit": receipt_local.returncode,
        "end_exit": ended.returncode,
        "active_after_end": read_active(root, env) is not None,
        "evidence_after_end": _evidence_present(root, env),
        "terminal_safe": terminal_safe(
            started, machine, human, receipt_human, receipt_machine, receipt_local, ended
        ),
        "consented": sorted(allow),
    }
    # Retained so that documentation can quote a real run rather than a
    # hand-typed approximation of one. Hand-typed output drifts from the
    # product silently, which is exactly what this project tells its users not
    # to accept from anyone else.
    observation["check_output"] = human.stdout.decode("utf-8", "replace")
    observation["receipt_output"] = receipt_human.stdout.decode("utf-8", "replace")

    observation.update(_from_check(machine))
    observation.update(_from_receipt(receipt_machine))
    observation["default_receipt_leaks"] = leaks(
        case, env, root, receipt_human.stdout + receipt_machine.stdout
    )
    return observation


def _from_check(completed):
    """Pull the structured claims out of `aiqe check --format json`."""
    empty = {
        "completion": None,
        "reasons": [],
        "classification": None,
        "coverage_states": {},
        "validator_outcomes": {},
        "changed_owned_count": None,
    }
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return empty

    if "classification" not in document:
        # A refusal or an authority-drift result carries a verdict and no
        # classification. Reporting three nulls would look like a
        # classification that found nothing.
        merged = dict(empty)
        merged.update(
            {
                "completion": (document.get("result") or {}).get("completion"),
                "reasons": sorted((document.get("result") or {}).get("reasons") or []),
            }
        )
        return merged

    classification = document.get("classification") or {}
    return {
        "completion": (document.get("result") or {}).get("completion"),
        "reasons": sorted((document.get("result") or {}).get("reasons") or []),
        "classification": [
            classification.get("quant_count"),
            classification.get("non_quant_count"),
            classification.get("unclassified_count"),
        ],
        "coverage_states": {
            entry["contract"]: entry["state"] for entry in document.get("coverage") or []
        },
        "validator_outcomes": {
            entry["validator_id"]: entry["outcome"]
            for entry in document.get("validators") or []
        },
        "changed_owned_count": document.get("changed_owned_count"),
    }


def _from_receipt(completed):
    empty = {
        "receipt_verdict": None,
        "receipt_reasons": [],
        "receipt_evidence": None,
        "receipt_owned_scope": None,
        "receipt_commit": None,
    }
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return empty
    return {
        "receipt_verdict": document.get("verdict"),
        "receipt_reasons": sorted(document.get("reasons") or []),
        "receipt_evidence": document.get("evidence"),
        "receipt_owned_scope": document.get("owned_scope"),
        "receipt_commit": document.get("commit"),
    }


def _evidence_present(root, env):
    directory = state_directory(root, env)
    if directory is None:
        return False
    return os.path.exists(os.path.join(directory, evidence_module.CHECK_FILE_NAME))


# --- The default receipt's exclusion property ------------------------------


def leaks(case, env, root, rendered):
    """Which forbidden literals appear in the default shareable receipt.

    Measured against the fixture's real values rather than a pattern: the
    worktree path, the owned filename, the commit identifiers, the branch, the
    remote, the validator command lines, the home directory, the username and
    the hostname all exist here and are all known, so their absence is a fact
    rather than a rule of thumb.
    """
    forbidden = {
        "case root": case.root,
        "worktree path": root,
        "home": env.get("HOME", ""),
        "owned path": OWNED_TEXT,
        "owned filename": "alpha.py",
        "validator command": "checks/",
        "config filename": "aiqe.toml",
        "branch": "refs/heads/",
        "username": _identity(os.environ.get("USER") or os.environ.get("LOGNAME")),
        "hostname": _identity(platform.node()),
    }
    head = git(root, "rev-parse", "HEAD", env=env, check=False)
    sha = head.stdout.decode("ascii", "replace").strip()
    if sha:
        forbidden["commit sha"] = sha
        forbidden["abbreviated sha"] = sha[:12]

    text = rendered.decode("utf-8", "replace")
    found = []
    for label, literal in sorted(forbidden.items()):
        if literal and literal in text:
            found.append(label)
    return found


def _identity(value):
    """A username or hostname short enough to occur by chance is not evidence.

    Three characters or fewer would make this property test fire on a state
    name or a reason code, which would be a false positive that eventually
    gets the whole check disabled.
    """
    if not value or len(value) <= 3:
        return ""
    return value


# --- Scenarios: the six launch contract families ---------------------------


def _family_scenarios():
    """Three variants per contract family, built from one shape.

    Writing them out by hand six times would be six chances to make one family
    quietly weaker than the others - and the whole point of a per-family
    fixture is that no family is represented by another.
    """
    scenarios = {}
    for contract in contracts_module.LAUNCH_CONTRACTS:
        lower = contract.lower()

        covered = config(
            [
                surface(["src/strategy/**"], quant=True, contracts=[contract]),
                NON_QUANT,
                validator("unit", ["./checks/unit.sh"], True, 60),
                validator(
                    lower, ["./checks/%s.sh" % (lower,)], True, 60, contracts=[contract]
                ),
            ]
        )
        failed = config(
            [
                surface(["src/strategy/**"], quant=True, contracts=[contract]),
                NON_QUANT,
                validator("unit", ["./checks/unit.sh"], True, 60),
                validator(
                    lower, ["./checks/%s.sh" % (lower,)], True, 60, contracts=[contract]
                ),
            ]
        )
        gap = config(
            [
                surface(["src/strategy/**"], quant=True, contracts=[contract]),
                NON_QUANT,
                validator("unit", ["./checks/unit.sh"], True, 60),
                # The contract applies and nothing required is bound to it.
                # An optional validator that passes must not close the gap.
                validator(
                    lower,
                    ["./checks/%s.sh" % (lower,)],
                    False,
                    60,
                    contracts=[contract],
                ),
            ]
        )

        scenarios["%s_covered" % (lower,)] = {
            "build": _builder(covered, [script("unit"), script(lower)]),
            "operate": _operator(allow=("unit", lower)),
        }
        scenarios["%s_failed" % (lower,)] = {
            "build": _builder(failed, [script("unit"), script(lower, exit_code=1)]),
            "operate": _operator(allow=("unit", lower)),
        }
        scenarios["%s_coverage_gap" % (lower,)] = {
            "build": _builder(gap, [script("unit"), script(lower)]),
            "operate": _operator(allow=("unit", lower)),
        }
    return scenarios


def _builder(config_text, scripts, edit_owned=True):
    def build(case, env):
        return build_repository(case, env, config_text, scripts, edit_owned)

    return build


def _operator(allow=(), before_receipt=None):
    def operate(case, env, root):
        hook = None if before_receipt is None else before_receipt(case, env, root)
        return workflow(case, env, root, allow=allow, before_receipt=hook)

    return operate


# --- Scenarios: classification and configuration ---------------------------

UNCLASSIFIED_CONFIG = config(
    [
        surface(["docs/**", "tests/**", "checks/**", "aiqe.toml"], quant=False),
        validator("unit", ["./checks/unit.sh"], True, 60),
    ]
)

CONFLICT_CONFIG = config(
    [
        surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
        surface(["**/alpha.py"], quant=False),
        NON_QUANT,
        validator("unit", ["./checks/unit.sh"], True, 60),
    ]
)

SIMPLE_QUANT = config(
    [
        surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        NON_QUANT,
        validator("unit", ["./checks/unit.sh"], True, 60),
        validator(
            "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
        ),
    ]
)

UNAVAILABLE_CONFIG = config(
    [
        surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        NON_QUANT,
        validator(
            "causality",
            ["./checks/not-installed.sh"],
            True,
            60,
            contracts=["CAUSALITY"],
        ),
    ]
)

TIMEOUT_CONFIG = config(
    [
        surface(["src/strategy/**"], quant=True, contracts=["DETERMINISM"]),
        NON_QUANT,
        validator(
            "determinism",
            ["./checks/determinism.sh"],
            True,
            1,
            contracts=["DETERMINISM"],
        ),
    ]
)

MUTATING_CONFIG = config(
    [
        surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        NON_QUANT,
        validator(
            "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
        ),
    ]
)

GENERIC_ONLY = config(
    [
        surface(["src/strategy/**"], quant=False),
        NON_QUANT,
        validator("unit", ["./checks/unit.sh"], True, 60),
    ]
)


def _edit_owned_after_check(case, env, root):
    def hook():
        write(
            os.path.join(root, "src", "strategy", "alpha.py"),
            "SIGNAL = 1\nADJUSTED = 3\n",
        )

    return hook


def _move_head_after_check(case, env, root):
    def hook():
        write(os.path.join(root, "docs", "notes.md"), "notes, revised\n")
        git(root, "add", "docs/notes.md", env=env)
        git(root, "commit", "-q", "-m", "unrelated", env=env)

    return hook


def _edit_config_after_check(case, env, root):
    def hook():
        with open(os.path.join(root, "aiqe.toml"), "a") as handle:
            handle.write("\n# a comment added after the check\n")

    return hook


def operate_consent_withheld(case, env, root):
    """No `--allow`, no recorded consent, and no interactive terminal."""
    observation = workflow(case, env, root, allow=())
    observation["validators_that_ran"] = case.fired()
    return observation


def operate_allow_is_not_persisted(case, env, root):
    """`--allow` authorises one run. The next check must ask again."""
    run_cli(root, env, b"task", b"start", b"--own", OWNED)
    first = run_cli(
        root, env, b"check", b"--allow", b"unit", b"--allow", b"causality",
        b"--format", b"json",
    )
    second = run_cli(root, env, b"check", b"--format", b"json")
    ended = run_cli(root, env, b"task", b"end")

    return {
        "first_exit": first.returncode,
        "second_exit": second.returncode,
        "first_outcomes": _from_check(first)["validator_outcomes"],
        "second_outcomes": _from_check(second)["validator_outcomes"],
        "active_after_end": read_active(root, env) is not None,
        "terminal_safe": terminal_safe(first, second, ended),
        "consented": ["causality", "unit"],
    }


def operate_definition_digest_drift(case, env, root):
    """Consent is recorded for a definition, then the definition changes.

    Consent is granted here the way an interactive user would grant it - by
    writing the record AIQE writes - and then the validator's timeout is
    edited. The digest no longer matches, so the recorded consent addresses a
    definition that no longer exists, and the validator is UNKNOWN again.
    """
    import aiqe.config as config_module
    import aiqe.validators as validators_module

    run_cli(root, env, b"task", b"start", b"--own", OWNED)

    parsed = config_module.load(os.fsencode(root))
    digests = {
        declared.id: validators_module.definition_digest(declared)
        for declared in parsed.validators
    }

    directory = state_directory(root, env)
    store = validators_module.ConsentStore(directory)
    for identifier, digest in digests.items():
        store.grant(digest, identifier)

    consented = run_cli(root, env, b"check", b"--format", b"json")

    # One semantic field changes, and with it the validator's identity.
    with open(os.path.join(root, "aiqe.toml")) as handle:
        text = handle.read()
    write(os.path.join(root, "aiqe.toml"), text.replace("timeout = 60", "timeout = 90"))

    drifted = run_cli(root, env, b"check", b"--format", b"json")
    ended = run_cli(root, env, b"task", b"end")

    return {
        "consented_exit": consented.returncode,
        "drifted_exit": drifted.returncode,
        "consented_outcomes": _from_check(consented)["validator_outcomes"],
        "drifted_outcomes": _from_check(drifted)["validator_outcomes"],
        "distinct_digests": len(set(digests.values())) == len(digests),
        "active_after_end": read_active(root, env) is not None,
        "terminal_safe": terminal_safe(consented, drifted, ended),
        "consented": sorted(digests),
    }


def operate_init_print(case, env, root):
    """`aiqe init --print` is a preview, and previews write nothing."""
    printed = run_cli(root, env, b"init", b"--print")
    return {
        "init_exit": printed.returncode,
        "renders_schema": b"schema = 1" in printed.stdout,
        "renders_surface_example": b"[[surface]]" in printed.stdout,
        "renders_validator_example": b"[[validator]]" in printed.stdout,
        "config_written": os.path.exists(os.path.join(root, "aiqe.toml")),
        "salt_created": salt_exists(env),
        "terminal_safe": terminal_safe(printed),
    }


def operate_init_writes_config(case, env, root):
    """`aiqe init --yes` writes one repository path and refuses to repeat."""
    written = run_cli(root, env, b"init", b"--yes")
    again = run_cli(root, env, b"init", b"--yes")
    return {
        "init_exit": written.returncode,
        "second_init_exit": again.returncode,
        "config_written": os.path.exists(os.path.join(root, "aiqe.toml")),
        "declares_no_surface": _uncommented(os.path.join(root, "aiqe.toml")),
        "terminal_safe": terminal_safe(written, again),
    }


def _uncommented(path):
    """The configuration's non-comment, non-blank lines.

    The scaffold must declare `schema = 1` and nothing else: a guessed surface
    would be a classification rule nobody wrote.
    """
    with open(path) as handle:
        return [
            line.strip()
            for line in handle
            if line.strip() and not line.strip().startswith("#")
        ]


def build_no_config(case, env):
    """A repository AIQE has never been configured for."""
    return build_repository(
        case, env, "", scripts=(), edit_owned=True, write_config=False
    )


def build_init_target(case, env):
    """A repository with no `aiqe.toml`, which is what `init` is for."""
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "src", "strategy", "alpha.py"), "SIGNAL = 1\n")
    commit_all(root, "base", env)
    return root


def operate_unchanged_owned_path(case, env, root):
    """A task whose owned path was never touched carries no obligation."""
    return workflow(case, env, root, allow=("unit",))


SCENARIOS = dict(_family_scenarios())
SCENARIOS.update(
    {
        "unclassified_changed_path": {
            "build": _builder(UNCLASSIFIED_CONFIG, [script("unit")]),
            "operate": _operator(allow=("unit",)),
        },
        "config_conflict_refused": {
            "build": _builder(CONFLICT_CONFIG, [script("unit")]),
            "operate": _operator(allow=("unit",)),
        },
        "consent_withheld": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": operate_consent_withheld,
        },
        "allow_is_not_persisted": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": operate_allow_is_not_persisted,
        },
        "definition_digest_drift": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": operate_definition_digest_drift,
            "fixture_writes": ("repo/aiqe.toml",),
        },
        "validator_unavailable": {
            "build": _builder(UNAVAILABLE_CONFIG, []),
            "operate": _operator(allow=("causality",)),
        },
        "validator_timeout_is_failure": {
            "build": _builder(
                TIMEOUT_CONFIG, [script("determinism", body="sleep 30")]
            ),
            "operate": _operator(allow=("determinism",)),
        },
        "validator_mutates_owned_path": {
            "build": _builder(
                MUTATING_CONFIG,
                [
                    script(
                        "causality",
                        body="echo 'edited by the validator' >> src/strategy/alpha.py",
                    )
                ],
            ),
            "operate": _operator(allow=("causality",)),
            "validator_writes": ("repo/src/strategy/alpha.py",),
        },
        "owned_content_changes_after_check": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": _operator(
                allow=("unit", "causality"), before_receipt=_edit_owned_after_check
            ),
            "fixture_writes": ("repo/src/strategy/alpha.py",),
        },
        "head_moves_after_check": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": _operator(
                allow=("unit", "causality"), before_receipt=_move_head_after_check
            ),
            "fixture_writes": ("repo/.git", "repo/docs/notes.md"),
        },
        "config_changes_after_check": {
            "build": _builder(SIMPLE_QUANT, [script("unit"), script("causality")]),
            "operate": _operator(
                allow=("unit", "causality"), before_receipt=_edit_config_after_check
            ),
            "fixture_writes": ("repo/aiqe.toml",),
        },
        "unchanged_owned_path": {
            "build": _builder(GENERIC_ONLY, [script("unit")], edit_owned=False),
            "operate": operate_unchanged_owned_path,
        },
        "configuration_absent": {
            "build": build_no_config,
            "operate": _operator(allow=()),
        },
        "init_print_writes_nothing": {
            "build": build_init_target,
            "operate": operate_init_print,
        },
        "init_writes_only_the_config": {
            "build": build_init_target,
            "operate": operate_init_writes_config,
            "aiqe_init_writes": ("repo/aiqe.toml",),
        },
    }
)
