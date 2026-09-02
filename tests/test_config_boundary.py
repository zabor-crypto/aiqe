"""The external-configuration execution boundary.

Repository content selects an executable; configuration supplies it. Those two
halves can live in different places, and reading only the repository's own
configuration and concluding "no filter here" is wrong. It was wrong: before
this boundary existed, three of the four fixtures below executed their canary.

Two defences, and each case below exercises exactly one of them:

    Configuration isolation, for a definition that lives outside the
    repository. Git cannot execute what is not in scope.

    Static refusal, for a definition already inside repository scope, where
    isolation cannot reach. There Doctor declines to compare worktree content
    and reports the unstaged count as unknown.

`unstaged = UNKNOWN` is an acceptable outcome throughout, and in several of
these it is the *correct* one. A precise number obtained by running a
repository's own command is not a better answer; it is the wrong answer to a
different question.
"""

import unittest

from . import support

#: Fixture identifier -> which defence is expected to carry it, and whether
#: the working state can still be determined afterwards.
BOUNDARY_CASES = {
    "global_filter_canary": ("static refusal", False),
    "global_fsmonitor_canary": ("per-invocation override", True),
    "local_include_filter_canary": ("static refusal", False),
    "global_attributes_filter_canary": ("configuration isolation", True),
    "external_attributes_local_filter_canary": ("static refusal", False),
    "submodule_filter_canary": ("no submodule descent", True),
    "env_command_config_filter_canary": ("command-scope sanitisation", True),
}


def _make_test(case_id, defence, determined):
    def test(self):
        observed = support.harness.run_case(case_id)

        self.assertEqual(
            observed["repository_defined_executions"],
            0,
            "%s: a repository-selected command executed (%s). Defence expected "
            "to carry this case: %s"
            % (case_id, observed["fired_canaries"], defence),
        )
        self.assertEqual(observed["fired_canaries"], [])
        self.assertEqual(observed["repository_mutations"], 0)
        self.assertEqual(observed["local_state_writes"], 0)

        self.assertEqual(
            observed["working_state"]["determined"],
            determined,
            "%s: expected determined=%s under defence %r"
            % (case_id, determined, defence),
        )
        if not determined:
            self.assertIsNone(observed["working_state"]["unstaged"])
            self.assertIn(
                "WORKING_STATE_UNSTAGED_UNKNOWN",
                observed["findings"],
                "a refused comparison must say so, not silently omit the count",
            )

    test.__name__ = "test_" + case_id
    test.__doc__ = "%s, carried by %s." % (case_id, defence)
    return test


class ExternalConfigBoundaryTests(unittest.TestCase):
    pass


for _case_id, (_defence, _determined) in sorted(BOUNDARY_CASES.items()):
    setattr(
        ExternalConfigBoundaryTests,
        "test_" + _case_id,
        _make_test(_case_id, _defence, _determined),
    )
del _case_id, _defence, _determined


class IsolationMechanismTests(unittest.TestCase):
    """Assert the mechanism, not only its effect."""

    def test_index_and_worktree_subcommands_are_isolated(self):
        from aiqe.gitq import CONFIG_ISOLATED_SUBCOMMANDS

        self.assertEqual(
            CONFIG_ISOLATED_SUBCOMMANDS,
            frozenset(
                {"status", "diff-index", "ls-files", "ls-tree", "cat-file"}
            ),
        )

    def test_discovery_subcommands_are_not_isolated(self):
        """Discovery must answer the same question the user's Git answers.

        Suppressing the user's configuration to decide *which repository this
        is* would be its own defect, and none of these can execute anything.
        """
        from aiqe.gitq import CONFIG_ISOLATED_SUBCOMMANDS

        for subcommand in ("rev-parse", "symbolic-ref", "--version"):
            self.assertNotIn(subcommand, CONFIG_ISOLATED_SUBCOMMANDS)

    def test_isolation_is_applied_at_run_time(self):
        observed = support.harness.run_case("global_attributes_filter_canary")
        pairs = list(
            zip(
                observed["git_invocations"],
                observed["git_invocations_config_isolated"],
            )
        )
        self.assertTrue(pairs)
        status_invocations = [
            (argv, isolated) for argv, isolated in pairs if "status" in argv
        ]
        self.assertTrue(status_invocations, "the case should have run status")
        for argv, isolated in status_invocations:
            self.assertTrue(isolated, argv)

    def test_status_does_not_descend_into_submodules(self):
        observed = support.harness.run_case("submodule_filter_canary")
        status_invocations = [
            argv for argv in observed["git_invocations"] if "status" in argv
        ]
        self.assertTrue(status_invocations)
        for argv in status_invocations:
            self.assertIn("--ignore-submodules=dirty", argv)

    def test_submodule_exclusion_is_disclosed(self):
        """A count that omits something must say what it omits."""
        observed = support.harness.run_case("submodule_filter_canary")
        self.assertTrue(observed["working_state"]["submodule_worktrees_excluded"])
        self.assertIn("submodule worktrees not counted", observed["human_output"])


