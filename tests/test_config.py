"""`aiqe.toml`, and the refusals that make it trustworthy.

Almost every test here is about something the parser will *not* do. That is
the point of a fail-closed reader: a permissive one turns `requred = true`
into an optional validator and never says a word, and the result is a green
check that means nothing.
"""

import os
import shutil
import tempfile
import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import config
from aiqe.config import ConfigError, parse

VALID = b"""schema = 1

[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY", "DATA_ALIGNMENT"]

[[surface]]
paths = ["tests/**", "docs/**"]
quant = false

[[validator]]
id = "unit"
run = ["pytest", "-q", "tests/unit"]
required = true
timeout = 300

[[validator]]
id = "causality"
run = ["python", "checks/no_lookahead.py"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
"""


class ValidConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = parse(VALID)

    def test_schema_and_block_counts(self):
        self.assertEqual(self.config.schema, 1)
        self.assertEqual(len(self.config.surfaces), 2)
        self.assertEqual(len(self.config.validators), 2)

    def test_surfaces_keep_their_declaration_index(self):
        """The index is for messages, never for precedence."""
        self.assertEqual([s.index for s in self.config.surfaces], [0, 1])

    def test_contracts_are_sorted_and_the_quant_flag_is_kept(self):
        first = self.config.surfaces[0]
        self.assertTrue(first.quant)
        self.assertEqual(first.contracts, ("CAUSALITY", "DATA_ALIGNMENT"))
        self.assertFalse(self.config.surfaces[1].quant)
        self.assertEqual(self.config.surfaces[1].contracts, ())

    def test_validator_fields(self):
        unit = self.config.validator("unit")
        self.assertEqual(unit.argv, ("pytest", "-q", "tests/unit"))
        self.assertTrue(unit.required)
        self.assertEqual(unit.timeout, 300)
        self.assertTrue(unit.generic)
        self.assertFalse(self.config.validator("causality").generic)

    def test_patterns_are_compiled_and_match_bytes(self):
        self.assertTrue(self.config.surfaces[0].matches(b"src/strategy/alpha.py"))
        self.assertFalse(self.config.surfaces[0].matches(b"src/other.py"))


class DigestTests(unittest.TestCase):
    def test_the_digest_is_over_raw_bytes(self):
        """A comment change must change the digest.

        Staleness is conservative on purpose: if the file a check ran against
        is not byte-identical to the file the reader is looking at, the
        evidence does not describe that file.
        """
        commented = VALID + b"\n# why this validator is required\n"
        self.assertNotEqual(parse(VALID).digest, parse(commented).digest)

    def test_the_digest_is_stable(self):
        self.assertEqual(parse(VALID).digest, parse(VALID).digest)

    def test_the_digest_is_domain_separated(self):
        import hashlib

        plain = "sha256:" + hashlib.sha256(VALID).hexdigest()
        self.assertNotEqual(parse(VALID).digest, plain)


