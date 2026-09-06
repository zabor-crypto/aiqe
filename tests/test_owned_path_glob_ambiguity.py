"""A glob-shaped `--own` value must never buy a green result.

`aiqe task start --own 'src/strategy/**'` records one literal path, exactly as
documented, and that path does not exist. Every file the caller meant is then
unowned, so a check over the declaration is arithmetically perfect and says
nothing: nought changed owned paths, no contracts, no obligations, exit 0.

That result is indistinguishable from a task that genuinely had nothing to
report, which is what makes it worse than a failure. These tests pin the
refusal that replaces it, and - just as importantly - pin the four
neighbouring behaviours that must not be disturbed by it, because the cheap
way to fix this defect is to start expanding globs, and expanding a glob would
claim ownership the caller never declared.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import support

from aiqe import check, evidence, exits, pathstate, scope
from aiqe import task as task_module
from aiqe.cli import main
from aiqe.textsafe import is_safe

builders = support.check_builders

GLOB_SHAPED = "src/strategy/**"

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


class GlobAmbiguityTestCase(unittest.TestCase):
    """A real repository driven through the real command surface."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-glob-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("check", self.root, ("repo",))
        self.env = self.case.env()
        self.repo = None

    def build(self, edit_owned=True):
        self.repo = builders.build_repository(
            self.case, self.env, CONFIG, SCRIPTS, edit_owned
        )
        return self.repo

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env, prompt=None)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self, *owned):
        arguments = ["task", "start"]
        for path in owned:
            arguments += ["--own", path]
        status, out, err = self.run_cli(arguments)
        self.assertEqual(status, exits.OK, err)
        return out

    def git(self, *args):
        return support.check_builders.git(self.repo, *args, env=self.env)

    def staged_names(self):
        result = self.git("diff", "--cached", "--name-only")
        return sorted(result.stdout.decode("utf-8").split())


