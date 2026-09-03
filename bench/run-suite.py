#!/usr/bin/env python3
"""Run the unit suite and record what ran, where, and what was skipped.

    python3 bench/run-suite.py --output suite-surface.json

`python -m unittest` is the ordinary way to run this suite and stays that way.
This runner exists for one reason the plain command cannot serve: a support
claim needs the counts and the environment identity as data, not as a line of
console output that a human reads once and a matrix then generalises from.

Every skip is recorded by name. A skipped case is not a pass, and the only way
to keep that true across a matrix is to make the skips visible in the evidence
rather than in a scrollback buffer.

Exit status is 0 when the suite passed, and 1 otherwise.
"""

import argparse
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from release import environment  # noqa: E402


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-directory", default=os.path.join(ROOT, "tests"))
    parser.add_argument("--verbose", action="store_true")
    options = parser.parse_args(argv)

    started = time.time()
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=options.start_directory, top_level_dir=ROOT)
    # Straight to stdout, unbuffered from this side. A suite that takes a
    # quarter of an hour and prints nothing until it finishes is
    # indistinguishable from a hung job, and a CI log that only appears at the
    # end is no use while deciding whether to cancel one.
    runner = unittest.TextTestRunner(
        stream=sys.stdout, verbosity=2 if options.verbose else 1
    )
    result = runner.run(suite)
    sys.stdout.flush()

    failures = [str(case) for case, _ in result.failures]
    errors = [str(case) for case, _ in result.errors]
    skipped = [
        {"test": str(case), "reason": reason} for case, reason in result.skipped
    ]
    unexpected = [str(case) for case in result.unexpectedSuccesses]

    record = {
        "schema_version": 1,
        "record_type": "RELEASE_PROOF_SURFACE",
        "level": environment.FULL_SUITE,
        "parts_requested": ["suite"],
        "parts_run": ["suite"],
        "parts_not_run": [],
        "tests_run": result.testsRun,
        "tests_failed": len(failures),
        "tests_errored": len(errors),
        "tests_skipped": len(skipped),
        "tests_unexpected_success": len(unexpected),
        "failures": failures,
        "errors": errors,
        "skips": skipped,
        "unexpected_successes": unexpected,
        "duration_seconds": round(time.time() - started, 1),
    }
    record.update(environment.describe(ROOT))
    record["totals"] = {
        "tests_failed": len(failures),
        "tests_errored": len(errors),
        "tests_unexpected_success": len(unexpected),
    }
    record["problems"] = (
        ["%d failing tests" % len(failures)] if failures else []
    ) + (["%d erroring tests" % len(errors)] if errors else [])
    record["outcome"] = "PASS" if result.wasSuccessful() else "FAIL"

    with open(options.output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")

    sys.stdout.write(
        "suite %s on %s %s / %s / python %s / %s\n"
        % (
            record["outcome"],
            record["os_family"],
            record["os_release"],
            record["arch"],
            record["python_version"],
            record["git_version"],
        )
    )
    sys.stdout.write(
        "  %d run · %d failed · %d errored · %d skipped\n"
        % (record["tests_run"], record["tests_failed"], record["tests_errored"], record["tests_skipped"])
    )
    for skip in skipped:
        sys.stdout.write("  SKIP  %s  (%s)\n" % (skip["test"], skip["reason"]))
    sys.stdout.write("  wrote %s\n" % (options.output,))
    return 0 if record["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