class RefusalTests(unittest.TestCase):
    def refusal(self, raw):
        with self.assertRaises(ConfigError, msg=raw) as caught:
            parse(raw)
        return caught.exception.code

    def test_missing_schema(self):
        self.assertEqual(self.refusal(b"[[surface]]\n"), config.CONFIG_SCHEMA_MISSING)

    def test_unsupported_schema(self):
        for raw in (b"schema = 2\n", b'schema = "1"\n', b"schema = true\n"):
            self.assertEqual(self.refusal(raw), config.CONFIG_SCHEMA_UNSUPPORTED, raw)

    def test_malformed_toml(self):
        self.assertEqual(self.refusal(b"schema = \n"), config.CONFIG_MALFORMED)

    def test_non_utf8_bytes(self):
        self.assertEqual(self.refusal(b"schema = 1\n\xff\xfe"), config.CONFIG_MALFORMED)

    def test_unknown_top_level_field(self):
        self.assertEqual(
            self.refusal(b"schema = 1\nstrict = true\n"), config.CONFIG_UNKNOWN_FIELD
        )

    def test_unknown_surface_field(self):
        raw = b'schema = 1\n[[surface]]\npaths = ["a"]\nquant = false\nexclude = ["b"]\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_UNKNOWN_FIELD)

    def test_unknown_validator_field(self):
        """A misspelled `required` must not silently become optional."""
        raw = (
            b'schema = 1\n[[validator]]\nid = "unit"\nrun = ["x"]\n'
            b"required = true\ntimeout = 5\nrequred = false\n"
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_UNKNOWN_FIELD)

    def test_surface_paths_must_be_a_non_empty_array(self):
        for raw in (
            b"schema = 1\n[[surface]]\nquant = false\n",
            b"schema = 1\n[[surface]]\npaths = []\nquant = false\n",
            b'schema = 1\n[[surface]]\npaths = "src"\nquant = false\n',
            b"schema = 1\n[[surface]]\npaths = [3]\nquant = false\n",
        ):
            self.assertEqual(self.refusal(raw), config.CONFIG_SURFACE_PATHS_INVALID, raw)

    def test_invalid_surface_pattern(self):
        raw = b'schema = 1\n[[surface]]\npaths = ["/src/**"]\nquant = false\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_SURFACE_PATTERN_INVALID)

    def test_quant_is_never_inferred(self):
        """Absence of evidence is not evidence of ordinary code."""
        raw = b'schema = 1\n[[surface]]\npaths = ["src/**"]\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_SURFACE_QUANT_INVALID)

    def test_quant_must_be_a_boolean(self):
        raw = b'schema = 1\n[[surface]]\npaths = ["src/**"]\nquant = "yes"\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_SURFACE_QUANT_INVALID)

    def test_quant_surface_needs_at_least_one_contract(self):
        raw = b'schema = 1\n[[surface]]\npaths = ["src/**"]\nquant = true\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_QUANT_WITHOUT_CONTRACTS)

    def test_non_quant_surface_may_not_carry_contracts(self):
        raw = (
            b'schema = 1\n[[surface]]\npaths = ["src/**"]\nquant = false\n'
            b'contracts = ["CAUSALITY"]\n'
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_NON_QUANT_WITH_CONTRACTS)

    def test_contract_identifier_shape(self):
        for name in (b'"causality"', b'"Causality"', b'"DATA-ALIGNMENT"', b"3", b'""'):
            raw = (
                b'schema = 1\n[[surface]]\npaths = ["src/**"]\nquant = true\n'
                b"contracts = [" + name + b"]\n"
            )
            self.assertEqual(self.refusal(raw), config.CONFIG_CONTRACT_INVALID, name)

    def test_duplicate_contract(self):
        raw = (
            b'schema = 1\n[[surface]]\npaths = ["src/**"]\nquant = true\n'
            b'contracts = ["CAUSALITY", "CAUSALITY"]\n'
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_CONTRACT_INVALID)

    def test_duplicate_validator_id(self):
        raw = (
            b'schema = 1\n[[validator]]\nid = "unit"\nrun = ["a"]\nrequired = true\n'
            b'timeout = 5\n[[validator]]\nid = "unit"\nrun = ["b"]\nrequired = true\n'
            b"timeout = 5\n"
        )
        self.assertEqual(self.refusal(raw), config.CONFIG_VALIDATOR_ID_DUPLICATE)

    def test_validator_id_shape(self):
        for identifier in (b'""', b'"unit suite"', b'"unit/suite"', b"3"):
            raw = (
                b"schema = 1\n[[validator]]\nid = " + identifier + b"\n"
                b'run = ["a"]\nrequired = true\ntimeout = 5\n'
            )
            self.assertEqual(
                self.refusal(raw), config.CONFIG_VALIDATOR_ID_INVALID, identifier
            )

    def test_empty_or_malformed_argv(self):
        for run in (b"[]", b'"pytest -q"', b'[""]', b"[3]"):
            raw = (
                b'schema = 1\n[[validator]]\nid = "unit"\nrun = ' + run + b"\n"
                b"required = true\ntimeout = 5\n"
            )
            self.assertEqual(
                self.refusal(raw), config.CONFIG_VALIDATOR_ARGV_INVALID, run
            )

    def test_missing_argv(self):
        raw = b'schema = 1\n[[validator]]\nid = "unit"\nrequired = true\ntimeout = 5\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_VALIDATOR_ARGV_INVALID)

    def test_required_is_never_defaulted(self):
        raw = b'schema = 1\n[[validator]]\nid = "unit"\nrun = ["a"]\ntimeout = 5\n'
        self.assertEqual(self.refusal(raw), config.CONFIG_VALIDATOR_REQUIRED_INVALID)

    def test_timeout_is_mandatory_and_bounded(self):
        base = b'schema = 1\n[[validator]]\nid = "unit"\nrun = ["a"]\nrequired = true\n'
        self.assertEqual(
            self.refusal(base), config.CONFIG_VALIDATOR_TIMEOUT_INVALID
        )
        for timeout in (b"0", b"-1", b"true", b'"300"', b"1.5", b"999999999"):
            self.assertEqual(
                self.refusal(base + b"timeout = " + timeout + b"\n"),
                config.CONFIG_VALIDATOR_TIMEOUT_INVALID,
                timeout,
            )

    def test_blocks_must_be_arrays_of_tables(self):
        for raw in (b"schema = 1\nsurface = 3\n", b"schema = 1\nvalidator = 3\n"):
            self.assertEqual(self.refusal(raw), config.CONFIG_BLOCK_MALFORMED, raw)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="aiqe-config-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.worktree = os.fsencode(self.root)

    def path(self):
        return os.path.join(self.root, "aiqe.toml")

    def test_absent_configuration(self):
        self.assertFalse(config.present(self.worktree))
        with self.assertRaises(ConfigError) as caught:
            config.load(self.worktree)
        self.assertEqual(caught.exception.code, config.CONFIG_ABSENT)

    def test_a_symlinked_configuration_is_refused(self):
        """The configuration in force must be in the repository.

        Following a link would make the classification rules depend on
        something outside it, which is exactly the ambiguity a fail-closed
        reader exists to refuse.
        """
        elsewhere = os.path.join(self.root, "elsewhere.toml")
        with open(elsewhere, "wb") as handle:
            handle.write(VALID)
        os.symlink(elsewhere, self.path())

        self.assertFalse(config.present(self.worktree))
        with self.assertRaises(ConfigError) as caught:
            config.load(self.worktree)
        self.assertEqual(caught.exception.code, config.CONFIG_NOT_A_REGULAR_FILE)

    def test_a_directory_is_refused(self):
        os.mkdir(self.path())
        with self.assertRaises(ConfigError) as caught:
            config.load(self.worktree)
        self.assertEqual(caught.exception.code, config.CONFIG_NOT_A_REGULAR_FILE)

    def test_a_regular_file_loads(self):
        with open(self.path(), "wb") as handle:
            handle.write(VALID)
        self.assertTrue(config.present(self.worktree))
        self.assertEqual(config.load(self.worktree).schema, 1)


if __name__ == "__main__":
    unittest.main()
