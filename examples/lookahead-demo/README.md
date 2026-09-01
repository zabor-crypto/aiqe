# Lookahead demo — specification

`DESIGN TARGET — specified, not yet implemented.`

This is the canonical failure-first demonstration. It is specified here and materialised
alongside the first alpha; no fixture files or code exist yet.

## What it demonstrates

A synthetic strategy contains a **one-character causality defect** — an index shift that
lets a bar influence a decision made before that bar existed.

```
the project's own generic tests    PASS
a native causality validator       FAIL
```

That gap is the entire argument. The tests are not wrong; they are answering a different
question. A green test suite is evidence that the tests passed, and it has never been
evidence that the numbers mean anything.

The demo also stages an unrelated note file **outside the owned scope**, to show that the
bounded commit excludes it and that the receipt reports it as observed and excluded
rather than quietly absorbing it.

## The coverage-gap variant

A second variant removes the causality validator entirely.

Run naively, everything is green — because nothing checked. AIQE reports `COVERAGE_GAP`:
the contract applies to this surface, no required validator is bound to it, and the
absence of a check is not a pass.

This variant matters more than the first. The first shows a check catching a defect. The
second shows the product's actual thesis: that the dangerous state is the one where
nobody looked and the output was green anyway.

## Constraints

```
no private market data
no real strategy
no external download
no network access
deterministic from a fixed seed
reproducible offline
redistribution-safe
```

The fixture must also be hermetic against stale bytecode and build caches, so that a
cached artifact cannot make the validator appear to succeed against source it never
read — which would falsify the demo's own expected result.

## Expected shape when materialised

```
examples/lookahead-demo/
  README.md          this file
  build.<ext>        deterministic fixture builder
  expected.json      declared expected outcomes, committed before the run
```

Every result the demo produces is retained, including the failing ones. The failing ones
are the demo.
