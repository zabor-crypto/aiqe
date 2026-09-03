"""What the real completion commit would do, decided before anything is written.

Doctor asks a first-contact question - "is anything here likely to execute?" -
and answers it from repository-scope files alone, without following an
`include` chain. That boundary is right for a diagnostic and wrong for a
commit. The commit AIQE creates is the commit the user's Git would create, so
the policy it must respect is the **effective** one: system, global, local,
worktree and command scope, with `include` and `includeIf` resolved, exactly
as Git resolves them.

Four refusals live here, and every one of them fails closed:

```
unsupported topology / operation state    exit 3
effective configuration unresolved        exit 3
an active commit hook                     exit 3
automatic commit signing                  exit 3
an external check-in filter on an owned path   exit 3
```

Three properties are load-bearing.

**No canary may fire during a refusal.** The refusal is decided from
configuration and from `lstat`, and `git check-attr` resolves attributes
without running a filter. Measured, not assumed: with a `filter.<name>.clean`
canary bound to a path, `check-attr` leaves the marker unwritten while
`hash-object --path` on the same path writes it. That measurement is the
reason the filter refusal happens *before* any expected-state derivation.

**A configured driver is not a blocker; a bound one is.** A repository whose
global configuration defines `filter.lfs.clean` and whose owned paths are all
plain Python has nothing to refuse. Refusing there would make AIQE unusable
on a machine that has ever installed Git LFS, and would teach its users that
its refusals are noise.

**Nothing is turned off to make the commit work.** There is no `--no-verify`,
no `--no-gpg-sign`, and no configuration stripped for convenience. AIQE v1
does not support these policies, and the honest form of "does not support" is
a refusal, not a bypass.
"""

import os
import stat as stat_module

from .textsafe import display_bytes, display_text

#: Refusal identities. All of them are exit 3: nothing was proven false about
#: the work, and the operation cannot safely proceed.
EFFECTIVE_CONFIG_UNRESOLVED = "EFFECTIVE_CONFIG_UNRESOLVED"
COMMIT_HOOK_POLICY_UNSUPPORTED = "COMMIT_HOOK_POLICY_UNSUPPORTED"
COMMIT_SIGNING_POLICY_UNSUPPORTED = "COMMIT_SIGNING_POLICY_UNSUPPORTED"
CHECKIN_FILTER_UNSUPPORTED = "CHECKIN_FILTER_UNSUPPORTED"
CHECKIN_ATTRIBUTES_UNRESOLVED = "CHECKIN_ATTRIBUTES_UNRESOLVED"

MERGE_IN_PROGRESS = "MERGE_IN_PROGRESS"
REBASE_IN_PROGRESS = "REBASE_IN_PROGRESS"
CHERRY_PICK_IN_PROGRESS = "CHERRY_PICK_IN_PROGRESS"
REVERT_IN_PROGRESS = "REVERT_IN_PROGRESS"
SEQUENCER_IN_PROGRESS = "SEQUENCER_IN_PROGRESS"
BISECT_IN_PROGRESS = "BISECT_IN_PROGRESS"
UNMERGED_INDEX_ENTRIES = "UNMERGED_INDEX_ENTRIES"
SPARSE_CHECKOUT_UNSUPPORTED = "SPARSE_CHECKOUT_UNSUPPORTED"
DETACHED_HEAD_UNSUPPORTED = "DETACHED_HEAD_UNSUPPORTED"
INDEX_UNREADABLE = "INDEX_UNREADABLE"

#: The commit-execution hooks Git may run for `git commit -m`.
COMMIT_HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit")

