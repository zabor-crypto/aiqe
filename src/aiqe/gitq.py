"""Bounded, read-only Git query layer.

Every Git invocation Doctor makes goes through this module, and nothing else
in AIQE core spawns a process. That single choke point is what makes Doctor's
frozen contract testable from the outside: a harness can assert exactly which
subcommands ran, and a mutation harness can assert that running them changed
no byte of the repository.

Two empirical facts shape this module. Neither is assumed; both are proven by
the negative controls in the test suite, because a Git command that is widely
*perceived* as diagnostic is not thereby read-only.

1.  `git status` writes `.git/index`.

    When the worktree is stat-dirty but content-identical - a tracked file
    rewritten with the same bytes, or merely touched - a plain `git status`
    refreshes the cached stat information and persists it. The index file's
    content and mtime both change. `--no-optional-locks` suppresses that
    write while leaving the reported state correct.

2.  `git status` executes repository-defined commands.

    `core.fsmonitor` is invoked as a child process during the index refresh,
    and `--no-optional-locks` does *not* prevent it. A per-invocation
    `-c core.fsmonitor=false` override does.

    A check-in filter is worse. When `.gitattributes` binds a path to a
    filter driver and the local configuration defines `filter.<name>.clean`
    or `filter.<name>.process`, Git runs that command to decide whether a
    same-size file actually changed. No Git flag prevents it: to answer the
    question at all, Git must read the content through the filter.

3.  The command that defines a filter driver need not live in the repository.

    A tracked `.gitattributes` can bind a path to a driver whose `clean` or
    `process` command is defined in the user's global configuration, or in a
    file pulled in by a local `include`. Repository content selects; external
    configuration supplies the executable. Inspecting only the repository's
    own configuration and concluding "no filter here" is therefore wrong, and
    it was: the canaries fired.

4.  `git status` descends into submodules and runs *their* filters.

    A submodule's own local configuration is repository scope for that
    submodule, so no amount of isolation in the superproject suppresses it.
    `--ignore-submodules=dirty` prevents the descent while still reporting a
    changed submodule pointer.

Two defences follow, and between them they are the whole mechanism:

    Configuration isolation. Every invocation that reads the index or the
    worktree runs with system and global configuration switched off, so an
    externally defined driver has no command to run. Git cannot execute a
    definition that is not in scope.

    Static refusal. Isolation cannot help when the definition is already in
    repository scope - a local `filter.<name>.clean`, an `include` whose
    target Doctor will not follow, or an attributes file binding a filter at
    all. There Doctor declines to compare worktree content and reports the
    unstaged count as unknown. See `doctor._filter_execution_risk`.

Isolation has a cost, and it is stated rather than hidden: a working-state
count is computed under repository-scope configuration only. A custom global
`core.excludesFile` does not apply to the untracked count, and a repository
whose access depends on a global `safe.directory` entry yields an unknown
working state rather than a wrong one.
"""

import os
import subprocess

#: Git subcommands Doctor is permitted to invoke. Every one of these has been
#: shown zero-write under the mutation harness with the hardening below. A
#: subcommand outside this set is a programming error, not a runtime
#: condition: the guard raises rather than degrading quietly.
#:
#: The set is also the network-behaviour argument. None of these commands
#: contacts a remote, and no code path in AIQE core can invoke any other.
ALLOWED_SUBCOMMANDS = frozenset(
    {
        "--version",
        "rev-parse",
        "symbolic-ref",
        "ls-files",
        "status",
        "diff-index",
    }
)

#: Subcommands that read the index or the worktree, and therefore run with
#: system and global configuration switched off. Discovery subcommands are
#: deliberately not in this set: they answer "which repository is this", and
#: answering it differently from the user's own Git would be its own defect.
CONFIG_ISOLATED_SUBCOMMANDS = frozenset({"status", "diff-index", "ls-files"})

#: Configuration isolation for those subcommands. `GIT_CONFIG_SYSTEM` and
#: `GIT_CONFIG_GLOBAL` pointing at the null device is the documented way to
#: read no configuration from those scopes; `GIT_CONFIG_NOSYSTEM` is kept as
#: well because it predates them by a decade.
#:
#: This writes nothing. The mutation harness proves the repository, its
#: configuration and the isolated home directory are byte-identical after a
#: Doctor run.
_CONFIG_ISOLATION = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
}

#: Hardening applied to every invocation, ahead of the subcommand.
#:
#: `--no-optional-locks`  suppresses the opportunistic index write.
#: `core.fsmonitor=false` suppresses the fsmonitor child process.
#:
#: `-c` sets configuration for one invocation only. It writes nothing: the
#: mutation harness proves that the repository configuration file is
#: byte-identical afterwards.
_HARDENING = ("--no-optional-locks", "-c", "core.fsmonitor=false")

#: Environment overrides. AIQE does not suppress the user's own Git
#: configuration: a diagnostic that reports counts the user cannot reproduce
#: with their own Git is a worse diagnostic, and `core.excludesFile` alone
#: would make the untracked count disagree. The overrides below remove
#: interactivity and paging, which would otherwise block or reformat output,
#: and disable the terminal credential prompt.
_ENV_OVERRIDES = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "GIT_FLUSH": "1",
    "LC_ALL": "C",
}

#: A Git invocation that has not returned within this many seconds is treated
#: as an unresolved condition rather than waited on indefinitely.
TIMEOUT_SECONDS = 30


