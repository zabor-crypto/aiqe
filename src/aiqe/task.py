"""The task boundary: which repository paths this unit of work owns.

This is the smallest thing that later makes `check`, `receipt` and a bounded
commit possible, and it is deliberately not more than that. A task answers one
question:

    which repository paths does this AIQE task own?

It does not answer whether checks passed, whether evidence is fresh, whether
the work is reviewable, or whether it can be committed. Those are later
slices, and answering them early would mean inventing completion semantics
before the evidence that justifies them exists.

Three properties are load-bearing.

**A task works before init.** `aiqe doctor` then `aiqe task start` must work on
a repository AIQE has never seen. Nothing here reads or requires `aiqe.toml`.

**Scope is a declaration, not an observation.** An owned path need not exist:
declaring `src/new_module.py` before writing it is the normal case. Nothing
here consults the filesystem to decide what a declared path means.

**AIQE writes only its own state.** Starting, showing or ending a task must
not touch tracked files, untracked files, the index, refs, HEAD, hooks or Git
configuration. The proof is called `TASK_WRITE_CONFINEMENT`, and it is scoped
to AIQE's own writes: it is not a claim that nothing else on the machine can
change the repository while AIQE runs.
"""

import os
import time

from . import scope as scope_module
from . import taskstate
from .gitq import GitRunner
from .textsafe import display_bytes, display_text

#: Bump when a reader of an older record would misread a newer one. This is
#: local internal state, not a public integration surface.
SCHEMA_VERSION = 1

REPOSITORY_ABSENT = "REPOSITORY_ABSENT"
UNSUPPORTED_TOPOLOGY = "UNSUPPORTED_TOPOLOGY"
TASK_ALREADY_ACTIVE = "TASK_ALREADY_ACTIVE"
NO_ACTIVE_TASK = "NO_ACTIVE_TASK"
TASK_STARTED = "TASK_STARTED"
TASK_ACTIVE = "TASK_ACTIVE"
TASK_ENDED = "TASK_ENDED"
TASK_RECORD_DISCARDED = "TASK_RECORD_DISCARDED"


class TaskOutcome(object):
    """What an operation did, why, and what the process should exit with."""

    __slots__ = ("code", "exit_code", "lines", "record")

    def __init__(self, code, exit_code, lines, record=None):
        self.code = code
        self.exit_code = exit_code
        self.lines = lines
        self.record = record

    def render(self):
        return "\n".join(self.lines) + "\n"


class Repository(object):
    """The worktree a task operation applies to."""

    __slots__ = ("git_dir", "worktree", "cwd_components", "head_state", "head_sha")

    def __init__(self, git_dir, worktree, cwd_components, head_state, head_sha):
        self.git_dir = git_dir
        self.worktree = worktree
        self.cwd_components = cwd_components
        self.head_state = head_state
        self.head_sha = head_sha


# --- Repository discovery --------------------------------------------------


def discover(cwd, env=None):
    """Locate the worktree, its Git directory, and the HEAD state.

    Uses the same hardened Git runner Doctor uses, so a task operation cannot
    execute a hook, a filter, an fsmonitor or a maintenance process on the way
    to establishing where it is. Only discovery subcommands are needed: no
    worktree content is compared, so nothing here can trigger a filter driver.
    """
    runner = GitRunner(cwd, env=env)
    located = runner.run("rev-parse", "--git-dir", "--is-inside-work-tree")
    if not located.ok:
        return None, TaskOutcome(
            REPOSITORY_ABSENT,
            3,
            [
                "aiqe: no Git repository here.",
                "A task declares ownership of repository paths, so it needs a "
                "worktree to declare them in.",
            ],
        )

    lines = located.lines()
    if len(lines) != 2 or lines[1].strip() != b"true":
        return None, TaskOutcome(
            UNSUPPORTED_TOPOLOGY,
            3,
            [
                "aiqe: this location has no worktree.",
                "AIQE tasks are declared inside a worktree.",
            ],
        )

    base = os.fsencode(cwd)
    git_dir = _absolute(lines[0], base)

    toplevel = runner.run("rev-parse", "--show-toplevel")
    if not toplevel.ok or not toplevel.lines():
        return None, TaskOutcome(
            UNSUPPORTED_TOPOLOGY,
            3,
            ["aiqe: Git did not report a worktree root for this repository."],
        )
    worktree = _absolute(toplevel.lines()[0], base)

    head_sha = None
    head_state = "unborn"
    resolved = runner.run("rev-parse", "--verify", "--quiet", "HEAD")
    if resolved.ok and resolved.lines():
        head_state = "commit"
        head_sha = resolved.lines()[0].decode("ascii", "replace").strip()

    return (
        Repository(git_dir, worktree, _relative_components(base, worktree), head_state, head_sha),
        None,
    )


def _absolute(path_bytes, base):
    if not os.path.isabs(path_bytes):
        path_bytes = os.path.join(base, path_bytes)
    return os.path.normpath(path_bytes)


def _relative_components(cwd, worktree):
    """Where the command was invoked from, relative to the worktree root.

    Both paths come from the operating system and from Git already resolved,
    so this is a lexical comparison of two resolved paths - not a place where
    a symlink can change the answer.
    """
    cwd = os.path.normpath(cwd)
    worktree = os.path.normpath(worktree)
    if cwd == worktree:
        return []
    prefix = worktree + b"/"
    if not cwd.startswith(prefix):
        # Invoked outside the worktree Git reported. Treat the root as the
        # base rather than guessing at a relationship that does not exist.
        return []
    return [component for component in cwd[len(prefix):].split(b"/") if component]


