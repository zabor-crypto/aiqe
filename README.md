# AIQE — AI Quant Engineering

> **DONE ISN'T EVIDENCE.**

AIQE is the assurance layer for AI-assisted quant engineering.
It bounds the change, keeps unrelated Git state out of the commit,
runs your project-native checks, and shows what remains unknown.

---

**Status: the whole v1 workflow is implemented and tested, end to end.**

`aiqe doctor`, `aiqe init`, `aiqe task`, `aiqe check`, `aiqe commit` and `aiqe receipt`
are real: they run, they are covered by a deterministic test suite, and their safety
contracts are measured from outside the process rather than self-reported. `commit` was
the last command to arrive, and with it `REVIEWABLE` — a verdict that had deliberately
been unreachable — became reachable. Nothing here is released and no version is tagged.

The output below was produced by `aiqe doctor` against benchmark case
`checkin_filter_configured`, a synthetic fixture built from nothing by
[`bench/fixtures/doctor/builders.py`](bench/fixtures/doctor/builders.py). It is copied
from the retained result artifact, not typed by hand.

```
AIQE DOCTOR

  Repository      ordinary worktree · git 2.50.1
  Git state       repository-safe view · on a branch · 0 staged · ? unstaged · 0 untracked
  Topology        single worktree · sparse checkout off
  Operations      none in progress
  AIQE config     absent
  Agent surface   Claude Code absent · Codex absent
  Commit policy   check-in filter configured · tracked .gitattributes

  UNKNOWN      WORKING_STATE_UNSTAGED_UNKNOWN
      The unstaged count is unknown: determining it would make Git run the
      check-in filter configured in this repository, and Doctor executes
      nothing the repository defines.

  FINDING      CHECKIN_FILTER_CONFIGURED
      A check-in filter driver is configured. Git runs it as a child process
      when comparing worktree content, so Doctor does not make that
      comparison.

  FINDING      TRACKED_GITATTRIBUTES
      A tracked .gitattributes file is present. It can bind paths to filter
      drivers that change content on check-in.

  1 unknown · 2 findings
```

That `UNKNOWN` is the product working. The repository configures a check-in filter, and
determining the unstaged count would make Git execute that filter as a child process.
Doctor does not execute what a repository defines, so it does not ask the question, and
it says so instead of printing a confident zero.

`repository-safe view` is the other half of the same honesty. Doctor counts the working
state with configuration from outside the repository suppressed, so nothing external can
be executed while it looks. That is a well-defined question, but it is *not* the question
`git status` answers under every user and global Git configuration, and the label says so
rather than leaving it to be assumed. Details: [`docs/doctor.md`](docs/doctor.md).

macOS is the supported target for v1 · Linux support is a later proof obligation · Windows is out of scope for v1

No telemetry. No network calls. No model calls. No daemon. No background watcher.
AIQE never pushes.

---

## Trying it

AIQE is a Python package with no third-party dependencies. It needs Python 3.11 or
newer, and is not published to any index yet, so install it from a clone:

```bash
python3 -m venv .venv && .venv/bin/pip install .
```

Or from a built artifact, with pip or with uv — both paths are exercised by the
release proof against a local wheel:

```bash
uvx --from ./dist/aiqe-0.1.0a0-py3-none-any.whl aiqe doctor
```

Where AIQE has actually been shown to run, and where it has not:
[`docs/support.md`](docs/support.md).

```bash
.venv/bin/aiqe doctor
```

`aiqe doctor` works before `aiqe init`, on a repository it has never seen, and on a
directory that is not a repository at all. It requires no configuration, writes nothing,
and makes no network request.

```bash
.venv/bin/aiqe doctor --format json
```

Reference for the output, the finding codes and the exit status:
[`docs/doctor.md`](docs/doctor.md).

### The workflow

```bash
.venv/bin/aiqe init
```

`init` writes exactly one repository path — `./aiqe.toml` — after showing you the
complete file and asking. Nothing else: not `.gitignore`, not a hook, not your shell
profile. `aiqe init --print` renders the same file and writes nothing at all.

