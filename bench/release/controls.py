"""Negative controls for the release proof.

A gate that has never been shown to fail is not a gate. Each control here
builds an unsafe reference - an artifact or a matrix with a real defect in it -
and requires that the defect is actually detected. If a control stops
reproducing, the corresponding check has stopped working, and the release
proof says so instead of reporting a clean run.

The controls are deliberately about the failure modes that packaging
introduces and that no amount of source-tree testing can see:

    NC-PACKAGE-SOURCE-IMPORT   the test passed because `src/` was on the path
    NC-PACKAGE-PRIVATE-FILE    the build swept in a file nobody meant to ship
    NC-SUPPORT-CLAIM           the matrix claimed a surface nobody ran
"""

import json
import os
import shutil

from . import artifacts, harness
from .environment import FULL_SUITE, INSTALLED_ARTIFACT_E2E
from . import support


def _tampered_source(root, workdir, mutate):
    """An exported source tree with a deliberate defect applied."""
    source = os.path.join(workdir, "source")
    harness.export_source(root, source)
    mutate(source)
    return source


def nc_package_source_import(root, workdir, build_python):
    """A module missing from the artifact, invisible to a source-tree test.

    The unsafe reference is a wheel built without `aiqe/receipt.py` - the
    shape of a packaging configuration that stops matching the package. The
    two checks are then run against the same defect:

        the naive check imports `aiqe.receipt` with the source tree on the
        path, and passes, because the file is right there;

        the artifact check installs the wheel into a fresh environment and
        runs the real workflow from outside the source tree, and fails.

    The control reproduces when the naive check passes and the artifact check
    fails. Both halves matter: a naive check that also failed would mean the
    contrast being demonstrated does not exist.
    """
    missing_module = "receipt.py"

    def remove_module(source):
        os.remove(os.path.join(source, "src", "aiqe", missing_module))

    source = _tampered_source(root, workdir, remove_module)
    dist = os.path.join(workdir, "dist")
    os.makedirs(dist)
    built = harness.build_artifacts(source, dist, python=build_python)
    inspected = artifacts.inspect_wheel(built["wheel"])
    module_in_wheel = "aiqe/%s" % (missing_module,) in inspected["members"]

    # The naive check: imports resolve from the real checkout, which still has
    # the module. This is the check a project writes without thinking about
    # packaging, and it is why the defect ships.
    naive = harness.run(
        [
            build_python,
            "-c",
            "import aiqe.receipt; print(aiqe.receipt.__file__)",
        ],
        cwd=root,
        env=dict(os.environ, PYTHONPATH=os.path.join(root, "src")),
    )
    naive_passes = naive["returncode"] == 0

    # The artifact check: a fresh environment, the installed distribution, and
    # a working directory that is not the source tree.
    venv = os.path.join(workdir, "venv")
    python = harness.create_venv(venv)
    install_failed = None
    artifact_fails = False
    artifact_detail = ""
    try:
        harness.install_artifact(python, built["wheel"])
    except harness.ProofError as exc:
        install_failed = str(exc)
        artifact_fails = True
        artifact_detail = "installation itself failed"
    if install_failed is None:
        result = harness.installed_end_to_end(
            harness.venv_script(venv, "aiqe"),
            os.path.join(workdir, "e2e"),
            python,
        )
        artifact_fails = result["outcome"] != "PASS"
        artifact_detail = "; ".join(result["problems"])[:2000]

    reproduced = naive_passes and artifact_fails and not module_in_wheel
    return {
        "control": "NC-PACKAGE-SOURCE-IMPORT",
        "reproduced": reproduced,
        "defect": "aiqe/%s omitted from the built wheel" % (missing_module,),
        "module_present_in_wheel": module_in_wheel,
        "naive_source_tree_check_passes": naive_passes,
        "installed_artifact_check_fails": artifact_fails,
        "installed_artifact_detail": artifact_detail,
        "why": (
            "the naive check resolved the import from ./src and never looked "
            "at the artifact"
        ),
    }


PRIVATE_MARKER_NAME = "private-transcript.txt"
PRIVATE_MARKER_BODY = (
    "SYNTHETIC PRIVATE MARKER - release-proof negative control fixture.\n"
    "This file exists only inside a deliberately unsafe build. It never\n"
    "appears in the repository and never appears in a real artifact.\n"
)


