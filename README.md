# AIQE — AI Quant Engineering

> **DONE ISN'T EVIDENCE.**

AIQE is the assurance layer for AI-assisted quant engineering.
It bounds the change, keeps unrelated Git state out of the commit,
runs your project-native checks, and shows what remains unknown.

This is what it leaves behind. Not a summary of a run — the artifact:

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

Every line is a measurement rather than a summary. `VERIFIED`: the parent-to-commit
changed pathset was read back from the object database and equals the declared owned
pathset. `BOUND`: every committed blob and mode equals the content the validators
checked. `EXCLUDED`: the staged work this task did not own was byte-identical before and
after. `REVIEWABLE` is reachable only when all three hold — and the receipt still names
nothing: no path, no repository, no branch, no commit id, no username. It came from
synthetic benchmark case `commit-owned-modification`, copied from the retained result
artifact. **No terminal output in this repository was typed by hand.**

**Status: the whole v1 workflow is implemented, tested, and validated end to end
against retained conformance fixtures.**
`aiqe doctor`, `aiqe init`, `aiqe task`, `aiqe check`, `aiqe commit` and `aiqe receipt`
are real, and their safety contracts are measured from outside the process rather than
self-reported. Nothing is released and no version is tagged.

```bash
python3 -m venv .venv && .venv/bin/pip install . && .venv/bin/aiqe doctor
```

