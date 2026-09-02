"""`aiqe init`: one repository path, after being shown and asked.

Most of this module is about what init does not do. The first command a person
runs is the worst possible moment to demonstrate that a tool writes into
places they did not look.
"""

import io
import os
import shutil
import tempfile
import unittest

from . import support

from aiqe import config, exits, init, taskstate
from aiqe.cli import main
from aiqe.textsafe import is_safe

builders = support.check_builders


class InitTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-init-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("init", self.root, ("repo",))
        self.env = self.case.env()
        self.repo = builders.build_init_target(self.case, self.env)

    def run_cli(self, argv, prompt=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env, prompt=prompt)
        return status, stdout.getvalue(), stderr.getvalue()

    def config_path(self):
        return os.path.join(self.repo, config.CONFIG_FILENAME)

    def snapshot(self):
        return support.measurement.snapshot(self.root, self.case.canaries)


class PreviewTests(InitTestCase):
    def test_print_renders_the_complete_proposed_file(self):
        status, out, _err = self.run_cli(["init", "--print"])
        self.assertEqual(status, exits.OK)
        self.assertIn("schema = 1", out)
        self.assertIn("[[surface]]", out)
        self.assertIn("[[validator]]", out)
        self.assertIn("COVERAGE_GAP", out)

    def test_print_writes_absolutely_nothing(self):
        """No file, no state directory, no salt.

        A preview that creates machine-local state is not a preview, and this
        is the first command a person runs on a machine AIQE has never
        touched.
        """
        support.measurement.wait_until_quiescent(self.root, self.case.canaries)
        before = self.snapshot()
        status, _out, _err = self.run_cli(["init", "--print"])
        after = self.snapshot()

        self.assertEqual(status, exits.OK)
        self.assertEqual(support.measurement.compare(before, after), [])
        self.assertFalse(os.path.exists(self.config_path()))
        self.assertFalse(os.path.exists(taskstate.salt_path(self.env)))

    def test_print_still_renders_when_a_configuration_exists(self):
        self.run_cli(["init", "--yes"])
        status, out, _err = self.run_cli(["init", "--print"])
        self.assertEqual(status, exits.OK)
        self.assertIn("already exists", out)
        self.assertIn("schema = 1", out)

    def test_print_and_yes_contradict_each_other(self):
        status, _out, err = self.run_cli(["init", "--print", "--yes"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("contradict", err)
        self.assertFalse(os.path.exists(self.config_path()))


class ConfirmationTests(InitTestCase):
    def test_a_non_interactive_init_refuses_rather_than_assuming_yes(self):
        status, _out, err = self.run_cli(["init"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("confirmation", err)
        self.assertFalse(os.path.exists(self.config_path()))

    def test_the_prompt_shows_the_complete_file_before_asking(self):
        shown = []
        self.run_cli(["init"], prompt=lambda text: shown.append(text) or False)
        self.assertEqual(len(shown), 1)
        self.assertIn("schema = 1", shown[0])
        self.assertIn("[[validator]]", shown[0])
        self.assertIn("the only thing `aiqe init` writes", shown[0])

    def test_declining_writes_nothing_and_is_not_an_error(self):
        status, out, _err = self.run_cli(["init"], prompt=lambda _text: False)
        self.assertEqual(status, exits.OK)
        self.assertIn("Nothing was written", out)
        self.assertFalse(os.path.exists(self.config_path()))

    def test_accepting_writes_the_file(self):
        status, out, _err = self.run_cli(["init"], prompt=lambda _text: True)
        self.assertEqual(status, exits.OK)
        self.assertIn("Wrote", out)
        self.assertTrue(os.path.isfile(self.config_path()))

    def test_yes_writes_without_asking(self):
        def prompt(_text):
            raise AssertionError("--yes must not prompt")

        status, _out, _err = self.run_cli(["init", "--yes"], prompt=prompt)
        self.assertEqual(status, exits.OK)
        self.assertTrue(os.path.isfile(self.config_path()))

    def test_yes_still_renders_the_proposal(self):
        _status, out, _err = self.run_cli(["init", "--yes"])
        self.assertIn("aiqe.toml", out)


class WriteConfinementTests(InitTestCase):
    def test_init_writes_exactly_one_repository_path(self):
        support.measurement.wait_until_quiescent(self.root, self.case.canaries)
        before = self.snapshot()
        self.run_cli(["init", "--yes"])
        after = self.snapshot()

        changes = support.measurement.compare(before, after)
        self.assertEqual(changes, [os.path.join("added: repo", "aiqe.toml")])

    def test_init_touches_no_git_metadata_and_no_ignore_file(self):
        self.run_cli(["init", "--yes"])
        for name in (".gitignore", ".git/hooks/pre-commit", ".git/config.aiqe"):
            self.assertFalse(
                os.path.exists(os.path.join(self.repo, name)), name
            )

    def test_init_creates_no_machine_local_state(self):
        """`init` has no local state to write, so it writes none."""
        self.run_cli(["init", "--yes"])
        self.assertFalse(os.path.exists(taskstate.salt_path(self.env)))


class RefusalTests(InitTestCase):
    def test_an_existing_configuration_is_never_overwritten(self):
        with open(self.config_path(), "w") as handle:
            handle.write("schema = 1\n# hand written\n")
        status, _out, err = self.run_cli(["init", "--yes"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("already exists", err)
        with open(self.config_path()) as handle:
            self.assertIn("hand written", handle.read())

    def test_a_symlinked_configuration_is_not_written_through(self):
        target = os.path.join(self.root, "elsewhere.toml")
        with open(target, "w") as handle:
            handle.write("original\n")
        os.symlink(target, self.config_path())

        status, _out, err = self.run_cli(["init", "--yes"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("already exists", err)
        with open(target) as handle:
            self.assertEqual(handle.read(), "original\n")

    def test_init_needs_a_repository(self):
        outside = tempfile.mkdtemp(prefix="aiqe-init-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(["init", "--yes"], stdout, stderr, outside, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)

    def test_unknown_flags_are_refused(self):
        for flag in ("--force", "--quant", "--discover"):
            status, _out, err = self.run_cli(["init", flag])
            self.assertEqual(status, exits.UNSUPPORTED, flag)
            self.assertIn("unknown argument", err)


class ScaffoldTests(InitTestCase):
    def uncommented(self):
        with open(self.config_path()) as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def test_the_scaffold_declares_nothing_but_the_schema(self):
        """Nothing is guessed.

        A `src/strategy/` matched against a list of conventions and declared
        quant would be a classification rule nobody wrote and everybody
        trusts, and a `quant = false` inferred from an absence of evidence is
        the false green this product exists to refuse.
        """
        self.run_cli(["init", "--yes"])
        self.assertEqual(self.uncommented(), ["schema = 1"])

    def test_the_scaffold_parses_under_the_product_s_own_reader(self):
        self.run_cli(["init", "--yes"])
        parsed = config.load(os.fsencode(self.repo))
        self.assertEqual(parsed.schema, config.SCHEMA_VERSION)
        self.assertEqual(parsed.surfaces, ())
        self.assertEqual(parsed.validators, ())

    def test_the_scaffold_names_every_launch_contract(self):
        from aiqe import contracts

        text = init.proposal()
        for contract in contracts.LAUNCH_CONTRACTS:
            self.assertIn(contract, text)

    def test_the_scaffold_says_what_an_undeclared_surface_means(self):
        text = init.proposal()
        self.assertIn("UNCLASSIFIED", text)
        self.assertIn("classification gap", text)
        self.assertIn("COVERAGE_GAP", text)

    def test_the_scaffold_does_not_promise_a_sandbox(self):
        text = init.proposal()
        self.assertIn("consent", text)
        self.assertIn("no sandbox, filesystem or network claim", text)

    def test_the_file_is_created_with_ordinary_permissions(self):
        import stat

        self.run_cli(["init", "--yes"])
        mode = stat.S_IMODE(os.stat(self.config_path()).st_mode)
        self.assertEqual(mode & 0o022, 0)

    def test_output_is_terminal_safe(self):
        for arguments in (["init", "--print"], ["init", "--yes"], ["init"]):
            _status, out, err = self.run_cli(arguments)
            for text in (out, err):
                self.assertTrue(all(is_safe(line) for line in text.splitlines()))


if __name__ == "__main__":
    unittest.main()
