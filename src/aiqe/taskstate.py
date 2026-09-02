"""Where a task lives on disk, and how it is written safely.

Task state is deliberately local, private and worktree-specific:

    <worktree git directory>/aiqe/task.json    the active task, if any
    <worktree git directory>/aiqe/task.lock    the start/end mutex

Not `$HOME`, not an XDG directory, not the tracked worktree, and not the
*common* Git directory. That last one is the subtle part. A linked worktree
has its own Git directory under `…/.git/worktrees/<name>` while sharing the
common one, so putting task state in the common directory would give two
worktrees one task between them. They get one each.

Nothing here writes to anything Git owns. The state directory sits beside
Git's files rather than among them: no config, no index, no refs, no hooks.

Two failure modes are handled deliberately.

**Unsafe state location.** If `…/aiqe` or `task.json` already exists as
something other than the expected kind - a symlink, a directory where a file
belongs - AIQE refuses rather than following it. Writing through a symlink
planted in a repository would put AIQE's own writes somewhere it never
promised to write. The check is a narrow `lstat`, not a general defence
against hostile Git metadata.

**A crash mid-write.** Every state transition is a write to a temporary file
in the same directory, an fsync, and an atomic `rename`. A reader sees either
the old state or the new one, never half of either, and a process killed
between the two leaves the old state intact.
"""

import errno
import fcntl
import json
import os
import stat as stat_module
import time

STATE_DIRECTORY_NAME = b"aiqe"
ACTIVE_TASK_NAME = b"task.json"
LOCK_NAME = b"task.lock"

#: How long `task start` waits for another AIQE process to finish before
#: refusing. Bounded rather than indefinite: a command that hangs forever
#: because some other process is wedged is its own kind of failure.
LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.02

STATE_DIRECTORY_UNSAFE = "STATE_DIRECTORY_UNSAFE"
STATE_UNREADABLE = "STATE_UNREADABLE"
STATE_LOCK_UNAVAILABLE = "STATE_LOCK_UNAVAILABLE"


class StateError(Exception):
    """AIQE's own state area is unusable. `code` is the machine identity."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class CorruptState(StateError):
    """An active task record exists but cannot be read as one.

    Distinguished from the other state errors because it means "unknown", not
    "unsupported": something is there, and AIQE will not guess what.
    """


def state_directory(git_dir):
    return os.path.join(git_dir, STATE_DIRECTORY_NAME)


def active_task_path(git_dir):
    return os.path.join(state_directory(git_dir), ACTIVE_TASK_NAME)


def _lock_path(git_dir):
    return os.path.join(state_directory(git_dir), LOCK_NAME)


def _require_directory(path):
    """The state directory must be a real directory, or absent."""
    try:
        stat = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "AIQE state directory cannot be inspected: %s" % (exc.strerror,),
        )
    if not stat_module.S_ISDIR(stat.st_mode):
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "AIQE state location exists but is not a directory; refusing to "
            "write through it",
        )
    return True


def _require_regular_file(path):
    """The active task record must be a real file, or absent."""
    try:
        stat = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "AIQE task record cannot be inspected: %s" % (exc.strerror,),
        )
    if not stat_module.S_ISREG(stat.st_mode):
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "AIQE task record exists but is not a regular file; refusing to "
            "write through it",
        )
    return True


def ensure_state_directory(git_dir):
    """Create the state directory if needed, refusing an unsafe one."""
    directory = state_directory(git_dir)
    if not _require_directory(directory):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            # Another AIQE process created it between the check and the
            # attempt. Re-check rather than assume it is the right kind.
            _require_directory(directory)
        except OSError as exc:
            raise StateError(
                STATE_DIRECTORY_UNSAFE,
                "AIQE state directory could not be created: %s" % (exc.strerror,),
            )
    return directory


def read_active(git_dir):
    """The active task record, or None. Never mutates anything.

    `aiqe task` is a read. It creates no directory, takes no lock and writes
    no file, because a status command that changes state is a status command
    nobody can trust.
    """
    path = active_task_path(git_dir)
    if not _require_regular_file(path):
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE, "AIQE task record could not be read: %s" % (exc.strerror,)
        )

    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorruptState(
            STATE_UNREADABLE,
            "the active AIQE task record is not valid JSON (%s). It was not "
            "written by a completed AIQE operation." % (exc,),
        )
    if not isinstance(record, dict) or "schema_version" not in record:
        raise CorruptState(
            STATE_UNREADABLE,
            "the active AIQE task record is not an AIQE task record",
        )
    return record


def write_active(git_dir, record):
    """Replace the active task record atomically."""
    directory = ensure_state_directory(git_dir)
    path = active_task_path(git_dir)
    _require_regular_file(path)
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_replace(directory, path, payload)


def clear_active(git_dir):
    """Remove the active task record atomically.

    Unlink is atomic from a reader's point of view: the record is either there
    or it is not.

    AIQE keeps no ended-task record. Retaining one would be the first row of a
    task history database, which is explicitly out of scope, and nothing in
    this slice reads it. Completion evidence belongs to receipts, which are
    artifacts in their own right, not a side effect of ending a task.
    """
    path = active_task_path(git_dir)
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE,
            "AIQE task record could not be removed: %s" % (exc.strerror,),
        )
    _sync_directory(state_directory(git_dir))
    return True


def _atomic_replace(directory, path, payload):
    temporary = os.path.join(
        directory, b".task.json.tmp." + str(os.getpid()).encode("ascii")
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, payload)
        # Durable before it is visible: a rename that beats its own contents to
        # disk is exactly the half-written state this is here to prevent.
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _sync_directory(directory)


def _sync_directory(directory):
    """Persist the rename itself, not only the bytes it points at."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class TaskLock(object):
    """Exclusive lock over start and end in one worktree.

    An advisory `flock` on a file in the state directory. It is per-worktree,
    because the state directory is, so two linked worktrees never contend.
    The kernel releases it if the process dies, so a crash cannot wedge a
    repository.

    Deliberately not: a daemon, a lock service, a lease, or anything
    distributed. One machine, one worktree, one active task.
    """

    def __init__(self, git_dir, timeout=LOCK_TIMEOUT_SECONDS):
        self._git_dir = git_dir
        self._timeout = timeout
        self._descriptor = None

    def __enter__(self):
        ensure_state_directory(self._git_dir)
        path = _lock_path(self._git_dir)
        self._descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.time() + self._timeout
        while True:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(self._descriptor)
                    self._descriptor = None
                    raise StateError(
                        STATE_LOCK_UNAVAILABLE,
                        "AIQE task lock could not be taken: %s" % (exc.strerror,),
                    )
            if time.time() >= deadline:
                os.close(self._descriptor)
                self._descriptor = None
                raise StateError(
                    STATE_LOCK_UNAVAILABLE,
                    "another AIQE task operation is in progress in this "
                    "worktree",
                )
            time.sleep(_LOCK_POLL_SECONDS)

    def __exit__(self, exc_type, exc_value, traceback):
        if self._descriptor is not None:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._descriptor)
                self._descriptor = None
        return False
