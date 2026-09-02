"""First-contact repository diagnosis.

Doctor runs before anything is written. It answers what it can determine
safely, reports what it cannot determine as unknown, and does not guess in
between.

The frozen safety contract, restated as the rules this module actually
follows:

    no repository mutation          nothing here writes into the repository,
                                    the index, or the Git configuration
    no repository-defined execution no configured hook, filter driver,
                                    fsmonitor or alias is run
    no AIQE local state writes      Doctor persists nothing, anywhere
    no network, no model calls      nothing here opens a socket

Those are not self-reported. The mutation and network harnesses in the test
suite measure them from outside this process, and the negative controls show
what a naive diagnostic implementation would have done instead.

The one place where honesty costs a feature is `working_state`. A check-in
filter cannot be prevented from running when Git is asked to compare worktree
content against the index, so Doctor does not always ask. Two defences decide
whether it asks at all, and they were chosen by measuring what actually
executes rather than by reasoning about what ought to:

    Configuration isolation, in `gitq`. Every index- or worktree-reading
    invocation runs with system and global configuration switched off, so a
    driver defined outside the repository has no command to run.

    Static refusal, in `_filter_execution_risk` below. Isolation cannot help
    once a definition is already in repository scope, so where repository
    configuration or repository attributes make execution safety unresolved,
    Doctor declines to compare worktree content and reports the unstaged count
    as unknown.

An unknown is the intended answer there, not a gap: an assurance layer that
executed a repository-defined command in order to fill in a number would have
broken its own first-contact contract to look complete.
"""

import json
import os

from . import findings as f
from . import gitconfig
from .gitq import GitRunner, parse_status_porcelain_v2, parse_version

#: Files whose presence in the Git directory marks an operation in progress.
#: Each is a plain existence check inside the repository's own Git directory.
_OPERATION_MARKERS = (
    (b"MERGE_HEAD", f.OPERATION_MERGE_IN_PROGRESS, "A merge is in progress"),
    (b"CHERRY_PICK_HEAD", f.OPERATION_CHERRY_PICK_IN_PROGRESS, "A cherry-pick is in progress"),
    (b"REVERT_HEAD", f.OPERATION_REVERT_IN_PROGRESS, "A revert is in progress"),
    (b"BISECT_LOG", f.OPERATION_BISECT_IN_PROGRESS, "A bisect is in progress"),
    (b"rebase-merge", f.OPERATION_REBASE_IN_PROGRESS, "A rebase is in progress"),
    (b"rebase-apply", f.OPERATION_REBASE_IN_PROGRESS, "A rebase is in progress"),
)

#: Claude Code permission entries that grant unconstrained shell access.
#: The rule is deliberately narrow: only an entry that places no constraint at
#: all on the command counts as broad. Anything else is reported as neither
#: broad nor bounded, because Doctor cannot state a deterministic rule for it.
_CLAUDE_UNCONSTRAINED_BASH = frozenset(
    {"bash", "bash()", "bash(*)", "bash(*:*)", "bash(:*)"}
)

#: Codex settings that disable the approval and sandbox boundaries. Matched
#: only as an exact top-level assignment, after comment stripping.
_CODEX_BROAD_ASSIGNMENTS = (
    ("approval_policy", "never"),
    ("sandbox_mode", "danger-full-access"),
)


