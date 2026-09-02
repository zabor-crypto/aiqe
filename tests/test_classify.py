"""All-matching surface classification, and the coverage arithmetic.

Two properties carry the weight here, and both are asserted directly rather
than inferred from examples:

    declaration order has no effect on classification
    adding a surface can never reduce a quant obligation

Everything else in this module is the coverage table, one row at a time.
"""

import itertools
import unittest

from . import support  # noqa: F401  (sets up sys.path)

from aiqe import classify, validators
from aiqe.config import parse


def config_of(*blocks):
    return parse(("schema = 1\n" + "\n".join(blocks)).encode("utf-8"))


def surface(paths, quant, contracts=None):
    lines = ["[[surface]]", "paths = [%s]" % ", ".join('"%s"' % p for p in paths)]
    lines.append("quant = %s" % ("true" if quant else "false"))
    if contracts:
        lines.append("contracts = [%s]" % ", ".join('"%s"' % c for c in contracts))
    return "\n".join(lines) + "\n"


def validator_block(identifier, required=True, contracts=None, timeout=60):
    lines = [
        "[[validator]]",
        'id = "%s"' % identifier,
        'run = ["./%s"]' % identifier,
        "required = %s" % ("true" if required else "false"),
        "timeout = %d" % timeout,
    ]
    if contracts:
        lines.append("contracts = [%s]" % ", ".join('"%s"' % c for c in contracts))
    return "\n".join(lines) + "\n"


class FakeValidator(object):
    """Enough of a validator to build an `Outcome` without running anything."""

    def __init__(self, identifier, required, contracts):
        self.id = identifier
        self.required = required
        self.contracts = tuple(contracts)


def outcome(identifier, result, required=True, contracts=()):
    return validators.Outcome(
        FakeValidator(identifier, required, contracts), "sha256:x", result
    )


class ClassificationTests(unittest.TestCase):
    def test_no_matching_surface_is_a_classification_gap(self):
        result = classify.classify(
            config_of(surface(["docs/**"], quant=False)), [b"src/alpha.py"]
        )
        self.assertEqual(result.paths[0].kind, classify.UNCLASSIFIED)
        self.assertTrue(result.has_gap)
        self.assertEqual(result.applicable_contracts, ())

    def test_only_quant_surfaces_match(self):
        result = classify.classify(
            config_of(surface(["src/**"], quant=True, contracts=["CAUSALITY"])),
            [b"src/alpha.py"],
        )
        self.assertEqual(result.paths[0].kind, classify.QUANT_SURFACE)
        self.assertEqual(result.applicable_contracts, ("CAUSALITY",))

    def test_only_non_quant_surfaces_match(self):
        result = classify.classify(
            config_of(surface(["src/**"], quant=False)), [b"src/alpha.py"]
        )
        self.assertEqual(result.paths[0].kind, classify.EXPLICIT_NON_QUANT_SURFACE)
        self.assertEqual(result.applicable_contracts, ())

    def test_contracts_union_across_every_matching_quant_surface(self):
        """Not first-match-wins. Every matching declaration contributes."""
        config = config_of(
            surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
            surface(["**/alpha.py"], quant=True, contracts=["DATA_ALIGNMENT"]),
            surface(["src/alpha.py"], quant=True, contracts=["DETERMINISM"]),
        )
        result = classify.classify(config, [b"src/alpha.py"])
        self.assertEqual(
            result.paths[0].contracts,
            ("CAUSALITY", "DATA_ALIGNMENT", "DETERMINISM"),
        )

    def test_a_conflicting_declaration_is_refused(self):
        config = config_of(
            surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
            surface(["**/alpha.py"], quant=False),
        )
        with self.assertRaises(classify.ConfigConflict) as caught:
            classify.classify(config, [b"src/alpha.py"])
        conflict = caught.exception
        self.assertEqual(conflict.path, b"src/alpha.py")
        self.assertEqual(conflict.quant_indices, (0,))
        self.assertEqual(conflict.non_quant_indices, (1,))

    def test_an_unmatched_path_cannot_conflict(self):
        config = config_of(
            surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
            surface(["docs/**"], quant=False),
        )
        result = classify.classify(config, [b"src/alpha.py", b"docs/notes.md"])
        self.assertEqual(
            [entry.kind for entry in result.paths],
            [classify.QUANT_SURFACE, classify.EXPLICIT_NON_QUANT_SURFACE],
        )


