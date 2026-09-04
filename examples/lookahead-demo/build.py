"""Build the lookahead demo's synthetic repository, from nothing.

Every byte of the demonstration repository is written here. There is no
private data, no real strategy, no download and no network access, and the
price series is produced by an integer linear congruential generator so that
two machines see the same numbers rather than two floating-point roundings of
them.

The repository is deliberately ordinary: a strategy module, a generic test
suite that a real project would already have, two validator scripts, and an
`aiqe.toml`. The only unusual thing about it is one character.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

if os.path.join(ROOT, "bench") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "bench"))

from fixtures.repobuild import commit_all, git, init_repo, write  # noqa: E402


#: The correct decision lag: a decision made at bar `i` reads bar `i - 1`.
CORRECT_LAG = 1

#: The defect: the decision reads the bar it is made on.
DEFECTIVE_LAG = 0


STRATEGY = '''"""A synthetic momentum strategy over a deterministic price series.

This is not a real strategy and its numbers mean nothing. It exists so that a
causality defect can be demonstrated without private data, a network, or a
floating-point difference between two machines.
"""

#: Which bar a decision is allowed to read.
#:
#: A decision made at bar `i` may only use bars strictly earlier than `i`, so
#: this must be 1. At 0 the decision reads the bar it is made on, and a price
#: that had not printed yet reaches back into a signal that was already taken.
#: That single character is the whole defect.
DECISION_LAG = %(lag)d

#: How far back the comparison reaches.
WINDOW = %(window)d


def series(count=64, seed=20260904):
    """A deterministic integer price series. No floats and no entropy source."""
    state = seed
    price = 100000
    prices = []
    for _ in range(count):
        state = (1103515245 * state + 12345) %% 2147483648
        price += (state %% 401) - 200
        prices.append(price)
    return prices


def signals(prices):
    """1 where the window rose, 0 otherwise, decided bar by bar."""
    out = []
    for index in range(len(prices)):
        recent = index - DECISION_LAG
        earlier = recent - WINDOW
        if earlier < 0:
            out.append(0)
            continue
        out.append(1 if prices[recent] > prices[earlier] else 0)
    return out
'''


#: The generic suite a project of this shape would already have. It asserts
#: shape, determinism, warm-up and a monotone response - all true things, and
#: all of them true whichever value `DECISION_LAG` holds.
GENERIC_TESTS = '''import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from strategy.momentum import series, signals


class MomentumTests(unittest.TestCase):
    def test_one_signal_per_bar(self):
        prices = series()
        self.assertEqual(len(signals(prices)), len(prices))

    def test_signals_are_binary(self):
        self.assertEqual(set(signals(series())) - {0, 1}, set())

    def test_the_series_is_deterministic(self):
        self.assertEqual(series(), series())

    def test_a_rising_ramp_is_long(self):
        ramp = [100 + step for step in range(32)]
        self.assertEqual(signals(ramp)[-1], 1)

    def test_a_falling_ramp_is_flat(self):
        ramp = [100 - step for step in range(32)]
        self.assertEqual(signals(ramp)[-1], 0)


if __name__ == "__main__":
    unittest.main()
'''


#: The check nobody writes. It asks the one question the generic suite does
#: not: can a bar change a decision that was made before it existed?
CAUSALITY_PROBE = '''"""Perturb one bar and prove no earlier decision moved.

A decision taken at bar `k` may depend on bars before `k`. It may not depend
on bar `k` itself, and it certainly may not depend on anything after it. So:
raise one bar by a large amount, recompute, and compare every decision from
bar 0 through bar `k`. If any of them moved, information travelled backwards.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from strategy.momentum import series, signals

SHOCK = 10000


def main():
    prices = series()
    baseline = signals(prices)
    violations = []

    for bar in range(len(prices)):
        perturbed = list(prices)
        perturbed[bar] += SHOCK
        moved = signals(perturbed)
        if moved[: bar + 1] != baseline[: bar + 1]:
            violations.append(bar)

    if violations:
        sys.stdout.write(
            "CAUSALITY VIOLATION: perturbing a bar moved a decision taken at "
            "or before it, at %d of %d bars (first: bar %d)\\n"
            % (len(violations), len(prices), violations[0])
        )
        return 1

    sys.stdout.write(
        "no decision at or before a perturbed bar moved, across %d bars\\n"
        % (len(prices),)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


#: Bytecode is a cache, and a cache is a way for a check to answer about
#: source it never read. Both validators refuse to write or use one.
UNIT_VALIDATOR = """#!/bin/sh
set -eu
exec python3 -B -E -m unittest discover --start-directory tests --quiet
"""

CAUSALITY_VALIDATOR = """#!/bin/sh
set -eu
exec python3 -B -E checks/causality_probe.py
"""


QUANT_SURFACE = '''[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY"]
'''

ORDINARY_SURFACE = '''[[surface]]
paths = ["tests/**", "checks/**", "docs/**", "src/foreign.py", "aiqe.toml"]
quant = false
'''

UNIT_DECLARATION = '''[[validator]]
id = "unit"
run = ["./checks/unit.sh"]
required = true
timeout = 120
'''

CAUSALITY_DECLARATION = '''[[validator]]
id = "causality"
run = ["./checks/causality.sh"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
'''


def configuration(causality_declared=True):
    blocks = [QUANT_SURFACE, ORDINARY_SURFACE, UNIT_DECLARATION]
    if causality_declared:
        blocks.append(CAUSALITY_DECLARATION)
    return "schema = 1\n\n" + "\n".join(blocks)


#: The window the baseline commit is made with.
BASELINE_WINDOW = 3


def strategy(lag, window=BASELINE_WINDOW):
    return STRATEGY % {"lag": lag, "window": window}


def build(root, env, causality_declared=True):
    """Write the repository and make its one baseline commit.

    The baseline is correct: `DECISION_LAG` is 1 and the causality probe holds
    on it. Every act below starts from that commit and makes its own change,
    which is what an agent editing the repository actually does. Nothing here
    runs AIQE.
    """
    init_repo(root, env)
    write(
        os.path.join(root, "src", "strategy", "momentum.py"),
        strategy(CORRECT_LAG),
    )
    write(os.path.join(root, "src", "foreign.py"), "UNRELATED = 1\n")
    write(os.path.join(root, "tests", "test_momentum.py"), GENERIC_TESTS)
    write(os.path.join(root, "checks", "causality_probe.py"), CAUSALITY_PROBE)
    write(os.path.join(root, "checks", "unit.sh"), UNIT_VALIDATOR, mode=0o755)
    write(
        os.path.join(root, "checks", "causality.sh"),
        CAUSALITY_VALIDATOR,
        mode=0o755,
    )
    write(os.path.join(root, "docs", "notes.md"), "Synthetic demonstration.\n")
    write(
        os.path.join(root, "aiqe.toml"),
        configuration(causality_declared=causality_declared),
    )
    commit_all(root, "synthetic baseline", env)
    return root


def edit_strategy(root, lag=CORRECT_LAG, window=BASELINE_WINDOW):
    """Rewrite the owned path in the worktree, without committing it.

    `lag=DEFECTIVE_LAG` is the one-character defect. Changing `window`
    instead is an ordinary correct change: it alters the numbers and violates
    nothing.
    """
    write(
        os.path.join(root, "src", "strategy", "momentum.py"),
        strategy(lag, window),
    )


def stage_unrelated_work(root, env):
    """Put work nobody declared into the index, the way a working day does."""
    write(os.path.join(root, "src", "foreign.py"), "UNRELATED = 2\n")
    git(root, "add", "src/foreign.py", env=env)
