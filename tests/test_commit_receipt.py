"""The post-commit receipt: the one place `REVIEWABLE` can be reached.

A completely green check still produces `INCOMPLETE`, with the reason named
rather than implied. Only a verified bounded commit turns the receipt into:

```
Owned scope     VERIFIED
Foreign staged  EXCLUDED
Checked content BOUND
Commit          CREATED
Push            NOT_PERFORMED_BY_AIQE
Verdict         REVIEWABLE
```

Two properties are load-bearing and easy to lose.

**The shareable receipt still discloses nothing.** A commit identifier is
exactly the right thing to show locally - the user is standing in that
repository - and exactly the wrong thing to put in an artifact they paste into
a pull request, because it names a commit, which names a branch, which names a
project. The default receipt gains a state and a count; it gains no
identifier.

**A post-commit receipt is about the commit AIQE created.** Once the
repository has moved past it, the receipt stops claiming a current reviewable
state. It does not become a verifier for arbitrary historical commits.
"""

import json
import unittest

from . import support

from aiqe import exits, receipt
from .test_commit import CommitTestCase

builders = support.commit_builders


class PostCommitReceiptTests(CommitTestCase):
    def receipt(self, *arguments):
        return self.run_cli(["receipt"] + list(arguments))

    def document(self, *arguments):
        status, out, err = self.run_cli(
            ["receipt"] + list(arguments) + ["--format", "json"]
        )
        return status, (json.loads(out) if out else None), err

    def test_a_green_check_alone_is_still_incomplete(self):
        self.build(owned_setup=builders.edit_owned)
        self.start()
        self.check()
        status, out, _err = self.receipt()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(receipt.BOUNDED_COMMIT_NOT_CREATED, out)
        self.assertIn("Commit          NONE", out)
        self.assertNotIn(receipt.REVIEWABLE, out)

    def test_a_verified_bounded_commit_is_reviewable(self):
        self.build(owned_setup=builders.edit_owned)
        status, _out, err = self.workflow()
        self.assertEqual(status, exits.OK, err)

        status, out, _err = self.receipt()
        self.assertEqual(status, exits.OK)
        for line in (
            "Owned scope     VERIFIED",
            "Foreign staged  EXCLUDED",
            "Checked content BOUND",
            "Commit          CREATED",
            "Push            NOT_PERFORMED_BY_AIQE",
            "Verdict         REVIEWABLE",
        ):
            self.assertIn(line, out)

    def test_the_shareable_receipt_names_no_commit(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        head = self.head()

        status, document, _err = self.document()
        self.assertEqual(status, exits.OK)
        text = json.dumps(document)
        self.assertNotIn(head, text)
        self.assertNotIn(builders.OWNED_TEXT, text)
        self.assertNotIn("local", document)
        self.assertEqual(document["commit"], receipt.CREATED)
        self.assertEqual(document["committed_path_count"], 1)

    def test_the_local_receipt_names_the_commit_it_is_about(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        head = self.head()

        status, document, _err = self.document("--local")
        self.assertEqual(status, exits.OK)
        detail = document["local"]["commit"]
        self.assertEqual(detail["commit_sha"], head)
        self.assertEqual(detail["expected_changed_paths"], [builders.OWNED_TEXT])
        self.assertEqual(detail["actual_changed_paths"], [builders.OWNED_TEXT])
        self.assertFalse(detail["push_performed_by_aiqe"])
        self.assertEqual(
            detail["foreign_staged_pre_digest"],
            detail["foreign_staged_post_digest"],
        )

    def test_a_later_commit_stops_the_receipt_claiming_a_current_state(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        builders.put(self.repo, b"tests/later.py", b"LATER = 1\n")
        builders.git(self.repo, "add", "--all", env=self.env)
        builders.git(self.repo, "commit", "--quiet", "--message", "later",
                     env=self.env)

        status, out, _err = self.receipt()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn(receipt.COMPLETION_COMMIT_SUPERSEDED, out)
        self.assertNotIn("Verdict         REVIEWABLE", out)

    def test_ending_the_task_removes_the_reviewable_state(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        self.run_cli(["task", "end"])
        status, _out, err = self.receipt()
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assertIn("no active task", err)

    def test_a_new_task_cannot_inherit_the_previous_completion_commit(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        self.run_cli(["task", "end"])

        builders.put(self.repo, b"tests/next.py", b"NEXT = 1\n")
        status, _out, err = self.run_cli(
            ["task", "start", "--own", "tests/next.py"]
        )
        self.assertEqual(status, exits.OK, err)
        status, out, _err = self.receipt()
        self.assertEqual(status, exits.INCOMPLETE)
        self.assertIn("Commit          NONE", out)
        self.assertNotIn("Verdict         REVIEWABLE", out)


class ReceiptSchemaTests(CommitTestCase):
    def test_the_schema_version_marks_the_bounded_commit_shape(self):
        """Version 1 promised `commit` was always NONE. This is not that."""
        self.assertEqual(receipt.RECEIPT_SCHEMA_VERSION, 2)

    def test_the_default_document_gains_states_and_counts_only(self):
        self.build(owned_setup=builders.edit_owned)
        self.workflow()
        _status, document, _err = self.run_cli(
            ["receipt", "--format", "json"]
        )
        document = json.loads(document)

        allowed = {
            "receipt",
            receipt.DEFAULT_REDACTION_POLICY,
            receipt.VERIFIED,
            receipt.EXCLUDED,
            receipt.BOUND,
            receipt.CREATED,
            receipt.CURRENT,
            receipt.REVIEWABLE,
            receipt.NOT_PERFORMED_BY_AIQE,
        }
        from aiqe import __version__

        allowed.add(__version__)

        def walk(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, path + [key])
            elif isinstance(value, list):
                for item in value:
                    walk(item, path + ["[]"])
            elif isinstance(value, str):
                self.assertIn(
                    value, allowed,
                    "unexpected free text at %s: %r" % ("/".join(path), value),
                )
            else:
                self.assertIsInstance(value, (int, bool, type(None)))

        walk(document, [])


if __name__ == "__main__":
    unittest.main()
