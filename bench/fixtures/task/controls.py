"""Negative controls for the Task family.

Each control is a reference naive implementation: the obvious way to build the
same feature, written the way a reasonable implementation would write it. Each
violates something the task boundary promises, and the harness records whether
the violation actually reproduced.

A control that stops reproducing is not a success. It means the control has
decayed and must be redesigned, which is why `control_reproduces_failure` is
recorded per control rather than assumed.

The three here are the reasons for three specific decisions:

    pathspec ownership -> why owned paths are literal data and never reach Git
                          as a pattern
    common-dir state   -> why task state lives in the worktree's own Git
                          directory, not the shared one
    check-then-write   -> why start takes a lock instead of looking first
"""

import json
import os
import subprocess
import sys
import time

from ..repobuild import commit_all, git, init_repo, write
from . import builders

PATHSPEC_EXPANSION = "pathspec_expansion"
SHARED_TASK_STATE = "shared_task_state"
LOST_START_RACE = "lost_start_race"


def _repo_with_metacharacter_names(case, env):
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "alpha.py"), "A = 1\n")
    write(os.path.join(root, "beta.py"), "B = 1\n")
    # A file whose name is literally an asterisk. Legal on POSIX, and the
    # whole point: as a pathspec it means "everything".
    write(os.path.join(root, "*"), "literally named star\n")
    commit_all(root, "base", env)
    return root


def run_pathspec_expansion(case, env):
    """Ownership expressed as a Git pathspec covers paths nobody declared."""
    root = _repo_with_metacharacter_names(case, env)

    naive = git(root, "ls-files", "-z", "--", "*", env=env, check=False)
    naive_matches = sorted(p for p in naive.stdout.split(b"\0") if p)

    started = builders.run_cli(root, env, b"task", b"start", b"--own", b"*")
    record = builders.read_active(root, env)
    builders.run_cli(root, env, b"task", b"end")

    return {
        "naive_matched_count": len(naive_matches),
        "naive_matched": [p.decode("utf-8", "replace") for p in naive_matches],
        "aiqe_start_exit": started.returncode,
        "aiqe_owned": builders.owned_display(record),
    }


def run_shared_task_state(case, env):
    """Task state in the common Git directory gives two worktrees one task."""
    root = builders.base_repo(case.repo_path, env)
    worktree_a = os.path.join(case.root, "worktree-a")
    worktree_b = os.path.join(case.root, "worktree-b")
    git(root, "worktree", "add", "--quiet", "-b", "side-a", worktree_a, env=env)
    git(root, "worktree", "add", "--quiet", "-b", "side-b", worktree_b, env=env)

    def naive_state_file(worktree):
        # The naive choice: the *common* Git directory, which linked worktrees
        # share. It looks repository-local and is not worktree-local.
        common = git(
            worktree, "rev-parse", "--git-common-dir", env=env, check=False
        ).stdout.decode().strip()
        if not os.path.isabs(common):
            common = os.path.join(worktree, common)
        directory = os.path.join(common, "naive-aiqe")
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, "task.json")

    with open(naive_state_file(worktree_a), "w") as handle:
        json.dump({"owned": ["src/a.py"], "worktree": "a"}, handle)

    with open(naive_state_file(worktree_b)) as handle:
        seen_from_b = json.load(handle)

    # And the product, on the same topology.
    builders.run_cli(worktree_a, env, b"task", b"start", b"--own", b"src/a.py")
    aiqe_b = builders.read_active(worktree_b, env)
    builders.run_cli(worktree_a, env, b"task", b"end")

    return {
        "naive_b_sees_a_task": seen_from_b.get("worktree") == "a",
        "aiqe_b_sees_a_task": aiqe_b is not None,
    }


_NAIVE_START = """
import json, os, sys, time
state = os.path.join(sys.argv[1], ".git", "naive-aiqe")
os.makedirs(state, exist_ok=True)
record = os.path.join(state, "task.json")
# Look first, then write. The gap between the two is the whole defect.
if os.path.exists(record):
    sys.exit(3)
time.sleep(0.3)
with open(record, "w") as handle:
    json.dump({"owned": [sys.argv[2]]}, handle)
sys.exit(0)
"""


def run_lost_start_race(case, env):
    """Check-then-write lets two concurrent starts both believe they won."""
    root = builders.base_repo(case.repo_path, env)
    script = os.path.join(case.root, "naive_start.py")
    write(script, _NAIVE_START)

    processes = [
        subprocess.Popen(
            [sys.executable, script, root, owned],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for owned in ("src/a.py", "src/b.py")
    ]
    naive_exits = []
    for process in processes:
        process.communicate()
        naive_exits.append(process.returncode)

    # And the product, on the same repository.
    aiqe = [
        builders.spawn_cli(root, env, b"task", b"start", b"--own", b"src/a.py"),
        builders.spawn_cli(root, env, b"task", b"start", b"--own", b"src/b.py"),
    ]
    aiqe_exits = []
    for process in aiqe:
        process.communicate()
        aiqe_exits.append(process.returncode)
    builders.run_cli(root, env, b"task", b"end")

    return {
        "naive_successes": sum(1 for code in naive_exits if code == 0),
        "aiqe_successes": sum(1 for code in aiqe_exits if code == 0),
        "aiqe_refusals": sum(1 for code in aiqe_exits if code == 3),
    }


CONTROLS = [
    {
        "id": "NC_TASK_PATHSPEC_EXPANSION",
        "description": (
            "Ownership handled as a Git pathspec. A file legally named '*' is a "
            "pattern matching every tracked path, so a declaration that names one "
            "file silently covers the repository. AIQE treats a declared path as "
            "literal data that never reaches Git as a pattern."
        ),
        "invariant": "OWNERSHIP_PATHS_ARE_LITERAL",
        "detects": PATHSPEC_EXPANSION,
        "run": run_pathspec_expansion,
    },
    {
        "id": "NC_TASK_SHARED_WORKTREE_STATE",
        "description": (
            "Task state in the common Git directory. Linked worktrees share it, "
            "so a task started in one worktree is the active task in the other. "
            "AIQE stores task state in the worktree's own Git directory."
        ),
        "invariant": "WORKTREE_A_TASK != WORKTREE_B_TASK",
        "detects": SHARED_TASK_STATE,
        "run": run_shared_task_state,
    },
    {
        "id": "NC_TASK_LOST_START_RACE",
        "description": (
            "Check-then-write task creation. Two concurrent starts both find no "
            "active task, both proceed, and the second overwrites the first - so "
            "a user believes they own a scope they do not. AIQE takes a lock "
            "instead of looking first."
        ),
        "invariant": "CONCURRENT_START_WINNERS = 1",
        "detects": LOST_START_RACE,
        "run": run_lost_start_race,
    },
]


def violated(control, observation):
    """Did the naive implementation actually breach the invariant this time?"""
    if control["detects"] == PATHSPEC_EXPANSION:
        return observation["naive_matched_count"] > 1
    if control["detects"] == SHARED_TASK_STATE:
        return observation["naive_b_sees_a_task"] is True
    if control["detects"] == LOST_START_RACE:
        return observation["naive_successes"] > 1
    raise ValueError("unknown control detection mode %r" % (control["detects"],))
