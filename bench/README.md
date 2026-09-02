# Benchmarks

This directory holds the benchmark protocol and, for each implemented product
surface, the fixture builders and the retained results.

```
protocol/           the method, the families, and the release gates      PRESENT
fixtures/           shared measurement and fixture-construction helpers  PRESENT
fixtures/doctor/    deterministic builders, controls, expected outcomes  PRESENT
fixtures/task/      deterministic builders, controls, expected outcomes  PRESENT
fixtures/check/     deterministic builders, controls, expected outcomes  PRESENT
results/doctor/     retained result artifact                             PRESENT
results/task/       retained result artifact                             PRESENT
results/check/      retained result artifact                             PRESENT
```

Nothing is present here for a surface that does not exist. `doctor`, `init`, `task`,
`check` and `receipt` are implemented, so their families are materialised; bounded
commit has no fixtures because there is nothing to point them at.

## Running a family

```
python3 bench/run-doctor-fixtures.py
python3 bench/run-task-fixtures.py
python3 bench/run-check-fixtures.py
```

Every case is built from nothing in an isolated temporary directory, with an isolated
`HOME`, XDG directories and global Git configuration, then run under the measurement
harness and compared against the expectation recorded in
[`fixtures/doctor/cases.json`](fixtures/doctor/cases.json). The runner rewrites
[`results/doctor/results.json`](results/doctor/results.json) and exits non-zero if any
case disagrees with its expectation or any negative control stops reproducing.

The Task family drives the real command-line entry point as subprocesses. Concurrency,
crash-atomicity and byte-preserving argv cannot be measured in-process, and putting every
case through the same door means no case is proven against a path the user does not take.

The check family does the same, and its safety claim is narrower than the other two,
so it is stated exactly. Doctor changes nothing; a task operation changes AIQE's own
machine-local state and nothing else; `aiqe check` runs code the repository declared,
and that code can write wherever the user can. "The repository did not change" is
therefore not available as a claim, and pretending otherwise would be the overstatement
this product exists to refuse. Instead every observed repository change is attributed
to exactly one cause — an authorised `aiqe init` write, a fixture validator's declared
side effect, the scenario's own declared action, or AIQE core — and only the last is
zero-tolerance:

```
AIQE_CORE_REPOSITORY_WRITES         = 0
UNCONSENTED_VALIDATOR_EXECUTIONS    = 0
PRECOMMIT_REVIEWABLE_VERDICTS       = 0
```

The attribution lists are declared per scenario in the builders, so a case cannot
quietly acquire permission to write by writing somewhere new. Every fixture validator
records the fact that it ran, in a directory outside every snapshot root, so the second
quantity is counted rather than argued.

Each of the six launch contract families has its own three fixtures — covered, failed,
and coverage gap. One family standing in for six would leave five with no evidence at
all.

`compare-results.py` selects the retained artifact from the family the fresh run names,
and checks it on headline numbers rather than bytes, because the artifact records the Git version it was produced
under and two correct machines legitimately differ there.

A case may declare a platform restriction. The arbitrary-byte path case needs a
filesystem that accepts non-UTF-8 filenames, which APFS does not provide, so it runs on
Linux and is reported as `SKIPPED_PLATFORM` elsewhere — named in the results, never
dropped from the listing. The comparison treats a case that one machine could run and
the other could not as a platform difference rather than a disagreement.

## Negative controls

Each control in [`fixtures/doctor/controls.py`](fixtures/doctor/controls.py) is a
reference naive diagnostic workflow — the obvious way to obtain the same information —
that violates a frozen Doctor invariant. `control_reproduces_failure` is recorded per
control. A control that stops reproducing is broken and must be redesigned; it is never
counted as a pass, because a control that cannot fail proves nothing about a product
that passes.

## Current state

```
Doctor family         RUN       (results retained here)
Task scope family     RUN       (results retained here)
Check / receipt /
  evidence family     RUN       (results retained here)
Numerical routing     RUN       (six contract families, in the check family)
Bounded commit        NOT_RUN   (no implementation exists)
Product friction      NOT_RUN   (no implementation exists)
Context efficiency    NOT_RUN   (deferred; methodology not yet defensible)

macOS baseline        observed
Linux baseline        exercised in CI, not a release claim
Windows               out of scope for v1
```

Three families have moved off `NOT_RUN`, and only for the cases that exist. No
aggregate benchmark completion is claimed.

Numerical routing is `RUN` for the pre-commit half only: classification, contract
applicability and coverage are measured for all six families, and the post-commit half
of family B waits on a bounded commit.

The provisional macOS baseline was observed during protocol development. It is **not**
published as an authority and no number from it appears in the README, because the
fixture builders and result artifacts that would make it reproducible are not yet
retained here. That is the whole point of the retention rule below.

## Retention rules

```
fixture builder source     retained in-repo, executable, deterministic
expected outcome           retained per case, declared before the run
result JSON                retained, regenerated, never hand-edited
visuals                    generated from result JSON only
failed / unsupported /
  not-run cases            retained and rendered — never hidden, never filtered
README numbers             permitted only from retained artifacts
```

A result file is an output. Editing one by hand converts the benchmark from evidence into
decoration.

See [`protocol/protocol.md`](protocol/protocol.md) for the method and
[`protocol/families.md`](protocol/families.md) for the case families.
