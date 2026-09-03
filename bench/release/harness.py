"""Building, installing and exercising a real AIQE artifact.

Everything here runs out of process, against an installed distribution, from a
working directory that is not the source tree. That is the whole point: a test
that imports `aiqe` from `src/` proves the source tree works and says nothing
about the artifact a user receives. The negative control in `controls.py`
demonstrates the difference rather than asserting it.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import artifacts

#: A build gets ten minutes and an install five. These are generous: they are
#: not performance assertions, they exist so that a hung child process fails
#: the proof instead of hanging the job.
BUILD_TIMEOUT = 600
INSTALL_TIMEOUT = 300
COMMAND_TIMEOUT = 300

#: The fixed timestamp the documented reproducible build procedure uses.
#: An arbitrary constant: what matters is that it is the same on every
#: build, not which instant it names.
SOURCE_DATE_EPOCH = 1700000000


class ProofError(Exception):
    """A step of the release proof could not be carried out at all."""


def run(argv, cwd=None, env=None, timeout=COMMAND_TIMEOUT):
    """Run a command, capturing both streams and never raising on failure."""
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": list(argv),
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", "replace"),
        "stderr": completed.stderr.decode("utf-8", "replace"),
    }


def export_source(root, destination):
    """Copy the repository's tracked content into an empty directory.

    Tracked content only, and no `.git`. A build that ran in the working
    directory would pick up whatever else is lying there - a previous
    `build/`, a `__pycache__`, an editor's scratch file - and the artifact
    would depend on the state of somebody's laptop.
    """
    listing = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if listing.returncode != 0:
        raise ProofError(
            "could not list tracked files in %s: %s"
            % (root, listing.stderr.decode("utf-8", "replace").strip())
        )
    names = [name for name in listing.stdout.split(b"\0") if name]
    os.makedirs(destination, exist_ok=True)
    for raw in names:
        relative = os.fsdecode(raw)
        source_path = os.path.join(root, relative)
        if not os.path.isfile(source_path):
            # A tracked path that is not a regular file in this checkout -
            # a submodule gitlink, say. Nothing to copy, and nothing this
            # project has.
            continue
        target_path = os.path.join(destination, relative)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)
    return destination, len(names)


def create_venv(path, python=None):
    """A fresh virtual environment, with pip, and nothing else."""
    interpreter = python or sys.executable
    result = run([interpreter, "-m", "venv", path], timeout=INSTALL_TIMEOUT)
    if result["returncode"] != 0:
        raise ProofError("could not create a virtual environment: %s" % result["stderr"])
    return venv_python(path)


def venv_python(path):
    return os.path.join(path, "bin", "python")


def venv_script(path, name):
    return os.path.join(path, "bin", name)


def build_artifacts(source, outdir, python=None, source_date_epoch=None):
    """Build an sdist and a wheel from an exported source tree.

    `python -m build` is used unchanged, with its own build isolation. It is
    the reference way to build a Python distribution, and using anything else
    here would mean the artifact this proof measures is not the artifact the
    standard toolchain produces.
    """
    interpreter = python or sys.executable
    env = dict(os.environ)
    env.pop("SOURCE_DATE_EPOCH", None)
    if source_date_epoch is not None:
        env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    result = run(
        [interpreter, "-m", "build", "--outdir", outdir],
        cwd=source,
        env=env,
        timeout=BUILD_TIMEOUT,
    )
    if result["returncode"] != 0:
        raise ProofError(
            "build failed:\n%s\n%s" % (result["stdout"][-4000:], result["stderr"][-4000:])
        )
    built = sorted(os.listdir(outdir))
    wheels = [name for name in built if name.endswith(".whl")]
    sdists = [name for name in built if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ProofError(
            "expected exactly one wheel and one sdist, got %r" % (built,)
        )
    return {
        "wheel": os.path.join(outdir, wheels[0]),
        "sdist": os.path.join(outdir, sdists[0]),
        "build_log_tail": result["stdout"][-2000:],
    }


def frozen_packages(python):
    """Every distribution installed in an environment, as `name==version`."""
    result = run([python, "-m", "pip", "list", "--format=freeze"], timeout=INSTALL_TIMEOUT)
    if result["returncode"] != 0:
        raise ProofError("could not list installed packages: %s" % result["stderr"])
    return sorted(
        line.strip() for line in result["stdout"].splitlines() if line.strip()
    )


#: Distributions a fresh `python -m venv` may legitimately contain, alongside
#: AIQE itself. Anything else means a third-party runtime dependency was
#: pulled in, which is the thing this project promises never happens.
BOOTSTRAP_DISTRIBUTIONS = frozenset({"aiqe", "pip", "setuptools", "wheel"})


def third_party_dependencies(python):
    """The distributions installed beyond AIQE and the environment's bootstrap."""
    names = {
        entry.split("==")[0].strip().lower().replace("_", "-")
        for entry in frozen_packages(python)
    }
    return sorted(names - BOOTSTRAP_DISTRIBUTIONS)