class ReproducesTheAuditCase(GlobAmbiguityTestCase):
    """1. The exact false green from the final audit, and its replacement."""

    def test_glob_shaped_declaration_no_longer_exits_zero(self):
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        status, out, err = self.run_cli(["check"])

        # The defect: this returned exits.OK with REVIEWABLE_CANDIDATE while
        # src/strategy/alpha.py sat modified and unowned.
        self.assertNotEqual(status, exits.OK)
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out + err)
        self.assertNotIn(check.REVIEWABLE_CANDIDATE, out)

    def test_the_diagnostic_names_what_escaped_and_what_to_type(self):
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        _status, out, _err = self.run_cli(["check"])

        self.assertIn("src/strategy/**", out)
        self.assertIn("src/strategy/alpha.py", out)
        # The remedy has to be the literal interface, not a way to make the
        # glob work. A message that implied expansion would be teaching the
        # defect.
        self.assertIn("--own", out)
        self.assertIn("literal", out)
        self.assertTrue(all(is_safe(line) for line in out.splitlines()))

    def test_json_reports_the_ambiguity_as_a_machine_readable_result(self):
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check", "--format", "json"])
        document = json.loads(out)

        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(document["result"]["completion"], check.INCOMPLETE)
        self.assertIn(
            pathstate.OWNED_PATH_GLOB_AMBIGUITY, document["result"]["reasons"]
        )
        entries = document["owned_path_glob_ambiguity"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matched_changed_count"], 1)

    def test_no_owned_path_is_silently_expanded(self):
        """The refusal must not quietly adopt the files it names.

        Claiming them would answer the caller's question for them, and the
        declared pathset is the one thing in the product that is supposed to
        be exactly what the caller said.
        """
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        _status, out, _err = self.run_cli(["task"])

        self.assertIn("1 exact path", out)
        self.assertIn("src/strategy/**", out)
        self.assertNotIn("alpha.py", out)


class LiteralBehaviourIsUnchanged(GlobAmbiguityTestCase):
    """2 and 6. The ordinary path, and quant coverage over it."""

    def test_exact_literal_ownership_is_untouched(self):
        self.build(edit_owned=True)
        self.start(builders.OWNED_TEXT)

        status, out, _err = self.run_cli(["check", "--allow", "unit",
                                         "--allow", "causality"])

        self.assertEqual(status, exits.OK, out)
        self.assertIn(check.REVIEWABLE_CANDIDATE, out)
        self.assertIn("1 declared", out)
        self.assertIn("1 changed", out)

    def test_quant_coverage_still_applies_to_a_correctly_owned_file(self):
        """6. The gap the audit compared against still reports as a gap."""
        self.build(edit_owned=True)
        self.start(builders.OWNED_TEXT)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        # `causality` is required and unconsented, so CAUSALITY is uncovered.
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("1 quant", out)
        self.assertIn("CAUSALITY", out)

    def test_a_clean_worktree_still_reports_nothing_changed(self):
        self.build(edit_owned=False)
        self.start(builders.OWNED_TEXT)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        self.assertEqual(status, exits.OK, out)
        self.assertIn("0 changed", out)


class GenuineMetacharacterFilenames(GlobAmbiguityTestCase):
    """4. `[`, `*` and `?` are legal bytes in a filename, and stay legal."""

    def commit_literal(self, name, text="ORIGINAL = 1\n"):
        self.build(edit_owned=False)
        path = os.path.join(self.repo, "src", "strategy", name)
        builders.write(path, text)
        builders.commit_all(self.repo, "add a metacharacter filename", self.env)
        return path

    def test_an_existing_file_named_with_brackets_is_owned_normally(self):
        path = self.commit_literal("table[1].py")
        self.start("src/strategy/table[1].py")
        builders.write(path, "ORIGINAL = 2\n")

        status, out, _err = self.run_cli(["check", "--allow", "unit",
                                          "--allow", "causality"])

        self.assertEqual(status, exits.OK, out)
        self.assertIn("1 changed", out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)

    def test_an_existing_file_named_with_a_star_is_owned_normally(self):
        path = self.commit_literal("star*.py")
        self.start("src/strategy/star*.py")
        builders.write(path, "ORIGINAL = 2\n")

        status, out, _err = self.run_cli(["check", "--allow", "unit",
                                          "--allow", "causality"])

        self.assertEqual(status, exits.OK, out)
        self.assertIn("1 changed", out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)

    def test_declaring_a_metacharacter_path_before_creating_it_still_works(self):
        """Absent and glob-shaped is not by itself an error.

        Nothing it could have matched has changed, so there is no green result
        being bought and nothing to refuse. Refusing here would break the
        ordinary declare-before-create case for a filename the caller is
        entitled to use.
        """
        self.build(edit_owned=False)
        self.start("src/strategy/pending[1].py")

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        self.assertEqual(status, exits.OK, out)
        self.assertIn("0 changed", out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)

    def test_task_start_warns_about_a_glob_shaped_absent_declaration(self):
        """The early warning. Useful, and deliberately not the control."""
        self.build(edit_owned=True)

        out = self.start(GLOB_SHAPED)

        self.assertIn("name no file yet", out)
        self.assertIn("src/strategy/**", out)


class InvocationDirectoryDoesNotChangeTheAnswer(GlobAmbiguityTestCase):
    """The candidate sweep is repository-wide, wherever it is invoked from.

    The Git runner is rooted at the invocation directory, so the two commands
    that enumerate candidates have to be told to answer for the whole
    repository. Left to their defaults, one of them reports paths relative to
    a subdirectory and only looks inside it - which is a false green again,
    reached by running the same command from one directory down.
    """

    def run_cli_in(self, subdirectory, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            argv, stdout, stderr, os.path.join(self.repo, subdirectory),
            self.env, prompt=None,
        )
        return status, stdout.getvalue(), stderr.getvalue()

    def test_a_modified_tracked_file_is_found_from_a_subdirectory(self):
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        status, out, err = self.run_cli_in("docs", ["check"])

        self.assertEqual(status, exits.INCOMPLETE, out + err)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out + err)
        self.assertIn("src/strategy/alpha.py", out)

    def test_a_staged_new_file_is_found_from_every_invocation_depth(self):
        """Root, one level down, and two levels down must agree.

        `ls-files` reports paths relative to the invocation directory and
        looks only inside it unless told otherwise, so the depth the command
        was typed at is exactly what a regression here would depend on.
        """
        self.build(edit_owned=False)
        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )
        self.git("add", "src/strategy/beta.py")
        self.start(GLOB_SHAPED)

        for subdirectory in (".", "docs", os.path.join("src", "strategy")):
            status, out, err = self.run_cli_in(subdirectory, ["check"])
            self.assertEqual(status, exits.INCOMPLETE, subdirectory + out + err)
            self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out, subdirectory)
            self.assertIn("src/strategy/beta.py", out, subdirectory)

    def test_an_untracked_file_elsewhere_is_found_from_a_subdirectory(self):
        self.build(edit_owned=False)
        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )
        self.start(GLOB_SHAPED)

        status, out, err = self.run_cli_in("docs", ["check"])

        self.assertEqual(status, exits.INCOMPLETE, out + err)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out + err)
        # Root-relative, not relative to the directory the command ran in.
        self.assertIn("src/strategy/beta.py", out)