class Report(object):
    """Everything Doctor determined, and everything it could not.

    Filesystem paths are held here only as private attributes. They are not
    part of the report: the rendered output carries counts, booleans and
    categories, because a Doctor screenshot or a stored JSON result should not
    disclose a home directory, a username, a branch name or a commit
    identifier.
    """

    def __init__(self):
        self.result = "PRODUCED"
        self.git = {"available": False, "version": None}
        self.repository = {
            "detected": False,
            "kind": "none",
            "head": "none",
        }
        self.working_state = {
            "staged": None,
            "unstaged": None,
            "untracked": None,
            "unmerged": None,
            "determined": False,
            # Set when the repository has submodules. Their worktree
            # dirtiness is not counted, because counting it means descending
            # into them and running their filters.
            "submodule_worktrees_excluded": False,
        }
        self.topology = {
            "linked_worktree": False,
            "sparse_checkout": "off",
        }
        self.operations = []
        self.aiqe = {"config_present": False}
        self.commit_policy = {
            "hooks_path_configured": False,
            "hooks_present": False,
            "signing_configured": False,
            "checkin_filter_configured": False,
            "tracked_gitattributes": False,
            "config_include_present": False,
            "local_config_readable": True,
            # Repository attributes bind at least one path to a filter
            # driver. The driver's command may be defined anywhere, including
            # outside the repository, so the binding alone makes a worktree
            # comparison unsafe.
            "attributes_bind_filter": False,
            # A repository attributes file is declared but could not be read,
            # so whether it binds a filter is unresolved.
            "attributes_readable": True,
            "submodules_present": False,
        }
        self.agent_surface = {
            "claude_config_present": False,
            "claude_permissions": "not_present",
            "codex_config_present": False,
            "codex_permissions": "not_present",
        }
        self.findings = []

        # Private working state; never rendered.
        self._worktree = None
        self._git_dir = None
        self._common_dir = None

    def add(self, code, state, summary):
        self.findings.append(f.Finding(code, state, summary))

    def sorted_findings(self):
        return sorted(self.findings, key=f.sort_key)

    def state_counts(self):
        counts = dict((state, 0) for state in f.STATES)
        for finding in self.findings:
            counts[finding.state] += 1
        return counts

    def exit_code(self):
        """Doctor's exit status.

        A finding is part of a valid diagnostic, so findings do not change
        the exit status. Only the inability to produce a valid diagnostic
        does.
        """
        from . import exits

        return exits.OK if self.result == "PRODUCED" else exits.UNSUPPORTED


def inspect(start_dir, env=None, git_binary="git"):
    """Diagnose the repository containing `start_dir`. Returns a Report.

    `start_dir` is used as the working directory for Git. Doctor does not walk
    upwards itself and does not look outside the repository it finds: Git's
    own discovery decides what repository this is, and nothing above the
    worktree root is inspected.
    """
    report = Report()
    runner = GitRunner(start_dir, git_binary=git_binary, env=env)
    report.runner = runner

    if not _inspect_git(report, runner):
        return report
    if not _inspect_repository(report, runner, start_dir):
        return report

    config = _read_local_config(report)
    tracked = _inspect_tracked(report, runner)

    _inspect_topology(report, config)
    _inspect_operations(report)
    _inspect_commit_policy(report, config, tracked)
    _inspect_working_state(report, runner)
    _inspect_aiqe_config(report)
    _inspect_agent_surface(report)

    return report


# --- Git availability ------------------------------------------------------


def _inspect_git(report, runner):
    result = runner.run("--version")
    if not result.ok:
        report.result = "UNSUPPORTED"
        report.add(
            f.GIT_UNAVAILABLE,
            f.UNSUPPORTED,
            "Git could not be run, so no repository diagnosis is possible.",
        )
        return False

    report.git["available"] = True
    version = parse_version(result.stdout)
    report.git["version"] = version
    if version is None:
        report.add(
            f.GIT_VERSION_UNKNOWN,
            f.UNKNOWN,
            "Git ran but did not report a recognisable version string.",
        )
    return True


# --- Repository discovery --------------------------------------------------


def _inspect_repository(report, runner, start_dir):
    result = runner.run(
        "rev-parse",
        "--git-dir",
        "--git-common-dir",
        "--is-bare-repository",
        "--is-inside-work-tree",
    )
    if not result.ok:
        report.repository["detected"] = False
        report.repository["kind"] = "none"
        report.add(
            f.REPOSITORY_ABSENT,
            f.FINDING,
            "No Git repository was found here. AIQE operates inside a Git worktree.",
        )
        return False

    lines = result.lines()
    if len(lines) != 4:
        return _unresolved_topology(
            report, "Git did not report the repository layout in the expected form."
        )

    git_dir, common_dir, is_bare, inside_worktree = lines
    report.repository["detected"] = True

    if is_bare.strip() == b"true":
        report.repository["kind"] = "bare"
        report.result = "UNSUPPORTED"
        report.add(
            f.REPOSITORY_BARE,
            f.UNSUPPORTED,
            "This is a bare repository. AIQE requires a worktree, so no "
            "first-contact diagnosis applies.",
        )
        return False

    if inside_worktree.strip() != b"true":
        return _unresolved_topology(
            report,
            "Git reports a repository but no worktree at this location.",
        )

    toplevel = runner.run("rev-parse", "--show-toplevel")
    if not toplevel.ok or not toplevel.lines():
        return _unresolved_topology(
            report, "Git did not report a worktree root for this repository."
        )

    base = os.fsencode(start_dir)
    report._worktree = _absolute(toplevel.lines()[0], base)
    report._git_dir = _absolute(git_dir, base)
    report._common_dir = _absolute(common_dir, base)
    report.repository["kind"] = "worktree"

    _inspect_head(report, runner)
    return True


