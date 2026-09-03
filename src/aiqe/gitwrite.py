"""The Git layer `aiqe commit` uses, and the one place AIQE may mutate a repository.

`gitq` is the read-only layer. It runs with system and global configuration
switched off, because a diagnostic must not let an externally defined filter
driver execute during an inspection. That isolation is exactly wrong here.

A completion commit is a high-authority operation, and the commit AIQE creates
is the commit the user's own Git would create. If AIQE resolved policy under a
configuration the real commit would not use, every refusal and every proof
would be about a repository that does not exist. So this runner reads the
**effective** configuration: system, global, local, worktree, command scope,
`include` and `includeIf`, exactly as Git resolves them. Nothing is stripped.

What is suppressed is the non-semantic execution behaviour named in the
architecture:

    core.fsmonitor      a child process started during an index refresh
    gc.auto             background maintenance, which writes after the
    maintenance.auto    command has already returned

None of the three changes what a commit contains. Everything that does -
hooks, signing, check-in filters, attributes - is left alone and refused in
preflight instead. Turning a policy off to make a commit succeed would be the
product quietly deciding it knows better than the repository it is committing
to.

**Every path is literal.** `--literal-pathspecs` is passed ahead of every
subcommand, not per call site. A repository path is a byte string, and `*`,
`?`, `[abc]`, `:(top)` and a leading dash are all names rather than syntax.
`--` is an option terminator and is used as one; it is not the mechanism that
makes a path literal, and treating it as one is how a filename becomes a glob.

**The allowlist is the network argument.** None of the subcommands below
contacts a remote, and `aiqe commit` cannot invoke any other, so
`AIQE_PUSH_CALLS = 0` is a property of this module rather than a promise made
in prose. Every invocation is recorded, and the test suite reads the record.
"""

import os
import subprocess

#: Git subcommands `aiqe commit` may invoke.
#:
#: `push`, `remote`, `fetch`, `ls-remote` and every other network subcommand
#: are absent, and the guard below raises rather than degrading: a subcommand
#: outside this set is a programming error, not a runtime condition.
ALLOWED_SUBCOMMANDS = frozenset(
    {
        "rev-parse",
        "symbolic-ref",
        "config",
        "check-attr",
        "hash-object",
        "ls-files",
        "ls-tree",
        "cat-file",
        "diff-index",
        "diff-tree",
        "rev-list",
        "add",
        "update-index",
        "commit",
    }
)

#: The three that write. Separated so a test can assert that a refusal path
#: invoked none of them, which is what `commit = NONE` and `index unchanged`
#: mean in the commit-policy contract.
MUTATING_SUBCOMMANDS = frozenset({"add", "update-index", "commit"})

#: Non-semantic execution controls, applied to every invocation.
#:
#: These suppress a child process and two background writers. They do not
#: change what a commit contains, and nothing else is overridden here: an
#: `-c` that altered check-in semantics would make the proof describe a
#: different commit from the one that was created.
_HARDENING = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "gc.auto=0",
    "-c",
    "maintenance.auto=false",
)

#: Applied ahead of the subcommand on every invocation. Global literal
#: pathspec semantics is the frozen mechanism; `GIT_LITERAL_PATHSPECS=1` is
#: its documented equivalent and is set as well, so that the guarantee does
#: not depend on one of the two surviving a refactor.
_LITERAL = ("--literal-pathspecs",)

#: Read-only invocations additionally suppress the opportunistic index write.
#: The commit itself must not: its index update is required, not optional.
_READ_ONLY_HARDENING = ("--no-optional-locks",)

_ENV_OVERRIDES = {
    "GIT_LITERAL_PATHSPECS": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "GIT_FLUSH": "1",
    "LC_ALL": "C",
}

_READ_ONLY_ENV_OVERRIDES = {"GIT_OPTIONAL_LOCKS": "0"}

#: A read that has not returned in this long is an unresolved condition.
READ_TIMEOUT_SECONDS = 60

#: A commit on a large repository is legitimately slower than a query. Still
#: bounded: a Git invocation that never returns must fail the operation rather
#: than hang it.
WRITE_TIMEOUT_SECONDS = 300


class GitResult(object):
    """Outcome of one Git invocation. Output stays as bytes throughout."""

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
        out = self.stdout
        if out.endswith(b"\n"):
            out = out[:-1]
        if not out:
            return []
        return out.split(b"\n")

    def nul_fields(self):
        """stdout split on NUL, with no trailing empty item.

        Machine-readable Git path output is NUL-delimited wherever Git
        supports it, because a newline is a legal byte in a filename.
        """
        out = self.stdout
        if out.endswith(b"\0"):
            out = out[:-1]
        if not out:
            return []
        return out.split(b"\0")


class CommitGitRunner(object):
    """Runs the allowlisted subcommands under effective Git semantics."""

    def __init__(self, cwd, git_binary="git", env=None):
        self.cwd = cwd
        self.git_binary = git_binary
        self._base_env = os.environ if env is None else env
        #: Every invocation, in order, as tuples of bytes/str argv elements.
        self.invocations = []
        #: Parallel to `invocations`: whether that invocation could write.
        self.mutating = []

    def _env(self, write):
        env = dict(self._base_env)
        env.update(_ENV_OVERRIDES)
        if not write:
            env.update(_READ_ONLY_ENV_OVERRIDES)
        return env

    @property
    def mutating_invocations(self):
        return [
            argv
            for argv, writes in zip(self.invocations, self.mutating)
            if writes
        ]

    def run(self, *args, **kwargs):
        """Invoke one allowlisted subcommand. Never raises for Git's own status."""
        if not args:
            raise ValueError("no Git subcommand given")
        subcommand = args[0]
        if subcommand not in ALLOWED_SUBCOMMANDS:
            raise AssertionError(
                "Git subcommand %r is not in the AIQE commit allowlist"
                % (subcommand,)
            )
        write = subcommand in MUTATING_SUBCOMMANDS
        timeout = kwargs.pop("timeout", None)
        if kwargs:
            raise TypeError("unexpected keyword arguments %r" % (sorted(kwargs),))
        if timeout is None:
            timeout = WRITE_TIMEOUT_SECONDS if write else READ_TIMEOUT_SECONDS

        argv = [self.git_binary]
        argv.extend(_LITERAL)
        if not write:
            argv.extend(_READ_ONLY_HARDENING)
        argv.extend(_HARDENING)
        argv.extend(args)

        self.invocations.append(tuple(argv))
        self.mutating.append(write)

        try:
            proc = subprocess.Popen(
                argv,
                cwd=self.cwd,
                env=self._env(write),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return GitResult(
                tuple(argv), 127, b"", str(exc).encode("utf-8", "replace")
            )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return GitResult(tuple(argv), -1, stdout, stderr, timed_out=True)

        return GitResult(tuple(argv), proc.returncode, stdout, stderr)
