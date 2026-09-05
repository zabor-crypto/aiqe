"""The check, evidence and receipt benchmark family, run as tests.

One test per case in `bench/fixtures/check/cases.json`. Each builds the
fixture from nothing, drives the real command-line entry point against it
under the measurement harness, and asserts the claims this family actually
makes:

    the observation matches the expectation recorded in cases.json
    AIQE core wrote no repository path
    no validator ran without consent
    nothing was written outside AIQE's machine-local state home
    no pre-commit state produced a REVIEWABLE verdict

The expectations were written from the frozen contract before the
implementation was run against them.

Note what is deliberately *not* asserted: that the repository did not change.
`aiqe check` runs code the repository declared, and that code can write
anywhere the user can. The harness attributes each change to a cause instead,
and only AIQE core's own repository writes are zero-tolerance.
"""

import unittest

from . import support


def _make_test(case):
    def test(self):
        if not support.check_harness.case_applies(case):
            self.skipTest(
                "case %s requires platform %r" % (case["id"], case.get("platform"))
            )
        observed = support.check_harness.run_case(case["id"])
        problems = support.check_harness.check_expectations(observed, case["expect"])
        if problems:
            self.fail(
                "case %s did not match its expectation:\n  %s"
                % (case["id"], "\n  ".join(problems))
            )

        self.assertEqual(
            observed["aiqe_core_repository_mutations"],
            0,
            "AIQE_CORE_REPOSITORY_WRITES: %s"
            % (observed["aiqe_core_repository_mutation_detail"],),
        )
        self.assertEqual(
            observed["unconsented_validator_executions"],
            0,
            "UNCONSENTED_VALIDATOR_EXECUTIONS: %s"
            % (observed["unconsented_validators"],),
        )
        self.assertEqual(
            observed["local_state_writes"],
            0,
            "writes outside the AIQE state home: %s"
            % (observed["local_state_write_detail"],),
        )
        self.assertEqual(observed["other_changes"], [])
        self.assertNotEqual(
            observed.get("receipt_verdict"),
            "REVIEWABLE",
            "REVIEWABLE is unreachable before a bounded commit exists",
        )

    test.__name__ = "test_" + case["id"]
    test.__doc__ = case["description"]
    return test


class CheckFixtureTests(unittest.TestCase):
    pass


for _case in support.check_cases():
    setattr(CheckFixtureTests, "test_" + _case["id"], _make_test(_case))
del _case


