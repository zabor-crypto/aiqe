"""What an owned path is right now, and the bounded binding that records it.

`aiqe check` classifies **changed owned paths**, not the repository. So the
first thing a check has to do is resolve, for each declared owned path, which
of five states it is in relative to the task's baseline commit:

```
TRACKED_UNCHANGED   present in the baseline commit, same bytes on disk
TRACKED_MODIFIED    present in the baseline commit, different bytes on disk
TRACKED_DELETED     present in the baseline commit, absent from the worktree
NEW                 absent from the baseline commit, present as a regular file
PENDING_ABSENT      absent from both - a path declared before it exists
```

Three of those are changes. `TRACKED_UNCHANGED` and `PENDING_ABSENT` are not,
and a task that declared a path it never touched carries no obligation for it.

**Nothing here asks Git whether a file changed.** Answering that question makes
Git read worktree content through any configured check-in filter, which is
repository-defined code, and running it would put the thing AIQE refuses to do
inside the operation whose whole job is to say what was checked. Instead the
baseline blob's stored bytes are read with `cat-file`, the worktree file's
bytes are read directly, and the comparison is AIQE's own.

That comparison is conservative in the safe direction. Under a check-in filter
or a line-ending conversion, a file Git would call unchanged can read as
changed here. The consequence is more paths classified and more obligations,
never fewer.

**Fail closed on anything else.** A declared path that today is a directory, a
symbolic link, a device node, or a submodule pointer in the baseline commit is
not reinterpreted. v1 owns regular files, their creation and their deletion,
and a declaration that has become something else is refused rather than
guessed at - which is what the frozen task contract promised the operation
resolving path identity would do.

The binding this module produces is bounded by the owned pathset. There is no
whole-tree fingerprint, and there never is one: the cost of a check must not
scale with the size of somebody's repository.
"""

import hashlib
import os
import stat as stat_module

#: Domain separator for owned content digests.
_CONTENT_DOMAIN = b"aiqe.owned-content.v1\0"

#: Domain separator for the digest over a whole owned-path binding, which is
#: what staleness detection compares.
_BINDING_DOMAIN = b"aiqe.owned-binding.v1\0"

TRACKED_UNCHANGED = "TRACKED_UNCHANGED"
TRACKED_MODIFIED = "TRACKED_MODIFIED"
TRACKED_DELETED = "TRACKED_DELETED"
NEW = "NEW"
PENDING_ABSENT = "PENDING_ABSENT"

#: The states that mean this owned path is part of the current change.
CHANGED_STATES = frozenset({TRACKED_MODIFIED, TRACKED_DELETED, NEW})

OWNED_PATH_UNSUPPORTED_OBJECT = "OWNED_PATH_UNSUPPORTED_OBJECT"
OWNED_PATH_UNREADABLE = "OWNED_PATH_UNREADABLE"
BASELINE_UNREADABLE = "BASELINE_UNREADABLE"

#: A glob-shaped owned declaration that names no file, while a changed file
#: the glob would have selected lies outside the owned pathset.
OWNED_PATH_GLOB_AMBIGUITY = "OWNED_PATH_GLOB_AMBIGUITY"


