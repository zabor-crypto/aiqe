"""The AIQE surface pattern grammar.

The grammar is small on purpose, so these tests are mostly about what it
refuses. A classification rule that silently means something other than what
its author wrote is the failure mode: it produces a check that passes, about
paths nobody meant to declare.
"""

import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import patterns
from aiqe.patterns import PatternError, compile_pattern


def matches(pattern, path):
    return compile_pattern(pattern).matches(path)


class LiteralTests(unittest.TestCase):
    def test_a_literal_pattern_matches_itself_and_nothing_else(self):
        self.assertTrue(matches("aiqe.toml", b"aiqe.toml"))
        self.assertFalse(matches("aiqe.toml", b"aiqe.tomlx"))
        self.assertFalse(matches("aiqe.toml", b"x/aiqe.toml"))

    def test_a_dot_is_not_a_wildcard(self):
        """The grammar is glob, not regular expression."""
        self.assertFalse(matches("a.c", b"abc"))
        self.assertTrue(matches("a.c", b"a.c"))


class WildcardTests(unittest.TestCase):
    def test_star_stays_within_one_component(self):
        self.assertTrue(matches("src/*.py", b"src/alpha.py"))
        self.assertFalse(matches("src/*.py", b"src/nested/alpha.py"))

    def test_star_matches_the_empty_string(self):
        self.assertTrue(matches("src/*alpha.py", b"src/alpha.py"))

    def test_question_mark_is_exactly_one_byte(self):
        self.assertTrue(matches("t?sts/**", b"tests/a"))
        self.assertFalse(matches("t?sts/**", b"tsts/a"))
        self.assertFalse(matches("t??sts/**", b"tests/a"))

    def test_byte_class(self):
        self.assertTrue(matches("[ab]lpha.py", b"alpha.py"))
        self.assertFalse(matches("[cd]lpha.py", b"alpha.py"))

    def test_negated_byte_class(self):
        self.assertFalse(matches("[!ab]lpha.py", b"alpha.py"))
        self.assertTrue(matches("[!cd]lpha.py", b"alpha.py"))

    def test_byte_class_range(self):
        self.assertTrue(matches("v[0-9].py", b"v7.py"))
        self.assertFalse(matches("v[0-9].py", b"vx.py"))

    def test_closing_bracket_first_in_a_class_is_literal(self):
        self.assertTrue(matches("a[]]b", b"a]b"))


class GlobstarTests(unittest.TestCase):
    def test_globstar_matches_zero_components(self):
        """`src/**` covers `src` itself, not only things under it."""
        self.assertTrue(matches("src/**", b"src"))

    def test_globstar_matches_many_components(self):
        self.assertTrue(matches("src/**", b"src/a"))
        self.assertTrue(matches("src/**", b"src/a/b/c.py"))

    def test_globstar_does_not_match_a_sibling_prefix(self):
        self.assertFalse(matches("src/**", b"srcx"))
        self.assertFalse(matches("src/**", b"srcx/a.py"))

    def test_globstar_in_the_middle(self):
        self.assertTrue(matches("src/**/alpha.py", b"src/alpha.py"))
        self.assertTrue(matches("src/**/alpha.py", b"src/a/b/alpha.py"))
        self.assertFalse(matches("src/**/alpha.py", b"src/a/b/beta.py"))

    def test_leading_globstar(self):
        self.assertTrue(matches("**/alpha.py", b"alpha.py"))
        self.assertTrue(matches("**/alpha.py", b"a/b/alpha.py"))

    def test_several_globstars_terminate(self):
        """The memo is what makes this finish, not luck.

        A naive recursive matcher on a pattern with several `**` components
        and a long path is exponential. This is the shape that would find it.
        """
        pattern = "/".join(["**"] * 8) + "/alpha.py"
        path = b"/".join([b"a"] * 24) + b"/alpha.py"
        self.assertTrue(matches(pattern, path))
        self.assertFalse(matches(pattern, path + b"x"))


class ByteSafetyTests(unittest.TestCase):
    def test_matching_is_on_bytes_not_text(self):
        compiled = compile_pattern("src/*.dat")
        self.assertTrue(compiled.matches(b"src/\xe9\xff.dat"))

    def test_a_path_must_be_bytes(self):
        with self.assertRaises(TypeError):
            compile_pattern("src/**").matches("src/alpha.py")

    def test_no_case_folding(self):
        """Two spellings that differ in case are two different paths."""
        self.assertFalse(matches("src/Alpha.py", b"src/alpha.py"))

    def test_no_unicode_normalisation(self):
        """Two byte sequences that render alike are still two paths."""
        composed = "café.py"
        decomposed = "café.py"
        self.assertFalse(
            matches(composed, decomposed.encode("utf-8")),
            "normalising here would make two distinct files look like one",
        )


class RefusalTests(unittest.TestCase):
    def refusal(self, pattern):
        with self.assertRaises(PatternError, msg=pattern) as caught:
            compile_pattern(pattern)
        return caught.exception.code

    def test_empty_pattern(self):
        self.assertEqual(self.refusal(""), patterns.PATTERN_EMPTY)

    def test_absolute_pattern(self):
        self.assertEqual(self.refusal("/src/**"), patterns.PATTERN_ABSOLUTE)

    def test_empty_component_and_trailing_separator(self):
        for pattern in ("src//alpha.py", "src/"):
            self.assertEqual(
                self.refusal(pattern), patterns.PATTERN_COMPONENT_EMPTY, pattern
            )

    def test_relative_components(self):
        for pattern in ("./src/**", "src/../**", ".."):
            self.assertEqual(
                self.refusal(pattern), patterns.PATTERN_COMPONENT_RELATIVE, pattern
            )

    def test_globstar_must_be_a_whole_component(self):
        """`a**b` is refused rather than silently demoted to `a*b`.

        An author who wrote `src**` meant recursion. Treating it as one
        component's worth of matching would leave a quant surface quietly
        smaller than its declaration says.
        """
        for pattern in ("src**", "**src", "a**b"):
            self.assertEqual(
                self.refusal(pattern),
                patterns.PATTERN_GLOBSTAR_NOT_A_COMPONENT,
                pattern,
            )

    def test_unterminated_byte_class(self):
        self.assertEqual(self.refusal("a[bc"), patterns.PATTERN_CLASS_UNTERMINATED)

    def test_nul_byte(self):
        self.assertEqual(self.refusal("a\0b"), patterns.PATTERN_NUL_BYTE)


class GitPathspecDivergenceTests(unittest.TestCase):
    """These are AIQE patterns, and they are never handed to Git."""

    def test_pathspec_magic_is_literal_text_here(self):
        self.assertTrue(matches(":(top)alpha.py", b":(top)alpha.py"))
        self.assertFalse(matches(":(top)alpha.py", b"alpha.py"))

    def test_a_leading_exclamation_is_not_an_exclusion(self):
        """There is no negation at pattern level; overlap is resolved by the
        union rule, not by an exclude that could quietly remove an obligation.
        """
        self.assertTrue(matches("!alpha.py", b"!alpha.py"))


if __name__ == "__main__":
    unittest.main()
