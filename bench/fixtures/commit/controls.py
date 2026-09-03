"""Negative controls for the BOUNDED_COMMIT family.

Each control is a reference naive implementation: the obvious way to build the
same feature, written the way a reasonable engineer would write it in an
afternoon. Each one produces a result that looks like success and is not
justified, and the harness records whether the failure actually reproduced
this time.

A control that stops reproducing is not good news. It means the control has
decayed and must be redesigned, which is why `control_reproduces_failure` is
measured per control rather than assumed.

The eight here are the reasons for the eight decisions that cost the most to
implement:

    plain `git commit`        -> why the commit is `--only` over an exact
                                 expected pathset
    a pathspec, not a path    -> why every Git call is `--literal-pathspecs`
    check then edit           -> why authority is recomputed immediately
                                 before the first index mutation
    `git add -N` then fail    -> why intent-to-add is transactional and
                                 scope-rolled-back rather than left behind
    a commit hook             -> why an active hook is a refusal instead of
                                 `--no-verify`
    `--no-gpg-sign`           -> why configured signing is a refusal instead
                                 of a bypass
    a clean filter            -> why an owned path bound to an external
                                 filter refuses before anything is hashed
    a concurrent stager       -> why `EXCLUDED` needs a before-and-after
                                 comparison rather than one snapshot
"""

import os
import subprocess
import threading
import time

from . import builders

SHARED_INDEX = "shared_index"
PATHSPEC = "pathspec"
STALE = "stale"
ITA_ROLLBACK = "ita_rollback"
HOOK_POLICY = "hook_policy"
SIGNING_POLICY = "signing_policy"
FILTER_POLICY = "filter_policy"
FOREIGN_RACE = "foreign_race"


# --- Shared helpers --------------------------------------------------------


