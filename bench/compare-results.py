#!/usr/bin/env python3
"""Compare a fresh benchmark run against the retained result artifact.

    python3 bench/compare-results.py <fresh-results.json>

The comparison is on headline numbers, not bytes. The artifact records the Git
version the run observed, and the rendered Doctor output quotes it, so two
correct machines legitimately produce different bytes. What may not differ is
how many cases there were, how many passed, how many negative controls
reproduced their failure, and whether every zero-tolerance total is zero.

Exit status is 0 when the fresh run agrees with the retained artifact, and 1
otherwise.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RETAINED = os.path.join(HERE, "results", "doctor", "results.json")

HEADLINE_FIELDS = (
    "cases_total",
    "cases_passed",
    "cases_failed",
    "negative_controls_total",
    "negative_controls_reproducing",
)


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: compare-results.py <fresh-results.json>\n")
        return 2

    with open(argv[0]) as handle:
        fresh = json.load(handle)
    with open(RETAINED) as handle:
        retained = json.load(handle)

    problems = [
        "%s: retained %r, fresh %r" % (field, retained[field], fresh[field])
        for field in HEADLINE_FIELDS
        if retained[field] != fresh[field]
    ]
    for key, value in sorted(fresh["totals"].items()):
        if value != 0:
            problems.append("zero-tolerance total %s is %r, expected 0" % (key, value))

    fresh_cases = {case["case"]: case["outcome"] for case in fresh["cases"]}
    retained_cases = {case["case"]: case["outcome"] for case in retained["cases"]}
    if set(fresh_cases) != set(retained_cases):
        problems.append(
            "case set differs: only retained %s, only fresh %s"
            % (
                sorted(set(retained_cases) - set(fresh_cases)),
                sorted(set(fresh_cases) - set(retained_cases)),
            )
        )
    for case, outcome in sorted(fresh_cases.items()):
        if outcome != retained_cases.get(case):
            problems.append(
                "%s: retained %r, fresh %r" % (case, retained_cases.get(case), outcome)
            )

    if problems:
        sys.stdout.write("Retained Doctor results disagree with a fresh run:\n")
        for problem in problems:
            sys.stdout.write("  " + problem + "\n")
        return 1

    sys.stdout.write("Retained Doctor results agree with a fresh run.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
