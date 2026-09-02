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
import time
import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import taskstate, validators
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

    def seed(self, contents):
        """Put a consent store on disk the way AIQE would have written one.

        At 0600 deliberately. A store at any other mode is refused before its
        contents are read at all, and that refusal has its own tests: what
        these two are about is a store AIQE wrote and can no longer interpret.
        """
        path = os.path.join(self.root, validators.CONSENT_FILE_NAME)
        with open(path, "w") as handle:
            handle.write(contents)
        os.chmod(path, taskstate.PRIVATE_FILE_MODE)
        return path

    def test_an_unreadable_store_grants_nothing(self):
        """Fail closed: a lost record costs one prompt, the opposite costs more."""
        self.seed("not json at all")
        self.assertFalse(validators.ConsentStore(self.root).granted("sha256:x"))

    def test_a_record_from_another_schema_grants_nothing(self):
        import json

        self.seed(json.dumps({"schema_version": 99, "granted": {"sha256:x": {}}}))
        self.assertFalse(validators.ConsentStore(self.root).granted("sha256:x"))

    def test_a_store_at_any_other_mode_is_refused_rather_than_read(self):
        """The refusal comes before the contents, not after.

        A store somebody else can write is a list of commands they can have
        executed as this user, so it is not parsed and then judged - it is not
        parsed.
        """
        import json

        digest = validators.definition_digest(declared())
        validators.ConsentStore(self.root).grant(digest, "unit")
        os.chmod(
            os.path.join(self.root, validators.CONSENT_FILE_NAME), 0o644
        )
        with self.assertRaises(taskstate.StateError) as caught:
            validators.ConsentStore(self.root)
        self.assertEqual(caught.exception.code, taskstate.LOCAL_STATE_UNSAFE)

    def test_the_record_is_owner_only(self):
        digest = validators.definition_digest(declared())
        validators.ConsentStore(self.root).grant(digest, "unit")
        path = os.path.join(self.root, validators.CONSENT_FILE_NAME)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0)


class ValidatorProcessTestCase(unittest.TestCase):
    """A temporary worktree, and shell scripts to run in it."""

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


class ExecutionTests(ValidatorProcessTestCase):
    def test_exit_zero_is_a_pass(self):
        run = (self.script("ok.sh", "exit 0"),)
        result = self.execute(declared(run=run))
        self.assertEqual(result.outcome, validators.PASS)
        self.assertEqual(result.exit_code, 0)

    def test_a_fast_validator_is_never_mistaken_for_a_timeout(self):
        """End of file on the pipes is not the same as the process being reaped.

        The kernel closes a process's descriptors when it exits and `waitpid`
        reports a moment later. Deciding "timed out" from a single
        non-blocking poll at that instant called a script that had already
        exited 0 a timeout - rarely, and only under load, which is the worst
        way for a bug like this to behave. Repetition is the test: one run
        would pass with the defect still present.
        """
        run = (self.script("fast.sh", "exit 0"),)
        validator = declared(run=run)
        outcomes = [self.execute(validator).outcome for _ in range(40)]
        self.assertEqual(
            sorted(set(outcomes)),
            [validators.PASS],
            "a validator that exits 0 immediately was misclassified",
        )

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

    def test_a_timeout_terminates_the_process_group_aiqe_created(self):
        """The claim is the process group, and only the process group.

        A script's ordinary children are in it, and they inherit its pipes:
        killing only the process AIQE started leaves them holding the pipe
        open, and the bounded wait turns into the full duration of whatever
        the validator spawned. This asserts the wall clock, because that is
        the property.

        It is not a containment claim. A child that leaves the group survives,
        and the benchmark keeps a fixture that demonstrates it.
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

    def test_the_bounded_tail_holds_only_the_budget(self):
        """The buffer, on its own, before anything else depends on it."""
        tail = validators._BoundedTail(16)
        for _ in range(1000):
            tail.add(b"0123456789")
        self.assertEqual(len(tail.value()), 16)
        self.assertEqual(tail.total, 10000)
        self.assertTrue(tail.truncated)

    def test_the_bounded_tail_keeps_the_end_of_the_stream(self):
        """The retention policy is `tail`: a failure's last lines say why."""
        tail = validators._BoundedTail(4)
        tail.add(b"abcdefgh")
        self.assertEqual(tail.value(), b"efgh")
        self.assertEqual(validators.RETENTION_POLICY, "tail")

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


