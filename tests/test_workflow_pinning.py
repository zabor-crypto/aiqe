"""Every action in every workflow is pinned to a full commit id.

This is the check that replaces a scanner exception rather than merely
accompanying it. `tools/public-scan/public-scan.sh` skips its `GIT_SHA_40`
class on a line that is nothing but a `uses:` pin - otherwise the scan would
report the supply-chain control as a leak - and the exception is only
defensible if something stronger takes its place. This is that something.

A mutable major tag is not a version. `actions/checkout@v4` resolves to
whatever that tag points at when the workflow runs, so the code executing in
the job that produces release evidence can change with no change in this
repository and no review anywhere. A full object id is immutable, and the
version comment beside it is what keeps that id readable.

These assertions are structural and offline. Whether a pinned id is the one
upstream published is a provenance question, answered when the pin is made or
updated - not something a test suite may reach the network to re-ask.
"""

import os
import re
import unittest

from . import support

WORKFLOWS = os.path.join(support.ROOT, ".github", "workflows")

#: `uses:` values, as written.
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)")

#: A pinned reference: `owner/repo@<40 lower-case hex>`.
PINNED = re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
                    r"@(?P<sha>[0-9a-f]{40})$")

#: The only owner whose actions this project runs. Narrow on purpose: adding
#: an owner here is the review step for taking on a new supply-chain
#: dependency, and it should be visible in a diff.
ALLOWED_OWNERS = frozenset({"actions"})


def workflow_files():
    if not os.path.isdir(WORKFLOWS):
        return []
    return sorted(
        os.path.join(WORKFLOWS, name)
        for name in os.listdir(WORKFLOWS)
        if name.endswith((".yml", ".yaml"))
    )


def uses_lines():
    """Every `uses:` in every workflow, as (file, line number, line)."""
    found = []
    for path in workflow_files():
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if USES.match(line):
                    found.append((os.path.basename(path), number, line.rstrip("\n")))
    return found


class WorkflowsExist(unittest.TestCase):
    def test_there_is_something_to_check(self):
        """A vacuous pass is the failure mode this whole file has to avoid.

        Every assertion below iterates. If the workflows moved or the glob
        stopped matching, all of them would pass by finding nothing, and the
        scanner exception they justify would be resting on air.
        """
        self.assertTrue(workflow_files())
        self.assertTrue(uses_lines())


class EveryActionIsPinned(unittest.TestCase):
    def test_no_reference_uses_a_tag_or_a_branch(self):
        for name, number, line in uses_lines():
            value = USES.match(line).group(1)
            self.assertRegex(
                value,
                r"@[0-9a-f]{40}$",
                "%s:%d is not pinned to a full commit id: %s"
                % (name, number, value),
            )

    def test_every_pin_names_an_allowed_first_party_owner(self):
        for name, number, line in uses_lines():
            value = USES.match(line).group(1)
            match = PINNED.match(value)
            self.assertIsNotNone(
                match, "%s:%d is not owner/repo@sha: %s" % (name, number, value)
            )
            self.assertIn(
                match.group("owner"),
                ALLOWED_OWNERS,
                "%s:%d runs an action from an unreviewed owner: %s"
                % (name, number, value),
            )

    def test_every_pin_carries_a_readable_version_comment(self):
        """A bare object id is correct and unreadable.

        Without the comment nobody reviewing a bump can tell v4.1.0 from
        v4.4.0, and the practical result is that pins stop being updated.
        """
        for name, number, line in uses_lines():
            self.assertRegex(
                line,
                r"@[0-9a-f]{40}\s+#\s*v\d",
                "%s:%d has no version comment: %s" % (name, number, line.strip()),
            )

    def test_one_action_resolves_to_one_pin_across_the_workflow(self):
        """The same action pinned two ways is a mistake, not a policy.

        It means a bump was applied to some jobs and not others, and the jobs
        that were missed are the ones nobody will look at again.
        """
        pins = {}
        for name, number, line in uses_lines():
            value = USES.match(line).group(1)
            action, _, sha = value.partition("@")
            pins.setdefault(action, set()).add(sha)
        for action, shas in sorted(pins.items()):
            self.assertEqual(
                len(shas), 1,
                "%s is pinned to more than one commit: %s"
                % (action, ", ".join(sorted(shas))),
            )


class TheScannerExceptionStaysNarrow(unittest.TestCase):
    """The exception is scoped to a line shape, and the shape is anchored.

    A file-scoped exception would blind the scan to a foreign object id
    anywhere in the workflow, which is the case `GIT_SHA_40` exists for.
    """

    SCANNER = os.path.join(
        support.ROOT, "tools", "public-scan", "public-scan.sh"
    )

    def scanner_text(self):
        with open(self.SCANNER, encoding="utf-8") as handle:
            return handle.read()

    def test_the_exception_pattern_is_anchored_at_both_ends(self):
        text = self.scanner_text()
        self.assertIn("action_pin_line=", text)
        pattern = text.split("action_pin_line='", 1)[1].split("'", 1)[0]
        self.assertTrue(pattern.startswith("^"), pattern)
        self.assertTrue(pattern.endswith("$"), pattern)
        self.assertIn("uses:", pattern)
        self.assertIn("[0-9a-f]{40}", pattern)

    def test_the_exception_names_this_file_as_its_replacement(self):
        """The scanner promises a stronger check. This is it, by name."""
        self.assertIn("tests/test_workflow_pinning.py", self.scanner_text())


if __name__ == "__main__":
    unittest.main()
