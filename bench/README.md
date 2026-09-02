# Benchmarks

This directory holds the benchmark protocol, and — for the one implemented product
surface — the fixture builders and the retained results.

```
protocol/           the method, the families, and the release gates      PRESENT
fixtures/doctor/    deterministic builders, controls, expected outcomes  PRESENT
results/doctor/     retained result artifact                             PRESENT
```

Nothing is present here for a surface that does not exist. `doctor` is implemented, so
its family is materialised; the other families have no fixtures because there is nothing
to point them at.

## Running the Doctor family

```
python3 bench/run-doctor-fixtures.py
```

Every case is built from nothing in an isolated temporary directory, with an isolated
`HOME`, XDG directories and global Git configuration, then run under the measurement
harness and compared against the expectation recorded in
[`fixtures/doctor/cases.json`](fixtures/doctor/cases.json). The runner rewrites
[`results/doctor/results.json`](results/doctor/results.json) and exits non-zero if any
case disagrees with its expectation or any negative control stops reproducing.

`compare-results.py` checks a fresh run against the retained artifact on headline
numbers rather than bytes, because the artifact records the Git version it was produced
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
Change integrity      NOT_RUN   (no implementation exists)
Completion / evidence NOT_RUN   (no implementation exists)
Numerical routing     NOT_RUN   (no implementation exists)
Product friction      NOT_RUN   (no implementation exists)
Context efficiency    NOT_RUN   (deferred; methodology not yet defensible)

macOS baseline        observed
Linux baseline        exercised in CI, not a release claim
Windows               out of scope for v1
```

Only the Doctor family has moved off `NOT_RUN`, and only for the cases that exist. No
aggregate benchmark completion is claimed.

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
