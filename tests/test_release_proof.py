"""The release proof's own logic, tested where it is cheap to test.

The expensive half of the release proof - building artifacts, creating
environments, installing distributions - runs in CI as its own job, on every
surface whose support is claimed. What lives here is the half that decides
what those runs *mean*: the allowlist a built artifact is measured against,
and the gate that turns observations into support claims or refuses to.

That split is deliberate. The gate is the component that says NOT_PROVEN, and
a gate whose logic is only ever exercised by a passing CI run has never been
shown to refuse anything.
"""

import os
import re
import unittest

from . import support as test_support

from release import artifacts, claims, controls, environment, support


class ArtifactAllowlistTests(unittest.TestCase):
    """What may appear inside a built distribution, and what may not."""

    def _disallowed(self, members, allowed):
        return artifacts._disallowed(members, allowed)

    def test_the_real_wheel_shape_is_allowed(self):
        members = [
            "aiqe/__init__.py",
            "aiqe/cli.py",
            "aiqe/receipt.py",
            "aiqe-0.1.0a0.dist-info/METADATA",
            "aiqe-0.1.0a0.dist-info/RECORD",
            "aiqe-0.1.0a0.dist-info/WHEEL",
            "aiqe-0.1.0a0.dist-info/entry_points.txt",
            "aiqe-0.1.0a0.dist-info/top_level.txt",
            "aiqe-0.1.0a0.dist-info/licenses/LICENSE",
        ]
        self.assertEqual(self._disallowed(members, artifacts.WHEEL_ALLOWED), [])

    def test_a_wheel_may_not_carry_anything_but_modules_and_metadata(self):
        """Each of these is a real way a private file reaches an artifact."""
        for member in (
            "aiqe/private-transcript.txt",
            "aiqe/.aiqe/task.json",
            "aiqe/data/secrets.json",
            ".git/config",
            "bench/results/commit/results.json",
            "aiqe-0.1.0a0.dist-info/AUTHORS.private",
            "aiqe/cli.pyc",
            "aiqe/subpackage/__init__.py",
        ):
            with self.subTest(member=member):
                self.assertEqual(
                    self._disallowed([member], artifacts.WHEEL_ALLOWED), [member]
                )

    def test_the_real_sdist_shape_is_allowed(self):
        members = [
            "LICENSE",
            "MANIFEST.in",
            "PKG-INFO",
            "README.md",
            "pyproject.toml",
            "setup.cfg",
            "src/aiqe/__init__.py",
            "src/aiqe/cli.py",
            "src/aiqe.egg-info/PKG-INFO",
            "src/aiqe.egg-info/SOURCES.txt",
            "src/aiqe.egg-info/dependency_links.txt",
            "src/aiqe.egg-info/entry_points.txt",
            "src/aiqe.egg-info/top_level.txt",
        ]
        self.assertEqual(self._disallowed(members, artifacts.SDIST_ALLOWED), [])

    def test_a_partial_test_tree_is_not_allowed_into_an_sdist(self):
        """The defect this project actually had, kept as a test.

        setuptools' default manifest collects `tests/test*.py` and nothing
        else from that directory, producing a test package that cannot be
        imported. `MANIFEST.in` prunes it; if that prune ever stops working,
        the allowlist is what notices.
        """
        self.assertEqual(
            self._disallowed(["tests/test_cli.py"], artifacts.SDIST_ALLOWED),
            ["tests/test_cli.py"],
        )

    def test_the_manifest_in_prunes_the_test_directory(self):
        path = os.path.join(test_support.ROOT, "MANIFEST.in")
        with open(path, encoding="utf-8") as handle:
            self.assertIn("prune tests", handle.read())


