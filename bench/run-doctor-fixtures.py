#!/usr/bin/env python3
"""Run the Doctor benchmark family and retain the result artifact.

    python3 bench/run-doctor-fixtures.py
    python3 bench/run-doctor-fixtures.py --output /tmp/fresh.json

Builds every case in `bench/fixtures/doctor/cases.json`, runs Doctor against
it under the measurement harness, compares the observation to the recorded
expectation, and writes `bench/results/doctor/results.json`.

This is a runner, not a framework. It has no plugins, no discovery, no
reporters and no configuration. Doctor is the only implemented product
surface, so it is the only family that can be run; the other families stay
NOT_RUN and are not fabricated here.

`--output` writes the artifact somewhere other than the retained location,
which is how continuous integration regenerates the results on a different
machine without overwriting the retained file. The two are then compared on
their headline numbers rather than byte for byte: the artifact records the Git
version it was produced under, and that legitimately differs between machines.

Exit status is 0 when every case matched its expectation with all three
zero-tolerance quantities at zero and every negative control reproduced its
failure, and 1 otherwise.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(HERE, "fixtures", "doctor"))

import controls  # noqa: E402
import harness  # noqa: E402

RESULTS_DIRECTORY = os.path.join(HERE, "results", "doctor")
RESULTS_FILE = os.path.join(RESULTS_DIRECTORY, "results.json")


#: Fields that must agree between the retained artifact and a fresh run on
#: any machine. Everything else - the observed Git version, the rendered
#: output that quotes it - is provenance, not a claim.
HEADLINE_FIELDS = (
    "cases_total",
    "cases_passed",
    "cases_failed",
    "negative_controls_total",
    "negative_controls_reproducing",
)


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

    for case in definition["cases"]:
        case_id = case["id"]
        observed = harness.run_case(case_id)
        problems = harness.check_expectations(observed, case["expect"])
        if problems:
            failed.append((case_id, problems))

        records.append(
            {
                "case": case_id,
                "description": case["description"],
                "outcome": "PASS" if not problems else "FAIL",
                "problems": problems,
                "result": observed["result"],
                "exit_code": observed["exit_code"],
                "findings": observed["findings"],
                "repository": observed["repository"],
                "topology": observed["topology"],
                "operations_in_progress": observed["operations_in_progress"],
                "working_state": observed["working_state"],
                "aiqe": observed["aiqe"],
                "commit_policy": observed["commit_policy"],
                "agent_surface": observed["agent_surface"],
                "repository_mutations": observed["repository_mutations"],
                "repository_mutation_detail": observed["repository_mutation_detail"],
                "repository_defined_executions": observed["repository_defined_executions"],
                "fired_canaries": observed["fired_canaries"],
                "local_state_writes": observed["local_state_writes"],
                "local_state_write_detail": observed["local_state_write_detail"],
                "git_invocations": observed["git_invocations"],
                "human_output": observed["human_output"],
            }
        )
        sys.stdout.write(
            "%-30s %s\n" % (case_id, "PASS" if not problems else "FAIL")
        )
        for problem in problems:
            sys.stdout.write("    %s\n" % (problem,))
        sys.stdout.flush()

    control_records = []
    for control in controls.CONTROLS:
        observation = harness.run_control(control["id"])
        control_records.append(harness.control_record(observation))
        sys.stdout.write(
            "%-42s control_reproduces_failure=%s\n"
            % (control["id"], observation["control_reproduces_failure"])
        )
        sys.stdout.flush()

    broken_controls = [
        record["control"]
        for record in control_records
        if not record["control_reproduces_failure"]
    ]
    if broken_controls:
        failed.append(("negative-controls", ["did not reproduce: %s" % (broken_controls,)]))

    document = {
        "schema_version": 1,
        "family": definition["family"],
        "aiqe_version": __version__,
        "cases_total": len(records),
        "cases_passed": sum(1 for record in records if record["outcome"] == "PASS"),
        "cases_failed": len(failed),
        "totals": {
            "repository_mutations": sum(r["repository_mutations"] for r in records),
            "repository_defined_executions": sum(
                r["repository_defined_executions"] for r in records
            ),
            "local_state_writes": sum(r["local_state_writes"] for r in records),
            "network_requests": 0,
            "model_calls": 0,
        },
        "other_families": {
            "CHANGE_INTEGRITY": "NOT_RUN",
            "COMPLETION_EVIDENCE_TRUTH": "NOT_RUN",
            "NUMERICAL_INTEGRITY_ROUTING": "NOT_RUN",
            "PRODUCT_FRICTION": "NOT_RUN",
            "CONTEXT_EFFICIENCY": "NOT_RUN"
        },
        "cases": records,
        "negative_controls": control_records,
        "negative_controls_total": len(control_records),
        "negative_controls_reproducing": sum(
            1 for record in control_records if record["control_reproduces_failure"]
        ),
    }

    directory = os.path.dirname(os.path.abspath(output_file))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(output_file, "w") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")

    sys.stdout.write(
        "\n%d/%d cases passed. mutations=%d executions=%d state writes=%d\n"
        "%d/%d negative controls reproduced their failure.\n"
        % (
            document["cases_passed"],
            document["cases_total"],
            document["totals"]["repository_mutations"],
            document["totals"]["repository_defined_executions"],
            document["totals"]["local_state_writes"],
            document["negative_controls_reproducing"],
            document["negative_controls_total"],
        )
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
