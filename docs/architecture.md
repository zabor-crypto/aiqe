# Architecture

This document is the public statement of AIQE's frozen v1 architecture. It describes
what the product does and where its guarantees stop. It is a specification: no
implementation exists yet, and every command below is a design target.

## Product

```
PRODUCT   quant engineering assurance layer

PILLARS   CHANGE INTEGRITY
          EVIDENCE INTEGRITY
          NUMERICAL INTEGRITY
```

AIQE v1 is deterministic and contains no model calls.

## Command surface

The v1 surface is closed. There are no other commands and no other flags.

```
aiqe --version

aiqe doctor  [--format json]

aiqe init    [--print] [--yes]

aiqe task    start --own <path>... [--label <text>]
aiqe task    end
aiqe task

aiqe check   [--allow <validator-id>]... [--format json]

aiqe commit  -m <message>

aiqe receipt [--local] [--format json]
```

Doctor runs before init. That ordering is intentional: nothing is written into a
repository before the environment has been inspected.

## Exit semantics

Exit codes are uniform across commands. There is no command-specific fifth code.

```
0   successful / reviewable operation
1   FAIL / NOT_REVIEWABLE
2   INCOMPLETE
3   UNSUPPORTED / invalid configuration / operation cannot safely proceed
```

Applied:

```
aiqe check
  0  required checks and coverage current and passing
  1  a required validator failed, including by timeout
  2  incomplete, unknown, unavailable, stale, or a coverage gap
  3  unsupported or refused on configuration grounds

aiqe commit
  0  bounded completion commit created and verified
  1  fail-class completion blocker
  2  incomplete-class completion blocker
  3  unsupported / configuration / policy refusal

aiqe receipt
  0  REVIEWABLE
  1  NOT_REVIEWABLE
  2  INCOMPLETE
  3  a valid receipt cannot be produced due to an unsupported or refused state
```

Machine-readable reason codes carry the detail that the exit code deliberately does not:

```
CONFIG_CONFLICT
COMMIT_HOOK_POLICY_UNSUPPORTED
COMMIT_SIGNING_POLICY_UNSUPPORTED
CHECKIN_FILTER_UNSUPPORTED
EFFECTIVE_CONFIG_UNRESOLVED
UNSUPPORTED_TOPOLOGY
COVERAGE_GAP
```

## Owned scope

A task declares an owned scope, and that scope is **immutable from task start**. In v1
it uses exact literal file paths only — no globs, no directory expansion.

Git caller paths use literal-pathspec semantics, so a filename that happens to contain a
pathspec metacharacter cannot silently widen the change. Machine-readable Git path
output is NUL-delimited wherever Git supports it, because newline-delimited paths are
not a safe parsing surface. Intent-to-add is transactional.

## Change integrity

The commit AIQE creates is a bounded completion commit. It is optional; AIQE does not
intercept ordinary Git, and it never pushes.

Foreign staged state is represented as the structured HEAD-to-index staged delta over
non-owned paths, compared before and after:

```
PRE == POST                     -> foreign staged non-reset is proven

any difference:
  a missing pre-existing entry
  a modified pre-existing entry
  a newly appearing entry
                                -> FOREIGN_STAGED_STATE = UNKNOWN
                                -> final verdict at best INCOMPLETE
```

A newly appearing foreign staged entry is never silently ignored, and it is never
attributed to AIQE unless an owned-scope violation independently proves AIQE caused it.

### The confinement claim, stated exactly

```
AIQE_WORKTREE_WRITE_CONFINEMENT
```

AIQE core's own filesystem writes are confined to declared owned paths where explicitly
required, to `./aiqe.toml` during `init`, and to AIQE local state outside the repository.

This is deliberately **not** called non-interference, because it does not claim that
validators cannot mutate foreign files, that Git cannot mutate internal repository
state, that another process cannot modify the worktree, or that foreign unstaged and
untracked bytes remain identical.