class CommandScopeSanitisationTests(unittest.TestCase):
    """Git reads configuration from the environment, and it outranks files.

    Silencing GIT_CONFIG_SYSTEM and GIT_CONFIG_GLOBAL says nothing about
    GIT_CONFIG_COUNT / GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n> or
    GIT_CONFIG_PARAMETERS, which is why the isolated invocations start from an
    environment with those removed.
    """

    def strip(self, env):
        from aiqe.gitq import strip_command_scope_config

        return strip_command_scope_config(env)

    def test_command_scope_variables_are_removed(self):
        stripped = self.strip(
            {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "filter.x.clean",
                "GIT_CONFIG_VALUE_0": "/tmp/evil",
                "GIT_CONFIG_KEY_1": "core.fsmonitor",
                "GIT_CONFIG_VALUE_1": "/tmp/evil",
                "GIT_CONFIG_PARAMETERS": "'filter.x.clean'='/tmp/evil'",
            }
        )
        self.assertEqual(stripped, {})

    def test_unrelated_environment_is_left_alone(self):
        """Bounded to command-scope configuration, not a Git denylist."""
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/someone",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "someone",
            "GIT_DIR": "/somewhere/.git",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.assertEqual(self.strip(env), env)

    def test_isolated_invocations_do_not_inherit_command_scope_config(self):
        import os

        from aiqe.gitq import GitRunner

        runner = GitRunner(
            os.getcwd(),
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "filter.x.clean",
                "GIT_CONFIG_VALUE_0": "/tmp/evil",
                "GIT_CONFIG_PARAMETERS": "'filter.x.clean'='/tmp/evil'",
            },
        )
        isolated = runner._env(True)
        for name in (
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_CONFIG_PARAMETERS",
        ):
            self.assertNotIn(name, isolated, name)

    def test_doctor_c_settings_are_not_environment_and_still_apply(self):
        """The safety settings travel on the command line, not the environment."""
        observed = support.harness.run_case("env_command_config_filter_canary")
        status = [argv for argv in observed["git_invocations"] if "status" in argv]
        self.assertTrue(status)
        for argv in status:
            self.assertIn("core.fsmonitor=false", argv)
            self.assertIn("--no-optional-locks", argv)


class WorkingStateScopeTests(unittest.TestCase):
    """A number whose scope is not stated invites being read as another one."""

    def test_scope_is_reported_when_working_state_was_inspected(self):
        observed = support.harness.run_case("normal_repository")
        self.assertEqual(
            observed["json_output"]["working_state_scope"], "repository_safe_view"
        )

    def test_scope_appears_in_human_output(self):
        observed = support.harness.run_case("normal_repository")
        self.assertIn("repository-safe view", observed["human_output"])

    def test_scope_is_not_applicable_without_a_worktree(self):
        for case_id in ("non_repository", "bare_repository"):
            observed = support.harness.run_case(case_id)
            self.assertEqual(
                observed["json_output"]["working_state_scope"],
                "not_applicable",
                case_id,
            )
            self.assertNotIn("repository-safe view", observed["human_output"], case_id)

    def test_scope_is_reported_even_when_the_comparison_was_refused(self):
        """An unknown count is still a count taken in a particular scope."""
        observed = support.harness.run_case("checkin_filter_configured")
        self.assertEqual(
            observed["json_output"]["working_state_scope"], "repository_safe_view"
        )
        self.assertFalse(observed["working_state"]["determined"])


class AttributeBindingTests(unittest.TestCase):
    """The static half: reading attributes files is reading data, not running it."""

    def parse(self, text):
        from aiqe.doctor import _attribute_text_binds_filter

        return _attribute_text_binds_filter(text)

    def test_filter_assignment_binds(self):
        self.assertTrue(self.parse("*.dat filter=lfs\n"))
        self.assertTrue(self.parse("path/to/file.bin\tfilter=custom -text\n"))

    def test_unsetting_a_filter_does_not_bind(self):
        self.assertFalse(self.parse("*.dat -filter\n"))
        self.assertFalse(self.parse("*.dat !filter\n"))

    def test_unrelated_attributes_do_not_bind(self):
        self.assertFalse(self.parse("*.py text\n*.png binary\n"))
        self.assertFalse(self.parse("*.md diff=markdown\n"))

    def test_comments_and_blank_lines_are_ignored(self):
        self.assertFalse(self.parse("# *.dat filter=lfs\n\n"))


if __name__ == "__main__":
    unittest.main()
