"""Shared measurement primitives for the AIQE benchmark families.

A claim about what a program does not do cannot be established by asking the
program. So every family measures from outside: a byte-level snapshot of the
whole isolated case directory before and after the operation under test, with
content hashes, sizes, modes and modification times compared.

What lives here is only the machinery that is genuinely common - the isolated
case directory and environment, the canary markers, the quiescence guard and
the snapshot comparison. What counts as an allowed change differs by family
and stays with the family: Doctor may change nothing, while a task operation
may change AIQE's own private state and nothing else.

The environment is isolated so the numbers mean something. HOME, the XDG
directories and the global Git configuration all point inside the case
directory, and system Git configuration is switched off, so a fixture cannot
reach the developer's real configuration and a write to the developer's real
state directory could not go unseen.
"""

import hashlib
import os
import stat as stat_module
import time


class Case(object):
    """One fixture, its isolated directories and its isolated environment."""

    def __init__(self, case_id, root, repository_dirs=("repo",)):
        self.case_id = case_id
        self.root = root
        #: Top-level directories under the case root that are repositories
        #: under measurement. Each family names its own.
        self.repository_dirs = tuple(repository_dirs)
        self.repo_path = os.path.join(root, "repo")
        self.canaries = os.path.join(root, "canaries")
        self.state = os.path.join(root, "state")
        os.makedirs(self.canaries)
        os.makedirs(self.state)
        self._markers = []

    def marker(self, name):
        """Path a canary writes when it runs. Outside every snapshot root."""
        path = os.path.join(self.canaries, name)
        if path not in self._markers:
            self._markers.append(path)
        return path

    def fired(self):
        return sorted(
            os.path.basename(path) for path in self._markers if os.path.exists(path)
        )

    def env(self):
        """A Git and process environment that cannot reach the real machine."""
        home = os.path.join(self.state, "home")
        for directory in (home, os.path.join(self.state, "xdg")):
            if not os.path.isdir(directory):
                os.makedirs(directory)

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "XDG_STATE_HOME": os.path.join(self.state, "xdg", "state"),
            "XDG_CONFIG_HOME": os.path.join(self.state, "xdg", "config"),
            "XDG_DATA_HOME": os.path.join(self.state, "xdg", "data"),
            "XDG_CACHE_HOME": os.path.join(self.state, "xdg", "cache"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.path.join(home, "gitconfig"),
            "GIT_AUTHOR_NAME": "AIQE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "AIQE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "LC_ALL": "C",
            "TZ": "UTC",
        }
        if not os.path.exists(env["GIT_CONFIG_GLOBAL"]):
            with open(env["GIT_CONFIG_GLOBAL"], "w") as handle:
                handle.write("")
        return env

    def is_repository_path(self, relative):
        return relative.split(os.sep, 1)[0] in self.repository_dirs

    def is_state_path(self, relative):
        return relative.split(os.sep, 1)[0] == "state"


#: How long to wait for a fixture to go quiet before giving up on it.
QUIESCE_TIMEOUT_SECONDS = 5.0


def wait_until_quiescent(root, skip):
    """Fail unless the fixture has stopped changing on its own.

    Git can start background maintenance after a write, and that process
    outlives the command that started it. If its lock file disappears during a
    measurement window, the harness sees a repository file vanish and blames
    Doctor for it. That false reading was observed before fixture construction
    disabled background maintenance.

    Belt as well as braces: measuring a repository that is still moving
    produces a confident number about the wrong thing, so a fixture that will
    not settle raises rather than being measured.
    """
    deadline = time.time() + QUIESCE_TIMEOUT_SECONDS
    while True:
        locks = _lock_files(root, skip)
        if not locks:
            return
        if time.time() > deadline:
            raise RuntimeError(
                "fixture did not become quiescent: lock files still present "
                "after %.0fs: %s. Something is still writing to this "
                "repository, and measuring it would attribute that to Doctor."
                % (QUIESCE_TIMEOUT_SECONDS, sorted(locks))
            )
        time.sleep(0.05)


def _lock_files(root, skip):
    found = []
    skip = os.path.abspath(skip)
    for directory, subdirectories, filenames in os.walk(root):
        if os.path.abspath(directory) == skip:
            subdirectories[:] = []
            continue
        for name in filenames:
            if name.endswith(".lock"):
                found.append(os.path.relpath(os.path.join(directory, name), root))
    return found


def snapshot(root, skip):
    """Byte-level snapshot of everything under `root`, excluding `skip`.

    Records content hash, size, mode and modification time for every regular
    file and symlink, and records every directory. Mode and mtime are included
    deliberately: an index refresh that rewrote identical bytes would still
    move the modification time, and a claim of zero writes that ignored that
    would be a weaker claim than the one being made.
    """
    entries = {}
    skip = os.path.abspath(skip)
    for directory, subdirectories, filenames in os.walk(root):
        if os.path.abspath(directory) == skip:
            subdirectories[:] = []
            continue
        subdirectories.sort()
        relative_dir = os.path.relpath(directory, root)
        if relative_dir != ".":
            entries[relative_dir] = ("dir",)
        for name in sorted(filenames):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, root)
            entries[relative] = _describe(path)
    return entries


def _describe(path):
    try:
        stat = os.lstat(path)
    except OSError as exc:
        return ("error", str(exc))

    if stat_module.S_ISLNK(stat.st_mode):
        try:
            target = os.readlink(path)
        except OSError as exc:
            return ("error", str(exc))
        return ("link", hashlib.sha256(os.fsencode(target)).hexdigest())

    if not stat_module.S_ISREG(stat.st_mode):
        # A FIFO, socket or device node. Opening one to hash it would block
        # forever waiting for a writer - a fixture containing one is a real
        # case, and the harness has to survive measuring it. Its identity is
        # its kind and metadata; there are no contents to read.
        return ("special", stat.st_mode, stat.st_mtime_ns)

    try:
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        return ("error", str(exc))
    return ("file", digest, stat.st_size, stat.st_mode, stat.st_mtime_ns)


def compare(before, after):
    """Changed paths between two snapshots, as sorted human-readable strings."""
    changes = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append("added: " + key)
        elif key not in after:
            changes.append("removed: " + key)
        elif before[key] != after[key]:
            changes.append("changed: " + key + " " + _what_changed(before[key], after[key]))
    return changes


def _what_changed(before, after):
    if before[0] != after[0] or before[0] != "file":
        return "(kind or content)"
    fields = ("content", "size", "mode", "mtime")
    names = [
        fields[index - 1]
        for index in range(1, 5)
        if index < len(before) and index < len(after) and before[index] != after[index]
    ]
    return "(" + ",".join(names) + ")"
