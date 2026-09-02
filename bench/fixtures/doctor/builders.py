"""Deterministic synthetic fixtures for the Doctor benchmark family.

Every fixture is built from nothing by the code in this file. No fixture is a
copy of a real repository, none contains real project material, and none
requires the network. Building the same case twice produces the same
repository state, so an expected outcome recorded once stays meaningful.

Several fixtures install a *canary*: a script that creates a marker file the
moment it is executed. The marker is written outside the repository, so
firing it is not itself a repository mutation and cannot be confused with
one. The harness asserts that Doctor left every canary unfired. That is the
difference between claiming Doctor executes nothing the repository defines
and showing it.

These builders are shared by the test suite and by the benchmark runner. They
are the retained artifact: a benchmark result whose fixtures were thrown away
is a prose claim, not evidence.
"""

import os
import subprocess
import sys

#: A fixture that has not finished in this many seconds is a broken fixture.
BUILD_TIMEOUT_SECONDS = 60


#: Applied to every fixture-construction invocation.
#:
#: Git may start background maintenance after a write, and that process
#: outlives the command: it creates `.git/objects/maintenance.lock` and
#: removes it when it finishes. If it finishes during a measurement window,
#: the harness sees a repository file disappear and attributes it to Doctor.
#: That is a false reading, and it was observed. Fixtures are built quiescent
#: instead, so a repository that changes during measurement means something
#: real changed it.
_NO_BACKGROUND_MAINTENANCE = ("-c", "gc.auto=0", "-c", "maintenance.auto=false")


def git(cwd, *args, **kwargs):
    """Run Git while building a fixture.

    Fixture construction is allowed to write - that is what building a
    repository means. Only the Doctor run under measurement must not.
    """
    check = kwargs.pop("check", True)
    env = kwargs.pop("env", None)
    proc = subprocess.run(
        ("git",) + _NO_BACKGROUND_MAINTENANCE + args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=BUILD_TIMEOUT_SECONDS,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "fixture git %s failed: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace"))
        )
    return proc


def write(path, text, mode=None):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(text)
    if mode is not None:
        os.chmod(path, mode)


def canary(path, marker, body="exit 0"):
    """Install an executable script that records the fact that it ran.

    The default body exits immediately. A filter driver needs to pass content
    through instead, so it overrides the body.
    """
    write(
        path,
        "#!/bin/sh\n: > %s\n%s\n" % (_quote(marker), body),
        mode=0o755,
    )


def _quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def init_repo(root, env):
    os.makedirs(root)
    git(root, "init", "--quiet", "--initial-branch=main", env=env)
    git(root, "config", "user.name", "AIQE Fixture", env=env)
    git(root, "config", "user.email", "fixture@example.invalid", env=env)
    git(root, "config", "commit.gpgsign", "false", env=env)
    return root


def commit_all(root, message, env):
    git(root, "add", "--all", env=env)
    git(root, "commit", "--quiet", "--message", message, env=env)


def base_repo(root, env):
    """A repository with one commit and two tracked files."""
    init_repo(root, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 1\n")
    write(os.path.join(root, "README.md"), "fixture\n")
    commit_all(root, "base", env)
    return root


def conflicted_base(root, env):
    """Two divergent branches that cannot merge cleanly.

    Used by the merge, rebase and cherry-pick fixtures so that all three
    reach a genuine mid-operation state rather than a simulated one.
    """
    init_repo(root, env)
    write(os.path.join(root, "signal.py"), "VALUE = 0\n")
    commit_all(root, "base", env)

    git(root, "checkout", "--quiet", "-b", "feature", env=env)
    write(os.path.join(root, "signal.py"), "VALUE = 1\n")
    commit_all(root, "feature", env)

    git(root, "checkout", "--quiet", "main", env=env)
    write(os.path.join(root, "signal.py"), "VALUE = 2\n")
    commit_all(root, "mainline", env)
    return root


# --- Individual case builders ---------------------------------------------
#
# Each builder receives the case's isolated root directory and environment,
# and returns the directory Doctor should be pointed at.


def build_normal_repository(case, env):
    return base_repo(case.repo_path, env)


def build_no_aiqe_config(case, env):
    return base_repo(case.repo_path, env)


def build_aiqe_config_present(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "aiqe.toml"), '# fixture\n[project]\nname = "fixture"\n')
    return root