class UntrackedFilesAreCandidates(GlobAmbiguityTestCase):
    """A file that does not exist in the baseline is still a changed path."""

    def test_a_new_untracked_file_the_glob_would_match_is_refused(self):
        self.build(edit_owned=False)
        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check"])

        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)
        self.assertIn("src/strategy/beta.py", out)

    def test_an_ignored_file_is_not_a_candidate(self):
        """`--exclude-standard`: an ignored file is not part of the change."""
        self.build(edit_owned=False)
        builders.write(os.path.join(self.repo, ".gitignore"), "src/strategy/*.log\n")
        builders.commit_all(self.repo, "ignore logs", self.env)
        builders.write(
            os.path.join(self.repo, "src", "strategy", "noise.log"), "noise\n"
        )
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        self.assertEqual(status, exits.OK, out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)


class TheIndexIsACandidateSource(GlobAmbiguityTestCase):
    """A staged-new file is in neither the baseline tree nor `--others`.

    It is absent from the baseline commit, and `git add` stops it being
    *other*, so a candidate pathset built from those two sources alone omits
    precisely the file a caller has just staged - and the sweep reports
    nothing while the change sits in the index. Staging is the most ordinary
    thing to do next after creating a file, which is what made this the worst
    remaining shape of the same false green.
    """

    def stage_new(self, name="beta.py", text="NEW = 1\n"):
        path = os.path.join(self.repo, "src", "strategy", name)
        builders.write(path, text)
        self.git("add", "src/strategy/" + name)
        return path

    def test_a_staged_new_matching_path_is_refused(self):
        self.build(edit_owned=False)
        self.stage_new()
        self.start(GLOB_SHAPED)

        status, out, err = self.run_cli(["check"])

        self.assertEqual(status, exits.INCOMPLETE, out + err)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)
        self.assertIn("src/strategy/beta.py", out)

    def test_a_staged_new_path_stays_staged(self):
        """The refusal reads the index. It does not write to it."""
        self.build(edit_owned=False)
        self.stage_new()
        self.start(GLOB_SHAPED)

        before = self.staged_names()
        self.run_cli(["check"])

        self.assertEqual(self.staged_names(), before)
        self.assertEqual(before, ["src/strategy/beta.py"])

    def test_an_exact_literal_staged_new_path_is_owned_normally(self):
        """Declared literally, the same staged file is simply owned."""
        self.build(edit_owned=False)
        self.stage_new()
        self.start("src/strategy/beta.py")

        status, out, _err = self.run_cli(
            ["check", "--allow", "unit", "--allow", "causality"]
        )

        self.assertEqual(status, exits.OK, out)
        self.assertIn("1 changed", out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)

    def test_an_unrelated_staged_foreign_path_does_not_trigger_it(self):
        """Foreign staged state is observed, never adopted."""
        self.build(edit_owned=False)
        builders.write(os.path.join(self.repo, "docs", "foreign.md"), "x\n")
        self.git("add", "docs/foreign.md")
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        self.assertEqual(status, exits.OK, out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)

    def test_an_unrelated_untracked_foreign_path_does_not_trigger_it(self):
        self.build(edit_owned=False)
        builders.write(os.path.join(self.repo, "docs", "foreign.md"), "x\n")
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])

        self.assertEqual(status, exits.OK, out)
        self.assertNotIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out)


