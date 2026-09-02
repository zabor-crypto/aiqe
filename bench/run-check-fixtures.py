#!/usr/bin/env python3
"""Run the check/receipt benchmark family and retain the result artifact.

    python3 bench/run-check-fixtures.py
    python3 bench/run-check-fixtures.py --output /tmp/fresh.json

Builds every case in `bench/fixtures/check/cases.json`, drives the real
command-line entry point against it under the measurement harness, compares
the observation to the recorded expectation, and writes
`bench/results/check/results.json`.

A runner, not a framework: no plugins, no discovery, no reporters. `commit`
does not exist, so its family stays NOT_RUN and is not fabricated here.

Exit status is 0 when every applicable case matched its expectation with every
zero-tolerance quantity at zero and every negative control reproduced its
failure, and 1 otherwise.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

from fixtures.check import controls  # noqa: E402
from fixtures.check import harness  # noqa: E402

RESULTS_FILE = os.path.join(HERE, "results", "check", "results.json")


def main(argv):
    from aiqe import __version__

    output_file = RESULTS_FILE
    if argv[:1] == ["--output"]:
        if len(argv) < 2:
            sys.stderr.write("--output requires a path\n")
            return 2
        output_file = argv[1]
        argv = argv[2:]
    if argv:
        sys.stderr.write("unexpected arguments: %s\n" % (argv,))
        return 2

    definition = harness.load_cases()
    records = []
    failed = []
    skipped = []

    for case in definition["cases"]:
        case_id = case["id"]

        if not harness.case_applies(case):
            skipped.append(case_id)
            records.append(
                {
                    "case": case_id,
                    "description": case["description"],
                    "outcome": "SKIPPED_PLATFORM",
                    "platform_required": case.get("platform"),
                    "problems": [],
                }
            )
            sys.stdout.write(
                "%-38s SKIPPED (requires %s)\n" % (case_id, case.get("platform"))
            )
            sys.stdout.flush()
            continue

        observed = harness.run_case(case_id)
        problems = harness.check_expectations(observed, case["expect"])
        if problems:
            failed.append((case_id, problems))

        record = {"description": case["description"]}
        record.update(observed)
        record["outcome"] = "PASS" if not problems else "FAIL"
        record["problems"] = problems
        records.append(record)

        sys.stdout.write("%-38s %s\n" % (case_id, record["outcome"]))
        for problem in problems:
            sys.stdout.write("    %s\n" % (problem,))
        sys.stdout.flush()

    control_records = []
    for control in controls.CONTROLS:
        observation = harness.run_control(control["id"])
        control_records.append(observation)
        sys.stdout.write(
            "%-38s control_reproduces_failure=%s\n"
            % (control["id"], observation["control_reproduces_failure"])
        )
        sys.stdout.flush()

    broken = [
        record["control"]
        for record in control_records
        if not record["control_reproduces_failure"]
    ]
    if broken:
        failed.append(("negative-controls", ["did not reproduce: %s" % (broken,)]))

    reviewable = [
        record["case"]
        for record in records
        if record.get("receipt_verdict") == "REVIEWABLE"
    ]

    document = {
        "schema_version": 1,
        "family": definition["family"],
        "aiqe_version": __version__,
        "platform": sys.platform,
        "cases_total": len(records),
        "cases_passed": sum(1 for r in records if r.get("outcome") == "PASS"),
        "cases_failed": len([f for f in failed if f[0] != "negative-controls"]),
        "cases_skipped_platform": len(skipped),
        "cases_skipped_platform_ids": sorted(skipped),
        "totals": {
            "aiqe_core_repository_mutations": sum(
                r.get("aiqe_core_repository_mutations", 0) for r in records
            ),
            "unconsented_validator_executions": sum(
                r.get("unconsented_validator_executions", 0) for r in records
            ),
            "local_state_writes": sum(r.get("local_state_writes", 0) for r in records),
            "precommit_reviewable_verdicts": len(reviewable),
            "raw_terminal_control_bytes": sum(
                value
                for record in records
                for key, value in record.items()
                if key.endswith("_control_bytes") and isinstance(value, int)
            ),
            "network_requests": 0,
            "model_calls": 0,
        },
        "other_families": {"BOUNDED_COMMIT": "NOT_RUN"},
        "cases": records,
        "negative_controls": control_records,
        "negative_controls_total": len(control_records),
        "negative_controls_reproducing": sum(
            1 for r in control_records if r["control_reproduces_failure"]
        ),
    }

    directory = os.path.dirname(os.path.abspath(output_file))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(output_file, "w") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")

    sys.stdout.write(
        "\n%d/%d applicable cases passed (%d skipped by platform).\n"
        "AIQE core repository writes=%d unconsented validator executions=%d "
        "local state writes=%d pre-commit REVIEWABLE verdicts=%d "
        "raw terminal control bytes=%d\n"
        "%d/%d negative controls reproduced their failure.\n"
        % (
            document["cases_passed"],
            document["cases_total"] - document["cases_skipped_platform"],
            document["cases_skipped_platform"],
            document["totals"]["aiqe_core_repository_mutations"],
            document["totals"]["unconsented_validator_executions"],
            document["totals"]["local_state_writes"],
            document["totals"]["precommit_reviewable_verdicts"],
            document["totals"]["raw_terminal_control_bytes"],
            document["negative_controls_reproducing"],
            document["negative_controls_total"],
        )
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
