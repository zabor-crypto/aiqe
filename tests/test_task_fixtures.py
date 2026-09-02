"""The Task benchmark family, run as tests.

One test per case in `bench/fixtures/task/cases.json`. Each builds the fixture
from nothing, drives the real command-line entry point against it under the
measurement harness, and asserts four things:

    the observation matches the expectation recorded in cases.json
    nothing in the repository changed except AIQE's own private state
    nothing was written to the isolated home or state directories
    nothing the repository defined was executed

The expectations were written from the frozen contract before the
implementation was run against them.
"""

import unittest

from . import support


def _make_test(case):
    def test(self):
        if not support.task_harness.case_applies(case):
            self.skipTest(
                "case %s requires platform %r" % (case["id"], case.get("platform"))
            )
        observed = support.task_harness.run_case(case["id"])
        problems = support.task_harness.check_expectations(observed, case["expect"])
        if problems:
            self.fail(
                "case %s did not match its expectation:\n  %s"
                % (case["id"], "\n  ".join(problems))
            )

        self.assertEqual(
            observed["repository_mutations"],
            0,
            "TASK_WRITE_CONFINEMENT: nothing in the repository, .git included, "
            "may change: %s" % (observed["repository_mutation_detail"],),
        )
        self.assertEqual(
            observed["local_state_writes"],
            0,
            "task operations must not write outside the repository: %s"
            % (observed["local_state_write_detail"],),
        )
        self.assertEqual(
            observed["repository_defined_executions"],
            0,
            "TASK_REPOSITORY_DEFINED_EXECUTIONS: %s" % (observed["fired_canaries"],),
        )
        self.assertEqual(observed["other_changes"], [])

    test.__name__ = "test_" + case["id"]
    test.__doc__ = case["description"]
    return test


class TaskFixtureTests(unittest.TestCase):
    pass


for _case in support.task_cases():
    setattr(TaskFixtureTests, "test_" + _case["id"], _make_test(_case))
del _case


class FixtureCoverageTests(unittest.TestCase):
    def test_every_scenario_has_a_recorded_expectation(self):
        self.assertEqual(
            set(support.task_builders.SCENARIOS), set(support.task_case_ids())
        )

    def test_required_conditions_are_all_covered(self):
        """Every condition the task contract names must have a case."""
        required = {
            "simple_file_scope",
            "untracked_regular_file",
            "nonexistent_future_path",
            "existing_directory_refused",
            "symlink_refused",
            "special_file_refused",
            "duplicate_declaration_refused",
            "lexical_parent_and_child",
            "unborn_head_refused",
            "salt_created_only_on_write",
            "foreign_staged_count_at_start",
            "superseded_schema_fail_closed",
            "literal_metacharacter_names",
            "whitespace_names",
            "subdirectory_invocation",
            "scope_rejections",
            "foreign_staged_preserved",
            "repository_defined_execution",
            "linked_worktree_isolation",
            "concurrent_start",
            "interrupted_write",
            "unsafe_state_location",
            "non_utf8_owned_path",
        }
        self.assertEqual(required - set(support.task_case_ids()), set())


if __name__ == "__main__":
    unittest.main()