class FixtureCoverageTests(unittest.TestCase):
    def test_every_scenario_has_a_recorded_expectation(self):
        self.assertEqual(
            set(support.check_builders.SCENARIOS), set(support.check_case_ids())
        )

    def test_every_launch_contract_family_has_all_three_variants(self):
        """No family may be represented by another.

        A single contract fixture standing in for six would leave five
        families with no evidence at all, which is exactly the substitution
        the benchmark protocol forbids.
        """
        from aiqe import contracts

        identifiers = set(support.check_case_ids())
        missing = []
        for contract in contracts.LAUNCH_CONTRACTS:
            for variant in ("covered", "failed", "coverage_gap"):
                name = "%s_%s" % (contract.lower(), variant)
                if name not in identifiers:
                    missing.append(name)
        self.assertEqual(missing, [])

    def test_required_conditions_are_all_covered(self):
        """Every condition the frozen check contract names must have a case."""
        required = {
            "unclassified_changed_path",
            "config_conflict_refused",
            "consent_withheld",
            "allow_is_not_persisted",
            "definition_digest_drift",
            "validator_unavailable",
            "validator_timeout_is_failure",
            "validator_mutates_owned_path",
            "owned_content_changes_after_check",
            "head_moves_after_check",
            "config_changes_after_check",
            "configuration_absent",
            "init_print_writes_nothing",
            "init_writes_only_the_config",
            "pty_consent_denied",
            "pty_consent_accepted_and_persisted",
            "large_output_bounded",
            "large_output_with_timeout",
            "detached_child_escapes_the_process_group",
            "unsafe_state_root_mode",
            "unsafe_derived_state_directory_mode",
            "unsafe_consent_file_mode",
            "state_symlink_refused",
            "safe_existing_state_still_works",
            "malicious_consent_denied",
            "malicious_consent_accepted",
            "malicious_validator_output",
        }
        self.assertEqual(required - set(support.check_case_ids()), set())

    def test_unsafe_local_state_never_executes_a_validator(self):
        """The point of the trust boundary, read off the expectations.

        Every case that damages an AIQE-managed component must expect a
        refusal and zero executions. A future case that wrote down anything
        else would fail here before it ever ran.
        """
        by_id = {case["id"]: case["expect"] for case in support.check_cases()}
        for identifier in (
            "unsafe_state_root_mode",
            "unsafe_derived_state_directory_mode",
            "unsafe_consent_file_mode",
            "state_symlink_refused",
        ):
            expect = by_id[identifier]
            self.assertEqual(expect["executions"], 0, identifier)
            self.assertEqual(expect["check_exit"], 3, identifier)

        # And the other half: ordinary pre-existing state is untouched by any
        # of it, at the modes AIQE creates.
        safe = by_id["safe_existing_state_still_works"]
        self.assertEqual(safe["first_check_exit"], 0)
        self.assertEqual(safe["second_check_exit"], 0)
        self.assertEqual(safe["state_modes"]["root"], "0700")
        self.assertEqual(safe["state_modes"]["consents.json"] if
                         "consents.json" in safe["state_modes"] else "0600", "0600")
        for name in ("task.json", "check.json", "salt"):
            self.assertEqual(safe["state_modes"][name], "0600", name)

    def test_hostile_repository_text_never_reaches_the_terminal_raw(self):
        """Escaped, not stripped, and the digest still binds the real thing."""
        by_id = {case["id"]: case["expect"] for case in support.check_cases()}

        for identifier in ("malicious_consent_denied", "malicious_consent_accepted"):
            expect = by_id[identifier]
            self.assertEqual(expect["raw_control_bytes"], 0, identifier)
            self.assertEqual(expect["raw_escape_sequences"], 0, identifier)
            self.assertEqual(expect["raw_carriage_returns"], 0, identifier)
            self.assertTrue(expect["escaped_form_shown"], identifier)
            self.assertTrue(expect["warning_intact"], identifier)

        accepted = by_id["malicious_consent_accepted"]
        self.assertTrue(accepted["consent_matches_raw_definition_digest"])
        self.assertTrue(accepted["consent_is_not_over_display_text"])

        output = by_id["malicious_validator_output"]
        for surface in (
            "check_human_control_bytes",
            "receipt_local_control_bytes",
            "default_receipt_control_bytes",
        ):
            self.assertEqual(output[surface], 0, surface)
        self.assertTrue(output["json_retains_the_output_itself"])
        self.assertTrue(output["default_receipt_holds_no_validator_output"])

    def test_consent_is_proved_through_a_real_terminal(self):
        """Not through an injected prompt callable.

        `aiqe` decides whether to ask by looking at whether standard input and
        standard output are terminals. An injected callable bypasses exactly
        the decision that matters, so both directions - denied and accepted -
        are driven through a real pseudo-terminal against the real CLI.
        """
        by_id = {case["id"]: case["expect"] for case in support.check_cases()}

        denied = by_id["pty_consent_denied"]
        self.assertEqual(denied["executions"], 0)
        self.assertEqual(denied["consents_recorded"], 0)
        for disclosure in (
            "prompt_shows_validator_id",
            "prompt_shows_exact_argv",
            "prompt_shows_timeout",
            "prompt_warns_no_containment",
        ):
            self.assertTrue(denied[disclosure], disclosure)

        accepted = by_id["pty_consent_accepted_and_persisted"]
        self.assertEqual(accepted["executions_after_accept"], 1)
        self.assertTrue(accepted["consent_matches_definition_digest"])
        self.assertEqual(accepted["executions_added_by_persisted_run"], 1)
        self.assertEqual(accepted["executions_added_by_drifted_run"], 0)

    def test_the_termination_claim_has_a_fixture_that_bounds_it(self):
        """A detached child must be observed surviving the group kill.

        Without it, "terminates the process group it created" and "bounds every
        descendant" look the same from the outside, and the stronger, false
        claim could return to the documentation unnoticed.

        The survival is only evidence if the scenario actually ran, so the two
        preconditions are asserted here as well: the validator has to have
        started, and its child has to have genuinely left the group. A future
        edit that dropped either one would leave a case that still passed while
        proving less than its name says.
        """
        by_id = {case["id"]: case["expect"] for case in support.check_cases()}
        detached = by_id["detached_child_escapes_the_process_group"]
        self.assertTrue(detached["validator_start_observed"])
        self.assertEqual(detached["executions"], 1)
        self.assertTrue(detached["detached_child_left_the_process_group"])
        self.assertTrue(detached["detached_child_survived_the_group_kill"])
        self.assertTrue(detached["check_ended_before_the_child_did"])

    def test_no_expectation_permits_a_reviewable_verdict(self):
        """The property, asserted over the recorded expectations themselves.

        Every valid pre-commit state combination in the family is enumerated
        here, and not one of them may expect `REVIEWABLE`. A future case that
        wrote one down would fail before it ever ran.
        """
        for case in support.check_cases():
            self.assertNotEqual(
                case["expect"].get("receipt_verdict"),
                "REVIEWABLE",
                case["id"],
            )


if __name__ == "__main__":
    unittest.main()
