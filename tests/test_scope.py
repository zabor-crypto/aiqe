"""Owned-scope path semantics.

The rules here are the product. A task that owns slightly more than it said it
owned is the failure this whole layer exists to prevent, so the boundary cases
are tested one by one rather than by example.
"""

import os
import shutil
import tempfile
import unittest

from . import support  # noqa: F401

from aiqe import scope


class MembershipTests(unittest.TestCase):
    """Component-prefix, not string-prefix. The distinction is the point."""

    def test_a_root_owns_itself(self):
        self.assertTrue(scope.owns(b"foo", b"foo"))

    def test_a_root_owns_what_is_under_it(self):
        self.assertTrue(scope.owns(b"foo", b"foo/bar"))
        self.assertTrue(scope.owns(b"foo", b"foo/bar/baz"))

    def test_a_root_does_not_own_a_name_it_merely_prefixes(self):
        for other in (b"foobar", b"foo-other", b"foo.py", b"foox/bar"):
            self.assertFalse(scope.owns(b"foo", other), other)

    def test_a_file_scope_owns_only_itself(self):
        self.assertTrue(scope.owns(b"src/a.py", b"src/a.py"))
        self.assertFalse(scope.owns(b"src/a.py", b"src/a.pyc"))
        self.assertFalse(scope.owns(b"src/a.py", b"src"))

    def test_owned_by_any(self):
        roots = [b"src", b"docs/guide.md"]
        self.assertTrue(scope.owned_by_any(roots, b"src/deep/file.py"))
        self.assertTrue(scope.owned_by_any(roots, b"docs/guide.md"))
        self.assertFalse(scope.owned_by_any(roots, b"docs/other.md"))
        self.assertFalse(scope.owned_by_any(roots, b"srcfoo"))


class CanonicalisationTests(unittest.TestCase):
    def canonical(self, raw, cwd=()):
        return scope.canonicalise(raw, list(cwd))

    def test_simple_file(self):
        self.assertEqual(self.canonical(b"src/strategy.py"), b"src/strategy.py")

    def test_directory(self):
        self.assertEqual(self.canonical(b"src"), b"src")

    def test_trailing_and_repeated_separators_collapse(self):
        for raw in (b"src/", b"src//", b"./src", b"src/."):
            self.assertEqual(self.canonical(raw), b"src", raw)

    def test_relative_to_the_invocation_directory(self):
        self.assertEqual(self.canonical(b"a.py", (b"tests",)), b"tests/a.py")

    def test_leading_parent_walks_back_through_the_invocation_directory(self):
        self.assertEqual(self.canonical(b"../src/a.py", (b"tests",)), b"src/a.py")
        self.assertEqual(
            self.canonical(b"../../src/a.py", (b"tests", b"unit")), b"src/a.py"
        )

    def test_no_unicode_normalisation_and_no_case_folding(self):
        """Two different filenames must not become one.

        The byte sequences are spelled out rather than written as source text,
        so that an editor normalising this file cannot quietly turn the test
        into a tautology. Both spell the same word with an accent: the first
        with a precomposed code point, the second with a base letter plus a
        combining acute. A filesystem can hold both at once, and they are
        different files.
        """
        composed = b"caf\xc3\xa9.py"
        decomposed = b"cafe\xcc\x81.py"
        self.assertNotEqual(composed, decomposed)
        self.assertNotEqual(self.canonical(composed), self.canonical(decomposed))
        self.assertNotEqual(self.canonical(b"README"), self.canonical(b"readme"))

    def test_declaration_does_not_touch_the_filesystem(self):
        """A path that does not exist yet is the normal case."""
        self.assertEqual(
            self.canonical(b"src/does/not/exist/yet.py"), b"src/does/not/exist/yet.py"
        )


class LiteralPathTests(unittest.TestCase):
    """Every one of these is a filename. None of them is a pattern."""

    def canonical(self, raw):
        return scope.canonicalise(raw, [])

    def test_glob_metacharacters_are_literal(self):
        for raw in (b"*", b"?", b"[abc]", b"src/*.py", b"a{b,c}"):
            self.assertEqual(self.canonical(raw), raw.rstrip(b"/"), raw)

    def test_pathspec_magic_is_literal(self):
        for raw in (b":(top)", b":(glob)vendor", b":!excluded", b":/anchored"):
            self.assertEqual(self.canonical(raw), raw, raw)

    def test_arguments_that_look_like_flags_are_literal(self):
        for raw in (b"--help", b"-a", b"--own", b"--format=json"):
            self.assertEqual(self.canonical(raw), raw, raw)

    def test_whitespace_and_control_bytes_are_literal(self):
        for raw in (b"space name", b"tab\tname", b"newline\nname", b"return\rname"):
            self.assertEqual(self.canonical(raw), raw, raw)

    def test_bytes_that_are_not_utf8_are_literal(self):
        raw = b"tracked-\xe9\xff.dat"
        self.assertEqual(self.canonical(raw), raw)


