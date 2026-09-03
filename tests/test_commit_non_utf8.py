"""End-to-end proof that a completion commit keeps a path's exact bytes.

The path is declared, checked, committed and verified through the real entry
point with byte-preserving argv, and the resulting commit is read back with
the harness's own Git invocations. If any layer decoded a path instead of
carrying its bytes, this is where it would show — and it is the case where a
pathspec would silently do something else.

APFS refuses non-UTF-8 filenames, so the case is Linux-only. Setting
AIQE_REQUIRE_NON_UTF8=1 turns skipping into an error; continuous integration
sets it on the Linux job so the proof cannot quietly stop happening.
"""

import os
import sys
import unittest

from . import support

REQUIRED = os.environ.get("AIQE_REQUIRE_NON_UTF8") == "1"
CASE = "commit-non-utf8-name"


class NonUtf8CompletionCommitTests(unittest.TestCase):
    def setUp(self):
        if sys.platform.startswith("linux"):
            return
        message = (
            "the arbitrary-byte completion-commit fixture needs a filesystem "
            "that accepts non-UTF-8 names; this platform is %r" % (sys.platform,)
        )
        if REQUIRED:
            self.fail(
                "AIQE_REQUIRE_NON_UTF8=1 but the case cannot run here: " + message
            )
        self.skipTest(message)

    def observe(self):
        return support.commit_harness.run_case(CASE)

    def test_the_commit_is_created_and_reviewable(self):
        observed = self.observe()
        self.assertEqual(observed["commit_exit"], 0)
        self.assertTrue(observed["commit_created"])
        self.assertEqual(observed["receipt_verdict"], "REVIEWABLE")

    def test_the_changed_pathset_is_exactly_the_declared_bytes(self):
        observed = self.observe()
        expected = support.commit_builders.NON_UTF8.decode("utf-8", "surrogateescape")
        self.assertEqual(observed["changed_paths"], [expected])
        self.assertEqual(observed["expected_changed_paths"], [expected])

    def test_the_parent_and_foreign_staged_proofs_hold(self):
        observed = self.observe()
        self.assertTrue(observed["parent_is_pre_commit_head"])
        self.assertTrue(observed["foreign_staged_preserved"])

    def test_no_worktree_path_was_written_by_aiqe(self):
        observed = self.observe()
        self.assertEqual(observed["aiqe_core_worktree_mutations"], 0)
        self.assertEqual(observed["policy_canary_executions"], 0)

    def test_output_carries_no_raw_terminal_control_bytes(self):
        observed = self.observe()
        self.assertEqual(observed["commit_output_control_bytes"], 0)
        self.assertEqual(observed["receipt_output_control_bytes"], 0)

    def test_fixture_really_uses_a_non_utf8_name(self):
        with self.assertRaises(UnicodeDecodeError):
            support.commit_builders.NON_UTF8.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
