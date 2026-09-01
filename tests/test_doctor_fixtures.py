"""The Doctor benchmark family, run as tests.

One test per case in `bench/fixtures/doctor/cases.json`. Each one builds the
fixture from nothing, runs Doctor against it under the measurement harness,
and asserts four things:

    the observed diagnosis matches the expectation recorded in cases.json
    the repository was not mutated
    nothing the repository defined was executed
    nothing was written to the isolated home or state directories

The expectations were written from the frozen contract before the
implementation was run against them. They are not a recording of whatever the
code happened to do.
"""

import unittest

from . import support

from aiqe import findings


def _make_test(case):
    def test(self):
        observed = support.harness.run_case(case["id"])
        problems = support.harness.check_expectations(observed, case["expect"])
        if problems:
            self.fail(
                "case %s did not match its expectation:\n  %s"
                % (case["id"], "\n  ".join(problems))
            )

        self.assertEqual(
            observed["repository_mutations"],
            0,
            "DOCTOR_REPOSITORY_MUTATIONS must be 0: %s"
            % (observed["repository_mutation_detail"],),
        )
        self.assertEqual(
            observed["repository_defined_executions"],
            0,
            "DOCTOR_REPOSITORY_DEFINED_EXECUTIONS must be 0: %s"
            % (observed["fired_canaries"],),
        )
        self.assertEqual(
            observed["local_state_writes"],
            0,
            "DOCTOR_LOCAL_STATE_WRITES must be 0: %s"
            % (observed["local_state_write_detail"],),
        )
        self.assertEqual(
            observed["other_changes"],
            [],
            "nothing outside the repository and state directories may change",
        )

        for code in observed["findings"]:
            self.assertIn(
                code,
                findings.ALL_CODES,
                "finding code %r is not declared in aiqe.findings" % (code,),
            )

    test.__name__ = "test_" + case["id"]
    test.__doc__ = case["description"]
    return test


class DoctorFixtureTests(unittest.TestCase):
    pass


for _case in support.cases():
    setattr(DoctorFixtureTests, "test_" + _case["id"], _make_test(_case))
del _case


class FixtureCoverageTests(unittest.TestCase):
    def test_every_builder_has_a_recorded_expectation(self):
        recorded = set(support.case_ids())
        self.assertEqual(set(support.builders.BUILDERS), recorded)

    def test_required_conditions_are_all_covered(self):
        """Every condition the frozen contract names must have a case.

        A benchmark that quietly drops a required condition reports a smaller
        problem than it was asked to measure.
        """
        required = {
            "normal_repository",
            "no_aiqe_config",
            "aiqe_config_present",
            "unborn_repository",
            "non_repository",
            "merge_in_progress",
            "rebase_in_progress",
            "cherry_pick_in_progress",
            "sparse_checkout",
            "linked_worktree",
            "tracked_gitattributes",
            "commit_signing_configured",
            "local_hooks_path",
            "config_include_present",
            "config_include_if_present",
            "checkin_filter_configured",
            "claude_bounded",
            "claude_broad",
            "codex_bounded",
            "codex_broad",
        }
        missing = required - set(support.case_ids())
        self.assertEqual(missing, set(), "uncovered required conditions")


if __name__ == "__main__":
    unittest.main()
