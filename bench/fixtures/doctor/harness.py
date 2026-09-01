"""Measurement harness for the Doctor benchmark family.

Doctor's frozen contract is a set of claims about what it does *not* do. A
program cannot establish that about itself: asking Doctor whether it wrote
anything only tells you what Doctor believes. So the harness measures from
outside.

For every case it takes a byte-level snapshot of the whole isolated case
directory before and after the Doctor run - the repository and its Git
directory, the linked worktree if there is one, and the isolated home and
state directories - and compares content hashes, sizes, modes and modification
times. Canary markers live outside the snapshot, so that a canary firing is
recorded as an execution rather than confused with a mutation.

Three zero-tolerance quantities come out of each case:

    repository_mutations          changed paths inside the repository
    repository_defined_executions canaries the repository installed that fired
    local_state_writes            changed paths in the isolated home and
                                  state directories

The environment is isolated so that the numbers mean something: HOME, the XDG
directories and the global Git configuration all point inside the case
directory, and the system Git configuration is switched off. A fixture cannot
reach the developer's real configuration, and Doctor cannot write to the
developer's real state directory without the harness seeing it.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_FILE = os.path.join(HERE, "cases.json")

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import builders  # noqa: E402  (path is set immediately above)
import controls  # noqa: E402


def load_cases():
    with open(CASES_FILE) as handle:
        return json.load(handle)


class Case(object):
    """One fixture, its isolated directories and its isolated environment."""

    def __init__(self, case_id, root):
        self.case_id = case_id
        self.root = root
        self.repo_path = os.path.join(root, "repo")
        self.canaries = os.path.join(root, "canaries")
        self.state = os.path.join(root, "state")
        os.makedirs(self.canaries)
        os.makedirs(self.state)
        self._markers = []

    def marker(self, name):
        """Path a canary writes when it runs. Outside every snapshot root."""
        path = os.path.join(self.canaries, name)
        if path not in self._markers:
            self._markers.append(path)
        return path

    def fired(self):
        return sorted(
            os.path.basename(path) for path in self._markers if os.path.exists(path)
        )

    def env(self):
        """A Git and process environment that cannot reach the real machine."""
        home = os.path.join(self.state, "home")
        for directory in (home, os.path.join(self.state, "xdg")):
            if not os.path.isdir(directory):
                os.makedirs(directory)

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "XDG_STATE_HOME": os.path.join(self.state, "xdg", "state"),
            "XDG_CONFIG_HOME": os.path.join(self.state, "xdg", "config"),
            "XDG_DATA_HOME": os.path.join(self.state, "xdg", "data"),
            "XDG_CACHE_HOME": os.path.join(self.state, "xdg", "cache"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.path.join(home, "gitconfig"),
            "GIT_AUTHOR_NAME": "AIQE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "AIQE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "LC_ALL": "C",
            "TZ": "UTC",
        }
        if not os.path.exists(env["GIT_CONFIG_GLOBAL"]):
            with open(env["GIT_CONFIG_GLOBAL"], "w") as handle:
                handle.write("")
        return env

    def is_repository_path(self, relative):
        return relative.split(os.sep, 1)[0] in ("repo", "linked")

    def is_state_path(self, relative):
        return relative.split(os.sep, 1)[0] == "state"


def snapshot(root, skip):
    """Byte-level snapshot of everything under `root`, excluding `skip`.

    Records content hash, size, mode and modification time for every regular
    file and symlink, and records every directory. Mode and mtime are included
    deliberately: an index refresh that rewrote identical bytes would still
    move the modification time, and a claim of zero writes that ignored that
    would be a weaker claim than the one being made.
    """
    entries = {}
    skip = os.path.abspath(skip)
    for directory, subdirectories, filenames in os.walk(root):
        if os.path.abspath(directory) == skip:
            subdirectories[:] = []
            continue
        subdirectories.sort()
        relative_dir = os.path.relpath(directory, root)
        if relative_dir != ".":
            entries[relative_dir] = ("dir",)
        for name in sorted(filenames):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, root)
            entries[relative] = _describe(path)
    return entries


def _describe(path):
    try:
        stat = os.lstat(path)
    except OSError as exc:
        return ("error", str(exc))
    if os.path.islink(path):
        try:
            target = os.readlink(path)
        except OSError as exc:
            return ("error", str(exc))
        return ("link", hashlib.sha256(os.fsencode(target)).hexdigest())
    try:
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        return ("error", str(exc))
    return ("file", digest, stat.st_size, stat.st_mode, stat.st_mtime_ns)


def compare(before, after):
    """Changed paths between two snapshots, as sorted human-readable strings."""
    changes = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append("added: " + key)
        elif key not in after:
            changes.append("removed: " + key)
        elif before[key] != after[key]:
            changes.append("changed: " + key + " " + _what_changed(before[key], after[key]))
    return changes


def _what_changed(before, after):
    if before[0] != after[0] or before[0] != "file":
        return "(kind or content)"
    fields = ("content", "size", "mode", "mtime")
    names = [
        fields[index - 1]
        for index in range(1, 5)
        if index < len(before) and index < len(after) and before[index] != after[index]
    ]
    return "(" + ",".join(names) + ")"


def run_case(case_id, keep=False):
    """Build one fixture, run Doctor against it, and measure everything.

    Doctor runs in this process rather than as a child. The measurements that
    matter - repository bytes, executed canaries, state directory bytes - are
    external to the process either way, and running in-process additionally
    exposes the exact list of Git invocations to the assertions.
    """
    from aiqe import __version__
    from aiqe.doctor import inspect
    from aiqe.report import render_human, render_json

    builder = builders.BUILDERS[case_id]
    root = tempfile.mkdtemp(prefix="aiqe-doctor-")
    try:
        case = Case(case_id, root)
        env = case.env()
        target = builder(case, env)

        before = snapshot(root, case.canaries)
        report = inspect(target, env=env)
        human = render_human(report)
        machine = render_json(report, __version__)
        after = snapshot(root, case.canaries)

        changes = compare(before, after)
        repository_changes = [
            change for change in changes if case.is_repository_path(change.split(": ", 1)[1])
        ]
        state_changes = [
            change for change in changes if case.is_state_path(change.split(": ", 1)[1])
        ]

        return {
            "case": case_id,
            "result": report.result,
            "exit_code": report.exit_code(),
            "findings": [finding.code for finding in report.sorted_findings()],
            "states": report.state_counts(),
            "repository": dict(report.repository),
            "topology": dict(report.topology),
            "operations_in_progress": list(report.operations),
            "working_state": dict(report.working_state),
            "aiqe": dict(report.aiqe),
            "commit_policy": dict(report.commit_policy),
            "agent_surface": dict(report.agent_surface),
            "repository_mutations": len(repository_changes),
            "repository_mutation_detail": repository_changes,
            "local_state_writes": len(state_changes),
            "local_state_write_detail": state_changes,
            "other_changes": [
                change
                for change in changes
                if change not in repository_changes and change not in state_changes
            ],
            "repository_defined_executions": len(case.fired()),
            "fired_canaries": case.fired(),
            "git_invocations": [list(invocation) for invocation in report.runner.invocations],
            "human_output": human,
            "json_output": json.loads(machine),
        }
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def check_expectations(observed, expected):
    """Compare one observed result against its recorded expectation.

    Returns a list of mismatch descriptions; empty means the case passed.
    """
    problems = []

    for key in ("result", "exit_code"):
        if observed[key] != expected[key]:
            problems.append("%s: expected %r, observed %r" % (key, expected[key], observed[key]))

    if sorted(observed["findings"]) != sorted(expected["findings"]):
        problems.append(
            "findings: expected %s, observed %s"
            % (sorted(expected["findings"]), sorted(observed["findings"]))
        )

    for section, fields in expected.get("report", {}).items():
        for field, value in fields.items():
            actual = observed[section].get(field)
            if actual != value:
                problems.append(
                    "%s.%s: expected %r, observed %r" % (section, field, value, actual)
                )

    if observed["repository_mutations"] != 0:
        problems.append("repository mutations: %s" % (observed["repository_mutation_detail"],))
    if observed["local_state_writes"] != 0:
        problems.append("local state writes: %s" % (observed["local_state_write_detail"],))
    if observed["repository_defined_executions"] != 0:
        problems.append("repository-defined executions: %s" % (observed["fired_canaries"],))

    return problems


def run_control(control_id, keep=False):
    """Build a control's fixture and run the naive workflow against it.

    The same measurement applies as for a Doctor case, so the comparison is
    like for like: the only thing that changes is which program looks at the
    repository.
    """
    control = None
    for candidate in controls.CONTROLS:
        if candidate["id"] == control_id:
            control = candidate
            break
    if control is None:
        raise KeyError(control_id)

    builder = builders.BUILDERS[control["fixture"]]
    root = tempfile.mkdtemp(prefix="aiqe-control-")
    try:
        case = Case(control["fixture"], root)
        env = case.env()
        target = builder(case, env)

        before = snapshot(root, case.canaries)
        proc = control["naive"](target, env)
        after = snapshot(root, case.canaries)

        changes = compare(before, after)
        repository_changes = [
            change for change in changes if case.is_repository_path(change.split(": ", 1)[1])
        ]

        observation = {
            "control": control_id,
            "description": control["description"],
            "fixture": control["fixture"],
            "invariant": control["invariant"],
            "detects": control["detects"],
            "naive_workflow": control["naive"].__name__,
            "naive_returncode": proc.returncode,
            "naive_stdout": proc.stdout.decode("utf-8", "replace"),
            "repository_mutations": len(repository_changes),
            "repository_mutation_detail": repository_changes,
            "repository_defined_executions": len(case.fired()),
            "fired_canaries": case.fired(),
        }
        observation["control_reproduces_failure"] = controls.violated(control, observation)
        return observation
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def control_record(observation):
    """The artifact-safe view of a control observation.

    Raw Git plumbing output is not retained. It carries Git object identifiers
    - forty hexadecimal characters apiece - and while these fixtures are
    synthetic, a retained artifact that habitually contains object identifiers
    is one the sanitisation scanner cannot distinguish from one that leaks a
    real commit. The evidence that matters survives: whether the naive
    workflow mutated the repository, whether it executed something the
    repository defined, and whether it resolved a value Doctor refuses to
    resolve.
    """
    record = dict(observation)
    stdout = record.pop("naive_stdout", "")
    record["naive_stdout_bytes"] = len(stdout.encode("utf-8"))
    record["naive_stdout_retained"] = False
    return record
