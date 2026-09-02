"""Owned-scope path semantics.

A task declares which repository paths it owns. That declaration is the whole
point of the product, so the rules below are deliberately strict and boring.

Three properties matter, and each rules out a class of mistake:

**Paths are literal.** A declared path is data, never a pattern. `*`, `?`,
`[abc]`, `:(top)`, `--help` and a name containing a newline are all just
names. Nothing here consults the filesystem to decide what a name means, and
nothing hands a declared path to Git as a pathspec without the literal
discipline that keeps it a path.

**Ownership is component-prefix, not string-prefix.** Owning `foo` owns
`foo/bar` and `foo/bar/baz`. It does not own `foobar`. The distinction looks
pedantic written down and is the difference between a bounded change and a
silently widened one.

**Paths are bytes.** A repository path is a byte string. Decoding one to
decide what it is means a repository with an unusual filename gets a different
answer, or an error, from the tool whose job is to be exact about which files
changed.

Scope is a *declaration*, not an observation. A path that does not exist yet
can be owned - that is the normal case when the task is about to create it -
so nothing here requires a path to exist, and nothing infers whether a path
will become a file or a directory.
"""

import hashlib

#: Domain separator, so this digest cannot collide with a digest of the same
#: bytes computed for some other purpose later.
_DIGEST_DOMAIN = b"aiqe.owned-scope.v1\0"

#: The Git administrative directory. Owning it, or anything inside it, is
#: never a declaration about project content.
_ADMINISTRATIVE = b".git"

SEPARATOR = b"/"


class ScopeError(Exception):
    """A declared scope that AIQE will not accept.

    `code` is the stable machine identity; the message is for the user and may
    be reworded.
    """

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


OWNERSHIP_SCOPE_EMPTY = "OWNERSHIP_SCOPE_EMPTY"
OWNERSHIP_SCOPE_TOO_BROAD = "OWNERSHIP_SCOPE_TOO_BROAD"
OWNERSHIP_PATH_EMPTY = "OWNERSHIP_PATH_EMPTY"
OWNERSHIP_PATH_ABSOLUTE = "OWNERSHIP_PATH_ABSOLUTE"
OWNERSHIP_PATH_ESCAPES_REPOSITORY = "OWNERSHIP_PATH_ESCAPES_REPOSITORY"
OWNERSHIP_PATH_PARENT_AMBIGUOUS = "OWNERSHIP_PATH_PARENT_AMBIGUOUS"
OWNERSHIP_PATH_ADMINISTRATIVE = "OWNERSHIP_PATH_ADMINISTRATIVE"
OWNERSHIP_PATH_INVALID = "OWNERSHIP_PATH_INVALID"


def canonicalise(raw, cwd_components):
    """Turn one declared path into canonical repository-relative bytes.

    `raw` is the argument exactly as the user gave it, in bytes. `cwd_components`
    is where the command was invoked from, as repository-relative byte
    components, so that a relative argument means what it appears to mean from
    a subdirectory.

    Canonicalisation is limited to what is safe without consulting the
    filesystem: empty and `.` components are dropped, repeated and trailing
    separators collapse. There is no Unicode normalisation and no case folding
    - those would make two different filenames look like one - and no symlink
    resolution, because the owned identity is the repository path, not whatever
    it currently points at.
    """
    if not raw:
        raise ScopeError(OWNERSHIP_PATH_EMPTY, "an owned path may not be empty")
    if b"\0" in raw:
        raise ScopeError(
            OWNERSHIP_PATH_INVALID, "an owned path may not contain a NUL byte"
        )
    if raw.startswith(SEPARATOR):
        raise ScopeError(
            OWNERSHIP_PATH_ABSOLUTE,
            "an owned path must be relative to the repository, not absolute",
        )

    components = list(cwd_components)
    consumed_declared_component = False

    for component in raw.split(SEPARATOR):
        if component in (b"", b"."):
            continue
        if component == b"..":
            if consumed_declared_component:
                # `src/../etc` is only equal to `etc` if `src` is not a
                # symlink, and Doctor's rule everywhere is not to resolve
                # symlinks to decide what a path means. Leading `..` is
                # different: it walks back through the invocation directory,
                # which the operating system has already resolved.
                raise ScopeError(
                    OWNERSHIP_PATH_PARENT_AMBIGUOUS,
                    "'..' after a named component is ambiguous when a "
                    "component is a symlink; declare the path from the "
                    "repository root instead",
                )
            if not components:
                raise ScopeError(
                    OWNERSHIP_PATH_ESCAPES_REPOSITORY,
                    "an owned path may not escape the repository",
                )
            components.pop()
            continue
        components.append(component)
        consumed_declared_component = True

    if not components:
        raise ScopeError(
            OWNERSHIP_SCOPE_TOO_BROAD,
            "owning the whole repository is not a bounded task scope; declare "
            "the paths or top-level directories the task actually owns",
        )
    if _ADMINISTRATIVE in components:
        raise ScopeError(
            OWNERSHIP_PATH_ADMINISTRATIVE,
            "an owned path may not be inside the Git administrative directory",
        )

    return SEPARATOR.join(components)


def resolve(raw_paths, cwd_components):
    """Canonicalise every declared path into the task's owned scope.

    Exact duplicates collapse: declaring the same path twice is one scope, not
    two. Overlapping declarations do not collapse - declaring both `foo` and
    `foo/bar` keeps both, because the narrower declaration is something the
    user wrote on purpose and may still mean after `foo` is removed.

    The result is sorted by raw bytes, which is what makes the digest stable
    regardless of the order the paths were typed in.
    """
    if not raw_paths:
        raise ScopeError(
            OWNERSHIP_SCOPE_EMPTY, "a task must declare at least one owned path"
        )

    resolved = []
    for raw in raw_paths:
        canonical = canonicalise(raw, cwd_components)
        if canonical not in resolved:
            resolved.append(canonical)
    return sorted(resolved)


def owns(root, path):
    """Does an owned root contain this repository path?

    Component-prefix containment: `foo` owns `foo` and `foo/bar`, and does not
    own `foobar`. Both arguments are canonical repository-relative bytes.
    """
    return path == root or path.startswith(root + SEPARATOR)


def owned_by_any(roots, path):
    for root in roots:
        if owns(root, path):
            return True
    return False


def digest(roots):
    """A deterministic digest binding the exact owned-scope authority.

    The construction is documented so a reviewer can recompute it by hand:

        SHA-256( "aiqe.owned-scope.v1\\0" + concat(root + "\\0" for sorted roots) )

    It binds the raw path bytes, the component boundaries and the canonical
    ordering, and nothing else. It does not bind display text: two scopes that
    render identically but differ in bytes must produce different digests, and
    a change to how paths are printed must not change the digest.

    NUL is a safe delimiter because a POSIX path - and therefore a Git path -
    cannot contain one.
    """
    stream = bytearray(_DIGEST_DOMAIN)
    for root in sorted(roots):
        stream += root
        stream += b"\0"
    return "sha256:" + hashlib.sha256(bytes(stream)).hexdigest()
