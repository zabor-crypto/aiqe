"""Deterministic fixtures and scenarios for the Task benchmark family.

Every fixture is built from nothing by the code in this file, and every task
operation runs through the real command-line entry point as a subprocess.
That is deliberate. Concurrency, crash-atomicity and byte-preserving argv
cannot be measured in-process, and putting every case through the same door
means no case is proven against a path the user does not take.

A scenario is two functions. `build` constructs the repository - which is
allowed to write - and `operate` performs the task operations while the
harness watches. The split is what makes the before/after snapshot mean
something.
"""

import base64
import json
import os
import subprocess
import sys

from ..repobuild import (  # noqa: F401  (re-exported: scenarios use these names)
    canary,
    commit_all,
    git,
    init_repo,
    platform_supports,
    write,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SOURCE = os.path.join(ROOT, "src")

if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

from aiqe import taskstate  # noqa: E402
from aiqe.textsafe import display_bytes, is_safe  # noqa: E402

CLI_TIMEOUT_SECONDS = 60


# --- Driving the real product ----------------------------------------------


def run_cli(cwd, env, *arguments):
    """Invoke the real AIQE entry point as a subprocess.

    Arguments may be bytes. On POSIX, byte arguments pass through unchanged,
    which is the only way to declare a path whose name is not valid text - and
    the only way to prove the whole pipeline carries it.
    """
    child = dict(env)
    child["PYTHONPATH"] = SOURCE
    argv = [sys.executable, "-m", "aiqe"]
    argv.extend(arguments)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=child,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=CLI_TIMEOUT_SECONDS,
    )


