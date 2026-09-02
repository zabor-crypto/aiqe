"""Surface classification, and the coverage arithmetic it feeds.

Two questions, in order.

**Which surface is this changed path on?** Every `[[surface]]` declaration that
matches is evaluated - never the first one that matches. First-match-wins
would make the answer depend on declaration order, and a reader who moved a
block to group it with its neighbours would silently change which contracts
apply to a strategy file. So:

```
no surface matches
    UNCLASSIFIED -> CLASSIFICATION_GAP -> INCOMPLETE

only quant = true surfaces match
    QUANT_SURFACE, contracts = the union across every one of them

only quant = false surfaces match
    EXPLICIT_NON_QUANT_SURFACE

both match
    CONFIG_CONFLICT -> exit 3, and no new evidence
```

The union is the direction that cannot be gamed: **adding a surface can never
reduce a quant obligation.** If it could, the way to make a check pass would
be to write another declaration, and an assurance layer whose obligations can
be edited away by adding configuration is decoration.

The conflict case is a refusal rather than a resolution. A path declared both
quant and non-quant means two people believed two different things about the
same file, and any rule for picking a winner - most specific, last declared,
quant wins - would hide that disagreement behind a result. `quant wins` in
particular looks safe and is not: it would produce a green check nobody could
explain from the file they are reading.

**Is anything actually checking it?** For every applicable contract:

```
zero required validators declaring it
    COVERAGE_GAP -> INCOMPLETE

all of them PASS
    COVERED

any of them FAIL
    CONTRACT_FAILED -> NOT_REVIEWABLE

none FAIL, any UNKNOWN or UNAVAILABLE
    CONTRACT_UNKNOWN -> INCOMPLETE
```

`COVERAGE_GAP` is the single most important state in the product. A repository
whose generic test suite passes, whose changed files are on a declared quant
surface, and which has no required validator bound to that surface's contracts
is not passing. It is unmeasured, and it looks exactly like passing to every
other tool. An optional validator never closes the gap, and neither does a
generic validator: a suite that was not written to detect a lookahead defect
does not become evidence about lookahead by succeeding.
"""

from . import validators as validators_module

UNCLASSIFIED = "UNCLASSIFIED"
QUANT_SURFACE = "QUANT_SURFACE"
EXPLICIT_NON_QUANT_SURFACE = "EXPLICIT_NON_QUANT_SURFACE"

CLASSIFICATION_GAP = "CLASSIFICATION_GAP"
CONFIG_CONFLICT = "CONFIG_CONFLICT"

COVERED = "COVERED"
COVERAGE_GAP = "COVERAGE_GAP"
CONTRACT_FAILED = "CONTRACT_FAILED"
CONTRACT_UNKNOWN = "CONTRACT_UNKNOWN"


class ConfigConflict(Exception):
    """A changed owned path is declared both quant and non-quant."""

    code = CONFIG_CONFLICT

    def __init__(self, path, quant_indices, non_quant_indices):
        self.path = path
        self.quant_indices = tuple(quant_indices)
        self.non_quant_indices = tuple(non_quant_indices)
        from .textsafe import display_bytes

        self.message = (
            "%s matches [[surface]] %s, which declares quant = true, and "
            "[[surface]] %s, which declares quant = false. AIQE will not pick "
            "a winner between two declarations that say different things "
            "about the same file."
            % (
                display_bytes(path),
                _positions(self.quant_indices),
                _positions(self.non_quant_indices),
            )
        )
        Exception.__init__(self, self.message)


def _positions(indices):
    return ", ".join("#%d" % (index + 1,) for index in indices)


class PathClassification(object):
    """One changed owned path, and what the configuration says about it."""

    __slots__ = ("path", "kind", "contracts", "surface_indices")

    def __init__(self, path, kind, contracts, surface_indices):
        self.path = path
        self.kind = kind
        self.contracts = contracts
        self.surface_indices = surface_indices

    def as_record(self):
        import base64

        return {
            "path_b64": base64.b64encode(self.path).decode("ascii"),
            "kind": self.kind,
            "contracts": list(self.contracts),
            "surfaces": list(self.surface_indices),
        }