def _unresolved_topology(report, summary):
    report.result = "UNSUPPORTED"
    report.add(f.REPOSITORY_TOPOLOGY_UNRESOLVED, f.UNSUPPORTED, summary)
    return False


def _absolute(path_bytes, base):
    """Resolve a possibly relative Git path against the inspected directory.

    Paths stay as bytes. A filename is not guaranteed to be valid UTF-8 on
    either supported platform, and decoding one early is how a diagnostic tool
    fails on the repository its user most needs inspected.
    """
    if not os.path.isabs(path_bytes):
        path_bytes = os.path.join(base, path_bytes)
    return os.path.normpath(path_bytes)


def _inspect_head(report, runner):
    on_branch = runner.run("symbolic-ref", "--quiet", "HEAD").ok
    has_commit = runner.run("rev-parse", "--verify", "--quiet", "HEAD").ok

    if on_branch and has_commit:
        report.repository["head"] = "branch"
    elif on_branch and not has_commit:
        report.repository["head"] = "unborn"
        report.add(
            f.REPOSITORY_UNBORN_HEAD,
            f.FINDING,
            "HEAD points at a branch that has no commits yet.",
        )
    elif has_commit:
        report.repository["head"] = "detached"
        report.add(
            f.HEAD_DETACHED,
            f.FINDING,
            "HEAD is detached rather than on a branch.",
        )
    else:
        report.repository["head"] = "unknown"
        report.add(
            f.REPOSITORY_TOPOLOGY_UNRESOLVED,
            f.UNSUPPORTED,
            "HEAD could not be resolved to a branch or a commit.",
        )
        report.result = "UNSUPPORTED"


# --- Local configuration ---------------------------------------------------


def _read_local_config(report):
    """Read the repository's own configuration files, statically.

    Two files are in scope: the repository configuration in the common Git
    directory, and the per-worktree configuration, which Git uses when the
    `worktreeConfig` extension is enabled - sparse-checkout enables it. No
    include chain is followed, and no configuration outside the repository is
    read.
    """
    entries = []
    unreadable = False

    for path in _config_paths(report):
        try:
            parsed = gitconfig.read_file(path)
        except gitconfig.ConfigError:
            unreadable = True
            continue
        if parsed is not None:
            entries.extend(parsed.entries)

    if unreadable:
        report.commit_policy["local_config_readable"] = False
        report.add(
            f.GIT_CONFIG_UNREADABLE,
            f.UNKNOWN,
            "A repository Git configuration file could not be parsed, so its "
            "policy signals are unknown.",
        )

    return gitconfig.ConfigFile(None, entries)


def _config_paths(report):
    paths = []
    if report._common_dir is not None:
        paths.append(os.path.join(report._common_dir, b"config"))
    if report._git_dir is not None:
        worktree_config = os.path.join(report._git_dir, b"config.worktree")
        if worktree_config not in paths:
            paths.append(worktree_config)
    return paths


# --- Tracked paths ---------------------------------------------------------


def _inspect_tracked(report, runner):
    """Return the tracked path list as bytes, or None if it is unavailable.

    `ls-files --cached` reads the index and reports names. It compares no
    content, so it cannot trigger a filter driver.
    """
    result = runner.run("ls-files", "--cached", "-z")
    if not result.ok:
        return None
    return result.nul_fields()


# --- Topology --------------------------------------------------------------


