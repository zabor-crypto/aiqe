"""The command surface, and the exit status it produces.

The surface is closed: `--version` and `doctor [--format json]`. Everything
else is an invalid invocation, and an invalid invocation exits 3 - never 2,
which means INCOMPLETE and belongs to commands that adjudicate completion.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import __version__, exits
from aiqe.cli import main


def run(argv, cwd=None, env=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(argv, stdout, stderr, cwd or os.getcwd(), env or dict(os.environ))
    return status, stdout.getvalue(), stderr.getvalue()


class VersionTests(unittest.TestCase):
    def test_version_prints_name_and_version(self):
        status, out, err = run(["--version"])
        self.assertEqual(status, exits.OK)
        self.assertEqual(out, "aiqe %s\n" % __version__)
        self.assertEqual(err, "")

    def test_version_rejects_arguments(self):
        status, _out, err = run(["--version", "extra"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("takes no arguments", err)


class InvalidInvocationTests(unittest.TestCase):
    def test_no_command(self):
        status, _out, err = run([])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no command given", err)

    def test_unknown_command(self):
        status, _out, err = run(["frobnicate"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("unknown command", err)

    def test_reserved_commands_are_not_implemented(self):
        """A frozen future command must not parse into a silent no-op.

        A command that accepts its arguments and does nothing advertises a
        capability the product has not built. `task` left this list when it
        acquired an implementation.
        """
        for command in ("init", "check", "commit", "receipt"):
            status, out, err = run([command])
            self.assertEqual(status, exits.UNSUPPORTED, command)
            self.assertEqual(out, "", command)
            self.assertIn("unknown command", err, command)

    def test_unknown_flag(self):
        for flag in ("--verbose", "--debug", "--fix", "--write", "--network"):
            status, _out, err = run(["doctor", flag])
            self.assertEqual(status, exits.UNSUPPORTED, flag)
            self.assertIn("unknown argument", err, flag)

    def test_unknown_format_value(self):
        status, _out, err = run(["doctor", "--format", "yaml"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("unknown --format value", err)

    def test_format_requires_a_value(self):
        status, _out, err = run(["doctor", "--format"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("requires a value", err)

    def test_format_may_not_repeat(self):
        status, _out, err = run(["doctor", "--format", "json", "--format", "json"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("more than once", err)


class DoctorOutputTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-cli-")
        self.addCleanup(shutil.rmtree, self.root, True)
        case = support.harness.Case("normal_repository", self.root)
        self.env = case.env()
        self.target = support.builders.build_normal_repository(case, self.env)

    def test_human_output_is_produced(self):
        status, out, err = run(["doctor"], cwd=self.target, env=self.env)
        self.assertEqual(status, exits.OK)
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("AIQE DOCTOR\n"))
        self.assertIn("Repository", out)

    def test_json_output_parses_and_is_stable(self):
        status, first, _err = run(["doctor", "--format", "json"], cwd=self.target, env=self.env)
        self.assertEqual(status, exits.OK)
        document = json.loads(first)
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["aiqe_version"], __version__)
        self.assertEqual(document["command"], "doctor")
        self.assertEqual(document["exit_code"], 0)

        _status, second, _err = run(["doctor", "--format", "json"], cwd=self.target, env=self.env)
        self.assertEqual(first, second, "repeated runs must render identical bytes")

    def test_equals_form_of_format_flag(self):
        status, out, _err = run(["doctor", "--format=json"], cwd=self.target, env=self.env)
        self.assertEqual(status, exits.OK)
        json.loads(out)

    def test_output_discloses_no_local_paths(self):
        """A Doctor result is pasted into issues and screenshots.

        It carries counts, booleans and categories. It must not carry the
        worktree path, the home directory or the username.
        """
        _status, human, _err = run(["doctor"], cwd=self.target, env=self.env)
        _status, machine, _err = run(["doctor", "--format", "json"], cwd=self.target, env=self.env)
        for rendered in (human, machine):
            self.assertNotIn(self.root, rendered)
            self.assertNotIn(self.target, rendered)
            self.assertNotIn(self.env["HOME"], rendered)


if __name__ == "__main__":
    unittest.main()
