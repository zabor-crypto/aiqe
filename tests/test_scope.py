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
    """Exact byte equality. There is no prefix rule, and that is the point.

    A prefix rule would let a task authorise files that did not exist when the
    scope was declared, which is the thing an owned scope exists to bound.
    """

    def test_a_declared_path_owns_itself(self):
        self.assertTrue(scope.owns(b"foo", b"foo"))

    def test_a_declared_path_does_not_own_its_descendants(self):
        for descendant in (b"foo/bar", b"foo/bar/baz", b"foo/"):
            self.assertFalse(scope.owns(b"foo", descendant), descendant)

    def test_a_declared_path_does_not_own_a_name_it_merely_prefixes(self):
        for other in (b"foobar", b"foo-other", b"foo.py", b"foox/bar"):
            self.assertFalse(scope.owns(b"foo", other), other)

    def test_a_declared_path_does_not_own_its_parent(self):
        self.assertFalse(scope.owns(b"src/a.py", b"src"))

    def test_a_file_declaration_owns_only_itself(self):
        self.assertTrue(scope.owns(b"src/a.py", b"src/a.py"))
        self.assertFalse(scope.owns(b"src/a.py", b"src/a.pyc"))

    def test_owned_by_any_is_exact_across_the_pathset(self):
        owned = [b"src/a.py", b"docs/guide.md"]
        self.assertTrue(scope.owned_by_any(owned, b"src/a.py"))
        self.assertTrue(scope.owned_by_any(owned, b"docs/guide.md"))
        for other in (b"src", b"src/b.py", b"docs/guide.md.bak", b"docs"):
            self.assertFalse(scope.owned_by_any(owned, other), other)




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


class DirectoryRejectionTests(unittest.TestCase):
    """A directory declaration has no meaning under exact ownership."""

    def setUp(self):
        self.worktree = os.fsencode(tempfile.mkdtemp(prefix="aiqe-dir-"))
        self.addCleanup(shutil.rmtree, self.worktree, True)

    def make(self, relative, kind):
        path = os.path.join(self.worktree, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if kind == "dir":
            os.makedirs(path)
        else:
            with open(path, "wb") as handle:
                handle.write(b"x\n")
        return path

    def test_an_existing_directory_is_refused(self):
        self.make(b"src", "dir")
        with self.assertRaises(scope.ScopeError) as caught:
            scope.reject_directories([b"src"], self.worktree)
        self.assertEqual(caught.exception.code, scope.OWNED_PATH_IS_DIRECTORY)

    def test_an_existing_file_is_accepted(self):
        self.make(b"src/a.py", "file")
        scope.reject_directories([b"src/a.py"], self.worktree)

    def test_a_path_that_does_not_exist_is_accepted(self):
        """Declaring a file before creating it is the normal case."""
        scope.reject_directories([b"src/future.py"], self.worktree)

    def test_a_symlink_to_a_directory_is_accepted(self):
        """The declaration owns the link, not what it resolves to."""
        self.make(b"real", "dir")
        os.symlink(b"real", os.path.join(self.worktree, b"link"))
        scope.reject_directories([b"link"], self.worktree)

    def test_only_the_offending_path_is_named(self):
        self.make(b"src", "dir")
        with self.assertRaises(scope.ScopeError) as caught:
            scope.reject_directories([b"a.py", b"src", b"b.py"], self.worktree)
        self.assertIn("src", caught.exception.message)

    def test_a_control_character_in_the_name_is_escaped_in_the_refusal(self):
        self.make(b"weird\nname", "dir")
        with self.assertRaises(scope.ScopeError) as caught:
            scope.reject_directories([b"weird\nname"], self.worktree)
        self.assertIn("weird\\nname", caught.exception.message)
        self.assertNotIn("\n", caught.exception.message.replace("\\n", ""))


class ResolveTests(unittest.TestCase):
    def test_exact_duplicates_collapse(self):
        self.assertEqual(
            scope.resolve([b"src/a.py", b"src/a.py", b"./src/a.py"], []), [b"src/a.py"]
        )

    def test_a_lexical_parent_and_child_are_two_distinct_paths(self):
        """Neither implies the other, so neither collapses into it."""
        self.assertEqual(
            scope.resolve([b"docs", b"docs/guide.md"], []), [b"docs", b"docs/guide.md"]
        )
        self.assertNotEqual(scope.digest([b"docs"]), scope.digest([b"docs", b"docs/guide.md"]))

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

    def test_domain_is_bound_to_exact_pathset_authority(self):
        """A digest of the same bytes under another domain must differ."""
        import hashlib

        stream = bytearray(b"aiqe.owned-pathset.v1\0")
        stream += b"src"
        stream += b"\0"
        self.assertEqual(
            scope.digest([b"src"]),
            "sha256:" + hashlib.sha256(bytes(stream)).hexdigest(),
        )

    def test_shape(self):
        value = scope.digest([b"src"])
        self.assertTrue(value.startswith("sha256:"))
        self.assertEqual(len(value), len("sha256:") + 64)


if __name__ == "__main__":
    unittest.main()