class ForeignStateIsNotTouched(GlobAmbiguityTestCase):
    """3. The refusal reads. It does not stage, unstage, restore or clean."""

    def staged(self):
        result = self.git("diff", "--cached", "--name-only")
        return sorted(result.stdout.decode("utf-8").split())

    def contents(self, *parts):
        with open(os.path.join(self.repo, *parts)) as handle:
            return handle.read()

    def test_foreign_staged_and_dirty_state_survives_the_refusal(self):
        self.build(edit_owned=True)
        builders.write(os.path.join(self.repo, "docs", "notes.md"), "edited\n")
        self.git("add", "docs/notes.md")
        builders.write(os.path.join(self.repo, "tests", "test_alpha.py"),
                       "def test():\n    assert True\n")

        before_staged = self.staged()
        before_dirty = self.contents("tests", "test_alpha.py")
        self.assertEqual(before_staged, ["docs/notes.md"])

        self.start(GLOB_SHAPED)
        status, _out, _err = self.run_cli(["check"])
        self.assertEqual(status, exits.INCOMPLETE)

        self.assertEqual(self.staged(), before_staged)
        self.assertEqual(self.contents("tests", "test_alpha.py"), before_dirty)
        # The file the glob would have matched is still modified and still
        # unowned. The refusal reported it; it did not resolve it.
        self.assertEqual(
            self.contents("src", "strategy", "alpha.py"),
            "SIGNAL = 1\nADJUSTED = 2\n",
        )


class StaleEvidenceCannotSurviveTheRefusal(GlobAmbiguityTestCase):
    """5. Staleness and bounded-commit semantics, at the seam this opens.

    The ordering that matters: a green check under a glob-shaped declaration,
    *then* a change to a file that declaration would have matched. The owned
    binding does not move - the declared path is still absent - so nothing in
    the existing staleness model notices, and the recorded green would answer
    a later `aiqe receipt` as though it were current.
    """

    def test_a_previous_green_record_is_discarded_not_left_current(self):
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)

        status, out, _err = self.run_cli(["check", "--allow", "unit"])
        self.assertEqual(status, exits.OK, out)
        self.assertIn(check.REVIEWABLE_CANDIDATE, out)

        # Now change exactly the file the declaration would have covered.
        builders.write(
            os.path.join(self.repo, "src", "strategy", "alpha.py"),
            "SIGNAL = 1\nADJUSTED = 2\n",
        )

        status, out, err = self.run_cli(["check", "--allow", "unit"])
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, out + err)

        # The receipt must not be able to answer from the discarded record.
        status, out, err = self.run_cli(["receipt"])
        self.assertNotEqual(status, exits.OK)
        self.assertNotIn("REVIEWABLE_CANDIDATE", out)

    def test_a_bounded_commit_is_refused_after_the_refusal(self):
        self.build(edit_owned=True)
        self.start(GLOB_SHAPED)

        status, _out, _err = self.run_cli(["check"])
        self.assertEqual(status, exits.INCOMPLETE)

        status, out, err = self.run_cli(["commit", "-m", "work"])
        self.assertNotEqual(status, exits.OK, out + err)