class GitResult(object):
    """Outcome of one Git invocation.

    `stdout` and `stderr` stay as bytes. Git reports paths as bytes, and a
    filename is not required to be valid UTF-8 on either supported platform.
    Decoding it early is how a diagnostic tool crashes on the one repository
    its user most needs it to inspect.
    """

    __slots__ = ("args", "returncode", "stdout", "stderr", "timed_out")

    def __init__(self, args, returncode, stdout, stderr, timed_out=False):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def ok(self):
        return self.returncode == 0 and not self.timed_out

    def lines(self):
        """stdout split on newlines, as bytes, with no trailing empty item."""
        out = self.stdout
        if out.endswith(b"\n"):
            out = out[:-1]
        if not out:
            return []
        return out.split(b"\n")

    def nul_fields(self):
        """stdout split on NUL, as bytes, with no trailing empty item.

        Machine-readable Git path output is NUL-delimited wherever Git
        supports it. Newline-delimited path output is not a safe parsing
        surface, because a newline is a legal byte in a filename.
        """
        out = self.stdout
        if out.endswith(b"\0"):
            out = out[:-1]
        if not out:
            return []
        return out.split(b"\0")


class GitRunner(object):
    """Runs the allowlisted Git subcommands and records what it ran.

    The recording is not for logs. It is evidence: the test suite reads
    `invocations` to assert that a Doctor run touched only allowlisted,
    local-only subcommands, and that it never ran the command a naive
    implementation would have reached for.
    """

    def __init__(self, cwd, git_binary="git", env=None):
        self.cwd = cwd
        self.git_binary = git_binary
        self._base_env = os.environ if env is None else env
        #: Every invocation this runner made, in order, as tuples of str.
        self.invocations = []
        #: Whether each invocation ran with system and global configuration
        #: switched off. Parallel to `invocations`, so a test can assert that
        #: the isolation was actually applied and not merely documented.
        self.config_isolated = []

    def _env(self, isolate_config):
        env = dict(self._base_env)
        env.update(_ENV_OVERRIDES)
        if isolate_config:
            env.update(_CONFIG_ISOLATION)
        return env

    def run(self, *args):
        """Invoke one allowlisted Git subcommand.

        Returns a GitResult. A missing Git binary, a non-zero status and a
        timeout are all returned rather than raised: for a first-contact
        diagnostic every one of them is a reportable condition, not a crash.
        """
        if not args:
            raise ValueError("no Git subcommand given")
        subcommand = args[0]
        if subcommand not in ALLOWED_SUBCOMMANDS:
            raise AssertionError(
                "Git subcommand %r is not in the Doctor allowlist" % (subcommand,)
            )

        if subcommand == "--version":
            argv = [self.git_binary, "--version"]
        else:
            argv = [self.git_binary]
            argv.extend(_HARDENING)
            argv.extend(args)

        isolate_config = subcommand in CONFIG_ISOLATED_SUBCOMMANDS
        self.invocations.append(tuple(argv))
        self.config_isolated.append(isolate_config)

        try:
            proc = subprocess.Popen(
                argv,
                cwd=self.cwd,
                env=self._env(isolate_config),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return GitResult(tuple(argv), 127, b"", str(exc).encode("utf-8", "replace"))

        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return GitResult(tuple(argv), -1, stdout, stderr, timed_out=True)

        return GitResult(tuple(argv), proc.returncode, stdout, stderr)


def parse_version(stdout):
    """Extract the dotted version from `git --version` output.

    Returns None when the output does not have the documented shape, which
    Doctor reports as an unknown rather than guessing a version number.
    """
    try:
        text = stdout.decode("utf-8", "replace").strip()
    except Exception:
        return None
    parts = text.split()
    # Documented shape: "git version X.Y.Z[ vendor suffix]"
    if len(parts) >= 3 and parts[0] == "git" and parts[1] == "version":
        candidate = parts[2]
        if candidate and candidate[0].isdigit():
            return candidate
    return None


def parse_status_porcelain_v2(stdout):
    """Count staged, unstaged and untracked entries in porcelain v2 output.

    The input is the NUL-delimited output of

        status --porcelain=v2 -z --untracked-files=normal --no-renames

    Record shapes, per gitformat / git-status(1):

        "1 <XY> ..."  ordinary changed entry
        "2 <XY> ..."  renamed or copied entry, followed by a second NUL field
                      holding the original path
        "u <XY> ..."  unmerged entry
        "? <path>"    untracked
        "! <path>"    ignored (not requested here)

    `--no-renames` is passed so that "2" records do not arise, but the parser
    consumes the extra path field anyway rather than silently misaligning if
    a future Git emits one.

    XY is a two-character status: X is the index-versus-HEAD state and Y the
    worktree-versus-index state. "." means unmodified in that position.

    Returns a dict of counts, or None if a record is not recognised - which
    Doctor reports as unknown rather than as a confident zero.
    """
    fields = stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()

    staged = 0
    unstaged = 0
    untracked = 0
    unmerged = 0

    index = 0
    total = len(fields)
    while index < total:
        record = fields[index]
        index += 1
        if not record:
            continue
        kind = record[0:1]

        if kind == b"?":
            untracked += 1
            continue
        if kind == b"!":
            continue
        if kind == b"u":
            unmerged += 1
            continue
        if kind in (b"1", b"2"):
            parts = record.split(b" ")
            if len(parts) < 2 or len(parts[1]) != 2:
                return None
            xy = parts[1]
            if xy[0:1] != b".":
                staged += 1
            if xy[1:2] != b".":
                unstaged += 1
            if kind == b"2":
                # The original path follows in its own NUL field.
                index += 1
            continue
        return None

    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "unmerged": unmerged,
    }
