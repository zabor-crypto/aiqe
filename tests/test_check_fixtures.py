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
        """Every condition the OSS-6C contract names must have a case."""
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
        }
        self.assertEqual(required - set(support.check_case_ids()), set())

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
