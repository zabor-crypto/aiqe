"""Deterministic fixtures for the BOUNDED_COMMIT family.

Every fixture is a real disposable repository built from nothing by the code
in this file, and every AIQE operation runs through the real command-line
entry point as a subprocess.

Three construction rules make the measurements mean something, and they are
the same three the check family uses, adapted to an operation that writes.

**The measured operation is allowed to write, and exactly where is declared.**
A completion commit changes the index, the object database, HEAD and the
reflog. Claiming `.git` byte immutability for it would be false, so the
harness attributes those changes to the commit and keeps the zero where it
belongs: **no worktree path is written by AIQE**. A commit that silently
rewrote a tracked file would be a violation, and a commit that wrote
`.git/index` is the operation working.

**Hooks, filters and signers announce themselves.** Every one a policy fixture
installs writes a marker into the case's canary directory, which lives outside
every snapshot root. So `hook executions = 0` on a refusal is counted rather
than argued.

**The proof is checked from outside AIQE.** The harness reads the resulting
commit with its own Git invocations - parent, changed pathset, blob and mode
per path, staged delta before and after - rather than believing AIQE's
rendering of them. A proof that only AIQE can see is not a proof.
"""

import json
import os
import subprocess
import sys

from ..repobuild import (  # noqa: F401  (re-exported: scenarios use these)
    canary,
    commit_all,
    git,
    init_repo,
    platform_supports,
    write,
)
from ..task.builders import (  # noqa: F401
    read_active,
    run_cli,
    salt_exists,
    state_directory,
    terminal_safe,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SOURCE = os.path.join(ROOT, "src")

if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)

#: The owned path every ordinary scenario declares.
OWNED = b"src/strategy/alpha.py"
OWNED_TEXT = "src/strategy/alpha.py"

CONFIG = """schema = 1

[[surface]]
paths = ["src/**"]
quant = true
contracts = ["CAUSALITY"]

[[surface]]
paths = ["tests/**", "checks/**", "aiqe.toml", ".gitattributes", ".gitignore"]
quant = false

[[validator]]
id = "unit"
run = ["./checks/unit.sh"]
required = true
timeout = 60
contracts = ["CAUSALITY"]
"""

#: Owned paths whose names are pathspec syntax, terminal syntax, or neither -
#: retained because a product whose claim is "exactly these paths" has to
#: survive the paths people actually have.
LITERAL_NAMES = (
    b"src/star*.py",
    b"src/q?.py",
    b"src/br[ack].py",
    b"src/:(top)magic.py",
    b"src/-dash.py",
    b"src/sp ace\ttab.py",
    b"src/nl\nname.py",
)

#: Paths a glob would sweep in but a literal declaration must not.
DECOY_NAMES = (b"src/starDECOY.py", b"src/qX.py", b"src/brack.py")

#: A filename that is not valid UTF-8. Only Linux accepts one; APFS rejects
#: the byte sequence outright, so the case is skipped rather than weakened.
NON_UTF8 = b"src/\xff\xfe-invalid.py"


# --- Repository construction -----------------------------------------------


def unit_script(root, marker, exit_code=0):
    canary(
        os.path.join(root, "checks", "unit.sh"), marker,
        body="exit %d" % (exit_code,),
    )


def build_repository(
    case,
    env,
    owned_setup=None,
    config_text=CONFIG,
    extra_git_config=(),
    committed_files=(),
    validator_exit=0,
):
    """A repository with one commit, a configuration and a passing validator.

    `committed_files` are (repository-relative bytes, content bytes, mode)
    written and committed as part of the baseline. `owned_setup` runs after
    the baseline commit and makes the change under test - deliberately before
    the measurement window opens, so the fixture's own edits are never
    confused with AIQE's.
    """
    root = init_repo(case.repo_path, env)
    write(os.path.join(root, "src", "strategy", "alpha.py"), "SIGNAL = 1\n")
    write(os.path.join(root, "src", "foreign.py"), "FOREIGN = 1\n")
    write(os.path.join(root, "tests", "test_alpha.py"), "def test():\n    pass\n")
    unit_script(root, case.marker("unit"), exit_code=validator_exit)
    write(os.path.join(root, "aiqe.toml"), config_text)
    for relative, content, mode in committed_files:
        put(root, relative, content, mode)
    commit_all(root, "base", env)
    for name, value in extra_git_config:
        git(root, "config", name, value, env=env)
    if owned_setup is not None:
        owned_setup(root, env)
    return root


def put(root, relative, content, mode=0o644):
    """Write a repository-relative byte path with exact content and mode."""
    path = os.path.join(os.fsencode(root), relative)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "wb") as handle:
        handle.write(content)
    os.chmod(path, mode)
    return path


def drop(root, relative):
    os.unlink(os.path.join(os.fsencode(root), relative))


