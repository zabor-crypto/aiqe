# Lookahead demo

A synthetic repository with a one-character causality defect, and four acts
showing what each workflow says about it.

```bash
python3 examples/lookahead-demo/run.py
```

It builds six repositories from nothing in a temporary directory — one for each
act, and a second for each act that also runs the reference workflow — drives
the real `aiqe` entry point against them, and prints what every act measured.
It needs no network, and writes nothing inside this repository.

The four acts land on stdout as they were measured, with the second one given
the room, because it is the one that carries the product's only unique claim.
Every value printed is read from the same record that is compared against
[`expected.json`](expected.json) — so a summary that disagreed with the
product would fail the run that printed it.

The outcomes it must reproduce are declared in [`expected.json`](expected.json),
which is written before the run. The demo exits non-zero if any of them
disagrees.

## The defect

The strategy decides at each bar whether the window rose. A decision made at
bar `i` may only read bars strictly earlier than `i`:

```python
DECISION_LAG = 0    # must be 1
```

At `0` the decision reads the bar it is made on, so a price that had not
printed yet reaches back into a signal that was already taken. The series is a
fixed integer sequence — no floats, no entropy source — so every machine sees
the same numbers.

## The four acts

```
1  defect_is_caught         the generic suite passes; the causality
                            validator fails            -> NOT_REVIEWABLE
2  nobody_looked            the same defect, with no required validator
                            bound to CAUSALITY         -> INCOMPLETE, COVERAGE_GAP
3  unrelated_staged_work    an ordinary commit absorbs the index; the
                            bounded commit does not    -> REVIEWABLE
4  stale_evidence           check, edit, commit: the reference workflow
                            commits content nothing checked
                                                       -> INCOMPLETE, STALE_OWNED_CONTENT
```

**Act 1** is the one people expect: a check catches a defect. The generic
suite passes anyway, and it is not wrong to — it was answering a different
question.

**Act 2** is the one that matters. Remove the causality validator and
everything the repository has still passes. AIQE reports `COVERAGE_GAP`: the
contract applies to the changed surface, no required validator is bound to it,
and the absence of a check is not a pass. This is the dangerous state — nobody
looked, and the output was green.

**Acts 3 and 4** are about the commit rather than the checks. Both run the
reference workflow first, in its own copy of the same repository, so the
contrast is measured rather than asserted: act 3 records the pathset the
ordinary commit actually contained, and act 4 re-runs the repository's own
causality check against what the ordinary commit actually committed.

## What it writes, and where

```
demo.json        every act's structured observations, including the full
                 rendered output of every AIQE command
transcript.txt   the commands and the output they produced
```

By default both go to a fresh temporary directory, whose path the run prints.
Running the demo therefore leaves this repository clean, which matters here
more than it would elsewhere: the transcript carries a task start timestamp
that legitimately differs between runs, so a default that wrote into the
tracked copies would hand every reader an unexplained diff.

The copies under [`results/`](results/) are the retained evidence. They are
rewritten only when that path is asked for by name:

```bash
python3 examples/lookahead-demo/run.py --output examples/lookahead-demo/results
```

The transcript states its own two rewritings
— `python3 -m aiqe` written as `aiqe`, and the background-maintenance flags on
every Git invocation — and nothing else in it differs from what a process
printed. The only field that changes between two runs is the task start
timestamp, and `tests/test_demo.py` re-runs the demo and asserts that the
retained transcript differs from a fresh one in exactly those lines.

Failing results are retained the same way as passing ones. The failing ones
are the demo.

## Constraints

```
no private market data          no network access
no real strategy                deterministic from a fixed seed
no external download            reproducible offline
redistribution-safe             hermetic against stale bytecode
```

The last one is not decoration: both validators run under `python3 -B -E`, so
a cached bytecode file cannot let a check answer about source it never read —
which would falsify the demo's own expected result.

## What the demo does not show

It does not show `aiqe doctor` or `aiqe init`; the
[quickstart](../../README.md#five-minute-quickstart) covers those. It runs AIQE
from the source tree rather than from an installed wheel — the release proof
covers the installed artifact, and is a different claim from this one.

And it proves nothing about your repository. What it demonstrates is the shape
of the argument: a generic suite is evidence that the generic suite passed.