def spawn_cli(cwd, env, *arguments):
    """Start the entry point without waiting, for the concurrency case."""
    child = dict(env)
    child["PYTHONPATH"] = SOURCE
    argv = [sys.executable, "-m", "aiqe"]
    argv.extend(arguments)
    return subprocess.Popen(
        argv,
        cwd=cwd,
        env=child,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_dirs(worktree, env):
    """(per-worktree Git directory, common Git directory), both absolute.

    In a linked worktree `.git` is a file pointing at
    `<main>/.git/worktrees/<name>`, and the two differ - which is what gives
    the two worktrees distinct machine-local keys.
    """
    result = git(
        worktree, "rev-parse", "--git-dir", "--git-common-dir", env=env, check=False
    )
    resolved = []
    for line in result.stdout.decode("utf-8", "surrogateescape").splitlines():
        path = line.strip()
        if not os.path.isabs(path):
            path = os.path.join(worktree, path)
        resolved.append(os.path.normpath(path))
    return resolved[0], resolved[1]


def derived_key(worktree, env):
    """This worktree's machine-local directory token, or None before any write.

    Derived through the product's own locator rather than a second copy of the
    construction: a fixture that computed the key differently would test the
    fixture.
    """
    salt = taskstate.read_salt(env)
    if salt is None:
        return None
    git_dir, common_dir = git_dirs(worktree, env)
    return taskstate.derive_key(salt, common_dir, git_dir)


def state_directory(worktree, env):
    key = derived_key(worktree, env)
    if key is None:
        return None
    return taskstate.worktree_state_directory(key, env)


def state_path(worktree, env):
    directory = state_directory(worktree, env)
    if directory is None:
        return None
    return os.path.join(directory, "task.json")


def salt_exists(env):
    return os.path.exists(taskstate.salt_path(env))


def state_root_exists(env):
    return os.path.exists(taskstate.state_root(env))


def read_active(worktree, env):
    """The active task record as the product wrote it, or None."""
    path = state_path(worktree, env)
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def owned_display(record):
    """Owned paths as escaped display text: reviewable, and injective."""
    if record is None:
        return []
    return [
        display_bytes(base64.b64decode(entry["path_b64"]))
        for entry in record["owned_paths"]
    ]


def owned_raw(record):
    if record is None:
        return []
    return [base64.b64decode(entry["path_b64"]) for entry in record["owned_paths"]]


def terminal_safe(*completed):
    """No control character may reach the terminal from user-supplied data."""
    for process in completed:
        for stream in (process.stdout, process.stderr):
            text = stream.decode("utf-8", "surrogateescape")
            for line in text.splitlines():
                if not is_safe(line):
                    return False
    return True


def base_repo(root, env):
    """A repository with one commit and a little structure."""
    init_repo(root, env)
    write(os.path.join(root, "src", "strategy.py"), "SIGNAL = 1\n")
    write(os.path.join(root, "tests", "test_strategy.py"), "def test(): pass\n")
    commit_all(root, "base", env)
    return root


def _lifecycle(case, env, target, *owned):
    """start, status, end - and what the state looked like in between."""
    arguments = []
    for path in owned:
        arguments.extend([b"--own", path])
    started = run_cli(target, env, b"task", b"start", *arguments)
    record = read_active(target, env)
    shown = run_cli(target, env, b"task")
    ended = run_cli(target, env, b"task", b"end")
    return {
        "exit_codes": [started.returncode, shown.returncode, ended.returncode],
        "owned_while_active": owned_display(record),
        "digest_while_active": None if record is None else record["owned_pathset_digest"],
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(started, shown, ended),
    }


# --- Scenarios -------------------------------------------------------------


def build_base(case, env):
    return base_repo(case.repo_path, env)


def operate_simple_file(case, env, target):
    return _lifecycle(case, env, target, b"src/strategy.py")


def operate_existing_directory_refused(case, env, target):
    """v1 owns an exact pathset. A directory declaration has no meaning in it."""
    refused = run_cli(target, env, b"task", b"start", b"--own", b"src")
    return {
        "exit_codes": [refused.returncode],
        "active_after_end": read_active(target, env) is not None,
        "refusal_names_the_directory": b"exists as a directory" in refused.stderr,
        "terminal_safe": terminal_safe(refused),
    }


def operate_nonexistent_path(case, env, target):
    """Scope is a declaration. The path need not exist yet - usually it does not."""
    observation = _lifecycle(case, env, target, b"src/new_module.py")
    observation["declared_path_exists"] = os.path.exists(
        os.path.join(target, "src", "new_module.py")
    )
    return observation


def operate_duplicate_declaration_refused(case, env, target):
    """Two spellings of one path in one declaration is a refusal, not a merge."""
    refused = run_cli(
        target, env, b"task", b"start",
        b"--own", b"src/strategy.py", b"--own", b"./src/strategy.py",
    )
    return {
        "exit_codes": [refused.returncode],
        "active_after_end": read_active(target, env) is not None,
        "salt_created": salt_exists(env),
        "terminal_safe": terminal_safe(refused),
    }


def operate_lexical_parent_and_child(case, env, target):
    """Two distinct paths. Under exact ownership neither implies the other."""
    return _lifecycle(case, env, target, b"docs", b"docs/guide.md")


def operate_trailing_separator(case, env, target):
    """A trailing separator is not part of the path's identity."""
    return _lifecycle(case, env, target, b"docs//")


def operate_literal_metacharacters(case, env, target):
    """Every one of these is a filename, not a pattern."""
    return _lifecycle(
        case,
        env,
        target,
        b"*",
        b"?",
        b"[abc]",
        b":(top)",
        b":(glob)vendor",
        b"--help",
        b"-a",
    )


def operate_whitespace_names(case, env, target):
    return _lifecycle(
        case, env, target, b"space name", b"tab\tname", b"newline\nname"
    )


def build_subdirectory(case, env):
    root = base_repo(case.repo_path, env)
    return os.path.join(root, "tests")


def operate_subdirectory(case, env, target):
    """A relative path means what it looks like from where it was typed."""
    repository = case.repo_path
    started = run_cli(target, env, b"task", b"start", b"--own", b"../src/strategy.py")
    record = read_active(repository, env)
    ended = run_cli(target, env, b"task", b"end")
    return {
        "exit_codes": [started.returncode, ended.returncode],
        "owned_while_active": owned_display(record),
        "digest_while_active": None if record is None else record["owned_pathset_digest"],
        "active_after_end": read_active(repository, env) is not None,
        "terminal_safe": terminal_safe(started, ended),
    }


def operate_scope_rejections(case, env, target):
    """Declarations AIQE will not accept, and no task left behind."""
    rejected = [
        b"/etc/passwd",
        b"../outside",
        b".",
        b"./",
        b".git",
        b".git/config",
        b"src/../etc",
    ]
    exits = []
    for path in rejected:
        result = run_cli(target, env, b"task", b"start", b"--own", path)
        exits.append(result.returncode)
    return {
        "rejection_exit_codes": exits,
        "active_after_rejections": read_active(target, env) is not None,
    }


def build_foreign_staged(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "foreign.txt"), "not mine\n")
    git(root, "add", "--", "foreign.txt", env=env)
    return root


