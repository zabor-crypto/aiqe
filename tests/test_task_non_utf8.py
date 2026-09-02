"""End-to-end proof that an owned path keeps its bytes through a whole task.

The path is declared through the real entry point with byte-preserving argv,
stored, read back, rendered and ended. If any layer decoded a path instead of
carrying its bytes, this is where it would show.

APFS refuses non-UTF-8 filenames, so the case is Linux-only. Setting
AIQE_REQUIRE_NON_UTF8=1 turns skipping into an error; continuous integration
sets it on the Linux job so the proof cannot quietly stop happening.
"""

import os
import sys
import unittest

from . import support

REQUIRED = os.environ.get("AIQE_REQUIRE_NON_UTF8") == "1"
CASE = "non_utf8_owned_path"


class NonUtf8OwnedPathTests(unittest.TestCase):
    def setUp(self):
        if sys.platform.startswith("linux"):
            return
        message = (
            "the arbitrary-byte owned-path fixture needs a filesystem that "
            "accepts non-UTF-8 names; this platform is %r" % (sys.platform,)
        )
        if REQUIRED:
            self.fail("AIQE_REQUIRE_NON_UTF8=1 but the case cannot run here: " + message)
        self.skipTest(message)

    def observe(self):
        return support.task_harness.run_case(CASE)

    def test_lifecycle_succeeds_on_byte_paths(self):
        observed = self.observe()
        self.assertEqual(observed["exit_codes"], [0, 0, 0])
        self.assertFalse(observed["active_after_end"])

    def test_stored_bytes_equal_the_bytes_declared(self):
        observed = self.observe()
        self.assertTrue(
            observed["raw_bytes_roundtrip"],
            "the stored owned path is not byte-identical to the declared one",
        )

    def test_digest_is_stable_over_byte_paths(self):
        first = self.observe()["digest_while_active"]
        second = self.observe()["digest_while_active"]
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("sha256:"))

    def test_output_carries_no_invalid_terminal_bytes(self):
        observed = self.observe()
        self.assertTrue(observed["terminal_safe"])
        for rendered in observed["owned_while_active"]:
            self.assertNotIn("\x1b", rendered)

    def test_safety_invariants_hold_on_byte_paths(self):
        observed = self.observe()
        self.assertEqual(observed["repository_mutations"], 0)
        self.assertEqual(observed["local_state_writes"], 0)
        self.assertEqual(observed["repository_defined_executions"], 0)

    def test_fixture_really_uses_a_non_utf8_name(self):
        with self.assertRaises(UnicodeDecodeError):
            support.task_builders.NON_UTF8_OWNED.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
