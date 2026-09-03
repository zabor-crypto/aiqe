"""Commit-policy preflight: what AIQE refuses, and what it must not touch.

Every refusal here is exit 3, and every one of them has the same shape:

```
commit = NONE
index unchanged
hook / filter / signer executions = 0
```

The last line is the one worth measuring rather than reasoning about. A
refusal that decided its answer by *running* the thing it was about to refuse
would be no refusal at all, so each fixture installs the repository-defined
program as a canary that records the fact that it ran, in a directory outside
the repository, and the tests assert the marker is absent.

The other half of the contract is that a refusal is not noise. A filter driver
that is configured and bound to nothing is not a blocker: refusing there would
make AIQE unusable on any machine that has ever installed Git LFS, and would
teach its users that its refusals mean nothing.
"""

import os
import unittest

from . import support

from aiqe import commitpolicy, exits, gitwrite
from .test_commit import CommitTestCase

builders = support.commit_builders


class PolicyTestCase(CommitTestCase):
    def assert_refused(self, reason):
        index_before = builders.index_paths(self.repo, self.env)
        head_before = self.head()
        status, out, err = self.commit()
        text = out + err
        self.assertEqual(status, exits.UNSUPPORTED, text)
        self.assertIn(reason, text)
        self.assertEqual(self.head(), head_before)
        self.assertEqual(builders.index_paths(self.repo, self.env), index_before)
        self.assertIsNone(self.commit_evidence())
        self.assertEqual(self.case.fired(), ["unit"], "policy code ran")
        return text

    def prepare(self):
        self.start()
        status, out, err = self.check()
        self.assertEqual(status, exits.OK, out + err)


class CommitHookTests(PolicyTestCase):
    def test_each_commit_execution_hook_refuses_and_does_not_run(self):
        for name in commitpolicy.COMMIT_HOOKS:
            with self.subTest(hook=name):
                self.setUp()
                self.build(owned_setup=builders.edit_owned)
                builders.install_hook(self.case, self.repo, name)
                self.prepare()
                self.assert_refused(commitpolicy.COMMIT_HOOK_POLICY_UNSUPPORTED)

    def test_a_hook_reached_through_core_hookspath_refuses(self):
        self.build(owned_setup=builders.edit_owned)
        directory = os.path.join(self.repo, ".aiqe-hooks")
        builders.install_hook(self.case, self.repo, "pre-commit", directory=directory)
        builders.git(self.repo, "config", "core.hooksPath", ".aiqe-hooks",
                     env=self.env)
        self.prepare()
        self.assert_refused(commitpolicy.COMMIT_HOOK_POLICY_UNSUPPORTED)

    def test_a_non_executable_hook_file_is_not_an_active_hook(self):
        """Git will not run it, so neither does the refusal fire."""
        self.build(owned_setup=builders.edit_owned)
        hooks = os.path.join(self.repo, ".git", "hooks")
        if not os.path.isdir(hooks):
            os.makedirs(hooks)
        with open(os.path.join(hooks, "pre-commit"), "w") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(hooks, "pre-commit"), 0o644)
        self.prepare()
        status, _out, _err = self.commit()
        self.assertEqual(status, exits.OK)

    def test_an_ambiguous_hook_object_fails_closed(self):
        """A hook path that is not a regular file is refused rather than read.

        Resolving the link to find out what is on the other side would be
        acting on a path this check has already decided it cannot
        characterise.
        """
        self.build(owned_setup=builders.edit_owned)
        hooks = os.path.join(self.repo, ".git", "hooks")
        if not os.path.isdir(hooks):
            os.makedirs(hooks)
        os.symlink("/nonexistent/hook", os.path.join(hooks, "pre-commit"))
        self.prepare()
        self.assert_refused(commitpolicy.COMMIT_HOOK_POLICY_UNSUPPORTED)