def operate_foreign_staged(case, env, target):
    """A repository may already have staged work. A task must not disturb it."""
    index = os.path.join(target, ".git", "index")

    def index_state():
        with open(index, "rb") as handle:
            return handle.read()

    def staged():
        result = git(
            target, "diff", "--cached", "--name-only", "-z", env=env, check=False
        )
        return sorted(p for p in result.stdout.split(b"\0") if p)

    before_bytes, before_staged = index_state(), staged()
    observation = _lifecycle(case, env, target, b"src/strategy.py")
    after_bytes, after_staged = index_state(), staged()

    observation["index_unchanged"] = before_bytes == after_bytes
    observation["staged_unchanged"] = before_staged == after_staged
    observation["staged_paths"] = [p.decode("utf-8", "replace") for p in after_staged]
    return observation


def build_execution_canaries(case, env):
    """Everything a repository can point at a command, all at once."""
    root = init_repo(case.repo_path, env)
    canary(
        os.path.join(root, "cleanfilter.sh"), case.marker("filter"), body="exec cat"
    )
    canary(os.path.join(root, "fsmonitor.sh"), case.marker("fsmonitor"))
    write(os.path.join(root, ".gitattributes"), "*.dat filter=taskcanary\n")
    write(os.path.join(root, "series.dat"), "aaaa\n")
    write(os.path.join(root, "src", "strategy.py"), "SIGNAL = 1\n")
    commit_all(root, "base", env)

    git(root, "config", "filter.taskcanary.clean", "./cleanfilter.sh", env=env)
    git(root, "config", "core.fsmonitor", "./fsmonitor.sh", env=env)
    git(root, "config", "alias.status", "!: > %s" % (case.marker("alias"),), env=env)
    git(
        root,
        "config",
        "alias.rev-parse",
        "!: > %s" % (case.marker("alias"),),
        env=env,
    )
    canary(os.path.join(root, ".git", "hooks", "pre-commit"), case.marker("hook"))
    write(os.path.join(root, "series.dat"), "bbbb\n")
    return root


def operate_execution_canaries(case, env, target):
    return _lifecycle(case, env, target, b"src/strategy.py")


def build_linked_worktrees(case, env):
    root = base_repo(case.repo_path, env)
    git(
        root,
        "worktree",
        "add",
        "--quiet",
        "-b",
        "side-a",
        os.path.join(case.root, "worktree-a"),
        env=env,
    )
    git(
        root,
        "worktree",
        "add",
        "--quiet",
        "-b",
        "side-b",
        os.path.join(case.root, "worktree-b"),
        env=env,
    )
    return root


