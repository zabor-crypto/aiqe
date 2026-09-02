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
CONFIG_REFERENCE = os.path.join(support.ROOT, "docs", "config.md")
CHECK_REFERENCE = os.path.join(support.ROOT, "docs", "check.md")
RECEIPT_REFERENCE = os.path.join(support.ROOT, "docs", "receipt.md")
README = os.path.join(support.ROOT, "README.md")
ARCHITECTURE = os.path.join(support.ROOT, "docs", "architecture.md")


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
            if name.startswith(("OWNERSHIP_", "OWNED_")) and isinstance(value, str)
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
            "ownership_semantics",
            "task_id",
            "aiqe_version",
            "started_at",
            "start_head_sha",
            "owned_paths",
            "owned_pathset_digest",
            "foreign_staged_count_at_start",
            "label",
        ):
            self.assertIn(field, reference, field)

    def test_documented_fields_are_the_fields_actually_written(self):
        """The reference must not drift from the record the product writes."""
        import inspect

        from aiqe import task

        source = inspect.getsource(task._build_record)
        reference = read(TASK_REFERENCE)
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith('"') or '":' not in stripped:
                continue
            field = stripped.split('"')[1]
            self.assertIn(field, reference, field)

    def test_the_state_location_is_stated(self):
        """A reader must be able to find where AIQE keeps its state."""
        reference = read(TASK_REFERENCE)
        self.assertIn("$XDG_STATE_HOME/aiqe", reference)
        self.assertIn("HMAC-SHA256", reference)
        self.assertNotIn("<worktree git directory>/aiqe/task.json", reference)

    def test_the_ownership_rule_is_stated(self):
        """A reader must not have to infer that ownership is exact."""
        reference = read(TASK_REFERENCE)
        self.assertIn("owns(foo, foo/bar)  FALSE", reference)
        self.assertIn("exact", reference.lower())
        self.assertNotIn("component-prefix ownership", reference)


class ConfigReferenceTests(unittest.TestCase):
    def test_every_configuration_refusal_code_is_documented(self):
        """A user who meets a refusal must be able to look it up."""
        from aiqe import config

        reference = read(CONFIG_REFERENCE)
        codes = [
            value
            for name, value in vars(config).items()
            if name.startswith("CONFIG_") and isinstance(value, str)
            and value == name
        ]
        self.assertTrue(codes)
        undocumented = sorted(code for code in codes if code not in reference)
        self.assertEqual(undocumented, [], "reason codes missing from docs/config.md")

    def test_the_pattern_grammar_is_documented(self):
        reference = read(CONFIG_REFERENCE)
        for element in ("`*`", "`?`", "`**`", "[abc]"):
            self.assertIn(element.strip("`"), reference, element)
        self.assertIn("not Git pathspec", reference)

    def test_every_launch_contract_is_documented(self):
        from aiqe import contracts

        reference = read(CONFIG_REFERENCE)
        for contract in contracts.LAUNCH_CONTRACTS:
            self.assertIn(contract, reference, contract)

    def test_init_write_confinement_is_stated(self):
        reference = read(CONFIG_REFERENCE)
        self.assertIn("exactly one repository path", reference)
        self.assertIn("`.gitignore`", reference)
        self.assertIn("never overwritten", reference)


class CheckReferenceTests(unittest.TestCase):
    def test_every_owned_path_state_is_documented(self):
        from aiqe import pathstate

        reference = read(CHECK_REFERENCE)
        for state in (
            pathstate.TRACKED_UNCHANGED,
            pathstate.TRACKED_MODIFIED,
            pathstate.TRACKED_DELETED,
            pathstate.NEW,
            pathstate.PENDING_ABSENT,
        ):
            self.assertIn(state, reference, state)

    def test_every_classification_and_coverage_state_is_documented(self):
        from aiqe import classify

        reference = read(CHECK_REFERENCE)
        for state in (
            classify.UNCLASSIFIED,
            classify.QUANT_SURFACE,
            classify.EXPLICIT_NON_QUANT_SURFACE,
            classify.CONFIG_CONFLICT,
            classify.CLASSIFICATION_GAP,
            classify.COVERED,
            classify.COVERAGE_GAP,
            classify.CONTRACT_FAILED,
            classify.CONTRACT_UNKNOWN,
        ):
            self.assertIn(state, reference, state)

    def test_every_validator_outcome_is_documented(self):
        from aiqe import validators

        reference = read(CHECK_REFERENCE)
        for outcome in validators.OUTCOMES:
            self.assertIn(outcome, reference, outcome)

    def test_the_load_bearing_rules_are_stated(self):
        reference = read(CHECK_REFERENCE)
        self.assertIn("A timeout is a `FAIL`", reference)
        self.assertIn("never the first one that matches", reference)
        self.assertIn("adding a surface can never reduce", reference)
        self.assertIn("no sandbox", reference)
        self.assertIn("REVIEWABLE_CANDIDATE", reference)

    def test_the_termination_claim_is_bounded(self):
        """The narrow sentence must be there, and the wide ones must not.

        "Terminates the process group it created" is a mechanism. "Bounds
        every descendant" is a containment guarantee AIQE does not provide,
        and it is the sentence that would be easy to write by accident.
        """
        reference = read(CHECK_REFERENCE)
        self.assertIn(
            "AIQE terminates the validator process group it created", reference
        )
        self.assertIn("setsid", reference)
        self.assertIn("does not", reference)
        for overclaim in (
            "bounds every descendant",
            "kills all descendants",
            "contains the process tree",
            "whole process group, so a validator",
        ):
            self.assertNotIn(overclaim, reference, overclaim)

    def test_the_output_capture_policy_is_documented(self):
        from aiqe import validators

        reference = read(CHECK_REFERENCE)
        self.assertIn("as it arrives", reference)
        self.assertIn("never read whole and", reference)
        self.assertIn(validators.RETENTION_POLICY, reference)

    def test_the_local_state_modes_are_documented(self):
        reference = read(CHECK_REFERENCE)
        for line in ("task.json  0600", "check.json 0600", "consents.json  0600"):
            self.assertIn(line, reference, line)
        self.assertIn("umask(0)", reference)

    def test_the_evidence_schema_version_is_stated(self):
        from aiqe import evidence

        reference = read(CHECK_REFERENCE)
        self.assertIn(
            "EVIDENCE_SCHEMA_VERSION = %d" % (evidence.EVIDENCE_SCHEMA_VERSION,),
            reference,
        )


