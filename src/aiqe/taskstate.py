"""Where a task lives on disk, and how it is written safely.

Task state is machine-local, and deliberately nowhere near the repository:

    $XDG_STATE_HOME/aiqe/salt              32 random bytes, mode 0600
    $XDG_STATE_HOME/aiqe/<key>/task.json   the active task, if any
    $XDG_STATE_HOME/aiqe/<key>/task.lock   the start/end mutex

When `XDG_STATE_HOME` is unset the conventional Unix fallback applies:
`~/.local/state`.

Nothing goes inside `.git`. Not the worktree Git directory, not the common
one, not the index, not the configuration. A tool whose claim is that it does
not touch your repository should not keep its own filing cabinet inside it,
and state written there would also be state a `git clean` or a fresh clone
silently disagrees with.

**The lookup key names no repository.** The directory under `aiqe/` is

    HMAC-SHA256(salt, canonical common-dir || 0x00 || canonical git-dir)

rendered as hex. The paths are inputs only: they are never stored. Without the
machine-local salt the key reveals nothing about which repository it belongs
to, which is what keeps a state directory listing - and any future receipt -
free of a project inventory. Including the per-worktree Git directory as well
as the common one is what gives two linked worktrees two distinct keys, and
therefore two independent tasks.

**The salt is created on the first write, never on a read.** `aiqe doctor`
creates nothing. `aiqe task`, with no salt and no state, answers that there is
no active task and leaves the filesystem exactly as it found it.

Two failure modes are handled deliberately.

**Unsafe state location.** AIQE creates its own state private - directories
0700, files 0600 - but creating it privately is only half the job. State that
is *already there* is state somebody else may have put there, and AIQE has no
way to tell a file it wrote last week from one that was placed for it to find.

So every AIQE-managed component that is actually used is validated before it
is read or written:

```
directories   a real directory, not a symlink, owned by this user,
              with no group or world permission bits
files         a regular file, not a symlink, owned by this user, mode 0600
```

Anything else is `LOCAL_STATE_UNSAFE`, and the operation refuses - exit 3, no
validator executed, and recorded consent not trusted. Consent is the reason
this matters most: a `consents.json` somebody else can write is a list of
commands somebody else can get executed as you, and reading it under the
assumption that AIQE wrote it would be the whole authorization boundary
undone by a file mode.

AIQE does not repair what it finds. It does not `chmod`, does not `chown`,
does not replace the file, and does not follow the symlink to see what is on
the other side - every one of those is an action taken on a path AIQE has
already decided it cannot trust, and a tool that "fixes" a hostile symlink by
writing through it has done the attacker's work. The user is told what is
wrong and left to decide.

This is deliberately not a general local-security framework. It validates
AIQE's own managed components and nothing else: the parent directories above
`$XDG_STATE_HOME`, the home directory, and the rest of the machine are the
operating system's business, and pretending otherwise would be a claim AIQE
cannot keep.

**A crash mid-write.** Every state transition is a write to a temporary file
in the same directory, an fsync, and an atomic rename. A reader sees either
the old state or the new one, never half of either.
"""

import errno
import fcntl
import hashlib
import hmac
import json
import os
import stat as stat_module
import time

#: The only record shape this build interprets.
#:
#: Earlier versions recorded a different ownership meaning and a different
#: state location. Reading one of those under today's semantics would say
#: something untrue about a live task, so they are refused rather than
#: reinterpreted. There is no migration, by design: this is local pre-release
#: state, and a migration framework for it would be machinery in place of a
#: sentence telling the user to end the task and start it again.
SUPPORTED_SCHEMA_VERSION = 3

#: Bytes of randomness in the machine-local salt.
SALT_BYTES = 32

#: The salt is readable by its owner alone. It is the only thing standing
#: between a state directory listing and a list of the repositories on this
#: machine.
SALT_MODE = 0o600

#: Every AIQE-managed local state file, created and required at this mode.
PRIVATE_FILE_MODE = 0o600
STATE_DIRECTORY_MODE = 0o700

STATE_ROOT_NAME = "aiqe"
SALT_NAME = "salt"
ACTIVE_TASK_NAME = "task.json"
LOCK_NAME = "task.lock"

#: How long `task start` waits for another AIQE process to finish before
#: refusing. Bounded rather than indefinite: a command that hangs forever
#: because some other process is wedged is its own kind of failure.
LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.02

