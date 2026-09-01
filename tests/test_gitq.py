"""Unit tests for the Git query layer's parsers and its allowlist guard.

These exercise the parsing surfaces directly, including the byte sequences a
repository can contain but a developer rarely types: a filename with a
newline, a filename that is not valid UTF-8.
"""

import unittest

from . import support  # noqa: F401

from aiqe.gitq import (
    ALLOWED_SUBCOMMANDS,
    GitResult,
    GitRunner,
    parse_status_porcelain_v2,
    parse_version,
)


class VersionParsingTests(unittest.TestCase):
    def test_documented_shape(self):
        self.assertEqual(parse_version(b"git version 2.50.1\n"), "2.50.1")

    def test_vendor_suffix_is_ignored(self):
        self.assertEqual(parse_version(b"git version 2.39.5 (Apple Git-154)\n"), "2.39.5")

    def test_unrecognised_output_is_unknown_not_guessed(self):
        for output in (b"", b"garbage\n", b"git\n", b"not git version x\n"):
            self.assertIsNone(parse_version(output), output)


class StatusParsingTests(unittest.TestCase):
    def counts(self, records):
        return parse_status_porcelain_v2(b"".join(record + b"\0" for record in records))

    def test_empty_output_is_a_clean_worktree(self):
        self.assertEqual(
            parse_status_porcelain_v2(b""),
            {"staged": 0, "unstaged": 0, "untracked": 0, "unmerged": 0},
        )

    def test_staged_unstaged_and_untracked(self):
        counts = self.counts(
            [
                b"1 M. N... 100644 100644 100644 aaaa bbbb staged.py",
                b"1 .M N... 100644 100644 100644 aaaa aaaa unstaged.py",
                b"1 MM N... 100644 100644 100644 aaaa bbbb both.py",
                b"? untracked.py",
            ]
        )
        self.assertEqual(counts["staged"], 2)
        self.assertEqual(counts["unstaged"], 2)
        self.assertEqual(counts["untracked"], 1)

    def test_unmerged_entries_are_counted_separately(self):
        counts = self.counts([b"u UU N... 100644 100644 100644 100644 a b c conflict.py"])
        self.assertEqual(counts["unmerged"], 1)
        self.assertEqual(counts["staged"], 0)

    def test_ignored_entries_are_not_counted(self):
        counts = self.counts([b"! ignored.py"])
        self.assertEqual(counts, {"staged": 0, "unstaged": 0, "untracked": 0, "unmerged": 0})

    def test_rename_record_consumes_its_second_path_field(self):
        """A "2" record is followed by the original path in its own field.

        --no-renames is passed so this should not arise, but a parser that
        misaligns on it would silently miscount everything after it.
        """
        counts = self.counts(
            [
                b"2 R. N... 100644 100644 100644 aaaa bbbb R100 new.py",
                b"old.py",
                b"? untracked.py",
            ]
        )
        self.assertEqual(counts["staged"], 1)
        self.assertEqual(counts["untracked"], 1)

    def test_filename_containing_a_newline_is_handled(self):
        """A newline is a legal byte in a filename.

        This is why the output is NUL-delimited and why the parser never
        splits on newlines.
        """
        counts = self.counts([b"? weird\nname.py", b"? plain.py"])
        self.assertEqual(counts["untracked"], 2)

    def test_filename_that_is_not_valid_utf8_is_handled(self):
        counts = self.counts([b"? \xff\xfe-invalid.py"])
        self.assertEqual(counts["untracked"], 1)

    def test_unrecognised_record_yields_unknown_not_a_wrong_count(self):
        self.assertIsNone(self.counts([b"x nonsense"]))
        self.assertIsNone(self.counts([b"1 TOOLONG N... a b c"]))


class ResultTests(unittest.TestCase):
    def test_nul_fields_drops_only_the_trailing_separator(self):
        result = GitResult((), 0, b"a\0b\0", b"")
        self.assertEqual(result.nul_fields(), [b"a", b"b"])

    def test_nul_fields_on_empty_output(self):
        self.assertEqual(GitResult((), 0, b"", b"").nul_fields(), [])

    def test_lines_preserve_bytes(self):
        result = GitResult((), 0, b"one\ntwo\n", b"")
        self.assertEqual(result.lines(), [b"one", b"two"])


class AllowlistTests(unittest.TestCase):
    def test_allowlist_contains_only_local_read_subcommands(self):
        self.assertEqual(
            ALLOWED_SUBCOMMANDS,
            frozenset(
                {"--version", "rev-parse", "symbolic-ref", "ls-files", "status", "diff-index"}
            ),
        )

    def test_a_subcommand_outside_the_allowlist_raises(self):
        runner = GitRunner(".")
        for subcommand in ("commit", "add", "fetch", "config", "diff-files", "gc"):
            with self.assertRaises(AssertionError, msg=subcommand):
                runner.run(subcommand)

    def test_no_arguments_is_rejected(self):
        with self.assertRaises(ValueError):
            GitRunner(".").run()

    def test_missing_git_binary_is_reported_not_raised(self):
        """A first-contact tool reports a missing Git; it does not traceback."""
        runner = GitRunner(".", git_binary="definitely-not-a-real-git-binary")
        result = runner.run("--version")
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
