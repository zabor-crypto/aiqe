"""`aiqe receipt`: the verdict, and what the shareable surface may contain.

Two things are load-bearing here and both are asserted as properties rather
than as examples.

**No pre-commit state produces `REVIEWABLE`.** Not the completely green one.
`REVIEWABLE` is a claim about a commit whose content is provably the checked
content, and no commit exists.

**The default receipt discloses no identity.** It is the artifact a person
pastes into a pull request or a screenshot, and the exclusion list is checked
against the fixture's real values - the worktree path, the owned filename, the
commit identifiers, the validator command lines, the home directory, the
username, the hostname - rather than against a pattern that might not match
them.
"""

import io
import itertools
import json
import os
import platform
import shutil
import tempfile
import unittest

from . import support

from aiqe import evidence, exits, receipt
from aiqe.cli import main
from aiqe.textsafe import is_safe

builders = support.check_builders

QUANT_CONFIG = builders.config(
    [
        builders.surface(["src/strategy/**"], quant=True, contracts=["CAUSALITY"]),
        builders.NON_QUANT,
        builders.validator("unit", ["./checks/unit.sh"], True, 60),
        builders.validator(
            "causality", ["./checks/causality.sh"], True, 60, contracts=["CAUSALITY"]
        ),
    ]
)


class ReceiptTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-receipt-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("receipt", self.root, ("repo",))
        self.env = self.case.env()
        self.repo = None

    def build(self, config_text=QUANT_CONFIG, scripts=None, edit_owned=True):
        if scripts is None:
            scripts = [builders.script("unit"), builders.script("causality")]
        self.repo = builders.build_repository(
            self.case, self.env, config_text, scripts, edit_owned
        )
        return self.repo

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self):
        self.run_cli(["task", "start", "--own", builders.OWNED_TEXT])

    def check(self, *allow):
        arguments = ["check"]
        for identifier in allow:
            arguments += ["--allow", identifier]
        return self.run_cli(arguments)[0]

    def receipt(self, *flags):
        status, out, err = self.run_cli(["receipt"] + list(flags))
        return status, out, err

    def document(self, *flags):
        status, out, _err = self.run_cli(["receipt", "--format", "json"] + list(flags))
        return status, (json.loads(out) if out else None)


