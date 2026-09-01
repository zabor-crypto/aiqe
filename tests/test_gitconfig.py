"""Unit tests for the static Git configuration reader.

The most important assertion in this file is the one about includes: the
parser must report an include directive's *presence* and must never surface a
value from the file it points at. Following that chain is what turns a bounded
first-contact inspection into an unbounded one.
"""

import os
import shutil
import tempfile
import unittest

from . import support  # noqa: F401

from aiqe import gitconfig


class ParsingTests(unittest.TestCase):
    def parse(self, text):
        return gitconfig.parse_text(text, path="fixture")

    def test_simple_section(self):
        parsed = self.parse("[core]\n\thooksPath = githooks\n")
        self.assertEqual(parsed.get("core", "hookspath"), "githooks")

    def test_key_lookup_is_case_insensitive(self):
        parsed = self.parse("[CORE]\n\tHOOKSPATH = x\n")
        self.assertEqual(parsed.get("core", "hookspath"), "x")

    def test_bare_key_is_true(self):
        parsed = self.parse("[commit]\n\tgpgsign\n")
        self.assertIsNone(parsed.get("commit", "gpgsign"))
        self.assertTrue(gitconfig.is_true(parsed.get("commit", "gpgsign")))

    def test_boolean_readings(self):
        for value in ("true", "TRUE", "yes", "on", "1", None):
            self.assertTrue(gitconfig.is_true(value), value)
        for value in ("false", "no", "off", "0", "", "maybe"):
            self.assertFalse(gitconfig.is_true(value), value)

    def test_comments_are_stripped(self):
        parsed = self.parse("[core]\n# comment\n; other\n\thooksPath = a # trailing\n")
        self.assertEqual(parsed.get("core", "hookspath"), "a")

    def test_quoted_value_keeps_its_comment_character(self):
        parsed = self.parse('[core]\n\thooksPath = "a#b"\n')
        self.assertEqual(parsed.get("core", "hookspath"), "a#b")

    def test_subsections(self):
        parsed = self.parse(
            '[filter "lfs"]\n\tclean = git-lfs clean\n[filter "other"]\n\tsmudge = x\n'
        )
        self.assertEqual(parsed.subsection_keys("filter", "clean"), ["lfs"])
        self.assertEqual(parsed.subsection_keys("filter", "smudge"), ["other"])

    def test_legacy_dotted_subsection(self):
        parsed = self.parse("[filter.legacy]\n\tclean = x\n")
        self.assertEqual(parsed.subsection_keys("filter", "clean"), ["legacy"])

    def test_last_value_wins_within_a_file(self):
        parsed = self.parse("[core]\n\thooksPath = a\n\thooksPath = b\n")
        self.assertEqual(parsed.get("core", "hookspath"), "b")

    def test_line_continuation(self):
        parsed = self.parse("[alias]\n\tst = !echo one \\\nand two\n")
        self.assertEqual(parsed.get("alias", "st"), "!echo one and two")

    def test_key_outside_a_section_is_an_error(self):
        with self.assertRaises(gitconfig.ConfigError):
            self.parse("hooksPath = x\n")

    def test_unterminated_section_header_is_an_error(self):
        with self.assertRaises(gitconfig.ConfigError):
            self.parse("[core\n")


class IncludeBoundaryTests(unittest.TestCase):
    """The boundary that keeps first-contact inspection bounded."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-config-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def test_include_presence_is_visible(self):
        parsed = gitconfig.parse_text("[include]\n\tpath = other.cfg\n")
        self.assertTrue(parsed.has_section("include"))

    def test_include_if_presence_is_visible(self):
        parsed = gitconfig.parse_text('[includeIf "gitdir:/x/"]\n\tpath = other.cfg\n')
        self.assertTrue(parsed.has_section("includeif"))

    def test_included_values_are_never_surfaced(self):
        self.write("included.cfg", "[core]\n\thooksPath = LEAKED\n")
        path = self.write("main.cfg", "[include]\n\tpath = included.cfg\n")
        parsed = gitconfig.read_file(path)
        self.assertTrue(parsed.has_section("include"))
        self.assertIsNone(
            parsed.get("core", "hookspath"),
            "the include chain must not be followed on first contact",
        )


class ReadFileTests(unittest.TestCase):
    def test_absent_file_is_none_not_an_error(self):
        self.assertIsNone(gitconfig.read_file("/nonexistent/aiqe/config"))

    def test_directory_in_place_of_a_file_is_an_error(self):
        root = tempfile.mkdtemp(prefix="aiqe-config-")
        self.addCleanup(shutil.rmtree, root, True)
        with self.assertRaises(gitconfig.ConfigError):
            gitconfig.read_file(root)


if __name__ == "__main__":
    unittest.main()
