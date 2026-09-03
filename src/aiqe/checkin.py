"""What Git would store, computed before the commit and proved after it.

`aiqe check` compares raw worktree bytes against raw stored bytes and never
asks Git whether a file changed, because answering that makes Git read content
through a check-in filter. The cost of that safety is a documented
conservatism: under EOL normalisation a file Git would call unchanged reads as
changed, which adds obligations rather than removing them.

A commit cannot afford that conservatism, because it has to prove the opposite
direction. `CHECKED_CONTENT_BOUND` means the committed blob is the supported
Git transformation of the exact checked bytes - and under
`core.autocrlf = true`, or a `* text` attribute, the committed blob is
deliberately *not* the worktree bytes. Comparing the two would report a
mismatch on a correct commit, which is the worst kind of wrong answer: a false
alarm from the mechanism whose entire job is to be believed.

So the expected committed state is derived, per owned path, as:

```
regular file      the blob OID Git would store, and the Git mode
deletion          absent, having been present in the pre-commit HEAD
pending absent    absent, and absent before - not a change
```

The blob OID comes from `git hash-object --path=<repo-relative path>`, which
applies exactly the check-in transformations Git would apply and writes
nothing. It also runs an external clean filter, if one is bound - which is
why `commitpolicy` refuses those before this module is ever reached. The
ordering is the safety property, and it is measured: `check-attr` leaves a
filter canary unwritten, `hash-object --path` fires it.

Modes follow `core.fileMode`. Where it is true the worktree's execute bit
decides; where it is false Git preserves the mode already recorded, so the
expectation does too. Both were measured rather than reasoned about.

The foreign staged state is a **structured delta**, not a count and not an
index dump. It is `diff-index --cached` against the pre-commit HEAD, restricted
to non-owned paths, with rename detection disabled and NUL-safe parsing, and
it distinguishes addition, modification, deletion and mode or type change -
which is what makes "the same before and after" a claim worth making. Staged
deletions are represented, and no foreign worktree content is ever hashed.
"""

import os

#: Git tree modes AIQE v1 can commit. Anything else - a symbolic link, a
#: gitlink - is refused by Task Core's owned-path rules long before here.
MODE_REGULAR = b"100644"
MODE_EXECUTABLE = b"100755"

ABSENT = "ABSENT"
REGULAR = "REGULAR"

EXPECTED_STATE_UNRESOLVED = "EXPECTED_STATE_UNRESOLVED"
FOREIGN_STAGED_UNREADABLE = "FOREIGN_STAGED_UNREADABLE"
COMMIT_TREE_UNREADABLE = "COMMIT_TREE_UNREADABLE"