#: An AIQE-managed component that already exists but is outside the trust
#: boundary above: wrong kind, wrong owner, or readable by anyone else.
LOCAL_STATE_UNSAFE = "LOCAL_STATE_UNSAFE"

STATE_DIRECTORY_UNSAFE = "STATE_DIRECTORY_UNSAFE"
STATE_UNREADABLE = "STATE_UNREADABLE"
STATE_LOCK_UNAVAILABLE = "STATE_LOCK_UNAVAILABLE"
TASK_STATE_SCHEMA_UNSUPPORTED = "TASK_STATE_SCHEMA_UNSUPPORTED"


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


class UnsupportedSchema(CorruptState):
    """An active record written by a build whose meaning differs from this one.

    A subclass of `CorruptState` because the consequence is identical - a
    record is present and this build will not interpret it - and because
    `task end` should discard it by the same route.
    """


# --- Locating machine-local state ------------------------------------------


def state_root(env=None):
    """`$XDG_STATE_HOME/aiqe`, or the conventional fallback beneath `$HOME`."""
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME")
    if not base:
        home = env.get("HOME")
        if not home:
            raise StateError(
                STATE_DIRECTORY_UNSAFE,
                "neither XDG_STATE_HOME nor HOME is set, so AIQE cannot "
                "locate machine-local state",
            )
        base = os.path.join(home, ".local", "state")
    root = os.path.join(base, STATE_ROOT_NAME)
    # Validated on every resolution rather than only before a write. This is
    # the one path every other component hangs off, and a read is exactly the
    # operation an unsafe root would be used to influence.
    _require_directory(root, "state root")
    return root


def salt_path(env=None):
    return os.path.join(state_root(env), SALT_NAME)


def read_salt(env=None):
    """The machine-local salt, or None when it has never been created.

    Reading never creates it. That is what lets `aiqe task` answer on a
    machine AIQE has never written to without becoming a machine AIQE has
    written to.
    """
    path = salt_path(env)
    if not _require_regular_file(path, "machine-local salt"):
        return None
    try:
        with open(path, "rb") as handle:
            salt = handle.read()
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE,
            "the AIQE machine-local salt could not be read: %s" % (exc.strerror,),
        )
    if len(salt) != SALT_BYTES:
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "the AIQE machine-local salt is not %d bytes; refusing to derive "
            "state locations from it" % (SALT_BYTES,),
        )
    return salt


def ensure_salt(env=None):
    """The machine-local salt, creating it once if it does not exist.

    Called only on a write path. Creation is a link into place, which is
    atomic and fails rather than overwrites: two processes racing to be the
    first ever writer both end up using the salt that won, never two salts.
    A crash mid-write leaves a temporary file that was never linked, not a
    short salt that would silently change every derived key.
    """
    existing = read_salt(env)
    if existing is not None:
        return existing

    root = _ensure_directory(state_root(env))
    final = os.path.join(root, SALT_NAME)
    temporary = os.path.join(
        root, ".%s.tmp.%d" % (SALT_NAME, os.getpid())
    )

    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SALT_MODE)
    try:
        os.write(descriptor, os.urandom(SALT_BYTES))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    try:
        os.link(temporary, final)
    except FileExistsError:
        # Another process got there first. Its salt is the canonical one.
        pass
    except OSError as exc:
        os.unlink(temporary)
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "the AIQE machine-local salt could not be created: %s" % (exc.strerror,),
        )
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    _sync_directory(root)

    salt = read_salt(env)
    if salt is None:
        raise StateError(
            STATE_DIRECTORY_UNSAFE,
            "the AIQE machine-local salt disappeared immediately after "
            "creation",
        )
    return salt


def derive_key(salt, common_dir, git_dir):
    """The machine-local directory token for one worktree.

    HMAC over the canonical common Git directory and the canonical
    per-worktree Git directory, NUL-separated. NUL is a safe separator because
    a POSIX path cannot contain one, so no two different pairs of paths can
    produce the same input string.

    Both are included on purpose. The common directory alone would give every
    linked worktree of a repository the same key, and therefore one task
    between them.
    """
    message = _canonical(common_dir) + b"\0" + _canonical(git_dir)
    return hmac.new(salt, message, hashlib.sha256).hexdigest()


def _canonical(path_bytes):
    if not isinstance(path_bytes, bytes):
        path_bytes = os.fsencode(path_bytes)
    try:
        return os.path.realpath(path_bytes)
    except OSError:
        return os.path.normpath(path_bytes)


