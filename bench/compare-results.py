#!/usr/bin/env python3
"""Compare a fresh benchmark run against the retained result artifact.

    python3 bench/compare-results.py <fresh-results.json>

The fresh run names its own family, and is compared against that family's
retained artifact.

The comparison is on headline numbers, not bytes. The artifact records the Git
version the run observed, and the rendered Doctor output quotes it, so two
correct machines legitimately produce different bytes. What may not differ is
how many cases there were, how many failed, how many negative controls
reproduced their failure, and whether every zero-tolerance total is zero.

A `diagnostics` section, at document level or inside a case, is stripped
before anything is compared. It holds measurements that two correct runs
legitimately disagree about, and it is named rather than merely unread so that
the exclusion is a decision instead of an oversight.

Platform-restricted cases are compared only where both runs actually ran them.
A case the retained run skipped and this run executed is a case gaining
coverage, which is not a disagreement - but a case that ran in both and
disagreed is.

Exit status is 0 when the fresh run agrees with the retained artifact, and 1
otherwise.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

#: Which retained artifact a fresh run should be compared against. The fresh
#: run names its own family, so the caller does not have to.
RETAINED_BY_FAMILY = {
    "DOCTOR_FIRST_CONTACT": os.path.join(HERE, "results", "doctor", "results.json"),
    "TASK_SCOPE_CORE": os.path.join(HERE, "results", "task", "results.json"),
    "CHECK_RECEIPT_EVIDENCE": os.path.join(HERE, "results", "check", "results.json"),
    "BOUNDED_COMMIT": os.path.join(HERE, "results", "commit", "results.json"),
}

#: Sections a result document carries for a reader, and that no comparison may
#: consult. A quantity lands here when two *correct* runs legitimately disagree
#: about it.
#:
#: `diagnostics.aiqe_commit_git_writes` is the reason this exists. Several
#: bounded-commit cases race a concurrent process against AIQE's own window on
#: purpose, and Git writes a different number of objects, lock files and reflog
#: entries depending on how the race lands - 292 and 295 were observed on one
#: machine minutes apart. Comparing it would make a correct family flaky, and
#: quietly dropping it would lose a real measurement, so it is recorded and
#: named unauthoritative instead.
#:
#: The stable fact underneath it - whether a case's completion commit wrote
#: through Git at all - is kept in the authoritative record as
#: `aiqe_commit_git_writes_observed`, and that one is compared like anything
#: else.
NON_AUTHORITATIVE_KEYS = ("diagnostics",)


def authoritative(document):
    """The part of a result document that carries authority.

    Applied to the whole document and to every case record, so that a
    diagnostics section cannot re-enter the comparison by being nested one
    level deeper than somebody remembered to check.
    """
    stripped = {
        key: value
        for key, value in document.items()
        if key not in NON_AUTHORITATIVE_KEYS
    }
    if isinstance(stripped.get("cases"), list):
        stripped["cases"] = [
            {
                key: value
                for key, value in case.items()
                if key not in NON_AUTHORITATIVE_KEYS
            }
            for case in stripped["cases"]
        ]
    return stripped


#: Numbers that must agree between any two correct runs, on any platform.
#: `cases_passed` is deliberately absent: it legitimately differs when one run
#: could execute a platform-restricted case and the other could not.
HEADLINE_FIELDS = (
    "cases_total",
    "cases_failed",
    "negative_controls_total",
    "negative_controls_reproducing",
)


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: compare-results.py <fresh-results.json>\n")
        return 2

    with open(argv[0]) as handle:
        fresh = authoritative(json.load(handle))

    family = fresh.get("family")
    if family not in RETAINED_BY_FAMILY:
        sys.stderr.write(
            "unknown benchmark family %r; known families: %s\n"
            % (family, sorted(RETAINED_BY_FAMILY))
        )
        return 2
    with open(RETAINED_BY_FAMILY[family]) as handle:
        retained = authoritative(json.load(handle))

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
        retained_outcome = retained_cases.get(case)
        if outcome == retained_outcome:
            continue
        if "SKIPPED_PLATFORM" in (outcome, retained_outcome) and "FAIL" not in (
            outcome,
            retained_outcome,
        ):
            # One machine could run the case and the other could not. That is
            # a platform difference, not a disagreement about behaviour.
            continue
        problems.append("%s: retained %r, fresh %r" % (case, retained_outcome, outcome))

    if problems:
        sys.stdout.write("Retained %s results disagree with a fresh run:\n" % (family,))
        for problem in problems:
            sys.stdout.write("  " + problem + "\n")
        return 1

    sys.stdout.write("Retained %s results agree with a fresh run.\n" % (family,))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
