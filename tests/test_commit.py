"""`aiqe commit`: preconditions, expected check-in state, proof and evidence.

These run in-process against a real repository. The benchmark family drives
the same behaviour through the installed entry point as subprocesses; this is
where the boundaries are pinned down one at a time, cheaply enough to be
specific about which one broke.
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from . import support

from aiqe import checkin, commit, commitevidence, exits, gitwrite, taskstate
from aiqe.cli import main
from aiqe.textsafe import is_safe

builders = support.commit_builders


def git(root, *args, **kwargs):
    return support.commit_builders.git(root, *args, **kwargs)


class CommitTestCase(unittest.TestCase):
    """A real repository, a real task, a real check, and the real surface."""

    def setUp(self):
        # Resolved, because on macOS a temporary directory is reached through
        # a symlink and Git reports the resolved worktree root. Left
        # unresolved, a relative `--own` from a subdirectory would silently
        # resolve against the worktree root and the subdirectory case would
        # prove nothing.
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="aiqe-commit-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case(
            "commit", self.root, ("repo", "linked")
        )
        self.env = self.case.env()
        self.repo = None

    def build(self, **kwargs):
        self.repo = builders.build_repository(self.case, self.env, **kwargs)
        return self.repo

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self, *owned):
        arguments = ["task", "start"]
        for path in owned or (builders.OWNED_TEXT,):
            arguments += ["--own", path]
        status, _out, err = self.run_cli(arguments)
        self.assertEqual(status, exits.OK, err)

    def check(self):
        status, out, err = self.run_cli(["check", "--allow", "unit"])
        return status, out, err

    def commit(self, message="bounded completion"):
        return self.run_cli(["commit", "-m", message])

    def workflow(self, *owned, **kwargs):
        self.start(*owned)
        status, out, err = self.check()
        self.assertEqual(status, exits.OK, out + err)
        return self.commit(kwargs.get("message", "bounded completion"))

    def head(self):
        return builders.head(self.repo, self.env)

    def state_directory(self):
        return builders.state_directory(self.repo, self.env)

    def commit_evidence(self):
        return builders.commit_evidence(self.repo, self.env)

    def tree(self, commit_sha, path):
        return builders.tree_state(self.repo, commit_sha, [path], self.env)


class PreconditionTests(CommitTestCase):
    def test_a_commit_needs_an_active_task(self):
        self.build(owned_setup=builders.edit_owned)
        status, _out, err = self.commit()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no active task", err)

    def test_a_commit_needs_current_check_evidence(self):
        """The commit consumes a check. It does not run one."""
        self.build(owned_setup=builders.edit_owned)
        self.start()
        status, out, _err = self.commit()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(commit.CHECK_EVIDENCE_ABSENT, out)
        self.assertIsNone(self.commit_evidence())

    def test_a_failing_check_is_not_a_completion_state(self):
        self.build(validator_exit=1, owned_setup=builders.edit_owned)
        self.start()
        self.check()
        status, out, _err = self.commit()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(commit.CHECK_NOT_REVIEWABLE_CANDIDATE, out)

    def test_a_moved_baseline_refuses_before_anything_is_written(self):
        self.build(owned_setup=builders.edit_owned)
        self.start()
        self.check()
        builders.put(self.repo, b"tests/later.py", b"LATER = 1\n")
        git(self.repo, "add", "--all", env=self.env)
        git(self.repo, "commit", "--quiet", "--message", "later", env=self.env)

        before = self.head()
        status, out, _err = self.commit()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(commit.TASK_BASELINE_MOVED, out)
        self.assertEqual(self.head(), before)

    def test_one_task_gets_one_completion_commit(self):
        self.build(owned_setup=builders.edit_owned)
        status, _out, _err = self.workflow()
        self.assertEqual(status, exits.OK)
        after = self.head()

        status, _out, err = self.commit("second attempt")
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("already has an AIQE completion commit", err)
        self.assertEqual(self.head(), after)

    def test_an_empty_expected_pathset_creates_no_commit(self):
        """No `--allow-empty`. A commit that records nothing is not one."""
        self.build()
        before = self.head()
        status, out, _err = self.workflow()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(commit.NO_OWNED_CHANGES_TO_COMMIT, out)
        self.assertEqual(self.head(), before)


class BoundedPathsetTests(CommitTestCase):
    def test_the_commit_contains_exactly_the_owned_changed_pathset(self):
        self.build(owned_setup=builders._setup_foreign_modification)
        before = self.head()
        status, _out, _err = self.workflow()
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            builders.changed_paths(self.repo, before, self.head(), self.env),
            [builders.OWNED],
        )

    def test_foreign_staged_work_survives_the_commit_unchanged(self):
        self.build(owned_setup=builders._setup_foreign_modification)
        before = self.head()
        staged = builders.staged_delta(self.repo, before, self.env)
        self.workflow()
        after = builders.staged_delta(self.repo, before, self.env)
        foreign = [record for record in after if "foreign" in record]
        self.assertEqual(foreign, [record for record in staged if "foreign" in record])

    def test_an_owned_name_that_is_pathspec_syntax_commits_itself_alone(self):
        self.build(
            committed_files=builders.BASELINE_LITERAL,
            owned_setup=builders._setup_literal_names,
        )
        before = self.head()
        status, _out, _err = self.workflow(
            *[name.decode("utf-8", "surrogateescape")
              for name in builders.LITERAL_NAMES]
        )
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            sorted(builders.changed_paths(self.repo, before, self.head(), self.env)),
            sorted(builders.LITERAL_NAMES),
        )

    def test_a_deletion_is_committed_as_a_deletion(self):
        self.build(
            committed_files=builders.BASELINE_DELETION,
            owned_setup=builders._setup_deletion,
        )
        status, _out, _err = self.workflow("src/gone.py")
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            self.tree(self.head(), b"src/gone.py"), {"src/gone.py": None}
        )

    def test_a_new_untracked_path_is_committed_through_intent_to_add(self):
        self.build(owned_setup=builders._setup_new_file)
        status, _out, _err = self.workflow("src/created.py")
        self.assertEqual(status, exits.OK)
        self.assertIsNotNone(
            self.tree(self.head(), b"src/created.py")["src/created.py"]
        )


class WorkingDirectoryTests(CommitTestCase):
    def test_a_commit_driven_from_a_subdirectory_commits_the_right_path(self):
        """Owned paths are repository-relative; a pathspec is not.

        Git interprets a pathspec against the process's working directory, so
        a commit run from `src/strategy/` with the owned path
        `src/strategy/alpha.py` would look for `src/strategy/src/strategy/...`.
        Every path this command hands to Git is root-relative, so the process
        is rooted at the worktree rather than wherever the user is standing.
        """
        self.build(owned_setup=builders.edit_owned)
        subdirectory = os.path.join(self.repo, "src", "strategy")

        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            ["task", "start", "--own", "alpha.py"],
            stdout, stderr, subdirectory, self.env,
        )
        self.assertEqual(status, exits.OK, stderr.getvalue())

        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            ["check", "--allow", "unit"], stdout, stderr, subdirectory, self.env
        )
        self.assertEqual(status, exits.OK, stdout.getvalue())

        before = self.head()
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            ["commit", "-m", "from a subdirectory"],
            stdout, stderr, subdirectory, self.env,
        )
        self.assertEqual(status, exits.OK, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(
            builders.changed_paths(self.repo, before, self.head(), self.env),
            [builders.OWNED],
        )


class CheckedInStateTests(CommitTestCase):
    def test_a_normalised_file_is_bound_to_its_transformed_blob(self):
        """The committed blob is not the worktree bytes, and is still bound.

        Under `* text eol=lf` the check-in transformation is exactly what Git
        would do. Comparing the raw worktree bytes against the stored blob
        would report a mismatch on a correct commit, which is the worst kind
        of wrong answer: a false alarm from the mechanism whose job is to be
        believed.
        """
        self.build(
            committed_files=builders.BASELINE_CRLF,
            owned_setup=builders._setup_crlf,
        )
        status, out, _err = self.workflow()
        self.assertEqual(status, exits.OK)
        self.assertIn("Checked content BOUND", out)

        worktree = builders.worktree_bytes(self.repo, builders.OWNED)
        stored = builders.blob_bytes(self.repo, self.head(), builders.OWNED, self.env)
        self.assertIn(b"\r\n", worktree)
        self.assertNotIn(b"\r\n", stored)
        self.assertEqual(stored, worktree.replace(b"\r\n", b"\n"))

    def test_an_executable_owned_file_keeps_mode_100755(self):
        self.build(
            committed_files=builders.BASELINE_EXECUTABLE,
            owned_setup=builders._setup_executable,
        )
        status, _out, _err = self.workflow("src/tool.sh")
        self.assertEqual(status, exits.OK)
        self.assertTrue(
            self.tree(self.head(), b"src/tool.sh")["src/tool.sh"].startswith("100755")
        )

    def test_a_mode_change_alone_is_a_change_and_is_committed(self):
        self.build(
            committed_files=builders.BASELINE_MODE_CHANGE,
            owned_setup=builders._setup_mode_change,
        )
        before = self.head()
        status, _out, _err = self.workflow("src/plain.sh")
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            builders.changed_paths(self.repo, before, self.head(), self.env),
            [b"src/plain.sh"],
        )
        self.assertTrue(
            self.tree(self.head(), b"src/plain.sh")["src/plain.sh"].startswith("100755")
        )

    def test_core_filemode_false_keeps_the_recorded_mode(self):
        """Where Git ignores the execute bit, so does the expectation."""
        self.build(
            committed_files=builders.BASELINE_MODE_CHANGE,
            extra_git_config=(("core.fileMode", "false"),),
        )
        os.chmod(os.path.join(self.repo, "src", "plain.sh"), 0o755)
        builders.put(self.repo, b"src/plain.sh", b"#!/bin/sh\necho changed\n", 0o755)
        status, _out, _err = self.workflow("src/plain.sh")
        self.assertEqual(status, exits.OK)
        self.assertTrue(
            self.tree(self.head(), b"src/plain.sh")["src/plain.sh"].startswith("100644")
        )


class StalenessTests(CommitTestCase):
    def test_an_edit_after_the_check_refuses_before_any_index_mutation(self):
        self.build(owned_setup=builders.edit_owned)
        self.start()
        self.check()
        before = self.head()
        index_before = builders.index_paths(self.repo, self.env)

        builders.put(self.repo, builders.OWNED, b"SIGNAL = 1\nUNCHECKED = 9\n")
        status, out, _err = self.commit()

        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("STALE_OWNED_CONTENT", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(builders.index_paths(self.repo, self.env), index_before)
        self.assertIsNone(self.commit_evidence())

    def test_a_configuration_edit_after_the_check_refuses(self):
        self.build(owned_setup=builders.edit_owned)
        self.start()
        self.check()
        with open(os.path.join(self.repo, "aiqe.toml"), "a") as handle:
            handle.write("\n# changed after the check\n")
        status, out, _err = self.commit()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("STALE_CONFIG", out)


class IntentToAddTests(CommitTestCase):
    def test_a_failed_staging_sequence_is_scope_rolled_back(self):
        """One new path succeeds, the next cannot, and the index is restored.

        The second path is ignored by `.gitignore`, so `git add -N` refuses
        it - a real failure rather than an injected one. What matters is what
        is left behind: exactly nothing.
        """
        self.build(
            committed_files=((b".gitignore", b"src/ignored.py\n", 0o644),),
        )
        builders.put(self.repo, b"src/created.py", b"CREATED = 1\n")
        builders.put(self.repo, b"src/ignored.py", b"IGNORED = 1\n")

        index_before = builders.index_paths(self.repo, self.env)
        status, out, _err = self.workflow("src/created.py", "src/ignored.py")

        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(commit.ITA_FAILED, out)
        self.assertEqual(builders.index_paths(self.repo, self.env), index_before)
        self.assertNotIn("src/created.py", builders.index_paths(self.repo, self.env))
        self.assertIsNone(self.commit_evidence())


class EvidenceTests(CommitTestCase):
    def test_the_record_holds_the_proof_and_not_the_message(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow(message="a message nobody should have to store")
        record = self.commit_evidence()

        self.assertEqual(
            record["schema_version"], commitevidence.COMMIT_EVIDENCE_SCHEMA_VERSION
        )
        self.assertEqual(record["parent_sha"], record["result"] and record["parent_sha"])
        self.assertEqual(record["commit_sha"], self.head())
        self.assertFalse(record["push_performed_by_aiqe"])
        self.assertEqual(
            record["expected_changed_paths_b64"], record["actual_changed_paths_b64"]
        )
        self.assertNotIn("a message nobody should have to store", json.dumps(record))

    def test_ending_a_task_discards_the_commit_evidence(self):
        """A new task cannot inherit a previous task's completion commit."""
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        self.assertIsNotNone(self.commit_evidence())

        status, _out, err = self.run_cli(["task", "end"])
        self.assertEqual(status, exits.OK, err)
        self.assertIsNone(self.commit_evidence())
        self.assertIsNone(
            commitevidence.read(self.state_directory())
        )