class ReceiptFreshnessUnderAmbiguity(GlobAmbiguityTestCase):
    """`aiqe receipt` must not answer from evidence the repository outran.

    The ordering that matters, and the reason the ordinary staleness model
    cannot see it: a green check is recorded while the glob-shaped declaration
    names nothing, and *then* a path it would have selected appears. The owned
    binding is a digest over the declared paths, and the declared path is
    still absent - so nothing in the recorded authority moves, and the receipt
    keeps reporting `CURRENT` until somebody happens to run `aiqe check`
    again. Receipt therefore asks the same question check asks, on the same
    inputs, and reads only.
    """

    def receipt(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            ["receipt", "--format", "json"], stdout, stderr,
            self.repo, self.env, prompt=None,
        )
        text = stdout.getvalue()
        return status, (json.loads(text) if text.strip() else None), stderr.getvalue()

    def green_check(self):
        status, out, err = self.run_cli(["check", "--allow", "unit"])
        self.assertEqual(status, exits.OK, out + err)

    def evidence_file(self):
        directory = task_module._existing_state_directory(
            task_module.discover(self.repo, self.env)[0], self.env
        )
        return os.path.join(directory, evidence.CHECK_FILE_NAME)

    # --- A and B: a matching path appears after a green record -------------

    def test_a_matching_untracked_path_makes_the_receipt_not_current(self):
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()

        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )

        status, document, _err = self.receipt()

        self.assertNotEqual(document["evidence"], "CURRENT")
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, document["reasons"])
        self.assertNotEqual(status, exits.OK)

    def test_a_matching_staged_new_path_makes_the_receipt_not_current(self):
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()

        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )
        self.git("add", "src/strategy/beta.py")

        status, document, _err = self.receipt()

        self.assertNotEqual(document["evidence"], "CURRENT")
        self.assertIn(pathstate.OWNED_PATH_GLOB_AMBIGUITY, document["reasons"])
        self.assertNotEqual(status, exits.OK)

    # --- C and D: the frozen foreign-state contract is unchanged -----------

    def test_an_unrelated_untracked_path_leaves_the_receipt_current(self):
        """Foreign state is observed. It has never made a receipt stale."""
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()

        builders.write(os.path.join(self.repo, "docs", "foreign.md"), "x\n")

        _status, document, _err = self.receipt()

        self.assertEqual(document["evidence"], "CURRENT")
        self.assertNotIn(
            pathstate.OWNED_PATH_GLOB_AMBIGUITY, document["reasons"]
        )

    def test_an_unrelated_staged_path_leaves_the_receipt_current(self):
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()

        builders.write(os.path.join(self.repo, "docs", "foreign.md"), "x\n")
        self.git("add", "docs/foreign.md")

        _status, document, _err = self.receipt()

        self.assertEqual(document["evidence"], "CURRENT")
        self.assertNotIn(
            pathstate.OWNED_PATH_GLOB_AMBIGUITY, document["reasons"]
        )

    # --- E and F: the staleness paths that already existed -----------------

    def test_stale_owned_content_still_reports_as_before(self):
        self.build(edit_owned=False)
        self.start(builders.OWNED_TEXT)
        status, out, err = self.run_cli(
            ["check", "--allow", "unit", "--allow", "causality"]
        )
        self.assertEqual(status, exits.OK, out + err)

        builders.write(
            os.path.join(self.repo, "src", "strategy", "alpha.py"),
            "SIGNAL = 1\nADJUSTED = 2\n",
        )

        _status, document, _err = self.receipt()

        self.assertEqual(document["evidence"], "STALE")
        self.assertIn(evidence.STALE_OWNED_CONTENT, document["reasons"])

    def test_a_moved_head_still_reports_as_before(self):
        self.build(edit_owned=False)
        self.start(builders.OWNED_TEXT)
        self.green_check()

        builders.write(os.path.join(self.repo, "docs", "later.md"), "x\n")
        builders.commit_all(self.repo, "a later commit", self.env)

        _status, document, _err = self.receipt()

        self.assertEqual(document["evidence"], "STALE")
        self.assertIn(evidence.STALE_HEAD, document["reasons"])

    # --- Receipt remains read-only ----------------------------------------

    def test_the_receipt_does_not_remove_or_rewrite_the_evidence(self):
        """`check` discards the record it invalidates. `receipt` never does.

        Receipt is a reporting surface, and a reporting surface that deletes
        the thing it reports on cannot be run twice.
        """
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()

        path = self.evidence_file()
        with open(path, "rb") as handle:
            before = handle.read()

        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )

        first_status, first, _err = self.receipt()
        second_status, second, _err = self.receipt()

        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(first_status, second_status)
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual(first["reasons"], second["reasons"])

    def test_the_receipt_owns_nothing_new(self):
        """No path is adopted, and no validator runs, to answer this."""
        self.build(edit_owned=False)
        self.start(GLOB_SHAPED)
        self.green_check()
        builders.write(
            os.path.join(self.repo, "src", "strategy", "beta.py"), "NEW = 1\n"
        )

        _status, document, _err = self.receipt()

        self.assertEqual(document["owned_declared_count"], 1)
        self.assertEqual(document["owned_changed_count"], 0)
        _status, out, _err = self.run_cli(["task"])
        self.assertIn("1 exact path", out)
        self.assertNotIn("beta.py", out)


class ShapeDetection(unittest.TestCase):
    """The predicate itself, on bytes, with no repository in sight."""

    def test_metacharacters_are_detected(self):
        for raw in (b"a*", b"a?", b"a[b]", b"src/**", b"[!x]"):
            self.assertTrue(scope.is_glob_shaped(raw), raw)

    def test_ordinary_paths_are_not(self):
        for raw in (b"a", b"src/strategy/model.py", b"a-b_c.1", b"a{b}", b"a\\b"):
            self.assertFalse(scope.is_glob_shaped(raw), raw)

    def test_ownership_is_still_exact_literal_equality(self):
        """Shape detection must not have leaked into ownership itself."""
        self.assertTrue(scope.owns(b"src/strategy/**", b"src/strategy/**"))
        self.assertFalse(scope.owns(b"src/strategy/**", b"src/strategy/a.py"))
        self.assertFalse(scope.owns(b"src/**", b"src/a/b.py"))


if __name__ == "__main__":
    unittest.main()