macOS and Linux are proven surfaces · Windows is out of scope for v1 ·
[where it runs](#where-it-runs)

No telemetry. No network calls. No model calls. No daemon. No background watcher.
AIQE never pushes.

---

## AIQE in 30 seconds

```
your agent changes code

  aiqe task start --own …    the exact pathset is declared up front,
                             and cannot widen afterwards

  aiqe check                 your repository's own validators run, and only
                             after you consent to each one on this machine;
                             the quant contracts that apply to the changed
                             surface are evaluated, and an applicable
                             contract with no required validator is a gap,
                             not a pass

  aiqe commit -m "…"         a bounded commit is created over exactly that
                             pathset and then proved — parent, pathset,
                             content, and the untouched foreign index — or
                             it is refused, with nothing written

  aiqe receipt               REVIEWABLE · INCOMPLETE · NOT_REVIEWABLE
```

### Before, and after

```
BEFORE                                   AFTER

the agent says the tests pass            the pathset was declared before the work
what it touched is whatever it touched   the commit contains exactly that pathset
your index came along for the ride       foreign staged state is excluded and proved
"the checks passed" — which checks?      each validator is named, with its outcome
the check nobody wrote is invisible      an uncovered contract is reported as a gap
the check ran, then the file changed     checked content is bound to the commit
done means somebody said done            the verdict names what is still unknown
```

None of that is a claim that your numbers are right. It is the difference between a
statement and an artifact.

### The three unknowns

An agent edits your backtest. It reports that the tests pass. Three separate things are
now unknown, and none of them are visible in that sentence:

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

A synthetic strategy with a one-character causality defect, in four acts:

```bash
python3 examples/lookahead-demo/run.py
```

The strategy decides at each bar whether the window rose, and a decision made at bar
`i` may only read bars strictly before `i`. One constant says otherwise:

```python
DECISION_LAG = 0    # must be 1
```

The project's own generic suite passes over it — the suite is not wrong, it was
answering a different question. A validator written to ask the causality question does
not:

```
AIQE CHECK

  Owned paths     1 declared · 1 changed
  Classification  1 quant · 0 non-quant · 0 unclassified

  Contracts
      CAUSALITY              CONTRACT_FAILED causality

  Validators
      unit                   required  PASS
      causality              required  FAIL         exit 1

  Evidence        CURRENT
  Completion      NOT_REVIEWABLE
  Reasons         REQUIRED_VALIDATOR_FAILED · CONTRACT_FAILED
```

**Remove that validator and everything the repository has still passes.** AIQE reports
`COVERAGE_GAP` rather than a green result: the contract applies to the changed surface,
no required validator is bound to it, and the absence of a check is not a pass. That
act matters more than the first. The first shows a check catching a defect; the second
shows the state nobody sees, where nobody looked and the output was green anyway.

The last two acts are about the commit rather than the checks, and each runs the
reference workflow first, in its own copy of the same repository, so the contrast is
measured rather than asserted.

```
unrelated work is already staged. Stage the change you meant to make, commit,
and read back what the commit turned out to contain:

  git add -- src/strategy/momentum.py
  git commit --quiet --message 'widen the momentum window'
      src/foreign.py
      src/strategy/momentum.py

  aiqe commit -m 'widen the momentum window'
      src/strategy/momentum.py
```

And the fourth act: check, keep editing, commit. The reference workflow commits content
no check ever saw — the same causality check, re-run against what was actually
committed, fails. AIQE recomputes its binding immediately before the first index
mutation, refuses with `STALE_OWNED_CONTENT`, and creates no commit.

Everything the demo produced is retained under
[`examples/lookahead-demo/results/`](examples/lookahead-demo/results/), failures
included. The failures are the demo. What it does and does not prove:
[`examples/lookahead-demo/`](examples/lookahead-demo/).

## Five-minute quickstart

AIQE is a Python package with no third-party dependencies. It needs Python 3.11 or
newer, and it is not published to any index yet, so install it from a clone.

**1 · Install.**

```bash
python3 -m venv .venv && .venv/bin/pip install .
```

It also installs from a built wheel or sdist and runs under uv — `pip install` from
each artifact, `uv tool install` and `uvx --from` are all exercised by the release
proof, against a local artifact, on every surface it runs:

```bash
uvx --from ./dist/aiqe-0.1.0a0-py3-none-any.whl aiqe doctor
```

**2 · Look at the repository before changing anything.**

```bash
.venv/bin/aiqe doctor
```

`doctor` works before `aiqe init`, on a repository it has never seen, and on a
directory that is not a repository at all. It needs no configuration, writes nothing,
and makes no network request. Here it is on benchmark case
`checkin_filter_configured`:

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
it says so instead of printing a confident zero. `repository-safe view` is the same
honesty applied to the count itself: Doctor looks with configuration from outside the
repository suppressed, which is a well-defined question but *not* the one `git status`
answers under every user and global configuration, and the label says so.
Reference: [`docs/doctor.md`](docs/doctor.md).

**3 · Declare what the repository contains.**

```bash
.venv/bin/aiqe init
```

`init` writes exactly one repository path — `./aiqe.toml` — after showing you the
complete file and asking. Nothing else: not `.gitignore`, not a hook, not your shell
profile. `aiqe init --print` renders the same file and writes nothing at all.

The scaffold declares **no** surfaces and **no** validators, because AIQE has no safe
way to discover what in your repository is quant-critical. A guess that happened to be
wrong would be a configuration nobody wrote and everybody trusts. You declare which
paths are quant surfaces, which contracts they carry, and which commands check them:

```toml
schema = 1

[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY"]

[[surface]]
paths = ["tests/**", "docs/**"]
quant = false

[[validator]]
id = "unit"
run = ["pytest", "-q", "tests/unit"]
required = true
timeout = 300

[[validator]]
id = "causality"
run = ["python", "checks/no_lookahead.py"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
```

Reference: [`docs/config.md`](docs/config.md).

**4 · Declare what this piece of work owns, before doing it.**

```bash
.venv/bin/aiqe task start --own src/strategy/alpha.py
```

Ownership is **exact**: owning `foo` owns `foo`, and not `foo/bar` or `foobar`. A
prefix rule would let a task authorise files that did not exist when the scope was
declared, which is the widening an owned scope exists to prevent. A declared path is
literal — `--own '*'` declares a file named `*`, not a pattern — and need not exist
yet, because declaring `src/new_module.py` before writing it is the normal case.

Task state is machine-local, under `$XDG_STATE_HOME/aiqe/`, keyed by an HMAC of the
repository's Git directories so the key names no repository. Nothing is written inside
`.git`, and starting a task changes nothing in the repository at all.
Reference: [`docs/task.md`](docs/task.md).

**5 · Change the code — you, or your agent — then check it.**

```bash
.venv/bin/aiqe check
```

Benchmark case `causality_coverage_gap`:

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
bound to that contract**. Nothing here was written to detect a lookahead defect, so the
contract is unmeasured — and unmeasured looks exactly like passing to every other tool.
An optional validator does not close that gap, and neither does a generic suite.
Reference: [`docs/check.md`](docs/check.md).

**6 · Ask what is proven.**

```bash
.venv/bin/aiqe receipt
```

With the contract properly covered, every pre-commit obligation is discharged. Here is
what the receipt says anyway, from case `causality_covered`:

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
exists yet, so **no pre-commit state can reach it** — a property the suite asserts over
every combination of classification, coverage, consent, staleness and validator outcome
this build can produce. `aiqe receipt --local` shows you what the shareable receipt
leaves out. Reference: [`docs/receipt.md`](docs/receipt.md).

**7 · Complete it.**

```bash
.venv/bin/aiqe commit -m "bounded completion"
```

That is the whole surface. There is no `--amend`, no `--no-verify`, no `--allow-empty`
and no `--push`, and their absence is the feature: each is a way to make the command
succeed by weakening the claim it makes. An active commit hook, configured signing, or
an external check-in filter bound to an owned path is a refusal, never a bypass — see
[Change integrity](#change-integrity). Case `commit-owned-modification`:

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

Then `aiqe receipt` again, and this time it says `REVIEWABLE` — the receipt at the top
of this page. Reference: [`docs/commit.md`](docs/commit.md).

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

The owned scope is fixed when a task starts and cannot widen. Checks run against that
scope. The receipt reports one of three verdicts — `REVIEWABLE`, `INCOMPLETE`, or
`NOT_REVIEWABLE` — and never invents a fourth, softer one.

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

At `check`, a bounded cryptographic state binding is recorded for every owned path,
covering file content, new-file and deletion states, relevant mode and type, and the
digests of the configuration and evidence definitions in force. The same bounded
authority is measured immediately before and after the validators run, so a validator
that modifies what it checks cannot leave evidence that calls itself current.
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

Six umbrella contracts ship at launch. Each names a class of defect that a generic test
suite does not detect, because a generic suite was not written to ask about it:

```
CAUSALITY               information reaching a decision from a bar, a row or a
                        timestamp that had not happened yet when the decision
                        was made

DATA_ALIGNMENT          series joined on the wrong key, index, timezone or
                        resample boundary, so two things line up that never
                        co-occurred

EXECUTION_REALISM       fills, costs, slippage, latency and borrow that a real
                        venue would not have given you at that moment

ACCOUNTING              positions, cash, fees, financing and corporate actions
                        that do not reconcile to an identity that must hold

TRAIN_TEST_SEPARATION   fitting, selection, tuning or normalisation that saw
                        the evaluation period, including through a shared
                        preprocessing step

DETERMINISM             a result that does not reproduce from the same inputs,
                        seeds, ordering and environment
```

You declare which surfaces carry which contracts, and which of your own commands check
them. AIQE ships no validator: a check that AIQE wrote would be a check that does not
know your data.

Every required validator bound to an applicable contract must pass. **A contract that
applies but has zero required validators is a `COVERAGE_GAP`, not a pass.** This is the
single most important behaviour in the product: silence is not evidence. Each of the six
families has its own deterministic fixtures proving all three outcomes — covered, failed
and coverage gap — because one family standing in for six would leave five with no
evidence at all.

### What a contract result means, exactly

> **AIQE does not prove universal numerical truth.**
>
> It proves that the declared required validators for the applicable contracts ran, and
> what their outcomes were.
>
> **`PASS` is not universal correctness.** It is the recorded outcome of a command your
> repository declared, under a recorded task and configuration state.

A `COVERED` contract means every required validator bound to it succeeded. It does not
mean the contract holds. Whether your causality validator actually detects lookahead is
a property of your validator, and AIQE has no way to know it — which is why the
contract's coverage and the validator's outcome are reported as two separate facts
rather than collapsed into one verdict.

Surface patterns are AIQE's own small documented grammar over raw path bytes, and are
never handed to Git. Details: [`docs/config.md`](docs/config.md) and
[`bench/protocol/families.md`](bench/protocol/families.md).

## Working with Claude Code and Codex

AIQE is an ordinary command-line program, and that is the whole integration. There is no
plugin, no extension, no MCP server, no wrapper and no adapter: your agent runs `aiqe`
the way it runs `pytest`. What you get back is an artifact you can regenerate yourself —
`aiqe receipt` recomputes its binding rather than trusting a stored verdict — instead of
a sentence the agent wrote about its own work.

```bash
aiqe task start --own src/strategy/alpha.py --own tests/test_alpha.py
# … the agent edits exactly those files …
aiqe check --allow unit --allow causality
aiqe commit -m "bounded completion"
aiqe receipt
```

The scope is declared by **you**, before the agent starts, and cannot widen afterwards.
Consent is yours too, and `--allow <id>` is where it can quietly stop being: a flag the
agent writes for itself is the agent consenting on your behalf, to a validator declared
in tracked content the agent can also edit. Pin the ids you are willing to run, or
approve them interactively. `aiqe doctor` reports whether an agent's own configuration
in this repository grants unconstrained execution, which is worth knowing before you
hand it a task.

Working guidance, including what to put in `CLAUDE.md` or `AGENTS.md` and why the agent
must never be the thing that decides its own scope:
[`docs/agents.md`](docs/agents.md).

## Conformance evidence

These are conformance families: deterministic fixtures, regressions and adversarial
negative controls that measure whether AIQE behaves as specified. They say nothing
about how fast anything is, or about anyone's productivity — no user-effect benchmark
exists yet.

<!-- benchmarks:begin -->
Rendered from the retained result artifacts under
[`bench/results/`](bench/results/) by
[`bench/render-assets.py`](bench/render-assets.py). No number below was
copied from prose, and a test fails if this block and those artifacts
disagree.

```
family              cases  passed  failed  skipped    controls
doctor                 41      40       0        1      7 of 7
task                   25      24       0        1      5 of 5
check                  46      46       0        0      4 of 4
bounded commit         37      36       0        1      8 of 8
                      ---     ---     ---      ---     -------
                      149     146       0        3    24 of 24
```

The retained run is AIQE 0.1.0a0 on darwin. Every skipped case is skipped for a stated
platform reason and is listed in the artifact rather than dropped from it:

```
commit-non-utf8-name
non_utf8_owned_path
non_utf8_path
```

Each family also declares zero-tolerance quantities, measured from outside the
process rather than reported by it. What each one counts is defined by the family
that measures it — see [`bench/README.md`](bench/README.md). Across all four families,
every one of them stands at zero:

```
aiqe_core_repository_mutations
aiqe_core_worktree_mutations
aiqe_push_calls
local_state_writes
model_calls
network_requests
policy_canary_executions
precommit_reviewable_verdicts
raw_terminal_control_bytes
repository_defined_executions
repository_mutations
unconsented_validator_executions
```

A negative control is a workflow that *must* fail, kept so that a gate which
has stopped detecting anything is caught here rather than believed. The method
and the families are in [`bench/protocol/protocol.md`](bench/protocol/protocol.md) and
[`bench/protocol/families.md`](bench/protocol/families.md).
<!-- benchmarks:end -->

## Where it runs

Every line below is gated against a run that happened. The evidence is
[`bench/results/release/release-proof.json`](bench/results/release/release-proof.json),
the method is [`docs/support.md`](docs/support.md), and a test fails if this section
claims a Python version the manifest does not.

<!-- support:begin -->
**PROVEN** — by the retained full-lane release-proof manifest, at the source commit
that manifest itself names, which is **not** the current HEAD. On that evidence the
installed artifact runs the whole workflow to `REVIEWABLE` on every claimed OS family,
and the full behavioural suite passes:

```
Python 3.11 · 3.12 · 3.13 · 3.14        macOS and Linux
```

Under a documented tiering: the installed-artifact end-to-end runs on **both**
families for **all four** minors; the full suite runs on Linux for all four and
on macOS at 3.11 and 3.14. What that gives up — a defect only on macOS, only on
3.12 or 3.13, and only outside the end-to-end — is stated in
[`docs/support.md`](docs/support.md), and the manifest records which families
ran the suite for each minor.

**TESTED** — the surfaces actually exercised, at the level recorded:

```
macOS 26      arm64     full suite · installed artifact
macOS 15      arm64     installed artifact
macOS 15      x86_64    installed artifact
Ubuntu 24.04  x86_64    full suite · installed artifact
Ubuntu 24.04  arm64     full suite · installed artifact
Ubuntu 22.04  x86_64    full suite · installed artifact
Debian 11     x86_64    artifact builds and installs; AIQE refuses to run
Git 2.55.0              every surface above except Debian 11
```

**NOT PROVEN** — no run supports these, so nothing claims them:

```
Git 2.32 to 2.54        the floor is enforced; no surface runs a Git in it
Other distributions     only the three above were exercised
Other macOS releases    only 15 and 26
Reproducible sdist      the wheel is, under a fixed SOURCE_DATE_EPOCH; the
                        sdist is not, and every packaged file is identical
                        either way
```

**OUT OF SCOPE**

```
Windows                 no implementation work, and no metadata claims it
Publication             no tag, no release, nothing on any index
Standalone executable   DEFERRED - no measured install friction justifies it
```

Git older than 2.32 is refused rather than degraded: the configuration
isolation every AIQE command rests on did not exist before that release, and
an older Git ignores the request silently. See
[`docs/support.md`](docs/support.md).
<!-- support:end -->

### Packaging

```
FORM              a standard Python package: wheel and sdist
PYTHON            >= 3.11
RUNTIME DEPS      0 third-party packages
INSTALL PATHS     pip install (wheel), pip install (sdist),
                  uv tool install, uvx --from
ENTRY POINT       the `aiqe` console script
STANDALONE BINARY DEFERRED
```

`DEFERRED` is not a roadmap entry. No measured install friction justifies a standalone
executable today, so none is planned, promised or dated. If that changes it will change
because of evidence, and this line will say so.

### External CI

The support claims above come from a release-proof manifest aggregated from real runs,
at the source commit the manifest itself names — which is **not** the current HEAD. CI
runs in two lanes: an ordinary push exercises Linux surfaces only, and the full matrix
runs on a tag or a manual dispatch. Only the full lane produces a manifest that can
carry a support claim, and no complete CI run has attested the current HEAD, so nothing
here claims one has. The gap, and the condition that closes it, are recorded in
[`docs/support.md`](docs/support.md#11-the-attestation-this-manifest-does-not-carry).

What the current HEAD *has* had is a fast-lane run, and it passed. Every job it
executed succeeded, which establishes by execution:

```
Ubuntu 22.04  x86_64    full suite · installed artifact
Ubuntu 24.04  x86_64    full suite · installed artifact
Ubuntu 24.04  arm64     full suite · installed artifact
Debian 11     x86_64    artifact builds and installs; AIQE refuses to run
```

The macOS matrix did not run in that lane, so it is not evidence about macOS at this
commit, and the manifest it produced records every claimed Python minor as
`NOT_PROVEN` — naming the missing observation rather than rounding up. That manifest is
kept as a fast-lane artifact and is deliberately not interchangeable with the retained
one above.

A green run on the fast lane is not a support claim, and the gate says so rather than
leaving it to be assumed: with no macOS surface record, every claimed Python minor comes
back `NOT_PROVEN`, naming the observation it did not get. There is no CI badge on this
page, for the same reason there is no safety score: a badge is read as a maturity claim,
and one sourced from a lane that never touched half the matrix would be a false one.

## Security and trust model

The full threat model, the trust boundaries and the vulnerability reporting process are
in [`SECURITY.md`](SECURITY.md). The parts that change how you should use AIQE:

**Validators are arbitrary repository-defined code.** `aiqe.toml` is tracked content.
Anyone who can land a commit can declare a validator naming any command on your machine.

**Nothing runs without your explicit local consent**, bound to that exact validator
definition by a digest. Consent lives outside the repository and outside `.git`, and a
changed definition revokes it.

**There is no sandbox.** AIQE makes no filesystem-containment and no network-restriction
claim about a validator. It runs as you, with your privileges, and can do anything your
shell can do. AIQE bounds *how long* it runs — it terminates the process group it
created on timeout — and that is a narrower claim than containment: a descendant that
calls `setsid` outlives the kill, and a fixture is kept that demonstrates exactly that.

**AIQE core makes no network request.** There is no network feature to disable, no
telemetry, no update check, no daemon and no background watcher. AIQE never pushes: the
Git allowlist it runs through contains no network subcommand.

**A bounded commit is refused, never forced.** An active commit hook, a configured
signing requirement, or a check-in filter bound to an owned path makes the bounded
commit `UNSUPPORTED`. AIQE will not pass `--no-verify` or `--no-gpg-sign` to make the
refusal go away, because doing so would silently discard a policy your repository set.

**Local evidence is machine-local and unencrypted.** Task state, consent records and
evidence live under `$XDG_STATE_HOME/aiqe/`, readable by you. AIQE does not defend
against a process running as your own user, or as root, on your own machine — that
process can already read and write everything AIQE can. Nothing here is a claim about
same-UID or root isolation.

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

**AIQE does not police ordinary Git.** It does not intercept your commits, and post-hoc
verification of externally created commits is not a v1 feature.

**There is no safety score.** AIQE produces no number summarising how safe a change is,
and no badge on this page implies one.

Also not in scope: it is not an agent runtime, not a backtester, not an orchestrator,
not a sandbox, not a telemetry platform, not a linter and not a CI system. It installs
no hooks and runs nothing in the background.

## Milestones

| Milestone | Meaning |
|---|---|
| *(current)* | `doctor`, `init`, `task`, `check`, `commit` and `receipt` implemented, tested, and validated against retained conformance fixtures. The v1 command surface is complete. Installable artifacts build, install and run on the surfaces in [Where it runs](#where-it-runs). The failure-first demo is materialised and retained. Nothing released or tagged. |
| `v0.1.0` | First installable alpha: `doctor`, `init`, `task`, `check`, `receipt` on macOS. Real tests in real CI. |
| `v0.2.0` | `commit` with checked-content binding, all six contracts, benchmark fixtures and retained results. |
| `v0.3.0` | Rendered visual assets, from the retained terminal captures. |
| `v1.0.0` | Every release gate green against retained artifacts. Command surface stable. Every public claim traced to evidence. |

No conformance number appears in this README unless it is generated from a retained result
artifact. No result is hidden, including failures and cases that were never run.

Every claim on this page is classified — proven, observed, not proven, design intent or
out of scope — against the artifact it rests on, in [`docs/claims.md`](docs/claims.md).
A claim absent from that inventory is one this project does not make.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions carry a clean-room and
public-data attestation; there is no CLA and no DCO.

## License

[Apache License 2.0](LICENSE).