def operate_linked_worktrees(case, env, target):
    """Two linked worktrees, two independent tasks, no collision.

    A naive implementation puts task state in the common Git directory, where
    the two worktrees share one file and therefore one task.
    """
    worktree_a = os.path.join(case.root, "worktree-a")
    worktree_b = os.path.join(case.root, "worktree-b")

    start_a = run_cli(worktree_a, env, b"task", b"start", b"--own", b"src/a.py")
    start_b = run_cli(worktree_b, env, b"task", b"start", b"--own", b"src/b.py")

    record_a = read_active(worktree_a, env)
    record_b = read_active(worktree_b, env)

    end_a = run_cli(worktree_a, env, b"task", b"end")
    after_end_a_b = read_active(worktree_b, env)
    status_b = run_cli(worktree_b, env, b"task")
    end_b = run_cli(worktree_b, env, b"task", b"end")

    common_a = git_dirs(worktree_a, env)[1]
    common_b = git_dirs(worktree_b, env)[1]

    return {
        "exit_codes": [
            start_a.returncode,
            start_b.returncode,
            end_a.returncode,
            status_b.returncode,
            end_b.returncode,
        ],
        "common_dirs_match": os.path.realpath(common_a) == os.path.realpath(common_b),
        "git_dirs_differ": git_dirs(worktree_a, env)[0] != git_dirs(worktree_b, env)[0],
        "derived_keys_differ": derived_key(worktree_a, env)
        != derived_key(worktree_b, env),
        "no_state_inside_git_dirs": not any(
            os.path.exists(os.path.join(directory, "aiqe"))
            for directory in (
                git_dirs(worktree_a, env)[0],
                git_dirs(worktree_b, env)[0],
                common_a,
            )
        ),
        "worktree_a_owned": owned_display(record_a),
        "worktree_b_owned": owned_display(record_b),
        "task_ids_differ": (
            record_a is not None
            and record_b is not None
            and record_a["task_id"] != record_b["task_id"]
        ),
        "b_survives_a_end": owned_display(after_end_a_b),
        "main_worktree_has_no_task": read_active(case.repo_path, env) is None,
        "terminal_safe": terminal_safe(start_a, start_b, end_a, status_b, end_b),
    }


def operate_concurrent_start(case, env, target):
    """Two real processes, one worktree, one winner."""
    processes = [
        spawn_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py"),
        spawn_cli(target, env, b"task", b"start", b"--own", b"tests/test_strategy.py"),
    ]
    outcomes = []
    for process in processes:
        process.communicate()
        outcomes.append(process.returncode)

    record = read_active(target, env)
    valid = 0
    if record is not None and record.get("schema_version") == 3 and record.get("task_id"):
        valid = 1

    return {
        "successes": sum(1 for code in outcomes if code == 0),
        "refusals": sum(1 for code in outcomes if code == 3),
        "unexpected_exits": sum(1 for code in outcomes if code not in (0, 3)),
        "valid_active_records": valid,
        "owned_while_active": owned_display(record),
    }


def _seed_state_directory(case, env, root, filename, contents):
    """Put a file into this worktree's machine-local state directory.

    The salt has to exist for the directory to be derivable at all, so the
    fixture creates one the way the product would - through the product's own
    routine, not a second copy of it.
    """
    taskstate.ensure_salt(env)
    directory = state_directory(root, env)
    taskstate.ensure_state_directory(os.path.basename(directory), env)
    write(os.path.join(directory, filename), contents)
    return root


def build_interrupted_write(case, env):
    """A crash before the atomic rename leaves a temporary file, not a task."""
    root = base_repo(case.repo_path, env)
    # Exactly what a process killed mid-write leaves behind: a partial file
    # under the temporary name, never renamed into place.
    return _seed_state_directory(
        case, env, root, ".task.json.tmp.99999", '{"schema_version": 3, "task_'
    )


def operate_interrupted_write(case, env, target):
    shown = run_cli(target, env, b"task")
    started = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    record = read_active(target, env)
    ended = run_cli(target, env, b"task", b"end")
    return {
        "exit_codes": [shown.returncode, started.returncode, ended.returncode],
        "status_before_recovery_shows_no_task": b"No active task" in shown.stdout,
        "owned_while_active": owned_display(record),
        "digest_while_active": None if record is None else record["owned_pathset_digest"],
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(shown, started, ended),
    }


def build_corrupt_record(case, env):
    root = base_repo(case.repo_path, env)
    return _seed_state_directory(
        case, env, root, "task.json", "this is not a task record"
    )


