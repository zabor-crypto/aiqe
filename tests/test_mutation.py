"""Focused zero-write and zero-execution proof on the adversarial fixtures.

`test_doctor_fixtures` asserts the three zero-tolerance quantities across
every case. This module goes further on the handful of fixtures that are
specifically built to break them, and asserts the mechanism rather than only
the aggregate: the index bytes, the individual canary, the hardening flags
that make the difference.

None of it is Doctor reporting on itself. Every measurement here is taken by
the harness from outside the process.
"""

import os
import unittest

from . import support

ADVERSARIAL = (
    "stat_dirty_repository",
    "fsmonitor_configured",
    "checkin_filter_configured",
    "installed_hook",
    "executable_alias_configured",
)


class ZeroWriteTests(unittest.TestCase):
    def test_adversarial_fixtures_are_not_mutated(self):
        for case_id in ADVERSARIAL:
            observed = support.harness.run_case(case_id)
            self.assertEqual(
                observed["repository_mutations"],
                0,
                "%s mutated the repository: %s"
                % (case_id, observed["repository_mutation_detail"]),
            )
            self.assertEqual(
                observed["repository_defined_executions"],
                0,
                "%s executed something the repository defined: %s"
                % (case_id, observed["fired_canaries"]),
            )
            self.assertEqual(
                observed["local_state_writes"],
                0,
                "%s wrote local state: %s"
                % (case_id, observed["local_state_write_detail"]),
            )

    def test_index_is_byte_identical_after_doctor(self):
        """The index is where a diagnostic tool leaks writes.

        A plain `git status` rewrites it on this exact fixture. The assertion
        is on the file's content hash, size, mode and modification time, so a
        rewrite of identical bytes would still be caught.
        """
        observed = support.harness.run_case("stat_dirty_repository")
        touched = [
            change
            for change in observed["repository_mutation_detail"]
            if "index" in change
        ]
        self.assertEqual(touched, [])
        self.assertEqual(observed["repository_mutations"], 0)


class HardeningTests(unittest.TestCase):
    """The flags are not decoration; assert they are actually applied."""

    def test_every_repository_invocation_is_hardened(self):
        observed = support.harness.run_case("fsmonitor_configured")
        for invocation in observed["git_invocations"]:
            if invocation[1:2] == ["--version"]:
                continue
            self.assertIn("--no-optional-locks", invocation, invocation)
            self.assertIn("core.fsmonitor=false", invocation, invocation)

    def test_only_allowlisted_subcommands_are_invoked(self):
        from aiqe.gitq import ALLOWED_SUBCOMMANDS

        # A representative slice rather than every case: the full argument
        # vectors for all cases are already asserted by the fixture suite,
        # and rebuilding every fixture a second time buys nothing.
        for case_id in ("normal_repository", "unborn_repository", "checkin_filter_configured"):
            observed = support.harness.run_case(case_id)
            for invocation in observed["git_invocations"]:
                self.assertTrue(invocation[0].endswith("git"), invocation)
                subcommands = [
                    argument
                    for argument in invocation[1:]
                    if argument in ALLOWED_SUBCOMMANDS
                ]
                self.assertTrue(
                    subcommands,
                    "invocation contains no allowlisted subcommand: %r" % (invocation,),
                )

    def test_no_content_comparison_when_a_filter_is_configured(self):
        """Doctor must not ask the question that would run the filter."""
        observed = support.harness.run_case("checkin_filter_configured")
        for invocation in observed["git_invocations"]:
            self.assertNotIn("status", invocation, invocation)
            self.assertNotIn("diff-files", invocation, invocation)
        self.assertIs(observed["working_state"]["unstaged"], None)
        self.assertFalse(observed["working_state"]["determined"])


class IsolationTests(unittest.TestCase):
    def test_harness_environment_is_isolated_from_the_real_machine(self):
        """The measurement is only meaningful if the fixture cannot escape."""
        import shutil
        import tempfile

        root = tempfile.mkdtemp(prefix="aiqe-isolation-")
        self.addCleanup(shutil.rmtree, root, True)
        case = support.harness.Case("normal_repository", root)
        env = case.env()

        self.assertTrue(env["HOME"].startswith(root))
        self.assertTrue(env["XDG_STATE_HOME"].startswith(root))
        self.assertTrue(env["XDG_CONFIG_HOME"].startswith(root))
        self.assertTrue(env["GIT_CONFIG_GLOBAL"].startswith(root))
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertNotEqual(env["HOME"], os.environ.get("HOME"))


if __name__ == "__main__":
    unittest.main()
