"""Negative controls for the task boundary.

Each control is a reference naive implementation of the same feature. If one
stops reproducing its failure it is broken and must be redesigned; it is never
counted as a pass, because a control that cannot fail proves nothing about a
product that passes.
"""

import unittest

from . import support


def _make_test(control):
    def test(self):
        observation = support.task_harness.run_control(control["id"])
        self.assertTrue(
            observation["control_reproduces_failure"],
            "control %s no longer reproduces its failure. Redesign it rather "
            "than counting it as a pass. Observation: %r"
            % (control["id"], observation),
        )

    test.__name__ = "test_" + control["id"].lower()
    test.__doc__ = control["description"]
    return test


class TaskNegativeControlTests(unittest.TestCase):
    def test_controls_exist(self):
        self.assertEqual(len(support.task_controls.CONTROLS), 3)


for _control in support.task_controls.CONTROLS:
    setattr(
        TaskNegativeControlTests, "test_" + _control["id"].lower(), _make_test(_control)
    )
del _control


class ControlVersusProductTests(unittest.TestCase):
    """The same fixture, measured twice: naive implementation, then AIQE."""

    def test_pathspec_expansion_versus_literal_ownership(self):
        observation = support.task_harness.run_control("NC_TASK_PATHSPEC_EXPANSION")
        self.assertGreater(observation["naive_matched_count"], 1)
        self.assertEqual(observation["aiqe_owned"], ["*"])

    def test_shared_state_versus_worktree_local_state(self):
        observation = support.task_harness.run_control(
            "NC_TASK_SHARED_WORKTREE_STATE"
        )
        self.assertTrue(observation["naive_b_sees_a_task"])
        self.assertFalse(observation["aiqe_b_sees_a_task"])

    def test_lost_race_versus_locking(self):
        observation = support.task_harness.run_control("NC_TASK_LOST_START_RACE")
        self.assertGreater(observation["naive_successes"], 1)
        self.assertEqual(observation["aiqe_successes"], 1)
        self.assertEqual(observation["aiqe_refusals"], 1)


if __name__ == "__main__":
    unittest.main()
