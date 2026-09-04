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


class InformationalRaceCountIsNotAuthoritativeTests(unittest.TestCase):
    """The race count must never be able to make this family disagree.

    Several cases in this family race a concurrent process against AIQE's own
    window on purpose. Git legitimately writes a different number of objects,
    lock files and reflog entries depending on how that race lands: two
    correct runs on one machine, minutes apart, reported 292 and 295 across
    four cases while every zero-tolerance total and every case outcome stayed
    identical.

    So the count is recorded as a diagnostic and compared by nothing. This is
    the regression that keeps it that way. Without it, a later tidy-up that
    folded `diagnostics` back into the comparison would look harmless and
    would make a correct family fail intermittently - the worst kind of red,
    because the reflex is to distrust the test rather than the comparison.
    """

    def comparator(self):
        """Load `bench/compare-results.py`, whose name is not importable."""
        import importlib.util
        import os

        path = os.path.join(support.BENCH, "compare-results.py")
        spec = importlib.util.spec_from_file_location("aiqe_compare_results", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def retained(self):
        import json
        import os

        path = os.path.join(support.BENCH, "results", "commit", "results.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_raw_count_is_not_in_the_authoritative_record(self):
        """It may exist; it may not exist where a comparison would find it."""
        comparator = self.comparator()
        document = comparator.authoritative(self.retained())
        self.assertNotIn("diagnostics", document)
        self.assertNotIn("aiqe_commit_git_writes", document.get("counts", {}))
        self.assertNotIn("aiqe_commit_git_writes", document.get("totals", {}))
        for case in document["cases"]:
            self.assertNotIn("diagnostics", case, case["case"])
            self.assertNotIn("aiqe_commit_git_writes", case, case["case"])

    def test_the_stable_fact_underneath_it_is_still_recorded(self):
        """Dropping the count must not drop the evidence it stood for."""
        retained = self.retained()
        observed = [
            case
            for case in retained["cases"]
            if case.get("aiqe_commit_git_writes_observed")
        ]
        self.assertTrue(
            observed,
            "no case records that its completion commit wrote through Git, "
            "which would mean the stable replacement measures nothing",
        )
        self.assertEqual(
            retained["counts"]["cases_with_commit_git_writes"], len(observed)
        )

    def test_two_runs_differing_only_in_the_race_count_still_agree(self):
        """The regression itself.

        One retained document, and a copy of it whose every race count has
        been changed - document level and per case. Nothing else differs. The
        comparator must see no disagreement.
        """
        import copy

        comparator = self.comparator()
        retained = self.retained()

        fresh = copy.deepcopy(retained)
        fresh.setdefault("diagnostics", {})["aiqe_commit_git_writes"] = (
            retained.get("diagnostics", {}).get("aiqe_commit_git_writes", 0) + 3
        )
        for index, case in enumerate(fresh["cases"]):
            case.setdefault("diagnostics", {})["aiqe_commit_git_writes"] = (
                case.get("diagnostics", {}).get("aiqe_commit_git_writes", 0)
                + index
                + 1
            )

        left = comparator.authoritative(retained)
        right = comparator.authoritative(fresh)
        self.assertEqual(
            left,
            right,
            "two results differing only in the informational race count are "
            "not identical once the non-authoritative sections are stripped",
        )

    def test_a_real_disagreement_is_still_caught(self):
        """A control on the control: stripping must not blind the comparison.

        If `authoritative` removed too much, the test above would pass for the
        wrong reason. So the same machinery is shown to still notice a change
        to something that does carry authority.
        """
        import copy

        comparator = self.comparator()
        retained = self.retained()

        for mutate in (
            lambda d: d["totals"].__setitem__("aiqe_push_calls", 1),
            lambda d: d["cases"][0].__setitem__("outcome", "FAIL"),
            lambda d: d.__setitem__("cases_total", d["cases_total"] + 1),
        ):
            broken = copy.deepcopy(retained)
            mutate(broken)
            self.assertNotEqual(
                comparator.authoritative(retained),
                comparator.authoritative(broken),
                "a change to an authoritative quantity survived stripping",
            )