class PushTests(CommitTestCase):
    def test_no_reachable_git_subcommand_contacts_a_remote(self):
        self.assertEqual(
            gitwrite.ALLOWED_SUBCOMMANDS
            & {"push", "fetch", "pull", "remote", "ls-remote", "clone"},
            set(),
        )

    def test_a_completion_commit_invokes_only_allowlisted_subcommands(self):
        """Recorded, not asserted in prose: the real invocation list."""
        self.build(owned_setup=builders.edit_owned)
        self.start()
        self.check()

        recorded = []
        original = gitwrite.CommitGitRunner.run

        def record(self_runner, *args, **kwargs):
            recorded.append(args[0])
            return original(self_runner, *args, **kwargs)

        gitwrite.CommitGitRunner.run = record
        try:
            status, _out, _err = self.commit()
        finally:
            gitwrite.CommitGitRunner.run = original

        self.assertEqual(status, exits.OK)
        self.assertTrue(recorded)
        for subcommand in recorded:
            self.assertIn(subcommand, gitwrite.ALLOWED_SUBCOMMANDS)

    def test_every_invocation_carries_literal_pathspec_semantics(self):
        runner = gitwrite.CommitGitRunner(self.root)
        runner.run("rev-parse", "--git-dir")
        self.assertIn("--literal-pathspecs", runner.invocations[0])


