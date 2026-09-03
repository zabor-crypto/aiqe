"""The bounded-commit benchmark family, run as tests.

One test per case in `bench/fixtures/commit/cases.json`. Each builds a real
disposable repository from nothing, drives the real command-line entry point
against it under the measurement harness, and asserts the claims this family
actually makes:

    the observation matches the expectation recorded in cases.json
    AIQE core wrote no worktree path
    no commit hook, filter driver or signer ever ran
    nothing was written outside AIQE's machine-local state home
    every commit's parent is the pre-commit HEAD
    every commit's changed pathset is exactly the expected owned pathset
    no REVIEWABLE verdict exists without a commit behind it

Note what is deliberately *not* asserted: that the repository did not change.
A completion commit writes the index, the object database, HEAD and the
reflog. Claiming `.git` byte immutability for an operation whose whole job is
to create a commit would be false, so those writes are attributed rather than
denied, and the zero is kept where it belongs.
"""

import unittest

from . import support


def _make_test(case):
    def test(self):
        if not support.commit_harness.case_applies(case):
            self.skipTest(
                "case %s requires platform %r" % (case["id"], case.get("platform"))
            )
        observed = support.commit_harness.run_case(case["id"])
        problems = support.commit_harness.check_expectations(
            observed, case["expect"]
        )
        if problems:
            self.fail(
                "case %s did not match its expectation:\n  %s"
                % (case["id"], "\n  ".join(problems))
            )

        self.assertEqual(
            observed["aiqe_core_worktree_mutations"],
            0,
            "AIQE_CORE_WORKTREE_MUTATIONS: %s"
            % (observed["aiqe_core_worktree_mutation_detail"],),
        )
        self.assertEqual(
            observed["policy_canary_executions"],
            0,
            "repository-defined commit policy code ran: %s"
            % (observed["policy_canaries"],),
        )
        self.assertEqual(
            observed["local_state_writes"],
            0,
            "writes outside the AIQE state home: %s"
            % (observed["local_state_write_detail"],),
        )
        self.assertEqual(observed["other_changes"], [])
        self.assertEqual(observed["remotes_configured"], 0)
        self.assertFalse(observed["receipt_discloses_commit_sha"])

        if observed["commit_created"]:
            self.assertTrue(observed["parent_is_pre_commit_head"])
            self.assertEqual(
                sorted(observed["changed_paths"]),
                sorted(observed["expected_changed_paths"]),
            )
        if observed.get("receipt_verdict") == "REVIEWABLE":
            self.assertTrue(
                observed["commit_created"],
                "REVIEWABLE without a commit is the one state this product "
                "must never reach",
            )
            self.assertTrue(observed["foreign_staged_preserved"])

    test.__name__ = "test_" + case["id"]
    test.__doc__ = case["description"]
    return test


class CommitFixtureTests(unittest.TestCase):
    pass


for _case in support.commit_cases():
    setattr(CommitFixtureTests, "test_" + _case["id"], _make_test(_case))
del _case
