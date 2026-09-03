"""The Git version AIQE refuses to run below, and why that floor exists.

Every AIQE command rests on one invariant: nothing the repository defines is
executed. That invariant is delivered by pointing `GIT_CONFIG_SYSTEM` and
`GIT_CONFIG_GLOBAL` at the null device before any invocation that reads the
index or the worktree.

Those two variables were introduced in Git 2.32. An older Git does not know
the names, so it does not read them **and does not complain**: the isolation
is applied, the command succeeds, and `$HOME/.gitconfig` is in scope the whole
time. `GIT_CONFIG_NOSYSTEM` is not a fallback for this. It declines the system
file and says nothing about the per-user one.

The consequence is not cosmetic, and it is not theoretical. It was measured:
on Debian 11 (Git 2.30.2) the negative control `NC_DOCTOR_GLOBAL_FILTER_
EXECUTION` stopped reproducing - because the fixture's globally defined filter
driver was never in scope at all - and the bounded-commit policy preflight
returned 0, creating a commit, where it must return 3 and refuse.

So AIQE fails closed. These tests hold that line from both directions: the
refusal fires below the floor, and it does not fire above it.
"""

import io
import os
import shutil
import stat
import tempfile
import unittest

from . import support  # noqa: F401  (path wiring)

from aiqe import cli, exits, gitq


def fake_git(directory, version_line):
    """A `git` that reports a version and refuses everything else.

    Refusing everything else is deliberate. If the refusal under test failed
    to fire, the command would go on to run real Git subcommands against this
    binary and fail confusingly; failing loudly instead keeps the reason for a
    red test unambiguous.
    """
    path = os.path.join(directory, "git")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then echo "%s"; exit 0; fi\n'
            'echo "fake git: no subcommand should have been reached" >&2\n'
            "exit 1\n" % (version_line,)
        )
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


class VersionOrderingTests(unittest.TestCase):
    def test_the_floor_is_the_release_that_introduced_the_variables(self):
        """2.32, and the reason is recorded next to the constant."""
        self.assertEqual(gitq.MINIMUM_GIT_VERSION, (2, 32))

    def test_a_vendor_suffix_does_not_break_the_ordering(self):
        """macOS reports `2.50.1 (Apple Git-155)`; only the numbers order it."""
        self.assertEqual(gitq.version_tuple("2.50.1"), (2, 50, 1))
        supported, reason = gitq.config_isolation_supported("2.50.1")
        self.assertTrue(supported)
        self.assertIsNone(reason)

    def test_versions_below_the_floor_are_unsupported(self):
        for version in ("2.30.2", "2.31.9", "2.25.1", "1.9.0"):
            with self.subTest(version=version):
                supported, reason = gitq.config_isolation_supported(version)
                self.assertFalse(supported)
                self.assertEqual(reason, gitq.GIT_TOO_OLD)

    def test_the_floor_itself_is_supported(self):
        supported, _reason = gitq.config_isolation_supported("2.32.0")
        self.assertTrue(supported)

    def test_an_unreadable_version_fails_closed(self):
        """An unknown toolchain is not assumed to be a good one."""
        for version in (None, "", "banana", "v2.40"):
            with self.subTest(version=version):
                supported, reason = gitq.config_isolation_supported(version)
                self.assertFalse(supported)
                self.assertEqual(reason, gitq.GIT_VERSION_UNKNOWN)