class ReceiptReferenceTests(unittest.TestCase):
    def test_every_staleness_reason_is_documented(self):
        from aiqe import evidence

        reference = read(RECEIPT_REFERENCE)
        for reason in evidence.STALENESS_REASONS:
            self.assertIn(reason, reference, reason)

    def test_the_redaction_policies_are_named(self):
        from aiqe import receipt

        reference = read(RECEIPT_REFERENCE)
        self.assertIn(receipt.DEFAULT_REDACTION_POLICY, reference)
        self.assertIn(receipt.LOCAL_REDACTION_POLICY, reference)

    def test_the_unreachable_verdict_is_stated(self):
        reference = read(RECEIPT_REFERENCE)
        self.assertIn("No pre-commit state", reference)
        self.assertIn("BOUNDED_COMMIT_NOT_CREATED", reference)

    def test_the_exclusion_list_is_documented(self):
        reference = read(RECEIPT_REFERENCE)
        for excluded in (
            "absolute paths",
            "the branch",
            "any commit identifier",
            "validator argument vectors",
            "the username",
            "the hostname",
        ):
            self.assertIn(excluded, reference, excluded)


class SecurityPolicyTests(unittest.TestCase):
    SECURITY = os.path.join(support.ROOT, "SECURITY.md")

    def test_the_termination_claim_is_bounded(self):
        policy = read(self.SECURITY)
        self.assertIn("process group it created", policy)
        self.assertIn("setsid", policy)
        self.assertNotIn("cannot outlive the bound", policy)

    def test_local_state_privacy_is_stated(self):
        policy = read(self.SECURITY)
        self.assertIn("owner-only regardless of your umask", policy)
        self.assertIn("0600", policy)

    def test_the_unimplemented_commit_boundary_is_marked_as_intent(self):
        policy = read(self.SECURITY)
        self.assertIn("`aiqe commit` is not implemented", policy)


class ArchitectureTests(unittest.TestCase):
    def test_implemented_commands_are_not_described_as_intent(self):
        reference = read(ARCHITECTURE)
        self.assertIn("except `aiqe commit`", reference)

    def test_the_one_remaining_design_target_is_named(self):
        reference = read(ARCHITECTURE)
        self.assertIn("`aiqe commit` is the one remaining design", reference)


class ReadmeClaimTests(unittest.TestCase):
    def test_readme_does_not_claim_doctor_is_unimplemented(self):
        readme = read(README)
        self.assertNotIn("no installable artifact yet", readme.lower())
        self.assertNotIn("no implementation exists", readme.lower())

    def test_readme_marks_unimplemented_commands_as_design_targets(self):
        readme = read(README)
        self.assertIn("design target", readme.lower())

    def test_readme_does_not_mark_implemented_commands_as_design_targets(self):
        """A command leaves the design-target list when it acquires an
        implementation. `commit` is what remains."""
        readme = read(README)
        for line in readme.splitlines():
            lowered = line.lower()
            if "design target" not in lowered:
                continue
            self.assertFalse(
                lowered.strip().startswith(
                    ("doctor ", "task ", "init ", "check ", "receipt ")
                ),
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

    def test_readme_workflow_output_matches_the_retained_artifact(self):
        """The check and receipt blocks are copied, not typed.

        The receipt block is the one that matters most: it shows `INCOMPLETE`
        on a completely green check, and a hand-typed approximation of that
        would be the first place the claim and the product diverged.
        """
        import json

        artifact = os.path.join(
            support.ROOT, "bench", "results", "check", "results.json"
        )
        with open(artifact) as handle:
            results = json.load(handle)
        retained = {case["case"]: case for case in results["cases"]}

        readme = read(README)
        self.assertIn(
            retained["causality_coverage_gap"]["check_output"].strip(),
            readme,
            "the README check example is not the retained output for its case",
        )
        self.assertIn(
            retained["causality_covered"]["receipt_output"].strip(),
            readme,
            "the README receipt example is not the retained output for its case",
        )

    def test_readme_states_that_a_green_check_is_still_incomplete(self):
        readme = read(README)
        self.assertIn("BOUNDED_COMMIT_NOT_CREATED", readme)
        self.assertIn("COVERAGE_GAP", readme)


if __name__ == "__main__":
    unittest.main()