def build_unborn_repository(case, env):
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 1\n")
    git(root, "add", "--", "strategy.py", env=env)
    return root


def build_non_repository(case, env):
    os.makedirs(case.repo_path)
    write(os.path.join(case.repo_path, "notes.txt"), "not a repository\n")
    return case.repo_path


def build_bare_repository(case, env):
    os.makedirs(case.repo_path)
    git(case.repo_path, "init", "--quiet", "--bare", env=env)
    return case.repo_path


def build_detached_head(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 2\n")
    commit_all(root, "second", env)
    git(root, "checkout", "--quiet", "--detach", "HEAD~1", env=env)
    return root


def build_tracked_modification(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 99\n")
    return root


def build_staged_modification(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 99\n")
    git(root, "add", "--", "strategy.py", env=env)
    return root


def build_staged_addition(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "added.py"), "NEW = 1\n")
    git(root, "add", "--", "added.py", env=env)
    return root


def build_staged_deletion(case, env):
    root = base_repo(case.repo_path, env)
    git(root, "rm", "--quiet", "--", "README.md", env=env)
    return root


def build_untracked_file(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "scratch.py"), "TEMP = 1\n")
    return root


def build_mixed_working_state(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 5\n")
    git(root, "add", "--", "strategy.py", env=env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 6\n")
    write(os.path.join(root, "README.md"), "changed\n")
    write(os.path.join(root, "scratch.py"), "TEMP = 1\n")
    return root


def build_stat_dirty_repository(case, env):
    """Tracked content rewritten byte-identically, with a newer timestamp.

    This is the state in which a plain `git status` rewrites the index. It
    exists so that the zero-write claim is measured where it is actually
    hard, not only where it is easy.
    """
    root = base_repo(case.repo_path, env)
    target = os.path.join(root, "strategy.py")
    write(target, "SIGNAL = 1\n")
    future = os.path.getmtime(target) + 10
    os.utime(target, (future, future))
    return root


def build_merge_in_progress(case, env):
    root = conflicted_base(case.repo_path, env)
    git(root, "merge", "feature", check=False, env=env)
    return root


def build_rebase_in_progress(case, env):
    root = conflicted_base(case.repo_path, env)
    git(root, "checkout", "--quiet", "feature", env=env)
    git(root, "rebase", "main", check=False, env=env)
    return root


def build_cherry_pick_in_progress(case, env):
    root = conflicted_base(case.repo_path, env)
    git(root, "cherry-pick", "feature", check=False, env=env)
    return root


def build_linked_worktree(case, env):
    root = base_repo(case.repo_path, env)
    linked = os.path.join(case.root, "linked")
    git(root, "worktree", "add", "--quiet", "-b", "side", linked, env=env)
    return linked


def build_sparse_checkout(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "keep", "kept.py"), "KEPT = 1\n")
    write(os.path.join(root, "drop", "dropped.py"), "DROPPED = 1\n")
    commit_all(root, "trees", env)
    git(root, "sparse-checkout", "set", "keep", env=env)
    return root


def build_tracked_gitattributes(case, env):
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 1\n")
    write(os.path.join(root, ".gitattributes"), "*.py text\n")
    commit_all(root, "base", env)
    return root


def build_local_hooks_path(case, env):
    root = base_repo(case.repo_path, env)
    os.makedirs(os.path.join(root, "githooks"))
    git(root, "config", "core.hooksPath", "githooks", env=env)
    return root


def build_installed_hook(case, env):
    """An executable pre-commit hook that fires a canary if it is ever run."""
    root = base_repo(case.repo_path, env)
    canary(os.path.join(root, ".git", "hooks", "pre-commit"), case.marker("hook"))
    return root


def build_commit_signing_configured(case, env):
    root = base_repo(case.repo_path, env)
    git(root, "config", "commit.gpgsign", "true", env=env)
    return root


def build_config_include_present(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(case.root, "included.cfg"),
        "[core]\n\thooksPath = elsewhere\n",
    )
    with open(os.path.join(root, ".git", "config"), "a") as handle:
        handle.write("[include]\n\tpath = ../../included.cfg\n")
    return root


def build_config_include_if_present(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(case.root, "included.cfg"),
        "[commit]\n\tgpgsign = true\n",
    )
    with open(os.path.join(root, ".git", "config"), "a") as handle:
        handle.write('[includeIf "gitdir:/"]\n\tpath = ../../included.cfg\n')
    return root


def build_checkin_filter_configured(case, env):
    """A configured clean filter, bound by .gitattributes, with a canary.

    The tracked file is modified to different content of the *same length*.
    That is the case in which Git cannot decide whether the file changed from
    stat information alone and must read the content through the filter -
    which means running the repository's own command.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("filter")
    canary(os.path.join(root, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(root, ".gitattributes"), "*.dat filter=fixture\n")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)
    git(root, "config", "filter.fixture.clean", "./cleanfilter.sh", env=env)
    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def build_fsmonitor_configured(case, env):
    """A configured fsmonitor hook, with a canary, and a stat-dirty worktree.

    Git invokes fsmonitor during an index refresh. `--no-optional-locks`
    alone does not prevent it.
    """
    root = base_repo(case.repo_path, env)
    marker = case.marker("fsmonitor")
    canary(os.path.join(root, "fsmonitor.sh"), marker)
    git(root, "config", "core.fsmonitor", "./fsmonitor.sh", env=env)
    write(os.path.join(root, "strategy.py"), "SIGNAL = 7\n")
    return root


def build_executable_alias_configured(case, env):
    root = base_repo(case.repo_path, env)
    marker = case.marker("alias")
    git(root, "config", "alias.status", "!: > %s" % marker, env=env)
    git(root, "config", "alias.rev-parse", "!: > %s" % marker, env=env)
    return root


def build_claude_bounded(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(root, ".claude", "settings.json"),
        '{\n  "permissions": {\n    "allow": ["Bash(git status:*)", "Read(src/**)"],\n'
        '    "deny": ["Bash(rm:*)"]\n  }\n}\n',
    )
    return root


def build_claude_broad(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(root, ".claude", "settings.json"),
        '{\n  "permissions": {\n    "defaultMode": "bypassPermissions",\n'
        '    "allow": ["Bash"]\n  }\n}\n',
    )
    return root


def build_claude_unreadable(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, ".claude", "settings.json"), "{ this is not json\n")
    return root


def build_codex_bounded(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(root, ".codex", "config.toml"),
        'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n',
    )
    return root


def build_codex_broad(case, env):
    root = base_repo(case.repo_path, env)
    write(
        os.path.join(root, ".codex", "config.toml"),
        '# fixture\napproval_policy = "never"\nsandbox_mode = "danger-full-access"\n',
    )
    return root


# --- Adversarial external-configuration cases ------------------------------
#
# The defining property of this group: the repository *selects* an executable,
# and the definition of that executable lives somewhere Doctor deliberately
# does not read. Inspecting the repository's own configuration and concluding
# "no filter here" is not enough, and these fixtures are what proved it.
#
# The global scope is real here, not simulated. The harness gives each case an
# isolated GIT_CONFIG_GLOBAL, and these builders write into it, so Git sees
# genuine global configuration while the developer's own stays untouched.


def append_global_config(env, text):
    with open(env["GIT_CONFIG_GLOBAL"], "a") as handle:
        handle.write(text)


def build_global_filter_canary(case, env):
    """Filter driver defined in GLOBAL config; binding tracked in the repo.

    The modification keeps the file's length, so Git cannot decide from stat
    information alone and must read content through the driver to answer.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("global-filter")
    canary(os.path.join(root, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(root, ".gitattributes"), "*.dat filter=external\n")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)
    append_global_config(
        env, '[filter "external"]\n\tclean = %s/cleanfilter.sh\n' % (root,)
    )
    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def build_global_fsmonitor_canary(case, env):
    """core.fsmonitor supplied by GLOBAL config rather than by the repository."""
    root = base_repo(case.repo_path, env)
    marker = case.marker("global-fsmonitor")
    canary(os.path.join(root, "fsmonitor.sh"), marker)
    append_global_config(env, "[core]\n\tfsmonitor = %s/fsmonitor.sh\n" % (root,))
    write(os.path.join(root, "strategy.py"), "SIGNAL = 7\n")
    return root


def build_local_include_filter_canary(case, env):
    """Local config includes a file that defines an executable filter driver.

    Configuration isolation cannot help here: an include inside the
    repository's own config is repository scope. Only refusing to compare
    worktree content does.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("include-filter")
    canary(os.path.join(root, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(root, ".gitattributes"), "*.dat filter=included\n")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)

    included = os.path.join(case.root, "included-filter.cfg")
    write(included, '[filter "included"]\n\tclean = %s/cleanfilter.sh\n' % (root,))
    with open(os.path.join(root, ".git", "config"), "a") as handle:
        handle.write("[include]\n\tpath = %s\n" % (included,))

    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def build_global_attributes_filter_canary(case, env):
    """The BINDING lives outside the repository too, via core.attributesFile.

    Doctor cannot see this binding at all, which is precisely why the defence
    has to be configuration isolation rather than detection.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("global-attributes")
    canary(os.path.join(root, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)

    attributes = os.path.join(case.root, "global-attributes")
    write(attributes, "*.dat filter=externalattr\n")
    append_global_config(
        env,
        "[core]\n\tattributesFile = %s\n" % (attributes,)
        + '[filter "externalattr"]\n\tclean = %s/cleanfilter.sh\n' % (root,),
    )
    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def build_external_attributes_local_filter_canary(case, env):
    """Binding from the default external attributes path, driver defined locally.

    Git reads $XDG_CONFIG_HOME/git/attributes whether or not any configuration
    points at it, so isolation does not remove the binding. The driver is in
    local config, which is what the static refusal is for.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("external-attributes")
    canary(os.path.join(root, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)

    attributes = os.path.join(env["XDG_CONFIG_HOME"], "git", "attributes")
    write(attributes, "*.dat filter=xdgattr\n")
    git(root, "config", "filter.xdgattr.clean", "./cleanfilter.sh", env=env)
    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def build_submodule_filter_canary(case, env):
    """A submodule whose OWN local config defines an executable filter.

    A submodule's configuration is repository scope for that submodule, so the
    superproject cannot isolate it away. An unguarded `git status` descends
    into the submodule worktree and runs it.
    """
    submodule = os.path.join(case.root, "submodule")
    init_repo(submodule, env)
    marker = case.marker("submodule-filter")
    canary(os.path.join(submodule, "cleanfilter.sh"), marker, body="exec cat")
    write(os.path.join(submodule, ".gitattributes"), "*.dat filter=inner\n")
    write(os.path.join(submodule, "series.dat"), "aaaa\n")
    commit_all(submodule, "submodule base", env)

    root = base_repo(case.repo_path, env)
    git(root, "-c", "protocol.file.allow=always", "submodule", "--quiet",
        "add", submodule, "vendor", env=env)
    git(root, "commit", "--quiet", "--message", "add submodule", env=env)

    checkout = os.path.join(root, "vendor")
    git(checkout, "config", "filter.inner.clean", "./cleanfilter.sh", env=env)
    write(os.path.join(checkout, "series.dat"), "bbbb\n")
    return root


#: Command-scope configuration injected into the Doctor process environment.
#: This is the documented mechanism, not a trick: Git reads these and they
#: outrank every configuration file.
ENV_COMMAND_CONFIG_DRIVER = "envdriver"


def build_env_command_config_filter_canary(case, env):
    """Filter driver injected through the process environment, not a file.

    The binding lives in an external attributes file, so the static refusal
    does not apply and the case tests only the thing it is meant to: whether
    silencing the configuration *files* is enough. It is not. Git accepts
    configuration at command scope from the environment, and it outranks every
    file, so pointing GIT_CONFIG_GLOBAL at the null device does nothing about
    it.

    The builder mutates the environment the harness will hand to Doctor, which
    is exactly the threat: Doctor inherits whatever it is launched with.
    """
    root = init_repo(case.repo_path, env)
    marker = case.marker("env-command-config")
    driver = os.path.join(root, "cleanfilter.sh")
    canary(driver, marker, body="exec cat")

    attributes = os.path.join(env["XDG_CONFIG_HOME"], "git", "attributes")
    write(attributes, "*.dat filter=%s\n" % (ENV_COMMAND_CONFIG_DRIVER,))

    write(os.path.join(root, "series.dat"), "aaaa\n")
    commit_all(root, "base", env)
    write(os.path.join(root, "series.dat"), "bbbb\n")

    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "filter.%s.clean" % (ENV_COMMAND_CONFIG_DRIVER,)
    env["GIT_CONFIG_VALUE_0"] = driver
    return root


# --- Arbitrary-byte path ---------------------------------------------------

# Filenames are byte strings on POSIX. Only some filesystems additionally
# require them to be well-formed text; APFS does, which is why this case is
# restricted to Linux rather than skipped everywhere.
NON_UTF8_TRACKED = b"tracked-\xe9\xff.dat"
NON_UTF8_STAGED = b"staged-\xc3.dat"
NON_UTF8_UNTRACKED = b"untracked-\xfe\xfe.dat"


def build_non_utf8_path(case, env):
    """A real repository containing paths that are not valid UTF-8.

    Not synthetic bytes handed to a parser: Git actually records these names,
    and Doctor reads them back through the whole pipeline. If any layer
    decoded a path instead of carrying the bytes, this is where it would
    raise.

    A filesystem that refuses the name fails the build loudly. This proof must
    not quietly degrade into a weaker one.
    """
    root = init_repo(case.repo_path, env)
    encoded_root = os.fsencode(root)

    try:
        with open(os.path.join(encoded_root, NON_UTF8_TRACKED), "wb") as handle:
            handle.write(b"aaaa\n")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            "this filesystem refuses a non-UTF-8 filename (%s). The "
            "arbitrary-byte path proof cannot be produced here, and must not "
            "be silently downgraded to a parser-only test." % (exc,)
        )

    git(root, "add", "--all", env=env)
    git(root, "commit", "--quiet", "--message", "byte paths", env=env)

    # One modification, one staged addition, one untracked file - each named
    # in bytes that no decoder would survive.
    with open(os.path.join(encoded_root, NON_UTF8_TRACKED), "wb") as handle:
        handle.write(b"bbbbbb\n")
    with open(os.path.join(encoded_root, NON_UTF8_STAGED), "wb") as handle:
        handle.write(b"staged\n")
    git(root, "add", "--", os.path.join(encoded_root, NON_UTF8_STAGED), env=env)
    with open(os.path.join(encoded_root, NON_UTF8_UNTRACKED), "wb") as handle:
        handle.write(b"untracked\n")
    return root


def platform_supports(platform):
    """Is a platform-restricted case applicable to the machine running it?"""
    if platform is None:
        return True
    if platform == "linux":
        return sys.platform.startswith("linux")
    raise ValueError("unknown fixture platform restriction %r" % (platform,))


#: Case identifier to builder. The expected outcome for each identifier lives
#: in cases.json, so that expectations are data a reviewer can read rather
#: than assertions buried in code.
BUILDERS = {
    "normal_repository": build_normal_repository,
    "no_aiqe_config": build_no_aiqe_config,
    "aiqe_config_present": build_aiqe_config_present,
    "unborn_repository": build_unborn_repository,
    "non_repository": build_non_repository,
    "bare_repository": build_bare_repository,
    "detached_head": build_detached_head,
    "tracked_modification": build_tracked_modification,
    "staged_modification": build_staged_modification,
    "staged_addition": build_staged_addition,
    "staged_deletion": build_staged_deletion,
    "untracked_file": build_untracked_file,
    "mixed_working_state": build_mixed_working_state,
    "stat_dirty_repository": build_stat_dirty_repository,
    "merge_in_progress": build_merge_in_progress,
    "rebase_in_progress": build_rebase_in_progress,
    "cherry_pick_in_progress": build_cherry_pick_in_progress,
    "linked_worktree": build_linked_worktree,
    "sparse_checkout": build_sparse_checkout,
    "tracked_gitattributes": build_tracked_gitattributes,
    "local_hooks_path": build_local_hooks_path,
    "installed_hook": build_installed_hook,
    "commit_signing_configured": build_commit_signing_configured,
    "config_include_present": build_config_include_present,
    "config_include_if_present": build_config_include_if_present,
    "checkin_filter_configured": build_checkin_filter_configured,
    "fsmonitor_configured": build_fsmonitor_configured,
    "executable_alias_configured": build_executable_alias_configured,
    "claude_bounded": build_claude_bounded,
    "claude_broad": build_claude_broad,
    "claude_unreadable": build_claude_unreadable,
    "codex_bounded": build_codex_bounded,
    "codex_broad": build_codex_broad,
    "global_filter_canary": build_global_filter_canary,
    "global_fsmonitor_canary": build_global_fsmonitor_canary,
    "local_include_filter_canary": build_local_include_filter_canary,
    "global_attributes_filter_canary": build_global_attributes_filter_canary,
    "external_attributes_local_filter_canary": build_external_attributes_local_filter_canary,
    "submodule_filter_canary": build_submodule_filter_canary,
    "env_command_config_filter_canary": build_env_command_config_filter_canary,
    "non_utf8_path": build_non_utf8_path,
}