def operate_corrupt_record(case, env, target):
    """Unknown, not unsupported - and `end` is the documented way out."""
    shown = run_cli(target, env, b"task")
    blocked = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    discarded = run_cli(target, env, b"task", b"end")
    recovered = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    record = read_active(target, env)
    ended = run_cli(target, env, b"task", b"end")
    return {
        "exit_codes": [
            shown.returncode,
            blocked.returncode,
            discarded.returncode,
            recovered.returncode,
            ended.returncode,
        ],
        "owned_while_active": owned_display(record),
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(shown, blocked, discarded, recovered, ended),
    }


def build_unsafe_state_location(case, env):
    """A symlink where this worktree's machine-local state belongs."""
    root = base_repo(case.repo_path, env)
    elsewhere = os.path.join(case.root, "elsewhere")
    os.makedirs(elsewhere)
    taskstate.ensure_salt(env)
    os.symlink(elsewhere, state_directory(root, env))
    return root


def operate_unsafe_state_location(case, env, target):
    started = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    return {
        "exit_codes": [started.returncode],
        "wrote_through_symlink": os.path.exists(
            os.path.join(case.root, "elsewhere", "task.json")
        ),
    }


def build_symlink(case, env):
    root = base_repo(case.repo_path, env)
    os.symlink("src", os.path.join(root, "linkdir"))
    os.symlink("src/strategy.py", os.path.join(root, "linkfile"))
    return root


def operate_symlink_refused(case, env, target):
    """v1 owns regular files. A link is refused as a link, not judged by target.

    Owned-path, checked-content and commit semantics are defined over regular
    files, their creation and their deletion. Accepting a link would put the
    hole in the content binding rather than in the path rules.
    """
    to_file = run_cli(target, env, b"task", b"start", b"--own", b"linkfile")
    to_directory = run_cli(target, env, b"task", b"start", b"--own", b"linkdir")
    return {
        "exit_codes": [to_file.returncode, to_directory.returncode],
        "active_after_end": read_active(target, env) is not None,
        "salt_created": salt_exists(env),
        "terminal_safe": terminal_safe(to_file, to_directory),
    }


def build_special_file(case, env):
    root = base_repo(case.repo_path, env)
    os.mkfifo(os.path.join(root, "pipe"))
    return root


def operate_special_file_refused(case, env, target):
    refused = run_cli(target, env, b"task", b"start", b"--own", b"pipe")
    return {
        "exit_codes": [refused.returncode],
        "active_after_end": read_active(target, env) is not None,
        "salt_created": salt_exists(env),
        "terminal_safe": terminal_safe(refused),
    }


def build_untracked_file(case, env):
    root = base_repo(case.repo_path, env)
    write(os.path.join(root, "scratch.py"), "TEMP = 1\n")
    return root


def operate_untracked_file(case, env, target):
    """Tracked or not makes no difference to a declaration."""
    return _lifecycle(case, env, target, b"scratch.py")


def build_unborn(case, env):
    return init_repo(case.repo_path, env)


def operate_unborn_head_refused(case, env, target):
    """A task records the commit it started from, and there is not one.

    Doctor still works here; the rule is about starting a task.
    """
    started = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    shown = run_cli(target, env, b"task")
    doctored = run_cli(target, env, b"doctor")
    return {
        "exit_codes": [started.returncode, shown.returncode, doctored.returncode],
        "salt_created": salt_exists(env),
        "state_root_created": state_root_exists(env),
        "terminal_safe": terminal_safe(started, shown, doctored),
    }


def build_foreign_staged_count(case, env):
    root = base_repo(case.repo_path, env)
    for name in ("f1.txt", "f2.txt", "f3.txt"):
        write(os.path.join(root, name), "foreign\n")
        git(root, "add", "--", name, env=env)
    return root