class StreamingCaptureTests(ValidatorProcessTestCase):
    """Output is bounded while it is being read, not after.

    A validator may be buggy or hostile and emit gigabytes. The memory AIQE
    spends on it must not be a function of how much it decided to print, and
    the only way to know that is to measure it rather than to read the code
    and agree with it.
    """

    #: Bytes per stream in the stress fixtures. Three orders of magnitude
    #: above the retention budget, and fast to produce.
    MEGABYTE = 1048576

    def loud(self, name, megabytes, exit_code=1):
        """A validator that emits `megabytes` on each stream, then exits."""
        return self.script(
            name,
            "yes 0123456789abcdef0123456789abcdef | head -c %d\n"
            "yes 0123456789abcdef0123456789abcdef | head -c %d >&2\n"
            "exit %d"
            % (megabytes * self.MEGABYTE, megabytes * self.MEGABYTE, exit_code),
        )

    def rendered_bytes(self, outcome):
        total = 0
        for tail in (outcome.stdout_tail, outcome.stderr_tail):
            if tail:
                total += len(tail.encode("utf-8"))
        return total

    def test_a_validator_that_far_exceeds_the_budget_still_completes(self):
        run = (self.loud("loud.sh", 32),)
        started = time.monotonic()
        outcome = self.execute(declared(run=run))
        elapsed = time.monotonic() - started

        self.assertEqual(outcome.outcome, validators.FAIL)
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(outcome.timed_out)
        self.assertLess(
            elapsed, 30, "64 MB of validator output should not take 30 seconds"
        )

    def test_a_validator_that_fills_the_pipe_does_not_deadlock(self):
        """A pipe nobody reads fills and blocks the writer forever.

        This validator emits far more than any pipe buffer and then exits 0.
        Reaching `PASS` at all is the assertion: it means the drain kept
        running for the whole life of the process rather than only at the end.
        """
        run = (self.loud("quiet-pass.sh", 8, exit_code=0),)
        outcome = self.execute(declared(run=run, timeout=30))
        self.assertEqual(outcome.outcome, validators.PASS)
        self.assertIsNone(outcome.stdout_tail)
        self.assertIsNone(outcome.stderr_tail)

    def test_retained_output_stays_within_the_budget(self):
        run = (self.loud("loud-retained.sh", 8),)
        outcome = self.execute(declared(run=run))

        for tail in (outcome.stdout_tail, outcome.stderr_tail):
            self.assertIsNotNone(tail)
            self.assertIn("earlier output not retained", tail)
            # The captured bytes are bounded by the budget. Rendering escapes
            # them for the terminal, and one byte can become four characters,
            # so the rendered field is bounded by four times the budget plus
            # AIQE's own fixed marker - not by what the validator emitted.
            self.assertLessEqual(
                len(tail.encode("utf-8")),
                4 * validators.OUTPUT_BUDGET_BYTES + 64,
            )

    def test_peak_memory_does_not_track_the_validator_s_output(self):
        """The property, measured: peak allocation against emitted volume.

        A 32-fold increase in what the validator prints must not move the peak
        meaningfully. An implementation that buffered the stream and truncated
        afterwards would fail this by roughly the difference in output size.
        """
        import tracemalloc

        def peak_for(name, megabytes):
            run = (self.loud(name, megabytes),)
            tracemalloc.start()
            try:
                outcome = self.execute(declared(run=run))
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertEqual(outcome.outcome, validators.FAIL)
            return peak

        small = peak_for("peak-small.sh", 1)
        large = peak_for("peak-large.sh", 32)

        self.assertLess(
            large,
            small + 1048576,
            "peak allocation grew with validator output: %d B for 1 MB per "
            "stream, %d B for 32 MB per stream" % (small, large),
        )

    def test_large_output_with_a_timeout_is_bounded_and_still_a_failure(self):
        """The hard case: an unbounded emitter that never finishes.

        `yes` writes until it is stopped, so nothing about this run ends on its
        own. The timeout has to hold, the memory has to hold, and the outcome
        has to be a failure rather than an unknown.
        """
        import tracemalloc

        run = (self.script("forever.sh", "yes 0123456789abcdef0123456789abcdef"),)
        tracemalloc.start()
        try:
            started = time.monotonic()
            outcome = self.execute(declared(run=run, timeout=1))
            elapsed = time.monotonic() - started
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(outcome.outcome, validators.FAIL)
        self.assertTrue(outcome.timed_out)
        self.assertEqual(outcome.reason, validators.TIMED_OUT)
        self.assertLess(elapsed, 15, "the timeout did not bound the run")
        self.assertLess(peak, 4194304, "peak allocation was %d B" % (peak,))
        self.assertLessEqual(
            len((outcome.stdout_tail or "").encode("utf-8")),
            4 * validators.OUTPUT_BUDGET_BYTES + 64,
        )


if __name__ == "__main__":
    unittest.main()