The claim that is made:

> AIQE's bounded commit contains only the expected owned changed pathset.

## Evidence integrity: checked-content binding

Equal path sets are not sufficient to turn a passing pre-commit check into post-commit
evidence. The same paths can hold different bytes.

At `check`, AIQE records a bounded cryptographic state binding for every owned path,
covering regular-file content state, new-file state, deletion markers, relevant mode and
type, and the digests of the configuration and evidence definitions in force.

At `commit`, before any mutation, that binding is recomputed:

```
if it differs  ->  evidence = STALE, commit = REFUSED
```

After the commit, AIQE verifies that the parent-to-commit changed pathset equals the
expected owned changed pathset, and that the committed owned tree and blob state
corresponds to the exact checked state under supported Git check-in semantics. If that
correspondence cannot be demonstrated, the receipt is not `REVIEWABLE`.

The cost is bounded by the owned pathset. No whole-tree fingerprinting is introduced.

## Commit policy: refuse, never bypass

AIQE will not disable repository governance in order to produce a commit.

```
ACTIVE_COMMIT_HOOK                              -> AIQE_COMMIT_UNSUPPORTED
EFFECTIVE_COMMIT_SIGNING_REQUIRED               -> AIQE_COMMIT_UNSUPPORTED
EXTERNAL_CLEAN_OR_PROCESS_FILTER_ON_OWNED_PATH  -> AIQE_COMMIT_UNSUPPORTED
```

Commit preflight reasons about the **effective** configuration the real commit would
use — hooks path, signing, filter drivers — including applicable `include` and
`includeIf` chains. This is a higher-authority operation than Doctor's bounded static
inspection, and it must either resolve that configuration unambiguously or refuse.
Absence is never assumed.

`aiqe commit` may neutralise non-semantic execution or performance surfaces only where
doing so bypasses no explicit repository policy, and the effect is documented.

When commit is unsupported, `check` and `receipt` remain available and the user commits
with ordinary Git.

## Numerical integrity

Quant surfaces are classified as `QUANT_SURFACE`, `EXPLICIT_NON_QUANT_SURFACE`, or
`UNCLASSIFIED`. All matching surfaces are evaluated and their contract obligations
union. A path declared both quant and non-quant is a `CONFIG_CONFLICT` and fails closed.

Six umbrella contracts ship at launch:

```
CAUSALITY   DATA_ALIGNMENT   EXECUTION_REALISM
ACCOUNTING  TRAIN_TEST_SEPARATION  DETERMINISM
```

Every required validator bound to an applicable contract must pass. An applicable
contract with **zero** required validators is a `COVERAGE_GAP` — never a pass.

Validators are plain child processes run after explicit local consent. There is no
sandbox claim and no network-restriction claim.

## Receipt semantics

Pre-commit:

```
Owned scope        DECLARED / CHECKED
Foreign staged     OBSERVED
Completion state   reviewable candidate, only when all evidence obligations pass
Commit             NONE
```

Post-commit:

```
Owned scope        VERIFIED
Foreign staged     EXCLUDED or UNKNOWN
Checked content    BOUND
Commit             CREATED (never pushed)
Verdict            REVIEWABLE only if every completion invariant holds
```

`VERIFIED` and `EXCLUDED` never appear before the proof exists. The user-facing verdict
vocabulary is exactly `REVIEWABLE`, `INCOMPLETE`, and `NOT_REVIEWABLE`.

## Agent adapters

Claude Code and Codex are adapters behind a narrow common interface. An adapter may not
widen the core command surface.

## Explicit non-features

No telemetry. No daemon. No background watcher. No hook installation. No model calls.
No auto-commit. No push. No numerical safety score.

## Platform status

```
macOS      supported target for v1
Linux      a later proof obligation, tied to an actually advertised artifact
Windows    out of scope for v1
```

Runtime and distribution remain deliberately late-bound, which is why this repository
contains no source or test directories yet.
