"""The command surface, and the exit status it produces.

The surface is closed. Everything outside it is an invalid invocation, and an
invalid invocation exits 3 - never 2, which means INCOMPLETE and belongs to
commands that adjudicate completion.

Asking for help is inside the surface, and it succeeds. A tool whose only
answer to `--help` is a usage error on standard error is one every wrapper,
package check and first-time reader has to be told about individually.
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


class HelpTests(unittest.TestCase):
    """`--help`, `-h` and `help`: one text, on stdout, exit 0."""

    SPELLINGS = ("--help", "-h", "help")

    def test_every_spelling_succeeds(self):
        for spelling in self.SPELLINGS:
            status, out, err = run([spelling])
            self.assertEqual(status, exits.OK, spelling)
            self.assertEqual(err, "", spelling)
            self.assertTrue(out.startswith("usage: aiqe"), spelling)

    def test_every_spelling_prints_the_same_canonical_text(self):
        """One text, so no two spellings can document different products."""
        rendered = set()
        for spelling in self.SPELLINGS:
            _status, out, _err = run([spelling])
            rendered.add(out)
        self.assertEqual(len(rendered), 1)

    def test_help_lists_the_whole_frozen_surface(self):
        _status, out, _err = run(["--help"])
        for command in ("--version", "doctor", "init", "task", "check",
                        "commit", "receipt"):
            self.assertIn(command, out)

    def test_help_answers_without_reaching_a_repository(self):
        """Help must work where every other command would refuse.

        It is answered before the Git preflight, so an unsupported Git, a
        missing Git or a directory that is not a repository does not stop the
        one question that has to be answerable everywhere.
        """
        outside = tempfile.mkdtemp(prefix="aiqe-help-test-")
        self.addCleanup(shutil.rmtree, outside, True)
        status, out, err = run(["--help"], cwd=outside, env={"PATH": ""})
        self.assertEqual(status, exits.OK, err)
        self.assertTrue(out.startswith("usage: aiqe"))

    def test_help_takes_no_arguments(self):
        for spelling in self.SPELLINGS:
            status, out, err = run([spelling, "extra"])
            self.assertEqual(status, exits.UNSUPPORTED, spelling)
            self.assertEqual(out, "", spelling)
            self.assertIn("takes no arguments", err)

    def test_an_unknown_command_still_fails(self):
        """Help succeeding must not soften anything else.

        `--halp` is not help, and a tool that answered it as though it were
        would exit 0 on a typo in a script.
        """
        for argv in (["--halp"], ["helpme"], ["-H"], ["frobnicate"]):
            status, out, err = run(argv)
            self.assertEqual(status, exits.UNSUPPORTED, argv)
            self.assertEqual(out, "", argv)
            self.assertNotEqual(err, "")


class InvalidInvocationTests(unittest.TestCase):
    def test_no_command(self):
        status, _out, err = run([])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no command given", err)

    def test_unknown_command(self):
        status, _out, err = run(["frobnicate"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("unknown command", err)

    def test_the_frozen_surface_has_no_reserved_command_left(self):
        """Nothing parses into a silent no-op, because nothing is reserved.

        A command that accepts its arguments and does nothing advertises a
        capability the product has not built. `task` left the reserved list
        when it acquired an implementation, `init`, `check` and `receipt` left
        it when they acquired theirs, and `commit` was the last one out.
        """
        from aiqe.cli import USAGE

        self.assertIn("aiqe commit  -m <message>", USAGE)
        self.assertNotIn("not implemented", USAGE)

        status, out, err = run(["frobnicate"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertEqual(out, "")
        self.assertIn("unknown command", err)

    def test_commit_takes_exactly_one_flag(self):
        """No `--amend`, no `--no-verify`, no `--allow-empty`, no `--push`.

        Each of those is a way to make the command succeed by weakening the
        claim it makes, so none of them parses.
        """
        for argv in (
            ["commit"],
            ["commit", "-m"],
            ["commit", "-m", "a", "-m", "b"],
            ["commit", "-m", "a", "--amend"],
            ["commit", "-m", "a", "--no-verify"],
            ["commit", "-m", "a", "--allow-empty"],
            ["commit", "--amend", "-m", "a"],
            ["commit", "-m", "   "],
            ["commit", "-m", ""],
        ):
            status, out, err = run(argv)
            self.assertEqual(status, exits.UNSUPPORTED, argv)
            self.assertEqual(out, "", argv)
            self.assertIn("usage:", err, argv)

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
