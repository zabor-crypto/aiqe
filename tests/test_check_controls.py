"""Negative controls for check, evidence and receipt.

Each control is a reference naive implementation of the same feature, and each
produces a green result that is not justified. If one stops reproducing its
failure it is broken and must be redesigned; it is never counted as a pass,
because a control that cannot fail proves nothing about a product that passes.
"""

import unittest

from . import support


def _make_test(control):
    def test(self):
        observation = support.check_harness.run_control(control["id"])
        self.assertTrue(
            observation["control_reproduces_failure"],
            "control %s no longer reproduces its failure. Redesign it rather "
            "than counting it as a pass. Observation: %r"
            % (control["id"], observation),
        )

    test.__name__ = "test_" + control["id"].lower()
    test.__doc__ = control["description"]
    return test


class CheckNegativeControlTests(unittest.TestCase):
    def test_controls_exist(self):
        self.assertEqual(len(support.check_controls.CONTROLS), 4)


for _control in support.check_controls.CONTROLS:
    setattr(
        CheckNegativeControlTests, "test_" + _control["id"].lower(), _make_test(_control)
    )
del _control


class ControlVersusProductTests(unittest.TestCase):
    """The same fixture, measured twice: naive implementation, then AIQE."""

    def test_check_then_edit_versus_checked_content_binding(self):
        observation = support.check_harness.run_control("NC_CHECK_STALENESS")
        self.assertTrue(observation["naive_still_reports_green"])
        self.assertEqual(observation["aiqe_check_completion"], "REVIEWABLE_CANDIDATE")
        self.assertEqual(observation["aiqe_receipt_evidence"], "STALE")
        self.assertEqual(observation["aiqe_receipt_verdict"], "INCOMPLETE")
        self.assertEqual(observation["aiqe_receipt_exit"], 2)

    def test_generic_tests_versus_contract_coverage(self):
        observation = support.check_harness.run_control("NC_MISSING_QUANT_VALIDATOR")
        self.assertTrue(observation["naive_reports_green"])
        self.assertEqual(observation["aiqe_coverage"], {"CAUSALITY": "COVERAGE_GAP"})
        self.assertEqual(observation["aiqe_check_exit"], 2)
        self.assertEqual(observation["aiqe_receipt_verdict"], "INCOMPLETE")

    def test_declared_versus_consented_execution(self):
        observation = support.check_harness.run_control("NC_CONSENT")
        self.assertTrue(observation["naive_executed_declared_command"])
        self.assertFalse(observation["aiqe_executed_declared_command"])
        self.assertEqual(observation["aiqe_outcomes"], {"causality": "UNKNOWN"})
        self.assertEqual(observation["aiqe_reasons"], {"causality": "CONSENT_REQUIRED"})

    def test_self_editing_validator_versus_measured_authority(self):
        observation = support.check_harness.run_control("NC_VALIDATOR_MUTATES_OWNED")
        self.assertTrue(observation["validator_changed_the_file_it_checked"])
        self.assertTrue(observation["naive_reports_green_and_current"])
        self.assertNotEqual(observation["aiqe_receipt_evidence"], "CURRENT")
        self.assertEqual(observation["aiqe_check_exit"], 2)


if __name__ == "__main__":
    unittest.main()