class Classification(object):
    """The classification of every changed owned path."""

    __slots__ = ("paths", "applicable_contracts")

    def __init__(self, paths, applicable_contracts):
        self.paths = paths
        self.applicable_contracts = applicable_contracts

    def count(self, kind):
        return sum(1 for entry in self.paths if entry.kind == kind)

    @property
    def has_gap(self):
        return self.count(UNCLASSIFIED) > 0

    def as_record(self):
        return {
            "paths": [entry.as_record() for entry in self.paths],
            "applicable_contracts": list(self.applicable_contracts),
            "quant_count": self.count(QUANT_SURFACE),
            "non_quant_count": self.count(EXPLICIT_NON_QUANT_SURFACE),
            "unclassified_count": self.count(UNCLASSIFIED),
        }


def classify(config, changed_paths):
    """Classify changed owned paths. Raises `ConfigConflict`.

    `changed_paths` is raw repository-relative bytes, already filtered to the
    paths this task actually changed. Unchanged declarations carry no
    obligation and are not classified.
    """
    entries = []
    applicable = set()

    for path in changed_paths:
        quant_indices = []
        non_quant_indices = []
        contracts = set()

        for surface in config.surfaces:
            if not surface.matches(path):
                continue
            if surface.quant:
                quant_indices.append(surface.index)
                contracts.update(surface.contracts)
            else:
                non_quant_indices.append(surface.index)

        if quant_indices and non_quant_indices:
            raise ConfigConflict(path, quant_indices, non_quant_indices)

        if quant_indices:
            kind = QUANT_SURFACE
            applicable.update(contracts)
            indices = quant_indices
        elif non_quant_indices:
            kind = EXPLICIT_NON_QUANT_SURFACE
            indices = non_quant_indices
        else:
            kind = UNCLASSIFIED
            indices = []

        entries.append(
            PathClassification(path, kind, tuple(sorted(contracts)), tuple(indices))
        )

    return Classification(tuple(entries), tuple(sorted(applicable)))


# --- Applicability ---------------------------------------------------------


def applicable_validators(config, applicable_contracts):
    """Which validators this check is obliged to consider.

    A validator declaring no contract is a generic task validator: it applies
    to every checked task, because it was written about the project rather
    than about a surface. A contract-bound validator applies only when at
    least one contract it declares actually applies here - running a
    causality check against a documentation change is noise, and noise is how
    a check becomes something people skip.
    """
    applicable = []
    skipped = []
    for validator in config.validators:
        if validator.generic:
            applicable.append(validator)
        elif set(validator.contracts) & set(applicable_contracts):
            applicable.append(validator)
        else:
            skipped.append(validator)
    return tuple(applicable), tuple(skipped)


# --- Coverage --------------------------------------------------------------


class ContractCoverage(object):
    """One applicable contract, and what is - or is not - checking it."""

    __slots__ = ("contract", "state", "required_validator_ids")

    def __init__(self, contract, state, required_validator_ids):
        self.contract = contract
        self.state = state
        self.required_validator_ids = required_validator_ids

    def as_record(self):
        return {
            "contract": self.contract,
            "state": self.state,
            "required_validators": list(self.required_validator_ids),
        }


def coverage(applicable_contracts, outcomes):
    """The coverage arithmetic, contract by contract.

    `outcomes` are `validators.Outcome` objects for the applicable validators.
    Optional validators are visible in the output and appear nowhere here: an
    optional validator that passes is a signal, and treating a signal as
    coverage is what turns a warning into a guarantee nobody granted.
    """
    results = []
    for contract in applicable_contracts:
        bound = [
            outcome
            for outcome in outcomes
            if outcome.required and contract in outcome.contracts
        ]
        identifiers = tuple(sorted(outcome.validator_id for outcome in bound))

        if not bound:
            state = COVERAGE_GAP
        elif any(outcome.outcome == validators_module.FAIL for outcome in bound):
            state = CONTRACT_FAILED
        elif any(
            outcome.outcome
            in (validators_module.UNKNOWN, validators_module.UNAVAILABLE)
            for outcome in bound
        ):
            state = CONTRACT_UNKNOWN
        elif all(outcome.outcome == validators_module.PASS for outcome in bound):
            state = COVERED
        else:
            state = CONTRACT_UNKNOWN

        results.append(ContractCoverage(contract, state, identifiers))
    return tuple(results)


def coverage_counts(results):
    counts = {COVERED: 0, COVERAGE_GAP: 0, CONTRACT_FAILED: 0, CONTRACT_UNKNOWN: 0}
    for result in results:
        counts[result.state] += 1
    return counts