# --- Lifecycle -------------------------------------------------------------


def start(cwd, owned, label=None, env=None):
    """Declare a new task. One active task per worktree."""
    repository, failure = discover(cwd, env)
    if failure is not None:
        return failure

    try:
        roots = scope_module.resolve(owned, repository.cwd_components)
    except scope_module.ScopeError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    try:
        with taskstate.TaskLock(repository.git_dir):
            existing = taskstate.read_active(repository.git_dir)
            if existing is not None:
                return TaskOutcome(
                    TASK_ALREADY_ACTIVE,
                    3,
                    [
                        "aiqe: a task is already active in this worktree.",
                        "End it with `aiqe task end` before starting another.",
                    ],
                )
            record = _build_record(repository, roots, label)
            taskstate.write_active(repository.git_dir, record)
    except taskstate.CorruptState as error:
        return _corrupt_outcome(error)
    except taskstate.StateError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    return TaskOutcome(TASK_STARTED, 0, _render(record, "started"), record)


def status(cwd, env=None):
    """Show the active task. Reads only; never creates or mutates state."""
    repository, failure = discover(cwd, env)
    if failure is not None:
        return failure

    try:
        record = taskstate.read_active(repository.git_dir)
    except taskstate.CorruptState as error:
        return _corrupt_outcome(error)
    except taskstate.StateError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    if record is None:
        return TaskOutcome(
            NO_ACTIVE_TASK,
            0,
            ["AIQE TASK", "", "  No active task in this worktree."],
        )
    return TaskOutcome(TASK_ACTIVE, 0, _render(record, "active"), record)


def end(cwd, env=None):
    """End the active task.

    An unreadable record is also cleared here, and that is the documented
    recovery path: `end` is the operation whose meaning is "there should be no
    active task", and leaving a repository permanently unable to start one
    would be a worse answer than removing a record nothing can read.
    """
    repository, failure = discover(cwd, env)
    if failure is not None:
        return failure

    try:
        with taskstate.TaskLock(repository.git_dir):
            try:
                record = taskstate.read_active(repository.git_dir)
            except taskstate.CorruptState:
                taskstate.clear_active(repository.git_dir)
                return TaskOutcome(
                    TASK_RECORD_DISCARDED,
                    0,
                    [
                        "AIQE TASK",
                        "",
                        "  Discarded an unreadable active task record.",
                        "  A new task can now be started in this worktree.",
                    ],
                )
            if record is None:
                return TaskOutcome(
                    NO_ACTIVE_TASK,
                    3,
                    ["aiqe: no active task in this worktree."],
                )
            taskstate.clear_active(repository.git_dir)
    except taskstate.StateError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    return TaskOutcome(TASK_ENDED, 0, _render(record, "ended"), record)


def _corrupt_outcome(error):
    return TaskOutcome(
        error.code,
        2,
        [
            "aiqe: " + error.message,
            "Run `aiqe task end` to discard it and start again.",
        ],
    )


# --- The record ------------------------------------------------------------


def _build_record(repository, roots, label):
    """The active task record.

    Deliberately absent: the worktree path, the remote URL, the repository
    owner or name, the hostname, the username and the email. None of them is
    needed to say which paths a task owns, and every one of them turns a local
    state file into something that identifies a person or a project if it is
    ever shared.

    Paths are stored base64-encoded, because the record is JSON and JSON is
    text: a path is bytes, and round-tripping it through a text encoding is
    exactly the kind of lossy step this product cannot afford.
    """
    from . import __version__

    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": _task_id(),
        "aiqe_version": __version__,
        "started_at": _timestamp(),
        "start_head_state": repository.head_state,
        "start_head_sha": repository.head_sha,
        "owned_scope": [{"path_b64": _encode(root)} for root in roots],
        "owned_scope_digest": scope_module.digest(roots),
        "label": label,
    }


def _task_id():
    """An opaque local identifier.

    Random, and nothing but random. It encodes no username, hostname,
    repository, branch or readable timestamp, so linking future local evidence
    to a task does not smuggle identity into whatever that evidence becomes.
    """
    return os.urandom(16).hex()


def _timestamp():
    """UTC, to the second, in a fixed format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _encode(raw):
    import base64

    return base64.b64encode(raw).decode("ascii")


def decode_scope(record):
    """The owned roots of a record, back as raw bytes."""
    import base64

    return [base64.b64decode(entry["path_b64"]) for entry in record["owned_scope"]]


# --- Rendering -------------------------------------------------------------


def _render(record, state):
    """Human output.

    Every user-controlled value - each owned path, the label - goes through
    the terminal-safe renderer. A repository can hold a filename containing an
    escape sequence, and the tool that reports what is in scope must not be
    the one that lets a filename draw a fake row.
    """
    roots = decode_scope(record)
    lines = ["AIQE TASK", ""]
    lines.append("  Task            %s" % (state,))
    lines.append("  Started         %s" % (record["started_at"],))
    if record.get("label"):
        lines.append("  Label           %s" % (display_text(record["label"]),))
    lines.append(
        "  Start HEAD      %s"
        % ("no commits yet" if record["start_head_state"] == "unborn" else "recorded",)
    )
    lines.append(
        "  Owned scope     %d %s"
        % (len(roots), "path" if len(roots) == 1 else "paths")
    )
    for root in roots:
        lines.append("      %s" % (display_bytes(root),))
    lines.append("  Scope digest    %s" % (record["owned_scope_digest"],))
    return lines