def nc_package_private_file(root, workdir, build_python, clean_wheel):
    """A forbidden file swept into the artifact by a permissive package-data rule.

    The unsafe reference is the ordinary version of this mistake: a synthetic
    private file inside the package directory, and a `package-data` glob wide
    enough to collect it. The source tree scan is not the control here - the
    file is in that tree, so of course the scan sees it. The control is that
    the *artifact allowlist* rejects the member, because the realistic version
    of this defect is a file that was always in the tree legitimately and
    should never have left it.
    """

    def plant_private_file(source):
        with open(
            os.path.join(source, "src", "aiqe", PRIVATE_MARKER_NAME), "w", encoding="utf-8"
        ) as handle:
            handle.write(PRIVATE_MARKER_BODY)
        with open(os.path.join(source, "pyproject.toml"), "a", encoding="utf-8") as handle:
            handle.write(
                "\n# Unsafe reference: the 'just include the data files' rule.\n"
                "[tool.setuptools.package-data]\n"
                'aiqe = ["*.txt"]\n'
            )

    source = _tampered_source(root, workdir, plant_private_file)
    dist = os.path.join(workdir, "dist")
    os.makedirs(dist)
    built = harness.build_artifacts(source, dist, python=build_python)

    unsafe_wheel = artifacts.inspect_wheel(built["wheel"])
    unsafe_sdist = artifacts.inspect_sdist(built["sdist"])
    member = "aiqe/%s" % (PRIVATE_MARKER_NAME,)

    present = member in unsafe_wheel["members"]
    rejected = member in unsafe_wheel["disallowed_members"]
    clean_is_clean = not clean_wheel["disallowed_members"]

    # The scan is the second line, and it is exercised too: an extracted
    # unsafe wheel is a tree, and a tree can be scanned.
    extracted = os.path.join(workdir, "extracted")
    artifacts.extract_wheel(built["wheel"], extracted)
    scanner = os.path.join(root, "tools", "public-scan", "public-scan.sh")
    scan = harness.run([scanner, extracted])

    reproduced = present and rejected and clean_is_clean
    return {
        "control": "NC-PACKAGE-PRIVATE-FILE",
        "reproduced": reproduced,
        "defect": "a synthetic private file collected by a wide package-data glob",
        "member": member,
        "present_in_unsafe_wheel": present,
        "rejected_by_allowlist": rejected,
        "unsafe_wheel_disallowed_members": unsafe_wheel["disallowed_members"],
        "unsafe_sdist_disallowed_members": unsafe_sdist["disallowed_members"],
        "clean_wheel_has_no_disallowed_members": clean_is_clean,
        "extracted_tree_scan_returncode": scan["returncode"],
        "why": (
            "a source-tree scan cannot see a packaging decision; the artifact "
            "has to be inspected as an artifact"
        ),
    }


def nc_support_claim(minors=("3.11", "3.12", "3.13", "3.14"), os_families=("linux",)):
    """A matrix that tested the endpoints of a range and claimed the range.

    Pure, and therefore cheap enough to run everywhere. The unsafe reference
    is `support.naive_python_range`, which is the reasoning an ordinary CI
    matrix invites: 3.11 passed, 3.14 passed, so 3.11-3.14 is supported. The
    interior minors were never executed.

    The control reproduces when the naive rule calls an untested interior
    minor PROVEN and the gate calls it NOT_PROVEN.
    """
    minors = list(minors)
    os_families = list(os_families)
    endpoints = [minors[0], minors[-1]]
    observations = []
    for minor in endpoints:
        for family in os_families:
            for level in (FULL_SUITE, INSTALLED_ARTIFACT_E2E):
                observations.append(
                    {
                        "os_family": family,
                        "os_release": "%s (synthetic control)" % (family,),
                        "arch": "x86_64",
                        "python_minor": minor,
                        "python_version": "%s.0" % (minor,),
                        "git_version": "git version 0.0.0 (synthetic control)",
                        "level": level,
                        "outcome": "PASS",
                        "runner_provenance": "synthetic negative control",
                    }
                )

    naive = support.naive_python_range(observations, minors)
    gated = support.python_support(observations, minors, os_families)
    interior = minors[1:-1]

    naive_overclaims = [
        minor for minor in interior if naive.get(minor, {}).get("verdict") == support.PROVEN
    ]
    gate_refuses = [
        minor
        for minor in interior
        if gated.get(minor, {}).get("verdict") == support.NOT_PROVEN
    ]
    endpoints_still_proven = all(
        gated.get(minor, {}).get("verdict") == support.PROVEN for minor in endpoints
    )

    reproduced = (
        sorted(naive_overclaims) == sorted(interior)
        and sorted(gate_refuses) == sorted(interior)
        and endpoints_still_proven
    )
    return {
        "control": "NC-SUPPORT-CLAIM",
        "reproduced": reproduced,
        "defect": "a contiguous support range extrapolated from its endpoints",
        "observed_minors": endpoints,
        "claimed_minors": minors,
        "naive_verdicts": {minor: naive[minor]["verdict"] for minor in minors},
        "gated_verdicts": {minor: gated[minor]["verdict"] for minor in minors},
        "naive_overclaims": sorted(naive_overclaims),
        "gate_refuses": sorted(gate_refuses),
        "endpoints_still_proven": endpoints_still_proven,
        "why": (
            "the gate counts observations; it has no rule that turns two of "
            "them into four"
        ),
    }


def run_all(root, workdir, build_python, clean_wheel):
    """Every control, each in its own disposable directory."""
    results = []
    for name, runner in (
        (
            "source-import",
            lambda directory: nc_package_source_import(root, directory, build_python),
        ),
        (
            "private-file",
            lambda directory: nc_package_private_file(
                root, directory, build_python, clean_wheel
            ),
        ),
    ):
        directory = os.path.join(workdir, name)
        os.makedirs(directory)
        results.append(runner(directory))
    results.append(nc_support_claim())
    return results
