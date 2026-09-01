"""Rendering: determinism, ordering, and the claims the output must not make.

Doctor's output is a product surface. These tests hold it to the frozen
vocabulary - no safety score, no green shield, no borrowing of the task
receipt verdicts - and to byte-level determinism, without needing a Git
repository to do it.
"""

import json
import unittest

from . import support  # noqa: F401

from aiqe import findings as f
from aiqe.doctor import Report
from aiqe.report import render_human, render_json


def build(states_and_codes, result="PRODUCED"):
    report = Report()
    report.result = result
    report.repository.update({"detected": True, "kind": "worktree", "head": "branch"})
    report.working_state.update(
        {"staged": 0, "unstaged": 0, "untracked": 0, "unmerged": 0, "determined": True}
    )
    for code, state in states_and_codes:
        report.add(code, state, "summary for %s" % (code,))
    return report


class DeterminismTests(unittest.TestCase):
    def test_json_render_is_byte_identical_across_calls(self):
        report = build([(f.LINKED_WORKTREE, f.FINDING), (f.HEAD_DETACHED, f.FINDING)])
        first = render_json(report, "0.0.0")
        second = render_json(report, "0.0.0")
        self.assertEqual(first, second)

    def test_json_keys_are_sorted(self):
        report = build([])
        document = json.loads(render_json(report, "0.0.0"))
        self.assertEqual(list(document), sorted(document))

    def test_findings_order_does_not_depend_on_discovery_order(self):
        forwards = build(
            [(f.HEAD_DETACHED, f.FINDING), (f.LINKED_WORKTREE, f.FINDING)]
        )
        backwards = build(
            [(f.LINKED_WORKTREE, f.FINDING), (f.HEAD_DETACHED, f.FINDING)]
        )
        self.assertEqual(render_json(forwards, "0.0.0"), render_json(backwards, "0.0.0"))

    def test_unresolved_states_sort_ahead_of_findings(self):
        report = build(
            [
                (f.LINKED_WORKTREE, f.FINDING),
                (f.WORKING_STATE_UNKNOWN, f.UNKNOWN),
                (f.REPOSITORY_BARE, f.UNSUPPORTED),
            ]
        )
        order = [finding.state for finding in report.sorted_findings()]
        self.assertEqual(order, [f.UNSUPPORTED, f.UNKNOWN, f.FINDING])


class SchemaTests(unittest.TestCase):
    def test_required_top_level_keys(self):
        document = json.loads(render_json(build([]), "1.2.3"))
        for key in (
            "schema_version",
            "aiqe_version",
            "command",
            "result",
            "exit_code",
            "git",
            "repository",
            "findings",
            "state_counts",
            "working_state",
        ):
            self.assertIn(key, document)
        self.assertEqual(document["aiqe_version"], "1.2.3")

    def test_findings_carry_a_stable_code_not_prose_identity(self):
        report = build([(f.LINKED_WORKTREE, f.FINDING)])
        document = json.loads(render_json(report, "0.0.0"))
        self.assertEqual(document["findings"][0]["code"], "LINKED_WORKTREE")
        self.assertEqual(document["findings"][0]["state"], "FINDING")
        self.assertIn("summary", document["findings"][0])

    def test_unknown_working_state_is_null_not_zero(self):
        """A number that was never determined must not render as zero."""
        report = build([(f.WORKING_STATE_UNSTAGED_UNKNOWN, f.UNKNOWN)])
        report.working_state["unstaged"] = None
        report.working_state["determined"] = False
        document = json.loads(render_json(report, "0.0.0"))
        self.assertIsNone(document["working_state"]["unstaged"])
        self.assertFalse(document["working_state"]["determined"])


class VocabularyTests(unittest.TestCase):
    def test_output_contains_no_safety_score(self):
        report = build([(f.LINKED_WORKTREE, f.FINDING)])
        rendered = render_human(report) + render_json(report, "0.0.0")
        lowered = rendered.lower()
        for forbidden in ("score", "grade", "rating", "safety level", "out of 10", "%"):
            self.assertNotIn(forbidden, lowered, forbidden)

    def test_output_does_not_borrow_the_receipt_verdicts(self):
        """REVIEWABLE / INCOMPLETE / NOT_REVIEWABLE are receipt semantics.

        Doctor describes a repository; it does not adjudicate a unit of work,
        and reusing that vocabulary here would imply it did.
        """
        report = build([(f.LINKED_WORKTREE, f.FINDING)])
        rendered = render_human(report) + render_json(report, "0.0.0")
        for verdict in ("REVIEWABLE", "NOT_REVIEWABLE", "INCOMPLETE"):
            self.assertNotIn(verdict, rendered, verdict)

    def test_clean_repository_renders_as_an_absence_of_findings(self):
        rendered = render_human(build([]))
        self.assertIn("No findings.", rendered)
        for badge in ("PASS", "OK", "SAFE", "SECURE"):
            self.assertNotIn(badge, rendered, badge)

    def test_unknown_count_renders_as_a_question_mark_not_zero(self):
        report = build([(f.WORKING_STATE_UNSTAGED_UNKNOWN, f.UNKNOWN)])
        report.working_state["unstaged"] = None
        rendered = render_human(report)
        self.assertIn("? unstaged", rendered)


class HumanLayoutTests(unittest.TestCase):
    def test_header_and_sections(self):
        rendered = render_human(build([]))
        self.assertTrue(rendered.startswith("AIQE DOCTOR\n"))
        for label in ("Repository", "Git state", "Topology", "AIQE config", "Commit policy"):
            self.assertIn(label, rendered)

    def test_no_ansi_escape_sequences(self):
        """No colour library, and no hand-rolled escape codes either."""
        rendered = render_human(build([(f.LINKED_WORKTREE, f.FINDING)]))
        self.assertNotIn("\x1b", rendered)

    def test_tally_counts_states_separately(self):
        report = build(
            [
                (f.LINKED_WORKTREE, f.FINDING),
                (f.HEAD_DETACHED, f.FINDING),
                (f.WORKING_STATE_UNKNOWN, f.UNKNOWN),
            ]
        )
        rendered = render_human(report)
        self.assertIn("1 unknown", rendered)
        self.assertIn("2 findings", rendered)


class ExitStatusTests(unittest.TestCase):
    def test_findings_alone_do_not_change_the_exit_status(self):
        report = build([(f.LINKED_WORKTREE, f.FINDING), (f.HEAD_DETACHED, f.FINDING)])
        self.assertEqual(report.exit_code(), 0)

    def test_unknowns_alone_do_not_change_the_exit_status(self):
        report = build([(f.WORKING_STATE_UNKNOWN, f.UNKNOWN)])
        self.assertEqual(report.exit_code(), 0)

    def test_unsupported_result_exits_three(self):
        report = build([(f.REPOSITORY_BARE, f.UNSUPPORTED)], result="UNSUPPORTED")
        self.assertEqual(report.exit_code(), 3)

    def test_doctor_never_exits_one_or_two(self):
        for result in ("PRODUCED", "UNSUPPORTED"):
            self.assertNotIn(build([], result=result).exit_code(), (1, 2))


if __name__ == "__main__":
    unittest.main()