#: An operation-state file or directory under the worktree Git directory, and
#: what its presence means. Checked by `lstat`, because the question is
#: whether Git considers an operation to be in progress, and Git decides that
#: by the path existing.
_OPERATION_STATE = (
    (b"MERGE_HEAD", MERGE_IN_PROGRESS, "a merge"),
    (b"rebase-merge", REBASE_IN_PROGRESS, "a rebase"),
    (b"rebase-apply", REBASE_IN_PROGRESS, "a rebase"),
    (b"CHERRY_PICK_HEAD", CHERRY_PICK_IN_PROGRESS, "a cherry-pick"),
    (b"REVERT_HEAD", REVERT_IN_PROGRESS, "a revert"),
    (b"sequencer", SEQUENCER_IN_PROGRESS, "a sequencer operation"),
    (b"BISECT_LOG", BISECT_IN_PROGRESS, "a bisect"),
)


class PolicyRefusal(Exception):
    """The completion commit would need behaviour AIQE v1 does not support."""

    def __init__(self, code, message, detail=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        #: Extra human lines, already terminal-safe.
        self.detail = tuple(detail or ())


# --- Effective configuration -----------------------------------------------


class EffectiveConfig(object):
    """The configuration Git itself resolved, as ordered (key, value) pairs.

    Keys arrive from Git already lowercased in section and key, with the
    subsection's case preserved, which is exactly Git's own comparison rule.
    Values keep Git's last-one-wins ordering, so `get` reads backwards.
    """

    __slots__ = ("entries", "scopes")

    def __init__(self, entries, scopes=()):
        #: [(key, value or None)], in Git's resolution order.
        self.entries = list(entries)
        #: Parallel scope names, as Git reports them.
        self.scopes = list(scopes)

    def get(self, key):
        """The winning value for a fully qualified key, or None."""
        for index in self._indices(key):
            return self.entries[index][1]
        return None

    def present(self, key):
        for _index in self._indices(key):
            return True
        return False

    def scope_of(self, key):
        """Which configuration scope supplied the winning value, or None."""
        for index in self._indices(key):
            if index < len(self.scopes):
                return self.scopes[index]
            return None
        return None

    def _indices(self, key):
        """Indices of entries matching `key`, latest first. Git's own rule.

        Section and variable names are case-insensitive; a subsection is not.
        `filter.Canary.clean` and `filter.canary.clean` are two different
        drivers to Git, and treating them as one would make AIQE refuse a
        commit over a driver that is not bound to anything.
        """
        wanted = _split(key)
        for index in range(len(self.entries) - 1, -1, -1):
            if _split(self.entries[index][0]) == wanted:
                yield index


def _split(key):
    """`section[.subsection].name`, normalised the way Git compares it.

    The subsection is everything between the first and last dot, and it keeps
    its case. A subsection may itself contain dots - `url.https://x.insteadOf`
    is a real key - so the split is on the first and last separator rather
    than on all of them.
    """
    section, separator, rest = key.partition(".")
    if not separator:
        return (key.lower(), None, None)
    subsection, separator, name = rest.rpartition(".")
    if not separator:
        return (section.lower(), None, rest.lower())
    return (section.lower(), subsection, name.lower())


def is_true(value):
    """Git's boolean reading. A bare key with no value is true."""
    if value is None:
        return True
    return value.strip().lower() in ("true", "yes", "on", "1")


def resolve_effective_config(runner):
    """Ask Git to resolve the whole configuration, includes and all.

    `git config --list` reads configuration and nothing else: it executes no
    hook, no filter and no signer. When it cannot resolve the chain - a
    malformed file, an unreadable one, a bad `includeIf` - it fails, and that
    failure is the refusal rather than something to work around.
    """
    result = runner.run("config", "--list", "-z", "--includes", "--show-scope")
    if not result.ok:
        raise PolicyRefusal(
            EFFECTIVE_CONFIG_UNRESOLVED,
            "the effective Git configuration for this repository could not be "
            "resolved, so the policy the completion commit would run under is "
            "unknown.",
            detail=_git_detail(result),
        )

    fields = result.nul_fields()
    if len(fields) % 2 != 0:
        raise PolicyRefusal(
            EFFECTIVE_CONFIG_UNRESOLVED,
            "the effective Git configuration could not be parsed as scoped "
            "key/value records.",
        )

    entries = []
    scopes = []
    for index in range(0, len(fields), 2):
        scope = fields[index].decode("utf-8", "replace")
        record = fields[index + 1]
        key, separator, value = record.partition(b"\n")
        entries.append(
            (
                key.decode("utf-8", "replace"),
                value.decode("utf-8", "replace") if separator else None,
            )
        )
        scopes.append(scope)
    return EffectiveConfig(entries, scopes)


def _git_detail(result):
    text = result.stderr.decode("utf-8", "replace").strip()
    if not text:
        return ()
    return tuple("  " + display_text(line) for line in text.split("\n")[:4])


# --- Topology and operation state ------------------------------------------


def require_supported_topology(runner, git_dir, config):
    """Refuse the operation states v1 does not model.

    v1 creates one ordinary commit on a branch. A merge, a rebase, a
    cherry-pick, a revert, an unmerged index or a sparse checkout each changes
    what "commit these paths" means, and inventing an answer for them would be
    a claim about a commit AIQE has never tested creating.
    """
    for name, code, description in _OPERATION_STATE:
        candidate = os.path.join(git_dir, name)
        if os.path.lexists(candidate):
            raise PolicyRefusal(
                code,
                "%s is in progress in this worktree. AIQE v1 creates one "
                "ordinary completion commit and does not model that "
                "operation." % (description,),
            )

    unmerged = runner.run("ls-files", "--unmerged", "-z")
    if not unmerged.ok:
        raise PolicyRefusal(
            INDEX_UNREADABLE,
            "the Git index could not be read, so AIQE cannot establish what a "
            "completion commit would contain.",
            detail=_git_detail(unmerged),
        )
    if unmerged.nul_fields():
        raise PolicyRefusal(
            UNMERGED_INDEX_ENTRIES,
            "the index holds unmerged entries. A completion commit over an "
            "unresolved conflict is not an operation AIQE v1 supports.",
        )

    if is_true(config.get("core.sparseCheckout")) and config.present(
        "core.sparseCheckout"
    ):
        raise PolicyRefusal(
            SPARSE_CHECKOUT_UNSUPPORTED,
            "this worktree is a sparse checkout. What a path's absence means "
            "there differs from what it means in a full checkout, so AIQE v1 "
            "refuses rather than guessing.",
        )

    branch = runner.run("symbolic-ref", "--quiet", "HEAD")
    if not branch.ok or not branch.lines():
        raise PolicyRefusal(
            DETACHED_HEAD_UNSUPPORTED,
            "HEAD is detached. AIQE v1 has not proven a detached HEAD as a "
            "supported completion surface, so it refuses rather than "
            "silently claiming support for one.",
        )


# --- Commit hooks ----------------------------------------------------------


def hooks_directory(config, common_dir, worktree):
    """The directory Git would look in for a commit hook.

    `core.hooksPath` may be relative, and Git resolves a relative value
    against the directory the hooks run in - the worktree root.
    """
    configured = config.get("core.hooksPath")
    if configured:
        candidate = os.fsencode(configured)
        if not os.path.isabs(candidate):
            candidate = os.path.join(worktree, candidate)
        return os.path.normpath(candidate), True
    return os.path.join(common_dir, b"hooks"), False


def require_no_active_commit_hook(config, common_dir, worktree):
    """Refuse if Git would execute a hook for this commit.

    Active means what Git means by it: a regular file with an execute bit. A
    hook path that is a symbolic link, a directory, or anything else is
    ambiguous rather than absent, and ambiguity fails closed - resolving the
    link to find out what is on the other side is already acting on a path
    this function has decided it cannot characterise.
    """
    directory, configured = hooks_directory(config, common_dir, worktree)
    active = []
    for name in COMMIT_HOOKS:
        path = os.path.join(directory, name.encode("ascii"))
        try:
            stat = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            active.append((name, "could not be inspected"))
            continue
        if not stat_module.S_ISREG(stat.st_mode):
            active.append((name, "is not a regular file"))
            continue
        if stat.st_mode & 0o111:
            active.append((name, "is executable"))

    if not active:
        return directory, configured

    raise PolicyRefusal(
        COMMIT_HOOK_POLICY_UNSUPPORTED,
        "this repository has commit hooks Git would run, and AIQE v1 neither "
        "runs them nor bypasses them with --no-verify.",
        detail=tuple(
            "  %-20s %s" % (display_text(name), reason) for name, reason in active
        )
        + (
            "  hooks path %s"
            % (display_bytes(directory) + (" (core.hooksPath)" if configured else ""),),
        ),
    )


# --- Commit signing --------------------------------------------------------


def require_no_automatic_signing(config):
    """Refuse if the effective configuration would sign this commit.

    `--no-gpg-sign` would make the commit succeed and would also mean AIQE
    had quietly overridden a policy the repository or the user set. v1 does
    not sign, and says so.
    """
    value = config.get("commit.gpgSign")
    if config.present("commit.gpgSign") and is_true(value):
        scope = config.scope_of("commit.gpgSign") or "unknown"
        raise PolicyRefusal(
            COMMIT_SIGNING_POLICY_UNSUPPORTED,
            "the effective configuration requires commit signing "
            "(commit.gpgSign is set in %s scope). AIQE v1 does not sign "
            "commits and will not disable your signing policy to create one."
            % (display_text(scope),),
        )


# --- External check-in filters ---------------------------------------------


def filter_bindings(runner, paths):
    """The `filter` attribute Git resolves for each path.

    `git check-attr` resolves the whole attribute stack - tracked
    `.gitattributes` at every level, `$GIT_DIR/info/attributes`, and the
    effective `core.attributesFile` - and it does so without running a
    filter. That is measured: with a clean-filter canary bound to a path,
    `check-attr` leaves the canary unwritten.

    Returns {path: driver name or None}. `unspecified`, `unset` and a bare
    `set` all mean no driver.
    """
    bindings = {}
    for path in paths:
        result = runner.run("check-attr", "-z", "filter", "--", path)
        if not result.ok:
            raise PolicyRefusal(
                CHECKIN_ATTRIBUTES_UNRESOLVED,
                "the check-in attributes for an owned path could not be "
                "resolved, so whether committing it would execute a filter is "
                "unknown.",
                detail=_git_detail(result),
            )
        fields = result.nul_fields()
        if len(fields) != 3 or fields[0] != path:
            raise PolicyRefusal(
                CHECKIN_ATTRIBUTES_UNRESOLVED,
                "Git returned an attribute record AIQE cannot match back to "
                "the owned path it asked about.",
            )
        value = fields[2].decode("utf-8", "replace")
        if value in ("unspecified", "unset", "set"):
            bindings[path] = None
        else:
            bindings[path] = value
    return bindings


def require_no_external_checkin_filter(runner, config, paths):
    """Refuse when an owned path is bound to a driver with a clean or process command.

    A driver that is configured but bound to nothing is not a blocker: a
    machine with Git LFS installed is not a machine AIQE refuses to work on.
    What matters is the pair - an attribute binding the path, and a
    configuration supplying an external command for it.
    """
    bindings = filter_bindings(runner, paths)
    blocked = []
    for path in paths:
        driver = bindings.get(path)
        if not driver:
            continue
        for key in ("clean", "process"):
            command = config.get("filter.%s.%s" % (driver, key))
            if command:
                blocked.append((path, driver, key))
                break

    if blocked:
        raise PolicyRefusal(
            CHECKIN_FILTER_UNSUPPORTED,
            "an owned path is bound to an external check-in filter. AIQE "
            "would have to run that command to know what the commit would "
            "contain, and v1 does not execute check-in filters.",
            detail=tuple(
                "  %s -> filter.%s.%s"
                % (display_bytes(path), display_text(driver), key)
                for path, driver, key in blocked
            ),
        )
    return bindings
