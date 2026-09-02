"""Machine-local state privacy, and the lifecycle of check evidence.

Local evidence can hold a failing validator's output, and a failing
validator's output can hold anything that validator printed. AIQE does not go
looking for secrets, but it is not in a position to promise there are none in
there either - so the privacy of these files must not depend on whoever ran
the command having a sensible umask.

Every test in the first half therefore runs under `umask(0)`, the most
permissive setting there is. A file that is 0600 under that umask is 0600
because AIQE asked for it, not because the process happened to be configured
helpfully.

The second half is the evidence lifecycle: one active record, replaced whole,
removed with the task, and never inherited by the next one.
"""

import io
import json
import os
import shutil
import stat
import tempfile
import unittest

from . import support

from aiqe import evidence, exits, taskstate, validators
from aiqe.cli import main

builders = support.check_builders

CONFIG = builders.config(
    [
        builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        builders.NON_QUANT,
        builders.validator("unit", ["./checks/unit.sh"], True, 60),
        builders.validator(
            "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
        ),
    ]
)
SCRIPTS = [builders.script("unit"), builders.script("causality")]


class LocalStateTestCase(unittest.TestCase):
    """A real repository, driven through the real command surface."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-privacy-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("privacy", self.root, ("repo",))
        self.env = self.case.env()
        self.repo = builders.build_repository(
            self.case, self.env, CONFIG, SCRIPTS, edit_owned=True
        )

    def run_cli(self, argv, prompt=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env, prompt=prompt)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self):
        status, _out, err = self.run_cli(
            ["task", "start", "--own", builders.OWNED_TEXT]
        )
        self.assertEqual(status, exits.OK, err)

    def check(self, *allow, **kwargs):
        arguments = ["check"]
        for identifier in allow:
            arguments += ["--allow", identifier]
        return self.run_cli(arguments, prompt=kwargs.get("prompt"))[0]

    def state_directory(self):
        from aiqe.gitq import GitRunner

        salt = taskstate.read_salt(self.env)
        if salt is None:
            return None
        runner = GitRunner(self.repo, env=self.env)
        result = runner.run("rev-parse", "--git-dir", "--git-common-dir")
        base = os.fsencode(self.repo)
        resolved = [
            line if os.path.isabs(line) else os.path.normpath(os.path.join(base, line))
            for line in result.lines()
        ]
        key = taskstate.derive_key(salt, resolved[1], resolved[0])
        return taskstate.worktree_state_directory(key, self.env)

    def state_path(self, name):
        return os.path.join(self.state_directory(), name)

    def mode(self, path):
        return stat.S_IMODE(os.lstat(path).st_mode)


class PermissiveUmaskTests(LocalStateTestCase):
    """The modes AIQE asks for, with the umask granting everything."""

    def setUp(self):
        LocalStateTestCase.setUp(self)
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    def test_the_umask_really_is_permissive(self):
        """Otherwise every assertion below would be proving the umask's work."""
        probe = os.path.join(self.root, "probe")
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT, 0o666)
        os.close(descriptor)
        self.assertEqual(self.mode(probe), 0o666)

    def test_the_state_root_and_worktree_directory_are_owner_only(self):
        self.start()
        for directory in (taskstate.state_root(self.env), self.state_directory()):
            self.assertEqual(
                self.mode(directory) & 0o077,
                0,
                "%s is readable or writable beyond its owner" % (directory,),
            )
            self.assertEqual(self.mode(directory), taskstate.STATE_DIRECTORY_MODE)

    def test_the_salt_is_owner_only(self):
        self.start()
        self.assertEqual(
            self.mode(taskstate.salt_path(self.env)), taskstate.SALT_MODE
        )

    def test_the_task_record_is_owner_only(self):
        self.start()
        self.assertEqual(self.mode(self.state_path(taskstate.ACTIVE_TASK_NAME)), 0o600)

    def test_the_check_evidence_is_owner_only(self):
        """It can hold a failing validator's output."""
        self.start()
        self.check("unit", "causality")
        self.assertEqual(self.mode(self.state_path(evidence.CHECK_FILE_NAME)), 0o600)

    def test_the_consent_record_is_owner_only(self):
        self.start()
        self.check(prompt=lambda _text: True)
        self.assertEqual(
            self.mode(self.state_path(validators.CONSENT_FILE_NAME)), 0o600
        )

    def test_the_lock_file_is_owner_only(self):
        self.start()
        self.assertEqual(self.mode(self.state_path(taskstate.LOCK_NAME)), 0o600)

    def test_no_temporary_file_is_ever_broader_than_its_final_form(self):
        """The window between creating a file and renaming it into place.

        Checking the final mode is not enough: a temporary file created 0644
        and renamed over a 0600 name would leave the final mode correct and
        still have published the contents for as long as the write took. So
        the mode is observed at the moment of the rename, from inside it.
        """
        observed = []
        original_replace = os.replace
        original_link = os.link

        def watched_replace(source, destination):
            observed.append((os.path.basename(destination), self.mode(source)))
            return original_replace(source, destination)

        def watched_link(source, destination):
            observed.append((os.path.basename(destination), self.mode(source)))
            return original_link(source, destination)

        os.replace = watched_replace
        os.link = watched_link
        try:
            self.start()
            self.check(prompt=lambda _text: True)
            self.check("unit", "causality")
        finally:
            os.replace = original_replace
            os.link = original_link

        self.assertTrue(observed, "no atomic write was observed")
        for name, mode in observed:
            self.assertEqual(
                mode & 0o077, 0, "%s was world- or group-accessible while being written"
                % (name,),
            )

        written = {name for name, _mode in observed}
        for expected in (
            taskstate.SALT_NAME,
            taskstate.ACTIVE_TASK_NAME,
            evidence.CHECK_FILE_NAME,
            validators.CONSENT_FILE_NAME,
        ):
            self.assertIn(expected, written)

    def test_a_failing_validator_s_output_lands_only_in_an_owner_only_file(self):
        """The reason this whole class exists, stated as a test."""
        self.repo = builders.build_repository(
            support.measurement.Case("privacy-fail", self.root + "-b", ("repo",)),
            self.env,
            CONFIG,
            [
                builders.script("unit"),
                builders.script("causality", body="echo SENSITIVE >&2; exit 1"),
            ],
        )
        self.addCleanup(shutil.rmtree, self.root + "-b", True)

        self.start()
        self.assertEqual(self.check("unit", "causality"), exits.FAIL)
        path = self.state_path(evidence.CHECK_FILE_NAME)
        with open(path) as handle:
            self.assertIn("SENSITIVE", handle.read())
        self.assertEqual(self.mode(path), 0o600)


