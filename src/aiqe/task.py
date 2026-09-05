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

**Ownership is exact.** Owning `foo` owns `foo`, and nothing else - not
`foo/bar`, not `foobar`. There is no descendant ownership and no directory
scope in v1: a prefix rule would let a task authorise files that did not exist
when the scope was declared, which is the thing an owned scope exists to
bound.

**A declaration is not an observation.** An owned path need not exist:
declaring `src/new_module.py` before writing it is the normal case. The
filesystem is consulted for one thing only - refusing a path that exists today
as a directory, which has no meaning under exact ownership.

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
SCHEMA_VERSION = taskstate.SUPPORTED_SCHEMA_VERSION

#: Recorded in every task, so a reader never has to infer from the version
#: number alone what a declared path meant.
OWNERSHIP_SEMANTICS = "exact_literal_pathset_v1"

REPOSITORY_ABSENT = "REPOSITORY_ABSENT"
UNSUPPORTED_TOPOLOGY = "UNSUPPORTED_TOPOLOGY"
UNBORN_HEAD_UNSUPPORTED = "UNBORN_HEAD_UNSUPPORTED"
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

    __slots__ = (
        "git_dir",
        "common_dir",
        "worktree",
        "cwd_components",
        "head_state",
        "head_sha",
        "runner",
    )

    def __init__(
        self, git_dir, common_dir, worktree, cwd_components, head_state, head_sha, runner
    ):
        self.git_dir = git_dir
        self.common_dir = common_dir
        self.worktree = worktree
        self.cwd_components = cwd_components
        self.head_state = head_state
        self.head_sha = head_sha
        self.runner = runner


# --- Repository discovery --------------------------------------------------


def discover(cwd, env=None):
    """Locate the worktree, its Git directory, and the HEAD state.

    Uses the same hardened Git runner Doctor uses, so a task operation cannot
    execute a hook, a filter, an fsmonitor or a maintenance process on the way
    to establishing where it is. Only discovery subcommands are needed: no
    worktree content is compared, so nothing here can trigger a filter driver.
    """
    runner = GitRunner(cwd, env=env)
    located = runner.run(
        "rev-parse", "--git-dir", "--git-common-dir", "--is-inside-work-tree"
    )
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
    if len(lines) != 3 or lines[2].strip() != b"true":
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
    common_dir = _absolute(lines[1], base)

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
        Repository(
            git_dir,
            common_dir,
            worktree,
            _relative_components(base, worktree),
            head_state,
            head_sha,
            runner,
        ),
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

    if repository.head_state != "commit":
        # A task's completion baseline is the commit it started from. Without
        # a parent there is nothing for later evidence to be relative to, so
        # the task is refused rather than started against nothing. Doctor
        # still works here; this rule is about starting a task.
        return TaskOutcome(
            UNBORN_HEAD_UNSUPPORTED,
            3,
            [
                "aiqe: this repository has no commits yet.",
                "A task records the commit it started from, so make the first "
                "commit before starting one.",
            ],
        )

    try:
        owned_paths = scope_module.resolve(owned, repository.cwd_components)
        scope_module.validate_paths(owned_paths, repository.worktree)
    except scope_module.ScopeError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    staged = _foreign_staged_count(repository)

    try:
        # The first write is what creates the machine-local salt. Everything
        # before this point - discovery, validation, refusals - leaves the
        # filesystem exactly as it was found.
        salt = taskstate.ensure_salt(env)
        key = taskstate.derive_key(salt, repository.common_dir, repository.git_dir)
        state_directory = taskstate.ensure_state_directory(key, env)

        with taskstate.TaskLock(state_directory):
            existing = taskstate.read_active(state_directory)
            if existing is not None:
                return TaskOutcome(
                    TASK_ALREADY_ACTIVE,
                    3,
                    [
                        "aiqe: a task is already active in this worktree.",
                        "End it with `aiqe task end` before starting another.",
                    ],
                )
            record = _build_record(repository, owned_paths, label, staged)
            taskstate.write_active(state_directory, record)
            # Evidence belongs to a task. A record left behind by a task that
            # ended badly must not be inherited by this one, so it goes now
            # rather than being ignored later on a technicality.
            _discard_check_evidence(state_directory)
    except taskstate.CorruptState as error:
        return _corrupt_outcome(error)
    except taskstate.StateError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    lines = _render(record, "started")
    lines.extend(_glob_shape_warning(owned_paths, repository.worktree))
    return TaskOutcome(TASK_STARTED, 0, lines, record)