def install_artifact(python, artifact, offline_after=False):
    """Install one built artifact into an environment.

    `--no-index` is not used: pip must be allowed to discover that the package
    declares no dependencies rather than be prevented from looking. That the
    resulting environment contains no third party is then a measurement, not a
    configuration.
    """
    result = run(
        [python, "-m", "pip", "install", "--quiet", artifact],
        timeout=INSTALL_TIMEOUT,
    )
    if result["returncode"] != 0:
        raise ProofError(
            "installing %s failed:\n%s" % (artifact, result["stderr"][-4000:])
        )
    return result


def installed_location(python):
    """Where `aiqe` resolves from in this environment.

    The proof that the end-to-end ran against the installed distribution and
    not against a source tree on the path is this string, recorded rather than
    asserted in a comment.
    """
    result = run(
        [
            python,
            "-c",
            "import aiqe, json, sys;"
            "print(json.dumps({'file': aiqe.__file__, 'version': aiqe.__version__,"
            " 'prefix': sys.prefix}))",
        ],
        cwd=tempfile.gettempdir(),
    )
    if result["returncode"] != 0:
        raise ProofError("installed aiqe could not be imported: %s" % result["stderr"])
    return json.loads(result["stdout"].strip())


# --- The synthetic end-to-end repository ----------------------------------
#
# Built from nothing, every time. It contains a quant surface, one required
# validator bound to a contract, and a one-line change to an owned file - the
# smallest repository in which `REVIEWABLE` is reachable at all.

VALIDATOR_SOURCE = '''\
import sys

with open("src/strategy/alpha.py", encoding="utf-8") as handle:
    source = handle.read()

# A stand-in for a causality check: the fixture's defect, if it had one, would
# be a negative index shift. This validator is real - it reads the file it was
# declared to check and decides from its content.
sys.exit(1 if "shift(-1)" in source else 0)
'''

CONFIG_TEMPLATE = '''\
schema = 1

[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY"]

[[validator]]
id = "causality"
run = [%s, "checks/no_lookahead.py"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
'''


def build_synthetic_repository(root, validator_interpreter):
    """A real Git repository with a real quant surface and a real validator."""
    os.makedirs(os.path.join(root, "src", "strategy"))
    os.makedirs(os.path.join(root, "checks"))
    with open(os.path.join(root, "src", "strategy", "alpha.py"), "w") as handle:
        handle.write("signal = 0\n")
    with open(os.path.join(root, "checks", "no_lookahead.py"), "w") as handle:
        handle.write(VALIDATOR_SOURCE)
    with open(os.path.join(root, "aiqe.toml"), "w") as handle:
        handle.write(CONFIG_TEMPLATE % (json.dumps(validator_interpreter),))

    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_NAME": "AIQE Release Proof",
            "GIT_AUTHOR_EMAIL": "release-proof@example.invalid",
            "GIT_COMMITTER_NAME": "AIQE Release Proof",
            "GIT_COMMITTER_EMAIL": "release-proof@example.invalid",
        }
    )
    for argv in (
        ["git", "init", "--quiet", "."],
        ["git", "config", "user.name", "AIQE Release Proof"],
        ["git", "config", "user.email", "release-proof@example.invalid"],
        ["git", "add", "-A"],
        ["git", "commit", "--quiet", "-m", "baseline"],
    ):
        result = run(argv, cwd=root, env=environment)
        if result["returncode"] != 0:
            raise ProofError(
                "could not build the synthetic repository (%s): %s"
                % (" ".join(argv), result["stderr"])
            )
    return root