The scaffold it writes declares **no** surfaces and **no** validators, because AIQE has
no safe way to discover what in your repository is quant-critical. A guess that
happened to be wrong would be a configuration nobody wrote and everybody trusts.
Reference: [`docs/config.md`](docs/config.md).

Declare what a piece of work owns, change those files, and check them:

```bash
.venv/bin/aiqe task start --own src/strategy/alpha.py
.venv/bin/aiqe check
```

The output below is `aiqe check` against benchmark case `causality_coverage_gap`, a
synthetic fixture built from nothing by
[`bench/fixtures/check/builders.py`](bench/fixtures/check/builders.py). It is copied
from the retained result artifact, not typed by hand.

```
AIQE CHECK

  Owned paths     1 declared · 1 changed
  Classification  1 quant · 0 non-quant · 0 unclassified

  Contracts
      CAUSALITY              COVERAGE_GAP   no required validator declares it

  Validators
      unit                   required  PASS
      causality              optional  PASS

  Evidence        CURRENT
  Completion      INCOMPLETE
  Reasons         COVERAGE_GAP
```

Every validator the repository declares **passed**. The unit suite is green, and so is
an optional causality validator. The answer is still not a pass, because the changed
file sits on a surface declared to carry `CAUSALITY` and **no required validator is
bound to that contract**. Nothing in the repository was written to detect a lookahead
defect, so the contract is unmeasured — and unmeasured looks exactly like passing to
every other tool.

An optional validator never closes that gap, and neither does a generic test suite. A
suite that was not written to detect a lookahead defect does not become evidence about
lookahead by succeeding.

Reference: [`docs/check.md`](docs/check.md).

### The receipt, and the verdict it will not give you

With the contract properly covered, every pre-commit obligation is discharged. Here is
what `aiqe receipt` says anyway — again, copied from the retained artifact for case
`causality_covered`:

```
AIQE RECEIPT

  Owned scope     CHECKED
  Owned paths     1 declared · 1 changed
  Foreign staged  OBSERVED
  Checked content CHECKED
  Evidence        CURRENT
  Commit          NONE
  Push            NOT_PERFORMED_BY_AIQE

  Classification  1 quant · 0 non-quant · 0 unclassified
  Contracts       1 applicable · 1 covered · 0 gap · 0 failed · 0 unknown
  Validators      2 applicable · 2 pass · 0 fail · 0 unknown · 0 unavailable
  Required        2 of them · 2 passed

  Verdict         INCOMPLETE
  Reason          BOUNDED_COMMIT_NOT_CREATED

  Receipt schema  2 · policy aiqe.receipt.default.v1
  AIQE            0.1.0a0
```

`INCOMPLETE`, on a completely green check. That is the product working. `REVIEWABLE` is
a claim about a commit whose content is provably the checked content, and no commit
exists yet, so **no pre-commit state can reach it** — a property the test suite asserts
over every combination of classification, coverage, consent, staleness and validator
outcome this build can produce.

The default receipt is what you paste into a pull request, so it carries counts,
states, reason ids and a verdict, and nothing else: no path, no filename, no repository
name, no branch, no commit id, no validator command line, no output, no username, no
hostname. The exclusion list is property-tested against the fixture's real values.
`aiqe receipt --local` shows you the rest, locally.

Reference: [`docs/receipt.md`](docs/receipt.md).

### The commit, and the verdict it earns

```
aiqe commit -m "bounded completion"
```

That is the whole surface. There is no `--amend`, no `--no-verify`, no `--allow-empty`
and no `--push`, and their absence is the feature: each of them is a way to make the
command succeed by weakening the claim it makes.

The commit is `git commit --only` over the exact expected changed pathset, with literal
pathspec semantics, after a preflight that resolves the **effective** Git configuration
the real commit would use — includes and all. An active commit hook, configured signing,
or an external check-in filter bound to an owned path is a refusal, never a bypass.

Output from benchmark case `commit-owned-modification`, copied from the retained result
artifact:

```
AIQE COMMIT

  Owned scope     VERIFIED
  Committed paths 1
  Foreign staged  EXCLUDED
  Checked content BOUND
  Commit          CREATED
  Push            NOT_PERFORMED_BY_AIQE

  Verdict         REVIEWABLE

  The commit contains exactly the owned changed pathset, its content is
  the checked content, and the staged work AIQE did not own is unchanged.
  See `aiqe receipt`.
```

Every word of that is a proof, not a summary. `VERIFIED` means the parent-to-commit
changed pathset was read back from the object database and equals the expected owned
pathset. `BOUND` means each committed blob and mode equals the check-in state derived
before the commit — which under `core.autocrlf` is deliberately *not* the worktree
bytes. `EXCLUDED` means the structured staged delta over every path the task does not
own was identical immediately before and immediately after.

And then the receipt, from the same retained case:

```
AIQE RECEIPT

  Owned scope     VERIFIED
  Owned paths     1 declared · 1 changed
  Foreign staged  EXCLUDED
  Checked content BOUND
  Evidence        CURRENT
  Commit          CREATED
  Push            NOT_PERFORMED_BY_AIQE

  Classification  1 quant · 0 non-quant · 0 unclassified
  Contracts       1 applicable · 1 covered · 0 gap · 0 failed · 0 unknown
  Validators      1 applicable · 1 pass · 0 fail · 0 unknown · 0 unavailable
  Required        1 of them · 1 passed
  Committed paths 1

  Verdict         REVIEWABLE

  Receipt schema  2 · policy aiqe.receipt.default.v1
  AIQE            0.1.0a0
```

`REVIEWABLE`, at last, and only here. If the foreign staged state had moved by so much
as one newly appearing entry, this would say `Foreign staged UNKNOWN` and
`Verdict INCOMPLETE` — a negative control drives exactly that, with a concurrent process
staging a file inside AIQE's own window.

The shareable receipt still names nothing: no commit id, no filename, no branch. It
gained a state and a count.

Reference: [`docs/commit.md`](docs/commit.md).

### Validators run only after you say so

`aiqe.toml` is tracked content: anyone who can land a commit can declare a validator
naming any command on your machine. So a declaration is a proposal, not authorization.
AIQE runs nothing until you consent, on this machine, to that **exact** validator
definition — its id, argument vector, timeout, required flag and contracts, bound by a
digest. Change any of them and the consent no longer applies.

Consent is never stored in `aiqe.toml`, in tracked content, or in `.git`. `--allow
<id>` authorises one run and records nothing. A non-interactive or `--format json`
check never prompts: the outcome is `UNKNOWN` with `CONSENT_REQUIRED`, which is neither
a pass nor a failure.

AIQE makes **no sandbox, filesystem or network claim** about a validator — it runs as
you — and the consent prompt says so before it asks.

### Evidence that expires

A check binds the exact content of every owned path, the commit, the raw `aiqe.toml`
bytes and the validator definitions. `aiqe receipt` recomputes that binding rather than
trusting a stored verdict, so editing an owned file, moving HEAD, or editing the
configuration turns `CURRENT` into `STALE` — without re-running a single validator, and
without fingerprinting your whole worktree.

The same measurement happens on both sides of validator execution. A validator that
edits the file it was checking and exits 0 does not produce current evidence, whatever
its exit status says.

### A bounded unit of work

Declare what a piece of work owns, before doing it:

```bash
.venv/bin/aiqe task start --own src/strategy.py --own tests/test_strategy.py
```

```bash
.venv/bin/aiqe task
```

```bash
.venv/bin/aiqe task end
```

Ownership is **exact**: owning `foo` owns `foo`, and not `foo/bar` or `foobar`. v1 owns
an exact pathset of regular files — declaring a directory, a symlink or the same path
twice is refused — because a prefix rule would let a task authorise files that did not
exist when the scope was declared, which is the widening an owned scope exists to
prevent. A declared path is literal (`--own '*'` declares a file named `*`, not a
pattern) and need not exist yet, because declaring `src/new_module.py` before writing it
is the normal case.

Task state is **machine-local**, under `$XDG_STATE_HOME/aiqe/`, keyed by an HMAC of the
repository's Git directories so the key names no repository. Nothing is written inside
`.git`, and starting a task changes nothing in the repository at all: staged work you
never mentioned is byte-identical afterwards.