class AdjudicationTests(unittest.TestCase):
    """The post-commit verdict table, exercised directly.

    A commit AIQE constructs correctly cannot produce `NOT_REVIEWABLE`, so no
    fixture can produce one either - which is exactly why the adjudication is
    tested here rather than left to a scenario that will never fire. A defect
    AIQE would report is a defect AIQE must be able to report.
    """

    def proof(self, **overrides):
        base = {
            "parents": ("parent",),
            "parent_ok": True,
            "actual_changed": (b"a",),
            "expected_changed": (b"a",),
            "pathset_ok": True,
            "unexpected_paths": (),
            "missing_paths": (),
            "committed": {},
            "content_ok": True,
            "content_mismatch": (),
            "foreign_post": {},
            "foreign_preserved": True,
        }
        base.update(overrides)
        return base

    def test_everything_proved_is_reviewable(self):
        state = commit._adjudicate(self.proof())
        self.assertEqual(state["verdict"], commit.REVIEWABLE)
        self.assertEqual(state["exit_code"], exits.OK)
        self.assertEqual(state["owned_scope"], commit.VERIFIED)
        self.assertEqual(state["foreign_staged"], commit.EXCLUDED)
        self.assertEqual(state["checked_content"], commit.BOUND)

    def test_foreign_drift_alone_is_incomplete_not_a_failure(self):
        """The commit is right and the surrounding claim cannot be made."""
        state = commit._adjudicate(self.proof(foreign_preserved=False))
        self.assertEqual(state["verdict"], commit.INCOMPLETE)
        self.assertEqual(state["exit_code"], exits.INCOMPLETE)
        self.assertEqual(state["owned_scope"], commit.VERIFIED)
        self.assertEqual(state["checked_content"], commit.BOUND)
        self.assertEqual(state["foreign_staged"], commit.UNKNOWN)
        self.assertEqual(state["reasons"], (commit.FOREIGN_STAGED_UNKNOWN,))

    def test_a_wrong_parent_is_not_reviewable(self):
        state = commit._adjudicate(self.proof(parent_ok=False))
        self.assertEqual(state["verdict"], commit.NOT_REVIEWABLE)
        self.assertEqual(state["exit_code"], exits.FAIL)
        self.assertEqual(state["owned_scope"], commit.UNVERIFIED)
        self.assertIn(commit.POST_COMMIT_PARENT_INVALID, state["reasons"])

    def test_a_wider_pathset_is_not_reviewable(self):
        state = commit._adjudicate(
            self.proof(pathset_ok=False, unexpected_paths=(b"foreign",))
        )
        self.assertEqual(state["verdict"], commit.NOT_REVIEWABLE)
        self.assertEqual(state["owned_scope"], commit.UNVERIFIED)
        self.assertIn(commit.POST_COMMIT_PATHSET_MISMATCH, state["reasons"])

    def test_unbound_content_is_not_reviewable(self):
        state = commit._adjudicate(
            self.proof(content_ok=False, content_mismatch=(b"a",))
        )
        self.assertEqual(state["verdict"], commit.NOT_REVIEWABLE)
        self.assertEqual(state["checked_content"], commit.NOT_BOUND)
        self.assertIn(commit.CHECKED_CONTENT_NOT_BOUND, state["reasons"])

    def test_a_proved_defect_outranks_an_unknown(self):
        """Both true at once, and the harder answer is the one reported."""
        state = commit._adjudicate(
            self.proof(content_ok=False, foreign_preserved=False)
        )
        self.assertEqual(state["verdict"], commit.NOT_REVIEWABLE)
        self.assertEqual(state["exit_code"], exits.FAIL)
        self.assertNotIn(commit.FOREIGN_STAGED_UNKNOWN, state["reasons"])

    def test_no_verdict_outside_the_frozen_vocabulary(self):
        for proof in (
            self.proof(),
            self.proof(foreign_preserved=False),
            self.proof(parent_ok=False),
            self.proof(pathset_ok=False),
            self.proof(content_ok=False),
        ):
            state = commit._adjudicate(proof)
            self.assertIn(
                state["verdict"],
                (commit.REVIEWABLE, commit.INCOMPLETE, commit.NOT_REVIEWABLE),
            )
            self.assertIn(state["exit_code"], (exits.OK, exits.FAIL,
                                               exits.INCOMPLETE))


class TerminalSafetyTests(CommitTestCase):
    def test_a_control_character_in_an_owned_name_never_reaches_the_terminal(self):
        name = b"src/nl\nname.py"
        self.build(
            committed_files=((name, b"BASE = 1\n", 0o644),),
        )
        builders.put(self.repo, name, b"CHANGED = 1\n")
        status, out, err = self.workflow(name.decode("utf-8", "surrogateescape"))
        self.assertEqual(status, exits.OK)
        for line in (out + err).splitlines():
            self.assertTrue(is_safe(line), line)


if __name__ == "__main__":
    unittest.main()