def isolated_environment(state_home, extra=None):
    """An environment whose AIQE state lives somewhere disposable."""
    environment = dict(os.environ)
    environment["XDG_STATE_HOME"] = state_home
    environment.update(
        {
            "GIT_AUTHOR_NAME": "AIQE Release Proof",
            "GIT_AUTHOR_EMAIL": "release-proof@example.invalid",
            "GIT_COMMITTER_NAME": "AIQE Release Proof",
            "GIT_COMMITTER_EMAIL": "release-proof@example.invalid",
        }
    )
    if extra:
        environment.update(extra)
    return environment


def installed_end_to_end(aiqe_binary, workdir, validator_interpreter, extra_env=None):
    """init, task start, check, commit, receipt - from the installed artifact.

    Returns a structured record, including the verdict the receipt actually
    reported. The caller decides whether that is a pass; this function does
    not soften anything.
    """
    repository = os.path.join(workdir, "repo")
    state = os.path.join(workdir, "state")
    outside = os.path.join(workdir, "not-a-repository")
    os.makedirs(repository)
    os.makedirs(state)
    os.makedirs(outside)
    build_synthetic_repository(repository, validator_interpreter)
    environment = isolated_environment(state, extra_env)

    steps = []

    def step(name, argv, cwd):
        result = run(argv, cwd=cwd, env=environment)
        steps.append(
            {
                "step": name,
                "argv": result["argv"],
                "returncode": result["returncode"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            }
        )
        return result

    version = step("version", [aiqe_binary, "--version"], outside)
    doctor_outside = step("doctor_non_repository", [aiqe_binary, "doctor"], outside)
    doctor_repo = step("doctor_repository", [aiqe_binary, "doctor"], repository)
    doctor_json = step(
        "doctor_json", [aiqe_binary, "doctor", "--format", "json"], repository
    )
    init_print = step("init_print", [aiqe_binary, "init", "--print"], repository)
    task_start = step(
        "task_start",
        [
            aiqe_binary,
            "task",
            "start",
            "--own",
            "src/strategy/alpha.py",
            "--label",
            "release proof",
        ],
        repository,
    )

    with open(os.path.join(repository, "src", "strategy", "alpha.py"), "w") as handle:
        handle.write("signal = 1\n")

    check = step("check", [aiqe_binary, "check", "--allow", "causality"], repository)
    commit = step("commit", [aiqe_binary, "commit", "-m", "bounded completion"], repository)
    receipt = step("receipt", [aiqe_binary, "receipt"], repository)
    receipt_local = step(
        "receipt_local",
        [aiqe_binary, "receipt", "--local", "--format", "json"],
        repository,
    )
    task_end = step("task_end", [aiqe_binary, "task", "end"], repository)

    def verdict_of(output):
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Verdict"):
                return stripped.split()[-1]
        return None

    commit_verdict = verdict_of(commit["stdout"])
    receipt_verdict = verdict_of(receipt["stdout"])

    problems = []
    for name, result, expected in (
        ("--version", version, 0),
        ("doctor outside a repository", doctor_outside, None),
        ("doctor in the repository", doctor_repo, None),
        ("doctor --format json", doctor_json, None),
        ("init --print", init_print, 0),
        ("task start", task_start, 0),
        ("check", check, 0),
        ("commit", commit, 0),
        ("receipt", receipt, 0),
        ("task end", task_end, 0),
    ):
        if expected is not None and result["returncode"] != expected:
            problems.append(
                "%s exited %d, expected %d" % (name, result["returncode"], expected)
            )
    if commit_verdict != "REVIEWABLE":
        problems.append("commit verdict was %r, expected REVIEWABLE" % (commit_verdict,))
    if receipt_verdict != "REVIEWABLE":
        problems.append(
            "receipt verdict was %r, expected REVIEWABLE" % (receipt_verdict,)
        )
    if os.path.exists(os.path.join(repository, "aiqe.toml.bak")):
        problems.append("init --print wrote a file")
    if receipt_local["returncode"] != 0:
        problems.append(
            "receipt --local --format json exited %d" % (receipt_local["returncode"],)
        )

    return {
        "outcome": "PASS" if not problems else "FAIL",
        "problems": problems,
        "commit_verdict": commit_verdict,
        "receipt_verdict": receipt_verdict,
        "version_output": version["stdout"].strip(),
        "steps": [
            {
                "step": entry["step"],
                "argv": entry["argv"],
                "returncode": entry["returncode"],
            }
            for entry in steps
        ],
        "receipt_output": receipt["stdout"],
        "commit_output": commit["stdout"],
    }


# --- Offline runtime proof -------------------------------------------------
#
# The claim is about AIQE's runtime, not about installation. Resolving and
# downloading a package uses the network by definition; that is the
# installer's behaviour. What must hold is that once AIQE is installed, its
# core commands need no network at all.
#
# The mechanism is the out-of-process form of the canary the unit suite
# already applies to Doctor in `tests/test_network.py`: every socket entry
# point in the standard library is replaced with a recorder that appends to a
# file and then raises. Here it is installed through `sitecustomize`, so it
# applies to the console script exactly as a user would run it, and to any
# Python child process it spawns.
#
# Its limit is stated rather than glossed: this is not a network namespace or
# a packet filter. It is conclusive for Python code and says nothing about
# what a non-Python child process does. Git is that child process, and the
# argument for Git is the frozen subcommand allowlist, which contains no
# network subcommand - an argument the unit suite makes separately.

NETWORK_CANARY = '''\
"""Record and refuse every network attempt made by this interpreter."""

import os

_RECORD = os.environ.get("AIQE_NETWORK_CANARY_FILE")


def _fire(what):
    if _RECORD:
        with open(_RECORD, "a", encoding="utf-8") as handle:
            handle.write("%s\\n" % (what,))
    raise RuntimeError("network attempt refused by the AIQE release proof: %s" % (what,))


def _install():
    import socket

    class _RefusingSocket:
        def __init__(self, *args, **kwargs):
            _fire("socket.socket%r" % (args,))

    socket.socket = _RefusingSocket
    socket.socketpair = lambda *a, **k: _fire("socket.socketpair")
    socket.create_connection = lambda *a, **k: _fire("socket.create_connection")
    socket.create_server = lambda *a, **k: _fire("socket.create_server")
    socket.getaddrinfo = lambda *a, **k: _fire("socket.getaddrinfo%r" % (a,))
    socket.gethostbyname = lambda *a, **k: _fire("socket.gethostbyname")


_install()
'''


def offline_core_proof(venv_path, aiqe_binary, workdir, validator_interpreter):
    """Run the core command set with every Python socket entry point refusing.

    Returns the canary's recorded attempts. Anything but an empty list is a
    failure of the offline claim.
    """
    canary_home = os.path.join(workdir, "canary")
    os.makedirs(canary_home)
    with open(os.path.join(canary_home, "sitecustomize.py"), "w") as handle:
        handle.write(NETWORK_CANARY)
    record = os.path.join(workdir, "network-attempts.txt")

    extra = {
        "PYTHONPATH": canary_home
        + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        "AIQE_NETWORK_CANARY_FILE": record,
    }

    # Prove the canary itself fires before trusting its silence. A canary that
    # was accidentally not installed is indistinguishable from a clean run,
    # and that is the failure mode this line exists to remove.
    probe = run(
        [
            venv_python(venv_path),
            "-c",
            "import socket; socket.create_connection(('127.0.0.1', 9))",
        ],
        cwd=workdir,
        env=isolated_environment(os.path.join(workdir, "probe-state"), extra),
    )
    canary_armed = probe["returncode"] != 0 and os.path.exists(record)
    if os.path.exists(record):
        os.remove(record)

    result = installed_end_to_end(
        aiqe_binary,
        os.path.join(workdir, "offline-e2e"),
        validator_interpreter,
        extra_env=extra,
    )

    attempts = []
    if os.path.exists(record):
        with open(record, encoding="utf-8") as handle:
            attempts = [line.strip() for line in handle if line.strip()]

    problems = list(result["problems"])
    if not canary_armed:
        problems.append(
            "the network canary did not fire on a deliberate connection attempt; "
            "its silence during the run proves nothing"
        )
    if attempts:
        problems.append("network attempts recorded: %r" % (attempts,))

    return {
        "outcome": "PASS" if not problems else "FAIL",
        "problems": problems,
        "canary_armed": canary_armed,
        "network_attempts": attempts,
        "commands": [step["step"] for step in result["steps"]],
        "receipt_verdict": result["receipt_verdict"],
        "commit_verdict": result["commit_verdict"],
    }


# --- uv / uvx --------------------------------------------------------------


def uv_proof(workdir, wheel, validator_interpreter):
    """Prove the low-friction local-artifact path with uv, using uv's own interface.

    uv is obtained the ordinary way, from an index, into an environment of its
    own. That download is *tool installation* network, and it is reported
    separately from AIQE's runtime, which remains network-free: the two are
    different claims and are never merged here.

    `uv tool install <local wheel>` and `uvx --from <local wheel> aiqe` are the
    current documented ways to install and to run a tool from a local
    artifact, and both are exercised rather than one standing in for the
    other.
    """
    toolenv = os.path.join(workdir, "uv-tool-env")
    python = create_venv(toolenv)
    acquisition = run(
        [python, "-m", "pip", "install", "--quiet", "uv"], timeout=INSTALL_TIMEOUT
    )
    if acquisition["returncode"] != 0:
        return {
            "outcome": "FAIL",
            "problems": ["uv could not be installed: %s" % acquisition["stderr"][-2000:]],
            "uv_version": None,
        }
    uv = venv_script(toolenv, "uv")
    uvx = venv_script(toolenv, "uvx")

    uv_home = os.path.join(workdir, "uv-home")
    os.makedirs(uv_home)
    environment = dict(os.environ)
    environment.update(
        {
            "UV_TOOL_DIR": os.path.join(uv_home, "tools"),
            "UV_TOOL_BIN_DIR": os.path.join(uv_home, "bin"),
            "UV_CACHE_DIR": os.path.join(uv_home, "cache"),
            "XDG_DATA_HOME": os.path.join(uv_home, "data"),
        }
    )

    version = run([uv, "--version"], env=environment)
    problems = []
    steps = []

    def step(name, argv, cwd=None):
        result = run(argv, cwd=cwd, env=environment, timeout=INSTALL_TIMEOUT)
        steps.append(
            {"step": name, "argv": result["argv"], "returncode": result["returncode"]}
        )
        return result

    install = step("uv tool install", [uv, "tool", "install", "--force", wheel])
    if install["returncode"] != 0:
        problems.append("uv tool install failed: %s" % install["stderr"][-2000:])

    installed_binary = os.path.join(uv_home, "bin", "aiqe")
    outside = os.path.join(workdir, "uv-outside")
    os.makedirs(outside)

    uv_version_output = ""
    uv_doctor_rc = None
    if os.path.exists(installed_binary):
        installed_version = step(
            "uv tool aiqe --version", [installed_binary, "--version"], outside
        )
        uv_version_output = installed_version["stdout"].strip()
        if installed_version["returncode"] != 0:
            problems.append("aiqe --version from the uv tool install failed")
        installed_doctor = step("uv tool aiqe doctor", [installed_binary, "doctor"], outside)
        uv_doctor_rc = installed_doctor["returncode"]
    else:
        problems.append("uv tool install produced no `aiqe` executable")

    uvx_version = step(
        "uvx --from <wheel> aiqe --version",
        [uvx, "--from", wheel, "aiqe", "--version"],
        outside,
    )
    if uvx_version["returncode"] != 0:
        problems.append("uvx --from <wheel> aiqe --version failed: %s" % uvx_version["stderr"][-2000:])
    uvx_doctor = step(
        "uvx --from <wheel> aiqe doctor", [uvx, "--from", wheel, "aiqe", "doctor"], outside
    )

    return {
        "outcome": "PASS" if not problems else "FAIL",
        "problems": problems,
        "uv_version": version["stdout"].strip() or None,
        "uv_acquired_from_network": True,
        "aiqe_runtime_network": "not required; see the offline runtime proof",
        "tool_install_version_output": uv_version_output,
        "tool_install_doctor_returncode": uv_doctor_rc,
        "uvx_version_output": uvx_version["stdout"].strip(),
        "uvx_doctor_returncode": uvx_doctor["returncode"],
        "steps": steps,
    }


# --- Reproducibility -------------------------------------------------------


def reproducibility(root, workdir, python):
    """Build the same wheel twice, in two clean isolated surfaces, and compare.

    Measured twice over: once with the environment as it comes, and once with
    `SOURCE_DATE_EPOCH` fixed. Both numbers are reported. A project that
    published only the second would be describing a build procedure rather
    than the tool's default behaviour, and a project that published only the
    first would be hiding a procedure that works.

    When two builds differ, the difference is decomposed rather than reported
    as one boolean. "Every packaged file is byte-identical and the archive
    metadata is not" and "the code differs" are the same red light on a
    checklist and completely different facts, and only one of them is about
    artifact integrity.
    """

    def build_once(label, source_date_epoch):
        source = os.path.join(workdir, "src-%s" % (label,))
        dist = os.path.join(workdir, "dist-%s" % (label,))
        os.makedirs(dist)
        export_source(root, source)
        return build_artifacts(
            source, dist, python=python, source_date_epoch=source_date_epoch
        )

    default_one = build_once("default-1", None)
    default_two = build_once("default-2", None)
    pinned_one = build_once("pinned-1", SOURCE_DATE_EPOCH)
    pinned_two = build_once("pinned-2", SOURCE_DATE_EPOCH)

    default_wheel = artifacts.compare_builds(default_one["wheel"], default_two["wheel"])
    default_sdist = artifacts.compare_builds(default_one["sdist"], default_two["sdist"])
    pinned_wheel = artifacts.compare_builds(pinned_one["wheel"], pinned_two["wheel"])
    pinned_sdist = artifacts.compare_builds(pinned_one["sdist"], pinned_two["sdist"])

    def cause_of(comparison):
        """Why two builds differ, in terms of what was actually measured."""
        if comparison["identical_bytes"]:
            return None
        if not comparison["content_identical"]:
            return (
                "packaged file content differs between builds: %s"
                % (comparison["members_with_differing_content"][:10],)
            )
        fields = sorted(comparison["differing_metadata_fields"])
        return (
            "every packaged file is byte-identical; the archives differ only "
            "in archive metadata (%s) and, for a gzipped tar, the gzip "
            "header's own timestamp. setuptools stamps generated metadata "
            "files - PKG-INFO, setup.cfg and the egg-info directory - with "
            "the moment they were written, and SOURCE_DATE_EPOCH does not "
            "reach them in the sdist path." % (", ".join(fields) or "none recorded",)
        )

    return {
        "wheel_hash_run_1": artifacts.sha256(default_one["wheel"]),
        "wheel_hash_run_2": artifacts.sha256(default_two["wheel"]),
        "bitwise_reproducible": default_wheel["identical_bytes"],
        "bitwise_reproducible_with_source_date_epoch": pinned_wheel["identical_bytes"],
        "source_date_epoch_used": SOURCE_DATE_EPOCH,
        "pinned_wheel_hash_run_1": artifacts.sha256(pinned_one["wheel"]),
        "pinned_wheel_hash_run_2": artifacts.sha256(pinned_two["wheel"]),
        "sdist_hash_run_1": artifacts.sha256(default_one["sdist"]),
        "sdist_hash_run_2": artifacts.sha256(default_two["sdist"]),
        "sdist_bitwise_reproducible": default_sdist["identical_bytes"],
        "pinned_sdist_bitwise_reproducible": pinned_sdist["identical_bytes"],
        "wheel_comparison_default": default_wheel,
        "wheel_comparison_pinned": pinned_wheel,
        "sdist_comparison_default": default_sdist,
        "sdist_comparison_pinned": pinned_sdist,
        "wheel_content_identical": pinned_wheel["content_identical"]
        and default_wheel["content_identical"],
        "sdist_content_identical": pinned_sdist["content_identical"]
        and default_sdist["content_identical"],
        "wheel_cause": cause_of(pinned_wheel),
        "sdist_cause": cause_of(pinned_sdist),
        "affects_artifact_integrity": not (
            default_wheel["content_identical"]
            and pinned_wheel["content_identical"]
            and default_sdist["content_identical"]
            and pinned_sdist["content_identical"]
        ),
        "documented_procedure": (
            "python -m build with SOURCE_DATE_EPOCH=%d, from a source tree "
            "exported with tracked content only" % (SOURCE_DATE_EPOCH,)
        )
        if pinned_wheel["identical_bytes"]
        else None,
    }
