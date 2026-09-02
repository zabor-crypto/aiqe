"""Repository-controlled text, and the terminal it is printed to.

A validator's identifier, its argument vector and its output are all written
by whoever can land a commit. Every one of them is printed back to a person -
the argument vector next to a question AIQE wants a truthful answer to, the
output next to the verdict it did not earn - and a terminal acts on some bytes
rather than displaying them.

So the rule is: **escape, never strip, and never execute.**

Escaping rather than stripping matters. A prompt that quietly removed part of
the command it is asking about would stop describing the thing being consented
to, and evidence with the awkward bytes deleted is not evidence. What AIQE
shows is a reversible rendering of exactly what is there.

Two defences, in order. The configuration grammar refuses what it can - an
identifier containing a newline never reaches a renderer at all - and
`textsafe` escapes the rest. The second exists because the first is one edit
away.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import support

from aiqe import config, exits
from aiqe.cli import main
from aiqe.textsafe import display_bytes, display_text, is_safe

builders = support.check_builders

#: Bytes a terminal acts on rather than displays. Newline is AIQE's own line
#: structure and is excluded; everything else here moves a cursor, repaints a
#: line, rings a bell, or begins a sequence that does.
def control_bytes(text):
    found = []
    for character in text:
        code = ord(character)
        if code == 0x0A:
            continue
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            found.append(code)
    return found


#: An argument vector aimed at the terminal rather than at the shell. Written
#: as TOML escapes because a raw control character is not legal in a TOML basic
#: string - which is the shape the attack actually has to take.
HOSTILE_ARGV = (
    "./checks/causality.sh",
    "\\u001B[2J\\u001B[H",
    "[y/N]",
    "\\nProceed? Type 'yes' to continue: yes\\n",
    "\\rPASS",
)

HOSTILE_OUTPUT = (
    "printf 'checking\\rPASS SENTINEL-9c1\\n'\n"
    "printf '\\033[2J\\033[Hall green SENTINEL-9c1\\033[32m\\a\\n' >&2\n"
    "exit 1"
)


class GrammarRefusesWhatItCanTests(unittest.TestCase):
    """The first defence: some hostile values never reach a renderer."""

    def refusal(self, raw):
        with self.assertRaises(config.ConfigError) as caught:
            config.parse(raw)
        return caught.exception.code

    def test_a_validator_id_containing_a_newline_is_refused(self):
        raw = (
            b'schema = 1\n[[validator]]\n'
            b'id = "evil\\nAllow validator? [y/N]"\n'
            b'run = ["x"]\nrequired = true\ntimeout = 5\n'
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_VALIDATOR_ID_INVALID)

    def test_a_validator_id_containing_an_escape_is_refused(self):
        raw = (
            b'schema = 1\n[[validator]]\nid = "evil\\u001B[2J"\n'
            b'run = ["x"]\nrequired = true\ntimeout = 5\n'
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_VALIDATOR_ID_INVALID)

    def test_a_contract_identifier_containing_an_escape_is_refused(self):
        raw = (
            b'schema = 1\n[[surface]]\npaths = ["a"]\nquant = true\n'
            b'contracts = ["CAUSALITY\\u001B[2J"]\n'
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_CONTRACT_INVALID)

    def test_an_unknown_field_name_is_escaped_when_it_is_named_back(self):
        """A TOML quoted key can contain anything, including ESC."""
        raw = b'schema = 1\n"evil\\u001B[2J" = 1\n'
        with self.assertRaises(config.ConfigError) as caught:
            config.parse(raw)
        message = caught.exception.message
        self.assertEqual(control_bytes(message), [])
        self.assertIn("\\x1b[2J", message)


class DisplayPrimitiveTests(unittest.TestCase):
    """The one escaping primitive, reused rather than reimplemented."""

    def test_every_dangerous_class_is_escaped(self):
        for raw, expected in (
            ("\x1b[2J", "\\x1b[2J"),
            ("\r", "\\r"),
            ("\n", "\\n"),
            ("\t", "\\t"),
            ("\x07", "\\x07"),
            ("\x7f", "\\x7f"),
            ("\x9b", "\\x9b"),
            ("\\", "\\\\"),
        ):
            self.assertEqual(display_text(raw), expected, repr(raw))
            self.assertTrue(is_safe(display_text(raw)), repr(raw))

    def test_escaping_is_reversible_by_eye_and_never_collides(self):
        """Escape, never strip: two different strings stay different.

        A rendering that mapped distinct commands onto the same text would let
        one consent cover both, which is the point of binding consent to a
        digest of the real definition rather than to what was displayed.
        """
        rendered = {
            display_text(value)
            for value in ("\x1b[2J", "\\x1b[2J", "\\\\x1b[2J", "x1b[2J")
        }
        self.assertEqual(len(rendered), 4)

    def test_ordinary_text_is_left_alone(self):
        self.assertEqual(display_text("pytest -q tests/unit"), "pytest -q tests/unit")
        self.assertEqual(display_bytes(b"src/strategy/alpha.py"), "src/strategy/alpha.py")


class HumanSurfaceTests(unittest.TestCase):
    """The real surfaces, driven with hostile configuration and output."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-terminal-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.case = support.measurement.Case("terminal", self.root, ("repo",))
        self.env = self.case.env()

    def build(self, argv=("./checks/causality.sh",), body="exit 0"):
        text = builders.config(
            [
                builders.surface(
                    ["src/strategy/**"], quant=True, contracts=["CAUSALITY"]
                ),
                builders.NON_QUANT,
                builders.validator(
                    "causality", list(argv), True, 60, contracts=["CAUSALITY"]
                ),
            ]
        )
        self.repo = builders.build_repository(
            self.case, self.env, text, [builders.script("causality", body=body)]
        )

    def run_cli(self, argv, prompt=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(argv, stdout, stderr, self.repo, self.env, prompt=prompt)
        return status, stdout.getvalue(), stderr.getvalue()

    def start(self):
        self.run_cli(["task", "start", "--own", builders.OWNED_TEXT])

    def assert_safe(self, text, where):
        self.assertEqual(
            control_bytes(text),
            [],
            "%s emitted terminal control characters" % (where,),
        )

    def test_the_consent_prompt_escapes_a_hostile_argument_vector(self):
        self.build(argv=HOSTILE_ARGV)
        self.start()
        asked = []
        self.run_cli(["check"], prompt=lambda text: asked.append(text) or False)

        self.assertEqual(len(asked), 1)
        prompt = asked[0]
        self.assert_safe(prompt, "the consent prompt")
        self.assertIn("\\x1b[2J", prompt)
        self.assertIn("\\r", prompt)
        self.assertIn("does not sandbox", prompt)

    def test_the_consent_prompt_still_describes_the_real_command(self):
        """Escaped, not stripped. The question must still be answerable."""
        self.build(argv=HOSTILE_ARGV)
        self.start()
        asked = []
        self.run_cli(["check"], prompt=lambda text: asked.append(text) or False)
        for fragment in ("./checks/causality.sh", "[y/N]", "PASS"):
            self.assertIn(fragment, asked[0], fragment)

    def test_check_human_output_is_safe_with_hostile_configuration(self):
        self.build(argv=HOSTILE_ARGV)
        self.start()
        _status, out, err = self.run_cli(["check", "--allow", "causality"])
        self.assert_safe(out, "aiqe check")
        self.assert_safe(err, "aiqe check (stderr)")

    def test_check_and_receipt_are_safe_with_hostile_validator_output(self):
        self.build(body=HOSTILE_OUTPUT)
        self.start()
        status, out, err = self.run_cli(["check", "--allow", "causality"])
        self.assertEqual(status, exits.FAIL, "a validator's own PASS is not evidence")
        self.assert_safe(out, "aiqe check")
        self.assert_safe(err, "aiqe check (stderr)")

        _status, local, _err = self.run_cli(["receipt", "--local"])
        self.assert_safe(local, "aiqe receipt --local")
        self.assertIn("\\x1b[2J", local, "the escaped form should be visible")
        self.assertIn("SENTINEL-9c1", local, "evidence was stripped, not escaped")

        _status, default, _err = self.run_cli(["receipt"])
        self.assert_safe(default, "aiqe receipt")
        self.assertNotIn("SENTINEL-9c1", default, "validator output reached the receipt")

    def test_json_stays_valid_and_faithful(self):
        """Rendering and authority are separate concerns.

        The local document keeps the output - escaped, and therefore losslessly
        - so that a machine reader sees what the validator actually printed.
        """
        self.build(body=HOSTILE_OUTPUT)
        self.start()
        self.run_cli(["check", "--allow", "causality"])
        _status, out, _err = self.run_cli(["receipt", "--local", "--format", "json"])

        document = json.loads(out)
        entry = document["local"]["validators"][0]
        retained = (entry["stdout_tail"] or "") + (entry["stderr_tail"] or "")
        self.assertIn("SENTINEL-9c1", retained)
        self.assertIn("\\x1b[2J", retained)
        self.assertNotIn("\x1b", retained)
        self.assert_safe(out, "aiqe receipt --local --format json")

    def test_a_config_refusal_is_safe(self):
        self.build()
        self.start()
        with open(os.path.join(self.repo, "aiqe.toml"), "w") as handle:
            handle.write('schema = 1\n"evil\\u001B[2J" = 1\n')
        status, out, err = self.run_cli(["check"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assert_safe(out + err, "a configuration refusal")

    def test_an_unknown_allow_id_is_echoed_safely(self):
        """The value came from the command line, and still goes to a terminal."""
        self.build()
        self.start()
        status, out, err = self.run_cli(["check", "--allow", "evil\x1b[2J"])
        self.assertEqual(status, exits.UNSUPPORTED)
        self.assert_safe(out + err, "an unknown --allow id")
        self.assertIn("\\x1b[2J", err)


if __name__ == "__main__":
    unittest.main()
