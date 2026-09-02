"""Documentation that goes stale silently is worse than absent documentation.

These are cheap structural checks, not prose review. They catch the two ways
this project's documentation would decay without anyone noticing: a finding
code that exists in code but is documented nowhere, and a claim in the README
that stopped being true when the implementation landed.
"""

import os
import unittest

from . import support

from aiqe import findings

DOCTOR_REFERENCE = os.path.join(support.ROOT, "docs", "doctor.md")
TASK_REFERENCE = os.path.join(support.ROOT, "docs", "task.md")
README = os.path.join(support.ROOT, "README.md")


def read(path):
    with open(path) as handle:
        return handle.read()


class FindingCodeCoverageTests(unittest.TestCase):
    def test_every_finding_code_is_documented(self):
        """A user who meets a code must be able to look it up."""
        reference = read(DOCTOR_REFERENCE)
        undocumented = sorted(
            code for code in findings.ALL_CODES if code not in reference
        )
        self.assertEqual(undocumented, [], "finding codes missing from docs/doctor.md")

    def test_no_documented_code_has_been_removed_from_the_code(self):
        """The reverse direction: documentation for a code that no longer exists.

        Scoped to the reference's finding-code section. Elsewhere the document
        legitimately names other SHOUTING_IDENTIFIERS - Git environment
        variables, for instance - and treating those as finding codes was a
        false positive waiting to happen.
        """
        import re

        reference = read(DOCTOR_REFERENCE)
        start = reference.index("## Finding codes")
        end = reference.index("## Exit status", start)
        section = reference[start:end]

        documented = set()
        for block in re.findall(r"^```\n(.*?)^```", section, re.S | re.M):
            for token in re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", block):
                documented.add(token)

        stale = sorted(documented - findings.ALL_CODES)
        self.assertEqual(stale, [], "docs/doctor.md documents codes that do not exist")


class TaskReferenceTests(unittest.TestCase):
    def test_every_scope_reason_code_is_documented(self):
        """A user who meets a refusal must be able to look it up."""
        from aiqe import scope

        reference = read(TASK_REFERENCE)
        codes = [
            value
            for name, value in vars(scope).items()
            if name.startswith("OWNERSHIP_") and isinstance(value, str)
        ]
        self.assertTrue(codes)
        undocumented = sorted(code for code in codes if code not in reference)
        self.assertEqual(undocumented, [], "reason codes missing from docs/task.md")

    def test_state_schema_is_marked_internal(self):
        """It is documented for auditability, not offered as an API."""
        reference = read(TASK_REFERENCE)
        self.assertIn("LOCAL INTERNAL STATE SCHEMA", reference)
        self.assertIn("not a public integration surface", reference)

    def test_every_record_field_is_documented(self):
        reference = read(TASK_REFERENCE)
        for field in (
            "schema_version",
            "task_id",
            "aiqe_version",
            "started_at",
            "start_head_state",
            "start_head_sha",
            "owned_scope",
            "owned_scope_digest",
            "label",
        ):
            self.assertIn(field, reference, field)


class ReadmeClaimTests(unittest.TestCase):
    def test_readme_does_not_claim_doctor_is_unimplemented(self):
        readme = read(README)
        self.assertNotIn("no installable artifact yet", readme.lower())
        self.assertNotIn("no implementation exists", readme.lower())

    def test_readme_marks_unimplemented_commands_as_design_targets(self):
        readme = read(README)
        self.assertIn("design target", readme.lower())

    def test_readme_does_not_mark_implemented_commands_as_design_targets(self):
        """`task` left the design-target list when it acquired an implementation."""
        readme = read(README)
        for line in readme.splitlines():
            lowered = line.lower()
            if "design target" not in lowered:
                continue
            self.assertFalse(
                lowered.strip().startswith(("doctor ", "task ")),
                "an implemented command is still marked a design target: %r" % (line,),
            )

    def test_readme_example_output_matches_the_retained_artifact(self):
        """A README terminal block must be copied from a retained result.

        Hand-typed output drifts from the product silently, which is exactly
        the failure this project tells its users not to accept from anyone
        else.
        """
        import json

        artifact = os.path.join(support.ROOT, "bench", "results", "doctor", "results.json")
        with open(artifact) as handle:
            results = json.load(handle)
        # A case skipped for platform reasons has no rendered output, and is
        # present in the artifact precisely so that it is not hidden.
        retained = {
            case["case"]: case["human_output"]
            for case in results["cases"]
            if "human_output" in case
        }

        readme = read(README)
        example = retained["checkin_filter_configured"]
        self.assertIn(
            example.strip(),
            readme,
            "the README example is not the retained output for its case",
        )


if __name__ == "__main__":
    unittest.main()
