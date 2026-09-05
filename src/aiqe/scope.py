"""Owned pathset semantics.

A task declares an exact set of repository paths it owns. That declaration is
the whole point of the product, so the rules below are deliberately strict and
boring.

Three properties matter, and each rules out a class of mistake:

**Ownership is exact.** Owning `foo` owns `foo`, and nothing else. Not
`foo/bar`, not `foobar`. There is no descendant ownership and no directory
scope in v1, on purpose: a prefix rule would let a task authorise files that
did not exist when the scope was declared, which is precisely the thing the
owned scope is supposed to bound. The public claim is the strong one - AIQE
knows the exact declared owned pathset - and a prefix rule cannot support it.

**Paths are literal.** A declared path is data, never a pattern. `*`, `?`,
`[abc]`, `:(top)`, `--help` and a name containing a newline are all just
names. Nothing hands a declared path to Git as a pattern.

**Paths are bytes.** A repository path is a byte string. Decoding one to
decide what it is means a repository with an unusual filename gets a different
answer, or an error, from the tool whose job is to be exact about which files
changed.

A declaration is not an observation. A path that does not exist yet can be
owned - that is the normal case when the task is about to create it - so
nothing here requires a path to exist. The one thing the filesystem is
consulted for is refusal: a path that exists *and is a directory today* is
refused rather than quietly meaning something a user might read as a scope.
"""

import hashlib
import stat as _stat_module

#: Domain separator, so this digest cannot collide with a digest of the same
#: bytes computed for some other purpose later. The name says what the digest
#: is authority over: an exact pathset, not a scope with descendants.
_DIGEST_DOMAIN = b"aiqe.owned-pathset.v1\0"

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
OWNED_PATH_IS_DIRECTORY = "OWNED_PATH_IS_DIRECTORY"
OWNED_PATH_IS_SYMLINK = "OWNED_PATH_IS_SYMLINK"
OWNED_PATH_NOT_REGULAR = "OWNED_PATH_NOT_REGULAR"
DUPLICATE_OWNED_PATH = "DUPLICATE_OWNED_PATH"


#: The bytes that make a declared value look like a surface pattern rather
#: than a filename. They are exactly the metacharacters of the surface pattern
#: grammar in `patterns.py`, because the question this supports is "would a
#: reader have expected this to behave like a surface pattern".
GLOB_METACHARACTERS = (b"*", b"?", b"[")


def is_glob_shaped(path):
    """Does this declared path *look* like a pattern?

    This decides nothing about ownership. Ownership stays exactly literal:
    `owns` is still raw-byte equality, and nothing here expands anything.
    What this answers is the narrower question that a fail-closed ambiguity
    check needs - whether a caller who typed this value could plausibly have
    believed it selected more than one file.

    Shape is not intent, so a positive answer is never acted on by itself. A
    declaration whose value exists as a real path is a filename that happens
    to contain these bytes, and it is treated as one.
    """
    return any(character in path for character in GLOB_METACHARACTERS)


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
    """Canonicalise every declared path into the task's owned pathset.

    A duplicate is refused, not quietly collapsed. Two spellings of one path
    in one declaration means the user believes they declared two things, and
    silently agreeing with half of that belief is how a scope ends up meaning
    something its author did not intend. Say so instead.

    Two *distinct* paths never merge, even when one is a lexical parent of the
    other - `foo` and `foo/bar` are two declarations of two paths, and with
    exact ownership neither implies the other.

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
        if canonical in resolved:
            raise ScopeError(
                DUPLICATE_OWNED_PATH,
                "%s is declared more than once; each owned path is declared "
                "once" % (_render(canonical),),
            )
        resolved.append(canonical)
    return sorted(resolved)


def owns(owned, path):
    """Is this repository path the declared owned path?

    Exact raw-byte equality, and nothing else:

        owns(foo, foo)      True
        owns(foo, foo/bar)  False
        owns(foo, foobar)   False

    Both arguments are canonical repository-relative bytes. The absence of a
    prefix rule here is the whole ownership semantics: a task owns what it
    named, and a file that appears later under a declared path's name was
    never declared.
    """
    return path == owned


def owned_by_any(owned_paths, path):
    for owned in owned_paths:
        if owns(owned, path):
            return True
    return False


def digest(owned_paths):
    """A deterministic digest binding the exact owned pathset.

    The construction is documented so a reviewer can recompute it by hand:

        SHA-256( "aiqe.owned-pathset.v1\\0" + concat(path + "\\0" for sorted paths) )

    It binds the raw path bytes, the component boundaries and the canonical
    ordering, and nothing else. It does not bind display text: two pathsets
    that render identically but differ in bytes must produce different
    digests, and a change to how paths are printed must not change the digest.

    NUL is a safe delimiter because a POSIX path - and therefore a Git path -
    cannot contain one.
    """
    stream = bytearray(_DIGEST_DOMAIN)
    for path in sorted(owned_paths):
        stream += path
        stream += b"\0"
    return "sha256:" + hashlib.sha256(bytes(stream)).hexdigest()


def validate_paths(owned_paths, worktree):
    """Refuse a declared path that exists today as anything but a regular file.

    v1 owns an exact pathset of regular files. What the filesystem is
    consulted for is refusal, and only refusal:

        absent                  accepted - a path declared before it exists
        regular file            accepted - tracked or untracked, it makes no
                                difference to a declaration
        directory               refused
        symlink                 refused
        anything else           refused

    `lstat`, not `stat`, and no target is followed. A symlink is refused as a
    symlink rather than judged by what it points at, because v1's owned-path,
    checked-content and commit semantics are defined over regular files, their
    creation and their deletion - and nothing else. Supporting links is not
    required for launch, and pretending to support them would put a hole in
    the content binding rather than in the path rules.

    A path that does not exist is accepted: declaring a file before creating
    it is the normal case. If it later materialises as something other than a
    regular file, a later operation resolving path identity must fail closed
    rather than reinterpret the declaration.
    """
    if worktree is None:
        return
    import os

    for path in owned_paths:
        try:
            stat = os.lstat(os.path.join(worktree, path))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            # Unreadable is not the same as "is the wrong kind". Leave it to
            # the operations that must resolve identity to fail closed.
            continue

        if _stat_module.S_ISREG(stat.st_mode):
            continue
        if _stat_module.S_ISDIR(stat.st_mode):
            raise ScopeError(
                OWNED_PATH_IS_DIRECTORY,
                "an owned path must be a file path; %s exists as a directory. "
                "AIQE v1 owns an exact pathset, so declare the files this task "
                "owns rather than a directory." % (_render(path),),
            )
        if _stat_module.S_ISLNK(stat.st_mode):
            raise ScopeError(
                OWNED_PATH_IS_SYMLINK,
                "an owned path must be a regular file; %s is a symbolic link. "
                "AIQE v1 does not own links." % (_render(path),),
            )
        raise ScopeError(
            OWNED_PATH_NOT_REGULAR,
            "an owned path must be a regular file; %s is not one."
            % (_render(path),),
        )


def _render(path):
    from .textsafe import display_bytes

    return display_bytes(path)
