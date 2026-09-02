"""End-to-end proof that a path Git records as bytes survives a Doctor run.

A filename on POSIX is a byte string. Only some filesystems additionally
require it to be well-formed text, and APFS is one of them - a non-UTF-8 name
cannot be created on macOS at all, which is why this proof is Linux-only
rather than skipped everywhere.

Feeding invalid bytes to a parser would not establish much. This builds a real
repository, lets Git record the names, and reads them back through the whole
pipeline: discovery, the tracked listing, the working-state comparison, and
both renderings. If any layer decoded a path instead of carrying its bytes,
this is where it raises.

Set AIQE_REQUIRE_NON_UTF8=1 to make skipping an error. Continuous integration
sets it on the Linux job, so the proof cannot quietly stop happening.
"""

import json
import os
import sys
import unittest

from . import support

REQUIRED = os.environ.get("AIQE_REQUIRE_NON_UTF8") == "1"
CASE = "non_utf8_path"


class NonUtf8PathTests(unittest.TestCase):
    def setUp(self):
        if sys.platform.startswith("linux"):
            return
        message = (
            "the arbitrary-byte path fixture needs a filesystem that accepts "
            "non-UTF-8 names; this platform is %r" % (sys.platform,)
        )
        if REQUIRED:
            self.fail(
                "AIQE_REQUIRE_NON_UTF8=1 but the case cannot run here: " + message
            )
        self.skipTest(message)

    def observe(self):
        return support.harness.run_case(CASE)

    def test_doctor_completes_on_byte_paths(self):
        observed = self.observe()
        self.assertEqual(observed["result"], "PRODUCED")
        self.assertEqual(observed["exit_code"], 0)

    def test_counts_are_correct(self):
        """The bytes must not merely survive; they must be counted correctly."""
        observed = self.observe()
        state = observed["working_state"]
        self.assertTrue(state["determined"])
        self.assertEqual(state["staged"], 1)
        self.assertEqual(state["unstaged"], 1)
        self.assertEqual(state["untracked"], 1)

    def test_json_output_is_valid(self):
        observed = self.observe()
        rendered = json.dumps(observed["json_output"])
        self.assertEqual(json.loads(rendered)["result"], "PRODUCED")

    def test_no_path_bytes_reach_the_output(self):
        """Byte-safety must not be demonstrated by printing the path."""
        observed = self.observe()
        rendered = observed["human_output"] + json.dumps(observed["json_output"])
        for fragment in ("tracked-", "staged-", "untracked-", "\\ud", "\\ufffd"):
            self.assertNotIn(fragment, rendered, fragment)

    def test_safety_invariants_hold_on_byte_paths(self):
        observed = self.observe()
        self.assertEqual(observed["repository_mutations"], 0)
        self.assertEqual(observed["repository_defined_executions"], 0)
        self.assertEqual(observed["local_state_writes"], 0)

    def test_fixture_really_contains_non_utf8_names(self):
        """Guard against a fixture that silently stopped being the hard case."""
        for name in (
            support.builders.NON_UTF8_TRACKED,
            support.builders.NON_UTF8_STAGED,
            support.builders.NON_UTF8_UNTRACKED,
        ):
            with self.assertRaises(UnicodeDecodeError, msg=repr(name)):
                name.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
