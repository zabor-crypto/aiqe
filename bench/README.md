# Benchmarks

This directory holds the benchmark protocol and, for each implemented product
surface, the fixture builders and the retained results.

```
protocol/           the method, the families, and the release gates      PRESENT
fixtures/           shared measurement and fixture-construction helpers  PRESENT
fixtures/doctor/    deterministic builders, controls, expected outcomes  PRESENT
fixtures/task/      deterministic builders, controls, expected outcomes  PRESENT
fixtures/check/     deterministic builders, controls, expected outcomes  PRESENT
fixtures/commit/    deterministic builders, controls, expected outcomes  PRESENT
release/            release-proof machinery: environment, artifacts,
                    support gate, controls                               PRESENT
results/doctor/     retained result artifact                             PRESENT
results/task/       retained result artifact                             PRESENT
results/check/      retained result artifact                             PRESENT
results/commit/     retained result artifact                             PRESENT
results/release/    retained release-proof manifest                      PRESENT
```

Nothing is present here for a surface that does not exist. The whole v1 command
surface is implemented, so all four families are materialised.

## Rendering what the results say

Two published surfaces are generated from the retained artifacts rather than written:
the terminal captures under [`../docs/assets/captures/`](../docs/assets/captures/), and
the benchmark totals in the README between its `benchmarks:` markers.

```
python3 bench/render-assets.py            report drift, exit 1 if any
python3 bench/render-assets.py --write    regenerate both
```

Copying a total out of prose is how a published number stops matching the artifact it
came from, so no number in the README's benchmark block was typed. The test suite runs
the check-mode invocation, so drift fails there too.

## What the zero-tolerance quantities count

The README publishes these totals, so each one has to mean something exact. Four are
measured by every family; the rest belong to the family named beside them.

```
repository_mutations            changed paths anywhere in the repository, `.git`
                                included. Doctor and Task only: `check` and
                                `commit` run repository-declared code and create
                                a commit, so neither can make this claim, and
                                each narrows it below instead.

repository_defined_executions   canaries that the repository installed and that
                                fired - a filter driver, a hook, an fsmonitor.
                                Counts executions AIQE caused, not mutations.

local_state_writes              changes under the isolated HOME and XDG tree
                                *outside* AIQE's own permitted state home. It is
                                not a claim that AIQE writes no local state: a
                                task operation writes machine-local state under
                                `$XDG_STATE_HOME/aiqe/` by design, and those
                                changes are counted separately, as
                                `aiqe_state_changes`, where a non-zero value is
                                expected. This quantity is what catches a write
                                landing anywhere else.

model_calls                     invocations of any model endpoint. AIQE contains
                                none; the quantity exists so that the absence is
                                measured rather than asserted.

network_requests                sockets opened during the case. See the release
                                proof for the narrower runtime claim and its
                                limit: it is conclusive for Python code and says
                                nothing about a non-Python child process.
```

Each family's own narrowing - `aiqe_core_repository_mutations`,
`aiqe_core_worktree_mutations`, `unconsented_validator_executions`,
`precommit_reviewable_verdicts`, `raw_terminal_control_bytes`,
`policy_canary_executions` and `aiqe_push_calls` - is defined where that family is
described below.

## Running a family

```
python3 bench/run-doctor-fixtures.py
python3 bench/run-task-fixtures.py
python3 bench/run-check-fixtures.py
python3 bench/run-commit-fixtures.py
```

Every case is built from nothing in an isolated temporary directory, with an isolated
`HOME`, XDG directories and global Git configuration, then run under the measurement
harness and compared against the expectation recorded in
[`fixtures/doctor/cases.json`](fixtures/doctor/cases.json). The runner rewrites
[`results/doctor/results.json`](results/doctor/results.json) and exits non-zero if any
case disagrees with its expectation or any negative control stops reproducing.

The Task family drives the real command-line entry point as subprocesses. Concurrency,
crash-atomicity and byte-preserving argv cannot be measured in-process, and putting every
case through the same door means no case is proven against a path the user does not take.

The check family does the same, and its safety claim is narrower than the other two,
so it is stated exactly. Doctor changes nothing; a task operation changes AIQE's own
machine-local state and nothing else; `aiqe check` runs code the repository declared,
and that code can write wherever the user can. "The repository did not change" is
therefore not available as a claim, and pretending otherwise would be the overstatement
this product exists to refuse. Instead every observed repository change is attributed
to exactly one cause — an authorised `aiqe init` write, a fixture validator's declared
side effect, the scenario's own declared action, or AIQE core — and only the last is
zero-tolerance:

```
aiqe_core_repository_mutations      = 0
unconsented_validator_executions    = 0
precommit_reviewable_verdicts       = 0
raw_terminal_control_bytes          = 0
```

The last of those is counted by any scenario that renders repository-controlled text -
a validator's argument vector or its output - to a human surface. Newline is AIQE's own
layout and is excluded; ESC, carriage return, BEL, backspace, DEL and the C1 range are
what an attacker uses to move a cursor or repaint a line, and none of them may reach a
terminal.

The attribution lists are declared per scenario in the builders, so a case cannot
quietly acquire permission to write by writing somewhere new. Every fixture validator
records *each* run, in a directory outside every snapshot root, so the second quantity
is counted rather than argued. A canary named with the `observed.` prefix records an
observation rather than a validator execution and is never counted as an unconsented
one — the detached-child case leaves one deliberately.

The bounded-commit family narrows the claim once more, because the command under
measurement creates a commit:

```
aiqe_core_worktree_mutations        = 0
policy_canary_executions            = 0
aiqe_push_calls                     = 0
precommit_reviewable_verdicts       = 0
raw_terminal_control_bytes          = 0
```

Changes under `.git` are attributed to the completion commit rather than denied.
`POLICY_CANARY_EXECUTIONS` counts every commit hook, filter driver and signing program
a policy fixture installs, each writing a marker outside the repository, so
"the refusal happened before anything ran" is measured rather than argued. And every
proof is read back with the harness's own Git invocations — parent, changed pathset,
blob and mode per path, staged delta before and after — rather than from AIQE's
rendering of them. A proof only the product can see is not a proof.

Three cases in this family are proofs rather than behaviours:

```
pty_consent_denied                        a real pseudo-terminal, answered no
pty_consent_accepted_and_persisted        answered yes, then persisted, then drifted
detached_child_escapes_the_process_group  what the termination claim does not cover
```

Consent is driven through a real Unix pseudo-terminal against the real CLI rather than
through an injected prompt callable, because the decision under test is whether AIQE
asks at all — and that decision is made by looking at whether standard input and output
are terminals. The detached-child case spawns a child that calls `setsid` and observes
it surviving the group kill: AIQE terminates the process group it created, and a fixture
that could not tell that apart from "terminates every descendant" would let the
stronger, false claim back into the documentation.

Two more measure bounds rather than semantics: `large_output_bounded` and
`large_output_with_timeout` emit far past the retention budget — the second of them
without ever stopping — and assert that the run completes, the retained output stays
within the budget, and the evidence record stays small.

Five cases damage AIQE's own machine-local state and require a refusal rather than a
repair — a world-writable state root, a group-readable worktree directory, a 0644
consent store, a symlinked consent store — plus one proving that ordinary pre-existing
state keeps working at 0700 and 0600 under `umask(0)`.

Three more supply repository-controlled text aimed at the terminal:

```
malicious_consent_denied      an argv carrying ESC[2J and a second prompt, answered no
malicious_consent_accepted    the same, answered yes - and what the digest binds
malicious_validator_output    a validator that fails while printing a screen clear
```

The pseudo-terminal is put in raw mode for these, with echo and output post-processing
off, so the transcript is exactly the bytes AIQE wrote rather than the line discipline's
rendering of them. Otherwise the question "did AIQE emit a control character" would be
answered about the terminal's own work.

Each of the six launch contract families has its own three fixtures — covered, failed,
and coverage gap. One family standing in for six would leave five with no evidence at
all.

`compare-results.py` selects the retained artifact from the family the fresh run names,
and checks it on headline numbers rather than bytes, because the artifact records the Git version it was produced
under and two correct machines legitimately differ there.

A case may declare a platform restriction. The arbitrary-byte path case needs a
filesystem that accepts non-UTF-8 filenames, which APFS does not provide, so it runs on
Linux and is reported as `SKIPPED_PLATFORM` elsewhere — named in the results, never
dropped from the listing. The comparison treats a case that one machine could run and
the other could not as a platform difference rather than a disagreement.

## The release proof

The four families measure what AIQE does to a repository. The release proof
measures something they cannot see: whether the artifact a user would install
is the thing that was tested, and on which machines that has been shown.

```
python3 bench/run-suite.py --output /tmp/surface-suite.json
python3 bench/run-release-proof.py --output /tmp/surface-artifact.json
python3 bench/aggregate-release-proof.py --surfaces /tmp/surfaces --output /tmp/release-proof.json
```

