# Architecture

This document is the public statement of AIQE's frozen v1 architecture. It describes
what the product does and where its guarantees stop.

All of it is now implemented. `aiqe doctor`, `aiqe init`, `aiqe task`, `aiqe check`,
`aiqe commit` and `aiqe receipt` exist and are tested, and the v1 command surface has
no remaining design target. Nothing here is released and no version is tagged.

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
aiqe --help | -h | help

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

Everything above is implemented. `aiqe commit` was the last command to arrive, and it
arrived with its implementation rather than as a stub, because a command that parses
and does nothing advertises a capability the product has not built.

The complete workflow therefore exists today:

```
aiqe doctor
aiqe init
aiqe task start --own <path>...
    change the owned files
aiqe check
aiqe commit -m <message>
aiqe receipt
```

`aiqe commit` takes exactly one flag. There is no `--amend`, no `--no-verify`, no
`--allow-empty` and no `--push`: each of them is a way to make the command succeed by
weakening the claim it makes.

References: [`config.md`](config.md) for `aiqe.toml` and `init`,
[`check.md`](check.md), [`receipt.md`](receipt.md).

The task boundary answers which exact repository paths a unit of work owns — a declared
path owns itself and nothing else — and deliberately nothing further: not whether checks
passed, not whether evidence is fresh, and not whether the work is reviewable.
Reference: [`task.md`](task.md).

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

aiqe doctor
  0  a valid first-contact diagnostic was produced, findings included
  3  a valid Doctor result could not be produced: an invalid invocation, or a
     repository topology that cannot be diagnosed
