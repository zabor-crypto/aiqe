"""The task command surface, its machine-local state, and its exit vocabulary.

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

from aiqe import exits, scope, taskstate
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

    def state_root(self):
        return taskstate.state_root(self.env)

    def salt_exists(self):
        return os.path.exists(taskstate.salt_path(self.env))

    def state_directory(self, worktree=None):
        """This worktree's machine-local directory, or None if none exists."""
        salt = taskstate.read_salt(self.env)
        if salt is None:
            return None
        target = worktree or self.repo
        git_dir, common_dir = self.git_dirs(target)
        key = taskstate.derive_key(salt, common_dir, git_dir)
        return taskstate.worktree_state_directory(key, self.env)

    def git_dirs(self, worktree):
        from aiqe.gitq import GitRunner

        runner = GitRunner(worktree, env=self.env)
        result = runner.run("rev-parse", "--git-dir", "--git-common-dir")
        base = os.fsencode(worktree)
        resolved = []
        for line in result.lines():
            resolved.append(
                line if os.path.isabs(line) else os.path.normpath(os.path.join(base, line))
            )
        return resolved[0], resolved[1]

    def active(self, worktree=None):
        return taskstate.read_active(self.state_directory(worktree))


class LifecycleTests(TaskTestCase):
    def test_start_status_end(self):
        status, out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertIn("src/strategy.py", out)

        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("active", out)

        status, _out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIsNone(self.active())

    def test_status_without_a_task_is_a_successful_answer(self):
        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)

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


