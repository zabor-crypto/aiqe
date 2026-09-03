#!/usr/bin/env python3
"""Turn a set of surface records into the release-proof manifest.

    python3 bench/aggregate-release-proof.py --surfaces <dir> --output manifest.json

Every surface record is one machine's account of what it actually executed.
This script combines them and applies the support gate: a claim survives only
if observations back it, and a claim that does not is written into the
manifest as NOT_PROVEN rather than dropped.

The manifest is evidence, not an announcement. It contains no secret and no
private hostname, and producing it publishes nothing.

Exit status is 0 when every surface passed and the manifest is internally
consistent, and 1 otherwise. A NOT_PROVEN claim is not by itself a failure -
recording one honestly is the script working - but `--require-all-claims`
makes it one, which is what the release gate uses.
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from release import claims, environment, support  # noqa: E402

SCHEMA_VERSION = 1


def load_surfaces(directory):
    records = []
    for path in sorted(glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)):
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("record_type") != "RELEASE_PROOF_SURFACE":
            continue
        record["_source_file"] = os.path.relpath(path, directory)
        records.append(record)
    return records


def _first(records, key, predicate=None):
    for record in records:
        value = record.get(key)
        if value and (predicate is None or predicate(record)):
            return value
    return None


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surfaces", required=True, help="directory of surface records")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--require-all-claims",
        action="store_true",
        help="fail when any claimed surface is NOT_PROVEN",
    )
    options = parser.parse_args(argv)

    surfaces = load_surfaces(options.surfaces)
    if not surfaces:
        sys.stderr.write("no surface records found under %s\n" % (options.surfaces,))
        return 2

    problems = []
    failed = [s for s in surfaces if s.get("outcome") != "PASS"]
    for surface in failed:
        problems.append(
            "surface %s reported %s: %s"
            % (surface["_source_file"], surface.get("outcome"), surface.get("problems"))
        )

    # --- The claims, gated ------------------------------------------------
    python_claims = support.python_support(
        surfaces, list(claims.CLAIMED_PYTHON_MINORS), list(claims.CLAIMED_OS_FAMILIES)
    )
    os_arch = support.os_arch_support(surfaces)
    git = support.git_boundary(surfaces)
    unproven_pythons = support.unproven(python_claims)

    # --- The artifact -----------------------------------------------------
    #
    # Artifact identity is taken from surfaces that actually built one. Every
    # such surface builds from the same source commit, so a disagreement
    # about the wheel's hash is a finding, not a detail to average away.
    artifact_surfaces = [s for s in surfaces if s.get("artifacts")]
    wheel_hashes = {}
    sdist_hashes = {}
    for surface in artifact_surfaces:
        wheel = surface["artifacts"]["wheel"]
        sdist = surface["artifacts"]["sdist"]
        wheel_hashes.setdefault(wheel["sha256"], []).append(
            "%s/%s/python %s" % (surface["os_family"], surface["arch"], surface["python_version"])
        )
        sdist_hashes.setdefault(sdist["sha256"], []).append(
            "%s/%s/python %s" % (surface["os_family"], surface["arch"], surface["python_version"])
        )

    commits = sorted({s.get("source_commit") for s in surfaces if s.get("source_commit")})
    if len(commits) > 1:
        problems.append("surfaces disagree about the source commit: %r" % (commits,))
    dirty = [s["_source_file"] for s in surfaces if s.get("source_tree_clean") is False]

    versions = sorted({s.get("aiqe_version") for s in artifact_surfaces if s.get("aiqe_version")})
    if len(versions) > 1:
        problems.append("surfaces disagree about the AIQE version: %r" % (versions,))

    reference = artifact_surfaces[0] if artifact_surfaces else None

    # --- Zero-tolerance readback -----------------------------------------
    totals = {}
    for surface in surfaces:
        for key, value in (surface.get("totals") or {}).items():
            totals[key] = totals.get(key, 0) + value
    nonzero = {key: value for key, value in totals.items() if value}
    for key, value in sorted(nonzero.items()):
        problems.append("zero-tolerance total %s is %d across all surfaces" % (key, value))

    # --- Scans ------------------------------------------------------------
    scan_results = []
    for surface in surfaces:
        for scan in surface.get("scans") or []:
            scan_results.append(
                {
                    "surface": surface["_source_file"],
                    "target": scan["target"],
                    "outcome": scan["outcome"],
                }
            )
    failed_scans = [scan for scan in scan_results if scan["outcome"] != "PASS"]

    # --- Negative controls -------------------------------------------------
    control_results = []
    for surface in surfaces:
        for control in surface.get("negative_controls") or []:
            control_results.append(
                {
                    "surface": surface["_source_file"],
                    "control": control["control"],
                    "reproduced": control["reproduced"],
                }
            )
    not_reproducing = [c for c in control_results if not c["reproduced"]]

    # --- Install paths ------------------------------------------------------
    install_paths = set()
    for surface in surfaces:
        install = surface.get("install") or {}
        for kind in ("wheel", "sdist"):
            if (install.get(kind) or {}).get("outcome") == "PASS":
                install_paths.add("pip install (%s)" % (kind,))
        uv = surface.get("uv") or {}
        if uv.get("outcome") == "PASS":
            install_paths.add("uv tool install (local wheel)")
            install_paths.add("uvx --from (local wheel)")

    reproducibility = next(
        (s["reproducibility"] for s in surfaces if s.get("reproducibility")), None
    )
    offline = [s["offline"] for s in surfaces if s.get("offline")]
    e2e = [s["e2e"] for s in surfaces if s.get("e2e")]

    ci_runs = []
    for surface in surfaces:
        if surface.get("ci_run"):
            entry = dict(surface["ci_run"])
            if entry not in ci_runs:
                ci_runs.append(entry)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "AIQE_RELEASE_PROOF_MANIFEST",
        "statement": (
            "This manifest is private release-proof evidence. It records what "
            "was built and what was executed against it. It is not a release "
            "announcement, nothing described here is published, and a claim "
            "absent from it is a claim that was not demonstrated."
        ),
        "source_commit": commits[0] if len(commits) == 1 else commits,
        "source_trees_with_uncommitted_changes": dirty,
        "aiqe_version": versions[0] if len(versions) == 1 else versions,
        "python_requirement": (
            reference["artifacts"]["wheel"]["requires_python"] if reference else None
        ),
        "declared_python_requirement": claims.REQUIRES_PYTHON,
        "runtime_dependency_count": len(
            (reference or {}).get("artifacts", {}).get("wheel", {}).get("requires_dist", [])
        ),
        "artifacts": {
            "wheel": {
                "filename": reference["artifacts"]["wheel"]["filename"],
                "sha256": reference["artifacts"]["wheel"]["sha256"],
                "size_bytes": reference["artifacts"]["wheel"]["size_bytes"],
                "tags": reference["artifacts"]["wheel"]["wheel_tags"],
                "root_is_purelib": reference["artifacts"]["wheel"]["root_is_purelib"],
                "console_scripts": reference["artifacts"]["wheel"]["console_scripts"],
                "license": reference["artifacts"]["wheel"]["license"],
                "member_count": reference["artifacts"]["wheel_member_count"],
                "disallowed_members": reference["artifacts"]["wheel"]["disallowed_members"],
            },
            "sdist": {
                "filename": reference["artifacts"]["sdist"]["filename"],
                "sha256": reference["artifacts"]["sdist"]["sha256"],
                "size_bytes": reference["artifacts"]["sdist"]["size_bytes"],
                "member_count": reference["artifacts"]["sdist_member_count"],
                "disallowed_members": reference["artifacts"]["sdist"]["disallowed_members"],
            },
        }
        if reference
        else None,
        "artifact_hash_agreement": {
            "wheel": {
                "distinct_hashes": len(wheel_hashes),
                "by_hash": wheel_hashes,
                "note": (
                    "A pure-Python wheel built from one commit should have one "
                    "hash on every surface only when the build procedure fixes "
                    "timestamps. Where it does not, the hashes differ while the "
                    "packaged content does not; see `reproducibility`."
                ),
            },
            "sdist": {"distinct_hashes": len(sdist_hashes), "by_hash": sdist_hashes},
        },
        "build_tool": (reference or {}).get("build_tool"),
        "build_backend": "setuptools.build_meta (requires setuptools>=61)",
        "tested_install_paths": sorted(install_paths),
        "tested_os_arch_surfaces": os_arch,
        "git_compatibility": git,
        "python_support": python_claims,
        "python_support_rule": (
            "A Python minor is PROVEN only with both a full-suite run and an "
            "installed-artifact end-to-end run, on every claimed OS family. "
            "Nothing is inferred from the endpoints of a range."
        ),
        "out_of_scope": list(claims.OUT_OF_SCOPE),
        "installed_artifact_e2e": {
            "runs": len(e2e),
            "all_reviewable": all(
                run.get("receipt_verdict") == "REVIEWABLE" for run in e2e
            )
            if e2e
            else False,
            "verdicts": sorted({run.get("receipt_verdict") for run in e2e}),
        },
        "offline_runtime": {
            "runs": len(offline),
            "all_pass": all(run.get("outcome") == "PASS" for run in offline)
            if offline
            else False,
            "canary_armed_everywhere": all(run.get("canary_armed") for run in offline)
            if offline
            else False,
            "network_attempts": sum(len(run.get("network_attempts") or []) for run in offline),
            "scope": (
                "AIQE runtime only. Obtaining AIQE, uv or any other tool from "
                "an index uses the network by definition; that is installation, "
                "and it is not claimed to be offline."
            ),
        },
        "reproducibility": reproducibility,
        "public_scan": {
            "results": scan_results,
            "all_pass": not failed_scans,
            "targets": sorted({scan["target"] for scan in scan_results}),
            "note": (
                "The scan is a pattern floor over text. The artifact allowlist "
                "is the check that catches a file no pattern describes; the "
                "NC-PACKAGE-PRIVATE-FILE control demonstrates the difference."
            ),
        },
        "negative_controls": {
            "results": control_results,
            "total": len(control_results),
            "reproducing": len(control_results) - len(not_reproducing),
            "not_reproducing": [c["control"] for c in not_reproducing],
        },
        "ci_runs": ci_runs,
        "surfaces": [
            {
                "record": surface["_source_file"],
                "level": surface.get("level"),
                "outcome": surface.get("outcome"),
                "os_family": surface.get("os_family"),
                "os_release": surface.get("os_release"),
                "arch": surface.get("arch"),
                "python_version": surface.get("python_version"),
                "git_version": surface.get("git_version"),
                "runner_provenance": surface.get("runner_provenance"),
                "parts_run": surface.get("parts_run"),
                "parts_not_run": surface.get("parts_not_run"),
                "tests_run": surface.get("tests_run"),
                "tests_skipped": surface.get("tests_skipped"),
                "skips": [skip["test"] for skip in surface.get("skips") or []],
                "duration_seconds": surface.get("duration_seconds"),
            }
            for surface in surfaces
        ],
        "zero_tolerance_totals": totals,
        "problems": problems,
        "unproven_python_minors": unproven_pythons,
    }

    if options.require_all_claims and unproven_pythons:
        problems.append(
            "claimed Python minors without evidence: %s" % (", ".join(unproven_pythons),)
        )
    manifest["problems"] = problems
    manifest["outcome"] = "PASS" if not problems else "FAIL"

    with open(options.output, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")

    sys.stdout.write("release-proof manifest %s\n" % (manifest["outcome"],))
    sys.stdout.write("  surfaces        %d (%d failed)\n" % (len(surfaces), len(failed)))
    sys.stdout.write("  source commit   %s\n" % (manifest["source_commit"],))
    sys.stdout.write("  aiqe version    %s\n" % (manifest["aiqe_version"],))
    for minor in claims.CLAIMED_PYTHON_MINORS:
        sys.stdout.write(
            "  python %-5s    %s\n" % (minor, python_claims[minor]["verdict"])
        )
    for surface in os_arch:
        sys.stdout.write(
            "  surface         %s %s / %s / %s\n"
            % (
                surface["os_family"],
                surface["os_release"],
                surface["arch"],
                ",".join(surface["levels"]),
            )
        )
    sys.stdout.write(
        "  git exercised   %s\n" % (", ".join(e["git_version"] for e in git["exercised"]) or "none",)
    )
    for problem in problems:
        sys.stdout.write("  PROBLEM  %s\n" % (problem,))
    sys.stdout.write("  wrote %s\n" % (options.output,))
    return 0 if manifest["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
