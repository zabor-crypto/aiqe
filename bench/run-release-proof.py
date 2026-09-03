#!/usr/bin/env python3
"""Prove, on this surface, that the artifact a user would install works.

    python3 bench/run-release-proof.py --output surface.json
    python3 bench/run-release-proof.py --parts artifacts,install,e2e,scan --output s.json

One run produces one *surface record*: what this machine is, what was built
here, what was installed here, and what was executed against it. The record is
the unit of support evidence, and `bench/aggregate-release-proof.py` turns a
set of them into the release-proof manifest.

Parts can be selected, and the record always states which parts ran and which
did not. That is the point of naming them: a part that did not run is absent
from the evidence rather than silently counted as a pass.

Exit status is 0 when every part that ran passed, and 1 otherwise.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from release import artifacts, controls, environment, harness  # noqa: E402

ALL_PARTS = ("artifacts", "install", "e2e", "offline", "uv", "reproducibility", "scan", "controls")

#: Quantities that must be zero for a surface to count as evidence. They are
#: counted rather than asserted so that the record says *how* wrong a failing
#: run was, not merely that it failed.
ZERO_TOLERANCE = (
    "disallowed_wheel_members",
    "disallowed_sdist_members",
    "third_party_runtime_dependencies",
    "network_attempts",
    "failed_artifact_scans",
    "negative_controls_not_reproducing",
    "end_to_end_problems",
    "install_failures",
)


def scan_tree(root, target):
    scanner = os.path.join(root, "tools", "public-scan", "public-scan.sh")
    result = harness.run([scanner, target], timeout=600)
    return {
        "target": os.path.basename(target.rstrip("/")) or target,
        "returncode": result["returncode"],
        "outcome": "PASS" if result["returncode"] == 0 else "FAIL",
        "tail": result["stdout"].strip().splitlines()[-3:],
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="where to write the surface record")
    parser.add_argument(
        "--parts",
        default=",".join(ALL_PARTS),
        help="comma-separated subset of: %s" % (", ".join(ALL_PARTS),),
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="leave the scratch directory in place for inspection",
    )
    options = parser.parse_args(argv)

    requested = [part.strip() for part in options.parts.split(",") if part.strip()]
    unknown = [part for part in requested if part not in ALL_PARTS]
    if unknown:
        parser.error("unknown part(s): %s" % (", ".join(unknown),))

    started = time.time()
    workdir = tempfile.mkdtemp(prefix="aiqe-release-proof-")
    record = {
        "schema_version": 1,
        "record_type": "RELEASE_PROOF_SURFACE",
        "level": environment.INSTALLED_ARTIFACT_E2E,
        "parts_requested": requested,
        "parts_run": [],
        "parts_not_run": [part for part in ALL_PARTS if part not in requested],
    }
    record.update(environment.describe(ROOT))
    problems = []
    totals = dict.fromkeys(ZERO_TOLERANCE, 0)

    try:
        # Every part needs a build environment and a built artifact, because
        # every claim here is about an artifact rather than about the tree.
        build_venv = os.path.join(workdir, "buildenv")
        build_python = harness.create_venv(build_venv)
        installed_build_tool = harness.run(
            [build_python, "-m", "pip", "install", "--quiet", "build"], timeout=600
        )
        if installed_build_tool["returncode"] != 0:
            raise harness.ProofError(
                "could not install the build front end: %s"
                % installed_build_tool["stderr"][-2000:]
            )
        record["build_tool"] = [
            entry
            for entry in harness.frozen_packages(build_python)
            if entry.split("==")[0].lower() in {"build", "packaging", "pyproject-hooks", "setuptools", "wheel", "pip"}
        ]

        source = os.path.join(workdir, "source")
        _, tracked = harness.export_source(ROOT, source)
        record["source_tracked_files"] = tracked

        dist = os.path.join(workdir, "dist")
        os.makedirs(dist)
        built = harness.build_artifacts(source, dist, python=build_python)
        wheel_report = artifacts.inspect_wheel(built["wheel"])
        sdist_report = artifacts.inspect_sdist(built["sdist"])
        record["artifacts"] = {
            "wheel": {k: v for k, v in wheel_report.items() if k != "members"},
            "sdist": {k: v for k, v in sdist_report.items() if k != "members"},
            "wheel_member_count": len(wheel_report["members"]),
            "sdist_member_count": len(sdist_report["members"]),
        }
        record["aiqe_version"] = wheel_report["version"]

        if "artifacts" in requested:
            record["parts_run"].append("artifacts")
            totals["disallowed_wheel_members"] = len(wheel_report["disallowed_members"])
            totals["disallowed_sdist_members"] = len(sdist_report["disallowed_members"])
            checks = []
            if wheel_report["wheel_tags"] != ["py3-none-any"]:
                checks.append("wheel tag is %r, expected py3-none-any" % (wheel_report["wheel_tags"],))
            if wheel_report["root_is_purelib"] != "true":
                checks.append("wheel is not pure-lib")
            if wheel_report["console_scripts"] != {"aiqe": "aiqe.cli:main_entry"}:
                checks.append("console scripts are %r" % (wheel_report["console_scripts"],))
            if wheel_report["requires_python"] != ">=3.11":
                checks.append("Requires-Python is %r" % (wheel_report["requires_python"],))
            if wheel_report["requires_dist"]:
                checks.append("wheel declares dependencies: %r" % (wheel_report["requires_dist"],))
            if wheel_report["license"] != "Apache-2.0":
                checks.append("wheel license metadata is %r" % (wheel_report["license"],))
            if not wheel_report["license_files"]:
                checks.append("wheel carries no license file")
            if wheel_report["description_content_type"] != "text/markdown":
                checks.append(
                    "README metadata content type is %r"
                    % (wheel_report["description_content_type"],)
                )
            if any("Operating System" in c for c in wheel_report["classifiers"]):
                checks.append(
                    "metadata carries an Operating System classifier, which would "
                    "claim a support surface: %r" % (wheel_report["classifiers"],)
                )
            if any(
                "Windows" in classifier for classifier in wheel_report["classifiers"]
            ):
                checks.append("metadata mentions Windows, which is out of scope for v1")
            record["artifact_checks"] = checks
            problems.extend(checks)

        wheel_venv = None
        wheel_python = None
        if "install" in requested or "e2e" in requested or "offline" in requested:
            # An environment is needed by any of the three, but only `install`
            # being requested makes the installation itself part of the
            # evidence this record claims to carry.
            if "install" in requested:
                record["parts_run"].append("install")
            install_report = {}
            wheel_venv = os.path.join(workdir, "wheel-venv")
            wheel_python = harness.create_venv(wheel_venv)
            try:
                harness.install_artifact(wheel_python, built["wheel"])
                install_report["wheel"] = {
                    "outcome": "PASS",
                    "location": harness.installed_location(wheel_python),
                    "third_party_dependencies": harness.third_party_dependencies(wheel_python),
                    "frozen": harness.frozen_packages(wheel_python),
                }
            except harness.ProofError as exc:
                install_report["wheel"] = {"outcome": "FAIL", "detail": str(exc)[:2000]}
                totals["install_failures"] += 1
                problems.append("wheel install failed")

            sdist_venv = os.path.join(workdir, "sdist-venv")
            sdist_python = harness.create_venv(sdist_venv)
            try:
                harness.install_artifact(sdist_python, built["sdist"])
                install_report["sdist"] = {
                    "outcome": "PASS",
                    "location": harness.installed_location(sdist_python),
                    "third_party_dependencies": harness.third_party_dependencies(sdist_python),
                }
            except harness.ProofError as exc:
                install_report["sdist"] = {"outcome": "FAIL", "detail": str(exc)[:2000]}
                totals["install_failures"] += 1
                problems.append("sdist install failed")

            third_party = set()
            for entry in install_report.values():
                third_party.update(entry.get("third_party_dependencies") or [])
            totals["third_party_runtime_dependencies"] = len(third_party)
            install_report["third_party_dependencies_union"] = sorted(third_party)
            record["install"] = install_report

        if "e2e" in requested:
            record["parts_run"].append("e2e")
            if wheel_python is None:
                problems.append("end-to-end requested without an installed artifact")
            else:
                e2e = harness.installed_end_to_end(
                    harness.venv_script(wheel_venv, "aiqe"),
                    os.path.join(workdir, "e2e"),
                    wheel_python,
                )
                record["e2e"] = e2e
                totals["end_to_end_problems"] = len(e2e["problems"])
                problems.extend(e2e["problems"])

        if "offline" in requested:
            record["parts_run"].append("offline")
            if wheel_python is None:
                problems.append("offline proof requested without an installed artifact")
            else:
                offline = harness.offline_core_proof(
                    wheel_venv,
                    harness.venv_script(wheel_venv, "aiqe"),
                    os.path.join(workdir, "offline"),
                    wheel_python,
                )
                record["offline"] = offline
                totals["network_attempts"] = len(offline["network_attempts"])
                problems.extend(offline["problems"])

        if "uv" in requested:
            record["parts_run"].append("uv")
            uv = harness.uv_proof(
                os.path.join(workdir, "uv"), built["wheel"], wheel_python or build_python
            )
            record["uv"] = uv
            problems.extend(uv["problems"])

        if "reproducibility" in requested:
            record["parts_run"].append("reproducibility")
            repro_dir = os.path.join(workdir, "repro")
            os.makedirs(repro_dir)
            record["reproducibility"] = harness.reproducibility(ROOT, repro_dir, build_python)
            if record["reproducibility"]["affects_artifact_integrity"]:
                problems.append(
                    "two builds of the same source produced different packaged content"
                )

        if "scan" in requested:
            record["parts_run"].append("scan")
            extracted_wheel = os.path.join(workdir, "extracted-wheel")
            extracted_sdist = os.path.join(workdir, "extracted-sdist")
            artifacts.extract_wheel(built["wheel"], extracted_wheel)
            artifacts.extract_sdist(built["sdist"], extracted_sdist)
            scans = [
                scan_tree(ROOT, ROOT),
                scan_tree(ROOT, extracted_sdist),
                scan_tree(ROOT, extracted_wheel),
            ]
            record["scans"] = scans
            failed = [scan for scan in scans if scan["outcome"] != "PASS"]
            totals["failed_artifact_scans"] = len(failed)
            problems.extend("public scan failed on %s" % (scan["target"],) for scan in failed)

        if "controls" in requested:
            record["parts_run"].append("controls")
            control_dir = os.path.join(workdir, "controls")
            os.makedirs(control_dir)
            results = controls.run_all(ROOT, control_dir, build_python, wheel_report)
            record["negative_controls"] = results
            not_reproducing = [r["control"] for r in results if not r["reproduced"]]
            totals["negative_controls_not_reproducing"] = len(not_reproducing)
            problems.extend(
                "negative control %s did not reproduce" % (name,) for name in not_reproducing
            )

    except harness.ProofError as exc:
        problems.append("release proof could not run: %s" % (exc,))
    except Exception as exc:  # pragma: no cover - defensive
        problems.append("release proof raised %s: %s" % (type(exc).__name__, exc))
    finally:
        if options.keep_workdir:
            record["workdir"] = workdir
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    # The level this record may claim is decided by what ran, not by what the
    # runner is called. A job that built an artifact and never executed it is
    # evidence about the build, and filing it under the end-to-end level would
    # let a reduced job stand in for a full one - exactly the substitution the
    # support gate exists to prevent.
    record["level"] = (
        environment.INSTALLED_ARTIFACT_E2E
        if "e2e" in record["parts_run"]
        else environment.ARTIFACT_BUILD_ONLY
    )
    record["totals"] = totals
    record["problems"] = problems
    record["outcome"] = "PASS" if not problems and not any(totals.values()) else "FAIL"
    record["duration_seconds"] = round(time.time() - started, 1)

    with open(options.output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")

    sys.stdout.write(
        "release proof %s on %s %s / %s / python %s / %s\n"
        % (
            record["outcome"],
            record["os_family"],
            record["os_release"],
            record["arch"],
            record["python_version"],
            record["git_version"],
        )
    )
    sys.stdout.write("  parts run     %s\n" % (", ".join(record["parts_run"]) or "none",))
    if record["parts_not_run"]:
        sys.stdout.write("  parts NOT run %s\n" % (", ".join(record["parts_not_run"]),))
    for name in ZERO_TOLERANCE:
        sys.stdout.write("  %-34s %d\n" % (name, totals[name]))
    for problem in problems:
        sys.stdout.write("  PROBLEM  %s\n" % (problem,))
    sys.stdout.write("  wrote %s\n" % (options.output,))
    return 0 if record["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