def status(cwd, env=None):
    """Show the active task. Reads only; never creates or mutates state."""
    repository, failure = discover(cwd, env)
    if failure is not None:
        return failure

    try:
        record = taskstate.read_active(_existing_state_directory(repository, env))
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
        state_directory = _existing_state_directory(repository, env)
        if state_directory is None:
            return TaskOutcome(
                NO_ACTIVE_TASK, 3, ["aiqe: no active task in this worktree."]
            )
        with taskstate.TaskLock(state_directory):
            try:
                record = taskstate.read_active(state_directory)
            except taskstate.CorruptState as error:
                # The record is present and this build will not interpret it -
                # whether because it is malformed or because it was written
                # under different ownership semantics. Either way `end` is the
                # operation that means "there should be no active task", and
                # saying which of the two it was is more useful than a generic
                # line.
                taskstate.clear_active(state_directory)
                _discard_check_evidence(state_directory)
                return TaskOutcome(
                    TASK_RECORD_DISCARDED,
                    0,
                    [
                        "AIQE TASK",
                        "",
                        "  Discarded an active task record this build cannot",
                        "  interpret: " + error.message,
                        "  A new task can now be started in this worktree.",
                    ],
                )
            if record is None:
                return TaskOutcome(
                    NO_ACTIVE_TASK,
                    3,
                    ["aiqe: no active task in this worktree."],
                )
            taskstate.clear_active(state_directory)
            _discard_check_evidence(state_directory)
    except taskstate.StateError as error:
        return TaskOutcome(error.code, 3, ["aiqe: " + error.message])

    return TaskOutcome(TASK_ENDED, 0, _render(record, "ended"), record)


def _discard_check_evidence(state_directory):
    """Remove the active task's check and completion-commit evidence.

    Completion evidence is *about* a task. When the task is gone the evidence
    describes nothing, and keeping it would be the first row of the evidence
    history this product does not build. A new task must not inherit either
    record: reusing a previous task's commit evidence would let a fresh task
    claim a completion commit it never made. Recorded validator consent is
    deliberately not touched: consenting to run a command is a statement about
    that command, not about one unit of work.

    This is the whole of the task lifecycle's knowledge of evidence. Task Core
    semantics, its record and its schema are unchanged.
    """
    from . import commitevidence
    from . import evidence

    for module in (evidence, commitevidence):
        try:
            module.remove(state_directory)
        except taskstate.StateError:
            # Ending a task must not be blocked by the removal of a file that
            # is already unreadable. The record itself is gone, which is what
            # `end` promises.
            pass


def _existing_state_directory(repository, env):
    """This worktree's machine-local state directory, if one exists.

    Read-only throughout. When no salt has ever been created there can be no
    state, so the answer is None and nothing is written to find that out.
    """
    salt = taskstate.read_salt(env)
    if salt is None:
        return None
    key = taskstate.derive_key(salt, repository.common_dir, repository.git_dir)
    return taskstate.worktree_state_directory(key, env)


def _foreign_staged_count(repository):
    """How many entries are staged when the task starts.

    Informational, and local only. It is *not* the foreign-staged guarantee:
    the load-bearing before-and-after comparison that decides whether a
    bounded commit excluded foreign staged work belongs to `aiqe commit`, and
    recording a number here does not make that comparison.

    Obtained with `diff-index --cached`, which compares the index against HEAD
    and reads no worktree content - so it cannot refresh the index and cannot
    trigger a filter driver. Filenames are counted, never stored.
    """
    result = repository.runner.run(
        "diff-index", "--cached", "--name-only", "-z", "HEAD"
    )
    if not result.ok:
        return None
    return len(result.nul_fields())


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


