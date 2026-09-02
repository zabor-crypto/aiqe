"""The task command surface, its state, and its exit vocabulary.

These run in-process against a real repository. The benchmark family drives
the same behaviour through the installed entry point as subprocesses; this
module is where the boundaries are pinned down cheaply enough to test one at a
time.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import support

from aiqe import exits, taskstate
from aiqe.cli import main
from aiqe.task import OWNERSHIP_SEMANTICS, decode_owned_paths
from aiqe.textsafe import display_bytes, display_text, is_safe


def run(argv, cwd, env):
    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(argv, stdout, stderr, cwd, env)
    return status, stdout.getvalue(), stderr.getvalue()


class TaskTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-task-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        case = support.measurement.Case("task", self.root, ("repo",))
        self.env = case.env()
        self.repo = support.task_builders.base_repo(case.repo_path, self.env)

    def git_dir(self):
        return os.path.join(os.fsencode(self.repo), b".git")

    def active(self):
        return taskstate.read_active(self.git_dir())


class LifecycleTests(TaskTestCase):
    def test_start_status_end(self):
        status, out, _err = run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("src/strategy.py", out)

        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("active", out)

        status, out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIsNone(self.active())

    def test_status_without_a_task_is_a_successful_answer(self):
        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)

    def test_status_creates_no_state(self):
        """A status command that changes state is one nobody can trust."""
        run(["task"], self.repo, self.env)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "aiqe")))

    def test_second_start_is_refused(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        status, _out, err = run(["task", "start", "--own", "other.py"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("already active", err)
        self.assertEqual(decode_owned_paths(self.active()), [b"src/strategy.py"])

    def test_end_without_a_task_is_refused(self):
        status, _out, err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no active task", err)

    def test_task_works_before_init(self):
        """`aiqe init` does not exist yet, and a task must not need it."""
        self.assertFalse(os.path.exists(os.path.join(self.repo, "aiqe.toml")))
        status, _out, _err = run(["task", "start", "--own", "src/x.py"], self.repo, self.env)
        self.assertEqual(status, exits.OK)

    def test_outside_a_repository(self):
        outside = os.path.join(self.root, "not-a-repository")
        os.makedirs(outside)
        status, _out, err = run(["task", "start", "--own", "a.py"], outside, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no Git repository", err)


class RecordTests(TaskTestCase):
    def start(self, *owned, **kwargs):
        argv = ["task", "start"]
        for path in owned:
            argv.extend(["--own", path])
        if kwargs.get("label"):
            argv.extend(["--label", kwargs["label"]])
        return run(argv, self.repo, self.env)

    def test_record_shape(self):
        self.start("src/strategy.py", label="refactor")
        record = self.active()
        for key in (
            "schema_version",
            "ownership_semantics",
            "task_id",
            "aiqe_version",
            "started_at",
            "start_head_state",
            "start_head_sha",
            "owned_paths",
            "owned_pathset_digest",
            "label",
        ):
            self.assertIn(key, record, key)
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["ownership_semantics"], OWNERSHIP_SEMANTICS)
        self.assertEqual(record["ownership_semantics"], "exact_literal_pathset_v1")
        self.assertEqual(record["label"], "refactor")
        self.assertEqual(record["start_head_state"], "commit")

    def test_record_carries_no_identifying_material(self):
        """A local state file should not become an identity document."""
        self.start("src/strategy.py", label="refactor")
        raw = json.dumps(self.active())
        for forbidden in (
            self.repo,
            self.root,
            os.path.expanduser("~"),
            "origin",
            "github",
            "@",
        ):
            self.assertNotIn(forbidden, raw, forbidden)

    def test_task_id_is_opaque(self):
        self.start("src/strategy.py")
        first = self.active()["task_id"]
        run(["task", "end"], self.repo, self.env)
        self.start("src/strategy.py")
        second = self.active()["task_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 32)
        int(first, 16)

    def test_paths_round_trip_as_bytes(self):
        self.start("src/strategy.py", "weird\nname")
        self.assertEqual(
            sorted(decode_owned_paths(self.active())), [b"src/strategy.py", b"weird\nname"]
        )

    def test_unborn_head_is_recorded_as_such(self):
        empty = os.path.join(self.root, "unborn")
        support.task_builders.init_repo(empty, self.env)
        run(["task", "start", "--own", "src/x.py"], empty, self.env)
        record = taskstate.read_active(os.path.join(os.fsencode(empty), b".git"))
        self.assertEqual(record["start_head_state"], "unborn")
        self.assertIsNone(record["start_head_sha"])


class CommandSurfaceTests(TaskTestCase):
    def test_unknown_subcommand(self):
        status, _out, err = run(["task", "resume"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("unknown task subcommand", err)

    def test_start_requires_an_owned_path(self):
        status, _out, err = run(["task", "start"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("--own", err)

    def test_own_requires_a_value(self):
        status, _out, err = run(["task", "start", "--own"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("requires a path", err)

    def test_end_takes_no_arguments(self):
        status, _out, err = run(["task", "end", "now"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no arguments", err)

    def test_a_value_that_looks_like_a_flag_is_a_path(self):
        """`--own --help` declares a path named `--help`. It is data."""
        status, _out, _err = run(
            ["task", "start", "--own", "--help", "--own", "-a"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(sorted(decode_owned_paths(self.active())), [b"--help", b"-a"])

    def test_unimplemented_commands_stay_unimplemented(self):
        for command in ("init", "check", "commit", "receipt"):
            status, out, err = run([command], self.repo, self.env)
            self.assertEqual(status, exits.UNSUPPORTED, command)
            self.assertEqual(out, "", command)
            self.assertIn("unknown command", err, command)


class ExactOwnershipTests(TaskTestCase):
    """v1 owns an exact pathset. No descendants, no directory scope."""

    def test_an_existing_directory_is_refused(self):
        status, _out, err = run(
            ["task", "start", "--own", "src"], self.repo, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("exists as a directory", err)
        self.assertIsNone(self.active())

    def test_a_file_inside_that_directory_is_accepted(self):
        status, _out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(decode_owned_paths(self.active()), [b"src/strategy.py"])

    def test_a_path_that_does_not_exist_yet_is_accepted(self):
        status, _out, _err = run(
            ["task", "start", "--own", "src/future.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_a_symlink_to_a_directory_owns_the_link(self):
        os.symlink("src", os.path.join(self.repo, "linkdir"))
        status, _out, _err = run(
            ["task", "start", "--own", "linkdir"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(decode_owned_paths(self.active()), [b"linkdir"])

    def test_a_lexical_parent_and_child_are_both_recorded(self):
        status, _out, _err = run(
            ["task", "start", "--own", "docs", "--own", "docs/guide.md"],
            self.repo,
            self.env,
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            sorted(decode_owned_paths(self.active())), [b"docs", b"docs/guide.md"]
        )

    def test_the_recorded_pathset_authorises_nothing_further(self):
        from aiqe import scope

        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        owned = decode_owned_paths(self.active())
        self.assertTrue(scope.owned_by_any(owned, b"src/strategy.py"))
        for other in (b"src", b"src/other.py", b"src/strategy.pyc"):
            self.assertFalse(scope.owned_by_any(owned, other), other)


class SchemaTransitionTests(TaskTestCase):
    """An older record meant something else, so it is refused, not reread."""

    def write_v1_record(self):
        state = os.path.join(self.repo, ".git", "aiqe")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "task.json"), "w") as handle:
            json.dump(
                {
                    "schema_version": 1,
                    "task_id": "0" * 32,
                    "aiqe_version": "0.0.0.dev0",
                    "started_at": "2026-09-01T00:00:00Z",
                    "start_head_state": "unborn",
                    "start_head_sha": None,
                    "owned_scope": [{"path_b64": "c3Jj"}],
                    "owned_scope_digest": "sha256:whatever",
                    "label": None,
                },
                handle,
            )

    def test_status_fails_closed(self):
        self.write_v1_record()
        status, _out, err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("schema version 1", err)
        self.assertIn("refused rather than reinterpreted", err)

    def test_start_fails_closed(self):
        self.write_v1_record()
        status, _out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.INCOMPLETE)

    def test_no_silent_migration(self):
        """The old record must not be rewritten or reinterpreted in place."""
        self.write_v1_record()
        path = os.path.join(self.repo, ".git", "aiqe", "task.json")
        with open(path) as handle:
            before = handle.read()
        run(["task"], self.repo, self.env)
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(path) as handle:
            self.assertEqual(handle.read(), before)

    def test_end_discards_it_and_a_new_task_can_start(self):
        self.write_v1_record()
        status, out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("cannot", out)
        status, _out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(self.active()["schema_version"], 2)


class ExitVocabularyTests(TaskTestCase):
    def test_invalid_scope_is_unsupported(self):
        for path in ("/etc/passwd", "..", ".", ".git/config", "src"):
            status, _out, _err = run(
                ["task", "start", "--own", path], self.repo, self.env
            )
            self.assertEqual(status, exits.UNSUPPORTED, path)

    def test_corrupt_record_is_incomplete_not_unsupported(self):
        """Something is there and AIQE will not guess what it is."""
        state = os.path.join(self.repo, ".git", "aiqe")
        os.makedirs(state)
        with open(os.path.join(state, "task.json"), "w") as handle:
            handle.write("not a task record")

        status, _out, err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.INCOMPLETE)
        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("task end", err)

    def test_end_discards_an_unreadable_record(self):
        """The documented way out, so a repository cannot be wedged."""
        state = os.path.join(self.repo, ".git", "aiqe")
        os.makedirs(state)
        with open(os.path.join(state, "task.json"), "w") as handle:
            handle.write("not a task record")

        status, out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("Discarded", out)
        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_unsafe_state_location_is_refused(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.repo, ".git", "aiqe"))

        status, _out, err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("refusing to write through it", err)
        self.assertFalse(os.path.exists(os.path.join(elsewhere, "task.json")))

    def test_task_never_exits_one(self):
        """Exit 1 is a FAIL verdict, and a task boundary adjudicates nothing."""
        for argv in (["task"], ["task", "end"], ["task", "start", "--own", "."]):
            status, _out, _err = run(argv, self.repo, self.env)
            self.assertNotEqual(status, exits.FAIL, argv)


class TerminalSafetyTests(TaskTestCase):
    def test_a_newline_in_a_path_cannot_forge_an_output_row(self):
        forged = "src/a.py\n  Owned scope     0 paths"
        run(["task", "start", "--own", forged], self.repo, self.env)
        _status, out, _err = run(["task"], self.repo, self.env)

        # The escaped path legitimately *contains* that text, on one line.
        # What must not happen is a second row: a line beginning at the
        # report's own label column, which is what a raw newline would create.
        rows = [line for line in out.splitlines() if line.startswith("  Owned pathset")]
        self.assertEqual(len(rows), 1, out)
        self.assertIn("\\n", out)
        for line in out.splitlines():
            self.assertTrue(is_safe(line), repr(line))

    def test_escape_sequences_are_rendered_not_executed(self):
        run(["task", "start", "--own", "src/\x1b[31mred.py"], self.repo, self.env)
        _status, out, _err = run(["task"], self.repo, self.env)
        self.assertNotIn("\x1b", out)
        self.assertIn("\\x1b", out)

    def test_a_label_is_escaped_too(self):
        run(
            ["task", "start", "--own", "src/a.py", "--label", "one\ntwo\x1b[0m"],
            self.repo,
            self.env,
        )
        _status, out, _err = run(["task"], self.repo, self.env)
        self.assertNotIn("\x1b", out)
        for line in out.splitlines():
            self.assertTrue(is_safe(line), repr(line))

    def test_display_does_not_change_what_is_stored(self):
        run(["task", "start", "--own", "weird\nname"], self.repo, self.env)
        self.assertEqual(decode_owned_paths(self.active()), [b"weird\nname"])
        self.assertEqual(display_bytes(b"weird\nname"), "weird\\nname")

    def test_display_is_injective_on_the_escape_character(self):
        self.assertNotEqual(display_bytes(b"a\\nb"), display_bytes(b"a\nb"))
        self.assertEqual(display_text("plain"), "plain")


class AtomicWriteTests(TaskTestCase):
    def test_an_unrenamed_temporary_file_is_not_a_task(self):
        """What a process killed mid-write actually leaves behind."""
        state = os.path.join(self.repo, ".git", "aiqe")
        os.makedirs(state)
        with open(os.path.join(state, ".task.json.tmp.99999"), "w") as handle:
            handle.write('{"schema_version": 1, "task_')

        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)

        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_write_replaces_rather_than_truncating(self):
        """A reader sees the old record or the new one, never a partial one."""
        self.assertTrue(hasattr(taskstate, "_atomic_replace"))
        run(["task", "start", "--own", "src/x.py"], self.repo, self.env)
        record = self.active()
        self.assertEqual(record["schema_version"], 2)

    def test_clear_syncs_the_containing_directory(self):
        """The mechanism, not a durability claim.

        `clear_active` unlinks the record and then fsyncs the directory. That
        is necessary for the deletion to survive power loss, and it is what
        this asserts. It is *not* a proof of power-loss durability, which
        needs power loss; the documented classification stays NOT_PROVEN.
        """
        run(["task", "start", "--own", "src/x.py"], self.repo, self.env)

        synced = []
        real_fsync = os.fsync

        def recording_fsync(descriptor):
            try:
                if os.fstat(descriptor).st_mode & 0o170000 == 0o040000:
                    synced.append(descriptor)
            except OSError:
                pass
            return real_fsync(descriptor)

        os.fsync = recording_fsync
        try:
            taskstate.clear_active(self.git_dir())
        finally:
            os.fsync = real_fsync

        self.assertTrue(synced, "the state directory was not fsynced after unlink")
        self.assertIsNone(self.active())

    def test_lock_is_per_worktree_and_released_on_exit(self):
        git_dir = self.git_dir()
        with taskstate.TaskLock(git_dir):
            with self.assertRaises(taskstate.StateError):
                with taskstate.TaskLock(git_dir, timeout=0.1):
                    pass
        with taskstate.TaskLock(git_dir, timeout=0.1):
            pass


if __name__ == "__main__":
    unittest.main()