def _naive_git(root, env, *args, **kwargs):
    """Git as a naive implementation would call it: no literal pathspecs.

    This is not a straw man. `git commit -- <path>` is what almost every tool
    that commits on a user's behalf actually runs.
    """
    return subprocess.run(
        ("git",) + args,
        cwd=root,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def _aiqe_workflow(case, env, root, owned, message="bounded completion",
                   before_commit=None):
    return builders.workflow(
        case, env, root, owned, message=message, before_commit=before_commit
    )


def _changed(root, base, after, env):
    return sorted(
        path.decode("utf-8", "surrogateescape")
        for path in builders.changed_paths(root, base, after, env) or ()
    )


def _fired(case, name):
    return os.path.exists(case.marker(name))


def _twin(case, env, build, run_naive, run_aiqe):
    """Build the same fixture twice and run one implementation against each.

    Two repositories rather than one, because the naive implementation
    commits, and a commit is not something the second run can be given back.
    """
    naive_root = build(case, env, "repo")
    observation = run_naive(case, env, naive_root)
    aiqe_root = build(case, env, "linked")
    observation.update(run_aiqe(case, env, aiqe_root))
    return observation


# --- NC-COMMIT-SHARED-INDEX ------------------------------------------------


def _build_shared_index(case, env, where):
    root = _repo(case, env, where)
    builders.put(root, builders.OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    builders.put(root, b"src/foreign.py", b"FOREIGN = 2\n")
    builders.git(root, "add", "--", "src/foreign.py", env=env)
    return root


def run_shared_index(case, env):
    def naive(case, env, root):
        base = builders.head(root, env)
        # The obvious implementation: stage what you changed, then commit.
        _naive_git(root, env, "add", "--", builders.OWNED_TEXT)
        _naive_git(root, env, "commit", "-m", "naive completion")
        after = builders.head(root, env)
        return {
            "naive_changed_paths": _changed(root, base, after, env),
            "naive_absorbed_foreign_staged": "src/foreign.py"
            in _changed(root, base, after, env),
        }

    def aiqe(case, env, root):
        observed = _aiqe_workflow(case, env, root, [builders.OWNED_TEXT])
        return {
            "aiqe_changed_paths": observed["changed_paths"],
            "aiqe_foreign_staged_preserved": observed["foreign_staged_preserved"],
            "aiqe_verdict": observed["receipt_verdict"],
        }

    return _twin(case, env, _build_shared_index, naive, aiqe)


# --- NC-COMMIT-PATHSPEC ----------------------------------------------------


def _build_pathspec(case, env, where):
    root = _repo(
        case,
        env,
        where,
        committed_files=(
            (b"src/star*.py", b"BASE = 1\n", 0o644),
            (b"src/starDECOY.py", b"BASE = 1\n", 0o644),
        ),
    )
    builders.put(root, b"src/star*.py", b"CHANGED = 1\n")
    builders.put(root, b"src/starDECOY.py", b"DECOY_CHANGED = 1\n")
    return root


def run_pathspec(case, env):
    def naive(case, env, root):
        base = builders.head(root, env)
        # The declared path, handed to Git as an argument. It is a pathspec,
        # and `*` is a wildcard, so the decoy comes with it.
        _naive_git(root, env, "commit", "--only", "-m", "naive", "--", "src/star*.py")
        after = builders.head(root, env)
        changed = _changed(root, base, after, env)
        return {
            "naive_changed_paths": changed,
            "naive_broadened_pathset": len(changed) > 1,
        }

    def aiqe(case, env, root):
        observed = _aiqe_workflow(case, env, root, ["src/star*.py"])
        return {
            "aiqe_changed_paths": observed["changed_paths"],
            "aiqe_verdict": observed["receipt_verdict"],
        }

    return _twin(case, env, _build_pathspec, naive, aiqe)


# --- NC-COMMIT-STALE -------------------------------------------------------


def _build_stale(case, env, where):
    root = _repo(case, env, where)
    builders.put(root, builders.OWNED, b"SIGNAL = 1\nCHECKED = 2\n")
    return root


UNCHECKED = b"SIGNAL = 1\nCHECKED = 2\nUNCHECKED = 3\n"


def run_stale(case, env):
    def naive(case, env, root):
        # Run the checks, then commit. The gap between the two is where the
        # edit lands, and nothing in this shape can see it.
        subprocess.run(
            ["./checks/unit.sh"], cwd=root, env=dict(env), timeout=60,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        builders.put(root, builders.OWNED, UNCHECKED)
        base = builders.head(root, env)
        _naive_git(root, env, "commit", "--only", "-m", "naive", "--",
                   builders.OWNED_TEXT)
        after = builders.head(root, env)
        committed = builders.blob_bytes(root, after, builders.OWNED, env)
        return {
            "naive_committed_unchecked_content": committed == UNCHECKED,
            "naive_commit_created": after != base,
        }

    def aiqe(case, env, root):
        def edit(root, _env):
            builders.put(root, builders.OWNED, UNCHECKED)

        observed = _aiqe_workflow(
            case, env, root, [builders.OWNED_TEXT], before_commit=edit
        )
        return {
            "aiqe_commit_created": observed["commit_created"],
            "aiqe_commit_exit": observed["commit_exit"],
            "aiqe_commit_reasons": observed["commit_reasons"],
            "aiqe_index_unchanged": observed["index_unchanged"],
        }

    return _twin(case, env, _build_stale, naive, aiqe)


# --- NC-COMMIT-ITA-ROLLBACK ------------------------------------------------


def _build_ita(case, env, where):
    root = _repo(
        case, env, where,
        committed_files=((b".gitignore", b"src/ignored.py\n", 0o644),),
    )
    builders.put(root, b"src/created.py", b"CREATED = 1\n")
    builders.put(root, b"src/ignored.py", b"IGNORED = 1\n")
    return root


def run_ita_rollback(case, env):
    def naive(case, env, root):
        # Mark both new files for addition, then commit. The second `add`
        # fails - Git will not add an ignored path - and the first one's
        # index entry is simply left behind.
        _naive_git(root, env, "add", "-N", "--", "src/created.py")
        _naive_git(root, env, "add", "-N", "--", "src/ignored.py")
        staged = builders.index_paths(root, env)
        return {
            "naive_index_residue": "src/created.py" in (staged or []),
        }

    def aiqe(case, env, root):
        before = builders.index_paths(root, env)
        observed = _aiqe_workflow(
            case, env, root, ["src/created.py", "src/ignored.py"]
        )
        after = builders.index_paths(root, env)
        return {
            "aiqe_index_residue": "src/created.py" in (after or []),
            "aiqe_index_unchanged": before == after,
            "aiqe_commit_created": observed["commit_created"],
            "aiqe_commit_exit": observed["commit_exit"],
            "aiqe_commit_reasons": observed["commit_reasons"],
        }

    return _twin(case, env, _build_ita, naive, aiqe)


# --- NC-COMMIT-HOOK-POLICY -------------------------------------------------


def _build_hook(case, env, where):
    root = _repo(case, env, where)
    builders.install_hook(case, root, "pre-commit")
    builders.put(root, builders.OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    return root


def run_hook_policy(case, env):
    def naive(case, env, root):
        _naive_git(root, env, "commit", "--only", "-m", "naive", "--",
                   builders.OWNED_TEXT)
        return {"naive_ran_hook": _fired(case, "hook.pre-commit")}

    def aiqe(case, env, root):
        # A second marker, so the two halves cannot be confused for each
        # other: the naive run's hook firing must not be read as AIQE's.
        builders.canary(
            os.path.join(root, ".git", "hooks", "pre-commit"),
            case.marker("hook.pre-commit.aiqe"),
        )
        observed = _aiqe_workflow(case, env, root, [builders.OWNED_TEXT])
        return {
            "aiqe_ran_hook": _fired(case, "hook.pre-commit.aiqe"),
            "aiqe_commit_created": observed["commit_created"],
            "aiqe_commit_exit": observed["commit_exit"],
            "aiqe_commit_reasons": observed["commit_reasons"],
        }

    return _twin(case, env, _build_hook, naive, aiqe)


# --- NC-COMMIT-SIGNING-POLICY ----------------------------------------------


def _build_signing(case, env, where):
    root = _repo(case, env, where)
    signer = builders.install_signer(case, root)
    builders.git(root, "config", "commit.gpgsign", "true", env=env)
    builders.git(root, "config", "gpg.program", signer, env=env)
    builders.put(root, builders.OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    return root


def run_signing_policy(case, env):
    def naive(case, env, root):
        base = builders.head(root, env)
        # Signing is configured and the signer is not available, so the
        # obvious fix is the one that makes the error go away.
        _naive_git(root, env, "commit", "--only", "--no-gpg-sign", "-m", "naive",
                   "--", builders.OWNED_TEXT)
        after = builders.head(root, env)
        signature = _naive_git(
            root, env, "log", "-1", "--format=%G?"
        ).stdout.decode("ascii", "replace").strip()
        return {
            "naive_commit_created": after != base,
            "naive_commit_signature_state": signature,
            "naive_bypassed_signing_policy": after != base and signature != "G",
        }

    def aiqe(case, env, root):
        observed = _aiqe_workflow(case, env, root, [builders.OWNED_TEXT])
        return {
            "aiqe_commit_created": observed["commit_created"],
            "aiqe_commit_exit": observed["commit_exit"],
            "aiqe_commit_reasons": observed["commit_reasons"],
            "aiqe_ran_signer": _fired(case, "signer"),
        }

    return _twin(case, env, _build_signing, naive, aiqe)


# --- NC-COMMIT-FILTER ------------------------------------------------------


def _build_filter(case, env, where):
    root = _repo(
        case, env, where,
        committed_files=((b".gitattributes", b"*.py filter=canary\n", 0o644),),
    )
    driver = builders.install_filter_driver(case, root, "canary.sh", "filter.clean")
    builders.git(root, "config", "filter.canary.clean", driver, env=env)
    builders.put(root, builders.OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    return root


def run_filter_policy(case, env):
    def naive(case, env, root):
        _naive_git(root, env, "commit", "--only", "-m", "naive", "--",
                   builders.OWNED_TEXT)
        return {"naive_ran_filter": _fired(case, "filter.clean")}

    def aiqe(case, env, root):
        driver = builders.install_filter_driver(
            case, root, "canary.sh", "filter.clean.aiqe"
        )
        builders.git(root, "config", "filter.canary.clean", driver, env=env)
        observed = _aiqe_workflow(case, env, root, [builders.OWNED_TEXT])
        return {
            "aiqe_ran_filter": _fired(case, "filter.clean.aiqe"),
            "aiqe_commit_created": observed["commit_created"],
            "aiqe_commit_exit": observed["commit_exit"],
            "aiqe_commit_reasons": observed["commit_reasons"],
        }

    return _twin(case, env, _build_filter, naive, aiqe)


# --- NC-COMMIT-FOREIGN-RACE ------------------------------------------------

#: How many new owned files the race fixture declares.
#:
#: The number sizes the window this control needs. AIQE proves a completion
#: commit path by path, so a task owning N paths spends N bounded `ls-tree`
#: invocations between the commit and the authoritative POST snapshot. Forty
#: of them is a window measured in seconds, against a single `git add`
#: measured in milliseconds - so the concurrent process lands inside by
#: construction rather than by luck.
RACE_NEW_FILES = 40

RACE_POLL_SECONDS = 0.001
RACE_TIMEOUT_SECONDS = 60.0

#: A control that did not execute is not evidence either way, so a scheduler
#: hiccup that keeps the concurrent process out of the window is retried a
#: bounded number of times rather than being recorded as "the product is
#: fine". The attempt count is reported, so a control that needs its retries
#: is visible rather than quietly passing.
RACE_ATTEMPTS = 3


def _build_race(case, env, where):
    root = _repo(case, env, where)
    for index in range(RACE_NEW_FILES):
        builders.put(root, b"src/new%03d.py" % (index,), b"N = %d\n" % (index,))
    return root


def _stage_foreign_after_the_commit_lands(root, env, base, done):
    """Stage a foreign path inside AIQE's window, after the commit exists.

    The signal is the branch ref moving off the pre-commit HEAD: the
    completion commit has been created, AIQE's authoritative PRE snapshot is
    long since taken, and its POST snapshot has not been.

    Waiting for the commit rather than for the first intent-to-add is what
    makes this a control over the *right* property. Staging during AIQE's own
    index writes contends for `index.lock` and makes AIQE's staging fail,
    which is a different, already-covered behaviour. Here the commit is
    entirely correct - the pathset and the content proofs both pass - and AIQE
    still refuses to call the foreign staged state excluded, because it is not
    what it was.

    Git is executed once before the wait begins. The first spawn of a binary
    on a cold page cache costs far more than the steady-state one, and paying
    that inside the window is how a deterministic control becomes a flaky one.
    """
    _naive_git(root, env, "rev-parse", "--git-dir")
    builders.put(root, b"src/foreign.py", b"FOREIGN = 999\n")
    deadline = time.monotonic() + RACE_TIMEOUT_SECONDS
    while time.monotonic() < deadline and not done.is_set():
        if _ref_moved(root, base):
            break
        time.sleep(RACE_POLL_SECONDS)
    else:
        return False

    while time.monotonic() < deadline:
        completed = _naive_git(root, env, "add", "--", "src/foreign.py")
        if completed.returncode == 0:
            return True
        time.sleep(RACE_POLL_SECONDS)
    return False


def _ref_moved(root, base):
    """Has the branch ref moved off `base`? A file read, not a subprocess."""
    for candidate in (
        os.path.join(root, ".git", "refs", "heads", "main"),
        os.path.join(root, ".git", "HEAD"),
    ):
        try:
            with open(candidate, "rb") as handle:
                value = handle.read().strip()
        except OSError:
            continue
        if value.startswith(b"ref:"):
            continue
        return bool(value) and value.decode("ascii", "replace") != base
    return False


def run_foreign_race(case, env):
    observation = None
    for attempt in range(1, RACE_ATTEMPTS + 1):
        observation = _attempt_foreign_race(case, env, "race-%d" % (attempt,))
        observation["attempts"] = attempt
        if observation["concurrent_stage_landed"]:
            return observation
    return observation


def _attempt_foreign_race(case, env, where):
    root = _build_race(case, env, where)
    owned = ["src/new%03d.py" % (index,) for index in range(RACE_NEW_FILES)]

    builders.run_cli(root, env, "task", "start", *sum(
        (["--own", path] for path in owned), []
    ))
    builders.run_cli(root, env, "check", "--allow", "unit")

    base = builders.head(root, env)
    before = builders.staged_delta(root, base, env)

    done = threading.Event()
    landed = {}

    def stage():
        landed["value"] = _stage_foreign_after_the_commit_lands(
            root, env, base, done
        )

    worker = threading.Thread(target=stage)
    worker.start()
    completed = builders.run_cli(root, env, "commit", "-m", "raced completion")
    done.set()
    worker.join(timeout=RACE_TIMEOUT_SECONDS)

    text = completed.stdout.decode("utf-8", "replace") + completed.stderr.decode(
        "utf-8", "replace"
    )
    after = builders.head(root, env)
    evidence = builders.commit_evidence(root, env)
    receipt = builders.run_cli(root, env, "receipt")
    receipt_text = receipt.stdout.decode("utf-8", "replace")

    return {
        "concurrent_stage_landed": bool(landed.get("value")),
        "foreign_staged_delta_changed": before != builders.staged_delta(
            root, base, env
        ),
        "aiqe_commit_created": after is not None and after != base,
        "aiqe_commit_exit": completed.returncode,
        "aiqe_commit_reasons": builders.reason_codes(text),
        "aiqe_recorded_pre_digest": (evidence or {}).get(
            "foreign_staged_pre_digest"
        ),
        "aiqe_recorded_post_digest": (evidence or {}).get(
            "foreign_staged_post_digest"
        ),
        "aiqe_foreign_staged": builders.field(receipt_text, "Foreign staged"),
        "aiqe_verdict": builders.field(receipt_text, "Verdict"),
        "aiqe_receipt_exit": receipt.returncode,
    }


# --- Fixture construction --------------------------------------------------


def _repo(case, env, where, committed_files=()):
    """Build one control repository under the case root.

    Controls need two repositories - one for the naive implementation, one for
    AIQE - because a commit cannot be handed back. `where` names which
    directory this one is, and both are measured directories of the family.
    """
    original = case.repo_path
    case.repo_path = os.path.join(case.root, where)
    try:
        return builders.build_repository(
            case, env, committed_files=committed_files
        )
    finally:
        case.repo_path = original


CONTROLS = [
    {
        "id": "NC-COMMIT-SHARED-INDEX",
        "description": "a plain commit absorbs unrelated staged work",
        "invariant": "a completion commit contains only the owned changed pathset",
        "detects": SHARED_INDEX,
        "run": run_shared_index,
    },
    {
        "id": "NC-COMMIT-PATHSPEC",
        "description": "a declared path handed to Git as a pathspec broadens",
        "invariant": "an owned path is a literal name, never a pattern",
        "detects": PATHSPEC,
        "run": run_pathspec,
    },
    {
        "id": "NC-COMMIT-STALE",
        "description": "check, edit, commit: the edit is never validated",
        "invariant": "committed content is the checked content",
        "detects": STALE,
        "run": run_stale,
    },
    {
        "id": "NC-COMMIT-ITA-ROLLBACK",
        "description": "a failed staging sequence leaves intent-to-add residue",
        "invariant": "a failed completion leaves the index as it found it",
        "detects": ITA_ROLLBACK,
        "run": run_ita_rollback,
    },
    {
        "id": "NC-COMMIT-HOOK-POLICY",
        "description": "committing runs the repository's commit hook",
        "invariant": "AIQE executes no repository-defined commit hook",
        "detects": HOOK_POLICY,
        "run": run_hook_policy,
    },
    {
        "id": "NC-COMMIT-SIGNING-POLICY",
        "description": "--no-gpg-sign makes the error go away, silently",
        "invariant": "configured signing is refused, never bypassed",
        "detects": SIGNING_POLICY,
        "run": run_signing_policy,
    },
    {
        "id": "NC-COMMIT-FILTER",
        "description": "checking in a bound path executes its clean filter",
        "invariant": "AIQE executes no external check-in filter",
        "detects": FILTER_POLICY,
        "run": run_filter_policy,
    },
    {
        "id": "NC-COMMIT-FOREIGN-RACE",
        "description": "foreign staged state changes inside the mutation window",
        "invariant": "EXCLUDED is claimed only when before equals after",
        "detects": FOREIGN_RACE,
        "run": run_foreign_race,
    },
]


def violated(control, observation):
    """Did the naive implementation actually breach the invariant this time?"""
    detects = control["detects"]
    if detects == SHARED_INDEX:
        return (
            observation["naive_absorbed_foreign_staged"] is True
            and observation["aiqe_changed_paths"] == [builders.OWNED_TEXT]
            and observation["aiqe_foreign_staged_preserved"] is True
        )
    if detects == PATHSPEC:
        return (
            observation["naive_broadened_pathset"] is True
            and observation["aiqe_changed_paths"] == ["src/star*.py"]
        )
    if detects == STALE:
        return (
            observation["naive_committed_unchecked_content"] is True
            and observation["aiqe_commit_created"] is False
            and observation["aiqe_index_unchanged"] is True
        )
    if detects == ITA_ROLLBACK:
        return (
            observation["naive_index_residue"] is True
            and observation["aiqe_index_residue"] is False
            and observation["aiqe_index_unchanged"] is True
            and observation["aiqe_commit_created"] is False
        )
    if detects == HOOK_POLICY:
        return (
            observation["naive_ran_hook"] is True
            and observation["aiqe_ran_hook"] is False
            and observation["aiqe_commit_created"] is False
        )
    if detects == SIGNING_POLICY:
        return (
            observation["naive_bypassed_signing_policy"] is True
            and observation["aiqe_commit_created"] is False
            and observation["aiqe_ran_signer"] is False
        )
    if detects == FILTER_POLICY:
        return (
            observation["naive_ran_filter"] is True
            and observation["aiqe_ran_filter"] is False
            and observation["aiqe_commit_created"] is False
        )
    if detects == FOREIGN_RACE:
        return (
            observation["concurrent_stage_landed"] is True
            and observation["aiqe_recorded_pre_digest"]
            != observation["aiqe_recorded_post_digest"]
            and observation["aiqe_foreign_staged"] == "UNKNOWN"
            and observation["aiqe_verdict"] == "INCOMPLETE"
        )
    raise ValueError("unknown control detection mode %r" % (detects,))