def _build_record(repository, owned_paths, label, foreign_staged_count):
    """The active task record.

    Deliberately absent: the worktree path, the Git directory, the remote URL,
    the repository owner or name, the hostname, the username and the email.
    None of them is needed to say which paths a task owns, and every one turns
    a local state file into something that identifies a person or a project if
    it is ever shared. The canonical Git paths are inputs to the machine-local
    lookup key and are not stored anywhere.

    Paths are stored base64-encoded, because the record is JSON and JSON is
    text: a path is bytes, and round-tripping it through a text encoding is
    exactly the kind of lossy step this product cannot afford.
    """
    from . import __version__

    return {
        "schema_version": SCHEMA_VERSION,
        "ownership_semantics": OWNERSHIP_SEMANTICS,
        "task_id": _task_id(),
        "aiqe_version": __version__,
        "started_at": _timestamp(),
        "start_head_sha": repository.head_sha,
        "owned_paths": [{"path_b64": _encode(path)} for path in owned_paths],
        "owned_pathset_digest": scope_module.digest(owned_paths),
        "foreign_staged_count_at_start": foreign_staged_count,
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


def decode_owned_paths(record):
    """The owned pathset of a record, back as raw bytes."""
    import base64

    return [base64.b64decode(entry["path_b64"]) for entry in record["owned_paths"]]


# --- Rendering -------------------------------------------------------------


def _glob_shape_warning(owned_paths, worktree):
    """Warn at declaration time about a glob-shaped path that names no file.

    This is a courtesy, not the control. The control is in `aiqe check`, which
    refuses outright once such a declaration is demonstrably letting a changed
    file escape ownership - a warning printed at the top of a session is not
    something a later green result can be allowed to depend on anyone having
    read.

    Started as a warning rather than a refusal because the declaration may be
    entirely correct: `notes[1].md` is a legal filename, and declaring a path
    before creating it is the ordinary case.
    """
    shaped = [
        path
        for path in owned_paths
        if scope_module.is_glob_shaped(path)
        and not os.path.lexists(os.path.join(worktree, path))
    ]
    if not shaped:
        return []

    lines = ["", "  Note            these declared paths name no file yet and"]
    lines.append("                  contain pattern characters:")
    for path in shaped:
        lines.append("      %s" % (display_bytes(path),))
    lines.extend(
        [
            "",
            "  `--own` takes literal paths and never expands one, so each is",
            "  owned exactly as spelled. If you meant several files, declare",
            "  each of them; `aiqe check` refuses rather than reporting a",
            "  green result while a file this would have matched changes",
            "  outside the owned pathset.",
        ]
    )
    return lines


def _render(record, state):
    """Human output.

    Every user-controlled value - each owned path, the label - goes through
    the terminal-safe renderer. A repository can hold a filename containing an
    escape sequence, and the tool that reports what is in scope must not be
    the one that lets a filename draw a fake row.
    """
    owned_paths = decode_owned_paths(record)
    lines = ["AIQE TASK", ""]
    lines.append("  Task            %s" % (state,))
    lines.append("  Started         %s" % (record["started_at"],))
    if record.get("label"):
        lines.append("  Label           %s" % (display_text(record["label"]),))
    lines.append("  Start HEAD      recorded")
    staged = record.get("foreign_staged_count_at_start")
    lines.append(
        "  Staged at start %s"
        % ("unknown" if staged is None else "%d entries (informational)" % (staged,),)
    )
    lines.append(
        "  Owned pathset   %d exact %s"
        % (len(owned_paths), "path" if len(owned_paths) == 1 else "paths")
    )
    for path in owned_paths:
        lines.append("      %s" % (display_bytes(path),))
    lines.append("  Pathset digest  %s" % (record["owned_pathset_digest"],))
    return lines
