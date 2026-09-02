"""`aiqe check`: preconditions, consent, adjudication and evidence.

These run in-process against a real repository. The benchmark family drives
the same behaviour through the installed entry point as subprocesses; this is
where the boundaries are pinned down one at a time, cheaply enough to be
specific about which one broke.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import support

from aiqe import check, classify, evidence, exits, taskstate, validators
from aiqe.cli import main
from aiqe.config import load as load_config
from aiqe.textsafe import is_safe

builders = support.check_builders


def lines_are_safe(text):
    """No control character may reach the terminal from user-supplied data.

    Line by line, because a rendered block is many lines and the newlines
    between them are the layout, not the danger.
    """
    return all(is_safe(line) for line in text.splitlines())


def surface(paths, quant, contracts=None):
    return builders.surface(paths, quant, contracts)


def validator(identifier, run, required, timeout, contracts=None):
    return builders.validator(identifier, run, required, timeout, contracts)


QUANT_CONFIG = builders.config(
    [
        surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        builders.NON_QUANT,
        validator("unit", ["./checks/unit.sh"], True, 60),
        validator(
            "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
        ),
    ]
)

BOTH_SCRIPTS = [builders.script("unit"), builders.script("causality")]


class WorkflowTestCase(unittest.TestCase):
    """A real repository, a real task, and the real command surface."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-check-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("check", self.root, ("repo",))
        self.env = self.case.env()
        self.repo = None

    def build(self, config_text=QUANT_CONFIG, scripts=BOTH_SCRIPTS, edit_owned=True):
        self.repo = builders.build_repository(
            self.case, self.env, config_text, scripts, edit_owned
        )
        return self.repo

    def run_cli(self, argv, prompt=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env, prompt=prompt)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self, *owned):
        arguments = ["task", "start"]
        for path in owned or (builders.OWNED_TEXT,):
            arguments += ["--own", path]
        status, _out, err = self.run_cli(arguments)
        self.assertEqual(status, exits.OK, err)

    def check(self, *allow, **kwargs):
        arguments = ["check"]
        for identifier in allow:
            arguments += ["--allow", identifier]
        return self.run_cli(arguments, prompt=kwargs.get("prompt"))

    def check_document(self, *allow):
        arguments = ["check"]
        for identifier in allow:
            arguments += ["--allow", identifier]
        status, out, err = self.run_cli(arguments + ["--format", "json"])
        return status, (json.loads(out) if out else None), err

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

    def stored_evidence(self):
        return evidence.read(self.state_directory())

    def fired(self):
        return self.case.fired()


class PreconditionTests(WorkflowTestCase):
    def test_a_check_needs_an_active_task(self):
        self.build()
        status, _out, err = self.check()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no active task", err)

    def test_a_missing_configuration_is_a_refusal_not_a_default(self):
        self.build(config_text="", scripts=(), edit_owned=True)
        os.unlink(os.path.join(self.repo, "aiqe.toml"))
        self.start()
        status, _out, err = self.check()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("aiqe.toml", err)

    def test_an_invalid_configuration_is_a_refusal(self):
        self.build()
        self.start()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write("schema = 99\n")
        status, _out, err = self.check()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("schema", err)

    def test_an_unknown_allow_id_is_a_refusal(self):
        self.build()
        self.start()
        status, _out, err = self.check("nonexistent")
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("nonexistent", err)

    def test_a_moved_head_is_not_silently_rebaselined(self):
        """The task declared its scope against one commit.

        Moving the baseline underneath it would redefine what "changed" means
        retroactively, and in whichever direction happened to be convenient.
        """
        self.build()
        self.start()
        support.check_builders.write(
            os.path.join(self.repo, "docs", "notes.md"), "revised\n"
        )
        support.check_builders.git(self.repo, "add", "docs/notes.md", env=self.env)
        support.check_builders.git(
            self.repo, "commit", "-q", "-m", "unrelated", env=self.env
        )

        status, out, _err = self.check("unit", "causality")
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(check.TASK_BASELINE_MOVED, out)
        self.assertIsNone(self.stored_evidence())

    def test_an_owned_path_that_became_a_directory_fails_closed(self):
        self.build()
        self.start("src/strategy/future.py")
        os.mkdir(os.path.join(self.repo, "src", "strategy", "future.py"))
        status, _out, err = self.check("unit", "causality")
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("regular files", err)


