#!/usr/bin/env python3
"""Render the presentation artifacts from the retained result artifacts.

    python3 bench/render-assets.py            report drift, exit 1 if any
    python3 bench/render-assets.py --write    regenerate everything

Two things are rendered, and neither is ever typed by hand:

**Terminal captures.** `docs/assets/captures/` holds one file per screenshotable
surface, each the exact rendered output a benchmark case produced, alongside an
index naming the family, the case and the field every capture came from. They
exist so a later visual asset is made from a recorded transcript rather than
from somebody's terminal - which would carry that machine's paths, username and
repository name into an image nobody reads before publishing it.

**The README benchmark block.** Copying a total out of prose is how a published
number stops matching the artifact it came from. The block is generated between
markers instead, and `tests/test_documentation.py` fails when the README and the
artifacts disagree.

This renders. It measures nothing: every value here was produced by a benchmark
runner, and if a family's retained artifact is stale, this reproduces it
faithfully.
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

RESULTS = os.path.join(HERE, "results")
CAPTURES = os.path.join(ROOT, "docs", "assets", "captures")
README = os.path.join(ROOT, "README.md")

BEGIN = "<!-- benchmarks:begin -->"
END = "<!-- benchmarks:end -->"


#: The families, in the order a reader meets the commands.
FAMILIES = (
    ("doctor", "doctor"),
    ("task", "task"),
    ("check", "check"),
    ("commit", "bounded commit"),
)


#: One entry per screenshotable surface: file stem, family, case, the field of
#: that case's record, and what the surface is for.
#:
#: Every one is a synthetic fixture built from nothing by a benchmark builder.
#: None of them was recorded against a real repository.
SURFACES = (
    (
        "doctor",
        "doctor",
        "normal_repository",
        "human_output",
        "Doctor on an ordinary repository, with nothing to report.",
    ),
    (
        "doctor-fail-closed",
        "doctor",
        "checkin_filter_configured",
        "human_output",
        "Doctor declining to answer a question it cannot answer without "
        "executing what the repository configured.",
    ),
    (
        "check-reviewable-candidate",
        "check",
        "causality_covered",
        "check_output",
        "A completely green check. Every required validator passed and every "
        "applicable contract is covered.",
    ),
    (
        "check-unknown",
        "check",
        "consent_withheld",
        "check_output",
        "Fail-closed: consent was not given, so the validators did not run and "
        "their outcome is UNKNOWN - neither a pass nor a failure.",
    ),
    (
        "receipt-precommit-incomplete",
        "check",
        "causality_covered",
        "receipt_output",
        "The pre-commit receipt for that same green check: INCOMPLETE, because "
        "no bounded commit exists for the evidence to bind to.",
    ),
    (
        "commit-reviewable",
        "commit",
        "commit-owned-modification",
        "commit_output",
        "The bounded completion commit, with the four proofs it rests on.",
    ),
    (
        "receipt-postcommit-reviewable",
        "commit",
        "commit-owned-modification",
        "receipt_output",
        "The post-commit receipt. The only place REVIEWABLE appears.",
    ),
)


def load(family):
    with open(os.path.join(RESULTS, family, "results.json")) as handle:
        return json.load(handle)


def cases(document):
    return {case["case"]: case for case in document["cases"]}


def digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Captures --------------------------------------------------------------


def render_captures():
    """(relative path -> content) for every capture and the index."""
    documents = {family: load(family) for family, _label in FAMILIES}
    rendered = {}
    index = []

    for stem, family, case_id, field, description in SURFACES:
        document = documents[family]
        case = cases(document).get(case_id)
        if case is None:
            raise SystemExit(
                "no case %r in the retained %s artifact" % (case_id, family)
            )
        if field not in case:
            raise SystemExit(
                "case %r in family %s has no %r" % (case_id, family, field)
            )
        body = case[field].rstrip("\n") + "\n"
        rendered["%s.txt" % (stem,)] = body
        index.append(
            {
                "capture": "%s.txt" % (stem,),
                "family": document["family"],
                "results": "bench/results/%s/results.json" % (family,),
                "case": case_id,
                "field": field,
                "description": description,
                "aiqe_version": document["aiqe_version"],
                "digest": digest(body),
            }
        )

    rendered["index.json"] = (
        json.dumps(
            {
                "schema_version": 1,
                "note": (
                    "Every capture is the exact rendered output of a synthetic "
                    "conformance case, copied from the retained result artifact "
                    "named in its row. Nothing here was typed, and nothing was "
                    "recorded against a real repository."
                ),
                "captures": index,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return rendered


# --- The README benchmark block --------------------------------------------


def render_benchmark_block():
    documents = [(label, load(family)) for family, label in FAMILIES]

    columns = (
        ("family", 18, "<"),
        ("cases", 7, ">"),
        ("passed", 8, ">"),
        ("failed", 8, ">"),
        ("skipped", 9, ">"),
        ("controls", 12, ">"),
    )
    header = "".join(
        ("%-*s" if align == "<" else "%*s") % (width, name)
        for name, width, align in columns
    )

    def row(label, cells):
        parts = [("%-*s" % (columns[0][1], label))]
        for (_name, width, _align), cell in zip(columns[1:], cells):
            parts.append("%*s" % (width, cell))
        return "".join(parts)

    lines = [header]
    totals = [0, 0, 0, 0, 0]
    for label, document in documents:
        counts = (
            document["cases_total"],
            document["cases_passed"],
            document["cases_failed"],
            document["cases_skipped_platform"],
        )
        controls = (
            document["negative_controls_reproducing"],
            document["negative_controls_total"],
        )
        for index, value in enumerate(counts):
            totals[index] += value
        totals[4] += controls[1]
        lines.append(
            row(
                label,
                [str(value) for value in counts]
                + ["%d of %d" % controls],
            )
        )

    reproducing = sum(
        document["negative_controls_reproducing"] for _label, document in documents
    )
    lines.append(
        row(
            "",
            ["---", "---", "---", "---", "-------"],
        )
    )
    lines.append(
        row(
            "",
            [str(value) for value in totals[:4]]
            + ["%d of %d" % (reproducing, totals[4])],
        )
    )

    quantities = sorted(
        {
            name
            for _label, document in documents
            for name in document["totals"]
        }
    )
    nonzero = sorted(
        "%s=%s" % (name, value)
        for _label, document in documents
        for name, value in document["totals"].items()
        if value
    )
    platforms = sorted({document["platform"] for _label, document in documents})
    versions = sorted({document["aiqe_version"] for _label, document in documents})
    skipped = sorted(
        case_id
        for _label, document in documents
        for case_id in document["cases_skipped_platform_ids"]
    )

    body = [
        "",
        "Rendered from the retained result artifacts under",
        "[`bench/results/`](bench/results/) by",
        "[`bench/render-assets.py`](bench/render-assets.py). No number below was",
        "copied from prose, and a test fails if this block and those artifacts",
        "disagree.",
        "",
        "```",
    ]
    body.extend(lines)
    body.extend(
        [
            "```",
            "",
            "The retained run is AIQE %s on %s. Every skipped case is skipped "
            "for a stated" % (" and ".join(versions), " and ".join(platforms)),
            "platform reason and is listed in the artifact rather than dropped "
            "from it:",
            "",
            "```",
        ]
    )
    body.extend("%s" % (case_id,) for case_id in skipped)
    body.extend(
        [
            "```",
            "",
            "Each family also declares zero-tolerance quantities, measured from "
            "outside the",
            "process rather than reported by it. What each one counts is "
            "defined by the family",
            "that measures it — see [`bench/README.md`](bench/README.md). Across "
            "all four families,",
            "every one of them stands at zero:",
            "",
            "```",
        ]
    )
    body.extend(quantities)
    body.extend(
        [
            "```",
            "",
        ]
    )
    if nonzero:
        body.extend(
            [
                "**A zero-tolerance quantity is not zero:** %s."
                % (", ".join(nonzero),),
                "",
            ]
        )
    body.extend(
        [
            "A negative control is a workflow that *must* fail, kept so that a "
            "gate which",
            "has stopped detecting anything is caught here rather than believed. "
            "The method",
            "and the families are in "
            "[`bench/protocol/protocol.md`](bench/protocol/protocol.md) and",
            "[`bench/protocol/families.md`](bench/protocol/families.md).",
            "",
        ]
    )
    return "\n".join(body)


# --- Writing and checking --------------------------------------------------


def readme_with_block(readme, block):
    if BEGIN not in readme or END not in readme:
        raise SystemExit("README.md has no %s / %s markers" % (BEGIN, END))
    start = readme.index(BEGIN) + len(BEGIN)
    end = readme.index(END, start)
    return readme[:start] + block + readme[end:]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite the captures and the README block instead of checking them",
    )
    options = parser.parse_args(argv)

    rendered = render_captures()
    block = render_benchmark_block()
    with open(README, encoding="utf-8") as handle:
        readme = handle.read()
    updated = readme_with_block(readme, block)

    if options.write:
        if not os.path.isdir(CAPTURES):
            os.makedirs(CAPTURES)
        for name, body in sorted(rendered.items()):
            with open(os.path.join(CAPTURES, name), "w", encoding="utf-8") as handle:
                handle.write(body)
        with open(README, "w", encoding="utf-8") as handle:
            handle.write(updated)
        sys.stdout.write(
            "wrote %d captures, their index, and the README benchmark block\n"
            % (len(SURFACES),)
        )
        return 0

    drifted = []
    for name, body in sorted(rendered.items()):
        path = os.path.join(CAPTURES, name)
        try:
            with open(path, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            drifted.append("docs/assets/captures/%s is missing" % (name,))
            continue
        if current != body:
            drifted.append("docs/assets/captures/%s is not the retained output" % (name,))
    if updated != readme:
        drifted.append("the README benchmark block is not what the artifacts render")

    for problem in drifted:
        sys.stderr.write("DRIFT  %s\n" % (problem,))
    if drifted:
        sys.stderr.write("Run: python3 bench/render-assets.py --write\n")
        return 1

    sys.stdout.write(
        "%d captures, their index, and the README benchmark block match the "
        "retained artifacts\n" % (len(SURFACES),)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