def _inspect_topology(report, config):
    if report._git_dir is not None and report._common_dir is not None:
        report.topology["linked_worktree"] = _realpath(report._git_dir) != _realpath(
            report._common_dir
        )

    if report.topology["linked_worktree"]:
        report.add(
            f.LINKED_WORKTREE,
            f.FINDING,
            "This is a linked worktree sharing a Git directory with another "
            "worktree.",
        )

    report.topology["sparse_checkout"] = _sparse_state(report, config)
    if report.topology["sparse_checkout"] == "on":
        report.add(
            f.SPARSE_CHECKOUT_ACTIVE,
            f.FINDING,
            "Sparse checkout is enabled, so the worktree does not contain "
            "every tracked path.",
        )
    elif report.topology["sparse_checkout"] == "unknown":
        report.add(
            f.SPARSE_CHECKOUT_UNRESOLVED,
            f.UNKNOWN,
            "A sparse-checkout pattern file is present but the enabling "
            "setting was not found in the repository configuration.",
        )


def _sparse_state(report, config):
    enabled = config.get("core", "sparsecheckout")
    pattern_file = _first_existing(
        report, os.path.join(b"info", b"sparse-checkout")
    )
    if enabled is not None and gitconfig.is_true(enabled):
        return "on"
    if pattern_file:
        return "unknown"
    return "off"


def _first_existing(report, relative):
    for base in (report._git_dir, report._common_dir):
        if base is None:
            continue
        if os.path.exists(os.path.join(base, relative)):
            return True
    return False


def _realpath(path_bytes):
    try:
        return os.path.realpath(path_bytes)
    except OSError:
        return path_bytes


# --- Operations in progress ------------------------------------------------


def _inspect_operations(report):
    seen = []
    for marker, code, summary in _OPERATION_MARKERS:
        if report._git_dir is None:
            break
        if not os.path.exists(os.path.join(report._git_dir, marker)):
            continue
        if code in seen:
            continue
        seen.append(code)
        report.add(
            code,
            f.FINDING,
            summary
            + ". AIQE does not support a bounded completion commit while the "
            "repository is mid-operation.",
        )
    report.operations = sorted(seen)


# --- Commit policy and execution-capable configuration ---------------------


def _inspect_commit_policy(report, config, tracked):
    policy = report.commit_policy

    if config.has_section("include") or config.has_section("includeif"):
        policy["config_include_present"] = True
        report.add(
            f.GIT_CONFIG_INCLUDE_UNRESOLVED,
            f.UNKNOWN,
            "The repository configuration includes another file. Doctor does "
            "not follow include chains, so the effective configuration here "
            "is unresolved.",
        )

    hooks_path = config.get("core", "hookspath")
    if hooks_path:
        policy["hooks_path_configured"] = True
        report.add(
            f.GIT_HOOKS_PATH_CONFIGURED,
            f.FINDING,
            "core.hooksPath is set in the repository configuration, so hooks "
            "are read from a non-default location.",
        )

    if _hooks_present(report, hooks_path):
        policy["hooks_present"] = True
        report.add(
            f.GIT_HOOKS_PRESENT,
            f.FINDING,
            "Executable Git hooks are installed. An active commit hook makes "
            "an AIQE bounded commit unsupported, because AIQE will not "
            "bypass repository governance to obtain one.",
        )

    if gitconfig.is_true(config.get("commit", "gpgsign")) and config.get(
        "commit", "gpgsign"
    ) is not None:
        policy["signing_configured"] = True
        report.add(
            f.COMMIT_SIGNING_CONFIGURED,
            f.FINDING,
            "Commit signing is configured in the repository configuration. "
            "Effective signing policy is resolved later, not by Doctor.",
        )

    if _filter_drivers(config):
        policy["checkin_filter_configured"] = True
        report.add(
            f.CHECKIN_FILTER_CONFIGURED,
            f.FINDING,
            "A check-in filter driver is configured. Git runs it as a child "
            "process when comparing worktree content, so Doctor does not "
            "make that comparison.",
        )

    if config.get("core", "fsmonitor") is not None:
        report.add(
            f.FSMONITOR_CONFIGURED,
            f.FINDING,
            "core.fsmonitor is configured. Git would run it as a child "
            "process during an index refresh; Doctor disables it for its own "
            "Git invocations.",
        )

    if _executable_aliases(config):
        report.add(
            f.EXECUTABLE_ALIAS_CONFIGURED,
            f.FINDING,
            "The repository configuration defines shell-executing Git "
            "aliases.",
        )

    if tracked is not None and _has_submodules(tracked):
        policy["submodules_present"] = True

    attribute_files = _attribute_files(report, tracked)
    if attribute_files:
        policy["tracked_gitattributes"] = True
        report.add(
            f.TRACKED_GITATTRIBUTES,
            f.FINDING,
            "A tracked .gitattributes file is present. It can bind paths to "
            "filter drivers that change content on check-in.",
        )

    binds, readable = _attributes_bind_filter(report, attribute_files)
    policy["attributes_bind_filter"] = binds
    policy["attributes_readable"] = readable