class ConsentTests(WorkflowTestCase):
    def test_nothing_runs_without_consent(self):
        self.build()
        self.start()
        status, document, _err = self.check_document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(self.fired(), [])
        outcomes = {
            entry["validator_id"]: (entry["outcome"], entry["reason"])
            for entry in document["validators"]
        }
        self.assertEqual(
            outcomes,
            {
                "unit": (validators.UNKNOWN, validators.CONSENT_REQUIRED),
                "causality": (validators.UNKNOWN, validators.CONSENT_REQUIRED),
            },
        )

    def test_allow_authorises_one_run_and_persists_nothing(self):
        self.build()
        self.start()
        status, _out, _err = self.check("unit", "causality")
        self.assertEqual(status, exits.OK)
        self.assertEqual(self.fired(), ["causality", "unit"])

        status, document, _err = self.check_document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(
            {e["validator_id"]: e["outcome"] for e in document["validators"]},
            {"unit": validators.UNKNOWN, "causality": validators.UNKNOWN},
        )

    def test_an_interactive_yes_runs_and_records_consent(self):
        self.build()
        self.start()
        asked = []

        def prompt(text):
            asked.append(text)
            return True

        status, _out, _err = self.check(prompt=prompt)
        self.assertEqual(status, exits.OK)
        self.assertEqual(len(asked), 2)
        self.assertEqual(self.fired(), ["causality", "unit"])

        # Recorded, so a second check does not ask again.
        status, _out, _err = self.check()
        self.assertEqual(status, exits.OK)

    def test_the_disclosure_states_exactly_what_is_being_agreed_to(self):
        self.build()
        self.start()
        asked = []

        def prompt(text):
            asked.append(text)
            return False

        self.check(prompt=prompt)
        text = "\n".join(asked)
        self.assertIn("./checks/unit.sh", text)
        self.assertIn("60 seconds", text)
        self.assertIn("does not sandbox", text)
        self.assertIn("does not restrict its filesystem", text)
        self.assertIn("network", text)
        self.assertTrue(lines_are_safe(text))

    def test_declining_is_unknown_and_runs_nothing(self):
        self.build()
        self.start()
        status, document, _err = self.check_document()
        self.assertEqual(status, exits.INCOMPLETE)

        def prompt(_text):
            return False

        status, _out, _err = self.check(prompt=prompt)
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(self.fired(), [])

    def test_a_machine_readable_check_never_prompts(self):
        """There is nobody at the terminal, and a prompt in a JSON stream is a
        corrupted document and a hung script."""
        self.build()
        self.start()

        def prompt(_text):
            raise AssertionError("a --format json check must not prompt")

        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            ["check", "--format", "json"],
            stdout,
            stderr,
            self.repo,
            self.env,
            prompt=prompt,
        )
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(self.fired(), [])

    def test_consent_is_revoked_by_a_definition_change(self):
        self.build()
        self.start()
        self.check(prompt=lambda _text: True)

        with open(os.path.join(self.repo, "aiqe.toml")) as handle:
            text = handle.read()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write(text.replace("timeout = 60", "timeout = 90"))

        status, document, _err = self.check_document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(
            {e["validator_id"]: e["reason"] for e in document["validators"]},
            {
                "unit": validators.CONSENT_REQUIRED,
                "causality": validators.CONSENT_REQUIRED,
            },
        )

    def test_consent_survives_the_task_it_was_granted_during(self):
        """Consent is a statement about a command, not about a unit of work."""
        self.build()
        self.start()
        self.check(prompt=lambda _text: True)
        self.run_cli(["task", "end"])

        self.start()
        status, _out, _err = self.check()
        self.assertEqual(status, exits.OK)


