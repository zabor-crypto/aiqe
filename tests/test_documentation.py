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
COMMIT_REFERENCE = os.path.join(support.ROOT, "docs", "commit.md")
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

    def test_the_local_state_trust_boundary_is_documented(self):
        """A refusal a user meets must be explainable from the reference."""
        from aiqe import taskstate

        reference = read(CHECK_REFERENCE)
        self.assertIn(taskstate.LOCAL_STATE_UNSAFE, reference)
        self.assertIn("not a symlink", reference)
        self.assertIn("owned by this user", reference)
        self.assertIn("does not repair", reference.lower())
        for refusal in ("chmod", "chown"):
            self.assertIn(refusal, reference, refusal)

    def test_the_terminal_safety_rule_is_documented(self):
        reference = read(CHECK_REFERENCE)
        self.assertIn("escape, never strip", reference.lower())
        self.assertIn("never over the escaped text", reference)

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

    def test_the_local_state_trust_boundary_is_stated(self):
        from aiqe import taskstate

        policy = read(self.SECURITY)
        self.assertIn("did not create is not trusted", policy)
        self.assertIn(taskstate.LOCAL_STATE_UNSAFE, policy)
        self.assertIn("does not repair it", policy)

    def test_the_terminal_boundary_is_stated(self):
        policy = read(self.SECURITY)
        self.assertIn("never stripped", policy)
        self.assertIn("escaped, never", policy)
        self.assertIn(
            "digest is taken over the argument vector AIQE will execute", policy
        )

    def test_the_commit_boundary_is_stated_as_implemented_behaviour(self):
        policy = read(self.SECURITY)
        self.assertIn("`aiqe commit` is implemented", policy)
        self.assertNotIn("`aiqe commit` is not implemented", policy)

    def test_the_push_claim_is_bounded(self):
        policy = read(self.SECURITY)
        self.assertIn("AIQE_PUSH_CALLS = 0", policy)
        self.assertIn("not a claim that nobody else pushed", policy)

    def test_the_commit_write_confinement_claim_is_not_overstated(self):
        policy = read(self.SECURITY)
        self.assertIn("byte immutability", policy)
        self.assertIn("AIQE_CORE_WORKTREE_MUTATIONS = 0", policy)


class CommitReferenceTests(unittest.TestCase):
    def test_every_commit_policy_refusal_is_documented(self):
        from aiqe import commitpolicy

        reference = read(COMMIT_REFERENCE)
        for code in (
            commitpolicy.EFFECTIVE_CONFIG_UNRESOLVED,
            commitpolicy.COMMIT_HOOK_POLICY_UNSUPPORTED,
            commitpolicy.COMMIT_SIGNING_POLICY_UNSUPPORTED,
            commitpolicy.CHECKIN_FILTER_UNSUPPORTED,
            commitpolicy.MERGE_IN_PROGRESS,
            commitpolicy.REBASE_IN_PROGRESS,
            commitpolicy.CHERRY_PICK_IN_PROGRESS,
            commitpolicy.REVERT_IN_PROGRESS,
            commitpolicy.SEQUENCER_IN_PROGRESS,
            commitpolicy.BISECT_IN_PROGRESS,
            commitpolicy.UNMERGED_INDEX_ENTRIES,
            commitpolicy.SPARSE_CHECKOUT_UNSUPPORTED,
            commitpolicy.DETACHED_HEAD_UNSUPPORTED,
        ):
            self.assertIn(code, reference, code)

    def test_every_commit_hook_name_is_documented(self):
        from aiqe import commitpolicy

        reference = read(COMMIT_REFERENCE)
        for hook in commitpolicy.COMMIT_HOOKS:
            self.assertIn(hook, reference, hook)

    def test_the_commit_evidence_schema_version_is_stated(self):
        from aiqe import commitevidence

        reference = read(COMMIT_REFERENCE)
        self.assertIn(
            "COMMIT_EVIDENCE_SCHEMA_VERSION = %d"
            % (commitevidence.COMMIT_EVIDENCE_SCHEMA_VERSION,),
            reference,
        )

    def test_the_forbidden_flags_are_named_rather_than_implied(self):
        reference = read(COMMIT_REFERENCE)
        for flag in ("--amend", "--no-verify", "--allow-empty", "--no-gpg-sign"):
            self.assertIn(flag, reference, flag)

    def test_the_push_claim_is_bounded(self):
        reference = read(COMMIT_REFERENCE)
        self.assertIn("AIQE_PUSH_CALLS = 0", reference)
        self.assertIn("not a claim that nobody else pushed", reference)

    def test_write_confinement_is_not_overstated(self):
        reference = read(COMMIT_REFERENCE)
        self.assertIn("is **not** claimed", reference)
        self.assertIn("AIQE_CORE_WORKTREE_MUTATIONS = 0", reference)