Each run writes a **surface record**: the machine, the interpreter, the Git
version, the runner provenance, the evidence level, and every test it skipped.
The aggregator collects the records and applies the support gate in
[`release/support.py`](release/support.py), which marks a claim `PROVEN` only
when observations back it and `NOT_PROVEN` otherwise. A skipped case is not a
pass, and `--parts` selections are recorded so a reduced run cannot be read as
a full one.

The release proof builds an sdist and a wheel from an exported
tracked-content-only source tree, installs each into a fresh environment, and
runs the whole workflow from the installed console script in a directory that
is not the source tree, ending in `REVIEWABLE`. It also measures the uv and
uvx paths, the offline runtime under a proven-armed socket canary, build
reproducibility across two clean builds, the artifact allowlist and the
extracted-artifact scans. Method and current verdicts:
[`../docs/support.md`](../docs/support.md).

## Negative controls

The release proof has three of its own, in
[`release/controls.py`](release/controls.py), for the failure modes packaging
introduces and no amount of source-tree testing can see:
`NC-PACKAGE-SOURCE-IMPORT` (a module missing from the artifact, which the
naive source-tree import does not notice), `NC-PACKAGE-PRIVATE-FILE` (a
synthetic private file the pattern scan passes and the artifact allowlist
rejects), and `NC-SUPPORT-CLAIM` (a contiguous version range extrapolated from
its endpoints, which the support gate refuses).

Each control in [`fixtures/doctor/controls.py`](fixtures/doctor/controls.py) is a
reference naive diagnostic workflow — the obvious way to obtain the same information —
that violates a frozen Doctor invariant. `control_reproduces_failure` is recorded per
control. A control that stops reproducing is broken and must be redesigned; it is never
counted as a pass, because a control that cannot fail proves nothing about a product
that passes.

## Current state

```
Doctor family         RUN       (results retained here)
Task scope family     RUN       (results retained here)
Check / receipt /
  evidence family     RUN       (results retained here)
Numerical routing     RUN       (six contract families, in the check family)
Bounded commit        RUN       (results retained here)
Release proof         RUN       (manifest retained in results/release/)
Product friction      NOT_RUN   (no public release exists)
Context efficiency    NOT_RUN   (deferred; methodology not yet defensible)

macOS baseline        observed
Linux baseline        exercised in CI, not a release claim
Windows               out of scope for v1
```

Four families have moved off `NOT_RUN`, and only for the cases that exist. No
aggregate benchmark completion is claimed.

The bounded-commit family measures a command that writes, so its zero is stated
differently from the others: `AIQE_CORE_WORKTREE_MUTATIONS = 0`. The index, the object
database, HEAD and the reflog are attributed to the completion commit rather than
denied, because `.git` byte immutability is not a claim a command that creates a commit
can make honestly. Its other zeros are `POLICY_CANARY_EXECUTIONS = 0` — no hook, filter
driver or signer ever ran — `AIQE_PUSH_CALLS = 0`, and no `REVIEWABLE` verdict without
a commit behind it.

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
diagnostics sections       retained, and compared by nothing
```

The last line is a narrow exception with one occupant. A quantity belongs in a
`diagnostics` section when two *correct* runs legitimately disagree about it,
and `diagnostics` is stripped — at document level and inside every case —
before `compare-results.py` looks at anything.

`diagnostics.aiqe_commit_git_writes` is why it exists. Several bounded-commit
cases race a concurrent process against AIQE's own window on purpose, and Git
writes a different number of objects, lock files and reflog entries depending
on how that race lands: 292 and 295 were observed on one machine minutes
apart, from four cases, with every zero-tolerance total and every case outcome
identical. Comparing that number would make a correct family flaky; deleting
it would lose a real measurement. So it is recorded and named
unauthoritative, and the stable fact underneath it —
`aiqe_commit_git_writes_observed`, whether a case's completion commit wrote
through Git at all — stays in the authoritative record and is compared like
everything else.

A regression in [`../tests/test_commit_fixtures.py`](../tests/test_commit_fixtures.py)
holds the exclusion in place from both directions: two documents differing
only in that count must agree, and a change to a quantity that does carry
authority must still be caught.

A result file is an output. Editing one by hand converts the benchmark from evidence into
decoration.

See [`protocol/protocol.md`](protocol/protocol.md) for the method and
[`protocol/families.md`](protocol/families.md) for the case families.