class OrderIndependenceTests(unittest.TestCase):
    """Declaration order must have no semantic effect at all."""

    BLOCKS = (
        surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
        surface(["**/alpha.py"], quant=True, contracts=["DATA_ALIGNMENT"]),
        surface(["src/strategy/**"], quant=True, contracts=["ACCOUNTING"]),
        surface(["docs/**"], quant=False),
        surface(["tests/**"], quant=False),
    )

    def test_every_permutation_classifies_identically(self):
        paths = [b"src/strategy/alpha.py", b"docs/notes.md", b"tests/test_a.py"]
        expected = None
        for permutation in itertools.permutations(self.BLOCKS):
            result = classify.classify(config_of(*permutation), paths)
            observed = (
                [(entry.kind, entry.contracts) for entry in result.paths],
                result.applicable_contracts,
            )
            if expected is None:
                expected = observed
            self.assertEqual(observed, expected)

        self.assertEqual(
            expected[1], ("ACCOUNTING", "CAUSALITY", "DATA_ALIGNMENT")
        )

    def test_adding_a_surface_never_reduces_a_quant_obligation(self):
        """The property that makes obligations non-negotiable.

        If a declaration could shrink an obligation, the way to make a check
        pass would be to write another declaration.
        """
        base = surface(["src/**"], quant=True, contracts=["CAUSALITY"])
        before = classify.classify(config_of(base), [b"src/alpha.py"])
        for extra in (
            surface(["**"], quant=True, contracts=["DETERMINISM"]),
            surface(["src/alpha.py"], quant=True, contracts=["ACCOUNTING"]),
            surface(["src/**"], quant=True, contracts=["CAUSALITY"]),
            surface(["nothing/**"], quant=True, contracts=["ACCOUNTING"]),
        ):
            after = classify.classify(config_of(base, extra), [b"src/alpha.py"])
            self.assertTrue(
                set(before.applicable_contracts)
                <= set(after.applicable_contracts),
                extra,
            )


class ApplicabilityTests(unittest.TestCase):
    def test_a_generic_validator_applies_to_every_task(self):
        config = config_of(validator_block("unit"))
        applicable, skipped = classify.applicable_validators(config, ())
        self.assertEqual([v.id for v in applicable], ["unit"])
        self.assertEqual(skipped, ())

    def test_a_contract_validator_applies_only_when_its_contract_does(self):
        config = config_of(validator_block("causality", contracts=["CAUSALITY"]))
        applicable, skipped = classify.applicable_validators(config, ("DETERMINISM",))
        self.assertEqual(applicable, ())
        self.assertEqual([v.id for v in skipped], ["causality"])

        applicable, skipped = classify.applicable_validators(config, ("CAUSALITY",))
        self.assertEqual([v.id for v in applicable], ["causality"])


class CoverageTests(unittest.TestCase):
    def test_zero_required_validators_is_a_coverage_gap(self):
        results = classify.coverage(("CAUSALITY",), [outcome("unit", validators.PASS)])
        self.assertEqual(results[0].state, classify.COVERAGE_GAP)
        self.assertEqual(results[0].required_validator_ids, ())

    def test_an_optional_validator_never_satisfies_coverage(self):
        """A signal is not a guarantee, however green it is."""
        results = classify.coverage(
            ("CAUSALITY",),
            [
                outcome("unit", validators.PASS),
                outcome(
                    "causality",
                    validators.PASS,
                    required=False,
                    contracts=("CAUSALITY",),
                ),
            ],
        )
        self.assertEqual(results[0].state, classify.COVERAGE_GAP)

    def test_a_generic_pass_never_covers_a_quant_contract(self):
        results = classify.coverage(
            ("CAUSALITY", "DETERMINISM"),
            [outcome("unit", validators.PASS)],
        )
        self.assertEqual(
            [entry.state for entry in results],
            [classify.COVERAGE_GAP, classify.COVERAGE_GAP],
        )

    def test_all_required_pass_is_covered(self):
        results = classify.coverage(
            ("CAUSALITY",),
            [outcome("causality", validators.PASS, contracts=("CAUSALITY",))],
        )
        self.assertEqual(results[0].state, classify.COVERED)
        self.assertEqual(results[0].required_validator_ids, ("causality",))

    def test_any_required_failure_fails_the_contract(self):
        results = classify.coverage(
            ("CAUSALITY",),
            [
                outcome("a", validators.PASS, contracts=("CAUSALITY",)),
                outcome("b", validators.FAIL, contracts=("CAUSALITY",)),
            ],
        )
        self.assertEqual(results[0].state, classify.CONTRACT_FAILED)

    def test_a_failure_outranks_an_unknown(self):
        results = classify.coverage(
            ("CAUSALITY",),
            [
                outcome("a", validators.UNKNOWN, contracts=("CAUSALITY",)),
                outcome("b", validators.FAIL, contracts=("CAUSALITY",)),
            ],
        )
        self.assertEqual(results[0].state, classify.CONTRACT_FAILED)

    def test_unknown_and_unavailable_are_contract_unknown(self):
        for result in (validators.UNKNOWN, validators.UNAVAILABLE):
            results = classify.coverage(
                ("CAUSALITY",),
                [
                    outcome("a", validators.PASS, contracts=("CAUSALITY",)),
                    outcome("b", result, contracts=("CAUSALITY",)),
                ],
            )
            self.assertEqual(results[0].state, classify.CONTRACT_UNKNOWN, result)

    def test_counts(self):
        results = classify.coverage(
            ("A", "B"),
            [outcome("a", validators.PASS, contracts=("A",))],
        )
        counts = classify.coverage_counts(results)
        self.assertEqual(counts[classify.COVERED], 1)
        self.assertEqual(counts[classify.COVERAGE_GAP], 1)


if __name__ == "__main__":
    unittest.main()