def _hooks_present(report, hooks_path):
    directory = None
    if hooks_path:
        candidate = os.fsencode(hooks_path)
        if not os.path.isabs(candidate) and report._worktree is not None:
            candidate = os.path.join(report._worktree, candidate)
        directory = candidate
    elif report._common_dir is not None:
        directory = os.path.join(report._common_dir, b"hooks")

    if directory is None:
        return False
    try:
        names = os.listdir(directory)
    except OSError:
        return False

    for name in names:
        if name.endswith(b".sample"):
            continue
        full = os.path.join(directory, name)
        try:
            if os.path.isfile(full) and os.access(full, os.X_OK):
                return True
        except OSError:
            continue
    return False


def _filter_drivers(config):
    """Filter drivers that run a command on check-in.

    `clean` and `process` are the check-in directions: Git runs them to turn
    worktree content into index content, which is exactly what a worktree
    comparison triggers. `smudge` runs on check-out and is reported through
    the same finding, because its presence indicates the same configured
    driver.
    """
    drivers = []
    for key in ("clean", "process", "smudge"):
        for name in config.subsection_keys("filter", key):
            if name not in drivers:
                drivers.append(name)
    return drivers


def _executable_aliases(config):
    return [
        key
        for key, value in config.keys_in("alias")
        if value is not None and value.startswith("!")
    ]


def _has_gitattributes(tracked):
    for path in tracked:
        if path.rsplit(b"/", 1)[-1] == b".gitattributes":
            return True
    return False


def _has_submodules(tracked):
    for path in tracked:
        if path.rsplit(b"/", 1)[-1] == b".gitmodules":
            return True
    return False


