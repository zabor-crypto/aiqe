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
        """The artifact evidence is required on every claimed family."""
        result = support.python_support(
            self.both_levels(os_family="linux"), ["3.12"], ["linux", "macos"]
        )
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)
        self.assertIn(
            "%s on macos" % environment.INSTALLED_ARTIFACT_E2E,
            result["3.12"]["missing"],
        )

    def test_the_documented_tiering_is_what_the_gate_applies(self):
        """The installed artifact everywhere; the full suite somewhere.

        This is the tiering, stated as a test so that it is a decision rather
        than an accident of how the matrix happens to be configured.
        """
        observations = [
            self.observation(os_family="linux", level=environment.FULL_SUITE),
            self.observation(
                os_family="linux", level=environment.INSTALLED_ARTIFACT_E2E
            ),
            self.observation(
                os_family="macos", level=environment.INSTALLED_ARTIFACT_E2E
            ),
        ]
        result = support.python_support(observations, ["3.12"], ["linux", "macos"])
        self.assertEqual(result["3.12"]["verdict"], support.PROVEN)
        self.assertEqual(
            result["3.12"]["families_by_level"][environment.FULL_SUITE], ["linux"]
        )
        self.assertEqual(
            result["3.12"]["families_by_level"][environment.INSTALLED_ARTIFACT_E2E],
            ["linux", "macos"],
        )

    def test_the_artifact_evidence_is_not_tiered_away(self):
        """Dropping the end-to-end on one family must not still say PROVEN."""
        observations = [
            self.observation(os_family="linux", level=environment.FULL_SUITE),
            self.observation(
                os_family="linux", level=environment.INSTALLED_ARTIFACT_E2E
            ),
        ]
        result = support.python_support(observations, ["3.12"], ["linux", "macos"])
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)

    def test_the_full_suite_is_required_somewhere(self):
        """The end-to-end on both families is still not the whole claim."""
        observations = [
            self.observation(
                os_family=family, level=environment.INSTALLED_ARTIFACT_E2E
            )
            for family in ("linux", "macos")
        ]
        result = support.python_support(observations, ["3.12"], ["linux", "macos"])
        self.assertEqual(result["3.12"]["verdict"], support.NOT_PROVEN)
        self.assertIn(
            "%s on any of linux, macos" % environment.FULL_SUITE,
            result["3.12"]["missing"],
        )

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

    def test_the_git_boundary_claims_no_minimum_without_an_enforced_one(self):
        result = support.git_boundary(self.both_levels())
        self.assertIsNone(result["minimum_claimed"])
        self.assertEqual(result["minimum_status"], support.NOT_PROVEN)
        self.assertEqual(result["lowest_exercised"], "git version 2.43.0")

    def test_an_enforced_floor_that_was_never_run_is_disclosed_as_such(self):
        """The distinction the manifest exists to keep: enforced is not tested.

        AIQE refuses below 2.32 on a mechanism argument. If every runner ships
        a much newer Git, the versions in between are permitted and covered by
        nothing, and the manifest has to say so rather than let the floor read
        as a tested boundary.
        """
        result = support.git_boundary(self.both_levels(), enforced_minimum=(2, 32))
        self.assertEqual(result["minimum_claimed"], "2.32")
        self.assertIsNotNone(result["enforced_but_unexercised_range"])
        self.assertIn("2.43.0", result["enforced_but_unexercised_range"])
        self.assertIn("introduced in Git 2.32", result["enforced_minimum_basis"])

    def test_no_gap_is_reported_when_the_floor_itself_was_run(self):
        result = support.git_boundary(
            self.both_levels(git_version="git version 2.32.0"),
            enforced_minimum=(2, 32),
        )
        self.assertIsNone(result["enforced_but_unexercised_range"])

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

        shallow = (
            subprocess.run(
                ["git", "-C", test_support.ROOT, "rev-parse", "--is-shallow-repository"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            .stdout.decode("ascii", "replace")
            .strip()
            == "true"
        )

        absent = []
        for identifier in identifiers:
            completed = subprocess.run(
                ["git", "-C", test_support.ROOT, "cat-file", "-t", identifier],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                absent.append(identifier)

        if absent and shallow:
            # In a shallow clone "not present" and "not ours" are the same
            # observation, so the check cannot be made. It is skipped by name
            # rather than passed quietly - CI clones with full history exactly
            # so that this never skips there.
            self.skipTest(
                "shallow clone: %s not present, which a shallow checkout cannot "
                "distinguish from a foreign object id" % (", ".join(absent),)
            )
        self.assertEqual(
            absent,
            [],
            "object id(s) in the manifest are not objects in this repository",
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

    def test_the_manifest_git_floor_matches_the_one_the_product_enforces(self):
        """A manifest that disagreed with the code would be worse than none."""
        from aiqe import gitq

        expected = ".".join(str(part) for part in gitq.MINIMUM_GIT_VERSION)
        self.assertEqual(
            self.manifest["git_compatibility"]["enforced_minimum"], expected
        )

    def test_the_manifest_distinguishes_enforced_from_exercised(self):
        boundary = self.manifest["git_compatibility"]
        self.assertIn("enforced_but_unexercised_range", boundary)
        self.assertIn("exercised", boundary)
        self.assertIn("introduced in Git 2.32", boundary["enforced_minimum_basis"])

    def test_the_unexercised_git_range_is_what_the_gate_recomputes(self):
        """A derived field must equal what its own inputs produce.

        This one was recorded as `null` - no unexercised range at all - while
        the README correctly published a 2.32 to 2.54 gap. The cause was that
        a *below-floor* surface, exercised only to prove AIQE refuses on it,
        was allowed to count as the lowest version run. A refusal cannot close
        a support gap, so the gate now ignores those, and this recomputes the
        field from the retained `exercised` list to keep the two agreeing.
        """
        boundary = self.manifest["git_compatibility"]
        observations = []
        for entry in boundary["exercised"]:
            for surface in entry["surfaces"]:
                family, rest = surface.split(" ", 1)
                release, arch, level = [part.strip() for part in rest.split("/")]
                observations.append(
                    {
                        "outcome": "PASS",
                        "git_version": entry["git_version"],
                        "os_family": family,
                        "os_release": release,
                        "arch": arch,
                        "level": level,
                    }
                )

        from aiqe import gitq

        recomputed = support.git_boundary(observations, gitq.MINIMUM_GIT_VERSION)
        self.assertEqual(
            recomputed["enforced_but_unexercised_range"],
            boundary["enforced_but_unexercised_range"],
            "the retained unexercised-range field is not what the gate "
            "computes from the manifest's own exercised versions",
        )

    def test_no_ci_run_record_carries_a_repository_namespace(self):
        """Retain only correlation that the evidence actually needs.

        Nothing reads the repository namespace: no gate, no comparator, and no
        published surface. What binds this manifest to this project is
        `source_commit` - proven elsewhere in this file to name an object in
        this repository - plus run identifiers that survive a rename or a
        transfer. A namespace would add no authority and would become a stale
        name for the project the moment one happened.
        """
        for entry in self.manifest["ci_runs"]:
            self.assertNotIn(
                "repository",
                entry,
                "a ci_runs record carries a repository namespace",
            )
            self.assertIn("sha", entry)


class ReadmeSupportSectionTests(unittest.TestCase):
    """The README may not claim a surface the manifest has not proven.

    "Do not write generic 'works on macOS and Linux' if the retained matrix is
    narrower" is the kind of rule that decays the moment nobody is checking,
    so it is checked. The README's support block is delimited by markers, and
    every Python minor it presents as proven has to carry a PROVEN verdict in
    the retained manifest.
    """

    BEGIN = "<!-- support:begin -->"
    END = "<!-- support:end -->"

    def setUp(self):
        import json

        with open(os.path.join(test_support.ROOT, "README.md"), encoding="utf-8") as h:
            self.readme = h.read()
        with open(RetainedManifestTests.MANIFEST, encoding="utf-8") as handle:
            self.manifest = json.load(handle)

    def block(self):
        # Membership is asserted without putting the README in the message: a
        # failure here should name the missing marker, not print the file.
        self.assertTrue(
            self.BEGIN in self.readme,
            "the README support block start marker %s is missing" % (self.BEGIN,),
        )
        self.assertTrue(
            self.END in self.readme,
            "the README support block end marker %s is missing" % (self.END,),
        )
        start = self.readme.index(self.BEGIN) + len(self.BEGIN)
        return self.readme[start : self.readme.index(self.END, start)]

    def proven_section(self):
        block = self.block()
        self.assertIn("PROVEN", block)
        start = block.index("**PROVEN**")
        for heading in ("**TESTED**", "**NOT PROVEN**", "**OUT OF SCOPE**"):
            if heading in block[start:]:
                return block[start : block.index(heading, start)]
        return block[start:]

    def test_the_block_exists_and_names_all_four_states(self):
        block = self.block()
        for state in ("PROVEN", "TESTED", "NOT PROVEN", "OUT OF SCOPE"):
            self.assertIn(state, block, state)

    def test_every_python_minor_shown_as_proven_is_proven_in_the_manifest(self):
        claimed = sorted(set(re.findall(r"\b3\.\d+\b", self.proven_section())))
        self.assertTrue(claimed, "the README claims no Python version as proven")
        support_claims = self.manifest["python_support"]
        for minor in claimed:
            with self.subTest(minor=minor):
                self.assertIn(
                    minor,
                    support_claims,
                    "the README presents Python %s as proven, and the manifest "
                    "has no claim for it at all" % (minor,),
                )
                self.assertEqual(
                    support_claims[minor]["verdict"],
                    support.PROVEN,
                    "the README presents Python %s as proven; the manifest says "
                    "%s" % (minor, support_claims[minor]["verdict"]),
                )

    def test_the_readme_does_not_quietly_drop_a_proven_minor(self):
        """The other direction, so the block cannot go stale by omission."""
        claimed = set(re.findall(r"\b3\.\d+\b", self.proven_section()))
        proven = {
            minor
            for minor, claim in self.manifest["python_support"].items()
            if claim["verdict"] == support.PROVEN
        }
        self.assertEqual(
            sorted(proven - claimed),
            [],
            "the manifest proves Python versions the README does not mention",
        )

    def test_windows_is_not_presented_as_supported(self):
        block = self.block().lower()
        if "windows" in block:
            out_of_scope = block[block.index("**out of scope**") :]
            self.assertIn("windows", out_of_scope)

    def test_the_block_points_at_the_evidence(self):
        block = self.block()
        self.assertIn("docs/support.md", block)


if __name__ == "__main__":
    unittest.main()