class SupportGateTests(unittest.TestCase):
    """The rule that turns observations into claims, and the things it refuses."""

    def observation(self, **overrides):
        record = {
            "os_family": "linux",
            "os_release": "ubuntu 24.04",
            "arch": "x86_64",
            "python_minor": "3.12",
            "python_version": "3.12.7",
            "git_version": "git version 2.43.0",
            "level": environment.FULL_SUITE,
            "outcome": "PASS",
            "runner_provenance": "github-hosted runner",
        }
        record.update(overrides)
        return record

    def both_levels(self, **overrides):
        return [
            self.observation(level=level, **overrides)
            for level in support.REQUIRED_PYTHON_LEVELS
        ]

    def test_both_levels_on_the_only_claimed_family_is_proven(self):
        result = support.python_support(self.both_levels(), ["3.12"], ["linux"])
        self.assertEqual(result["3.12"]["verdict"], support.PROVEN)
        self.assertEqual(result["3.12"]["missing"], [])

    def test_the_full_suite_alone_is_not_enough(self):
        """It proves the source tree runs; it says nothing about the artifact."""
        result = support.python_support(
            [self.observation(level=environment.FULL_SUITE)], ["3.12"], ["linux"]
        )
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)
        self.assertEqual(
            result["3.12"]["missing"], ["%s on linux" % environment.INSTALLED_ARTIFACT_E2E]
        )

    def test_the_installed_end_to_end_alone_is_not_enough(self):
        """It proves the artifact starts; it says nothing about the behaviour."""
        result = support.python_support(
            [self.observation(level=environment.INSTALLED_ARTIFACT_E2E)],
            ["3.12"],
            ["linux"],
        )
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)

    def test_one_family_does_not_prove_another(self):
        result = support.python_support(
            self.both_levels(os_family="linux"), ["3.12"], ["linux", "macos"]
        )
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)
        self.assertIn("%s on macos" % environment.FULL_SUITE, result["3.12"]["missing"])

    def test_a_failing_observation_is_not_evidence(self):
        failing = [dict(o, outcome="FAIL") for o in self.both_levels()]
        result = support.python_support(failing, ["3.12"], ["linux"])
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)

    def test_a_skipped_observation_is_not_evidence(self):
        skipped = [dict(o, outcome="SKIPPED") for o in self.both_levels()]
        result = support.python_support(skipped, ["3.12"], ["linux"])
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)

    def test_a_proven_claim_names_the_observations_that_proved_it(self):
        result = support.python_support(self.both_levels(), ["3.12"], ["linux"])
        self.assertTrue(result["3.12"]["evidence"])
        for entry in result["3.12"]["evidence"]:
            self.assertIn("3.12.7", entry)

    def test_architectures_are_never_merged(self):
        """A pure-Python wheel is not an argument about a processor."""
        observations = self.both_levels(arch="x86_64") + self.both_levels(arch="arm64")
        surfaces = support.os_arch_support(observations)
        self.assertEqual(sorted(s["arch"] for s in surfaces), ["arm64", "x86_64"])

    def test_the_git_boundary_claims_no_minimum(self):
        result = support.git_boundary(self.both_levels())
        self.assertIsNone(result["minimum_claimed"])
        self.assertEqual(result["minimum_status"], support.NOT_PROVEN)
        self.assertEqual(result["lowest_exercised"], "git version 2.43.0")

    def test_the_git_boundary_orders_versions_numerically(self):
        observations = (
            self.both_levels(git_version="git version 2.9.5")
            + self.both_levels(git_version="git version 2.43.0")
            + self.both_levels(git_version="git version 2.30.2")
        )
        result = support.git_boundary(observations)
        self.assertEqual(result["lowest_exercised"], "git version 2.9.5")
        self.assertEqual(result["highest_exercised"], "git version 2.43.0")


class SupportClaimNegativeControlTests(unittest.TestCase):
    """NC-SUPPORT-CLAIM: the extrapolation, and the refusal to make it."""

    def test_the_control_reproduces(self):
        result = controls.nc_support_claim()
        self.assertTrue(result["reproduced"], result)

    def test_the_naive_rule_really_does_overclaim(self):
        """A control that did not fail in the unsafe reference proves nothing."""
        result = controls.nc_support_claim()
        self.assertEqual(result["naive_overclaims"], ["3.12", "3.13"])
        self.assertEqual(
            [result["naive_verdicts"][minor] for minor in ("3.12", "3.13")],
            [support.PROVEN, support.PROVEN],
        )

    def test_the_gate_refuses_exactly_the_untested_interior(self):
        result = controls.nc_support_claim()
        self.assertEqual(result["gate_refuses"], ["3.12", "3.13"])
        self.assertTrue(result["endpoints_still_proven"])