def _attribute_files(report, tracked):
    """Attributes files Doctor can see, as absolute byte paths.

    Only repository-scope sources: tracked `.gitattributes` at any depth, and
    the repository's own `info/attributes`. Attributes configured outside the
    repository are deliberately not sought - Doctor does not read a user's
    wider environment - and configuration isolation is what stops a driver
    bound there from executing.
    """
    paths = []
    if tracked is not None and report._worktree is not None:
        for path in tracked:
            if path.rsplit(b"/", 1)[-1] == b".gitattributes":
                paths.append(os.path.join(report._worktree, path))
    for base in (report._git_dir, report._common_dir):
        if base is None:
            continue
        candidate = os.path.join(base, b"info", b"attributes")
        if os.path.isfile(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def _attributes_bind_filter(report, attribute_files):
    """Does any visible attributes file assign a filter driver to a path?

    Returns (binds, readable). Reading these files executes nothing: an
    attributes file is data, and Doctor treats it as data.

    The question matters because the binding and the driver definition live
    in different places. A tracked `.gitattributes` saying `*.dat filter=lfs`
    is enough to make a worktree comparison run whatever `filter.lfs.clean`
    happens to be, wherever it is defined. Doctor cannot see every place it
    could be defined, so the binding alone is treated as unsafe.

    A tracked attributes file that is not present in the worktree - under a
    sparse checkout, for example - leaves the question unresolved, which is
    reported as unreadable rather than assumed benign.
    """
    binds = False
    readable = True

    for path in attribute_files:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError:
            readable = False
            continue
        if _attribute_text_binds_filter(raw.decode("utf-8", "replace")):
            binds = True

    return binds, readable


def _attribute_text_binds_filter(text):
    """True when an attributes file assigns a filter driver to any pattern.

    `-filter` and `!filter` unset the attribute rather than selecting a
    driver, so they do not count. Anything of the form `filter=<name>` does.
    """
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for token in line.split():
            if token.startswith("filter="):
                return True
    return False


# --- Working state ---------------------------------------------------------


def _filter_execution_risk(report):
    """Why comparing worktree content here could execute something, or None.

    Configuration isolation removes the risk that comes from outside the
    repository. What remains is the risk that is already inside it, and this
    is the list of ways that happens. Each returns the sentence Doctor will
    show, because "unknown" without a reason is not a diagnosis.
    """
    policy = report.commit_policy

    if policy["checkin_filter_configured"]:
        return (
            "determining it would make Git run the check-in filter configured "
            "in this repository, and Doctor executes nothing the repository "
            "defines"
        )
    if policy["config_include_present"]:
        return (
            "the repository configuration includes another file that Doctor "
            "does not follow, so whether it defines an executable filter "
            "driver is unresolved"
        )
    if policy["attributes_bind_filter"]:
        return (
            "repository attributes bind a path to a filter driver, and the "
            "driver's command can be defined anywhere, so comparing content "
            "could execute it"
        )
    if not policy["attributes_readable"]:
        return (
            "a repository attributes file could not be read, so whether it "
            "binds an executable filter driver is unresolved"
        )
    return None


def _inspect_working_state(report, runner):
    """Count staged, unstaged and untracked paths without executing anything.

    When comparing worktree content could execute something the repository
    selected, the comparison is not made at all. Staged and untracked counts
    are still available - neither reads worktree content through a filter -
    and the unstaged count is reported as unknown.
    """
    state = report.working_state

    risk = _filter_execution_risk(report)
    if risk is not None:
        _working_state_without_content_comparison(report, runner, risk)
        return

    result = runner.run(
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=normal",
        "--no-renames",
        # A submodule's own configuration is repository scope for that
        # submodule, so isolating the superproject's does not protect it:
        # descending into one runs its filters. "dirty" prevents the descent
        # while still reporting a changed submodule pointer, which "all"
        # would also hide.
        "--ignore-submodules=dirty",
    )
    if not result.ok:
        report.add(
            f.WORKING_STATE_UNKNOWN,
            f.UNKNOWN,
            "Git did not report the working state, so staged, unstaged and "
            "untracked counts are unknown.",
        )
        return

    counts = parse_status_porcelain_v2(result.stdout)
    if counts is None:
        report.add(
            f.WORKING_STATE_UNKNOWN,
            f.UNKNOWN,
            "Git reported the working state in a form Doctor does not "
            "recognise, so the counts are unknown.",
        )
        return

    state.update(counts)
    state["determined"] = True
    state["submodule_worktrees_excluded"] = report.commit_policy["submodules_present"]

    if counts["unmerged"]:
        report.add(
            f.UNMERGED_PATHS_PRESENT,
            f.FINDING,
            "The index contains unmerged paths.",
        )


def _working_state_without_content_comparison(report, runner, reason):
    state = report.working_state

    if report.repository["head"] == "unborn":
        cached = runner.run("ls-files", "--cached", "-z")
        if cached.ok:
            state["staged"] = len(cached.nul_fields())
    else:
        staged = runner.run("diff-index", "--cached", "--name-only", "-z", "HEAD")
        if staged.ok:
            state["staged"] = len(staged.nul_fields())

    untracked = runner.run("ls-files", "--others", "--exclude-standard", "-z")
    if untracked.ok:
        state["untracked"] = len(untracked.nul_fields())

    report.add(
        f.WORKING_STATE_UNSTAGED_UNKNOWN,
        f.UNKNOWN,
        "The unstaged count is unknown: " + reason + ".",
    )


# --- AIQE configuration ----------------------------------------------------


def _inspect_aiqe_config(report):
    if report._worktree is None:
        return
    report.aiqe["config_present"] = os.path.isfile(
        os.path.join(report._worktree, b"aiqe.toml")
    )


# --- Agent surface ---------------------------------------------------------


def _inspect_agent_surface(report):
    if report._worktree is None:
        return
    _inspect_claude(report)
    _inspect_codex(report)


def _inspect_claude(report):
    """Detect Claude Code repository configuration.

    Broad is claimed only under a rule that can be stated exactly:

        permissions.defaultMode is "bypassPermissions", or
        permissions.allow contains an entry granting shell access with no
        constraint on the command.

    Anything else yields "present" - not "bounded". Doctor does not certify a
    configuration as safe; it reports the one shape it can recognise without
    interpretation.
    """
    surface = report.agent_surface
    documents = []
    unreadable = False

    for name in (b"settings.json", b"settings.local.json"):
        path = os.path.join(report._worktree, b".claude", name)
        if not os.path.isfile(path):
            continue
        surface["claude_config_present"] = True
        try:
            with open(path, "rb") as handle:
                documents.append(json.loads(handle.read().decode("utf-8", "replace")))
        except (OSError, ValueError):
            unreadable = True

    if not surface["claude_config_present"]:
        if os.path.isfile(os.path.join(report._worktree, b"CLAUDE.md")) or os.path.isdir(
            os.path.join(report._worktree, b".claude")
        ):
            surface["claude_config_present"] = True
            surface["claude_permissions"] = "present"
        return

    if unreadable:
        surface["claude_permissions"] = "unknown"
        report.add(
            f.AGENT_CONFIG_UNREADABLE,
            f.UNKNOWN,
            "A Claude Code settings file is present but could not be parsed, "
            "so its permission surface is unknown.",
        )
        return

    surface["claude_permissions"] = "present"
    for document in documents:
        if _claude_is_broad(document):
            surface["claude_permissions"] = "broad"
            report.add(
                f.CLAUDE_PERMISSIONS_BROAD,
                f.FINDING,
                "Claude Code repository settings grant unconstrained command "
                "execution.",
            )
            return


def _claude_is_broad(document):
    if not isinstance(document, dict):
        return False
    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        return False

    if permissions.get("defaultMode") == "bypassPermissions":
        return True

    allow = permissions.get("allow")
    if isinstance(allow, list):
        for entry in allow:
            if isinstance(entry, str):
                normalised = entry.strip().lower().replace(" ", "")
                if normalised in _CLAUDE_UNCONSTRAINED_BASH:
                    return True
    return False


def _inspect_codex(report):
    """Detect Codex repository configuration.

    Broad is claimed only on an exact top-level assignment, after stripping
    comments:

        approval_policy = "never"
        sandbox_mode = "danger-full-access"

    This is a bounded textual scan, not a TOML evaluation. It can only
    under-report, which is the direction Doctor is allowed to be wrong in: an
    unrecognised file yields "present", never "bounded".
    """
    surface = report.agent_surface
    config_path = os.path.join(report._worktree, b".codex", b"config.toml")
    agents_doc = os.path.join(report._worktree, b"AGENTS.md")

    if os.path.isfile(config_path):
        surface["codex_config_present"] = True
    elif os.path.isdir(os.path.join(report._worktree, b".codex")) or os.path.isfile(
        agents_doc
    ):
        surface["codex_config_present"] = True
        surface["codex_permissions"] = "present"
        return
    else:
        return

    try:
        with open(config_path, "rb") as handle:
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        surface["codex_permissions"] = "unknown"
        report.add(
            f.AGENT_CONFIG_UNREADABLE,
            f.UNKNOWN,
            "A Codex configuration file is present but could not be read, so "
            "its permission surface is unknown.",
        )
        return

    surface["codex_permissions"] = "present"
    if _codex_is_broad(text):
        surface["codex_permissions"] = "broad"
        report.add(
            f.CODEX_PERMISSIONS_BROAD,
            f.FINDING,
            "Codex repository configuration disables the approval or sandbox "
            "boundary.",
        )


def _codex_is_broad(text):
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'").lower()
        for broad_key, broad_value in _CODEX_BROAD_ASSIGNMENTS:
            if key == broad_key and value == broad_value:
                return True
    return False
