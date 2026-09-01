# Clean-room provenance

This repository is a clean-room implementation. Its history begins here: no history,
source, or files were imported from any predecessor codebase, and nothing was copied and
then sanitised after the fact.

This manifest records *how* each public mechanism came to exist, in categories, so that
the claim above is auditable rather than merely asserted. It deliberately does not
describe any private system, because a provenance record that leaked its own subject
would defeat its purpose.

## Categories

Every mechanism in this repository is assigned exactly one category.

**`CLEAN_ROOM_REIMPLEMENTATION`**
Specified from a behavioural description and implemented independently. No source was
consulted during implementation.

**`DIRECT_PUBLIC_REUSE_ELIGIBLE`**
Material that is public and licence-compatible and may be reused directly, with its
licence and attribution recorded. Anything in this category carries its attribution in
`NOTICE` once such material exists.

**`CONCEPT_ONLY_DERIVATION`**
The idea is prior art or was learned from experience; the expression here is original.
This covers most of the architecture: bounded change scope, staged-state observation,
and content binding are not novel concepts, and this project claims no invention in them.

**`SYNTHETIC_FIXTURE`**
Generated data and repositories constructed for tests, benchmarks, and demonstrations.
Synthetic fixtures are deterministic, redistribution-safe, and contain no real market
data, no real strategy, and no data derived from any private source.

**`PUBLIC_DOCUMENTATION_REFERENCE`**
Behaviour derived from published specifications — principally Git's own documentation for
pathspec semantics, index and staging behaviour, configuration resolution including
`include` and `includeIf`, check-in and check-out filters, and hook execution.

## Current status

At bootstrap this repository contains specification, protocol, and tooling only.

```
Documentation and specification   CONCEPT_ONLY_DERIVATION
                                  PUBLIC_DOCUMENTATION_REFERENCE
Benchmark protocol and families   CLEAN_ROOM_REIMPLEMENTATION
Bootstrap sanitisation tooling    CLEAN_ROOM_REIMPLEMENTATION
Apache-2.0 licence text           DIRECT_PUBLIC_REUSE_ELIGIBLE
Implementation source             does not exist yet
Third-party dependencies          none
```

Because there are no third-party dependencies, there is no `NOTICE` file. One is created
when the first such dependency lands, not before.

## What this manifest does not contain

By design, and permanently:

- paths, names, or identifiers belonging to any private repository or system;
- private commit identifiers or history;
- private project, strategy, or infrastructure names;
- private hostnames, accounts, buckets, or endpoints;
- private benchmark economics or any figure derived from real trading;
- conversation transcripts or working notes.

Describing a mechanism is in scope. Exposing a private instance of one is not.

## Obligation on contributors

Every contribution declares its provenance category in the pull request, and contributors
attest that they have the right to submit it and have disclosed any non-original
material. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

This manifest is only worth what that attestation is worth, which is why it is one of the
few pieces of process this project keeps.