def worktree_state_directory(key, env=None):
    directory = os.path.join(state_root(env), key)
    _require_directory(directory, "state directory for this worktree")
    return directory


def active_task_path(state_directory):
    return os.path.join(state_directory, ACTIVE_TASK_NAME)


# --- Filesystem safety -----------------------------------------------------


def _inspect(path, what):
    """`lstat` an AIQE-managed component, or None if it is not there.

    `lstat`, never `stat`: a symlink is refused as a symlink. Following one to
    find out what it points at is already acting on a path AIQE has decided it
    cannot trust.
    """
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s could not be inspected: %s. AIQE will not use local "
            "state it cannot check." % (what, exc.strerror),
        )


def _require_owner(stat, what):
    """The component must belong to whoever is running AIQE.

    A state file owned by someone else is a state file someone else can
    rewrite, and recorded consent is a list of commands that would then be
    executed as this user.
    """
    if not hasattr(os, "getuid"):
        return
    if stat.st_uid != os.getuid():
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s is owned by another user (uid %d). AIQE will not "
            "read or write local state it does not own, and will not change "
            "its ownership." % (what, stat.st_uid),
        )


def _require_directory(path, what="state directory"):
    """A real, private, owned directory - or nothing at all.

    Returns whether it exists. Raises `StateError` when it exists and is
    outside the trust boundary.
    """
    stat = _inspect(path, what)
    if stat is None:
        return False

    if stat_module.S_ISLNK(stat.st_mode):
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s is a symbolic link. AIQE does not follow a link out "
            "of its own state area, and does not replace it." % (what,),
        )
    if not stat_module.S_ISDIR(stat.st_mode):
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s exists but is not a directory; refusing to write "
            "through it." % (what,),
        )
    _require_owner(stat, what)

    mode = stat_module.S_IMODE(stat.st_mode)
    if mode & 0o077:
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s is mode %04o, which grants access beyond its owner. "
            "AIQE creates it 0700 and will not silently tighten one it did "
            "not create - `chmod 700` it, or remove it." % (what, mode),
        )
    return True


def _require_regular_file(path, what="local state file"):
    """A real, private, owned regular file - or nothing at all.

    Returns whether it exists. Raises `StateError` when it exists and is
    outside the trust boundary.
    """
    stat = _inspect(path, what)
    if stat is None:
        return False

    if stat_module.S_ISLNK(stat.st_mode):
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s is a symbolic link. AIQE does not write through a "
            "link out of its own state area, and does not replace it."
            % (what,),
        )
    if not stat_module.S_ISREG(stat.st_mode):
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s exists but is not a regular file; refusing to write "
            "through it." % (what,),
        )
    _require_owner(stat, what)

    mode = stat_module.S_IMODE(stat.st_mode)
    if mode != PRIVATE_FILE_MODE:
        raise StateError(
            LOCAL_STATE_UNSAFE,
            "the AIQE %s is mode %04o, and AIQE only reads or writes local "
            "state at mode %04o. It will not change the mode for you: a "
            "record anyone else can write is not evidence, and recorded "
            "consent anyone else can write is a list of commands they can "
            "have run as you." % (what, mode, PRIVATE_FILE_MODE),
        )
    return True


def _ensure_directory(path):
    if not _require_directory(path):
        try:
            os.makedirs(path, STATE_DIRECTORY_MODE)
        except FileExistsError:
            _require_directory(path)
        except OSError as exc:
            raise StateError(
                STATE_DIRECTORY_UNSAFE,
                "AIQE state directory could not be created: %s" % (exc.strerror,),
            )
    return path


def ensure_state_directory(key, env=None):
    _ensure_directory(state_root(env))
    return _ensure_directory(worktree_state_directory(key, env))


# --- Reading and writing the active task -----------------------------------


def read_active(state_directory):
    """The active task record, or None. Never mutates anything.

    `aiqe task` is a read. It creates no directory, takes no lock and writes
    no file, because a status command that changes state is a status command
    nobody can trust.
    """
    if state_directory is None:
        return None
    path = active_task_path(state_directory)
    if not _require_regular_file(path, "task record"):
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
    if record["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedSchema(
            TASK_STATE_SCHEMA_UNSUPPORTED,
            "the active AIQE task record uses state schema version %r, and "
            "this build interprets version %d. Task state meant something "
            "different in an earlier schema, so the record is refused rather "
            "than reinterpreted."
            % (record["schema_version"], SUPPORTED_SCHEMA_VERSION),
        )
    return record