class SigningTests(PolicyTestCase):
    def test_configured_signing_refuses_rather_than_being_disabled(self):
        self.build(owned_setup=builders.edit_owned)
        signer = builders.install_signer(self.case, self.repo)
        builders.git(self.repo, "config", "commit.gpgsign", "true", env=self.env)
        builders.git(self.repo, "config", "gpg.program", signer, env=self.env)
        self.prepare()
        self.assert_refused(commitpolicy.COMMIT_SIGNING_POLICY_UNSUPPORTED)

    def test_signing_policy_through_a_global_include_refuses_the_same(self):
        """Doctor does not follow includes. A commit must, because Git does."""
        self.build(owned_setup=builders.edit_owned)
        signer = builders.install_signer(self.case, self.repo)
        # Fixture construction disables signing in repository scope, which
        # outranks the global file. Without this the fixture would prove
        # nothing.
        builders.git(self.repo, "config", "--unset", "commit.gpgsign",
                     env=self.env)
        included = os.path.join(self.root, "signing.cfg")
        builders.write(
            included,
            "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = %s\n" % (signer,),
        )
        builders.global_config(self.env, ("include", "\tpath = %s" % (included,)))
        self.prepare()
        self.assert_refused(commitpolicy.COMMIT_SIGNING_POLICY_UNSUPPORTED)

    def test_signing_configuration_that_is_off_is_not_a_blocker(self):
        self.build(
            owned_setup=builders.edit_owned,
            extra_git_config=(("commit.gpgsign", "false"),),
        )
        self.prepare()
        status, _out, _err = self.commit()
        self.assertEqual(status, exits.OK)


class CheckinFilterTests(PolicyTestCase):
    def bind(self, attributes="tracked", process=False, scope="local"):
        files = ()
        if attributes == "tracked":
            files = ((b".gitattributes", b"*.py filter=canary\n", 0o644),)
        self.build(committed_files=files)
        driver = builders.install_filter_driver(
            self.case, self.repo, "canary.sh", "filter.clean", process=process
        )
        if attributes == "info":
            builders.write(
                os.path.join(self.repo, ".git", "info", "attributes"),
                "*.py filter=canary\n",
            )
        elif attributes == "attributesfile":
            external = os.path.join(self.root, "attributes")
            builders.write(external, "*.py filter=canary\n")
            builders.global_config(
                self.env, ("core", "\tattributesFile = %s" % (external,))
            )
        key = "filter.canary.process" if process else "filter.canary.clean"
        if scope == "local":
            builders.git(self.repo, "config", key, driver, env=self.env)
        else:
            included = os.path.join(self.root, "filters.cfg")
            builders.write(
                included,
                '[filter "canary"]\n\t%s = %s\n'
                % ("process" if process else "clean", driver),
            )
            builders.global_config(
                self.env, ("include", "\tpath = %s" % (included,))
            )
        builders.edit_owned(self.repo, self.env)
        self.prepare()

    def test_a_tracked_attributes_binding_refuses_before_the_filter_runs(self):
        self.bind()
        self.assert_refused(commitpolicy.CHECKIN_FILTER_UNSUPPORTED)

    def test_a_process_filter_refuses_and_is_never_started(self):
        self.bind(process=True)
        self.assert_refused(commitpolicy.CHECKIN_FILTER_UNSUPPORTED)

    def test_a_driver_defined_through_a_global_include_refuses(self):
        self.bind(scope="global")
        self.assert_refused(commitpolicy.CHECKIN_FILTER_UNSUPPORTED)

    def test_a_binding_from_core_attributesfile_is_resolved(self):
        self.bind(attributes="attributesfile")
        self.assert_refused(commitpolicy.CHECKIN_FILTER_UNSUPPORTED)

    def test_a_binding_from_info_attributes_is_resolved(self):
        self.bind(attributes="info")
        self.assert_refused(commitpolicy.CHECKIN_FILTER_UNSUPPORTED)

    def test_a_configured_driver_bound_to_no_owned_path_is_not_a_blocker(self):
        self.build(
            committed_files=(
                (b".gitattributes", b"*.bin filter=canary\n", 0o644),
            ),
        )
        driver = builders.install_filter_driver(
            self.case, self.repo, "canary.sh", "filter.clean"
        )
        builders.git(self.repo, "config", "filter.canary.clean", driver,
                     env=self.env)
        builders.edit_owned(self.repo, self.env)
        self.prepare()
        status, out, err = self.commit()
        self.assertEqual(status, exits.OK, out + err)
        self.assertEqual(self.case.fired(), ["unit"])


