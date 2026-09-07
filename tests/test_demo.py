"""The lookahead demonstration must still demonstrate what it claims.

A demo is a claim about the product made in public, and it decays the same
way documentation does: the retained transcript stays on the page long after
the behaviour it recorded has moved. So the suite runs the demo, compares what
it produced against what is retained, and fails if the two have parted.

The run is done once for the whole module. It builds four repositories and
drives real subprocesses against them, which is not free, and repeating it per
assertion would buy nothing.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from . import support

DEMO = os.path.join(support.ROOT, "examples", "lookahead-demo")
RETAINED = os.path.join(DEMO, "results")
README = os.path.join(support.ROOT, "README.md")

#: The demo builds repositories and runs validators in them. Generous,
#: because a slow machine must not fail this; bounded, because a demo that
#: never finishes is a broken demo.
TIMEOUT_SECONDS = 900

#: The one line in the transcript that legitimately differs between runs.
TIMESTAMP = re.compile(r"^  Started         \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_fresh = None
_directory = None


def setUpModule():
    global _fresh, _directory
    _directory = tempfile.mkdtemp(prefix="aiqe-demo-test-")
    proc = subprocess.run(
        [sys.executable, os.path.join(DEMO, "run.py"), "--output", _directory],
        cwd=support.ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
    )
    _fresh = proc


def tearDownModule():
    if _directory:
        shutil.rmtree(_directory, ignore_errors=True)


def read(path):
    with open(path) as handle:
        return handle.read()


class DemoRunTests(unittest.TestCase):
    def test_the_demo_reproduces_every_outcome_it_declared(self):
        """`run.py` compares itself against `expected.json` and exits 1 if it
        disagreed. That comparison is the demo's own gate; this asserts it
        still passes rather than restating it."""
        self.assertEqual(
            _fresh.returncode,
            0,
            "the demo did not reproduce its declared outcomes:\n%s"
            % (_fresh.stderr.decode("utf-8", "replace"),),
        )

    def test_the_retained_record_is_what_a_fresh_run_produces(self):
        """Byte-identical, because nothing in the record is timing or path
        dependent - which is the property that makes it retainable at all."""
        self.assertEqual(
            json.loads(read(os.path.join(_directory, "demo.json"))),
            json.loads(read(os.path.join(RETAINED, "demo.json"))),
            "the retained demo record is not what the demo now produces",
        )

    def test_the_retained_transcript_differs_only_in_the_task_timestamp(self):
        """The transcript's own preamble makes this claim. This is the check
        that keeps it true: every other line must be identical, and the lines
        that do differ must all be task start timestamps."""
        fresh = read(os.path.join(_directory, "transcript.txt")).splitlines()
        retained = read(os.path.join(RETAINED, "transcript.txt")).splitlines()
        self.assertEqual(len(fresh), len(retained), "the transcript changed shape")
        for index, (left, right) in enumerate(zip(fresh, retained)):
            if left == right:
                continue
            self.assertRegex(left, TIMESTAMP, "transcript line %d" % (index + 1,))
            self.assertRegex(right, TIMESTAMP, "transcript line %d" % (index + 1,))


def load_run_module():
    """Import `run.py` as a module, to test what it renders directly.

    Run as a script its own directory is on `sys.path` and `import build`
    resolves; imported by path it is not, so the loader supplies it.
    """
    import importlib.util

    if DEMO not in sys.path:
        sys.path.insert(0, DEMO)
    spec = importlib.util.spec_from_file_location(
        "lookahead_demo_run", os.path.join(DEMO, "run.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoOutputLocationTests(unittest.TestCase):
    """An ordinary run of the demo must not dirty the repository.

    The retained artifacts are tracked, and the transcript legitimately
    carries a task start timestamp that differs between runs - so a default
    that wrote there would leave every reader with an uncommitted diff in the
    one repository that argues nobody should accept unexplained changes.
    """

    def test_the_regeneration_path_is_the_tracked_results_directory(self):
        module = load_run_module()
        self.assertEqual(
            os.path.realpath(module.RETAINED), os.path.realpath(RETAINED)
        )

    def test_the_help_states_the_default_and_the_regeneration_path(self):
        """`--help` is where a reader learns whether running this will touch
        their tree, so it has to say so."""
        proc = subprocess.run(
            [sys.executable, os.path.join(DEMO, "run.py"), "--help"],
            cwd=support.ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        helptext = proc.stdout.decode("utf-8", "replace")
        self.assertIn("temporary directory", helptext)
        self.assertIn("examples/lookahead-demo/results", helptext)

    def test_a_default_run_writes_nothing_into_the_repository(self):
        """Asserted against the run `setUpModule` already made: it was given
        an explicit output, and the tracked results are byte-unchanged."""
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", "examples/lookahead-demo/results"],
            cwd=support.ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        self.assertEqual(
            proc.stdout.decode("utf-8", "replace").strip(),
            "",
            "running the demo left the retained artifacts modified",
        )


class DemoSummaryTests(unittest.TestCase):
    """The demo has to show its payoff without being opened.

    Everything the summary prints is read out of the record that
    `expected.json` gates, so these assertions are about *provenance* as much
    as wording: a value that stopped coming from the record would stop
    matching the record.
    """

    def setUp(self):
        self.module = load_run_module()
        self.record = json.loads(read(os.path.join(RETAINED, "demo.json")))
        self.acts = {act["act"]: act for act in self.record["acts"]}

    def render(self, record=None):
        import io

        out = io.StringIO()
        self.module.summarise(
            record if record is not None else self.record,
            out,
            "/tmp/example/transcript.txt",
            "/tmp/example/demo.json",
        )
        return out.getvalue()

    def test_every_act_appears_with_its_measured_verdict(self):
        rendered = self.render()
        for act in self.record["acts"]:
            with self.subTest(act=act["act"]):
                self.assertIn(act["title"], rendered)
                self.assertIn(act["receipt_verdict"], rendered)

    def test_act_two_is_the_dominant_result(self):
        """Act 2 is the product's one unique claim: every check the
        repository has can pass because nobody wrote the applicable one."""
        rendered = self.render()
        self.assertIn("THE ONE THAT MATTERS", rendered)
        self.assertIn("COVERAGE_GAP", rendered)
        self.assertIn("The absence of a check is not a pass.", rendered)
        self.assertIn(self.module.RULE, rendered)

    def test_the_coverage_gap_row_is_lifted_from_the_rendered_check(self):
        """Not described, quoted. The row in the summary is a row the product
        actually printed."""
        rendered = self.render()
        rows = self.module.contract_rows(
            self.acts["nobody_looked"]["check_output"]
        )
        self.assertTrue(rows, "the retained act-2 check declared no contract")
        for row in rows:
            self.assertIn(row, rendered)

    def test_the_summary_reads_values_rather_than_restating_them(self):
        """Perturb the record and the rendering must follow it. This is what
        separates a summary from a caption."""
        import copy

        mutated = copy.deepcopy(self.record)
        for act in mutated["acts"]:
            if act["act"] == "stale_evidence":
                act["aiqe_commits_created"] = 7
        self.assertIn("commits AIQE created  0", self.render())
        self.assertIn("commits AIQE created  7", self.render(mutated))

    def test_the_pathset_contrast_is_the_retained_pathsets(self):
        act = self.acts["unrelated_staged_work"]
        rendered = self.render()
        self.assertIn(" · ".join(act["reference_changed_paths"]), rendered)
        self.assertIn(" · ".join(act["aiqe_changed_paths"]), rendered)

    def test_a_real_run_prints_the_summary_and_the_transcript_path(self):
        """Asserted against the run `setUpModule` actually made."""
        stdout = _fresh.stdout.decode("utf-8", "replace")
        self.assertIn("THE ONE THAT MATTERS", stdout)
        self.assertIn("COVERAGE_GAP", stdout)
        self.assertIn("transcript  ", stdout)
        self.assertIn(_directory, stdout)


class DemoContentTests(unittest.TestCase):
    """What the demo asserts about the product, asserted here too.

    If these ever disagree with the retained record, the demo has stopped
    demonstrating what its README says it demonstrates.
    """

    def setUp(self):
        record = json.loads(read(os.path.join(RETAINED, "demo.json")))
        self.acts = {act["act"]: act for act in record["acts"]}

    def test_the_generic_suite_passes_over_the_defect(self):
        act = self.acts["defect_is_caught"]
        self.assertEqual(act["generic_suite_exit"], 0)
        self.assertEqual(act["causality_validator_exit"], 1)
        self.assertEqual(act["receipt_verdict"], "NOT_REVIEWABLE")

    def test_an_undeclared_contract_is_a_gap_and_not_a_pass(self):
        act = self.acts["nobody_looked"]
        self.assertEqual(act["generic_suite_exit"], 0)
        self.assertIn("COVERAGE_GAP", act["check_output"])
        self.assertEqual(act["receipt_verdict"], "INCOMPLETE")

    def test_the_reference_commit_absorbs_what_the_bounded_one_excludes(self):
        act = self.acts["unrelated_staged_work"]
        self.assertTrue(act["reference_absorbed_unrelated_work"])
        self.assertFalse(act["aiqe_absorbed_unrelated_work"])
        self.assertEqual(act["aiqe_changed_paths"], ["src/strategy/momentum.py"])
        self.assertEqual(act["precommit_receipt_verdict"], "INCOMPLETE")
        self.assertEqual(act["receipt_verdict"], "REVIEWABLE")

    def test_a_stale_edit_is_refused_rather_than_committed(self):
        act = self.acts["stale_evidence"]
        self.assertTrue(act["reference_committed_unchecked_content"])
        self.assertEqual(act["aiqe_commits_created"], 0)
        self.assertIn("STALE_OWNED_CONTENT", act["commit_output"])

    def test_no_receipt_in_the_demo_discloses_a_local_identifier(self):
        """The receipts are the demo's most quotable output. They name
        nothing, and that is checked against the fixture's real values."""
        for act in self.acts.values():
            for field, value in act.items():
                if not field.endswith("receipt_output"):
                    continue
                for secret in ("src/strategy/momentum.py", "src/foreign.py", "main"):
                    self.assertNotIn(secret, value, "%s.%s" % (act["act"], field))