class AdjudicationTests(WorkflowTestCase):
    def test_a_green_check_is_a_candidate_not_a_verdict(self):
        self.build()
        self.start()
        status, out, _err = self.check("unit", "causality")
        self.assertEqual(status, exits.OK)
        self.assertIn(check.REVIEWABLE_CANDIDATE, out)
        self.assertNotIn("REVIEWABLE\n", out.replace("REVIEWABLE_CANDIDATE", ""))
        self.assertIn("not a", out)

    def test_a_required_failure_exits_one(self):
        self.build(scripts=[builders.script("unit"), builders.script("causality", 1)])
        self.start()
        status, document, _err = self.check_document("unit", "causality")
        self.assertEqual(status, exits.FAIL)
        self.assertEqual(document["result"]["completion"], check.NOT_REVIEWABLE)

    def test_a_failure_outranks_an_incompleteness(self):
        """Both are true at once often enough, and the softer one is the wrong
        round-off in the one direction that matters."""
        config_text = builders.config(
            [
                surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
                builders.NON_QUANT,
                validator("unit", ["./checks/unit.sh"], True, 60),
                validator("missing", ["./checks/absent.sh"], True, 60),
                validator(
                    "causality",
                    ["./checks/causality.sh"],
                    True,
                    60,
                    contracts=["CAUSALITY"],
                ),
            ]
        )
        self.build(
            config_text=config_text,
            scripts=[builders.script("unit"), builders.script("causality", 1)],
        )
        self.start()
        status, document, _err = self.check_document("unit", "causality", "missing")
        self.assertEqual(status, exits.FAIL)
        self.assertIn(
            check.REQUIRED_VALIDATOR_UNAVAILABLE, document["result"]["reasons"]
        )

    def test_an_optional_failure_changes_nothing(self):
        config_text = builders.config(
            [
                surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
                builders.NON_QUANT,
                validator(
                    "causality",
                    ["./checks/causality.sh"],
                    True,
                    60,
                    contracts=["CAUSALITY"],
                ),
                validator("style", ["./checks/style.sh"], False, 60),
            ]
        )
        self.build(
            config_text=config_text,
            scripts=[builders.script("causality"), builders.script("style", 1)],
        )
        self.start()
        status, _out, _err = self.check("causality", "style")
        self.assertEqual(status, exits.OK)

    def test_a_classification_gap_is_incomplete_and_names_the_path(self):
        config_text = builders.config(
            [
                surface(["docs/**", "tests/**", "checks/**", "aiqe.toml"], quant=False),
                validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        self.build(config_text=config_text, scripts=[builders.script("unit")])
        self.start()
        status, out, _err = self.check("unit")
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(classify.CLASSIFICATION_GAP, out)
        # Local output may name a repository-relative path. The receipt is the
        # correlation-minimised surface, and it is a different document.
        self.assertIn(builders.OWNED_TEXT, out)

    def test_a_config_conflict_exits_three_and_writes_no_evidence(self):
        config_text = builders.config(
            [
                surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
                surface(["**/alpha.py"], quant=False),
                builders.NON_QUANT,
                validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        self.build(config_text=config_text, scripts=[builders.script("unit")])
        self.start()
        status, _out, err = self.check("unit")
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("quant = true", err)
        self.assertIsNone(self.stored_evidence())
        self.assertEqual(self.fired(), [])

    def test_an_unchanged_owned_path_carries_no_contract(self):
        self.build(edit_owned=False)
        self.start()
        status, document, _err = self.check_document("unit", "causality")
        self.assertEqual(status, exits.OK)
        self.assertEqual(document["changed_owned_count"], 0)
        self.assertEqual(document["classification"]["applicable_contracts"], [])

    def test_a_contract_validator_is_not_run_when_its_contract_does_not_apply(self):
        self.build(edit_owned=False)
        self.start()
        status, document, _err = self.check_document("unit", "causality")
        self.assertEqual(status, exits.OK)
        self.assertEqual(
            [entry["validator_id"] for entry in document["validators_not_applicable"]],
            ["causality"],
        )
        self.assertEqual(self.fired(), ["unit"])


class EvidenceTests(WorkflowTestCase):
    def test_evidence_is_written_and_bound_to_the_task(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        record = self.stored_evidence()
        self.assertEqual(record["schema_version"], evidence.EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(
            len(record["owned_binding"]), 1
        )
        self.assertEqual(record["result"]["completion"], check.REVIEWABLE_CANDIDATE)

    def test_each_check_replaces_the_previous_record(self):
        """One active record. Not a history: the question a receipt answers is
        whether something is true now."""
        self.build()
        self.start()
        self.check("unit", "causality")
        first = self.stored_evidence()

        with open(os.path.join(self.repo, "checks", "causality.sh"), "w") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(self.repo, "checks", "causality.sh"), 0o755)
        self.check("unit", "causality")
        second = self.stored_evidence()

        self.assertNotEqual(first["result"], second["result"])
        self.assertEqual(
            len(os.listdir(self.state_directory())),
            len({"task.json", "task.lock", "check.json"}),
        )

    def test_ending_a_task_removes_its_evidence_but_not_consent(self):
        self.build()
        self.start()
        self.check(prompt=lambda _text: True)
        self.assertIsNotNone(self.stored_evidence())

        self.run_cli(["task", "end"])
        self.assertIsNone(self.stored_evidence())
        self.assertTrue(
            os.path.exists(
                os.path.join(self.state_directory(), validators.CONSENT_FILE_NAME)
            )
        )

    def test_a_new_task_does_not_inherit_stale_evidence(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        record = self.stored_evidence()

        # Simulate a task that ended without its evidence being cleared.
        self.run_cli(["task", "end"])
        evidence.write(self.state_directory(), record)
        self.start()
        self.assertIsNone(self.stored_evidence())

    def test_evidence_belonging_to_another_task_is_not_read(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        record = self.stored_evidence()
        self.assertIsNone(
            evidence.read(self.state_directory(), task_id="not-this-task")
        )
        self.assertIsNotNone(
            evidence.read(self.state_directory(), task_id=record["task_id"])
        )


class ValidatorInducedChangeTests(WorkflowTestCase):
    def test_a_validator_that_edits_its_own_subject_produces_no_evidence(self):
        """The negative control, asserted directly.

        A validator is arbitrary code. The naive shape of this feature cannot
        tell a validator that checked the code from one that edited the code
        and then reported success.
        """
        config_text = builders.config(
            [
                surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
                builders.NON_QUANT,
                validator(
                    "causality",
                    ["./checks/causality.sh"],
                    True,
                    60,
                    contracts=["CAUSALITY"],
                ),
            ]
        )
        self.build(
            config_text=config_text,
            scripts=[
                builders.script(
                    "causality",
                    body="echo rewritten >> src/strategy/alpha.py\nexit 0",
                )
            ],
        )
        self.start()
        status, out, _err = self.check("causality")
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(check.AUTHORITY_CHANGED_DURING_CHECK, out)
        self.assertIn(evidence.STALE_OWNED_CONTENT, out)
        self.assertIsNone(self.stored_evidence())

    def test_a_previous_record_is_removed_rather_than_left_looking_current(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        self.assertIsNotNone(self.stored_evidence())

        with open(os.path.join(self.repo, "checks", "causality.sh"), "w") as handle:
            handle.write(
                "#!/bin/sh\necho rewritten >> src/strategy/alpha.py\nexit 0\n"
            )
        os.chmod(os.path.join(self.repo, "checks", "causality.sh"), 0o755)

        status, _out, _err = self.check("unit", "causality")
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIsNone(self.stored_evidence())


class WriteConfinementTests(WorkflowTestCase):
    def test_a_check_that_runs_nothing_writes_no_repository_path(self):
        """AIQE core's own repository writes are the zero-tolerance quantity.

        Consent is withheld here so that nothing but AIQE core is running, and
        the measurement is on the repository's bytes rather than on AIQE's own
        report about itself.
        """
        self.build()
        self.start()
        support.measurement.wait_until_quiescent(self.repo, self.case.canaries)
        before = support.measurement.snapshot(self.repo, self.case.canaries)
        status, _out, _err = self.check()
        after = support.measurement.snapshot(self.repo, self.case.canaries)

        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(support.measurement.compare(before, after), [])

    def test_a_receipt_writes_no_repository_path(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        support.measurement.wait_until_quiescent(self.repo, self.case.canaries)
        before = support.measurement.snapshot(self.repo, self.case.canaries)
        self.run_cli(["receipt"])
        self.run_cli(["receipt", "--local"])
        after = support.measurement.snapshot(self.repo, self.case.canaries)
        self.assertEqual(support.measurement.compare(before, after), [])


class ExitVocabularyTests(WorkflowTestCase):
    def test_the_check_exit_matrix(self):
        """0 complete · 1 required failure · 2 incomplete · 3 refusal."""
        self.build()
        self.start()
        self.assertEqual(self.check("unit", "causality")[0], exits.OK)
        self.assertEqual(self.check()[0], exits.INCOMPLETE)

        with open(os.path.join(self.repo, "checks", "causality.sh"), "w") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(self.repo, "checks", "causality.sh"), 0o755)
        self.assertEqual(self.check("unit", "causality")[0], exits.FAIL)

        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write("schema = 1\nnonsense = true\n")
        self.assertEqual(self.check("unit")[0], exits.UNSUPPORTED)


class OutputTests(WorkflowTestCase):
    def test_output_is_terminal_safe(self):
        self.build()
        self.start()
        for arguments in (["check"], ["check", "--allow", "unit"]):
            _status, out, err = self.run_cli(arguments)
            self.assertTrue(lines_are_safe(out))
            self.assertTrue(lines_are_safe(err))

    def test_the_json_document_is_stable_across_identical_runs(self):
        """Everything except how long the validators took.

        Wall-clock duration is a measurement, and two runs of the same
        validator legitimately differ. Every claim in the document - the
        classification, the coverage, the outcomes, the verdict - must not.
        """

        def without_durations(document):
            copy = json.loads(json.dumps(document))
            for entry in copy["validators"]:
                entry.pop("duration_ms")
            return copy

        self.build()
        self.start()
        _status, first, _err = self.check_document("unit", "causality")
        _status, second, _err = self.check_document("unit", "causality")
        self.assertEqual(without_durations(first), without_durations(second))

    def test_a_refusal_produces_no_machine_readable_artifact(self):
        """An invalid configuration is not a result."""
        self.build()
        self.start()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write("schema = 99\n")
        status, out, err = self.run_cli(["check", "--format", "json"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertEqual(out, "")
        self.assertTrue(err)


class ConfigurationDigestTests(WorkflowTestCase):
    def test_the_definition_digests_recorded_are_the_declared_ones(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        record = self.stored_evidence()
        parsed = load_config(os.fsencode(self.repo))
        expected = {
            declaration.id: validators.definition_digest(declaration)
            for declaration in parsed.validators
        }
        self.assertEqual(record["authority"]["validator_definitions"], expected)
        self.assertEqual(record["authority"]["config_digest"], parsed.digest)


if __name__ == "__main__":
    unittest.main()
