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
        """The reverse direction: documentation for a code that no longer exists."""
        reference = read(DOCTOR_REFERENCE)
        # Only check the codes the reference lists in its code blocks, matched
        # by shape: uppercase words with underscores, at least two segments.
        import re

        documented = set()
        for block in re.findall(r"^```\n(.*?)^```", reference, re.S | re.M):
            for token in re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", block):
                documented.add(token)
        # Vocabulary and schema words appear in those blocks too; only assert
        # about tokens that look like finding codes by being declared or by
        # sharing a declared prefix family.
        families = {code.split("_")[0] for code in findings.ALL_CODES}
        candidates = {
            token
            for token in documented
            if token.split("_")[0] in families and token not in ("OK",)
        }
        stale = sorted(candidates - findings.ALL_CODES)
        self.assertEqual(stale, [], "docs/doctor.md documents codes that do not exist")


class ReadmeClaimTests(unittest.TestCase):
    def test_readme_does_not_claim_doctor_is_unimplemented(self):
        readme = read(README)
        self.assertNotIn("no installable artifact yet", readme.lower())
        self.assertNotIn("no implementation exists", readme.lower())

    def test_readme_marks_unimplemented_commands_as_design_targets(self):
        readme = read(README)
        self.assertIn("design target", readme.lower())

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
        retained = {case["case"]: case["human_output"] for case in results["cases"]}

        readme = read(README)
        example = retained["checkin_filter_configured"]
        self.assertIn(
            example.strip(),
            readme,
            "the README example is not the retained output for its case",
        )


if __name__ == "__main__":
    unittest.main()
