"""Negative controls for the Doctor family.

A benchmark that only ever shows the product passing is not measuring
anything. Each control below is a *reference naive diagnostic workflow*: the
obvious way to obtain the same information, written the way a reasonable
implementation would write it. Each one violates a frozen Doctor invariant,
and the harness records whether the violation actually reproduced.

A control that stops reproducing is not a success. It means the control has
decayed - a Git version changed, a fixture drifted - and it must be redesigned
rather than counted as a pass. `control_reproduces_failure` is reported per
control for exactly that reason.

The four controls here are not hypothetical. Every one was observed before the
implementation was written, and each is the direct reason for a specific
decision in `aiqe.gitq` and `aiqe.doctor`:

    index refresh   -> why every invocation carries --no-optional-locks
    fsmonitor       -> why every invocation carries -c core.fsmonitor=false
    check-in filter -> why Doctor declines to compare worktree content at all
    config include  -> why Doctor parses configuration files itself
"""

import subprocess

#: How the naive workflow's violation is detected.
MUTATION = "repository_mutation"
EXECUTION = "repository_defined_execution"
RESOLUTION = "unresolved_configuration_treated_as_authority"


def _run(target, env, *args):
    return subprocess.run(
        ("git",) + args,
        cwd=target,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def naive_status(target, env):
    """The obvious way to read working state: plain `git status`."""
    return _run(target, env, "status", "--porcelain=v2", "-z", "--untracked-files=normal")


def naive_status_locked_only(target, env):
    """`git status` hardened against the index write, and nothing else.

    This is the plausible half-measure: a developer reads that
    `--no-optional-locks` avoids the index write, applies it, and concludes
    the command is now inert.
    """
    return _run(
        target,
        env,
        "--no-optional-locks",
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=normal",
    )


def naive_config_get(target, env):
    """The obvious way to read a setting: ask Git for it.

    Git resolves the whole configuration chain, so an `include` directive
    pointing anywhere on the filesystem silently contributes to the answer.
    """
    return _run(target, env, "config", "--get", "core.hooksPath")


CONTROLS = [
    {
        "id": "NC_DOCTOR_INDEX_REFRESH",
        "description": (
            "A plain `git status` on a stat-dirty, content-identical worktree "
            "refreshes cached stat information and rewrites .git/index. The "
            "command is universally treated as diagnostic; it is not read-only."
        ),
        "fixture": "stat_dirty_repository",
        "invariant": "DOCTOR_REPOSITORY_MUTATIONS = 0",
        "detects": MUTATION,
        "naive": naive_status,
    },
    {
        "id": "NC_DOCTOR_FSMONITOR_EXECUTION",
        "description": (
            "`git status` runs the core.fsmonitor command as a child process "
            "during the index refresh. --no-optional-locks does not prevent it, "
            "so a workflow that stops at that flag still executes a command the "
            "repository defined."
        ),
        "fixture": "fsmonitor_configured",
        "invariant": "DOCTOR_REPOSITORY_DEFINED_EXECUTIONS = 0",
        "detects": EXECUTION,
        "naive": naive_status_locked_only,
    },
    {
        "id": "NC_DOCTOR_CHECKIN_FILTER_EXECUTION",
        "description": (
            "When .gitattributes binds a path to a configured clean filter and "
            "the content changed without changing length, `git status` must read "
            "the file through the filter to answer at all - executing the "
            "repository's own command. No Git flag prevents this, which is why "
            "Doctor does not ask the question."
        ),
        "fixture": "checkin_filter_configured",
        "invariant": "DOCTOR_REPOSITORY_DEFINED_EXECUTIONS = 0",
        "detects": EXECUTION,
        "naive": naive_status_locked_only,
    },
    {
        "id": "NC_DOCTOR_CONFIG_INCLUDE_RESOLUTION",
        "description": (
            "Asking Git for a configuration value follows include and includeIf "
            "chains, so a value defined in an arbitrary included file is returned "
            "as though it were established local configuration. Doctor reports "
            "such a chain as unresolved instead."
        ),
        "fixture": "config_include_present",
        "invariant": "Doctor does not follow include chains on first contact",
        "detects": RESOLUTION,
        "naive": naive_config_get,
        "leaked_value": "elsewhere",
    },
]


def violated(control, observation):
    """Did the naive workflow actually breach the invariant this time?"""
    if control["detects"] == MUTATION:
        return observation["repository_mutations"] > 0
    if control["detects"] == EXECUTION:
        return observation["repository_defined_executions"] > 0
    if control["detects"] == RESOLUTION:
        return control["leaked_value"] in observation["naive_stdout"]
    raise ValueError("unknown control detection mode %r" % (control["detects"],))