class VerdictTests(ReceiptTestCase):
    def test_no_active_task_is_a_deterministic_refusal(self):
        """Rather than a fabricated receipt about nothing."""
        self.build()
        status, out, err = self.receipt()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertEqual(out, "")
        self.assertIn("no active task", err)

    def test_a_task_with_no_check_is_incomplete(self):
        self.build()
        self.start()
        status, document = self.document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(document["verdict"], receipt.INCOMPLETE)
        self.assertEqual(document["owned_scope"], receipt.DECLARED)
        self.assertEqual(document["evidence"], receipt.NONE)
        self.assertEqual(document["commit"], receipt.NONE)
        self.assertIn(receipt.EVIDENCE_NONE, document["reasons"])

    def test_a_green_check_is_still_incomplete(self):
        """The distinction this whole phase turns on.

        Every pre-commit obligation is discharged, and the verdict is still
        INCOMPLETE, because the thing that would make the work reviewable - a
        bounded commit whose content is provably the checked content - has not
        been created.
        """
        self.build()
        self.start()
        self.assertEqual(self.check("unit", "causality"), exits.OK)

        status, document = self.document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(document["owned_scope"], receipt.CHECKED)
        self.assertEqual(document["foreign_staged"], receipt.OBSERVED)
        self.assertEqual(document["evidence"], receipt.CURRENT)
        self.assertEqual(document["commit"], receipt.NONE)
        self.assertEqual(document["verdict"], receipt.INCOMPLETE)
        self.assertEqual(document["reasons"], [receipt.BOUNDED_COMMIT_NOT_CREATED])

    def test_a_required_failure_is_not_reviewable(self):
        self.build(scripts=[builders.script("unit"), builders.script("causality", 1)])
        self.start()
        self.assertEqual(self.check("unit", "causality"), exits.FAIL)
        status, document = self.document()
        self.assertEqual(status, exits.FAIL)
        self.assertEqual(document["verdict"], receipt.NOT_REVIEWABLE)
        self.assertEqual(document["evidence"], receipt.CURRENT)

    def test_a_coverage_gap_is_incomplete(self):
        config_text = builders.config(
            [
                builders.surface(
                    ["src/strategy/**"], quant=True, contracts=["CAUSALITY"]
                ),
                builders.NON_QUANT,
                builders.validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        self.build(config_text=config_text, scripts=[builders.script("unit")])
        self.start()
        self.assertEqual(self.check("unit"), exits.INCOMPLETE)
        status, document = self.document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(document["verdict"], receipt.INCOMPLETE)
        self.assertIn("COVERAGE_GAP", document["reasons"])


class StalenessTests(ReceiptTestCase):
    def green(self):
        self.build()
        self.start()
        self.assertEqual(self.check("unit", "causality"), exits.OK)

    def test_owned_content_change(self):
        self.green()
        builders.write(
            os.path.join(self.repo, "src", "strategy", "alpha.py"), "EDITED = 1\n"
        )
        status, document = self.document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertEqual(document["evidence"], receipt.STALE)
        self.assertEqual(document["reasons"], [evidence.STALE_OWNED_CONTENT])

    def test_a_mode_change_alone_is_a_change(self):
        self.green()
        path = os.path.join(self.repo, "src", "strategy", "alpha.py")
        os.chmod(path, 0o755)
        _status, document = self.document()
        self.assertEqual(document["reasons"], [evidence.STALE_OWNED_CONTENT])

    def test_head_move(self):
        self.green()
        builders.write(os.path.join(self.repo, "docs", "notes.md"), "revised\n")
        builders.git(self.repo, "add", "docs/notes.md", env=self.env)
        builders.git(self.repo, "commit", "-q", "-m", "unrelated", env=self.env)
        _status, document = self.document()
        self.assertEqual(document["evidence"], receipt.STALE)
        self.assertEqual(document["reasons"], [evidence.STALE_HEAD])

    def test_configuration_change(self):
        self.green()
        with open(os.path.join(self.repo, "aiqe.toml"), "a") as handle:
            handle.write("\n# a comment\n")
        _status, document = self.document()
        self.assertEqual(document["reasons"], [evidence.STALE_CONFIG])

    def test_validator_definition_change(self):
        self.green()
        with open(os.path.join(self.repo, "aiqe.toml")) as handle:
            text = handle.read()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write(text.replace("timeout = 60", "timeout = 90"))
        _status, document = self.document()
        self.assertEqual(
            sorted(document["reasons"]),
            sorted([evidence.STALE_CONFIG, evidence.STALE_VALIDATOR_DEFINITION]),
        )

    def test_a_receipt_runs_no_validator(self):
        """Freshness is decided by recomputing bounded authority.

        Re-running the validators to answer "is this still true" would make
        the answer depend on running them again, which is the question it was
        supposed to settle.
        """
        self.green()
        os.unlink(self.case.marker("unit"))
        os.unlink(self.case.marker("causality"))
        self.receipt()
        self.receipt("--local")
        self.assertEqual(self.case.fired(), [])

    def test_an_unrelated_file_does_not_make_evidence_stale(self):
        """No whole-worktree fingerprint. A foreign file is not this task."""
        self.green()
        builders.write(os.path.join(self.repo, "docs", "notes.md"), "revised\n")
        builders.write(os.path.join(self.repo, "unrelated.txt"), "new\n")
        _status, document = self.document()
        self.assertEqual(document["evidence"], receipt.CURRENT)


class RefusalTests(ReceiptTestCase):
    def test_a_config_conflict_produces_no_receipt_artifact(self):
        config_text = builders.config(
            [
                builders.surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
                builders.surface(["**/alpha.py"], quant=False),
                builders.NON_QUANT,
                builders.validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        self.build(config_text=config_text, scripts=[builders.script("unit")])
        self.start()
        for flags in ([], ["--local"], ["--format", "json"]):
            status, out, err = self.run_cli(["receipt"] + flags)
            self.assertEqual(status, exits.UNSUPPORTED, flags)
            self.assertEqual(out, "", flags)
            self.assertTrue(err)

    def test_a_refusal_names_no_repository_path(self):
        """An error string is still the surface a user shares."""
        config_text = builders.config(
            [
                builders.surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
                builders.surface(["**/alpha.py"], quant=False),
                builders.NON_QUANT,
            ]
        )
        self.build(config_text=config_text, scripts=())
        self.start()
        _status, _out, err = self.receipt()
        self.assertNotIn("alpha.py", err)
        self.assertNotIn(self.repo, err)

    def test_an_invalid_configuration_produces_no_receipt(self):
        self.build()
        self.start()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write("schema = 99\n")
        status, out, _err = self.receipt()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertEqual(out, "")

    def test_an_absent_configuration_still_produces_a_receipt(self):
        """A task without a configuration is an ordinary state, not a refusal."""
        self.build()
        self.start()
        os.unlink(os.path.join(self.repo, "aiqe.toml"))
        status, document = self.document()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(receipt.CONFIG_ABSENT, document["reasons"])


class PrivacyTests(ReceiptTestCase):
    """The default receipt's exclusion list, checked against real values."""

    def forbidden(self):
        head = builders.git(self.repo, "rev-parse", "HEAD", env=self.env, check=False)
        sha = head.stdout.decode("ascii", "replace").strip()
        branch = builders.git(
            self.repo, "rev-parse", "--abbrev-ref", "HEAD", env=self.env, check=False
        )
        values = {
            "case root": self.root,
            "worktree path": self.repo,
            "home directory": self.env["HOME"],
            "state home": self.env["XDG_STATE_HOME"],
            "owned path": builders.OWNED_TEXT,
            "owned filename": "alpha.py",
            "repository directory name": os.path.basename(self.repo),
            "validator command": "./checks/unit.sh",
            "configuration filename": "aiqe.toml",
            "commit sha": sha,
            "abbreviated sha": sha[:12],
            "branch": branch.stdout.decode("ascii", "replace").strip(),
        }
        for label, value in (
            ("username", os.environ.get("USER") or os.environ.get("LOGNAME")),
            ("hostname", platform.node()),
        ):
            if value and len(value) > 3:
                values[label] = value
        return {label: value for label, value in values.items() if value}

    def rendered_surfaces(self):
        _status, human, _err = self.receipt()
        _status, machine, _err = self.run_cli(["receipt", "--format", "json"])
        return {"human": human, "json": machine}

    def assert_no_disclosure(self):
        forbidden = self.forbidden()
        for surface_name, text in self.rendered_surfaces().items():
            self.assertTrue(text, surface_name)
            for label, value in sorted(forbidden.items()):
                self.assertNotIn(
                    value,
                    text,
                    "the default %s receipt disclosed the %s"
                    % (surface_name, label),
                )

    def test_a_green_receipt_discloses_nothing(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        self.assert_no_disclosure()

    def test_a_failing_receipt_discloses_nothing(self):
        self.build(scripts=[builders.script("unit"), builders.script("causality", 1)])
        self.start()
        self.check("unit", "causality")
        self.assert_no_disclosure()

    def test_a_receipt_with_no_evidence_discloses_nothing(self):
        self.build()
        self.start()
        self.assert_no_disclosure()

    def test_a_stale_receipt_discloses_nothing(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        builders.write(
            os.path.join(self.repo, "src", "strategy", "alpha.py"), "EDITED = 1\n"
        )
        self.assert_no_disclosure()

    def test_an_unclassified_receipt_discloses_no_path(self):
        """`check` may name the path locally. The receipt may not."""
        config_text = builders.config(
            [
                builders.surface(["docs/**", "checks/**", "aiqe.toml"], quant=False),
                builders.validator("unit", ["./checks/unit.sh"], True, 60),
            ]
        )
        self.build(config_text=config_text, scripts=[builders.script("unit")])
        self.start()
        self.check("unit")
        self.assert_no_disclosure()

    def test_validator_output_never_reaches_the_default_receipt(self):
        self.build(
            scripts=[
                builders.script("unit"),
                builders.script(
                    "causality", body="echo SECRET_VALIDATOR_OUTPUT >&2; exit 1"
                ),
            ]
        )
        self.start()
        self.check("unit", "causality")
        for text in self.rendered_surfaces().values():
            self.assertNotIn("SECRET_VALIDATOR_OUTPUT", text)

    def test_the_task_label_never_reaches_the_default_receipt(self):
        self.build()
        self.run_cli(
            [
                "task",
                "start",
                "--own",
                builders.OWNED_TEXT,
                "--label",
                "SECRET_PROJECT_NAME",
            ]
        )
        self.check("unit", "causality")
        for text in self.rendered_surfaces().values():
            self.assertNotIn("SECRET_PROJECT_NAME", text)

    def test_the_default_document_carries_only_the_declared_fields(self):
        """A field can only reach the shareable surface by being written into
        the serialiser above the local branch."""
        self.build()
        self.start()
        self.check("unit", "causality")
        _status, document = self.document()
        self.assertEqual(
            sorted(document),
            sorted(
                [
                    "aiqe_version",
                    "checked_content",
                    "classification",
                    "command",
                    "commit",
                    "coverage",
                    "evidence",
                    "exit_code",
                    "foreign_staged",
                    "owned_changed_count",
                    "owned_declared_count",
                    "owned_scope",
                    "push",
                    "reasons",
                    "receipt_schema_version",
                    "redaction_policy",
                    "validators",
                    "verdict",
                ]
            ),
        )
        self.assertEqual(
            document["redaction_policy"], receipt.DEFAULT_REDACTION_POLICY
        )

    def test_every_value_in_the_default_document_is_a_count_or_a_state(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        _status, document = self.document()

        allowed_strings = set(
            [
                "receipt",
                receipt.DEFAULT_REDACTION_POLICY,
                receipt.CHECKED,
                receipt.DECLARED,
                receipt.OBSERVED,
                receipt.CURRENT,
                receipt.STALE,
                receipt.NONE,
                receipt.INCOMPLETE,
                receipt.NOT_REVIEWABLE,
                receipt.BOUNDED_COMMIT_NOT_CREATED,
                receipt.NOT_PERFORMED_BY_AIQE,
            ]
        )
        from aiqe import __version__

        allowed_strings.add(__version__)

        def walk(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, path + [key])
            elif isinstance(value, list):
                for item in value:
                    walk(item, path + ["[]"])
            elif isinstance(value, str):
                self.assertIn(
                    value,
                    allowed_strings,
                    "unexpected free text at %s: %r" % ("/".join(path), value),
                )
            else:
                self.assertIsInstance(value, (int, bool, type(None)))

        walk(document, [])


class LocalReceiptTests(ReceiptTestCase):
    def test_local_adds_what_the_default_withholds(self):
        self.build()
        self.run_cli(
            ["task", "start", "--own", builders.OWNED_TEXT, "--label", "a label"]
        )
        self.check("unit", "causality")

        status, out, _err = self.receipt("--local")
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(builders.OWNED_TEXT, out)
        self.assertIn("a label", out)
        self.assertIn("not the shareable receipt", out)

    def test_local_json_nests_the_detail_under_one_key(self):
        self.build()
        self.start()
        self.check("unit", "causality")
        _status, out, _err = self.run_cli(["receipt", "--local", "--format", "json"])
        document = json.loads(out)
        self.assertEqual(document["redaction_policy"], receipt.LOCAL_REDACTION_POLICY)
        self.assertIn("local", document)
        self.assertEqual(document["verdict"], receipt.INCOMPLETE)
        self.assertIn(builders.OWNED_TEXT, [e["path"] for e in document["local"]["owned"]])

    def test_local_retains_bounded_failing_output_only(self):
        self.build(
            scripts=[
                builders.script("unit"),
                builders.script("causality", body="echo DETAIL >&2; exit 1"),
            ]
        )
        self.start()
        self.check("unit", "causality")
        _status, out, _err = self.run_cli(["receipt", "--local", "--format", "json"])
        document = json.loads(out)
        by_id = {e["validator_id"]: e for e in document["local"]["validators"]}
        self.assertIn("DETAIL", by_id["causality"]["stderr_tail"])
        self.assertIsNone(by_id["unit"]["stdout_tail"])

    def test_local_output_is_terminal_safe(self):
        self.build(
            scripts=[
                builders.script("unit"),
                builders.script(
                    "causality", body="printf 'a\\033[31mred\\007\\n' >&2; exit 1"
                ),
            ]
        )
        self.start()
        self.check("unit", "causality")
        _status, out, _err = self.receipt("--local")
        self.assertTrue(all(is_safe(line) for line in out.splitlines()))


class ReviewableIsUnreachableTests(ReceiptTestCase):
    """The property, over every valid pre-commit state this build can produce."""

    def test_no_combination_of_pre_commit_state_produces_reviewable(self):
        outcomes = ("pass", "fail")
        classifications = ("quant", "non_quant", "unclassified")
        coverages = ("bound", "unbound")
        consents = (True, False)
        staleness = (None, "owned", "head", "config")

        verdicts = set()
        for classification, coverage, consent, stale, outcome in itertools.product(
            classifications, coverages, consents, staleness, outcomes
        ):
            verdicts.add(
                self.one_combination(
                    classification, coverage, consent, stale, outcome
                )
            )
        self.assertNotIn(receipt.REVIEWABLE, verdicts)
        self.assertTrue(verdicts <= {receipt.INCOMPLETE, receipt.NOT_REVIEWABLE})

    def one_combination(self, classification, coverage, consent, stale, outcome):
        self.setUp()
        surfaces = {
            "quant": builders.surface(
                ["src/strategy/**"], quant=True, contracts=["CAUSALITY"]
            ),
            "non_quant": builders.surface(["src/strategy/**"], quant=False),
            "unclassified": "",
        }[classification]
        bound = ["CAUSALITY"] if coverage == "bound" else None
        config_text = builders.config(
            [
                surfaces,
                builders.NON_QUANT,
                builders.validator(
                    "causality", ["./checks/causality.sh"], True, 60, bound
                ),
            ]
        )
        self.build(
            config_text=config_text,
            scripts=[builders.script("causality", 0 if outcome == "pass" else 1)],
        )
        self.start()
        self.check(*(("causality",) if consent else ()))

        if stale == "owned":
            builders.write(
                os.path.join(self.repo, "src", "strategy", "alpha.py"), "EDITED\n"
            )
        elif stale == "head":
            builders.write(os.path.join(self.repo, "docs", "notes.md"), "revised\n")
            builders.git(self.repo, "add", "docs/notes.md", env=self.env)
            builders.git(self.repo, "commit", "-q", "-m", "x", env=self.env)
        elif stale == "config":
            with open(os.path.join(self.repo, "aiqe.toml"), "a") as handle:
                handle.write("\n# edited\n")

        status, document = self.document()
        self.assertIn(status, (exits.FAIL, exits.INCOMPLETE))
        return document["verdict"]


if __name__ == "__main__":
    unittest.main()
