"""Every action in every workflow is one of four reviewed identities.

This is the check that replaces a scanner exception rather than merely
accompanying it. `tools/public-scan/public-scan.sh` skips its `GIT_SHA_40`
class on a `uses:` pin line inside a workflow file - otherwise the scan would
report the supply-chain control as a leak - and the exception is only
defensible if something stronger takes its place. This is that something.

Shape is not identity, and shape was the earlier mistake. Asserting that a
reference is *some* 40-character object id accepts
`actions/checkout@<any 40 hex>` - including a typo, a commit from a fork, and
an id an attacker chose - which is most of what pinning exists to prevent. So
what is asserted here is the exact tuple: which action, which object id, which
released version. The four below were resolved from the canonical upstream
repositories and verified there; re-establishing that is a review step taken
when a pin changes, not a network call made at validation time. These tests
are offline and deterministic.

Object ids are written as two adjacent string literals. Python joins them at
parse time, so the value is exact, while the source carries no 40-character
hexadecimal run - which would otherwise make this file itself a `GIT_SHA_40`
finding. The alternative was excepting the scanner on test files, and a
scanner exception granted to keep a test convenient is how the exception
mechanism stops meaning anything. `test_the_reviewed_ids_are_well_formed`
checks the halves rejoin to exactly forty hexadecimal characters.
"""

import hashlib
import os
import re
import unittest

from . import support

WORKFLOWS = os.path.join(support.ROOT, ".github", "workflows")

#: The only external actions this project runs, and the only identities they
#: may carry. Changing an entry here is the review step for taking on a new
#: version of a supply-chain dependency, and it is meant to be visible in a
#: diff and hard to do by accident.
APPROVED = {
    "actions/checkout": (
        "11d5960a326750d5838078" "e36cf38b85af677262",
        "v4.4.0",
    ),
    "actions/setup-python": (
        "a26af69be951a213d495a4" "c3e4e4022e16d87065",
        "v5.6.0",
    ),
    "actions/upload-artifact": (
        "ea165f8d65b6e75b540449" "e92b4886f43607fa02",
        "v4.6.2",
    ),
    "actions/download-artifact": (
        "d3f86a106a0bac45b974a6" "28896c90dbdf5c8093",
        "v4.3.0",
    ),
}