class CheckinError(Exception):
    """Git could not answer a question the commit proof depends on."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class ExpectedState(object):
    """What one owned path is expected to look like in the completion commit."""

    __slots__ = ("path", "kind", "blob", "mode", "before_kind", "before_blob",
                 "before_mode")

    def __init__(self, path, kind, blob, mode, before_kind, before_blob,
                 before_mode):
        self.path = path
        #: REGULAR or ABSENT.
        self.kind = kind
        #: Expected blob OID as ASCII bytes, or None when absent.
        self.blob = blob
        #: Expected Git mode as bytes, or None when absent.
        self.mode = mode
        self.before_kind = before_kind
        self.before_blob = before_blob
        self.before_mode = before_mode

    @property
    def changed(self):
        """Does the expected committed state differ from the pre-commit HEAD?"""
        return (
            self.kind != self.before_kind
            or self.blob != self.before_blob
            or self.mode != self.before_mode
        )

    def matches(self, kind, blob, mode):
        return self.kind == kind and self.blob == blob and self.mode == mode

    def as_record(self):
        import base64

        return {
            "path_b64": base64.b64encode(self.path).decode("ascii"),
            "expected_kind": self.kind,
            "expected_blob": _text(self.blob),
            "expected_mode": _text(self.mode),
            "head_kind": self.before_kind,
            "head_blob": _text(self.before_blob),
            "head_mode": _text(self.before_mode),
            "expected_changed": self.changed,
        }


def _text(value):
    if value is None:
        return None
    return value.decode("ascii", "replace")


# --- Reading trees and the index -------------------------------------------


def tree_entries(runner, commit, paths):
    """Tree state of exactly these paths at `commit`.

    One `ls-tree` per declaration, matched back by exact raw bytes. Pathspec
    magic is deliberately absent: the runner passes `--literal-pathspecs`
    globally, which turns off *all* magic, so a `:(literal)` prefix would be
    read as part of the filename. Measured: with both in play, `ls-tree`
    matches nothing.
    """
    entries = {}
    for path in paths:
        result = runner.run("ls-tree", "-z", "--full-tree", commit, "--", path)
        if not result.ok:
            raise CheckinError(
                COMMIT_TREE_UNREADABLE,
                "the tree of commit %s could not be read for an owned path."
                % (commit,),
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


def index_entries(runner, paths):
    """Stage-0 index entries for exactly these paths: {path: (mode, oid)}."""
    entries = {}
    if not paths:
        return entries
    result = runner.run("ls-files", "--stage", "-z", "--", *paths)
    if not result.ok:
        raise CheckinError(
            EXPECTED_STATE_UNRESOLVED,
            "the Git index could not be read for the owned pathset.",
        )
    for field in result.nul_fields():
        if b"\t" not in field:
            continue
        metadata, path = field.split(b"\t", 1)
        parts = metadata.split(b" ")
        if len(parts) != 3:
            continue
        mode, oid, stage = parts
        if stage != b"0":
            continue
        entries[path] = (mode, oid)
    return entries


# --- Expected checked-in state ---------------------------------------------


def file_mode_is_significant(config):
    """Git's effective `core.fileMode`, which decides whether mode 0755 exists.

    Unset means true, which is Git's own default. Where it is false Git
    ignores the worktree execute bit entirely and keeps the recorded mode -
    measured, not assumed: a `chmod +x` under `core.fileMode=false` commits
    100644.
    """
    from .commitpolicy import is_true

    if not config.present("core.fileMode"):
        return True
    return is_true(config.get("core.fileMode"))


def expected_states(runner, config, worktree, head_sha, owned_states):
    """Derive the expected committed state of every owned path.

    `owned_states` are `pathstate.OwnedPathState` values, already resolved
    against the same commit, so a path that has become a directory or a link
    has already been refused.
    """
    from . import pathstate

    paths = [state.path for state in owned_states]
    head = tree_entries(runner, head_sha, paths)
    index = index_entries(runner, paths)
    significant = file_mode_is_significant(config)

    expected = []
    for state in owned_states:
        head_entry = head.get(state.path)
        before_kind = REGULAR if head_entry is not None else ABSENT
        before_blob = head_entry["object"] if head_entry is not None else None
        before_mode = head_entry["mode"] if head_entry is not None else None

        if state.state in (pathstate.TRACKED_DELETED, pathstate.PENDING_ABSENT):
            expected.append(
                ExpectedState(
                    state.path, ABSENT, None, None, before_kind, before_blob,
                    before_mode,
                )
            )
            continue

        blob = _hash_object(runner, worktree, state.path)
        mode = _expected_mode(
            significant, state, index.get(state.path), head_entry
        )
        expected.append(
            ExpectedState(
                state.path, REGULAR, blob, mode, before_kind, before_blob,
                before_mode,
            )
        )
    return tuple(expected)


def _hash_object(runner, worktree, path):
    """The blob OID Git would store for this worktree file. Writes nothing.

    `--path` is what makes the answer include the check-in transformations
    bound to that repository path - EOL normalisation above all. Without it
    the answer would be the raw bytes, which is the conservative comparison
    `check` makes and the wrong one to prove a commit against.
    """
    absolute = os.path.join(worktree, path)
    result = runner.run("hash-object", b"--path=" + path, "--", absolute)
    if not result.ok or not result.lines():
        raise CheckinError(
            EXPECTED_STATE_UNRESOLVED,
            "Git could not compute the object identity an owned path would be "
            "stored as.",
        )
    return result.lines()[0].strip()


def _expected_mode(significant, state, index_entry, head_entry):
    if significant:
        return MODE_EXECUTABLE if state.mode == 0o755 else MODE_REGULAR
    if index_entry is not None:
        return index_entry[0]
    if head_entry is not None:
        return head_entry["mode"]
    return MODE_REGULAR


def changed_paths(expected):
    """The authoritative expected parent-to-commit changed pathset."""
    return tuple(entry.path for entry in expected if entry.changed)


# --- Structured deltas -----------------------------------------------------


def _parse_raw_delta(fields):
    """Parse `--raw -z` records into {path: (srcmode, dstmode, srcsha, dstsha, status)}.

    Record shape:

        :<srcmode> SP <dstmode> SP <srcsha> SP <dstsha> SP <status> NUL <path> NUL

    Rename and copy statuses carry a second path field. Rename detection is
    disabled on every call site, but the parser consumes the extra field
    anyway rather than silently misaligning if a future Git emits one.
    """
    delta = {}
    index = 0
    total = len(fields)
    while index < total:
        record = fields[index]
        index += 1
        if not record.startswith(b":"):
            raise ValueError("unrecognised raw diff record")
        parts = record[1:].split(b" ")
        if len(parts) != 5:
            raise ValueError("unrecognised raw diff record")
        if index >= total:
            raise ValueError("raw diff record without a path")
        path = fields[index]
        index += 1
        status = parts[4]
        if status[:1] in (b"R", b"C"):
            if index >= total:
                raise ValueError("rename record without a destination path")
            path = fields[index]
            index += 1
        delta[path] = (parts[0], parts[1], parts[2], parts[3], status)
    return delta


def foreign_staged_delta(runner, head_sha, owned_paths):
    """The staged delta against `head_sha` over every non-owned path.

    Authoritative, structured and comparable: enough identity to tell an
    addition from a modification from a deletion from a mode or type change.
    No foreign worktree content is read, and no foreign untracked file is
    hashed - `diff-index --cached` compares the index against a tree and
    touches the worktree not at all.
    """
    result = runner.run(
        "diff-index", "--cached", "--raw", "-z", "--no-renames", head_sha
    )
    if not result.ok:
        raise CheckinError(
            FOREIGN_STAGED_UNREADABLE,
            "the staged state of this worktree could not be read, so AIQE "
            "cannot prove what the commit did or did not include.",
        )
    try:
        delta = _parse_raw_delta(result.nul_fields())
    except ValueError as error:
        raise CheckinError(FOREIGN_STAGED_UNREADABLE, str(error))
    owned = set(owned_paths)
    return {path: record for path, record in delta.items() if path not in owned}


def commit_changed_delta(runner, before_sha, after_sha):
    """The actual parent-to-commit changed delta. NUL-safe, renames disabled."""
    result = runner.run(
        "diff-tree",
        "-r",
        "--raw",
        "-z",
        "--no-renames",
        "--no-commit-id",
        before_sha,
        after_sha,
    )
    if not result.ok:
        raise CheckinError(
            COMMIT_TREE_UNREADABLE,
            "the change introduced by the completion commit could not be read.",
        )
    try:
        return _parse_raw_delta(result.nul_fields())
    except ValueError as error:
        raise CheckinError(COMMIT_TREE_UNREADABLE, str(error))


def parents(runner, commit):
    """The parent commit ids of `commit`, as a tuple of ASCII strings."""
    result = runner.run("rev-list", "--parents", "-n", "1", commit)
    if not result.ok or not result.lines():
        raise CheckinError(
            COMMIT_TREE_UNREADABLE,
            "the ancestry of the completion commit could not be read.",
        )
    fields = result.lines()[0].split()
    return tuple(field.decode("ascii", "replace") for field in fields[1:])


def committed_states(runner, commit, paths):
    """Actual committed state per owned path: {path: (kind, blob, mode)}."""
    entries = tree_entries(runner, commit, paths)
    states = {}
    for path in paths:
        entry = entries.get(path)
        if entry is None:
            states[path] = (ABSENT, None, None)
        else:
            states[path] = (REGULAR, entry["object"], entry["mode"])
    return states


def delta_record(delta):
    """A structured delta as a JSON-safe, order-independent record."""
    import base64

    return [
        {
            "path_b64": base64.b64encode(path).decode("ascii"),
            "src_mode": delta[path][0].decode("ascii", "replace"),
            "dst_mode": delta[path][1].decode("ascii", "replace"),
            "src_oid": delta[path][2].decode("ascii", "replace"),
            "dst_oid": delta[path][3].decode("ascii", "replace"),
            "status": delta[path][4].decode("ascii", "replace"),
        }
        for path in sorted(delta)
    ]


def delta_digest(delta):
    """One digest over a structured delta, binary-safe and order-independent."""
    import hashlib

    stream = bytearray(b"aiqe.foreign-staged-delta.v1\0")
    for path in sorted(delta):
        record = delta[path]
        _append(stream, path)
        for field in record:
            _append(stream, field)
    return "sha256:" + hashlib.sha256(bytes(stream)).hexdigest()


def _append(stream, field):
    stream += len(field).to_bytes(8, "big")
    stream += field
