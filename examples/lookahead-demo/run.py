#!/usr/bin/env python3
"""Run the lookahead demonstration and retain everything it produced.

    python3 examples/lookahead-demo/run.py
    python3 examples/lookahead-demo/run.py --output examples/lookahead-demo/results

Four acts, each in its own repository built from nothing by `build.py`, each
driving the real `aiqe` entry point as a subprocess in an isolated environment.
Two of them also run the workflow a developer would otherwise use, so that the
contrast is measured rather than asserted.

The demo writes two artifacts: a structured record of what every act observed,
and a transcript of the commands and the output they actually produced. The
record is compared against `expected.json`, which was written before the run,
and the exit status is non-zero if any act disagreed with it.

Without `--output` both artifacts go to a fresh temporary directory, whose path
is printed at the end. That is deliberate: the retained copies under `results/`
are tracked evidence, and an ordinary run of the demo must not leave the
repository dirty. The second invocation above is the regeneration path, and is
the only way the retained artifacts are rewritten.

Nothing here is rendered by hand. If a line appears in the transcript, a
process printed it, and every value in the summary printed to stdout is read
from the same record that is compared against `expected.json`.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SOURCE = os.path.join(ROOT, "src")

for entry in (os.path.join(ROOT, "bench"), SOURCE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import build  # noqa: E402

from fixtures.measurement import Case  # noqa: E402
from fixtures.repobuild import git  # noqa: E402

OWNED = "src/strategy/momentum.py"
UNRELATED = "src/foreign.py"

#: A demo that has not finished in this long is a broken demo, not a slow one.
TIMEOUT_SECONDS = 300

#: The tracked, retained copies. Not the default output: writing here on an
#: ordinary run would dirty the repository with a timestamp that legitimately
#: differs between runs. Passing this path explicitly is the regeneration path.
RETAINED = os.path.join(HERE, "results")

EXPECTED_FILE = os.path.join(HERE, "expected.json")


# --- Running things --------------------------------------------------------


def aiqe(root, env, *arguments):
    """Invoke the real command-line entry point as a subprocess."""
    child = dict(env)
    child["PYTHONPATH"] = SOURCE
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "aiqe"] + list(arguments),
        cwd=root,
        env=child,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
    )


def run_script(root, env, script):
    """Run one of the repository's own validator scripts, directly.

    This is the control the whole demonstration rests on: what the project's
    checks say when nobody is mediating them.
    """
    child = dict(env)
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [script],
        cwd=root,
        env=child,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
    )


DIFF_TREE = ("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")


def changed_paths(proc):
    """The pathset one commit changed, read back from the object database."""
    return sorted(
        line for line in proc.stdout.decode("utf-8").splitlines() if line
    )


def text(proc):
    return proc.stdout.decode("utf-8", "replace")


# --- Transcript ------------------------------------------------------------


class Transcript(object):
    """What a person watching this run would have seen.

    Commands are recorded as they were invoked, with the interpreter and the
    module path collapsed to `aiqe` - the name the same invocation has once
    the package is installed. Nothing else is rewritten, and no line is
    written that a process did not print.
    """

    #: Stated rather than left to be assumed. These are the only two ways a
    #: recorded line differs from the invocation that produced it.
    PREAMBLE = (
        "AIQE - lookahead demonstration",
        "",
        "Every line below was printed by a process. Two invocations are",
        "written differently from the way they ran, and in no other way:",
        "",
        "  * AIQE runs here as `python3 -m aiqe` against a source tree and is",
        "    written `aiqe`, which is the same invocation once the package is",
        "    installed.",
        "  * Every Git command carries `-c gc.auto=0 -c maintenance.auto=false`,",
        "    which suppresses background maintenance so a fixture cannot move",
        "    while it is being measured. Those two flags are not shown.",
        "",
        "The task start timestamp is the only field here that differs between",
        "two runs of this demonstration.",
        "",
        "Reproduce: python3 examples/lookahead-demo/run.py",
    )

    def __init__(self):
        self.lines = list(self.PREAMBLE)

    def heading(self, title, subtitle):
        if self.lines:
            self.lines.append("")
        self.lines.append("=" * 72)
        self.lines.append(title)
        self.lines.append(subtitle)
        self.lines.append("=" * 72)

    def note(self, message):
        self.lines.append("")
        self.lines.append("# %s" % (message,))

    def command(self, rendered, proc, comment=None):
        self.lines.append("")
        if comment is None:
            self.lines.append("$ %s" % (rendered,))
        else:
            self.lines.append("$ %s   # %s" % (rendered, comment))
        body = text(proc).rstrip("\n")
        if body:
            self.lines.extend(body.split("\n"))
        self.lines.append("[exit %d]" % (proc.returncode,))

    def render(self):
        return "\n".join(self.lines) + "\n"


def show(transcript, root, env, *arguments):
    """Run an AIQE command and record it as it was invoked."""
    proc = aiqe(root, env, *arguments)
    transcript.command(invocation("aiqe", arguments), proc)
    return proc


def show_git(transcript, root, env, *arguments):
    """Run a Git command and record it the same way."""
    proc = git(root, *arguments, env=env)
    transcript.command(invocation("git", arguments), proc)
    return proc


def invocation(program, arguments):
    """The invocation, quoted the way a shell would need it written.

    The interpreter and the module path are collapsed to `aiqe`, which is the
    name the same invocation has once the package is installed. Nothing else
    is rewritten.
    """
    return " ".join([program] + [shlex.quote(argument) for argument in arguments])


# --- The acts --------------------------------------------------------------


def act_defect_is_caught(directory, transcript):
    """The generic suite passes. The causality validator does not."""
    case = Case("defect", os.path.join(directory, "defect"))
    env = case.env()
    root = build.build(case.repo_path, env)
    build.edit_strategy(root, lag=build.DEFECTIVE_LAG)

    transcript.heading(
        "ACT 1  the defect a green test suite cannot see",
        "one character changed: a decision now reads the bar it is made on",
    )

    unit = run_script(root, env, "./checks/unit.sh")
    causality = run_script(root, env, "./checks/causality.sh")
    transcript.note(
        "the repository's own checks, run directly - no AIQE involved"
    )
    transcript.command("./checks/unit.sh", unit)
    transcript.command("./checks/causality.sh", causality)

    show(transcript, root, env, "task", "start", "--own", OWNED)
    check = show(
        transcript, root, env, "check", "--allow", "unit", "--allow", "causality"
    )
    receipt = show(transcript, root, env, "receipt")

    return {
        "act": "defect_is_caught",
        "title": "the defect a green test suite cannot see",
        "generic_suite_exit": unit.returncode,
        "causality_validator_exit": causality.returncode,
        "check_exit": check.returncode,
        "check_output": text(check),
        "receipt_exit": receipt.returncode,
        "receipt_output": text(receipt),
        "receipt_verdict": verdict(text(receipt)),
    }


def act_nobody_looked(directory, transcript):
    """The same defect, in a repository that declares no causality validator."""
    case = Case("gap", os.path.join(directory, "gap"))
    env = case.env()
    root = build.build(case.repo_path, env, causality_declared=False)
    build.edit_strategy(root, lag=build.DEFECTIVE_LAG)

    transcript.heading(
        "ACT 2  the same defect, with nothing declared to detect it",
        "every check the repository has still passes",
    )

    unit = run_script(root, env, "./checks/unit.sh")
    transcript.note("the repository's own checks, run directly")
    transcript.command("./checks/unit.sh", unit)

    show(transcript, root, env, "task", "start", "--own", OWNED)
    check = show(transcript, root, env, "check", "--allow", "unit")
    receipt = show(transcript, root, env, "receipt")

    return {
        "act": "nobody_looked",
        "title": "the same defect, with nothing declared to detect it",
        "generic_suite_exit": unit.returncode,
        "check_exit": check.returncode,
        "check_output": text(check),
        "receipt_exit": receipt.returncode,
        "receipt_output": text(receipt),
        "receipt_verdict": verdict(text(receipt)),
    }


def act_unrelated_staged_work(directory, transcript):
    """An ordinary commit absorbs the index. A bounded commit does not."""
    transcript.heading(
        "ACT 3  unrelated staged work, and where it ends up",
        "a correct change to the strategy, with somebody else's work staged",
    )

    reference = Case("shared-index-reference", os.path.join(directory, "shared"))
    reference_env = reference.env()
    reference_root = build.build(reference.repo_path, reference_env)
    build.edit_strategy(reference_root, window=4)
    build.stage_unrelated_work(reference_root, reference_env)
    transcript.note(
        "the reference workflow: unrelated work is already staged; stage the "
        "change you meant to make, and commit"
    )
    show_git(transcript, reference_root, reference_env, "add", "--", OWNED)
    show_git(
        transcript,
        reference_root,
        reference_env,
        "commit",
        "--quiet",
        "--message",
        "widen the momentum window",
    )
    transcript.note("what that commit actually contains")
    reference_paths = changed_paths(
        show_git(transcript, reference_root, reference_env, *DIFF_TREE)
    )

    bounded = Case("shared-index-bounded", os.path.join(directory, "bounded"))
    bounded_env = bounded.env()
    bounded_root = build.build(bounded.repo_path, bounded_env)
    build.edit_strategy(bounded_root, window=4)
    build.stage_unrelated_work(bounded_root, bounded_env)

    transcript.note("the same repository, the same staged work, through AIQE")
    show(transcript, bounded_root, bounded_env, "task", "start", "--own", OWNED)
    check = show(
        transcript,
        bounded_root,
        bounded_env,
        "check",
        "--allow",
        "unit",
        "--allow",
        "causality",
    )
    precommit = show(transcript, bounded_root, bounded_env, "receipt")
    commit = show(
        transcript,
        bounded_root,
        bounded_env,
        "commit",
        "-m",
        "widen the momentum window",
    )
    receipt = show(transcript, bounded_root, bounded_env, "receipt")
    bounded_paths = changed_paths(
        show_git(transcript, bounded_root, bounded_env, *DIFF_TREE)
    )

    return {
        "act": "unrelated_staged_work",
        "title": "unrelated staged work, and where it ends up",
        "reference_changed_paths": reference_paths,
        "reference_absorbed_unrelated_work": UNRELATED in reference_paths,
        "check_exit": check.returncode,
        "check_output": text(check),
        "precommit_receipt_exit": precommit.returncode,
        "precommit_receipt_output": text(precommit),
        "precommit_receipt_verdict": verdict(text(precommit)),
        "commit_exit": commit.returncode,
        "commit_output": text(commit),
        "aiqe_changed_paths": bounded_paths,
        "aiqe_absorbed_unrelated_work": UNRELATED in bounded_paths,
        "receipt_exit": receipt.returncode,
        "receipt_output": text(receipt),
        "receipt_verdict": verdict(text(receipt)),
    }


def act_stale_evidence(directory, transcript):
    """Check, edit, commit. The edit was never checked by anything."""
    transcript.heading(
        "ACT 4  the edit that arrived after the check",
        "the checks passed, then the file changed, then it was committed",
    )

    reference = Case("stale-reference", os.path.join(directory, "stale-ref"))
    reference_env = reference.env()
    reference_root = build.build(reference.repo_path, reference_env)
    build.edit_strategy(reference_root, window=4)
    checked = run_script(reference_root, reference_env, "./checks/causality.sh")
    build.edit_strategy(reference_root, lag=build.DEFECTIVE_LAG, window=4)
    git(reference_root, "add", "--", OWNED, env=reference_env)
    git(
        reference_root,
        "commit",
        "--quiet",
        "--message",
        "widen the momentum window",
        env=reference_env,
    )
    committed = run_script(reference_root, reference_env, "./checks/causality.sh")
    transcript.note(
        "the reference workflow: run the checks, keep editing, commit. The "
        "same check, run again on what was committed"
    )
    transcript.command(
        "./checks/causality.sh", checked, comment="before the last edit"
    )
    transcript.command(
        "./checks/causality.sh", committed, comment="on the committed content"
    )

    bounded = Case("stale-bounded", os.path.join(directory, "stale-bounded"))
    bounded_env = bounded.env()
    bounded_root = build.build(bounded.repo_path, bounded_env)
    build.edit_strategy(bounded_root, window=4)

    transcript.note("the same sequence through AIQE")
    show(transcript, bounded_root, bounded_env, "task", "start", "--own", OWNED)
    show(
        transcript,
        bounded_root,
        bounded_env,
        "check",
        "--allow",
        "unit",
        "--allow",
        "causality",
    )
    build.edit_strategy(bounded_root, lag=build.DEFECTIVE_LAG, window=4)
    transcript.note("the owned file is edited again, after the check")
    commit = show(
        transcript,
        bounded_root,
        bounded_env,
        "commit",
        "-m",
        "widen the momentum window",
    )
    receipt = show(transcript, bounded_root, bounded_env, "receipt")
    head = git(bounded_root, "rev-list", "--count", "HEAD", env=bounded_env)

    return {
        "act": "stale_evidence",
        "title": "the edit that arrived after the check",
        "reference_check_exit_when_run": checked.returncode,
        "reference_check_exit_on_committed_content": committed.returncode,
        "reference_committed_unchecked_content": (
            checked.returncode == 0 and committed.returncode != 0
        ),
        "commit_exit": commit.returncode,
        "commit_output": text(commit),
        "aiqe_commits_created": int(head.stdout.decode("ascii").strip()) - 1,
        "receipt_exit": receipt.returncode,
        "receipt_output": text(receipt),
        "receipt_verdict": verdict(text(receipt)),
    }


ACTS = (
    act_defect_is_caught,
    act_nobody_looked,
    act_unrelated_staged_work,
    act_stale_evidence,
)


def verdict(receipt_output):
    for line in receipt_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Verdict"):
            return stripped.split()[-1]
    return None


# --- The summary ------------------------------------------------------------
#
# A demo whose payoff lives on line 210 of a transcript nobody opens has not
# demonstrated anything. So the run prints what it measured.
#
# Every value below is read out of `record` - the same structure that is
# compared against `expected.json` a few lines later. Nothing is re-derived,
# re-worded or restated from memory: if the product's behaviour changed, this
# summary changes with it, and the comparison fails in the same run. The only
# literal text is the framing, and the one paragraph of interpretation under
# act 2, which says what the demo's own README says.

RULE = "  " + "-" * 70


def contract_rows(check_output):
    """The contract rows of a rendered `AIQE CHECK`, exactly as it printed them.

    Act 2's whole point is one line of real output, so it is lifted from the
    output rather than described. Rows run from the `Contracts` heading to the
    blank line that ends the block.
    """
    rows = []
    inside = False
    for line in check_output.splitlines():
        if line.strip() == "Contracts":
            inside = True
            continue
        if inside:
            if not line.strip():
                break
            rows.append(line.strip())
    return rows


def reasons(check_output):
    """The `Reasons` line of a rendered check, as a single string."""
    for line in check_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Reasons"):
            return stripped.split(None, 1)[1]
    return ""


def summarise(record, out, transcript_path, record_path):
    """Print what the four acts measured, act 2 first among equals."""
    acts = {act["act"]: act for act in record["acts"]}
    write = out.write

    write(
        "\nlookahead demo · AIQE %s · %d acts, every declared outcome "
        "reproduced\n" % (record["aiqe_version"], len(record["acts"]))
    )

    one = acts["defect_is_caught"]
    write("\n  ACT 1  %s\n" % (one["title"],))
    write(
        "         generic suite  exit %d  ·  causality validator  exit %d\n"
        % (one["generic_suite_exit"], one["causality_validator_exit"])
    )
    write("         verdict  %s\n" % (one["receipt_verdict"],))

    # Act 2 is the product's one unique claim, so it gets the room. Every
    # other act is a supporting proof.
    two = acts["nobody_looked"]
    write("\n%s\n" % (RULE,))
    write("  ACT 2  %s\n" % (two["title"],))
    write("         THE ONE THAT MATTERS\n")
    write(
        "\n         generic suite  exit %d  ·  every check the repository "
        "declares passed\n" % (two["generic_suite_exit"],)
    )
    write("\n")
    for row in contract_rows(two["check_output"]):
        write("             %s\n" % (row,))
    write(
        "\n         verdict  %s  ·  %s\n"
        % (two["receipt_verdict"], reasons(two["check_output"]))
    )
    write(
        "\n         Nothing in this repository was written to ask the "
        "causality\n"
        "         question. The absence of a check is not a pass.\n"
    )
    write("%s\n" % (RULE,))

    three = acts["unrelated_staged_work"]
    write("\n  ACT 3  %s\n" % (three["title"],))
    write(
        "         git commit   %s\n"
        % (" · ".join(three["reference_changed_paths"]),)
    )
    write(
        "         aiqe commit  %s\n" % (" · ".join(three["aiqe_changed_paths"]),)
    )
    write("         verdict  %s\n" % (three["receipt_verdict"],))

    four = acts["stale_evidence"]
    write("\n  ACT 4  %s\n" % (four["title"],))
    write(
        "         reference workflow committed content its own check fails  %s\n"
        % ("yes" if four["reference_committed_unchecked_content"] else "no",)
    )
    write(
        "         commits AIQE created  %d\n" % (four["aiqe_commits_created"],)
    )
    write("         verdict  %s\n" % (four["receipt_verdict"],))

    write("\n  transcript  %s\n" % (transcript_path,))
    write("  record      %s\n" % (record_path,))


# --- Comparison ------------------------------------------------------------

#: Fields compared against `expected.json`. Rendered output is retained in
#: full and is not part of the expectation: it is the evidence, and pinning it
#: here would turn a wording change into a demo failure.
COMPARED = (
    "generic_suite_exit",
    "causality_validator_exit",
    "check_exit",
    "receipt_verdict",
    "precommit_receipt_verdict",
    "commit_exit",
    "reference_changed_paths",
    "reference_absorbed_unrelated_work",
    "aiqe_changed_paths",
    "aiqe_absorbed_unrelated_work",
    "reference_committed_unchecked_content",
    "aiqe_commits_created",
)


def compare(record, expected):
    problems = []
    observed = {act["act"]: act for act in record["acts"]}
    for want in expected["acts"]:
        name = want["act"]
        if name not in observed:
            problems.append("act %s did not run" % (name,))
            continue
        got = observed[name]
        for field in COMPARED:
            if field not in want:
                continue
            if got.get(field) != want[field]:
                problems.append(
                    "%s.%s: expected %r, observed %r"
                    % (name, field, want[field], got.get(field))
                )
    return problems


# --- Entry point -----------------------------------------------------------


def main(argv):
    parser = argparse.ArgumentParser(description="Run the lookahead demo.")
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "directory the artifacts are written to. Default: a fresh "
            "temporary directory, so that running the demo leaves the "
            "repository clean. Pass %s to regenerate the retained evidence."
            % (os.path.relpath(RETAINED, ROOT),)
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="do not delete the temporary repositories the demo built",
    )
    options = parser.parse_args(argv)

    from aiqe import __version__

    directory = tempfile.mkdtemp(prefix="aiqe-lookahead-demo-")
    transcript = Transcript()
    try:
        acts = [act(directory, transcript) for act in ACTS]
    finally:
        if options.keep:
            sys.stderr.write("kept %s\n" % (directory,))
        else:
            shutil.rmtree(directory, ignore_errors=True)

    record = {
        "schema_version": 1,
        "demo": "lookahead",
        "aiqe_version": __version__,
        "acts": acts,
    }

    # A run that was not told where to write does not write into the tracked
    # tree. The directory is kept rather than cleaned up: the transcript is
    # the evidence, and printing a path to something already deleted would be
    # worse than useless.
    output = options.output
    if output is None:
        output = tempfile.mkdtemp(prefix="aiqe-lookahead-demo-out-")
    if not os.path.isdir(output):
        os.makedirs(output)

    record_path = os.path.join(output, "demo.json")
    transcript_path = os.path.join(output, "transcript.txt")
    with open(record_path, "w") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with open(transcript_path, "w") as handle:
        handle.write(transcript.render())

    with open(EXPECTED_FILE) as handle:
        expected = json.load(handle)
    problems = compare(record, expected)

    for problem in problems:
        sys.stderr.write("DEMO MISMATCH  %s\n" % (problem,))
    if problems:
        sys.stderr.write(
            "The demo did not reproduce what `expected.json` declared.\n"
        )
        sys.stderr.write("transcript  %s\n" % (transcript_path,))
        sys.stderr.write("record      %s\n" % (record_path,))
        return 1

    summarise(record, sys.stdout, transcript_path, record_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