class ClaimConsistencyTests(unittest.TestCase):
    """The claims the project makes must agree wherever they are written down."""

    def test_the_declared_python_floor_matches_pyproject(self):
        path = os.path.join(test_support.ROOT, "pyproject.toml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn('requires-python = "%s"' % (claims.REQUIRES_PYTHON,), content)

    def test_every_claimed_minor_has_a_classifier(self):
        path = os.path.join(test_support.ROOT, "pyproject.toml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        for minor in claims.CLAIMED_PYTHON_MINORS:
            self.assertIn("Programming Language :: Python :: %s" % (minor,), content)

    def test_no_operating_system_classifier_is_declared(self):
        """A classifier is a support claim, and this project's are gated."""
        path = os.path.join(test_support.ROOT, "pyproject.toml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertNotIn("Operating System ::", content)

    def test_windows_is_not_claimed_anywhere_in_package_metadata(self):
        path = os.path.join(test_support.ROOT, "pyproject.toml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read().lower()
        self.assertNotIn("windows", content)


def _matrix_python_lists(workflow):
    """Every `python: [...]` list declared in the workflow.

    A deliberately small reader rather than a YAML parser: this project has no
    third-party test dependency, and the file it reads is one this repository
    controls.
    """
    return [
        [item.strip().strip('"').strip("'") for item in match.split(",")]
        for match in re.findall(r"^\s*python:\s*\[([^\]]*)\]", workflow, re.M)
    ]


def _matrix_os_lists(workflow):
    return [
        [item.strip().strip('"').strip("'") for item in match.split(",")]
        for match in re.findall(r"^\s*os:\s*\[([^\]]*)\]", workflow, re.M)
    ]


class WorkflowCoversTheClaimTests(unittest.TestCase):
    """The matrix has to contain the evidence the claims need.

    Without this, widening a claim and forgetting to widen CI produces a
    NOT_PROVEN in the manifest that somebody then argues with. Failing here
    instead makes the missing job the finding.
    """

    def setUp(self):
        path = os.path.join(test_support.ROOT, ".github", "workflows", "checks.yml")
        with open(path, encoding="utf-8") as handle:
            self.workflow = handle.read()

    def test_every_claimed_python_minor_appears_in_a_matrix(self):
        declared = set()
        for entries in _matrix_python_lists(self.workflow):
            declared.update(entries)
        missing = sorted(set(claims.CLAIMED_PYTHON_MINORS) - declared)
        self.assertEqual(missing, [], "CI declares no job for these claimed minors")

    def test_the_suite_and_the_release_proof_both_run_every_claimed_minor(self):
        lists = _matrix_python_lists(self.workflow)
        self.assertTrue(lists, "no python matrix found in the workflow")
        for entries in lists:
            missing = sorted(set(claims.CLAIMED_PYTHON_MINORS) - set(entries))
            self.assertEqual(
                missing,
                [],
                "a python matrix omits claimed minors: %r" % (entries,),
            )

    def test_both_claimed_os_families_appear_in_the_matrix(self):
        declared = " ".join(" ".join(entry) for entry in _matrix_os_lists(self.workflow))
        self.assertIn("macos", declared)
        self.assertIn("ubuntu", declared)

    def test_the_release_proof_runner_is_invoked(self):
        self.assertIn("bench/run-release-proof.py", self.workflow)
        self.assertIn("bench/aggregate-release-proof.py", self.workflow)
        self.assertIn("bench/run-suite.py", self.workflow)


class RetainedManifestTests(unittest.TestCase):
    """The retained release-proof manifest, and the scanner exception it earns.

    `tools/public-scan/public-scan.sh` does not apply its `GIT_SHA_40` class to
    this file, because the manifest's job is to name the commit an artifact was
    built from. That exception is only defensible with a stronger check in its
    place, and this is it: every 40-character object id in the manifest must be
    an object that exists in *this* repository. An id from anywhere else - the
    thing the pattern class exists to catch - fails here.
    """

    MANIFEST = os.path.join(
        test_support.ROOT, "bench", "results", "release", "release-proof.json"
    )

    def setUp(self):
        import json

        with open(self.MANIFEST, encoding="utf-8") as handle:
            self.raw = handle.read()
        self.manifest = json.loads(self.raw)

    def test_the_manifest_exists_and_identifies_itself(self):
        self.assertEqual(
            self.manifest["record_type"], "AIQE_RELEASE_PROOF_MANIFEST"
        )

    def test_every_object_id_in_the_manifest_belongs_to_this_repository(self):
        import subprocess

        identifiers = sorted(set(re.findall(r"\b[0-9a-f]{40}\b", self.raw)))
        self.assertTrue(identifiers, "the manifest records no source commit")
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                completed = subprocess.run(
                    ["git", "-C", test_support.ROOT, "cat-file", "-t", identifier],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "object id %s in the manifest is not an object in this "
                    "repository" % (identifier,),
                )

    def test_the_manifest_carries_every_field_the_release_proof_owes(self):
        """The fields a release-proof manifest is required to contain."""
        for field in (
            "source_commit",
            "aiqe_version",
            "artifacts",
            "python_requirement",
            "runtime_dependency_count",
            "build_tool",
            "build_backend",
            "tested_install_paths",
            "tested_os_arch_surfaces",
            "git_compatibility",
            "python_support",
            "ci_runs",
            "public_scan",
            "reproducibility",
            "negative_controls",
            "out_of_scope",
        ):
            self.assertIn(field, self.manifest, field)
        for kind in ("wheel", "sdist"):
            self.assertIn("filename", self.manifest["artifacts"][kind])
            self.assertIn("sha256", self.manifest["artifacts"][kind])
            self.assertRegex(self.manifest["artifacts"][kind]["sha256"], r"^[0-9a-f]{64}$")

    def test_the_manifest_states_that_it_publishes_nothing(self):
        self.assertIn("not a release announcement", self.manifest["statement"])

    def test_the_manifest_carries_no_dependency(self):
        self.assertEqual(self.manifest["runtime_dependency_count"], 0)

    def test_the_manifest_agrees_with_the_declared_python_floor(self):
        self.assertEqual(
            self.manifest["python_requirement"], claims.REQUIRES_PYTHON
        )

    def test_windows_is_recorded_as_out_of_scope(self):
        self.assertIn("windows", self.manifest["out_of_scope"])

    def test_no_git_minimum_is_claimed(self):
        self.assertIsNone(self.manifest["git_compatibility"]["minimum_claimed"])
        self.assertEqual(
            self.manifest["git_compatibility"]["minimum_status"], support.NOT_PROVEN
        )


if __name__ == "__main__":
    unittest.main()