class PathStateError(Exception):
    """An owned path whose current identity AIQE will not guess at."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class OwnedPathState(object):
    """One owned declaration, resolved against the baseline commit."""

    __slots__ = ("path", "state", "content_digest", "mode")

    def __init__(self, path, state, content_digest, mode):
        #: Raw repository-relative bytes, exactly as declared.
        self.path = path
        self.state = state
        #: Digest of the current worktree content, or None when absent.
        self.content_digest = content_digest
        #: The permission bits that matter - the executable bit - or None.
        self.mode = mode

    @property
    def changed(self):
        return self.state in CHANGED_STATES

    def as_record(self):
        """The binding entry persisted in local evidence."""
        import base64

        return {
            "path_b64": base64.b64encode(self.path).decode("ascii"),
            "state": self.state,
            "content_digest": self.content_digest,
            "mode": self.mode,
        }


def content_digest(raw):
    return "sha256:" + hashlib.sha256(_CONTENT_DOMAIN + raw).hexdigest()


def binding_digest(states):
    """One digest over the whole owned-path binding.

    Length-delimited and binary-safe, so that no two different bindings can
    serialise to the same bytes: a path containing the delimiter, or a path
    that is a prefix of another, must not be able to collide with a different
    binding.

    Ordering is by raw path bytes, so the digest does not depend on the order
    the paths were declared in.
    """
    stream = bytearray(_BINDING_DOMAIN)
    for state in sorted(states, key=lambda entry: entry.path):
        _append(stream, state.path)
        _append(stream, state.state.encode("ascii"))
        _append(stream, (state.content_digest or "").encode("ascii"))
        _append(stream, b"" if state.mode is None else b"%d" % (state.mode,))
    return "sha256:" + hashlib.sha256(bytes(stream)).hexdigest()


def _append(stream, field):
    stream += len(field).to_bytes(8, "big")
    stream += field


# --- Resolution ------------------------------------------------------------


def resolve(runner, worktree, owned_paths, baseline_sha):
    """Resolve every owned path against `baseline_sha`. Raises `PathStateError`.

    `runner` is a `GitRunner` already rooted in the repository. `worktree` is
    the absolute worktree root, as bytes.
    """
    baseline = _baseline_entries(runner, owned_paths, baseline_sha)
    return tuple(
        _resolve_one(runner, worktree, path, baseline.get(path))
        for path in owned_paths
    )


def _resolve_one(runner, worktree, path, baseline_entry):
    absolute = os.path.join(worktree, path)
    try:
        stat = os.lstat(absolute)
    except (FileNotFoundError, NotADirectoryError):
        stat = None
    except OSError as exc:
        raise PathStateError(
            OWNED_PATH_UNREADABLE,
            "the owned path %s could not be inspected: %s"
            % (_render(path), exc.strerror),
        )

    if stat is not None and not stat_module.S_ISREG(stat.st_mode):
        raise PathStateError(
            OWNED_PATH_UNSUPPORTED_OBJECT,
            "the owned path %s exists as %s. AIQE v1 owns regular files, and "
            "a declaration that has become something else is refused rather "
            "than reinterpreted." % (_render(path), _kind(stat.st_mode)),
        )

    if baseline_entry is not None and baseline_entry["type"] != b"blob":
        raise PathStateError(
            OWNED_PATH_UNSUPPORTED_OBJECT,
            "the owned path %s is a %s in the task's baseline commit, not a "
            "file." % (_render(path), baseline_entry["type"].decode("ascii")),
        )
    if baseline_entry is not None and baseline_entry["mode"] == b"120000":
        raise PathStateError(
            OWNED_PATH_UNSUPPORTED_OBJECT,
            "the owned path %s is a symbolic link in the task's baseline "
            "commit. AIQE v1 does not own links." % (_render(path),),
        )

    if stat is None:
        if baseline_entry is None:
            return OwnedPathState(path, PENDING_ABSENT, None, None)
        return OwnedPathState(path, TRACKED_DELETED, None, None)

    try:
        with open(absolute, "rb") as handle:
            current = handle.read()
    except OSError as exc:
        raise PathStateError(
            OWNED_PATH_UNREADABLE,
            "the owned path %s could not be read: %s"
            % (_render(path), exc.strerror),
        )

    digest = content_digest(current)
    mode = 0o755 if stat.st_mode & 0o111 else 0o644

    if baseline_entry is None:
        return OwnedPathState(path, NEW, digest, mode)

    stored = _baseline_blob(runner, path, baseline_entry["object"])
    baseline_mode = 0o755 if baseline_entry["mode"] == b"100755" else 0o644
    if stored == current and baseline_mode == mode:
        return OwnedPathState(path, TRACKED_UNCHANGED, digest, mode)
    return OwnedPathState(path, TRACKED_MODIFIED, digest, mode)


def _baseline_entries(runner, owned_paths, baseline_sha):
    """The baseline commit's tree entries for the owned paths.

    One `ls-tree` per declaration, addressed with the `:(literal)` pathspec
    magic so that a filename containing a pathspec metacharacter names itself
    and nothing else. The result is matched back by exact raw bytes: a
    declaration that names a directory in the baseline returns that
    directory's own entry, whose type is `tree`, and the caller refuses it.
    """
    entries = {}
    for path in owned_paths:
        result = runner.run(
            "ls-tree",
            "-z",
            "--full-tree",
            baseline_sha,
            "--",
            b":(literal)" + path,
        )
        if not result.ok:
            raise PathStateError(
                BASELINE_UNREADABLE,
                "the task's baseline commit could not be read for %s."
                % (_render(path),),
            )
        for field in result.nul_fields():
            entry = _parse_tree_entry(field)
            if entry is not None and entry["path"] == path:
                entries[path] = entry
    return entries


def _parse_tree_entry(field):
    """`<mode> SP <type> SP <object> TAB <path>`, all bytes."""
    if b"\t" not in field:
        return None
    metadata, path = field.split(b"\t", 1)
    parts = metadata.split(b" ")
    if len(parts) != 3:
        return None
    return {"mode": parts[0], "type": parts[1], "object": parts[2], "path": path}


def _baseline_blob(runner, path, object_id):
    result = runner.run("cat-file", "blob", object_id.decode("ascii", "replace"))
    if not result.ok:
        raise PathStateError(
            BASELINE_UNREADABLE,
            "the baseline content of %s could not be read." % (_render(path),),
        )
    return result.stdout


def _kind(mode):
    if stat_module.S_ISDIR(mode):
        return "a directory"
    if stat_module.S_ISLNK(mode):
        return "a symbolic link"
    return "neither a regular file nor a directory"


def _render(path):
    from .textsafe import display_bytes

    return display_bytes(path)


# --- Foreign staged observation --------------------------------------------


def foreign_staged_count(runner, owned_paths):
    """How many staged entries lie outside the owned pathset.

    Informational, exactly as at task start. `diff-index --cached` compares
    the index against HEAD and reads no worktree content, so it cannot refresh
    the index and cannot trigger a filter driver. Filenames are counted, never
    stored.

    This is not the foreign-staged preservation proof. That is a structured
    before-and-after comparison, and it belongs to a bounded commit, which
    does not exist.
    """
    result = runner.run("diff-index", "--cached", "--name-only", "-z", "HEAD")
    if not result.ok:
        return None
    owned = set(owned_paths)
    return sum(1 for name in result.nul_fields() if name not in owned)


# --- Glob/literal ambiguity ------------------------------------------------


class GlobAmbiguity(object):
    """One glob-shaped declaration, and a changed path that escaped it.

    `declared` is the owned value exactly as the task recorded it. `example`
    is the lowest-sorted changed repository path the same value would have
    selected had it been a pattern, and `total` is how many such paths were
    found. One example is enough to show the caller what they lost; the count
    tells them whether naming it is the whole fix.
    """

    __slots__ = ("declared", "example", "total")

    def __init__(self, declared, example, total):
        self.declared = declared
        self.example = example
        self.total = total

    def as_record(self):
        import base64

        return {
            "declared_b64": base64.b64encode(self.declared).decode("ascii"),
            "example_b64": base64.b64encode(self.example).decode("ascii"),
            "matched_changed_count": self.total,
        }


def glob_ambiguities(runner, worktree, owned_states, baseline_sha):
    """Changed paths a glob-shaped owned declaration would have selected.

    `--own` takes literal paths, and that is not changing. But a caller who
    typed `--own 'src/strategy/**'` and got one absent literal path back has
    declared ownership of nothing, and every file they meant is unowned. The
    check that follows is then arithmetically correct and completely
    misleading: zero changed owned paths, no obligations, and a green result.

    So a declaration is refused when all three of these hold:

      * it is glob-shaped - it contains `*`, `?` or `[`;
      * it names no file - neither the baseline commit nor the worktree has
        it, so it cannot be a filename that merely contains those bytes;
      * read as a surface pattern it selects at least one repository path
        that has changed and that the task does not own.

    Any one of those failing means there is no false green to prevent. A real
    file called `weird[1].csv` is a filename, and stays one. A glob-shaped
    declaration for a file that does not exist yet is the ordinary
    declare-before-create case, and stays one until something it would have
    matched actually changes.

    **Nothing is expanded.** No matched path becomes owned, and the owned
    pathset is untouched. The only outcome is a refusal that names what was
    missed, so the caller can declare those paths themselves.

    Cost is paid only on the exceptional branch: with no glob-shaped absent
    declaration this makes no Git calls at all.
    """
    from . import scope as scope_module

    suspects = [
        state.path
        for state in owned_states
        if state.state == PENDING_ABSENT
        and scope_module.is_glob_shaped(state.path)
    ]
    if not suspects:
        return ()

    patterns = []
    for declared in suspects:
        pattern = _compile_or_none(declared)
        if pattern is not None:
            patterns.append((declared, pattern))
    if not patterns:
        # Glob-shaped but not a compilable pattern - `a**b`, an unterminated
        # byte class. There is no reading of it under which it selects a set,
        # so there is no ambiguity to report.
        return ()

    owned = set(state.path for state in owned_states)
    candidates, baseline = _candidate_paths(runner, baseline_sha)

    ambiguities = []
    for declared, pattern in patterns:
        matched = []
        for path in candidates:
            if path in owned or not pattern.matches(path):
                continue
            if _is_changed(runner, worktree, path, baseline.get(path)):
                matched.append(path)
        if matched:
            ambiguities.append(GlobAmbiguity(declared, matched[0], len(matched)))
    return tuple(ambiguities)


def _compile_or_none(declared):
    from . import patterns as patterns_module

    try:
        return patterns_module.compile_pattern(declared)
    except patterns_module.PatternError:
        return None


def _candidate_paths(runner, baseline_sha):
    """Every path a pattern could select, and the baseline entries for them.

    Two sources, and neither reads file content through Git:

      * `ls-tree -r` lists the baseline commit's blobs out of the object
        database;
      * `ls-files --others --exclude-standard` lists untracked worktree files
        by name.

    Names only. The changed/unchanged decision stays where this module already
    makes it - AIQE's own byte comparison - so a check-in filter is no more
    reachable from here than from anywhere else in this file.

    Returns (sorted candidate paths, {path: baseline entry}). Sorting is by raw
    bytes so the reported example does not depend on Git's output order.
    """
    baseline = {}
    result = runner.run("ls-tree", "-r", "-z", "--full-tree", baseline_sha)
    if not result.ok:
        raise PathStateError(
            BASELINE_UNREADABLE,
            "the task's baseline commit could not be listed while resolving a "
            "glob-shaped owned declaration.",
        )
    for field in result.nul_fields():
        entry = _parse_tree_entry(field)
        if entry is not None:
            baseline[entry["path"]] = entry

    candidates = set(baseline)
    # `--full-name` and the `:(top)` pathspec are both required, and for two
    # different reasons. The runner is rooted at the *invocation* directory,
    # not the worktree root, and a bare `ls-files --others` there would report
    # paths relative to that subdirectory *and* look only inside it - so a
    # check run from `src/` would compare `strategy/a.py` against a pattern
    # written from the repository root, and would never see an untracked file
    # anywhere else. `ls-tree --full-tree` above is already root-relative.
    untracked = runner.run(
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--full-name",
        "--",
        ":(top)",
    )
    if untracked.ok:
        candidates.update(untracked.nul_fields())
    return sorted(candidates), baseline


def _is_changed(runner, worktree, path, baseline_entry):
    """Is this candidate part of the current change?

    A candidate whose identity cannot be resolved is reported as unchanged,
    which is safe here and would not be safe for a declared path. The states
    that raise are the ones where the path is not a regular file, and AIQE v1
    cannot own one of those under any spelling - so naming it explicitly would
    not have produced a different result, and there is no false green being
    concealed.
    """
    try:
        state = _resolve_one(runner, worktree, path, baseline_entry)
    except PathStateError:
        return False
    return state.changed