def write_active(state_directory, record):
    """Replace the active task record atomically."""
    _ensure_directory(state_directory)
    path = active_task_path(state_directory)
    _require_regular_file(path, "task record")
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_replace(state_directory, path, payload)


def clear_active(state_directory):
    """Remove the active task record atomically.

    Unlink is atomic from a reader's point of view: the record is either there
    or it is not.

    AIQE keeps no ended-task record. Retaining one would be the first row of a
    task history database, which is explicitly out of scope, and nothing in
    this slice reads it. Completion evidence belongs to receipts, which are
    artifacts in their own right, not a side effect of ending a task.
    """
    path = active_task_path(state_directory)
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE,
            "AIQE task record could not be removed: %s" % (exc.strerror,),
        )
    _sync_directory(state_directory)
    return True


def write_local_file(state_directory, name, payload):
    """Replace one machine-local state file atomically.

    The same temporary-file, fsync and rename path the active task record
    uses. It is here rather than in each caller because every file AIQE keeps
    beside the task - recorded consent, current check evidence - has the same
    requirement: a reader sees the old bytes or the new ones, never half of
    either, and a crash mid-write loses at most the newest write.

    This is the whole of the Task Core integration the later lifecycle
    surfaces needed. It adds no task semantics and does not touch the task
    record's schema.
    """
    _ensure_directory(state_directory)
    path = os.path.join(state_directory, name)
    _require_regular_file(path, name)
    _atomic_replace(state_directory, path, payload, name)
    return path


def read_local_file(state_directory, name):
    """One machine-local state file's bytes, or None. Never mutates anything."""
    if state_directory is None:
        return None
    path = os.path.join(state_directory, name)
    if not _require_regular_file(path, name):
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE,
            "AIQE local state file could not be read: %s" % (exc.strerror,),
        )


def remove_local_file(state_directory, name):
    """Remove one machine-local state file. Returns whether it was there.

    Validated first, and for the same reason as everywhere else: removing a
    symlink AIQE found in its state area removes the link, but acting on
    unvalidated state at all is the habit worth not having.
    """
    if state_directory is None:
        return False
    path = os.path.join(state_directory, name)
    _require_regular_file(path, name)
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError(
            STATE_UNREADABLE,
            "AIQE local state file could not be removed: %s" % (exc.strerror,),
        )
    _sync_directory(state_directory)
    return True


def _atomic_replace(directory, path, payload, name=ACTIVE_TASK_NAME):
    temporary = os.path.join(directory, ".%s.tmp.%d" % (name, os.getpid()))
    # `O_EXCL` as well as `O_CREAT`: a temporary name that already exists is
    # something AIQE did not create, and truncating through it would be
    # writing to a path it has not validated. A leftover from a crashed
    # process of the same pid is cleared first, deliberately and by name.
    _clear_stale_temporary(temporary)
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE
    )
    try:
        os.write(descriptor, payload)
        # Durable before it is visible: a rename that beats its own contents to
        # disk is exactly the half-written state this is here to prevent.
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _sync_directory(directory)


def _clear_stale_temporary(path):
    """Remove a leftover temporary of AIQE's own naming, if it is safe to.

    Its name contains this process's pid, so anything at that path is either
    debris from a crash of a previous process that had the same pid, or
    something placed there. The first is removable; the second is refused by
    the same rules as every other component rather than written through.
    """
    if _require_regular_file(path, "temporary state file"):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise StateError(
                LOCAL_STATE_UNSAFE,
                "a leftover AIQE temporary file could not be removed: %s"
                % (exc.strerror,),
            )


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
    """Exclusive lock over start and end for one worktree.

    An advisory `flock` on a file in that worktree's machine-local state
    directory. It is per-worktree because the directory is, so two linked
    worktrees never contend. The kernel releases it if the process dies, so a
    crash cannot wedge anything.

    Deliberately not: a daemon, a lock service, a lease, or anything
    distributed. One machine, one worktree, one active task.
    """

    def __init__(self, state_directory, timeout=LOCK_TIMEOUT_SECONDS):
        self._state_directory = state_directory
        self._timeout = timeout
        self._descriptor = None

    def __enter__(self):
        _ensure_directory(self._state_directory)
        path = os.path.join(self._state_directory, LOCK_NAME)
        _require_regular_file(path, LOCK_NAME)
        self._descriptor = os.open(path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE_MODE)
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
                    "another AIQE task operation is in progress for this "
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
