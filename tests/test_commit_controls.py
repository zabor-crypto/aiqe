"""Negative controls for the bounded completion commit.

Each control is a reference naive implementation of the same feature, and each
produces a result that looks like success and is not justified. If one stops
reproducing its failure it is broken and must be redesigned; it is never
counted as a pass, because a control that cannot fail proves nothing about a
product that passes.
"""

import unittest

from . import support


def _make_test(control):
    def test(self):
        observation = support.commit_harness.run_control(control["id"])
        self.assertTrue(
            observation["control_reproduces_failure"],
            "control %s no longer reproduces its failure. Redesign it rather "
            "than counting it as a pass. Observation: %r"
            % (control["id"], observation),
        )

    test.__name__ = "test_" + control["id"].lower().replace("-", "_")
    test.__doc__ = control["description"]
    return test


class CommitNegativeControlTests(unittest.TestCase):
    def test_controls_exist(self):
        self.assertEqual(len(support.commit_controls.CONTROLS), 8)


for _control in support.commit_controls.CONTROLS:
    setattr(
        CommitNegativeControlTests,
        "test_" + _control["id"].lower().replace("-", "_"),
        _make_test(_control),
    )
del _control


class ControlVersusProductTests(unittest.TestCase):
    """The same fixture, measured twice: naive implementation, then AIQE."""

    def test_shared_index_versus_bounded_pathset(self):
        observation = support.commit_harness.run_control("NC-COMMIT-SHARED-INDEX")
        self.assertTrue(observation["naive_absorbed_foreign_staged"])
        self.assertEqual(
            observation["aiqe_changed_paths"],
            [support.commit_builders.OWNED_TEXT],
        )
        self.assertTrue(observation["aiqe_foreign_staged_preserved"])
        self.assertEqual(observation["aiqe_verdict"], "REVIEWABLE")

    def test_pathspec_versus_literal_path(self):
        observation = support.commit_harness.run_control("NC-COMMIT-PATHSPEC")
        self.assertTrue(observation["naive_broadened_pathset"])
        self.assertIn("src/starDECOY.py", observation["naive_changed_paths"])
        self.assertEqual(observation["aiqe_changed_paths"], ["src/star*.py"])

    def test_check_then_edit_versus_premutation_recheck(self):
        observation = support.commit_harness.run_control("NC-COMMIT-STALE")
        self.assertTrue(observation["naive_committed_unchecked_content"])
        self.assertFalse(observation["aiqe_commit_created"])
        self.assertEqual(observation["aiqe_commit_exit"], 2)
        self.assertIn("STALE_OWNED_CONTENT", observation["aiqe_commit_reasons"])
        self.assertTrue(observation["aiqe_index_unchanged"])

    def test_intent_to_add_residue_versus_scope_rollback(self):
        observation = support.commit_harness.run_control("NC-COMMIT-ITA-ROLLBACK")
        self.assertTrue(observation["naive_index_residue"])
        self.assertFalse(observation["aiqe_index_residue"])
        self.assertTrue(observation["aiqe_index_unchanged"])
        self.assertFalse(observation["aiqe_commit_created"])

    def test_hook_execution_versus_refusal(self):
        observation = support.commit_harness.run_control("NC-COMMIT-HOOK-POLICY")
        self.assertTrue(observation["naive_ran_hook"])
        self.assertFalse(observation["aiqe_ran_hook"])
        self.assertEqual(observation["aiqe_commit_exit"], 3)

    def test_signing_bypass_versus_refusal(self):
        observation = support.commit_harness.run_control("NC-COMMIT-SIGNING-POLICY")
        self.assertTrue(observation["naive_bypassed_signing_policy"])
        self.assertFalse(observation["aiqe_commit_created"])
        self.assertFalse(observation["aiqe_ran_signer"])
        self.assertEqual(observation["aiqe_commit_exit"], 3)

    def test_filter_execution_versus_refusal(self):
        observation = support.commit_harness.run_control("NC-COMMIT-FILTER")
        self.assertTrue(observation["naive_ran_filter"])
        self.assertFalse(observation["aiqe_ran_filter"])
        self.assertEqual(observation["aiqe_commit_exit"], 3)

    def test_concurrent_foreign_staging_versus_excluded(self):
        """`EXCLUDED` is a before-and-after claim, and this is why.

        A concurrent process stages a path AIQE does not own, inside AIQE's
        own mutation window. The commit itself is correct - the owned pathset
        and its content are exactly right - and AIQE still refuses to call the
        foreign staged state excluded, because it is not what it was.
        """
        observation = support.commit_harness.run_control("NC-COMMIT-FOREIGN-RACE")
        self.assertTrue(
            observation["concurrent_stage_landed"],
            "the control did not land inside the mutation window, so it "
            "proved nothing this run",
        )
        self.assertNotEqual(
            observation["aiqe_recorded_pre_digest"],
            observation["aiqe_recorded_post_digest"],
        )
        self.assertEqual(observation["aiqe_foreign_staged"], "UNKNOWN")
        self.assertEqual(observation["aiqe_verdict"], "INCOMPLETE")
        self.assertEqual(observation["aiqe_receipt_exit"], 2)


if __name__ == "__main__":
    unittest.main()
