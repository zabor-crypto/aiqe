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
