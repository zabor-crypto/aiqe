# AIQE — AI Quant Engineering

> **DONE ISN'T EVIDENCE.**

For quant developers and research engineers running Claude Code, Codex or a similar agent
against real strategy, backtest and research repositories. AIQE bounds the change, keeps
unrelated Git state out of the commit, runs your project-native checks, and shows what
remains unknown.

Your agent says the tests pass. That does not bound what changed; it says nothing about
the check nobody wrote, because absent and passing look identical to every other tool; and
it proves nothing numerically — one shifted index leaks a future bar into a signal, every
test still passes, and the equity curve becomes fiction.

Here is what it leaves behind instead — not a summary of a run, the artifact:

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

`VERIFIED`: the changed pathset was read back from the object database and equals the
declared owned pathset. `BOUND`: every committed blob and mode equals what the validators
checked. `EXCLUDED`: staged work this task did not own was byte-identical before and
after. `REVIEWABLE` needs all three — and it still names nothing: no path, no repository,
no branch, no commit id, no username. **No terminal output on this page was typed by
hand.**

**What it cannot prove: that your numbers are right.** `PASS` means a validator your
repository declared exited zero, and nothing more — [the full
boundary](#what-aiqe-does-not-do--and-cannot-prove).

The v1 workflow is implemented, tested and validated against retained conformance
fixtures. The package version is `0.1.0a0`. Whether a Git tag, a GitHub Release or a
package-index entry exists for it is established from that object, not from this page.

```bash
python3 -m venv .venv && .venv/bin/pip install . && .venv/bin/aiqe doctor
```

Or see the argument first — no install, no network, about ten seconds:

```bash
python3 examples/lookahead-demo/run.py
```

Proven on macOS and Linux by a retained full-lane release proof — at the commit that
manifest names, which is not this one. No macOS evidence is claimed for any other commit.
Windows is out of scope. [Where it runs](#where-it-runs).

No telemetry. No network calls. No model calls. No daemon. AIQE never pushes.

---

## AIQE in 30 seconds

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

None of that says your numbers are right. It is the difference between a statement and an
artifact.

AIQE is deterministic and contains no model calls. The v1 surface is closed, and the
receipt reports `REVIEWABLE`, `INCOMPLETE` or `NOT_REVIEWABLE` — never a fourth, softer
verdict. [`docs/architecture.md`](docs/architecture.md), and per command:
[`doctor`](docs/doctor.md), [`init`](docs/config.md), [`task`](docs/task.md),
[`check`](docs/check.md), [`commit`](docs/commit.md), [`receipt`](docs/receipt.md).

## Failure-first demo

A synthetic strategy with a one-character causality defect, in four acts. A decision made
at bar `i` may read only bars strictly before `i`. One constant says otherwise:

```python
DECISION_LAG = 0    # must be 1
```

The project's generic suite passes over it — not wrong, just answering a different
question. A validator written to ask the causality question is not:

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

That is the act people expect. **The second is the one that matters: remove that validator
and everything the repository has still passes.** AIQE reports `COVERAGE_GAP` rather than
a green result — the contract applies, nothing required is bound to it, and the absence of
a check is not a pass. The first act shows a check catching a defect; the second shows the
state nobody sees, where nobody looked and it was green.

Acts 3 and 4 concern the commit, each running the reference workflow first so the contrast
is measured rather than asserted: act 3 reads back what each commit contained ([Change
integrity](#change-integrity)); act 4 edits after checking, so the reference workflow
ships content no check saw while AIQE refuses with `STALE_OWNED_CONTENT`.

The demo writes to a temporary directory and leaves this repository clean, retaining
everything it produced — failures included, and the failures are the demo:
[`examples/lookahead-demo/`](examples/lookahead-demo/).

## Five-minute quickstart

No third-party dependencies, Python 3.11 or newer, installed from this checkout — no
package index involved.

**1 · Install.**

```bash
python3 -m venv .venv && .venv/bin/pip install .
```

Wheel, sdist and uv installs are exercised by the release proof too — see
[Packaging](#packaging).

**2 · Look at the repository before changing anything.**

```bash
.venv/bin/aiqe doctor
```

`doctor` needs no configuration, writes nothing, and works on a repository it has never
seen. Conformance case `checkin_filter_configured`:

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

That `UNKNOWN` is the product working: counting unstaged files would make Git run this
repository's check-in filter, and Doctor executes nothing a repository defines — so it
says so rather than print a confident zero. [`docs/doctor.md`](docs/doctor.md).

**3 · Declare what the repository contains.**

```bash
.venv/bin/aiqe init
```

`init` writes exactly one repository path — `./aiqe.toml` — after showing you the file and
asking. It declares **no** surfaces and **no** validators: a wrong guess about what is
quant-critical would be a configuration nobody wrote and everybody trusts.
[`examples/aiqe.toml`](examples/aiqe.toml) illustrates all six contracts; its validator
commands are placeholders, and writing them is yours.
[`docs/config.md`](docs/config.md).

**4 · Declare what this piece of work owns, before doing it.**

```bash
.venv/bin/aiqe task start --own src/strategy/alpha.py
```

Ownership is **exact**: owning `foo` owns `foo`, not `foo/bar` or `foobar` — a prefix rule
would let a task authorise files that did not exist when the scope was declared. Task
state is machine-local, and nothing is written inside `.git`.
[`docs/task.md`](docs/task.md).

**5 · Change the code — you, or your agent — then check it.**

```bash
.venv/bin/aiqe check
```

Conformance case `causality_coverage_gap`:

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

Every validator the repository declares **passed**, and the answer is still not a pass:
the changed file sits on a surface carrying `CAUSALITY` and **no required validator is
bound to it**. Unmeasured looks exactly like passing to every other tool.
[`docs/check.md`](docs/check.md).

**6 · Ask what is proven.**

```bash
.venv/bin/aiqe receipt
```

With the contract covered and every pre-commit obligation discharged, case
`causality_covered` still says:

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

`INCOMPLETE`, on a completely green check: `REVIEWABLE` is a claim about a commit, and no
commit exists yet, so **no pre-commit state can reach it**.
[`docs/receipt.md`](docs/receipt.md).

**7 · Complete it.**

```bash
.venv/bin/aiqe commit -m "bounded completion"
```

There is no `--amend`, `--no-verify`, `--allow-empty` or `--push`: each would make the
command succeed by weakening the claim it makes. Case `commit-owned-modification`:

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

Ask for the receipt again and it says `REVIEWABLE` — the one at the top of this page.

### Validators run only after you say so

`aiqe.toml` is tracked content: anyone who can land a commit can declare a validator
naming any command on your machine, so a declaration is a proposal, not authorization.
AIQE runs nothing until you give explicit local consent to that **exact** definition,
bound by a digest and never stored in `aiqe.toml` or `.git`. A non-interactive check never
prompts — the outcome is `UNKNOWN` with `CONSENT_REQUIRED`, neither pass nor failure.

Conformance case `consent_withheld`:

```
AIQE CHECK

  Owned paths     1 declared · 1 changed
  Classification  1 quant · 0 non-quant · 0 unclassified

  Contracts
      CAUSALITY              CONTRACT_UNKNOWN causality

  Validators
      unit                   required  UNKNOWN      CONSENT_REQUIRED
      causality              required  UNKNOWN      CONSENT_REQUIRED

  Evidence        CURRENT
  Completion      INCOMPLETE
  Reasons         REQUIRED_VALIDATOR_UNKNOWN · CONTRACT_UNKNOWN
```

`UNKNOWN` is a third answer rather than a soft failure. The validators did not run, so
the contract they were bound to is `CONTRACT_UNKNOWN` — not covered, and not failed
either. A tool that resolved this to a pass would be guessing, and one that resolved it
to a failure would be reporting a defect nobody measured.

## Change integrity

AIQE bounds what a completion commit may contain. Foreign staged state is captured as a
structured delta before and after against the same baseline, and if it drifts in any
direction — including a *newly appearing* entry — the answer is `UNKNOWN`, not a shrug.
AIQE never pushes: its Git allowlist contains no network subcommand.

The demo's third act, measured — the same repository and staged work, through each
workflow:

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

The guarantee is stated narrowly and deliberately:

> AIQE's bounded commit contains only the expected owned changed pathset.

A check that succeeded earlier does not describe a commit made later, so AIQE binds them.
At `check` a cryptographic state binding is recorded for every owned path and measured
again after the validators run, so a validator that modifies what it checks cannot leave
evidence calling itself current. At `commit` it is recomputed immediately before the first
index mutation, and a difference refuses the commit with nothing written. AIQE then
verifies the parent, the changed pathset and every committed blob and mode; if any of that
cannot be demonstrated the receipt does not say `REVIEWABLE`, and AIQE does not reset,
revert or amend the commit away to tidy the report: [`docs/commit.md`](docs/commit.md).

## Numerical integrity

Quant surfaces are classified explicitly, every matching surface is evaluated and their
obligations union, and declaring a path both quant and non-quant fails closed. Six
umbrella contracts ship at launch, each a class of defect a generic suite does not detect
because it was never written to ask:

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

You declare which surfaces carry which contracts and which of your own commands check
them. AIQE ships no validator: a check AIQE wrote would not know your data.

Every required validator bound to an applicable contract must pass. **A contract that
applies but has zero required validators is a `COVERAGE_GAP`, not a pass.** Silence is not
evidence. All six families have fixtures proving all three outcomes.

> **AIQE does not prove universal numerical truth.**
>
> It proves that the declared required validators for the applicable contracts ran, and
> what their outcomes were.
>
> **`PASS` is not universal correctness.** It is the recorded outcome of a command your
> repository declared, under a recorded task and configuration state.

A `COVERED` contract does not mean the contract holds: whether your causality validator
detects lookahead is a property of your validator, which is why coverage and outcome stay
two facts, not one verdict.

## Working with Claude Code and Codex

AIQE is an ordinary command-line program, and that is the whole integration. No plugin, no
extension, no MCP server, no adapter — your agent runs `aiqe` the way it runs `pytest`.

```bash
aiqe task start --own src/strategy/alpha.py --own tests/test_alpha.py
# … the agent edits exactly those files …
aiqe check --allow unit --allow causality
aiqe commit -m "bounded completion"
aiqe receipt
```

The scope is declared by **you**, before the agent starts, and cannot widen. Consent is
yours too — and `--allow <id>` is where it quietly stops being, because a flag the agent
writes for itself is the agent consenting on your behalf, to a validator in tracked
content it can edit. Guidance: [`docs/agents.md`](docs/agents.md).

## Conformance evidence

Three categories stay apart here, permanently. **Conformance evidence** is deterministic
fixtures, regressions and adversarial negative controls measuring whether AIQE behaves as
specified. **Platform attestation** is executed OS, Python and CI evidence — [Where it
runs](#where-it-runs). A **user-effect benchmark** compares what changes for the people
using it.

No user-effect benchmark has been published. Everything below measures AIQE's own
behaviour, and none of it claims a productivity, development-time, token or context
reduction, model-performance, or defect-prevention effect.
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
the method [`docs/support.md`](docs/support.md); a test fails if this section claims a
Python version the manifest does not.
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
Publication             not covered by this evidence: a tag, a release or an
                        index entry is established from that object
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

`DEFERRED` is not a roadmap entry: no measured install friction justifies a standalone
executable, so none is planned, promised or dated.

### External CI

CI runs in two lanes: a push exercises Linux only, the full matrix runs on a tag or
manual dispatch. Only the full lane produces a manifest that can carry a support claim,
and the manifest retained here was aggregated at an earlier commit, so nothing on this
page attests the commit you are reading. Whether a full-lane run exists for that exact
commit is answered by the run's own head and run identity, never by a tracked file:
[`docs/support.md`](docs/support.md#11-the-attestation-this-manifest-does-not-carry).

A push to `main` runs the fast lane, over these surfaces:

```
Ubuntu 22.04  x86_64    full suite · installed artifact
Ubuntu 24.04  x86_64    full suite · installed artifact
Ubuntu 24.04  arm64     full suite · installed artifact
Debian 11     x86_64    artifact builds and installs; AIQE refuses to run
```

What that establishes is bound to the run that produced it and to the commit that run
names — not to the branch, and not to whatever `main` points at when you read this. The
fast lane touches no macOS surface, so the manifest it produces records every claimed
Python minor as `NOT_PROVEN`, naming the missing observation rather than rounding up, and
the retained full-lane evidence above applies only to the commit its own manifest names.

There is no CI badge here for the same reason there is no safety score: a badge asserts a
branch is green, while the thing worth knowing is which commit was measured and on what.
A run's own record answers that; a badge cannot.

## Security and trust model

Full threat model and reporting: [`SECURITY.md`](SECURITY.md). What changes how you use
AIQE:

**Validators are arbitrary repository-defined code** run under your explicit local consent
([above](#validators-run-only-after-you-say-so)). **There is no sandbox.** AIQE makes no
filesystem-containment and no network-restriction claim about a validator: it runs as you,
with your privileges. AIQE bounds *how long* it runs, which is narrower than containment —
a descendant that calls `setsid` outlives the kill, and a fixture demonstrates it.

**A bounded commit is refused, never forced.** A commit hook, a signing requirement or a
check-in filter on an owned path makes it `UNSUPPORTED`, and AIQE will not pass
`--no-verify` to make that go away.

**Local evidence is machine-local and unencrypted.** AIQE does not defend against a
process running as your own user, or as root — it can already read and write everything
AIQE can. No same-UID or root isolation is claimed.

## What AIQE does not do — and cannot prove

This section is load-bearing: an assurance tool that overstates its guarantees is worse
than no assurance tool.

**`PASS` means your validator succeeded. Nothing more.** AIQE guarantees the command was
invoked under the recorded task and configuration state, that its outcome was recorded,
and that the owned source state it checked is bound to the eventual commit. It does
**not** guarantee the validator consumed every artifact you intended, that caches were
fresh, that its logic is correct, or that its data was causally fresh.

**Write confinement is scoped, not global.** AIQE core's writes are confined to declared
owned paths, `./aiqe.toml` during `init`, and local state outside the repository. That is
*not* a claim that validators cannot mutate foreign files, that Git cannot mutate its own
internal state, or that foreign untracked bytes stay identical.

**AIQE does not police ordinary Git**, and post-hoc verification of externally created
commits is not a v1 feature. **There is no safety score**, and no badge implies one; no
user-effect benchmark has been published, so nothing claims a productivity,
token-efficiency or defect-prevention effect.

Also not in scope: not an agent runtime, not a backtester, not an orchestrator, not a
sandbox, not a telemetry platform, not a linter, not a CI system. No hooks, nothing in the
background.

## Milestones

| Milestone | Meaning |
|---|---|
| `v0.1.0a0` | First alpha candidate, and the package version this source carries: v1 command surface complete, tested, validated against retained conformance fixtures. Artifacts build, install and run on the surfaces in [Where it runs](#where-it-runs). A tag, release or index entry for it is established from that object, not from this table. |
| `v1.0.0` | Every release gate green against retained artifacts. Command surface stable. |

No conformance number appears here unless generated from a retained artifact, and no
result is hidden. Every claim is classified against its evidence in
[`docs/claims.md`](docs/claims.md); a claim absent from that inventory is one this project
does not make.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions carry a clean-room and public-data
attestation; there is no CLA and no DCO.

## License

[Apache License 2.0](LICENSE).
