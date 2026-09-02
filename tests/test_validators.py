"""Validator identity, consent, and execution outcomes.

The three things this module pins down are the three that make running
repository-declared code defensible: what a validator *is* (its definition
digest), whether it may run (consent, per digest, machine-local), and what its
process outcome means.
"""

import os
import shutil
import stat
import tempfile
import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import validators
from aiqe.config import parse


def declared(
    identifier="unit",
    run=("./run.sh",),
    required=True,
    timeout=60,
    contracts=(),
):
    lines = [
        "schema = 1",
        "[[validator]]",
        'id = "%s"' % identifier,
        "run = [%s]" % ", ".join('"%s"' % part for part in run),
        "required = %s" % ("true" if required else "false"),
        "timeout = %d" % timeout,
    ]
    if contracts:
        lines.append("contracts = [%s]" % ", ".join('"%s"' % c for c in contracts))
    return parse(("\n".join(lines) + "\n").encode("utf-8")).validators[0]


class DefinitionDigestTests(unittest.TestCase):
    def digest(self, **overrides):
        return validators.definition_digest(declared(**overrides))

    def test_the_digest_is_deterministic(self):
        self.assertEqual(self.digest(), self.digest())

    def test_every_semantic_field_changes_the_identity(self):
        base = self.digest()
        self.assertNotEqual(base, self.digest(identifier="other"))
        self.assertNotEqual(base, self.digest(run=("./other.sh",)))
        self.assertNotEqual(base, self.digest(timeout=61))
        self.assertNotEqual(base, self.digest(required=False))
        self.assertNotEqual(base, self.digest(contracts=("CAUSALITY",)))

    def test_contract_order_is_not_part_of_the_identity(self):
        """Reordering a list must not revoke somebody's consent."""
        self.assertEqual(
            self.digest(contracts=("CAUSALITY", "DETERMINISM")),
            self.digest(contracts=("DETERMINISM", "CAUSALITY")),
        )

    def test_argument_boundaries_are_part_of_the_identity(self):
        """Two argument vectors that would render alike are different.

        `["a b"]` and `["a", "b"]` are one argument and two. A digest over a
        rendering could not tell them apart, and the second is a different
        command.
        """
        self.assertNotEqual(self.digest(run=("a b",)), self.digest(run=("a", "b")))

    def test_the_digest_is_domain_separated(self):
        import hashlib

        self.assertNotEqual(
            self.digest(), "sha256:" + hashlib.sha256(b"unit").hexdigest()
        )


class ConsentStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-consent-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_an_empty_store_grants_nothing(self):
        store = validators.ConsentStore(self.root)
        self.assertFalse(store.granted("sha256:anything"))

    def test_a_grant_is_readable_by_a_new_store(self):
        digest = validators.definition_digest(declared())
        validators.ConsentStore(self.root).grant(digest, "unit")
        self.assertTrue(validators.ConsentStore(self.root).granted(digest))

    def test_consent_is_bound_to_the_exact_definition(self):
        """The whole mechanism: change the definition, lose the consent."""
        original = validators.definition_digest(declared())
        validators.ConsentStore(self.root).grant(original, "unit")

        drifted = validators.definition_digest(declared(timeout=90))
        store = validators.ConsentStore(self.root)
        self.assertTrue(store.granted(original))
        self.assertFalse(store.granted(drifted))

    def test_an_unreadable_store_grants_nothing(self):
        """Fail closed: a lost record costs one prompt, the opposite costs more."""
        with open(os.path.join(self.root, validators.CONSENT_FILE_NAME), "w") as handle:
            handle.write("not json at all")
        self.assertFalse(validators.ConsentStore(self.root).granted("sha256:x"))

    def test_a_record_from_another_schema_grants_nothing(self):
        import json

        path = os.path.join(self.root, validators.CONSENT_FILE_NAME)
        with open(path, "w") as handle:
            json.dump({"schema_version": 99, "granted": {"sha256:x": {}}}, handle)
        self.assertFalse(validators.ConsentStore(self.root).granted("sha256:x"))

    def test_the_record_is_owner_only(self):
        digest = validators.definition_digest(declared())
        validators.ConsentStore(self.root).grant(digest, "unit")
        path = os.path.join(self.root, validators.CONSENT_FILE_NAME)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-validator-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.worktree = os.fsencode(self.root)

    def script(self, name, body):
        path = os.path.join(self.root, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return "./" + name

    def execute(self, validator):
        return validators.execute(
            validator, "sha256:x", self.worktree, dict(os.environ)
        )

    def test_exit_zero_is_a_pass(self):
        run = (self.script("ok.sh", "exit 0"),)
        result = self.execute(declared(run=run))
        self.assertEqual(result.outcome, validators.PASS)
        self.assertEqual(result.exit_code, 0)

    def test_a_non_zero_exit_is_a_failure(self):
        run = (self.script("bad.sh", "exit 7"),)
        result = self.execute(declared(run=run))
        self.assertEqual(result.outcome, validators.FAIL)
        self.assertEqual(result.exit_code, 7)

    def test_a_timeout_is_a_failure(self):
        """R11 is explicit, and it is the right rule.

        A validator that did not finish did not establish what it was asked
        to establish. Calling that merely unknown turns an unbounded check
        into a permanent excuse.
        """
        run = (self.script("slow.sh", "sleep 30"),)
        result = self.execute(declared(run=run, timeout=1))
        self.assertEqual(result.outcome, validators.FAIL)
        self.assertTrue(result.timed_out)
        self.assertIs(result.exit_code, None)
        self.assertEqual(result.reason, validators.TIMED_OUT)

    def test_a_timeout_ends_the_children_a_validator_started(self):
        """The timeout must bound the whole tree, not just the top of it.

        A script's children inherit its pipes. Killing only the process AIQE
        started leaves them holding the pipe open, and the bounded wait turns
        into the full duration of whatever the validator spawned. This asserts
        the wall-clock, because that is the property.
        """
        import time

        run = (self.script("spawner.sh", "sleep 30 & sleep 30"),)
        started = time.monotonic()
        result = self.execute(declared(run=run, timeout=1))
        elapsed = time.monotonic() - started

        self.assertEqual(result.outcome, validators.FAIL)
        self.assertTrue(result.timed_out)
        self.assertLess(
            elapsed,
            10,
            "the timeout did not bound the run: %.1fs elapsed" % (elapsed,),
        )

    def test_a_missing_executable_is_unavailable(self):
        result = self.execute(declared(run=("./not-installed.sh",)))
        self.assertEqual(result.outcome, validators.UNAVAILABLE)
        self.assertEqual(result.reason, validators.EXECUTABLE_NOT_FOUND)

    def test_a_non_executable_file_is_unavailable(self):
        path = os.path.join(self.root, "plain.sh")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o644)
        result = self.execute(declared(run=("./plain.sh",)))
        self.assertEqual(result.outcome, validators.UNAVAILABLE)
        self.assertEqual(result.reason, validators.NOT_EXECUTABLE)

    def test_there_is_no_shell(self):
        """Nothing in aiqe.toml is word-split, glob-expanded or substituted."""
        run = (self.script("args.sh", 'test "$1" = "a b" || exit 3'), "a b")
        self.assertEqual(self.execute(declared(run=run)).outcome, validators.PASS)

    def test_the_working_directory_is_the_repository_root(self):
        run = (self.script("cwd.sh", "test -f ./cwd.sh || exit 4"),)
        self.assertEqual(self.execute(declared(run=run)).outcome, validators.PASS)

    def test_output_from_a_passing_validator_is_discarded(self):
        run = (self.script("chatty.sh", "echo hello; exit 0"),)
        result = self.execute(declared(run=run))
        self.assertIs(result.stdout_tail, None)
        self.assertIs(result.stderr_tail, None)

    def test_output_from_a_failing_validator_is_retained_and_bounded(self):
        run = (
            self.script(
                "loud.sh",
                "i=0; while [ $i -lt 4000 ]; do echo '0123456789'; "
                "i=$((i+1)); done; exit 1",
            ),
        )
        result = self.execute(declared(run=run))
        self.assertEqual(result.outcome, validators.FAIL)
        self.assertIsNotNone(result.stdout_tail)
        self.assertLessEqual(
            len(result.stdout_tail.encode("utf-8")),
            validators.OUTPUT_BUDGET_BYTES + 200,
        )
        self.assertIn("earlier output not retained", result.stdout_tail)

    def test_retained_output_is_terminal_safe(self):
        """A validator's output is attacker-controlled bytes."""
        from aiqe.textsafe import is_safe

        run = (self.script("escape.sh", "printf 'a\\033[31mred\\007\\n'; exit 1"),)
        result = self.execute(declared(run=run))
        self.assertTrue(is_safe(result.stdout_tail))

    def test_a_validator_gets_no_standard_input(self):
        run = (self.script("stdin.sh", "read line && exit 5; exit 0"),)
        self.assertEqual(self.execute(declared(run=run)).outcome, validators.PASS)


if __name__ == "__main__":
    unittest.main()
