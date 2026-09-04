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


class ProductPackageTests(unittest.TestCase):
    """The presentation artifacts, and the claims they are allowed to make.

    Everything asserted here decays silently: a capture that stopped being the
    output it names, a benchmark total copied by hand, a flag documented into
    existence, a CI badge that arrived without the run behind it.
    """

    def setUp(self):
        self.readme = read(README)

    def test_the_rendered_assets_are_what_the_retained_artifacts_render(self):
        """`bench/render-assets.py` without `--write` reports drift and exits
        non-zero. Running it here is the whole gate: it covers every terminal
        capture and the README benchmark block in one comparison."""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, os.path.join(support.ROOT, "bench", "render-assets.py")],
            cwd=support.ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "rendered assets have drifted from the retained artifacts:\n%s"
            % (proc.stderr.decode("utf-8", "replace"),),
        )

    def test_every_capture_resolves_to_the_case_its_index_names(self):
        """The index is the provenance, so it has to be checkable."""
        import json

        directory = os.path.join(support.ROOT, "docs", "assets", "captures")
        with open(os.path.join(directory, "index.json")) as handle:
            index = json.load(handle)
        self.assertTrue(index["captures"], "the capture index is empty")
        for entry in index["captures"]:
            with self.subTest(capture=entry["capture"]):
                with open(os.path.join(support.ROOT, entry["results"])) as handle:
                    results = json.load(handle)
                cases = {case["case"]: case for case in results["cases"]}
                self.assertIn(entry["case"], cases, entry["case"])
                body = read(os.path.join(directory, entry["capture"]))
                self.assertEqual(
                    body.rstrip("\n"),
                    cases[entry["case"]][entry["field"]].rstrip("\n"),
                    "%s is not the %s of case %s"
                    % (entry["capture"], entry["field"], entry["case"]),
                )

    def test_the_five_screenshotable_surfaces_are_all_captured(self):
        """The set is stated so that losing one is a failure, not an omission
        nobody notices: Doctor, a green check, the pre-commit receipt, the
        post-commit receipt, and a fail-closed UNKNOWN."""
        directory = os.path.join(support.ROOT, "docs", "assets", "captures")
        for name in (
            "doctor.txt",
            "check-reviewable-candidate.txt",
            "receipt-precommit-incomplete.txt",
            "receipt-postcommit-reviewable.txt",
            "check-unknown.txt",
        ):
            self.assertTrue(
                os.path.exists(os.path.join(directory, name)), name
            )
        self.assertIn(
            "REVIEWABLE_CANDIDATE",
            read(os.path.join(directory, "check-reviewable-candidate.txt")),
        )
        self.assertIn(
            "UNKNOWN", read(os.path.join(directory, "check-unknown.txt"))
        )

    def test_every_aiqe_flag_the_readme_shows_exists_in_the_command_surface(self):
        """A flag documented into existence is the cheapest possible lie."""
        import re

        from aiqe import cli

        surface = {}
        for line in cli.USAGE.splitlines():
            match = re.match(r"\s*(?:usage:)?\s*aiqe\s+(\S+)(.*)", line)
            if not match:
                continue
            subcommand, rest = match.group(1), match.group(2)
            flags = set(re.findall(r"--[a-z-]+", rest))
            if subcommand.startswith("--"):
                flags.add(subcommand)
                subcommand = ""
            surface.setdefault(subcommand, set()).update(flags)

        shown = re.findall(r"^\s*(?:\.venv/bin/)?aiqe\s+(.*)$", self.readme, re.M)
        self.assertTrue(shown, "the README shows no aiqe invocation at all")
        for invocation in shown:
            words = invocation.split()
            subcommand = words[0] if not words[0].startswith("-") else ""
            with self.subTest(invocation=invocation):
                self.assertIn(
                    subcommand,
                    surface,
                    "the README shows `aiqe %s`, which is not a command"
                    % (subcommand,),
                )
                for word in words[1:]:
                    if not word.startswith("--"):
                        continue
                    flag = word.split("=")[0]
                    self.assertIn(
                        flag,
                        surface[subcommand],
                        "the README shows `%s` on `aiqe %s`, and the command "
                        "surface does not have it" % (flag, subcommand),
                    )

    def test_every_documented_configuration_is_one_the_product_accepts(self):
        """A documented `aiqe.toml` the parser would refuse is a worked
        example that does not work. The parser is fail-closed by design, so
        this is not hypothetical: a key renamed in the implementation makes
        every configuration on these pages invalid, silently."""
        import re
        import tempfile

        from aiqe import config as config_module

        pages = [README] + [
            os.path.join(support.ROOT, "docs", name)
            for name in ("config.md", "agents.md", "architecture.md")
        ]
        found = 0
        for page in pages:
            for body in re.findall(r"^```toml\n(.*?)^```", read(page), re.S | re.M):
                found += 1
                directory = tempfile.mkdtemp(prefix="aiqe-doc-config-")
                with open(os.path.join(directory, "aiqe.toml"), "w") as handle:
                    handle.write(body)
                with self.subTest(page=os.path.basename(page)):
                    parsed = config_module.load(os.fsencode(directory))
                    self.assertTrue(
                        parsed.surfaces,
                        "%s documents a configuration with no surface"
                        % (os.path.basename(page),),
                    )
        self.assertTrue(found, "no documented configuration was found to check")

    def test_every_launch_contract_is_explained_rather_than_only_listed(self):
        """Six names in a code block is a list. The README has to say what
        each one is about, or the section is decoration."""
        from aiqe import contracts as contracts_module

        for contract in contracts_module.LAUNCH_CONTRACTS:
            with self.subTest(contract=contract):
                self.assertIn(contract, self.readme, contract)

    def test_the_contract_claim_is_bounded(self):
        """The one sentence that keeps a covered contract from being read as
        a correctness proof."""
        lowered = self.readme.lower()
        self.assertIn("does not prove universal numerical truth", lowered)
        self.assertIn("is not universal correctness", lowered)
        self.assertIn("coverage_gap", lowered)

    def test_the_trust_boundaries_are_stated_on_the_front_page(self):
        """A reader who never opens SECURITY.md still has to meet these."""
        lowered = self.readme.lower()
        for claim in (
            "there is no sandbox",
            "no network-restriction",
            "explicit local consent",
            "machine-local",
            "no telemetry",
        ):
            self.assertIn(claim, lowered, claim)

    def test_local_security_is_not_overstated(self):
        """AIQE defends nothing against a process running as you."""
        lowered = self.readme.lower()
        self.assertIn("same-uid", lowered)
        self.assertIn("or as root", lowered)

    def test_no_badge_appears_anywhere_on_the_page(self):
        """A badge above the fold is a maturity claim, and the exact-HEAD CI
        run that would justify one has not happened."""
        lowered = self.readme.lower()
        for shape in ("shields.io", "badge.svg", "img.shields", "/badge)"):
            self.assertNotIn(shape, lowered, shape)

    def test_the_external_ci_debt_is_recorded_rather_than_implied(self):
        """The README states the substance; the support method document holds
        the marker and the condition that closes it. The marker is project
        vocabulary and does not belong in product copy."""
        lowered = self.readme.lower()
        self.assertIn("not** the current head", lowered)
        self.assertIn("no complete ci run has attested", lowered)

        reference = read(os.path.join(support.ROOT, "docs", "support.md"))
        self.assertIn("OSS7_FINAL_HEAD_GITHUB_CI_ATTESTATION", reference)
        self.assertIn("PENDING_EXTERNAL_BILLING_CAPACITY", reference)
        self.assertIn("source_commit", reference)
        for forbidden in ("shields.io", "badge.svg"):
            self.assertNotIn(forbidden, reference, forbidden)

    def test_the_packaging_facts_are_stated(self):
        for fact in (">= 3.11", "wheel and sdist", "uvx --from", "DEFERRED"):
            self.assertIn(fact, self.readme, fact)

    def test_a_deferred_thing_is_not_presented_as_planned(self):
        """`DEFERRED` must not quietly become a roadmap entry."""
        self.assertIn("is not a roadmap entry", self.readme)

    def test_the_demo_is_not_still_described_as_unbuilt(self):
        lowered = self.readme.lower()
        for stale in (
            "materialised alongside the first alpha",
            "for the specification",
            "not yet implemented",
        ):
            self.assertNotIn(stale, lowered, stale)


