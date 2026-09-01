"""Negative controls: does the measurement detect a real breach?

Every control is a reference naive diagnostic workflow that violates a frozen
Doctor invariant. If a control stops reproducing its failure, the control is
broken and must be redesigned - it is never counted as a pass, because a
control that cannot fail proves nothing about a product that passes.
"""

import unittest

from . import support


def _make_test(control):
    def test(self):
        observation = support.harness.run_control(control["id"])
        self.assertTrue(
            observation["control_reproduces_failure"],
            "control %s no longer reproduces its failure. It must be "
            "redesigned, not counted as a pass. Observation: %r"
            % (control["id"], observation),
        )

    test.__name__ = "test_" + control["id"].lower()
    test.__doc__ = control["description"]
    return test


class NegativeControlTests(unittest.TestCase):
    def test_at_least_one_control_exists(self):
        self.assertGreater(len(support.controls.CONTROLS), 0)


for _control in support.controls.CONTROLS:
    setattr(NegativeControlTests, "test_" + _control["id"].lower(), _make_test(_control))
del _control


class ControlVersusDoctorTests(unittest.TestCase):
    """The same fixture, measured twice: naive workflow, then Doctor.

    This is the comparison the benchmark exists to make. The naive workflow
    breaches the invariant on exactly the fixture where Doctor does not.
    """

    def test_index_refresh_control_versus_doctor(self):
        control = support.harness.run_control("NC_DOCTOR_INDEX_REFRESH")
        doctor = support.harness.run_case("stat_dirty_repository")
        self.assertGreater(control["repository_mutations"], 0)
        self.assertEqual(doctor["repository_mutations"], 0)

    def test_filter_execution_control_versus_doctor(self):
        control = support.harness.run_control("NC_DOCTOR_CHECKIN_FILTER_EXECUTION")
        doctor = support.harness.run_case("checkin_filter_configured")
        self.assertGreater(control["repository_defined_executions"], 0)
        self.assertEqual(doctor["repository_defined_executions"], 0)


if __name__ == "__main__":
    unittest.main()