class MachineLocalStateTests(TaskTestCase):
    """State is machine-local, and names no repository."""

    def test_nothing_is_written_inside_the_repository(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        run(["task"], self.repo, self.env)
        run(["task", "end"], self.repo, self.env)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "aiqe")))
        git_dir = os.path.join(self.repo, ".git")
        for directory, subdirectories, filenames in os.walk(git_dir):
            for name in subdirectories + filenames:
                # Relative, because the enclosing temporary directory is
                # itself named after the project.
                relative = os.path.relpath(os.path.join(directory, name), git_dir)
                self.assertNotIn("aiqe", relative.lower(), relative)

    def test_state_lives_under_the_xdg_state_directory(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        directory = self.state_directory()
        self.assertTrue(directory.startswith(self.env["XDG_STATE_HOME"]))
        self.assertTrue(os.path.isfile(os.path.join(directory, "task.json")))

    def test_the_fallback_is_the_conventional_one(self):
        env = dict(self.env)
        env.pop("XDG_STATE_HOME")
        env["HOME"] = "/example/home"
        self.assertEqual(
            taskstate.state_root(env), os.path.join("/example/home", ".local", "state", "aiqe")
        )

    def test_the_directory_token_reveals_no_repository(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        token = os.path.basename(self.state_directory())
        self.assertEqual(len(token), 64)
        int(token, 16)
        for fragment in (self.repo, os.path.basename(self.repo), "repo", ".git"):
            self.assertNotIn(fragment, token)

    def test_the_record_holds_no_repository_identity(self):
        run(
            ["task", "start", "--own", "src/strategy.py", "--label", "demo"],
            self.repo,
            self.env,
        )
        raw = json.dumps(self.active())
        for forbidden in (
            self.repo,
            self.root,
            self.env["HOME"],
            ".git",
            "origin",
            "github",
            "@",
        ):
            self.assertNotIn(forbidden, raw, forbidden)


class SaltTests(TaskTestCase):
    def test_status_creates_no_salt_and_no_state(self):
        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)
        self.assertFalse(self.salt_exists())
        self.assertFalse(os.path.exists(self.state_root()))

    def test_doctor_creates_no_salt_and_no_state(self):
        status, _out, _err = run(["doctor"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertFalse(os.path.exists(self.state_root()))

    def test_a_refused_start_creates_no_salt_and_no_state(self):
        """Validation happens before the first write, on purpose."""
        for argv in (
            ["task", "start", "--own", "src"],
            ["task", "start", "--own", "/etc/passwd"],
            ["task", "start", "--own", "a.py", "--own", "a.py"],
        ):
            status, _out, _err = run(argv, self.repo, self.env)
            self.assertEqual(status, exits.UNSUPPORTED, argv)
            self.assertFalse(self.salt_exists(), argv)
            self.assertFalse(os.path.exists(self.state_root()), argv)

    def test_start_creates_the_salt(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        self.assertTrue(self.salt_exists())

    def test_salt_is_thirty_two_random_bytes_readable_only_by_its_owner(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        path = taskstate.salt_path(self.env)
        with open(path, "rb") as handle:
            salt = handle.read()
        self.assertEqual(len(salt), taskstate.SALT_BYTES)
        self.assertEqual(len(salt), 32)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotEqual(salt, b"\0" * 32)

    def test_the_salt_is_created_once_and_reused(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(taskstate.salt_path(self.env), "rb") as handle:
            first = handle.read()
        run(["task", "end"], self.repo, self.env)
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(taskstate.salt_path(self.env), "rb") as handle:
            self.assertEqual(handle.read(), first)

    def test_ensure_salt_converges_when_one_already_exists(self):
        """The loser of a first-write race adopts the winner's salt."""
        first = taskstate.ensure_salt(self.env)
        second = taskstate.ensure_salt(self.env)
        self.assertEqual(first, second)
        entries = os.listdir(self.state_root())
        self.assertEqual([e for e in entries if e == "salt"], ["salt"])
        self.assertEqual([e for e in entries if e.startswith(".")], [])

    def test_a_truncated_salt_is_refused_rather_than_used(self):
        os.makedirs(self.state_root(), exist_ok=True)
        with open(taskstate.salt_path(self.env), "wb") as handle:
            handle.write(b"short")
        with self.assertRaises(taskstate.StateError):
            taskstate.read_salt(self.env)


class DerivedKeyTests(TaskTestCase):
    def test_the_key_binds_both_git_directories(self):
        salt = b"\x01" * 32
        common = b"/x/.git"
        self.assertNotEqual(
            taskstate.derive_key(salt, common, b"/x/.git"),
            taskstate.derive_key(salt, common, b"/x/.git/worktrees/a"),
        )

    def test_a_different_salt_gives_a_different_key(self):
        self.assertNotEqual(
            taskstate.derive_key(b"\x01" * 32, b"/x/.git", b"/x/.git"),
            taskstate.derive_key(b"\x02" * 32, b"/x/.git", b"/x/.git"),
        )

    def test_the_separator_prevents_a_path_pair_collision(self):
        """NUL cannot appear in a path, so no two pairs share an input."""
        salt = b"\x03" * 32
        self.assertNotEqual(
            taskstate.derive_key(salt, b"/a", b"/bc"),
            taskstate.derive_key(salt, b"/ab", b"/c"),
        )


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
            "start_head_sha",
            "owned_paths",
            "owned_pathset_digest",
            "foreign_staged_count_at_start",
            "label",
        ):
            self.assertIn(key, record, key)
        self.assertEqual(record["schema_version"], 3)
        self.assertEqual(record["ownership_semantics"], OWNERSHIP_SEMANTICS)
        self.assertEqual(record["ownership_semantics"], "exact_literal_pathset_v1")
        self.assertEqual(record["label"], "refactor")

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
            sorted(decode_owned_paths(self.active())),
            [b"src/strategy.py", b"weird\nname"],
        )

    def test_foreign_staged_count_is_recorded(self):
        for name in ("f1.txt", "f2.txt", "f3.txt"):
            with open(os.path.join(self.repo, name), "w") as handle:
                handle.write("foreign\n")
            support.task_builders.git(
                self.repo, "add", "--", name, env=self.env
            )
        self.start("src/strategy.py")
        self.assertEqual(self.active()["foreign_staged_count_at_start"], 3)

    def test_foreign_staged_count_is_zero_when_nothing_is_staged(self):
        self.start("src/strategy.py")
        self.assertEqual(self.active()["foreign_staged_count_at_start"], 0)

    def test_no_filenames_are_disclosed_by_the_staged_count(self):
        with open(os.path.join(self.repo, "secret-name.txt"), "w") as handle:
            handle.write("foreign\n")
        support.task_builders.git(
            self.repo, "add", "--", "secret-name.txt", env=self.env
        )
        _status, out, _err = self.start("src/strategy.py")
        self.assertNotIn("secret-name", out)
        self.assertNotIn("secret-name", json.dumps(self.active()))


class ExactOwnershipTests(TaskTestCase):
    """v1 owns an exact pathset of regular files."""

    def test_a_tracked_regular_file_is_accepted(self):
        status, _out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_an_untracked_regular_file_is_accepted(self):
        with open(os.path.join(self.repo, "scratch.py"), "w") as handle:
            handle.write("x\n")
        status, _out, _err = run(
            ["task", "start", "--own", "scratch.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_a_path_that_does_not_exist_yet_is_accepted(self):
        status, _out, _err = run(
            ["task", "start", "--own", "src/future.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_a_directory_is_refused(self):
        status, _out, err = run(["task", "start", "--own", "src"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("exists as a directory", err)
        self.assertIsNone(self.active())

    def test_a_symlink_to_a_file_is_refused(self):
        os.symlink("src/strategy.py", os.path.join(self.repo, "linkfile"))
        status, _out, err = run(
            ["task", "start", "--own", "linkfile"], self.repo, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("symbolic link", err)

    def test_a_symlink_to_a_directory_is_refused(self):
        os.symlink("src", os.path.join(self.repo, "linkdir"))
        status, _out, err = run(
            ["task", "start", "--own", "linkdir"], self.repo, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("symbolic link", err)

    def test_a_special_file_is_refused(self):
        os.mkfifo(os.path.join(self.repo, "pipe"))
        status, _out, err = run(["task", "start", "--own", "pipe"], self.repo, self.env)
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("regular file", err)

    def test_a_duplicate_declaration_is_refused(self):
        """Silently agreeing with half of what the user typed is not an answer."""
        status, _out, err = run(
            ["task", "start", "--own", "src/strategy.py", "--own", "./src/strategy.py"],
            self.repo,
            self.env,
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("more than once", err)
        self.assertIsNone(self.active())

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
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        owned = decode_owned_paths(self.active())
        self.assertTrue(scope.owned_by_any(owned, b"src/strategy.py"))
        for other in (b"src", b"src/other.py", b"src/strategy.pyc"):
            self.assertFalse(scope.owned_by_any(owned, other), other)


class UnbornHeadTests(TaskTestCase):
    def setUp(self):
        TaskTestCase.setUp(self)
        self.unborn = os.path.join(self.root, "unborn")
        support.task_builders.init_repo(self.unborn, self.env)

    def test_task_start_is_refused(self):
        """A task records the commit it started from; there is not one."""
        status, _out, err = run(
            ["task", "start", "--own", "src/x.py"], self.unborn, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no commits yet", err)
        self.assertFalse(self.salt_exists())

    def test_doctor_still_works_there(self):
        status, out, _err = run(["doctor"], self.unborn, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("REPOSITORY_UNBORN_HEAD", out)

    def test_status_still_answers_there(self):
        status, out, _err = run(["task"], self.unborn, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)


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
        for command in ("commit",):
            status, out, err = run([command], self.repo, self.env)
            self.assertEqual(status, exits.UNSUPPORTED, command)
            self.assertEqual(out, "", command)
            self.assertIn("unknown command", err, command)


class ExitVocabularyTests(TaskTestCase):
    def test_invalid_scope_is_unsupported(self):
        for path in ("/etc/passwd", "..", ".", ".git/config", "src"):
            status, _out, _err = run(
                ["task", "start", "--own", path], self.repo, self.env
            )
            self.assertEqual(status, exits.UNSUPPORTED, path)

    def test_corrupt_record_is_incomplete_not_unsupported(self):
        """Something is there and AIQE will not guess what it is."""
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(os.path.join(self.state_directory(), "task.json"), "w") as handle:
            handle.write("not a task record")

        status, _out, err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.INCOMPLETE)
        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("task end", err)

    def test_end_discards_an_unreadable_record(self):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(os.path.join(self.state_directory(), "task.json"), "w") as handle:
            handle.write("not a task record")

        status, out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("cannot", out)
        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_unsafe_state_location_is_refused(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        os.makedirs(self.state_root(), exist_ok=True)
        os.symlink(elsewhere, os.path.join(self.state_root(), "task.json"))
        with open(taskstate.salt_path(self.env), "wb") as handle:
            handle.write(b"\x07" * 32)
        os.chmod(taskstate.salt_path(self.env), 0o600)

        directory = self.state_directory()
        os.makedirs(os.path.dirname(directory), exist_ok=True)
        os.symlink(elsewhere, directory)

        status, _out, err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("refusing to write through it", err)

    def test_task_never_exits_one(self):
        """Exit 1 is a FAIL verdict, and a task boundary adjudicates nothing."""
        for argv in (["task"], ["task", "end"], ["task", "start", "--own", "."]):
            status, _out, _err = run(argv, self.repo, self.env)
            self.assertNotEqual(status, exits.FAIL, argv)


class SchemaTransitionTests(TaskTestCase):
    """An older record meant something else, so it is refused, not reread."""

    def write_old_record(self, version):
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        path = os.path.join(self.state_directory(), "task.json")
        with open(path) as handle:
            record = json.load(handle)
        record["schema_version"] = version
        with open(path, "w") as handle:
            json.dump(record, handle)
        return path

    def test_status_fails_closed(self):
        self.write_old_record(2)
        status, _out, err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("schema version 2", err)
        self.assertIn("refused rather than reinterpreted", err)

    def test_no_silent_migration(self):
        path = self.write_old_record(1)
        with open(path) as handle:
            before = handle.read()
        run(["task"], self.repo, self.env)
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        with open(path) as handle:
            self.assertEqual(handle.read(), before)

    def test_end_discards_it_and_a_new_task_can_start(self):
        self.write_old_record(1)
        status, _out, _err = run(["task", "end"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        status, _out, _err = run(
            ["task", "start", "--own", "src/strategy.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(self.active()["schema_version"], 3)


class TerminalSafetyTests(TaskTestCase):
    def test_a_newline_in_a_path_cannot_forge_an_output_row(self):
        forged = "src/a.py\n  Owned pathset   0 exact paths"
        run(["task", "start", "--own", forged], self.repo, self.env)
        _status, out, _err = run(["task"], self.repo, self.env)

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

    def test_a_refusal_message_is_escaped_too(self):
        os.mkdir(os.path.join(self.repo, "weird\nname"))
        _status, _out, err = run(
            ["task", "start", "--own", "weird\nname"], self.repo, self.env
        )
        for line in err.splitlines():
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
        run(["task", "start", "--own", "src/strategy.py"], self.repo, self.env)
        directory = self.state_directory()
        run(["task", "end"], self.repo, self.env)
        with open(os.path.join(directory, ".task.json.tmp.99999"), "w") as handle:
            handle.write('{"schema_version": 3, "task_')

        status, out, _err = run(["task"], self.repo, self.env)
        self.assertEqual(status, exits.OK)
        self.assertIn("No active task", out)

        status, _out, _err = run(
            ["task", "start", "--own", "src/x.py"], self.repo, self.env
        )
        self.assertEqual(status, exits.OK)

    def test_clear_syncs_the_containing_directory(self):
        """The mechanism, not a durability claim.

        `clear_active` unlinks the record and then fsyncs the directory. That
        is necessary for the deletion to survive power loss, and it is what
        this asserts. It is *not* a proof of power-loss durability, which
        needs power loss; the documented classification stays NOT_PROVEN.
        """
        run(["task", "start", "--own", "src/x.py"], self.repo, self.env)
        directory = self.state_directory()

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
            taskstate.clear_active(directory)
        finally:
            os.fsync = real_fsync

        self.assertTrue(synced, "the state directory was not fsynced after unlink")
        self.assertIsNone(self.active())

    def test_lock_is_per_worktree_and_released_on_exit(self):
        run(["task", "start", "--own", "src/x.py"], self.repo, self.env)
        directory = self.state_directory()
        with taskstate.TaskLock(directory):
            with self.assertRaises(taskstate.StateError):
                with taskstate.TaskLock(directory, timeout=0.1):
                    pass
        with taskstate.TaskLock(directory, timeout=0.1):
            pass


if __name__ == "__main__":
    unittest.main()