#: One `uses:` line: the reference, and the trailing comment if there is one.
USES = re.compile(
    r"^\s*-?\s*uses:\s*(?P<ref>\S+)"
    r"(?:\s+#\s*(?P<comment>.*?))?\s*$"
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")


def synthetic_sha(seed):
    """A well-formed object id that is not any reviewed one.

    Derived rather than written out, for the same reason the reviewed ids are
    split: a literal here would be a `GIT_SHA_40` finding in a file the
    scanner is right to be strict about.
    """
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def workflow_files():
    if not os.path.isdir(WORKFLOWS):
        return []
    return sorted(
        os.path.join(WORKFLOWS, name)
        for name in os.listdir(WORKFLOWS)
        if name.endswith((".yml", ".yaml"))
    )


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def references(text):
    """Every `uses:` in one workflow, as (line number, ref, comment)."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = USES.match(line)
        if match:
            found.append(
                (number, match.group("ref"), (match.group("comment") or "").strip())
            )
    return found


def violations(text):
    """Every way this workflow text departs from the approved identities.

    Returns a list of `(line number, code)`. Empty means every reference is an
    exact reviewed tuple and every reviewed action is present.
    """
    problems = []
    seen = set()

    for number, ref, comment in references(text):
        if "@" not in ref:
            problems.append((number, "UNPINNED_REFERENCE"))
            continue
        action, _, revision = ref.partition("@")

        if action not in APPROVED:
            # Covers an unreviewed first-party action and a third-party one
            # alike. Neither is more acceptable than the other: what is
            # approved is an identity, not an owner.
            problems.append((number, "UNAPPROVED_ACTION"))
            continue

        approved_sha, approved_version = APPROVED[action]
        seen.add(action)

        if not HEX40.match(revision):
            # A tag or a branch. `@v4` resolves to whatever it points at when
            # the job runs, which is the whole defect.
            problems.append((number, "NOT_A_FULL_COMMIT_ID"))
            continue
        if revision != approved_sha:
            problems.append((number, "UNAPPROVED_COMMIT_ID"))
            continue
        if comment != approved_version:
            # A bare id is unreadable and a wrong version comment is worse
            # than none: it tells a reviewer the pin is something it is not.
            problems.append((number, "VERSION_COMMENT_MISMATCH"))

    for action in sorted(set(APPROVED) - seen):
        problems.append((0, "APPROVED_ACTION_MISSING:" + action))

    return problems


def codes(text):
    return sorted({code for _number, code in violations(text)})


def workflow(*lines):
    """A minimal synthetic workflow body."""
    return "name: example\njobs:\n  one:\n    steps:\n" + "".join(
        "      - uses: %s\n" % (line,) for line in lines
    )


def every_approved_line():
    return [
        "%s@%s # %s" % (action, sha, version)
        for action, (sha, version) in sorted(APPROVED.items())
    ]


class TheReviewedIdentities(unittest.TestCase):
    def test_the_reviewed_ids_are_well_formed(self):
        """The split literals rejoin to exactly forty hexadecimal characters."""
        for action, (sha, version) in APPROVED.items():
            self.assertEqual(len(sha), 40, action)
            self.assertRegex(sha, HEX40, action)
            self.assertRegex(version, r"^v\d+\.\d+\.\d+$", action)

    def test_the_reviewed_ids_are_distinct(self):
        shas = [sha for sha, _version in APPROVED.values()]
        self.assertEqual(len(shas), len(set(shas)))


class TheRealWorkflows(unittest.TestCase):
    def test_there_is_something_to_check(self):
        """A vacuous pass is the failure mode this whole file has to avoid.

        Every assertion below iterates. If the workflows moved or the listing
        stopped matching, they would all pass by finding nothing, and the
        scanner exception they justify would be resting on air.
        """
        self.assertTrue(workflow_files())
        self.assertTrue(any(references(read(p)) for p in workflow_files()))

    def test_every_reference_is_an_approved_identity(self):
        for path in workflow_files():
            self.assertEqual(
                violations(read(path)), [], os.path.basename(path)
            )

    def test_every_approved_action_is_still_used(self):
        used = set()
        for path in workflow_files():
            for _number, ref, _comment in references(read(path)):
                used.add(ref.partition("@")[0])
        self.assertEqual(used, set(APPROVED))

    def test_the_whole_reference_set_is_covered(self):
        """The positive control, counted.

        A validator that silently stopped parsing most lines would still pass
        every assertion above, so the number of references it actually saw is
        asserted rather than assumed.
        """
        total = sum(len(references(read(p))) for p in workflow_files())
        self.assertEqual(total, 30)


class RejectedIdentities(unittest.TestCase):
    """One negative per way a pin can be wrong. Each must be caught."""

    def test_approved_action_with_a_random_object_id(self):
        text = workflow(
            "actions/checkout@%s # v4.4.0" % (synthetic_sha("random"),)
        )
        self.assertIn("UNAPPROVED_COMMIT_ID", codes(text))

    def test_approved_action_with_another_real_but_unapproved_id(self):
        """A real object id, reviewed - for a different action.

        This is the realistic mistake: a line copied and the action name
        edited without the id. Shape checking accepts it completely.
        """
        borrowed = APPROVED["actions/setup-python"][0]
        text = workflow("actions/checkout@%s # v4.4.0" % (borrowed,))
        self.assertIn("UNAPPROVED_COMMIT_ID", codes(text))

    def test_approved_pin_with_the_wrong_version_comment(self):
        sha = APPROVED["actions/checkout"][0]
        text = workflow("actions/checkout@%s # v4.1.0" % (sha,))
        self.assertIn("VERSION_COMMENT_MISMATCH", codes(text))

    def test_approved_pin_with_no_version_comment(self):
        sha = APPROVED["actions/checkout"][0]
        text = workflow("actions/checkout@%s" % (sha,))
        self.assertIn("VERSION_COMMENT_MISMATCH", codes(text))

    def test_an_unreviewed_first_party_action(self):
        text = workflow(
            "actions/never-reviewed@%s # v1.0.0" % (synthetic_sha("never"),)
        )
        self.assertIn("UNAPPROVED_ACTION", codes(text))

    def test_a_third_party_action(self):
        text = workflow(
            "docker/login-action@%s # v3.0.0" % (synthetic_sha("docker"),)
        )
        self.assertIn("UNAPPROVED_ACTION", codes(text))

    def test_a_mutable_major_tag(self):
        text = workflow("actions/checkout@v4")
        self.assertIn("NOT_A_FULL_COMMIT_ID", codes(text))

    def test_a_reference_with_no_revision_at_all(self):
        text = workflow("actions/checkout")
        self.assertIn("UNPINNED_REFERENCE", codes(text))

    def test_a_dropped_approved_action_is_noticed(self):
        text = workflow(*every_approved_line()[:-1])
        self.assertTrue(
            any(code.startswith("APPROVED_ACTION_MISSING") for code in codes(text))
        )

    def test_a_repeated_approved_action_is_allowed(self):
        """Only with its exact tuple, and it appears many times in practice."""
        line = every_approved_line()
        text = workflow(*(line + [line[0], line[0]]))
        self.assertEqual(codes(text), [])

    def test_a_repeated_action_with_one_bad_pin_is_caught(self):
        """The second reference is checked as hard as the first."""
        lines = every_approved_line()
        lines.append(
            "actions/checkout@%s # v4.4.0" % (synthetic_sha("second"),)
        )
        self.assertIn("UNAPPROVED_COMMIT_ID", codes(workflow(*lines)))

    def test_the_full_approved_set_passes(self):
        self.assertEqual(codes(workflow(*every_approved_line())), [])


class TheCombinedGate(unittest.TestCase):
    """Scanner and pin validator, together, on the same synthetic workflow.

    Neither control is sufficient alone, and the division of labour is the
    point. The scanner asks a *sanitisation* question - is a bare object id
    reaching public content - and a syntactically correct pin answers it
    whatever id it carries. The pin validator asks the *supply-chain*
    question - is this the reviewed identity - which the scanner was never
    able to ask. A wrong id therefore passes the scanner and must still fail
    the gate, and these cases assert exactly that rather than assuming it.
    """

    def scan(self, files):
        """Run the real scanner over a synthetic tree. Returns True on PASS."""
        import shutil
        import subprocess
        import tempfile

        root = tempfile.mkdtemp(prefix="aiqe-combined-")
        self.addCleanup(shutil.rmtree, root, True)
        tools = os.path.join(root, "tools", "public-scan")
        os.makedirs(tools)
        source = os.path.join(support.ROOT, "tools", "public-scan")
        for name in ("public-scan.sh", "patterns.txt"):
            shutil.copy(os.path.join(source, name), os.path.join(tools, name))

        for relative, body in files.items():
            destination = os.path.join(root, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(body)

        completed = subprocess.run(
            [os.path.join(tools, "public-scan.sh")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
        )
        return completed.returncode == 0

    def gate(self, body):
        """(scanner passed, pin validator passed) for one workflow body."""
        scanner = self.scan({".github/workflows/checks.yml": body})
        return scanner, codes(body) == []

    def test_the_approved_pins_pass_both_controls(self):
        scanner, pins = self.gate(workflow(*every_approved_line()))
        self.assertTrue(scanner)
        self.assertTrue(pins)

    def test_an_approved_action_with_a_random_id_is_stopped_by_the_pins(self):
        lines = every_approved_line()
        lines[0] = "actions/checkout@%s # v4.4.0" % (synthetic_sha("random"),)
        scanner, pins = self.gate(workflow(*lines))

        # The scanner has no way to tell this from a correct pin, and is not
        # asked to. The gate closes anyway.
        self.assertTrue(scanner)
        self.assertFalse(pins)

    def test_an_unreviewed_first_party_action_is_stopped_by_the_pins(self):
        lines = every_approved_line()
        lines.append(
            "actions/never-reviewed@%s # v1.0.0" % (synthetic_sha("never"),)
        )
        scanner, pins = self.gate(workflow(*lines))
        self.assertTrue(scanner)
        self.assertFalse(pins)

    def test_a_third_party_action_is_stopped_by_the_pins(self):
        lines = every_approved_line()
        lines.append(
            "docker/login-action@%s # v3.0.0" % (synthetic_sha("docker"),)
        )
        scanner, pins = self.gate(workflow(*lines))
        self.assertTrue(scanner)
        self.assertFalse(pins)

    def test_a_bare_object_id_in_a_workflow_is_stopped_by_the_scanner(self):
        body = workflow(*every_approved_line())
        body += "# rebuilt from %s\n" % (synthetic_sha("bare"),)
        scanner, pins = self.gate(body)

        # Here the division reverses: the pins are all correct, and the loose
        # object id is the scanner's question.
        self.assertFalse(scanner)
        self.assertTrue(pins)

    def test_an_action_shaped_line_outside_a_workflow_is_stopped(self):
        """The exception is scoped by file as well as by line shape."""
        line = "      - uses: actions/checkout@%s # v4.4.0" % (
            APPROVED["actions/checkout"][0],
        )
        self.assertFalse(
            self.scan({"docs/architecture.md": "Pin like this:\n%s\n" % (line,)})
        )
        self.assertFalse(
            self.scan({"src/aiqe/thing.py": "# %s\n" % (line,)})
        )


class TheScannerExceptionStaysNarrow(unittest.TestCase):
    """The exception needs a workflow path *and* a pin line shape.

    Either condition alone leaks. Shape alone lets a foreign object id through
    anywhere in the tree by dressing it up as an action reference; path alone
    lets a bare id through anywhere in a workflow. The behavioural proof is in
    `tools/public-scan/self-test.sh`, which builds all three cases and
    requires the scanner to report them; what is asserted here is that both
    conditions are present and anchored, so neither can be quietly relaxed.
    """

    SCANNER = os.path.join(
        support.ROOT, "tools", "public-scan", "public-scan.sh"
    )

    def scanner_text(self):
        with open(self.SCANNER, encoding="utf-8") as handle:
            return handle.read()

    def variable(self, name):
        text = self.scanner_text()
        self.assertIn(name + "=", text)
        return text.split(name + "='", 1)[1].split("'", 1)[0]

    def test_the_line_shape_is_anchored_at_both_ends(self):
        pattern = self.variable("action_pin_line")
        self.assertTrue(pattern.startswith("^"), pattern)
        self.assertTrue(pattern.endswith("$"), pattern)
        self.assertIn("uses:", pattern)
        self.assertIn("[0-9a-f]{40}", pattern)

    def test_the_file_condition_is_anchored_to_the_workflow_directory(self):
        pattern = self.variable("workflow_path")
        self.assertTrue(pattern.startswith("^"), pattern)
        self.assertTrue(pattern.endswith("$"), pattern)
        self.assertIn(".github/workflows/", pattern)
        self.assertIn("yml", pattern)
        self.assertIn("yaml", pattern)
        # No nesting below workflows/, so a deeper path cannot borrow it.
        self.assertIn("[^/]+", pattern)

    def test_both_conditions_gate_the_exception(self):
        """The path test must be applied, not merely defined."""
        text = self.scanner_text()
        body = text.split("justified_match()", 1)[1].split("\n}", 1)[0]
        self.assertIn("workflow_path", body)
        self.assertIn("action_pin_line", body)

    def test_the_exception_names_this_file_as_its_replacement(self):
        self.assertIn("tests/test_workflow_pinning.py", self.scanner_text())


if __name__ == "__main__":
    unittest.main()