class DemoArtifactPrivacyTests(unittest.TestCase):
    """A retained artifact generated on a real machine can carry that machine.

    The demo runs in a temporary directory under an isolated HOME, so nothing
    should reach the retained files. That is exactly the kind of claim that is
    true until one day it is not.
    """

    def test_no_absolute_path_reaches_a_retained_artifact(self):
        for name in ("demo.json", "transcript.txt"):
            body = read(os.path.join(RETAINED, name))
            for shape in (os.path.expanduser("~"), "/Users/", "/home/", "/tmp/"):
                self.assertNotIn(shape, body, "%s carries %r" % (name, shape))


class DemoDocumentationTests(unittest.TestCase):
    def setUp(self):
        record = json.loads(read(os.path.join(RETAINED, "demo.json")))
        self.acts = {act["act"]: act for act in record["acts"]}
        self.readme = read(README)

    def test_the_readme_demo_output_is_the_retained_output(self):
        """The README's demo excerpt is copied from the artifact, like every
        other terminal block on that page. Membership is asserted without
        putting the README in the message."""
        self.assertTrue(
            self.acts["defect_is_caught"]["check_output"].strip() in self.readme,
            "the README demo block is not the demo's retained output",
        )

    def test_the_readme_shows_the_commands_the_demo_actually_ran(self):
        """The contrast block quotes two invocations. Both must appear in the
        retained transcript exactly as written, or the README is describing a
        workflow the demo did not run."""
        transcript = read(os.path.join(RETAINED, "transcript.txt"))
        for command in (
            "git add -- src/strategy/momentum.py",
            "git commit --quiet --message 'widen the momentum window'",
            "aiqe commit -m 'widen the momentum window'",
        ):
            self.assertIn("$ " + command, transcript, command)
            self.assertTrue(
                command in self.readme,
                "the README quotes a command the demo did not run: %r"
                % (command,),
            )

    def test_the_readme_pathset_contrast_is_the_retained_pathsets(self):
        """The two pathsets are the argument the third act makes. They are
        rendered from the retained arrays rather than retyped."""
        act = self.acts["unrelated_staged_work"]
        for field in ("reference_changed_paths", "aiqe_changed_paths"):
            block = "\n".join("      " + path for path in act[field])
            self.assertTrue(
                block in self.readme,
                "the README does not show the retained %s" % (field,),
            )

    def test_the_demo_readme_names_the_acts_the_demo_runs(self):
        record = json.loads(read(os.path.join(RETAINED, "demo.json")))
        reference = read(os.path.join(DEMO, "README.md"))
        for act in record["acts"]:
            self.assertIn(act["act"], reference, act["act"])

    def test_the_expectation_covers_every_act(self):
        """An act nobody declared an outcome for is an act that cannot fail."""
        with open(os.path.join(DEMO, "expected.json")) as handle:
            expected = json.load(handle)
        record = json.loads(read(os.path.join(RETAINED, "demo.json")))
        self.assertEqual(
            sorted(act["act"] for act in expected["acts"]),
            sorted(act["act"] for act in record["acts"]),
        )


if __name__ == "__main__":
    unittest.main()
