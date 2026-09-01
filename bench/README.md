# Benchmarks

This directory holds the benchmark protocol. It does not yet hold results, because there
is nothing to run.

```
protocol/     the method, the families, and the release gates   PRESENT
fixtures/     deterministic fixture builders                    arrives with the first alpha
results/      retained result artifacts                         arrives with the beta
```

`fixtures/` and `results/` are absent rather than empty. An empty directory implies work
that has not happened.

## Current state

```
AIQE results          NOT_RUN   (no implementation exists)
macOS baseline        observed, provisional
Linux baseline        NOT_RUN   (no approved surface yet)
Windows               out of scope for v1
```

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