def operate_foreign_staged_count(case, env, target):
    """The informational count, and the index it must not disturb.

    This is not the foreign-staged guarantee. The load-bearing before-and-after
    comparison belongs to a future bounded commit; recording a number here does
    not make that comparison.
    """
    index = os.path.join(target, ".git", "index")

    def index_state():
        with open(index, "rb") as handle:
            return handle.read()

    def staged():
        result = git(
            target, "diff", "--cached", "--name-only", "-z", env=env, check=False
        )
        return sorted(p for p in result.stdout.split(b"\0") if p)

    before_bytes, before_staged = index_state(), staged()
    started = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    record = read_active(target, env)
    shown = run_cli(target, env, b"task")
    ended = run_cli(target, env, b"task", b"end")
    after_bytes, after_staged = index_state(), staged()

    return {
        "exit_codes": [started.returncode, shown.returncode, ended.returncode],
        "recorded_staged_count": None
        if record is None
        else record["foreign_staged_count_at_start"],
        "index_unchanged": before_bytes == after_bytes,
        "staged_unchanged": before_staged == after_staged,
        "staged_names_absent_from_output": all(
            b"f1.txt" not in stream
            for process in (started, shown, ended)
            for stream in (process.stdout, process.stderr)
        ),
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(started, shown, ended),
    }


def operate_salt_created_only_on_write(case, env, target):
    """Reads leave the machine exactly as they found it."""
    doctored = run_cli(target, env, b"doctor")
    salt_after_doctor = salt_exists(env)
    shown = run_cli(target, env, b"task")
    salt_after_status = salt_exists(env)
    refused = run_cli(target, env, b"task", b"start", b"--own", b"src")
    salt_after_refusal = salt_exists(env)
    started = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    salt_after_start = salt_exists(env)
    mode = None
    size = None
    if salt_after_start:
        stat = os.stat(taskstate.salt_path(env))
        mode = stat.st_mode & 0o777
        size = stat.st_size
    run_cli(target, env, b"task", b"end")

    return {
        "exit_codes": [
            doctored.returncode,
            shown.returncode,
            refused.returncode,
            started.returncode,
        ],
        "salt_after_doctor": salt_after_doctor,
        "salt_after_status": salt_after_status,
        "salt_after_refused_start": salt_after_refusal,
        "salt_after_start": salt_after_start,
        "salt_mode": mode,
        "salt_bytes": size,
        "terminal_safe": terminal_safe(doctored, shown, refused, started),
    }


_SUPERSEDED_RECORD = (
    '{"schema_version": 2, "ownership_semantics": "exact_literal_pathset_v1", '
    '"task_id": "%s", "aiqe_version": "0.0.0.dev0", '
    '"started_at": "2026-09-01T00:00:00Z", "start_head_state": "commit", '
    '"start_head_sha": null, "owned_paths": [{"path_b64": "c3Jj"}], '
    '"owned_pathset_digest": "sha256:superseded", "label": null}\n' % ("0" * 32,)
)


def build_superseded_schema_record(case, env):
    """An active record written by a build with different state semantics."""
    root = base_repo(case.repo_path, env)
    return _seed_state_directory(case, env, root, "task.json", _SUPERSEDED_RECORD)


def operate_superseded_schema_record(case, env, target):
    """Refused, not reinterpreted, and never silently migrated.

    Reading a version-1 record under exact semantics would quietly narrow a
    live task's authority. There is no migration; `end` discards it and the
    user starts again.
    """
    record_path = state_path(target, env)
    with open(record_path, "rb") as handle:
        before = handle.read()

    shown = run_cli(target, env, b"task")
    blocked = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")

    with open(record_path, "rb") as handle:
        after = handle.read()

    discarded = run_cli(target, env, b"task", b"end")
    restarted = run_cli(target, env, b"task", b"start", b"--own", b"src/strategy.py")
    record = read_active(target, env)
    ended = run_cli(target, env, b"task", b"end")

    return {
        "exit_codes": [
            shown.returncode,
            blocked.returncode,
            discarded.returncode,
            restarted.returncode,
            ended.returncode,
        ],
        "record_untouched_while_refused": before == after,
        "schema_after_restart": None if record is None else record["schema_version"],
        "owned_while_active": owned_display(record),
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(shown, blocked, discarded, restarted, ended),
    }


