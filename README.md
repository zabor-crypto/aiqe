# AIQE — AI Quant Engineering

> **DONE ISN'T EVIDENCE.**

AIQE is the assurance layer for AI-assisted quant engineering.
It bounds the change, keeps unrelated Git state out of the commit,
runs your project-native checks, and shows what remains unknown.

---

**Status: architecture and benchmark protocol frozen. No installable artifact yet.**

Nothing below is a claim about software that exists today. This repository currently
contains the frozen product specification, the benchmark protocol, and the bootstrap
tooling. Every command shown is marked as a design target until it is implemented and
its behaviour is demonstrated by a retained artifact.

`DESIGN TARGET — specified, not yet implemented.`

```
$ aiqe doctor
```

macOS is the supported target for v1 · Linux support is a later proof obligation · Windows is out of scope for v1

No telemetry. No network calls. No model calls. No daemon. No background watcher.
AIQE never pushes.

---

## The 30-second problem

An agent edits your backtest. It reports that the tests pass.

Three separate things are now unknown, and none of them are visible in that sentence:

1. **What actually changed.** The agent touched files you did not ask it to touch, or
   your index already held unrelated staged work, and the commit silently absorbed it.
2. **What the passing tests actually prove.** They prove that the tests that exist
   succeeded. They say nothing about the check nobody wrote.
3. **Whether the result is numerically trustworthy.** A one-character index shift can
   leak a future bar into a signal. Every generic test still passes. The equity curve
   just became fiction.

AIQE does not make your code correct. It makes the boundary between *checked* and
*unknown* explicit, and refuses to call an unproven state reviewable.

## Failure-first demo

The canonical demo is a synthetic strategy containing a one-character causality defect.
The project's own generic tests **pass**. A native causality validator **fails**. A
second variant removes the causality validator entirely, and AIQE reports a coverage
gap rather than a green result.

See [`examples/lookahead-demo/`](examples/lookahead-demo/) for the specification.
The demo is materialised alongside the first alpha, not before.

## How it works

AIQE is deterministic. It contains no model calls.

```
doctor    inspect the environment before anything is changed
init      write ./aiqe.toml
task      declare an immutable owned scope for a unit of work
check     run the validators bound to the applicable contracts
commit    create a bounded completion commit, or refuse
receipt   render what is proven, what is excluded, and what is unknown
```

The owned scope is fixed when a task starts and cannot widen. Checks run against that
scope. The receipt reports one of three verdicts — `REVIEWABLE`, `INCOMPLETE`, or
`NOT_REVIEWABLE` — and never invents a fourth, softer one.

Full command surface and exit semantics: [`docs/architecture.md`](docs/architecture.md).

## Change integrity

AIQE bounds what a completion commit is allowed to contain.

- The owned scope is immutable from task start and uses exact literal file paths in v1.
- Git caller paths use literal-pathspec semantics, so a filename containing a glob
  character cannot silently expand the change.
- Foreign staged state — anything staged outside the owned scope — is observed before
  and after. If it drifts in any direction, including a *newly appearing* entry, the
  answer is `UNKNOWN`, not a shrug.
- Intent-to-add is transactional.
- AIQE never pushes.

The user-facing guarantee is stated narrowly and deliberately:

> AIQE's bounded commit contains only the expected owned changed pathset.

## Evidence integrity

A check that succeeded earlier does not describe a commit made later. AIQE binds them.

At `check`, a bounded cryptographic state binding is recorded for every owned path,
covering file content, new-file and deletion states, relevant mode and type, and the
digests of the configuration and evidence definitions in force.

At `commit`, that binding is recomputed before any mutation. If it differs, the evidence
is stale and the commit is refused. After the commit, AIQE verifies that the changed
pathset is exactly the expected owned pathset and that the committed content corresponds
to the exact checked state. If that correspondence cannot be demonstrated, the receipt
does not say `REVIEWABLE`.

## Numerical integrity

Quant surfaces are classified explicitly. Every matching surface is evaluated and their
contract obligations union. Declaring a path both quant and non-quant is a configuration
conflict and fails closed.

Six umbrella contracts ship at launch:

```
CAUSALITY              DATA_ALIGNMENT         EXECUTION_REALISM
ACCOUNTING             TRAIN_TEST_SEPARATION  DETERMINISM
```

Every required validator bound to an applicable contract must pass. **A contract that
applies but has zero required validators is a `COVERAGE_GAP`, not a pass.** This is the
single most important behaviour in the product: silence is not evidence.

Details: [`bench/protocol/families.md`](bench/protocol/families.md).

## What AIQE does not do — and cannot prove

This section is load-bearing. An assurance tool that overstates its own guarantees is
worse than no assurance tool.

**`PASS` means your validator succeeded. Nothing more.**

AIQE guarantees that the declared validator command was invoked under the recorded task
and configuration state, that its process outcome was recorded, and that the owned source
state it checked is bound to the eventual bounded commit.

AIQE does **not** guarantee that a validator internally consumed every source or data
artifact you intended, that interpreter or build caches were fresh, that the validator's
own logic is correct, or that its dependencies and external data were causally fresh.

**Write confinement is scoped, not global.** AIQE core's own filesystem writes are
confined to declared owned paths where explicitly required, to `./aiqe.toml` during
`init`, and to AIQE local state outside the repository. That is *not* a claim that
validators cannot mutate foreign files, that Git cannot mutate internal repository
state, that another process cannot modify the worktree, or that foreign unstaged and
untracked bytes remain identical.

**Validators are not sandboxed.** Repository-native validators run as ordinary child
processes after explicit local consent. AIQE makes no sandbox and no network-restriction
claim about them. A validator can do anything your shell can do.

**AIQE does not police ordinary Git.** It does not intercept your commits, and post-hoc
verification of externally created commits is not a v1 feature.

**There is no safety score.** AIQE produces no number summarising how safe a change is.

Also not in scope: it is not a linter, not a CI system, not a sandbox, and it does not
install hooks or run in the background.

## Milestones

| Milestone | Meaning |
|---|---|
| *(current)* | Specification and benchmark protocol frozen. No installable artifact. |
| `v0.1.0` | First installable alpha: `doctor`, `init`, `task`, `check`, `receipt` on macOS. Real tests in real CI. |
| `v0.2.0` | `commit` with checked-content binding, all six contracts, benchmark fixtures and retained results. |
| `v0.3.0` | Linux baseline actually run. Agent adapters. Demo and visual package materialised. |
| `v1.0.0` | Every release gate green against retained artifacts. Command surface stable. Every public claim traced to evidence. |

No benchmark number will appear in this README until it is generated from a retained
result artifact. No result is hidden, including failures and cases that were never run.

## Security

Vulnerability reporting, the trust boundaries, and the threat model summary are in
[`SECURITY.md`](SECURITY.md). Please do not open a public issue for a vulnerability.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions carry a clean-room and
public-data attestation; there is no CLA and no DCO.

## License

[Apache License 2.0](LICENSE).