class ArchitectureTests(unittest.TestCase):
    def test_no_command_is_described_as_a_remaining_design_target(self):
        reference = read(ARCHITECTURE)
        self.assertIn("Everything above is implemented.", reference)
        self.assertNotIn("except `aiqe commit`", reference)
        self.assertNotIn("`aiqe commit` is the one remaining design", reference)

    def test_the_commit_reference_is_linked(self):
        reference = read(ARCHITECTURE)
        self.assertIn("commit.md", reference)


class ReadmeClaimTests(unittest.TestCase):
    def test_readme_does_not_claim_doctor_is_unimplemented(self):
        readme = read(README)
        self.assertNotIn("no installable artifact yet", readme.lower())
        self.assertNotIn("no implementation exists", readme.lower())

    def test_readme_does_not_mark_implemented_commands_as_design_targets(self):
        """A command leaves the design-target list when it acquires an
        implementation. `commit` was the last one out, so the list is empty."""
        readme = read(README)
        for line in readme.splitlines():
            lowered = line.lower()
            if "design target" not in lowered:
                continue
            self.assertFalse(
                lowered.strip().startswith(
                    ("doctor ", "task ", "init ", "check ", "receipt ", "commit ")
                ),
                "an implemented command is still marked a design target: %r" % (line,),
            )

    def test_readme_does_not_still_call_commit_unimplemented(self):
        readme = read(README).lower()
        for claim in (
            "`aiqe commit` is not implemented",
            "commit` remains a\ndesign target",
            "unknown command",
        ):
            self.assertNotIn(claim, readme, claim)

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

    def test_readme_commit_output_matches_the_retained_artifact(self):
        """The first real `REVIEWABLE` receipt is copied, not composed.

        This is the block a reader is most likely to take at face value, so it
        is the block that must come from a retained measurement of a synthetic
        fixture rather than from anybody's keyboard.
        """
        import json

        artifact = os.path.join(
            support.ROOT, "bench", "results", "commit", "results.json"
        )
        with open(artifact) as handle:
            results = json.load(handle)
        retained = {case["case"]: case for case in results["cases"]}

        readme = read(README)
        case = retained["commit-owned-modification"]
        self.assertEqual(case["receipt_verdict"], "REVIEWABLE")
        self.assertIn(
            case["commit_output"].strip(),
            readme,
            "the README commit example is not the retained output for its case",
        )
        self.assertIn(
            case["receipt_output"].strip(),
            readme,
            "the README post-commit receipt is not the retained output",
        )

    def test_the_readme_reviewable_receipt_carries_no_identifier(self):
        """The one place a shareable artifact could leak, shown to everyone."""
        import json

        artifact = os.path.join(
            support.ROOT, "bench", "results", "commit", "results.json"
        )
        with open(artifact) as handle:
            results = json.load(handle)
        retained = {case["case"]: case for case in results["cases"]}
        case = retained["commit-owned-modification"]
        self.assertFalse(case["receipt_discloses_commit_sha"])
        self.assertNotIn("src/strategy/alpha.py", case["receipt_output"])


if __name__ == "__main__":
    unittest.main()
