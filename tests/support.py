"""Shared test wiring.

The benchmark fixture builders and the measurement harnesses are the retained
artifact under `bench/`, and the tests import them rather than keeping a
second, drifting copy. A fixture the test suite and the benchmark disagreed
about would make both worthless.
"""

import os
import sys

TESTS_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIRECTORY)
SOURCE = os.path.join(ROOT, "src")
BENCH = os.path.join(ROOT, "bench")

for path in (SOURCE, BENCH):
    if path not in sys.path:
        sys.path.insert(0, path)

from fixtures import measurement  # noqa: E402,F401
from fixtures.doctor import builders, controls, harness  # noqa: E402,F401
from fixtures.task import builders as task_builders  # noqa: E402,F401
from fixtures.task import controls as task_controls  # noqa: E402,F401
from fixtures.task import harness as task_harness  # noqa: E402,F401
from fixtures.check import builders as check_builders  # noqa: E402,F401
from fixtures.check import controls as check_controls  # noqa: E402,F401
from fixtures.check import harness as check_harness  # noqa: E402,F401


def cases():
    return harness.load_cases()["cases"]


def case_ids():
    return [case["id"] for case in cases()]


def task_cases():
    return task_harness.load_cases()["cases"]


def task_case_ids():
    return [case["id"] for case in task_cases()]


def check_cases():
    return check_harness.load_cases()["cases"]


def check_case_ids():
    return [case["id"] for case in check_cases()]