class RejectionTests(unittest.TestCase):
    def assertRejected(self, raw, code, cwd=()):
        with self.assertRaises(scope.ScopeError, msg=repr(raw)) as caught:
            scope.canonicalise(raw, list(cwd))
        self.assertEqual(caught.exception.code, code, repr(raw))

    def test_absolute_paths(self):
        for raw in (b"/etc/passwd", b"/", b"//srv/x"):
            self.assertRejected(raw, scope.OWNERSHIP_PATH_ABSOLUTE)

    def test_empty_path(self):
        self.assertRejected(b"", scope.OWNERSHIP_PATH_EMPTY)

    def test_escaping_the_repository(self):
        for raw in (b"..", b"../outside", b"../../outside"):
            self.assertRejected(raw, scope.OWNERSHIP_PATH_ESCAPES_REPOSITORY)

    def test_escaping_from_a_subdirectory(self):
        self.assertRejected(
            b"../../outside", scope.OWNERSHIP_PATH_ESCAPES_REPOSITORY, cwd=(b"tests",)
        )

    def test_parent_after_a_named_component_is_ambiguous(self):
        """`src/../etc` only equals `etc` if `src` is not a symlink."""
        for raw in (b"src/../etc", b"a/b/../../c"):
            self.assertRejected(raw, scope.OWNERSHIP_PATH_PARENT_AMBIGUOUS)

    def test_repository_root_is_too_broad(self):
        for raw in (b".", b"./", b"././."):
            self.assertRejected(raw, scope.OWNERSHIP_SCOPE_TOO_BROAD)

    def test_git_administrative_paths(self):
        for raw in (b".git", b".git/config", b"vendor/.git/objects"):
            self.assertRejected(raw, scope.OWNERSHIP_PATH_ADMINISTRATIVE)

    def test_nul_byte(self):
        self.assertRejected(b"a\0b", scope.OWNERSHIP_PATH_INVALID)

    def test_no_owned_path_at_all(self):
        with self.assertRaises(scope.ScopeError) as caught:
            scope.resolve([], [])
        self.assertEqual(caught.exception.code, scope.OWNERSHIP_SCOPE_EMPTY)


class SymlinkTests(unittest.TestCase):
    def test_a_symlinked_component_is_not_resolved(self):
        """The owned identity is the repository path, not the link target."""
        root = tempfile.mkdtemp(prefix="aiqe-scope-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "target"))
        os.symlink("target", os.path.join(root, "link"))

        self.assertEqual(scope.canonicalise(b"link/file.py", []), b"link/file.py")


class ResolveTests(unittest.TestCase):
    def test_exact_duplicates_collapse(self):
        self.assertEqual(
            scope.resolve([b"src/a.py", b"src/a.py", b"./src/a.py"], []), [b"src/a.py"]
        )

    def test_overlapping_declarations_are_both_kept(self):
        """The narrower declaration was written on purpose."""
        self.assertEqual(
            scope.resolve([b"src", b"src/a.py"], []), [b"src", b"src/a.py"]
        )

    def test_order_does_not_matter(self):
        self.assertEqual(
            scope.resolve([b"b", b"a"], []), scope.resolve([b"a", b"b"], [])
        )


class DigestTests(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(scope.digest([b"src"]), scope.digest([b"src"]))

    def test_independent_of_declaration_order(self):
        self.assertEqual(scope.digest([b"a", b"b"]), scope.digest([b"b", b"a"]))

    def test_different_scopes_differ(self):
        self.assertNotEqual(scope.digest([b"src"]), scope.digest([b"src/a.py"]))
        self.assertNotEqual(scope.digest([b"src"]), scope.digest([b"src", b"tests"]))

    def test_component_boundaries_are_bound(self):
        """`a/b` and a single file literally named `a\\0b` cannot collide."""
        self.assertNotEqual(scope.digest([b"a", b"b"]), scope.digest([b"a/b"]))
        self.assertNotEqual(scope.digest([b"ab"]), scope.digest([b"a", b"b"]))

    def test_binds_bytes_not_display_text(self):
        """Two paths that could render alike must not digest alike."""
        composed = b"caf\xc3\xa9"
        decomposed = b"cafe\xcc\x81"
        self.assertNotEqual(scope.digest([composed]), scope.digest([decomposed]))

    def test_shape(self):
        value = scope.digest([b"src"])
        self.assertTrue(value.startswith("sha256:"))
        self.assertEqual(len(value), len("sha256:") + 64)


if __name__ == "__main__":
    unittest.main()
