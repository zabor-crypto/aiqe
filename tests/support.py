"""Shared test wiring.

The benchmark fixture builders and the measurement harness are the retained
artifact under `bench/`, and the tests import them rather than keeping a
second, drifting copy. A fixture that the test suite and the benchmark
disagree about would make both worthless.
"""

import os
import sys

TESTS_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIRECTORY)
SOURCE = os.path.join(ROOT, "src")
FIXTURES = os.path.join(ROOT, "bench", "fixtures", "doctor")

for path in (SOURCE, FIXTURES):
    if path not in sys.path:
        sys.path.insert(0, path)

import builders  # noqa: E402,F401
import controls  # noqa: E402,F401
import harness  # noqa: E402,F401


def cases():
    return harness.load_cases()["cases"]


def case_ids():
    return [case["id"] for case in cases()]
