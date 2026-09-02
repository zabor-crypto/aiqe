"""The quant contract families that ship at launch.

A contract is an obligation a surface carries. `[[surface]]` declares which
contracts apply to a set of paths; `[[validator]]` declares which contracts a
validator discharges. Nothing here knows how to detect a defect - AIQE runs
the repository's own validators and reports what they said. What this registry
supplies is the vocabulary, so that "which contracts apply here" and "which
contracts is anything actually checking" are questions with a stable answer.

Six umbrella families ship at launch. They are umbrellas on purpose: a
detailed sub-taxonomy would be a claim about how a defect must be detected,
and AIQE does not detect defects.

    CAUSALITY              future information reaches a decision made before
                           it existed
    DATA_ALIGNMENT         series are joined on mismatched indices or
                           timestamps
    EXECUTION_REALISM      fills assume prices or liquidity that were not
                           available
    ACCOUNTING             positions, cash and PnL fail to reconcile
    TRAIN_TEST_SEPARATION  evaluation data informed fitting
    DETERMINISM            identical inputs produce different results across
                           runs

Custom contract identifiers remain legal. A repository with an obligation
these six do not name should say so in its own words rather than misfile it
under one of them, and AIQE treats a custom identifier exactly like a launch
one: it applies where a surface declares it, and it is covered only by a
required validator that declares it too.

The identifier grammar is deliberately narrow - upper-case ASCII, digits and
underscores, beginning with a letter - so that a contract identifier reads as
one in every rendering, and so that a typo is a configuration error rather
than a silently distinct contract.
"""

CAUSALITY = "CAUSALITY"
DATA_ALIGNMENT = "DATA_ALIGNMENT"
EXECUTION_REALISM = "EXECUTION_REALISM"
ACCOUNTING = "ACCOUNTING"
TRAIN_TEST_SEPARATION = "TRAIN_TEST_SEPARATION"
DETERMINISM = "DETERMINISM"

#: The launch families, in their canonical order. The order is presentation
#: only: nothing in classification or coverage depends on it.
LAUNCH_CONTRACTS = (
    CAUSALITY,
    DATA_ALIGNMENT,
    EXECUTION_REALISM,
    ACCOUNTING,
    TRAIN_TEST_SEPARATION,
    DETERMINISM,
)

#: One line each, for `aiqe check` output and the reference documentation.
DESCRIPTIONS = {
    CAUSALITY: "future information reaches a decision made before it existed",
    DATA_ALIGNMENT: "series joined on mismatched indices or timestamps",
    EXECUTION_REALISM: "fills assume prices or liquidity that were not available",
    ACCOUNTING: "positions, cash and PnL fail to reconcile",
    TRAIN_TEST_SEPARATION: "evaluation data informed fitting",
    DETERMINISM: "identical inputs produce different results across runs",
}


def is_launch_contract(identifier):
    return identifier in LAUNCH_CONTRACTS


def is_valid_identifier(identifier):
    """Does this string have the shape of a contract identifier?

    Upper-case ASCII letters, digits and underscores, starting with a letter.
    Narrow on purpose: a lower-case or hyphenated spelling of a launch family
    is a typo, and a typo that silently became a custom contract nothing
    covers would report a coverage gap the author could not explain.
    """
    if not isinstance(identifier, str) or not identifier:
        return False
    if not ("A" <= identifier[0] <= "Z"):
        return False
    for character in identifier:
        if "A" <= character <= "Z" or "0" <= character <= "9" or character == "_":
            continue
        return False
    return True