class RefusalTests(unittest.TestCase):
    """The refusal, through the real command-line entry point."""

    GIT_TOUCHING_COMMANDS = (
        ["doctor"],
        ["doctor", "--format", "json"],
        ["init", "--print"],
        ["task"],
        ["task", "start", "--own", "a.py"],
        ["task", "end"],
        ["check"],
        ["commit", "-m", "message"],
        ["receipt"],
    )

    def run_cli(self, argv, version_line):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        fake_git(directory, version_line)
        env = dict(os.environ)
        env["PATH"] = directory + os.pathsep + env.get("PATH", "")
        out, err = io.StringIO(), io.StringIO()
        status = cli.main(argv, out, err, tempfile.gettempdir(), env=env)
        return status, out.getvalue(), err.getvalue()

    def test_every_git_touching_command_refuses_below_the_floor(self):
        for argv in self.GIT_TOUCHING_COMMANDS:
            with self.subTest(argv=argv):
                status, _out, err = self.run_cli(argv, "git version 2.30.2")
                self.assertEqual(status, exits.UNSUPPORTED)
                self.assertIn(gitq.GIT_TOO_OLD, err)

    def test_the_refusal_names_the_version_and_the_floor(self):
        """A refusal a user cannot act on is a worse refusal."""
        _status, _out, err = self.run_cli(["doctor"], "git version 2.30.2")
        self.assertIn("2.30.2", err)
        self.assertIn("2.32", err)
        self.assertIn("GIT_CONFIG_GLOBAL", err)

    def test_an_unreadable_version_refuses_with_its_own_reason(self):
        status, _out, err = self.run_cli(["doctor"], "git version banana")
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn(gitq.GIT_VERSION_UNKNOWN, err)

    def test_version_still_works_without_git(self):
        """`aiqe --version` reaches no repository, so it answers regardless."""
        from aiqe import __version__

        status, out, err = self.run_cli(["--version"], "git version 2.30.2")
        self.assertEqual(status, exits.OK)
        self.assertEqual(out, "aiqe %s\n" % (__version__,))
        self.assertEqual(err, "")

    def test_a_supported_version_is_not_refused(self):
        """The other direction: the gate must not fire on a modern Git.

        The fake Git refuses every subcommand, so the command fails after the
        gate rather than at it. What is asserted here is only that the failure
        is not the version refusal.
        """
        for argv in (["doctor"], ["receipt"]):
            with self.subTest(argv=argv):
                _status, _out, err = self.run_cli(argv, "git version 2.32.0")
                self.assertNotIn(gitq.GIT_TOO_OLD, err)
                self.assertNotIn(gitq.GIT_VERSION_UNKNOWN, err)


class NegativeControlTests(unittest.TestCase):
    """NC-GIT-ISOLATION-SILENT: the naive check that this defect defeats.

    The naive way to satisfy yourself that configuration isolation works is to
    set the variables and observe that Git ran without complaining. That check
    passes on every Git ever released, including the ones where the variables
    do nothing, which is precisely why the defect survived until a real old-Git
    surface ran the suite.

    The control reproduces when the naive check passes on a Git that AIQE
    refuses.
    """

    def test_the_control_reproduces(self):
        version = "2.30.2"

        # The naive check: the isolation environment is applied, and the
        # process exits 0. Nothing here can tell whether Git read the
        # variables or ignored them.
        isolation_applied = dict(gitq._CONFIG_ISOLATION)
        naive_passes = bool(isolation_applied) and all(
            value for value in isolation_applied.values()
        )

        # AIQE's check: the version decides, because the version is what
        # determines whether those names mean anything.
        supported, reason = gitq.config_isolation_supported(version)

        self.assertTrue(
            naive_passes,
            "the naive reference must pass, or there is no contrast to show",
        )
        self.assertFalse(supported)
        self.assertEqual(reason, gitq.GIT_TOO_OLD)

    def test_nosystem_is_not_a_fallback_for_the_global_scope(self):
        """The belief that made the defect plausible, written down as a test.

        `GIT_CONFIG_NOSYSTEM` is old enough to work everywhere, which is why it
        reads like a safety net. It is not one: it declines the system file and
        has no opinion about `$HOME/.gitconfig`.
        """
        self.assertIn("GIT_CONFIG_NOSYSTEM", gitq._CONFIG_ISOLATION)
        self.assertIn("GIT_CONFIG_GLOBAL", gitq._CONFIG_ISOLATION)
        supported, _reason = gitq.config_isolation_supported("2.30.2")
        self.assertFalse(
            supported,
            "NOSYSTEM being present must not make an old Git look supported",
        )


if __name__ == "__main__":
    unittest.main()