#: Path components that are valid on POSIX and invalid UTF-8.
NON_UTF8_OWNED = b"src/tracked-\xe9\xff.dat"


def build_non_utf8(case, env):
    root = base_repo(case.repo_path, env)
    encoded = os.path.join(os.fsencode(root), b"src", b"tracked-\xe9\xff.dat")
    try:
        with open(encoded, "wb") as handle:
            handle.write(b"aaaa\n")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            "this filesystem refuses a non-UTF-8 filename (%s). The "
            "arbitrary-byte task proof cannot be produced here, and must not "
            "be silently downgraded." % (exc,)
        )
    return root


def operate_non_utf8(case, env, target):
    """The bytes the user typed are the bytes AIQE stores."""
    started = run_cli(target, env, b"task", b"start", b"--own", NON_UTF8_OWNED)
    record = read_active(target, env)
    shown = run_cli(target, env, b"task")
    ended = run_cli(target, env, b"task", b"end")
    return {
        "exit_codes": [started.returncode, shown.returncode, ended.returncode],
        "owned_while_active": owned_display(record),
        "raw_bytes_roundtrip": owned_raw(record) == [NON_UTF8_OWNED],
        "digest_while_active": None if record is None else record["owned_pathset_digest"],
        "active_after_end": read_active(target, env) is not None,
        "terminal_safe": terminal_safe(started, shown, ended),
    }


SCENARIOS = {
    "simple_file_scope": {"build": build_base, "operate": operate_simple_file},
    "existing_directory_refused": {
        "build": build_base,
        "operate": operate_existing_directory_refused,
    },
    "symlink_refused": {"build": build_symlink, "operate": operate_symlink_refused},
    "superseded_schema_fail_closed": {
        "build": build_superseded_schema_record,
        "operate": operate_superseded_schema_record,
    },
    "nonexistent_future_path": {"build": build_base, "operate": operate_nonexistent_path},
    "duplicate_declaration_refused": {
        "build": build_base,
        "operate": operate_duplicate_declaration_refused,
    },
    "special_file_refused": {
        "build": build_special_file,
        "operate": operate_special_file_refused,
    },
    "untracked_regular_file": {
        "build": build_untracked_file,
        "operate": operate_untracked_file,
    },
    "unborn_head_refused": {"build": build_unborn, "operate": operate_unborn_head_refused},
    "foreign_staged_count_at_start": {
        "build": build_foreign_staged_count,
        "operate": operate_foreign_staged_count,
    },
    "salt_created_only_on_write": {
        "build": build_base,
        "operate": operate_salt_created_only_on_write,
    },
    "lexical_parent_and_child": {
        "build": build_base,
        "operate": operate_lexical_parent_and_child,
    },
    "trailing_separator": {"build": build_base, "operate": operate_trailing_separator},
    "literal_metacharacter_names": {
        "build": build_base,
        "operate": operate_literal_metacharacters,
    },
    "whitespace_names": {"build": build_base, "operate": operate_whitespace_names},
    "subdirectory_invocation": {
        "build": build_subdirectory,
        "operate": operate_subdirectory,
    },
    "scope_rejections": {"build": build_base, "operate": operate_scope_rejections},
    "foreign_staged_preserved": {
        "build": build_foreign_staged,
        "operate": operate_foreign_staged,
    },
    "repository_defined_execution": {
        "build": build_execution_canaries,
        "operate": operate_execution_canaries,
    },
    "linked_worktree_isolation": {
        "build": build_linked_worktrees,
        "operate": operate_linked_worktrees,
    },
    "concurrent_start": {"build": build_base, "operate": operate_concurrent_start},
    "interrupted_write": {
        "build": build_interrupted_write,
        "operate": operate_interrupted_write,
    },
    "corrupt_record_recovery": {
        "build": build_corrupt_record,
        "operate": operate_corrupt_record,
    },
    "unsafe_state_location": {
        "build": build_unsafe_state_location,
        "operate": operate_unsafe_state_location,
    },
    "non_utf8_owned_path": {"build": build_non_utf8, "operate": operate_non_utf8},
}