```

Doctor never exits 1 or 2: those codes belong to commands that adjudicate completion,
and Doctor adjudicates nothing. A finding is part of a valid diagnostic, not a process
failure. Full reference: [`doctor.md`](doctor.md).

`aiqe init` exits 0 or 3 only, for the same reason: it writes a file or it does not,
and it adjudicates nothing either.

`aiqe receipt` exits 0 for `REVIEWABLE`, which **no pre-commit state can reach**. A
completely green check yields `INCOMPLETE` with reason `BOUNDED_COMMIT_NOT_CREATED`,
because `REVIEWABLE` is a claim about a commit whose content is provably the checked
content. Only a verified bounded commit produces it. See [`receipt.md`](receipt.md)
and [`commit.md`](commit.md).

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

At `check` — implemented — AIQE records a bounded cryptographic state binding for
every owned path, covering regular-file content state, new-file state, deletion
markers, relevant mode and type, and the digests of the configuration and evidence
definitions in force. That binding is also measured immediately before and after
validator execution, so a validator that edits the file it is checking cannot leave
behind evidence that calls itself current.

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
doing so bypasses no explicit repository policy, and the effect is documented:
`core.fsmonitor`, `gc.auto` and `maintenance.auto`, none of which changes what a commit
contains. Implemented; see [`commit.md`](commit.md).

When commit is unsupported, `check` and `receipt` remain available and the user commits
with ordinary Git.

## Numerical integrity

Quant surfaces are classified as `QUANT_SURFACE`, `EXPLICIT_NON_QUANT_SURFACE`, or
`UNCLASSIFIED`. All matching surfaces are evaluated and their contract obligations
union, so adding a surface can never reduce an obligation. A path declared both quant
and non-quant is a `CONFIG_CONFLICT` and fails closed. Surface patterns are AIQE's own
small documented grammar over raw path bytes, and are never handed to Git.
Implemented; see [`config.md`](config.md) and [`check.md`](check.md).

Six umbrella contracts ship at launch:

```
CAUSALITY   DATA_ALIGNMENT   EXECUTION_REALISM
ACCOUNTING  TRAIN_TEST_SEPARATION  DETERMINISM
```

Every required validator bound to an applicable contract must pass. An applicable
contract with **zero** required validators is a `COVERAGE_GAP` — never a pass.

Validators are plain child processes run after explicit local consent, recorded
machine-locally per validator definition digest and never in tracked content. A
definition change revokes it by identity mismatch. Timeouts are mandatory, and a
timeout is a `FAIL`. There is no sandbox claim, no filesystem-restriction claim and no
network-restriction claim. The measured invariant is
`UNCONSENTED_VALIDATOR_EXECUTIONS = 0`, not the absence of repository-defined
execution: here that execution is expected, after consent.

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

## Agents

There is no adapter, plugin, extension, MCP server or hook, and none is required: an
agent invokes `aiqe` as an ordinary command, like any other tool in its shell.
`doctor`, `check` and `receipt` take `--format json`; every command's exit status is
the uniform one above. That is the whole machine-readable interface.

Should an adapter ever exist, it may not widen the core command surface. Working
guidance for Claude Code and Codex: [`agents.md`](agents.md).

## Explicit non-features

No telemetry. No daemon. No background watcher. No hook installation. No model calls.
No auto-commit. No push. No numerical safety score.

## The Git floor, and why it is a refusal

Before any command that reaches Git, AIQE reads `git --version` and refuses if
the toolchain cannot deliver the invariant every command rests on.

```
3   GIT_TOO_OLD_FOR_CONFIG_ISOLATION   Git is older than 2.32
3   GIT_VERSION_UNKNOWN                the version could not be read
```

`aiqe --version` and the three help spellings are exempt: they reach no
repository. Asking a tool how it is invoked is the one question it has to be
able to answer on a machine where it would refuse to do anything else, so help
is answered before the preflight and exits `0`.

AIQE's configuration isolation works by pointing `GIT_CONFIG_SYSTEM` and
`GIT_CONFIG_GLOBAL` at the null device. Both were introduced in Git 2.32. An
older Git does not know the names, so it does not read them **and does not
complain**: the isolation is applied, the command succeeds, and the user's
global configuration is in scope throughout. `GIT_CONFIG_NOSYSTEM` declines the
*system* file only and is not a fallback for it.

That is not a cosmetic gap. It was measured on Debian 11 (Git 2.30.2): the
Doctor negative control for a globally defined filter driver stopped
reproducing, and the bounded-commit policy preflight created a commit where it
must have refused. A confident answer with the isolation silently absent is
the failure this product exists to refuse, so AIQE declines to produce one.

Refusing on an unreadable version is the same decision: the alternative is
assuming the best about an unknown toolchain.

Full account, including how the floor was found:
[`support.md`](support.md#3-the-git-compatibility-boundary).

## Platform status

```
macOS      exercised on every claimed interpreter minor
Linux      exercised on every claimed interpreter minor
Windows    out of scope for v1
Git        2.32 or newer, enforced; older is refused, not degraded
```

Which surfaces have actually been run, at what evidence level, and what is
still `NOT_PROVEN`: [`support.md`](support.md) and the retained manifest it
points at. Nothing in this document is the authority on that; the manifest is.

## Runtime

The runtime is no longer late-bound. AIQE is implemented as a Python package with **no
third-party runtime dependencies and no third-party test dependencies**; the test suite
runs on the standard library `unittest` module. Python 3.11 is the support floor, and
3.11 through 3.14 are each exercised rather than inferred from the ends of the range.

The choice follows from what the product has to be correct about. Doctor is a thin,
careful layer over Git process invocation and filesystem inspection, and the hard parts
are byte-safe path handling, NUL-delimited machine output, and provable zero-write
behaviour — none of which any candidate runtime makes materially easier or harder. What
differed was the cost of proving it: a dependency-free package that installs and tests
without a build step keeps the auditable surface small, which matters more for an
assurance layer than for most software.

A single-file distribution remains available later by bundling, and is required by no
frozen contract. Doctor is small enough that if this choice proves wrong, replacing it
is a bounded rewrite rather than an architectural unwind — which is the property that
made it safe to decide now.

Directory layout follows from that choice:

```
src/aiqe/     the package
tests/        the deterministic suite
bench/        fixture builders, expected outcomes, retained results
docs/         the command references
```

`aiqe.toml` is read with the standard library's `tomllib`, which is why Python 3.11 is
the support floor. No third-party dependency was added for it.

Task state is machine-local, under `$XDG_STATE_HOME/aiqe/`, in a directory named by an
HMAC of the repository's canonical Git directories under a machine-local salt. Not the
tracked worktree, and deliberately not inside `.git`: a tool claiming not to touch your
repository should not keep its own filing cabinet inside it. Including the per-worktree
Git directory in the key is what gives two linked worktrees two independent tasks, and
the key names no repository, so a state directory listing is not an inventory of
someone's projects.