Reference for the scope rules, the state schema and the exit status:
[`docs/task.md`](docs/task.md).

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
doctor    inspect the environment before anything is changed   IMPLEMENTED
init      write ./aiqe.toml                                    IMPLEMENTED
task      declare an immutable owned scope for a unit of work  IMPLEMENTED
check     run the validators bound to the applicable contracts IMPLEMENTED
commit    create a bounded completion commit, or refuse        IMPLEMENTED
receipt   render what is proven, what is excluded, and what is unknown
                                                               IMPLEMENTED
```

The v1 surface is closed and has no remaining design target.

The owned scope is fixed when a task starts and cannot widen, as an exact pathset.
Checks run against that scope. The receipt reports one of three verdicts —
`REVIEWABLE`, `INCOMPLETE`, or `NOT_REVIEWABLE` — and never invents a fourth, softer
one. `REVIEWABLE` requires a bounded commit whose parent, pathset and content have all
been proved.

Full command surface and exit semantics: [`docs/architecture.md`](docs/architecture.md).
Per-command references: [`doctor`](docs/doctor.md), [`init` and
`aiqe.toml`](docs/config.md), [`task`](docs/task.md), [`check`](docs/check.md),
[`commit`](docs/commit.md), [`receipt`](docs/receipt.md).

## Change integrity

AIQE bounds what a completion commit is allowed to contain.

- The owned scope is immutable from task start and uses exact literal file paths in v1:
  a declared path owns itself and nothing else.
- Git caller paths use literal-pathspec semantics, so a filename containing a glob
  character cannot silently expand the change.
- Foreign staged state — anything staged outside the owned scope — is captured as a
  structured delta before and after, against the same baseline. If it drifts in any
  direction, including a *newly appearing* entry, the answer is `UNKNOWN`, not a shrug.
- Intent-to-add is transactional, and a failure scope-rolls back exactly what AIQE
  created rather than restoring a whole saved index over somebody else's staged work.
- Committed content is proved against the *expected check-in state*, so a correct commit
  under `core.autocrlf` is not reported as a mismatch, and a wrong one still is.
- AIQE never pushes. The Git allowlist it runs through contains no network subcommand,
  and the guard raises rather than degrading.

The user-facing guarantee is stated narrowly and deliberately:

> AIQE's bounded commit contains only the expected owned changed pathset.

## Evidence integrity

A check that succeeded earlier does not describe a commit made later. AIQE binds them.

At `check`, a bounded cryptographic state binding is recorded for every
owned path, covering file content, new-file and deletion states, relevant mode and
type, and the digests of the configuration and evidence definitions in force. The same
bounded authority is measured immediately before and after the validators run, so a
validator that modifies what it checks cannot leave evidence that calls itself current.
`aiqe receipt` recomputes it to decide freshness, and never re-runs a validator to do
so.

At `commit`, that binding is recomputed immediately before the first index mutation —
after every expensive preflight step, because the gap between "checked" and "committed"
is the whole staleness surface. If it differs, the evidence is stale and the commit is
refused with nothing written. After the commit, AIQE verifies the parent, verifies that
the changed pathset is exactly the expected owned pathset, and verifies that each
committed blob and mode equals the check-in state derived beforehand. If any of that
cannot be demonstrated, the receipt does not say `REVIEWABLE` — and AIQE does not reset,
revert or amend the commit away to make the report tidier.

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
single most important behaviour in the product: silence is not evidence. Each of the
six families has its own deterministic fixtures proving all three outcomes — covered,
failed, and coverage gap — because one family standing in for six would leave five with
no evidence at all.

Surface patterns are AIQE's own small documented grammar over raw path bytes, and are
never handed to Git.

Details: [`docs/config.md`](docs/config.md) and
[`bench/protocol/families.md`](bench/protocol/families.md).

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
| *(current)* | `doctor`, `init`, `task`, `check`, `commit` and `receipt` implemented, tested, and benchmarked. The v1 command surface is complete. Nothing released or tagged. |
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