class AgentReferenceTests(unittest.TestCase):
    """`docs/agents.md` is where a reader decides how to wire AIQE into an
    agent, which makes it the easiest place to imply an integration that does
    not exist."""

    REFERENCE = os.path.join(support.ROOT, "docs", "agents.md")

    def setUp(self):
        self.reference = read(self.REFERENCE)

    def test_no_integration_that_does_not_exist_is_implied(self):
        lowered = self.reference.lower()
        self.assertIn("no plugin", lowered)
        self.assertIn("no mcp server", lowered)
        self.assertIn("no adapter", lowered)

    def test_the_agent_finding_codes_it_quotes_are_real(self):
        for code in (
            "CLAUDE_PERMISSIONS_BROAD",
            "CODEX_PERMISSIONS_BROAD",
            "AGENT_CONFIG_UNREADABLE",
        ):
            with self.subTest(code=code):
                self.assertIn(code, findings.ALL_CODES, code)
                self.assertIn(code, self.reference, code)

    def test_the_scope_and_consent_rules_are_not_delegated_to_the_agent(self):
        lowered = self.reference.lower()
        self.assertIn("you declare the scope, before the agent starts", lowered)
        self.assertIn("you give consent", lowered)

    def test_it_does_not_claim_to_supervise_the_agent(self):
        lowered = self.reference.lower()
        self.assertIn("does not supervise your agent", lowered)
        self.assertIn("does not sandbox it", lowered)

    def test_the_readme_points_at_it(self):
        self.assertIn("docs/agents.md", read(README))


if __name__ == "__main__":
    unittest.main()
