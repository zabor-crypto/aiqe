"""Who ran a measurement, recorded so that the measurement can be believed.

A green job proves nothing about a support surface unless the surface is
identified. `runner provenance` is part of that identity: a result produced on
a GitHub-hosted runner and a result produced on somebody's laptop are both
evidence, and they are not the same evidence.

Nothing here reads the network, and nothing here reads a private hostname:
the record is deliberately coarse. `platform.node()` is never consulted, and
neither is the user name. What the manifest needs is which *kind* of machine
this was, not which machine.
"""

import os
import platform
import subprocess
import sys

#: The evidence levels a surface observation can carry, weakest last.
#:
#: These are not adjectives. Each one names an exact thing that was executed,
#: and the support gate in `support.py` is written against these names rather
#: than against a feeling about how well tested something is.
FULL_SUITE = "FULL_SUITE"
INSTALLED_ARTIFACT_E2E = "INSTALLED_ARTIFACT_E2E"
BENCHMARK_FAMILIES = "BENCHMARK_FAMILIES"

#: A run that built and inspected artifacts but did not execute the workflow
#: from an installed one. It is a real measurement and it is not the same
#: claim, so it gets its own name rather than being filed under the level it
#: nearly reached.
ARTIFACT_BUILD_ONLY = "ARTIFACT_BUILD_ONLY"

LEVELS = (FULL_SUITE, INSTALLED_ARTIFACT_E2E, BENCHMARK_FAMILIES, ARTIFACT_BUILD_ONLY)


def _run(argv):
    """Return the first line of a command's output, or None."""
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.decode("utf-8", "replace").strip()
    return text.splitlines()[0] if text else None


def git_version():
    """The Git version this surface actually has, as Git reports it.

    The whole string is kept, not a parsed tuple. `git version 2.39.5 (Apple
    Git-154)` and `git version 2.39.5` are different builds, and a support
    claim that erased the difference would be claiming something it had not
    tested.
    """
    return _run(["git", "--version"])


def git_version_number():
    """The numeric part of the Git version, as a tuple, or None.

    Used for ordering surfaces, never for claiming a minimum: the lower bound
    AIQE publishes is a version that was actually exercised, not one inferred
    from a comparison.
    """
    reported = git_version()
    if not reported:
        return None
    for token in reported.split():
        parts = token.split(".")
        if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
            numbers = []
            for part in parts:
                if not part.isdigit():
                    break
                numbers.append(int(part))
            return tuple(numbers)
    return None


def os_family():
    """`macos`, `linux`, or the raw platform name.

    Windows is deliberately not mapped to a friendly name. It is out of scope
    for v1, and a record produced there should look unfamiliar.
    """
    return {"darwin": "macos", "linux": "linux"}.get(sys.platform, sys.platform)


def os_release():
    """A coarse OS release string.

    On macOS this is the product version. On Linux it is the distribution's
    own `ID` and `VERSION_ID` from os-release, which is the only place the
    distribution states its identity in a machine-readable way.
    """
    if sys.platform == "darwin":
        version = platform.mac_ver()[0]
        return "macOS %s" % (version,) if version else "macOS"
    if sys.platform == "linux":
        fields = {}
        try:
            with open("/etc/os-release", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    fields[key.strip()] = value.strip().strip('"')
        except OSError:
            return platform.platform(terse=True)
        identity = fields.get("ID")
        version = fields.get("VERSION_ID")
        if identity and version:
            return "%s %s" % (identity, version)
        return fields.get("PRETTY_NAME") or platform.platform(terse=True)
    return platform.platform(terse=True)


def runner_provenance():
    """Where this ran, at the coarsest useful resolution.

    GitHub Actions announces itself in the environment. Anything else is
    `local`, and the manifest says so rather than letting a laptop run be read
    as CI evidence.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        image = os.environ.get("ImageOS") or os.environ.get("RUNNER_OS") or "unknown"
        label = os.environ.get("AIQE_RUNNER_LABEL") or "unspecified"
        container = os.environ.get("AIQE_CONTAINER_IMAGE")
        provenance = "github-hosted runner %s (image %s)" % (label, image)
        if container:
            provenance += " in container %s" % (container,)
        return provenance
    return "local"


def ci_run_identity():
    """The CI run this record belongs to, or None outside CI.

    Run identifiers only. No token, no URL with a credential in it, and no
    private hostname.

    The repository namespace is deliberately not recorded. Nothing in the
    manifest, the gate or any comparator reads it, and no published surface
    shows it, so it is correlation the evidence does not need. What carries
    the authority is `sha` - bound to an object a test proves belongs to this
    repository - together with the run identifiers, which survive a rename or
    a transfer. A namespace retained here would only be a stale name for the
    project after any such move.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    identity = {
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
        "sha": os.environ.get("GITHUB_SHA"),
    }
    return {key: value for key, value in identity.items() if value}


def source_commit(root):
    """The commit the measured source came from.

    Returned as `unknown` rather than guessed. An artifact whose source commit
    cannot be established is not release evidence, and the manifest has to be
    able to say so.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.decode("ascii", "replace").strip() or "unknown"


def source_tree_clean(root):
    """Whether the measured checkout had uncommitted changes.

    A measurement taken from a dirty tree describes no commit. It is still
    worth recording - it is how this work is developed - but it must not be
    mistaken for evidence about a landed commit, so the flag travels with it.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace").strip() == ""


def describe(root):
    """The full environment identity for one measurement."""
    return {
        "os_family": os_family(),
        "os_release": os_release(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "python_minor": "%d.%d" % sys.version_info[:2],
        "python_implementation": platform.python_implementation(),
        "git_version": git_version(),
        "runner_provenance": runner_provenance(),
        "ci_run": ci_run_identity(),
        "source_commit": source_commit(root),
        "source_tree_clean": source_tree_clean(root),
    }