class EvidenceLifecycleTests(LocalStateTestCase):
    """One active record. Replaced whole, removed with the task, never inherited."""

    def evidence_path(self):
        return self.state_path(evidence.CHECK_FILE_NAME)

    def consent_path(self):
        return self.state_path(validators.CONSENT_FILE_NAME)

    def test_a_check_creates_evidence_and_task_end_removes_it(self):
        self.start()
        self.check(prompt=lambda _text: True)
        self.assertTrue(os.path.exists(self.evidence_path()))
        self.assertTrue(os.path.exists(self.consent_path()))

        self.run_cli(["task", "end"])
        self.assertFalse(
            os.path.exists(self.evidence_path()),
            "evidence about an abandoned unit of work is not evidence",
        )
        self.assertTrue(
            os.path.exists(self.consent_path()),
            "consenting to run a command is a statement about the command",
        )

    def test_a_new_task_cannot_observe_the_previous_task_s_evidence(self):
        self.start()
        self.check("unit", "causality")
        first = evidence.read(self.state_directory())
        self.run_cli(["task", "end"])

        # Put it back, as a task that ended badly would have left it.
        evidence.write(self.state_directory(), first)
        self.start()

        self.assertIsNone(evidence.read(self.state_directory()))
        self.assertFalse(os.path.exists(self.evidence_path()))

    def test_a_receipt_for_the_new_task_reports_no_evidence(self):
        """The lifecycle from the outside, not from the state directory."""
        self.start()
        self.check("unit", "causality")
        self.run_cli(["task", "end"])
        self.start()

        _status, out, _err = self.run_cli(["receipt", "--format", "json"])
        document = json.loads(out)
        self.assertEqual(document["evidence"], "NONE")
        self.assertEqual(document["owned_scope"], "DECLARED")

    def test_a_second_check_replaces_the_first_atomically(self):
        """Never a partial record on disk, and never two.

        The observation is taken from inside the rename: whatever a reader
        would have seen at that instant must be the previous record, whole and
        parseable - not half of the new one.
        """
        self.start()
        self.check("unit", "causality")
        with open(self.evidence_path(), "rb") as handle:
            first = handle.read()
        self.assertEqual(json.loads(first)["result"]["completion"], "REVIEWABLE_CANDIDATE")

        seen = []
        original_replace = os.replace

        def watched_replace(source, destination):
            if os.path.basename(destination) == evidence.CHECK_FILE_NAME:
                with open(destination, "rb") as handle:
                    seen.append(handle.read())
            return original_replace(source, destination)

        with open(os.path.join(self.repo, "checks", "causality.sh"), "w") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(self.repo, "checks", "causality.sh"), 0o755)

        os.replace = watched_replace
        try:
            self.assertEqual(self.check("unit", "causality"), exits.FAIL)
        finally:
            os.replace = original_replace

        self.assertEqual(len(seen), 1, "the record was not replaced exactly once")
        self.assertEqual(
            seen[0], first, "a reader mid-replacement saw something other than the "
            "previous complete record"
        )

        with open(self.evidence_path(), "rb") as handle:
            second = handle.read()
        self.assertEqual(json.loads(second)["result"]["completion"], "NOT_REVIEWABLE")

        # One record, not a history.
        self.assertEqual(
            sorted(
                name
                for name in os.listdir(self.state_directory())
                if name.startswith("check")
            ),
            [evidence.CHECK_FILE_NAME],
        )

    def test_a_refused_check_leaves_no_new_evidence(self):
        """A configuration that says two things about one file is not a result."""
        self.start()
        self.check("unit", "causality")
        with open(self.evidence_path(), "rb") as handle:
            before = handle.read()

        conflicting = builders.config(
            [
                builders.surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
                builders.surface(["**/alpha.py"], quant=False),
                builders.NON_QUANT,
                builders.validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write(conflicting)

        self.assertEqual(self.check("unit"), exits.UNSUPPORTED)
        with open(self.evidence_path(), "rb") as handle:
            self.assertEqual(handle.read(), before, "a refused check wrote evidence")

        # And the refusal is not hidden behind a stale receipt either.
        status, out, _err = self.run_cli(["receipt", "--format", "json"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertEqual(out, "")

    def test_there_is_no_history(self):
        """Four checks, one record. The state directory does not accumulate."""
        self.start()
        for _ in range(4):
            self.check("unit", "causality")
        self.assertEqual(
            sorted(os.listdir(self.state_directory())),
            sorted(
                [
                    taskstate.ACTIVE_TASK_NAME,
                    taskstate.LOCK_NAME,
                    evidence.CHECK_FILE_NAME,
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