def edit_owned(root, _env):
    put(root, OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")


# --- Reading the repository from outside AIQE ------------------------------


def _git_bytes(root, *args, **kwargs):
    env = kwargs.pop("env", None)
    proc = subprocess.run(
        ("git", "--literal-pathspecs", "-c", "gc.auto=0",
         "-c", "maintenance.auto=false") + args,
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    return proc


def head(root, env):
    proc = _git_bytes(root, "rev-parse", "--verify", "--quiet", "HEAD", env=env)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("ascii").strip()


def parents(root, commit, env):
    proc = _git_bytes(root, "rev-list", "--parents", "-n", "1", commit, env=env)
    if proc.returncode != 0:
        return None
    return [field.decode("ascii") for field in proc.stdout.split()[1:]]


def changed_paths(root, before, after, env):
    """The parent-to-commit changed pathset, read independently of AIQE."""
    proc = _git_bytes(
        root, "diff-tree", "-r", "--no-renames", "--name-only", "-z",
        "--no-commit-id", before, after, env=env,
    )
    if proc.returncode != 0:
        return None
    return sorted(field for field in proc.stdout.split(b"\0") if field)


def staged_delta(root, base, env):
    """The whole staged delta against `base`, as comparable text records."""
    proc = _git_bytes(
        root, "diff-index", "--cached", "--raw", "-z", "--no-renames", base,
        env=env,
    )
    if proc.returncode != 0:
        return None
    fields = [field for field in proc.stdout.split(b"\0") if field]
    records = []
    index = 0
    while index + 1 < len(fields):
        records.append(
            fields[index].decode("ascii", "replace")
            + " "
            + fields[index + 1].decode("utf-8", "surrogateescape")
        )
        index += 2
    return sorted(records)


def tree_state(root, commit, paths, env):
    """{path: "<mode> <oid>"} for exactly these paths at `commit`."""
    state = {}
    for path in paths:
        proc = _git_bytes(
            root, "ls-tree", "-z", "--full-tree", commit, "--", path, env=env
        )
        entry = None
        if proc.returncode == 0:
            for field in proc.stdout.split(b"\0"):
                if b"\t" not in field:
                    continue
                metadata, name = field.split(b"\t", 1)
                if name == path:
                    parts = metadata.split(b" ")
                    entry = parts[0].decode("ascii") + " " + parts[2].decode("ascii")
        state[path.decode("utf-8", "surrogateescape")] = entry
    return state


def index_paths(root, env):
    proc = _git_bytes(root, "ls-files", "-z", env=env)
    if proc.returncode != 0:
        return None
    return sorted(
        field.decode("utf-8", "surrogateescape")
        for field in proc.stdout.split(b"\0")
        if field
    )


def blob_bytes(root, commit, path, env):
    proc = _git_bytes(root, "ls-tree", "-z", "--full-tree", commit, "--", path,
                      env=env)
    for field in proc.stdout.split(b"\0"):
        if b"\t" not in field:
            continue
        metadata, name = field.split(b"\t", 1)
        if name == path:
            oid = metadata.split(b" ")[2].decode("ascii")
            content = _git_bytes(root, "cat-file", "blob", oid, env=env)
            return content.stdout
    return None


def worktree_bytes(root, path):
    try:
        with open(os.path.join(os.fsencode(root), path), "rb") as handle:
            return handle.read()
    except OSError:
        return None


def commit_evidence(root, env):
    """The commit evidence record AIQE wrote, or None."""
    directory = state_directory(root, env)
    if directory is None:
        return None
    try:
        with open(os.path.join(directory, "commit.json"), "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


# --- The measured workflow -------------------------------------------------

#: The completion message every scenario uses. Deliberately dull: the message
#: is user data, AIQE stores none of it, and a fixture that made it
#: interesting would be testing the wrong thing.
MESSAGE = "bounded completion"


def reason_codes(text):
    """The machine reason identifiers a command rendered, in order."""
    codes = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Reason"):
            continue
        _label, _separator, rest = stripped.partition(" ")
        for token in rest.split("·"):
            token = token.strip()
            if token:
                codes.append(token)
    return codes


def field(text, label):
    """The value of one rendered `Label   VALUE` row, or None."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(label + " ") or stripped == label:
            return stripped[len(label):].strip()
    return None


def control_bytes(text):
    """Raw terminal control bytes that reached a human surface."""
    return sum(
        1
        for character in text
        if ord(character) < 0x20 and character not in "\n\t"
    )


def workflow(
    case,
    env,
    root,
    owned,
    message=MESSAGE,
    allow=("unit",),
    before_commit=None,
    after_commit=None,
    after_commit_immediate=None,
    commit_arguments=None,
    cwd=None,
    owned_repository_paths=None,
):
    """Start a task, check it, commit it, and read the result from outside.

    Every claim in the observation is read back with the harness's own Git
    invocations. AIQE's rendering is recorded too, but it is never the source
    of a proof: a benchmark that believed the product's own summary would
    measure the summary.
    """
    observation = {}
    # Where the user is standing. Everything AIQE is *told* is relative to it;
    # everything AIQE passes to Git is relative to the worktree root, and the
    # two are only the same when the user happens to be at the top.
    invoked_from = cwd or root
    # What the user typed and what the repository calls it are the same thing
    # only when the command is run at the worktree root. The declaration side
    # uses the argument; every proof below uses the repository-relative path.
    repository_paths = list(owned_repository_paths or owned)

    start = run_cli(invoked_from, env, "task", "start", *_own_arguments(owned))
    observation["task_start_exit"] = start.returncode

    check_argv = ["check"]
    for identifier in allow:
        check_argv += ["--allow", identifier]
    checked = run_cli(invoked_from, env, *check_argv)
    observation["check_exit"] = checked.returncode
    observation["check_output"] = checked.stdout.decode("utf-8", "replace")
    observation["check_completion"] = field(
        checked.stdout.decode("utf-8", "replace"), "Completion"
    )

    base = head(root, env)
    # Underscore-prefixed keys are working values. The harness strips them
    # before the record is retained, because a retained artifact that carried
    # commit identifiers - even a disposable fixture's - would be the first
    # place this project's own public-sanitisation gate had an exception
    # carved out for it.
    observation["_head_before"] = base
    delta_before = staged_delta(root, base, env)
    observation["_staged_delta_before"] = delta_before
    observation["staged_delta_before"] = redact_delta(delta_before)
    observation["index_paths_before"] = index_paths(root, env)

    if before_commit is not None:
        # After the baseline is read and immediately before the command under
        # test. A scenario that breaks the effective Git configuration would
        # otherwise break the harness's own reads too, and measure nothing.
        before_commit(root, env)

    argv = commit_arguments or ["commit", "-m", message]
    committed = run_cli(invoked_from, env, *argv)
    text = committed.stdout.decode("utf-8", "replace") + committed.stderr.decode(
        "utf-8", "replace"
    )
    observation["commit_exit"] = committed.returncode
    # Retained so the README can quote the product rather than an
    # approximation of it. The rendering carries no identifier and no
    # timestamp, so it is reproducible across runs.
    observation["commit_output"] = committed.stdout.decode("utf-8", "replace")
    observation["commit_reasons"] = reason_codes(text)
    observation["commit_output_control_bytes"] = control_bytes(text)
    observation["commit_verdict"] = field(text, "Verdict")

    if after_commit_immediate is not None:
        # Before the harness reads anything back. A scenario that broke the
        # effective Git configuration for the duration of the command has to
        # restore it here, or every measurement below describes the broken
        # configuration instead of the repository.
        after_commit_immediate(root, env)

    after = head(root, env)
    observation["_head_after"] = after
    observation["commit_created"] = after is not None and after != base
    observation["index_paths_after"] = index_paths(root, env)
    observation["index_unchanged"] = (
        observation["index_paths_before"] == observation["index_paths_after"]
    )
    delta_after = staged_delta(root, base, env)
    observation["_staged_delta_after"] = delta_after
    observation["staged_delta_after"] = redact_delta(delta_after)

    if observation["commit_created"]:
        commit_parents = parents(root, after, env)
        observation["commit_parent_count"] = len(commit_parents or ())
        observation["parent_is_pre_commit_head"] = commit_parents == [base]
        observation["changed_paths"] = [
            path.decode("utf-8", "surrogateescape")
            for path in changed_paths(root, base, after, env) or ()
        ]
        observation["owned_tree_modes"] = tree_modes(
            root, after, [_as_bytes(path) for path in repository_paths], env
        )
    else:
        observation["commit_parent_count"] = None
        observation["parent_is_pre_commit_head"] = None
        observation["changed_paths"] = []
        observation["owned_tree_modes"] = {}

    observation["foreign_staged_preserved"] = _foreign_preserved(
        delta_before, delta_after, repository_paths
    )

    evidence = commit_evidence(root, env)
    observation["commit_evidence_schema"] = (
        evidence.get("schema_version") if evidence else None
    )
    observation["expected_changed_paths"] = sorted(
        _decode(value)
        for value in (evidence or {}).get("expected_changed_paths_b64") or []
    )
    observation["evidence_push_performed"] = (
        evidence.get("push_performed_by_aiqe") if evidence else None
    )

    if after_commit is not None:
        after_commit(root, env)

    receipt = run_cli(invoked_from, env, "receipt")
    receipt_text = receipt.stdout.decode("utf-8", "replace") + receipt.stderr.decode(
        "utf-8", "replace"
    )
    observation["receipt_exit"] = receipt.returncode
    observation["receipt_output"] = receipt.stdout.decode("utf-8", "replace")
    observation["receipt_verdict"] = field(receipt_text, "Verdict")
    observation["receipt_commit"] = field(receipt_text, "Commit")
    observation["receipt_foreign_staged"] = field(receipt_text, "Foreign staged")
    observation["receipt_checked_content"] = field(receipt_text, "Checked content")
    observation["receipt_owned_scope"] = field(receipt_text, "Owned scope")
    observation["receipt_reasons"] = reason_codes(receipt_text)
    observation["receipt_output_control_bytes"] = control_bytes(receipt_text)
    observation["receipt_discloses_commit_sha"] = bool(
        after and after in receipt_text
    )
    return observation


def redact_delta(records):
    """A staged delta with the object identities removed.

    The comparison that decides `foreign_staged_preserved` is made over the
    full records, in memory. What is *retained* keeps the modes, the status
    and the path - enough to read what the delta was - and drops the two blob
    identities, because a retained artifact carrying object ids would be the
    first place this project's own public-sanitisation gate had an exception
    carved out for it.
    """
    if records is None:
        return None
    redacted = []
    for record in records:
        fields = record.split(" ", 5)
        if len(fields) != 6:
            redacted.append(record)
            continue
        source_mode, destination_mode, _src, _dst, status, path = fields
        redacted.append(
            "%s %s %s %s" % (source_mode, destination_mode, status, path)
        )
    return sorted(redacted)


def tree_modes(root, commit, paths, env):
    """{path: Git mode or None} for exactly these paths at `commit`.

    The mode, not the blob id. Whether the committed blob is the expected one
    is proved by AIQE against the object database and re-proved by the case's
    changed-pathset comparison; retaining the identity would add an identifier
    to a shared artifact and prove nothing further.
    """
    state = tree_state(root, commit, paths, env)
    return {
        path: (entry.split(" ", 1)[0] if entry else None)
        for path, entry in state.items()
    }


def _own_arguments(owned):
    arguments = []
    for path in owned:
        arguments.append("--own")
        arguments.append(path)
    return arguments


def _as_bytes(path):
    if isinstance(path, bytes):
        return path
    return os.fsencode(path)


def _decode(value):
    import base64

    return base64.b64decode(value).decode("utf-8", "surrogateescape")


def _foreign_preserved(before, after, owned):
    # Compares the full records, object identities included: a foreign blob
    # that changed identity under an unchanged mode is exactly the drift this
    # is here to catch.
    """Did every staged record outside the owned pathset survive unchanged?

    The comparison is over records, not counts, and in both directions: an
    entry that appeared is as much a difference as one that vanished.
    """
    if before is None or after is None:
        return None
    names = {
        _as_bytes(path).decode("utf-8", "surrogateescape") for path in owned
    }

    def foreign(records):
        out = []
        for record in records:
            # The record is five space-separated raw diff fields followed by
            # the path, which may itself contain spaces.
            path = record.split(" ", 5)[-1]
            if path not in names:
                out.append(record)
        return sorted(out)

    return foreign(before) == foreign(after)


# --- Policy fixtures -------------------------------------------------------


def install_hook(case, root, name, directory=None):
    """An executable commit hook that records the fact that it ran.

    Installed under `.git/hooks` by default, which is where Git looks unless
    `core.hooksPath` says otherwise. The marker lives outside every snapshot
    root, so "the hook did not run" is counted rather than argued.
    """
    base = directory or os.path.join(root, ".git", "hooks")
    if not os.path.isdir(base):
        os.makedirs(base)
    canary(os.path.join(base, name), case.marker("hook." + name))


def install_filter_driver(case, root, name, marker, process=False):
    """A check-in filter driver command that records that it ran.

    A clean filter has to pass content through, or the commit it is bound to
    would store nothing. The point of the fixture is that it never runs at
    all, so what it would have done is almost beside the point - but a driver
    that corrupted content would make a failure look like a different failure.
    """
    path = os.path.join(root, ".filters", name)
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    body = "cat\n" if not process else "sleep 30\n"
    write(path, "#!/bin/sh\n: > %s\n%s" % (_quote(case.marker(marker)), body),
          mode=0o755)
    return path


def install_signer(case, root):
    """A signing program that records that it ran, then fails.

    Failing is deliberate: if AIQE ever bypassed the signing refusal and let
    Git sign, the commit would fail loudly rather than quietly succeed with a
    signature nobody asked this fixture to produce.
    """
    path = os.path.join(root, ".filters", "signer")
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    write(path, "#!/bin/sh\n: > %s\nexit 1\n" % (_quote(case.marker("signer")),),
          mode=0o755)
    return path


def _quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def global_config(env, *pairs):
    """Append settings to the fixture's isolated global Git configuration."""
    path = env["GIT_CONFIG_GLOBAL"]
    with open(path, "a") as handle:
        for section, body in pairs:
            handle.write("[%s]\n%s\n" % (section, body))
    return path


# --- Scenario helpers ------------------------------------------------------


def config_with(extra_non_quant=()):
    """The standard configuration plus explicit non-quant top-level paths.

    Needed only by the fixtures whose filenames live outside `src/`, because
    an owned path no surface matches is a classification gap and the check
    would never reach `REVIEWABLE_CANDIDATE`.
    """
    if not extra_non_quant:
        return CONFIG
    quoted = ", ".join('"%s"' % (path,) for path in extra_non_quant)
    return CONFIG.replace(
        'paths = ["tests/**", "checks/**", "aiqe.toml", ".gitattributes", ".gitignore"]',
        'paths = ["tests/**", "checks/**", "aiqe.toml", ".gitattributes", '
        '".gitignore", %s]' % (quoted,),
    )


def scenario(description, build, operate, **extra):
    entry = {"description": description, "build": build, "operate": operate}
    entry.update(extra)
    return entry


def plain(owned_setup, owned=(OWNED_TEXT,), **build_kwargs):
    """The ordinary shape: build, then start-check-commit-receipt."""

    def build(case, env):
        return build_repository(case, env, owned_setup=owned_setup, **build_kwargs)

    def operate(case, env, root):
        return workflow(case, env, root, list(owned))

    return build, operate


# --- Owned-change setups ---------------------------------------------------


def _setup_multiple(root, _env):
    put(root, OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    put(root, b"src/beta.py", b"BETA = 1\n")
    drop(root, b"src/gamma.py")


def _setup_deletion(root, _env):
    drop(root, b"src/gone.py")


def _setup_new_file(root, _env):
    put(root, b"src/created.py", b"CREATED = 1\n")


def _setup_executable(root, _env):
    put(root, b"src/tool.sh", b"#!/bin/sh\necho two\n", mode=0o755)


def _setup_mode_change(root, _env):
    os.chmod(os.path.join(os.fsencode(root), b"src/plain.sh"), 0o755)


def _setup_literal_names(root, _env):
    for name in LITERAL_NAMES:
        put(root, name, b"CHANGED = 1\n")
    for name in DECOY_NAMES:
        # Changed too, and staged nowhere. A glob would sweep these in; a
        # literal declaration must leave them exactly where they are.
        put(root, name, b"DECOY_CHANGED = 1\n")


def _setup_leading_dash(root, _env):
    put(root, b"-dash.py", b"DASH = 2\n")


def _setup_non_utf8(root, _env):
    put(root, NON_UTF8, b"INVALID = 2\n")


def _setup_crlf(root, _env):
    put(root, OWNED, b"SIGNAL = 1\r\nADJUSTED = 2\r\n")


def _setup_unchanged(_root, _env):
    """Deliberately nothing. The task owns a path it never touched."""


def _stage_foreign(root, env, relative, content=None, mode=None, delete=False):
    if delete:
        drop(root, relative)
    else:
        put(root, relative, content, mode if mode is not None else 0o644)
    git(root, "add", "--all", "--", relative.decode("utf-8", "surrogateescape"),
        env=env)


def _setup_foreign_modification(root, env):
    edit_owned(root, env)
    _stage_foreign(root, env, b"src/foreign.py", b"FOREIGN = 2\n")


def _setup_foreign_addition(root, env):
    edit_owned(root, env)
    _stage_foreign(root, env, b"src/foreign_added.py", b"ADDED = 1\n")


def _setup_foreign_deletion(root, env):
    edit_owned(root, env)
    _stage_foreign(root, env, b"src/foreign.py", delete=True)


def _setup_foreign_mode_change(root, env):
    edit_owned(root, env)
    os.chmod(os.path.join(os.fsencode(root), b"src/foreign_tool.sh"), 0o755)
    git(root, "add", "--all", "--", "src/foreign_tool.sh", env=env)


def _setup_foreign_untracked(root, env):
    edit_owned(root, env)
    put(root, b"src/foreign_untracked.py", b"UNTRACKED = 1\n")


def _edit_owned_again(root, _env):
    """The check-edit-commit staleness case, made after the check ran."""
    put(root, OWNED, b"SIGNAL = 1\nADJUSTED = 3\nUNCHECKED = 4\n")


def _commit_unrelated(root, env):
    """A commit the user makes after AIQE's, moving HEAD off it."""
    put(root, b"tests/later.py", b"LATER = 1\n")
    git(root, "add", "--all", env=env)
    git(root, "commit", "--quiet", "--message", "later", env=env)


# --- Baseline file sets ----------------------------------------------------

BASELINE_DELETION = ((b"src/gone.py", b"GONE = 1\n", 0o644),)
BASELINE_MULTIPLE = ((b"src/gamma.py", b"GAMMA = 1\n", 0o644),)
BASELINE_EXECUTABLE = ((b"src/tool.sh", b"#!/bin/sh\necho one\n", 0o755),)
BASELINE_MODE_CHANGE = ((b"src/plain.sh", b"#!/bin/sh\necho plain\n", 0o644),)
BASELINE_FOREIGN_MODE = (
    (b"src/foreign_tool.sh", b"#!/bin/sh\necho foreign\n", 0o644),
)
BASELINE_LITERAL = tuple(
    (name, b"BASE = 1\n", 0o644) for name in LITERAL_NAMES + DECOY_NAMES
)
BASELINE_LEADING_DASH = ((b"-dash.py", b"DASH = 1\n", 0o644),)
BASELINE_NON_UTF8 = ((NON_UTF8, b"INVALID = 1\n", 0o644),)
BASELINE_CRLF = ((b".gitattributes", b"*.py text eol=lf\n", 0o644),)


# --- Custom operations -----------------------------------------------------


def _operate_linked_worktree(case, env, target):
    """The whole workflow inside a linked worktree.

    A linked worktree has its own Git directory and its own index, and shares
    the object database. It is a supported completion surface, so it is proved
    rather than assumed.
    """
    return workflow(case, env, target["linked"], [OWNED_TEXT])


def _build_linked_worktree(case, env):
    root = build_repository(case, env)
    linked = os.path.join(os.path.dirname(root), "linked")
    git(root, "worktree", "add", "--quiet", "-b", "side", linked, env=env)
    put(linked, OWNED, b"SIGNAL = 1\nADJUSTED = 2\n")
    return {"root": root, "linked": linked}


def _operate_second_commit(case, env, root):
    """A second completion commit for the same task must refuse."""
    observation = workflow(case, env, root, [OWNED_TEXT])
    again = run_cli(root, env, "commit", "-m", "second attempt")
    text = again.stdout.decode("utf-8", "replace") + again.stderr.decode(
        "utf-8", "replace"
    )
    observation["second_commit_exit"] = again.returncode
    observation["second_commit_created"] = (
        head(root, env) != observation["_head_after"]
    )
    observation["second_commit_reasons"] = reason_codes(text)
    return observation


def _operate_head_move(case, env, root):
    """A commit the user makes afterwards must stop the receipt claiming now."""
    return workflow(case, env, root, [OWNED_TEXT], after_commit=_commit_unrelated)


def _operate_broken_effective_config(case, env, root):
    """The effective configuration is unresolvable only while AIQE commits.

    The break is in the *global* configuration, which AIQE's read-only layer
    deliberately switches off - so discovery and `aiqe check` still work, and
    the commit is the first operation that has to resolve the real chain. It
    is repaired immediately afterwards so that the harness's own Git reads
    describe the repository rather than the broken configuration.
    """
    broken = os.path.join(case.state, "broken.cfg")
    write(broken, "[[[not configuration\n")
    original = None

    def break_config(_root, _env):
        nonlocal original
        with open(env["GIT_CONFIG_GLOBAL"]) as handle:
            original = handle.read()
        with open(env["GIT_CONFIG_GLOBAL"], "a") as handle:
            handle.write("[include]\n\tpath = %s\n" % (broken,))

    def repair(_root, _env):
        with open(env["GIT_CONFIG_GLOBAL"], "w") as handle:
            handle.write(original or "")

    return workflow(
        case,
        env,
        root,
        [OWNED_TEXT],
        before_commit=break_config,
        after_commit_immediate=repair,
    )


def _build_merge_in_progress(case, env):
    root = build_repository(case, env)
    git(root, "checkout", "--quiet", "-b", "side", env=env)
    put(root, b"tests/side.py", b"SIDE = 1\n")
    commit_all(root, "side", env)
    git(root, "checkout", "--quiet", "main", env=env)
    put(root, b"tests/main.py", b"MAIN = 1\n")
    commit_all(root, "main", env)
    git(root, "merge", "--no-commit", "--no-ff", "side", env=env, check=False)
    edit_owned(root, env)
    return root


def _build_detached_head(case, env):
    root = build_repository(case, env, owned_setup=edit_owned)
    git(root, "checkout", "--quiet", "--detach", env=env)
    return root


def _build_hook(case, env, name, hooks_path=False):
    root = build_repository(case, env, owned_setup=edit_owned)
    if hooks_path:
        directory = os.path.join(root, ".aiqe-hooks")
        install_hook(case, root, name, directory=directory)
        git(root, "config", "core.hooksPath", ".aiqe-hooks", env=env)
    else:
        install_hook(case, root, name)
    return root


def _build_signing_local(case, env):
    root = build_repository(case, env, owned_setup=edit_owned)
    signer = install_signer(case, root)
    git(root, "config", "commit.gpgsign", "true", env=env)
    git(root, "config", "gpg.program", signer, env=env)
    return root


def _build_signing_include(case, env):
    """Signing policy arriving through a global `include`, not the repository.

    Doctor reads repository-scope files and does not follow includes. A commit
    must, because Git does - so a policy defined two files away still refuses.
    """
    root = build_repository(case, env, owned_setup=edit_owned)
    signer = install_signer(case, root)
    # Fixture construction disables signing in repository scope so that its
    # own commits do not need a key. Repository scope outranks the global
    # file, so leaving it there would make this fixture prove nothing.
    git(root, "config", "--unset", "commit.gpgsign", env=env)
    included = os.path.join(os.path.dirname(root), "signing.cfg")
    write(
        included,
        "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = %s\n" % (signer,),
    )
    global_config(env, ("include", "\tpath = %s" % (included,)))
    return root


def _build_filter(case, env, process=False, scope="local", attributes="tracked"):
    """A check-in filter bound to an owned path, defined where the case says.

    The attributes binding and the driver definition are deliberately
    separable: repository content selects a driver, and configuration
    anywhere supplies the command. Both halves have to be resolved, from
    their real sources, before a commit can know what it would store.
    """
    files = ()
    if attributes == "tracked":
        files = ((b".gitattributes", b"*.py filter=canary\n", 0o644),)
    root = build_repository(case, env, committed_files=files)
    driver = install_filter_driver(
        case, root, "canary.sh", "filter.clean", process=process
    )

    if attributes == "info":
        write(os.path.join(root, ".git", "info", "attributes"),
              "*.py filter=canary\n")
    elif attributes == "attributesfile":
        external = os.path.join(os.path.dirname(root), "attributes")
        write(external, "*.py filter=canary\n")
        global_config(env, ("core", "\tattributesFile = %s" % (external,)))

    key = "filter.canary.process" if process else "filter.canary.clean"
    if scope == "local":
        git(root, "config", key, driver, env=env)
    else:
        included = os.path.join(os.path.dirname(root), "filters.cfg")
        write(included, '[filter "canary"]\n\t%s = %s\n'
              % ("process" if process else "clean", driver))
        global_config(env, ("include", "\tpath = %s" % (included,)))

    edit_owned(root, env)
    return root


def _build_filter_unbound(case, env):
    """A driver that is configured and bound to nothing.

    This is the case a blunt implementation gets wrong. Refusing here would
    make AIQE unusable on any machine that has ever installed Git LFS, and
    would teach its users that its refusals are noise.
    """
    root = build_repository(
        case, env, committed_files=((b".gitattributes", b"*.bin filter=canary\n", 0o644),)
    )
    driver = install_filter_driver(case, root, "canary.sh", "filter.clean")
    git(root, "config", "filter.canary.clean", driver, env=env)
    edit_owned(root, env)
    return root


# --- The scenarios ---------------------------------------------------------

_LITERAL_OWNED = [name.decode("utf-8", "surrogateescape") for name in LITERAL_NAMES]

SCENARIOS = {}


def _register(case_id, description, build, operate, **extra):
    SCENARIOS[case_id] = scenario(description, build, operate, **extra)


def _register_plain(case_id, description, owned_setup, owned=(OWNED_TEXT,),
                    **build_kwargs):
    build, operate = plain(owned_setup, owned, **build_kwargs)
    _register(case_id, description, build, operate)


_register_plain(
    "commit-owned-modification",
    "one tracked owned file, modified and committed",
    edit_owned,
)
_register_plain(
    "commit-multiple-owned-paths",
    "a modification, a creation and a deletion in one bounded commit",
    _setup_multiple,
    owned=(OWNED_TEXT, "src/beta.py", "src/gamma.py"),
    committed_files=BASELINE_MULTIPLE,
)
_register_plain(
    "commit-owned-deletion",
    "an owned path deleted from the worktree is committed as a deletion",
    _setup_deletion,
    owned=("src/gone.py",),
    committed_files=BASELINE_DELETION,
)
_register_plain(
    "commit-new-untracked-path",
    "a new untracked owned file, committed through transactional intent-to-add",
    _setup_new_file,
    owned=("src/created.py",),
)
_register_plain(
    "commit-executable-mode",
    "an executable owned file keeps mode 100755 through the commit",
    _setup_executable,
    owned=("src/tool.sh",),
    committed_files=BASELINE_EXECUTABLE,
)
_register_plain(
    "commit-mode-change",
    "a mode change with identical content is a change, and is committed",
    _setup_mode_change,
    owned=("src/plain.sh",),
    committed_files=BASELINE_MODE_CHANGE,
)
_register_plain(
    "commit-literal-pathspec-names",
    "owned filenames that are pathspec syntax commit themselves and no decoy",
    _setup_literal_names,
    owned=tuple(_LITERAL_OWNED),
    committed_files=BASELINE_LITERAL,
)
_register_plain(
    "commit-leading-dash-name",
    "an owned filename beginning with a dash is a name, not an option",
    _setup_leading_dash,
    owned=("-dash.py",),
    committed_files=BASELINE_LEADING_DASH,
    config_text=config_with(("-dash.py",)),
)
_register_plain(
    "commit-crlf-normalisation",
    "a CRLF worktree file commits as its normalised blob and stays bound",
    _setup_crlf,
    committed_files=BASELINE_CRLF,
)
_register_plain(
    "commit-foreign-staged-modification",
    "a foreign staged modification survives the bounded commit untouched",
    _setup_foreign_modification,
)
_register_plain(
    "commit-foreign-staged-addition",
    "a foreign staged addition survives the bounded commit untouched",
    _setup_foreign_addition,
)
_register_plain(
    "commit-foreign-staged-deletion",
    "a foreign staged deletion survives the bounded commit untouched",
    _setup_foreign_deletion,
)
_register_plain(
    "commit-foreign-staged-mode-change",
    "a foreign staged mode change survives the bounded commit untouched",
    _setup_foreign_mode_change,
    committed_files=BASELINE_FOREIGN_MODE,
)
_register_plain(
    "commit-foreign-untracked-path",
    "a foreign untracked file is neither committed nor staged",
    _setup_foreign_untracked,
)
_register_plain(
    "commit-empty-expected-changeset",
    "an owned path the task never touched produces no empty completion commit",
    _setup_unchanged,
)
_register_plain(
    "commit-stale-owned-edit",
    "an owned file edited after the check refuses before any index mutation",
    edit_owned,
)
SCENARIOS["commit-stale-owned-edit"]["operate"] = lambda case, env, root: workflow(
    case, env, root, [OWNED_TEXT], before_commit=_edit_owned_again
)
SCENARIOS["commit-stale-owned-edit"]["fixture_writes"] = (
    "repo/" + OWNED_TEXT,
)

_register(
    "commit-non-utf8-name",
    "an owned filename that is not valid UTF-8 commits as its exact bytes",
    lambda case, env: build_repository(
        case, env, owned_setup=_setup_non_utf8, committed_files=BASELINE_NON_UTF8
    ),
    lambda case, env, root: workflow(case, env, root, [NON_UTF8]),
)
_register(
    "commit-from-a-subdirectory",
    "a completion commit driven from a subdirectory of the worktree",
    lambda case, env: build_repository(case, env, owned_setup=edit_owned),
    lambda case, env, root: workflow(
        case,
        env,
        root,
        ["alpha.py"],
        cwd=os.path.join(root, "src", "strategy"),
        owned_repository_paths=[OWNED_TEXT],
    ),
)
_register(
    "commit-linked-worktree",
    "a completion commit in a linked worktree",
    _build_linked_worktree,
    _operate_linked_worktree,
)
_register(
    "commit-second-commit-refused",
    "a second completion commit for the same task refuses deterministically",
    lambda case, env: build_repository(case, env, owned_setup=edit_owned),
    _operate_second_commit,
)
_register(
    "commit-postcommit-head-move",
    "a later commit stops the receipt claiming a current reviewable state",
    lambda case, env: build_repository(case, env, owned_setup=edit_owned),
    _operate_head_move,
    fixture_writes=("repo/.git", "repo/tests/later.py"),
)
_register(
    "commit-effective-config-unresolved",
    "an unresolvable effective configuration refuses rather than guessing",
    lambda case, env: build_repository(case, env, owned_setup=edit_owned),
    _operate_broken_effective_config,
    fixture_state_writes=("state/home/gitconfig", "state/broken.cfg"),
)
_register(
    "commit-merge-in-progress",
    "a merge in progress is a topology this build refuses to commit onto",
    _build_merge_in_progress,
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-detached-head",
    "a detached HEAD is refused rather than silently claimed as supported",
    _build_detached_head,
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)

for _hook in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit"):
    _register(
        "commit-hook-%s" % (_hook,),
        "an active %s hook refuses, and does not run" % (_hook,),
        (lambda name: lambda case, env: _build_hook(case, env, name))(_hook),
        lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
    )

_register(
    "commit-hooks-path",
    "a hook reached through core.hooksPath refuses, and does not run",
    lambda case, env: _build_hook(case, env, "pre-commit", hooks_path=True),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-signing-configured",
    "commit.gpgSign in repository scope refuses, and no signer runs",
    _build_signing_local,
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-signing-through-include",
    "commit.gpgSign reached through a global include refuses just the same",
    _build_signing_include,
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-tracked-attributes",
    "a tracked .gitattributes binding a clean filter refuses, filter unrun",
    lambda case, env: _build_filter(case, env),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-process",
    "a process filter refuses, and is never started",
    lambda case, env: _build_filter(case, env, process=True),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-through-include",
    "a driver defined through a global include still refuses",
    lambda case, env: _build_filter(case, env, scope="global"),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-attributes-file",
    "a binding from core.attributesFile is resolved and refuses",
    lambda case, env: _build_filter(case, env, attributes="attributesfile"),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-info-attributes",
    "a binding from $GIT_DIR/info/attributes is resolved and refuses",
    lambda case, env: _build_filter(case, env, attributes="info"),
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
_register(
    "commit-filter-configured-but-unbound",
    "a configured driver bound to no owned path is not a blocker",
    _build_filter_unbound,
    lambda case, env, root: workflow(case, env, root, [OWNED_TEXT]),
)