class TopologyTests(PolicyTestCase):
    def test_a_merge_in_progress_is_refused(self):
        self.build()
        builders.git(self.repo, "checkout", "--quiet", "-b", "side", env=self.env)
        builders.put(self.repo, b"tests/side.py", b"SIDE = 1\n")
        builders.commit_all(self.repo, "side", self.env)
        builders.git(self.repo, "checkout", "--quiet", "main", env=self.env)
        builders.put(self.repo, b"tests/main.py", b"MAIN = 1\n")
        builders.commit_all(self.repo, "main", self.env)
        builders.git(self.repo, "merge", "--no-commit", "--no-ff", "side",
                     env=self.env, check=False)
        builders.edit_owned(self.repo, self.env)
        self.prepare()
        self.assert_refused(commitpolicy.MERGE_IN_PROGRESS)

    def test_a_detached_head_is_refused_rather_than_claimed(self):
        self.build(owned_setup=builders.edit_owned)
        builders.git(self.repo, "checkout", "--quiet", "--detach", env=self.env)
        self.prepare()
        self.assert_refused(commitpolicy.DETACHED_HEAD_UNSUPPORTED)

    def test_a_sparse_checkout_is_refused(self):
        self.build(
            owned_setup=builders.edit_owned,
            extra_git_config=(("core.sparseCheckout", "true"),),
        )
        self.prepare()
        self.assert_refused(commitpolicy.SPARSE_CHECKOUT_UNSUPPORTED)


class EffectiveConfigTests(PolicyTestCase):
    def test_an_unresolvable_effective_configuration_refuses(self):
        """A `~/.gitconfig` Git cannot parse is named, not mistaken for absence.

        The break is in the *global* configuration, which is where a user
        actually breaks one. It makes every Git invocation fail, including the
        one that answers "which repository is this", so the naive report would
        be "no Git repository here" - true of nothing and useless to the
        person who has to fix it.

        The configuration is restored before anything is asserted, because
        the test's own Git reads run under the same broken environment.
        """
        self.build(owned_setup=builders.edit_owned)
        self.prepare()
        head_before = self.head()
        index_before = builders.index_paths(self.repo, self.env)

        with open(self.env["GIT_CONFIG_GLOBAL"]) as handle:
            original = handle.read()
        broken = os.path.join(self.root, "broken.cfg")
        builders.write(broken, "[[[not configuration\n")
        builders.global_config(self.env, ("include", "\tpath = %s" % (broken,)))
        try:
            status, out, err = self.commit()
        finally:
            with open(self.env["GIT_CONFIG_GLOBAL"], "w") as handle:
                handle.write(original)

        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn(commitpolicy.EFFECTIVE_CONFIG_UNRESOLVED, out + err)
        self.assertEqual(self.head(), head_before)
        self.assertEqual(builders.index_paths(self.repo, self.env), index_before)
        self.assertIsNone(self.commit_evidence())
        self.assertEqual(self.case.fired(), ["unit"])

    def test_the_resolved_configuration_includes_what_git_includes(self):
        """The reader is Git's own resolution, not a second implementation."""
        self.build()
        included = os.path.join(self.root, "extra.cfg")
        builders.write(included, "[aiqe]\n\tprobe = included-value\n")
        builders.global_config(self.env, ("include", "\tpath = %s" % (included,)))
        runner = gitwrite.CommitGitRunner(self.repo, env=self.env)
        config = commitpolicy.resolve_effective_config(runner)
        self.assertEqual(config.get("aiqe.probe"), "included-value")

    def test_a_subsection_keeps_its_case_and_a_key_does_not(self):
        """Git's own comparison rule, because refusals depend on it.

        `filter.Canary.clean` and `filter.canary.clean` are two different
        drivers. Matching them case-insensitively would make AIQE refuse a
        commit because of a driver bound to nothing, which is the kind of
        false refusal that teaches users to ignore real ones.
        """
        config = commitpolicy.EffectiveConfig(
            [("filter.canary.clean", "run"), ("commit.gpgsign", "true")],
            ["local", "global"],
        )
        self.assertEqual(config.get("filter.canary.clean"), "run")
        self.assertIsNone(config.get("filter.Canary.clean"))
        self.assertFalse(config.present("filter.Canary.clean"))
        self.assertEqual(config.get("commit.gpgSign"), "true")
        self.assertEqual(config.scope_of("commit.gpgSign"), "global")

    def test_the_last_value_wins(self):
        config = commitpolicy.EffectiveConfig(
            [("commit.gpgsign", "true"), ("commit.gpgSign", "false")],
            ["global", "local"],
        )
        self.assertEqual(config.get("commit.gpgsign"), "false")
        self.assertEqual(config.scope_of("commit.gpgsign"), "local")

    def test_a_bare_key_reads_as_true(self):
        self.build()
        with open(os.path.join(self.repo, ".git", "config"), "a") as handle:
            handle.write("[aiqe]\n\tflag\n")
        runner = gitwrite.CommitGitRunner(self.repo, env=self.env)
        config = commitpolicy.resolve_effective_config(runner)
        self.assertTrue(config.present("aiqe.flag"))
        self.assertTrue(commitpolicy.is_true(config.get("aiqe.flag")))


if __name__ == "__main__":
    unittest.main()
