# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

An `Unreleased` section is always present. Entries are added in the pull request that
makes the change, not at release time.

## [Unreleased]

### Added

- **[`examples/aiqe.toml`](examples/aiqe.toml), a worked six-contract configuration.**
  `aiqe init` deliberately scaffolds no surfaces and no validators, and the README
  illustrated one contract of six, so a reader had nothing to copy for the other five.
  This is an illustration, not a starting point: every validator in it names a command
  that does not exist until you write it, so copying it unchanged reports those
  validators `UNAVAILABLE` with `EXECUTABLE_NOT_FOUND`, their contracts
  `CONTRACT_UNKNOWN`, and a refused completion — never a pass. An example whose checks
  passed out of the box would be a green result nobody earned, from the one tool that
  exists to say green is not evidence. Two tests keep it honest: one parses it through
  the real fail-closed parser and requires all six families both declared on a surface
  and bound to a required validator, the other refuses any validator that would succeed
  without checking anything.

- **A demo summary on standard output.** `python3 examples/lookahead-demo/run.py` printed
  three lines while the argument sat on line 210 of a transcript nobody opened. It now
  prints what the four acts measured, with act 2 given the room — the state where every
  check the repository declares passes because nobody wrote the applicable one. The
  `COVERAGE_GAP` row is lifted out of the rendered `AIQE CHECK` rather than described,
  and every other value is read from the same record that `expected.json` gates, so a
  summary disagreeing with the product fails the run that printed it.

- **`aiqe --help`, `aiqe -h` and `aiqe help`.** All three print the canonical usage
  text on standard output and exit `0`. The surface previously had no help spelling at
  all: `--help` fell through to the unknown-argument path, printing usage to standard
  error and exiting `3`, so the conventional way to ask a tool how to run it looked
  like a failure to every wrapper, packaging check and first-time reader. Help is
  answered before the Git preflight, so it works where every other command would
  refuse. Unknown commands still exit `3`, and no CLI framework or dependency was
  added.

- **[`docs/claims.md`](docs/claims.md), the launch-claims inventory.** Every externally
  visible factual claim, classified `PROVEN` / `OBSERVED` / `NOT_PROVEN` /
  `DESIGN_INTENT` / `OUT_OF_SCOPE` against the retained artifact it rests on, with its
  known limitation and the surfaces allowed to carry it. A claim absent from it may not
  appear on a public surface. It is a boundary document, deliberately small, and not a
  claims database.
- **A definition for every published zero-tolerance quantity**, in
  [`bench/README.md`](bench/README.md), where the README already sent readers for them.
  Six of the twelve had none. `local_state_writes` needed one most: it counts writes
  under the isolated home *outside* AIQE's own permitted state directory, and is not the
  claim that AIQE writes no local state — a task operation writes machine-local state by
  design, counted separately as `aiqe_state_changes`.
- **A positive control for a letter-suffixed internal phase identifier.** The
  `INTERNAL_PHASE_ID` scanner class accepted a trailing `R` only, so a letter-suffixed
  id passed the scan and survived in a tracked benchmark fixture and a test docstring.
  The class now matches any single trailing letter, the corpus carries the shape that
  got through, and both instances are sanitised. Widening what a class *detects* is not
  widening it into an ignore, which stays forbidden.

### Changed

- **The lookahead demo no longer writes into the repository.** `--output` defaulted to
  the tracked `examples/lookahead-demo/results/`, and the transcript legitimately carries
  a task start timestamp that differs between runs, so an ordinary run of the demo left
  the reader an uncommitted diff in the repository that argues nobody should accept an
  unexplained change. Output now defaults to a fresh temporary directory whose path is
  printed; `--output examples/lookahead-demo/results` is the regeneration path and the
  only way the retained evidence is rewritten. The timestamps are untouched: rewriting
  process output to make a diff go away is the failure this product exists to refuse.

- **The README's first fold answers who it is for, and what it cannot prove.** The ICP —
  quant developers and research engineers running Claude Code, Codex or a similar agent
  against real strategy, backtest and research repositories — is now named rather than
  implied, alongside what a passing suite does not tell you, the boundary that `PASS`
  means only that a declared validator exited zero, and a one-command way to see the
  argument without installing anything. The platform line carries its provenance into
  the fold: proven on macOS and Linux by a retained full-lane release proof at the commit
  that manifest names, not this one, which has had a Linux-only fast lane. A reader who
  stops at the fold is no longer left holding a claim about the current `HEAD`.

- **The README is about a third shorter**, 5,326 words to 3,688, with no generated
  evidence block, retained terminal output or gated claim removed. Reasoning that a
  reference document already owns is now a pointer rather than a second copy, and two
  sections were merged into the ones that carried them: `how it works` restated the
  workflow chain directly above it, and `evidence integrity` is the same boundary as
  `change integrity`. [`docs/product-spec.md`](docs/product-spec.md) freezes the
  resulting information architecture and the new above-the-fold order.

- **Evidence vocabulary is fixed on every public surface.** `CONFORMANCE EVIDENCE`
  (deterministic fixtures, regressions and adversarial negative controls),
  `PLATFORM ATTESTATION` (executed OS, Python, install-path and CI evidence) and
  `USER-EFFECT BENCHMARK` (a controlled comparison of what changes for the people using
  it) are three categories, and "benchmark" is no longer the generic word for the first.
  `USER-EFFECT BENCHMARK = NOT PUBLISHED`, stated compactly in the README so that no
  reader infers a productivity, development-time, token, context, model-performance or
  defect-prevention claim from conformance evidence. The `bench/` filesystem namespace
  and the CI job identifiers are unchanged, and historical entries in this file were not
  rewritten: a record of what was said at the time is worth more than a consistent one.

### Fixed

- **A staged file escaped the glob-ambiguity refusal entirely.** The candidate pathset
  was the baseline commit's paths union the untracked ones, and a file that has been
  created and `git add`-ed is in neither: it is absent from the baseline tree, and
  staging stops it being untracked. So the whole refusal was bypassed by the most
  ordinary next action after creating a file — `aiqe check` returned `1 declared /
  0 changed`, `REVIEWABLE_CANDIDATE` and exit `0` with the staged file sitting unowned.
  The index is now a third candidate source, read by name only in the same `ls-files`
  invocation, and the union is taken by raw bytes so no path's identity changes.
- **`aiqe receipt` reported stale evidence as `CURRENT` after a matching path
  appeared.** With a glob-shaped declaration, a green check recorded while the
  declaration named nothing stayed authoritative: the owned binding is a digest over
  the *declared* paths, the declared path is still absent, so none of the four
  freshness comparisons moved while the file that should have been in scope appeared
  beside it. A receipt asked without an intervening `aiqe check` answered `Owned scope
  CHECKED / Checked content CHECKED / Evidence CURRENT`.

  Receipt now runs the same detector `aiqe check` runs, on the same inputs, and reports
  `OWNED_PATH_GLOB_AMBIGUITY` with evidence that is not `CURRENT`. It remains read-only:
  no validator runs, no stored evidence is rewritten or removed, and no path becomes
  owned. Unrelated foreign staged or untracked changes still leave a receipt `CURRENT`,
  and `STALE_OWNED_CONTENT` and `STALE_HEAD` behave exactly as before.
- **The action-pin checks tested shape, not identity.** A 40-character object id was
  accepted from any first-party action, so `actions/checkout@<any 40 hex>` passed — a
  typo, a commit from a fork, or an id an attacker chose — which is most of what
  pinning exists to prevent. `tests/test_workflow_pinning.py` now holds the four
  reviewed owner/action/object-id/version tuples and requires every `uses:` to match one
  exactly, with negative controls for a random id, a real id belonging to a different
  approved action, a wrong or missing version comment, an unreviewed first-party action,
  a third-party action and a mutable major tag. The check is offline; the identities
  were established by review, not by a lookup at validation time.
- **The scanner's action-pin exception applied in any file.** It was scoped to a line
  shape alone, so a foreign object id could reach public content from a document, a
  source file or a test by being written as an action reference. It now requires a
  workflow path *and* the pin line shape, and `self-test.sh` builds an action-shaped
  line in `docs/`, one in a source file, and a bare object id inside a workflow, and
  requires the scanner to report all three.
- **A glob-shaped `--own` value could buy a green check.** `aiqe task start --own
  'src/strategy/**'` records one literal path with that name — which is the documented
  behaviour and is not changing — but that path does not exist, so every file the
  caller meant was unowned. Modifying `src/strategy/model.py` then produced `1 declared
  / 0 changed`, `REVIEWABLE_CANDIDATE` and exit `0`, while declaring the same file
  literally correctly produced a quant `COVERAGE_GAP` and exit `2`. A result that
  reports no obligations because it was asked about nothing is indistinguishable from
  one that had nothing to report, which makes it worse than a failure.

  `aiqe check` now refuses when a declared value contains `*`, `?` or `[`, names no
  file in the baseline commit or the worktree, and — read as a surface pattern —
  selects a changed repository path the task does not own: reason
  `OWNED_PATH_GLOB_AMBIGUITY`, completion `INCOMPLETE`, exit `2`. Any previous evidence
  record is removed, because the owned binding does not move when an unowned file
  changes and a stale green would otherwise still answer `aiqe receipt`. `aiqe task
  start` also notes a glob-shaped absent declaration, but the note is a courtesy: a
  green result must not depend on somebody having read a warning.

  Ownership stays exactly literal. Nothing is expanded, no matched path becomes owned,
  and a real file named `notes[1].md` is still a filename. Declaring a
  metacharacter-bearing path before creating it also still works, until something it
  would have matched actually changes.
- **Every action in the release workflow was pinned to a mutable major tag.**
  `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4` and
  `actions/download-artifact@v4` all resolve to whatever their major tag points at
  today, so the code running in the workflow that produces release evidence could
  change without any change to this repository. Each is now pinned to a full-length
  commit SHA resolved from its canonical upstream repository, with the released version
  retained as a comment. No workflow semantics, permissions or actions changed.

  A pin is a bare 40-character object id, so `tools/public-scan/public-scan.sh` would
  have reported the control as a leak. Its `GIT_SHA_40` class now has a second recorded
  exception, scoped to a line that is nothing but a `uses:` pin and anchored at both
  ends — a bare id anywhere else in the same workflow is still a finding. The stronger
  check that replaces it is the new `tests/test_workflow_pinning.py`: every `uses:` in
  every workflow must be pinned to a full object id, carry a version comment, and name
  a first-party owner from a short reviewed list. The scanner self-test carries a
  pinned reference among its benign strings, so dropping the exception fails the
  self-test rather than passing quietly.
- **`SECURITY.md` said private vulnerability reporting would be enabled before the
  repository became public.** It cannot be: private vulnerability reporting is a
  public-repository feature, so it is not available while this repository is private.
  The policy now states that it is enabled and verified as part of making the
  repository public — not beforehand — and that there is no private reporting channel
  until then.
- **The support gate reported no unexercised Git range when there was one.** It took the
  lowest exercised version overall, which is Git 2.30.2 — a surface exercised only to
  prove AIQE *refuses* on it. A refusal cannot close a support gap, so the gate now
  ignores below-floor surfaces, and `enforced_but_unexercised_range` in the retained
  manifest is corrected to what the gate computes from that manifest's own `exercised`
  list. Every other field of `git_compatibility` reproduces unchanged from the same
  inputs. The README already stated the 2.32-to-2.54 gap correctly; the manifest was the
  surface that did not.
- **The README claimed Git 2.55.0 on "every hosted runner in the matrix".** The
  Debian 11 job is a hosted runner in the matrix and runs Git 2.30.2. The line now names
  the surfaces the manifest records.
- **Two published durations rested on nothing.** The demo was described as taking about
  ten seconds, on no retained measurement, against this project's own rule that a prose
  observation never becomes a published number. Both are removed. Benchmark family E,
  which would measure time to value, is now marked deferred rather than described in the
  present tense, and the five-minute quickstart target is recorded as a product target
  in the claims inventory.
- **`render-assets.py` reported one more capture than it checked**, counting the index
  alongside the seven captures.

### Changed

- **The retained release-proof manifest no longer records a repository namespace.**
  `ci_runs[].repository` was read by no gate, no comparator and no published surface.
  What binds the manifest to this project is `source_commit` — proven by test to name an
  object in this repository — together with run identifiers that survive a rename or a
  transfer, so the namespace added no authority and would become a stale project name
  after any such move. It is removed from the retained record and no longer collected.
  A test keeps it out.

- **The failure-first demonstration, materialised.**
  [`examples/lookahead-demo/`](examples/lookahead-demo/) is now runnable rather than
  specified: `run.py` builds four synthetic repositories from nothing, drives the real
  entry point against them, and runs the reference workflow against copies of the same
  repositories so the contrast is measured. A one-character causality defect passes the
  project's own generic suite and fails a native causality validator; removing that
  validator leaves everything green and produces `COVERAGE_GAP`; an ordinary commit
  absorbs unrelated staged work that the bounded commit excludes; and a check-then-edit
  sequence commits unchecked content that AIQE refuses with `STALE_OWNED_CONTENT`.
  Outcomes are declared in `expected.json` before the run, and everything the run
  produced is retained under `examples/lookahead-demo/results/`, failures included.
- **`bench/render-assets.py`.** Renders the screenshotable terminal surfaces into
  [`docs/assets/captures/`](docs/assets/captures/) and the README's benchmark totals
  between markers, both from the retained result artifacts. Without `--write` it
  reports drift and exits non-zero, so a published number cannot part company with the
  artifact it came from and a capture cannot stop being the output it names. Each
  capture carries its provenance — family, result artifact, case and field — in
  `captures/index.json`.
- **[`docs/agents.md`](docs/agents.md).** How to use AIQE with Claude Code and Codex
  through ordinary shell invocation, what belongs in `CLAUDE.md` or `AGENTS.md`, and
  which two decisions — the owned scope and validator consent — must not be delegated
  to the agent. There is no plugin, adapter or MCP server, and the page says so.
- **[`docs/assets/README.md`](docs/assets/README.md).** What the captures are, how they
  are regenerated, and the rules any later rendered asset has to follow.
- **`tests/test_demo.py`.** Runs the demo, compares what it produced against what is
  retained, and asserts that the retained transcript differs from a fresh one in
  exactly the task start timestamps and nowhere else.
- **Documentation gates for the claims the new pages make**, in
  `tests/test_documentation.py`: every `aiqe` flag shown in the README exists in the
  command surface, every documented `aiqe.toml` is one the fail-closed parser accepts,
  every launch contract is explained rather than only listed, the trust boundaries and
  the bounded contract claim are present, no badge appears, and the rendered assets
  still match the retained artifacts.
- **A release proof, and a support gate that can refuse.** Every CI job that is
  support evidence now writes a *surface record* naming the machine, the interpreter,
  the Git version, the runner provenance, the evidence level and every test it
  skipped. [`bench/aggregate-release-proof.py`](bench/aggregate-release-proof.py)
  collects them and applies the gate in
  [`bench/release/support.py`](bench/release/support.py): a Python minor is `PROVEN`
  only with both a full-suite run and an installed-artifact end-to-end run, on every
  claimed OS family. Nothing is inferred from the endpoints of a range, nothing is
  inferred about an architecture from a pure-Python wheel, and a skipped case is not
  a pass. Reference: [`docs/support.md`](docs/support.md).
- **`bench/run-release-proof.py`.** Builds an sdist and a wheel from an exported
  tracked-content-only source tree, installs each into a fresh environment, and runs
  the complete workflow — `doctor`, `init`, `task start`, `check`, `commit`,
  `receipt` — from the installed console script in a directory that is not the source
  tree, ending in `REVIEWABLE`. Also measures the uv and uvx paths, the offline
  runtime, build reproducibility, the artifact allowlist and the extracted-artifact
  scans. `--parts` selects a subset, and the record states which parts did *not* run,
  so a reduced job can never be read as a full one.
- **`bench/run-suite.py`.** The unit suite with its counts, its environment identity
  and every skip recorded by name, because a support claim cannot be made from a
  green checkmark.
- **Three release-proof negative controls**, each with an unsafe reference that
  genuinely fails. `NC-PACKAGE-SOURCE-IMPORT` builds a wheel with a module missing:
  the naive check imports it from `./src` and passes, the installed-artifact check
  fails. `NC-PACKAGE-PRIVATE-FILE` plants a synthetic private file collected by a wide
  `package-data` glob: the pattern scan passes it and the artifact allowlist rejects
  it. `NC-SUPPORT-CLAIM` extrapolates a contiguous Python range from its endpoints and
  requires the gate to refuse it.
- **An offline runtime proof for the installed artifact.** The whole core command set
  runs with every standard-library socket entry point replaced by a recorder that
  raises — and the canary is proved to fire on a deliberate connection attempt before
  its silence is accepted as evidence. The claim is stated narrowly: AIQE's runtime
  needs no network; obtaining AIQE or uv from an index does.
- **`docs/support.md`.** How a support claim is decided, the Git behaviours the frozen
  core relies on, the distribution decision, what may appear inside an artifact, and
  the reproducibility procedure.

### Changed

- **The README is reorganised around the product rather than the build order.** The
  hero is the post-commit Task Receipt; a 30-second explanation and a before/after
  table come next, then the demo, then a five-minute quickstart following the real
  command sequence. New sections explain what each of the six launch contracts is
  about, state exactly what a contract result does and does not prove, summarise the
  trust boundaries on the front page, record the packaging facts, and publish the
  benchmark totals from the retained artifacts. Every terminal block on the page is
  still copied from a retained result, and tests still check that it is.
- **The external CI attestation is recorded rather than implied.** The README states
  that the release-proof manifest was aggregated at a source commit which is not the
  current HEAD, and that no complete CI run has attested the current HEAD. No badge
  appears on the page, and a test fails if one does.
- **`docs/architecture.md` no longer describes agent adapters as though they exist.**
  It states the actual integration — an ordinary command with a uniform exit status —
  and points at [`docs/agents.md`](docs/agents.md).
- **A race-dependent count no longer sits in the retained bounded-commit result as
  though it were a result.** Several cases in that family race a concurrent process
  against AIQE's own window on purpose, and Git legitimately writes a different number
  of objects, lock files and reflog entries depending on how the race lands: two correct
  runs on one machine, minutes apart, reported 292 and 295 across four cases, with every
  zero-tolerance total and every case outcome identical.

  `aiqe_commit_git_writes` moves into a `diagnostics` section — document level and per
  case — which `compare-results.py` now strips explicitly before comparing anything. The
  stable fact underneath it stays where it belongs: `aiqe_commit_git_writes_observed`
  records whether a case's completion commit wrote through Git at all, which is what
  distinguishes a case that committed from one that refused, and `counts` carries
  `cases_with_commit_git_writes` in place of the raw sum. No zero-tolerance quantity
  changed, no case outcome changed, and no headline number changed.

  A regression holds the exclusion from both directions: two documents differing only in
  that count must agree, and a change to a quantity that does carry authority must still
  be caught. Without the second half the first would pass for the wrong reason.

- **AIQE now refuses to run on Git older than 2.32, rather than running under-isolated.**
  Every command rests on the invariant that nothing the repository defines is executed,
  and that invariant is delivered by pointing `GIT_CONFIG_SYSTEM` and `GIT_CONFIG_GLOBAL`
  at the null device. Both variables arrived in Git 2.32. An older Git does not know the
  names, so it does not read them *and does not complain*: the isolation is applied, the
  command succeeds, and `$HOME/.gitconfig` is in scope the whole time.
  `GIT_CONFIG_NOSYSTEM` is not a fallback — it declines the system file and has no
  opinion about the per-user one.

  This was found, not reasoned about. On Debian 11 (Git 2.30.2) the Doctor negative
  control `NC_DOCTOR_GLOBAL_FILTER_EXECUTION` stopped reproducing, because the fixture's
  globally defined filter driver was never in scope at all; in the same run the
  bounded-commit policy preflight returned `0` and created a commit where it must return
  `3` and refuse. Fourteen cases failed from that one cause.

  Before any command that reaches Git, AIQE now reads `git --version` and refuses with
  exit `3` and reason `GIT_TOO_OLD_FOR_CONFIG_ISOLATION` below the floor, or
  `GIT_VERSION_UNKNOWN` when the version cannot be read — failing closed on an unknown
  toolchain rather than assuming the best about it. `aiqe --version` still answers,
  because it reaches no repository. This is the one frozen surface this work
  changed, and it is a refusal added at the entry point rather than a change to any
  command's semantics.

- **The package version is now `0.1.0a0`** — PEP 440's spelling of the frozen
  milestone `v0.1.0-alpha`, the first installable real product. It is a package
  version and nothing else: no Git tag exists, no release exists, and nothing is
  published to any index. The retained benchmark artifacts were regenerated at the new
  version; every case outcome, every family count and every zero-tolerance total is
  unchanged.
- **`tools/public-scan/public-scan.sh` takes an optional root**, so the extracted
  sdist, the extracted wheel and the release-proof manifest are scanned as trees in
  their own right. A source tree that scans clean says nothing about what a build
  backend put inside an artifact.
- **The CI matrix proves what is claimed.** All four Python minors are exercised rather
  than inferred from the endpoints, under a documented tiering: the installed-artifact
  end-to-end runs on every claimed OS family and every minor, and the full behavioural
  suite runs on Linux for every minor and on macOS at the ends of the range. The support
  gate encodes exactly that split, and the manifest records per minor which families ran
  the suite, so the basis of a `PROVEN` verdict is readable rather than implied. Plus
  five deliberately chosen surfaces — Ubuntu 22.04, Linux on arm64, a Debian 11
  container for the Git floor, macOS one release back, and x86_64 macOS — each
  answering a distinct compatibility risk rather than inflating the matrix.

### Fixed

- **The sdist no longer contains a broken partial copy of the test suite.**
  setuptools' default manifest collected `tests/test*.py` and neither
  `tests/__init__.py` nor `tests/support.py`, producing a test package that could not
  be imported: a tree that looks like evidence and is not. `MANIFEST.in` prunes the
  directory, and the artifact allowlist is what notices if that ever stops working.

- **`aiqe commit -m <message>`.** The bounded completion commit, and the last command
  of the frozen v1 surface. It consumes existing green check evidence, never reruns a
  validator, and never pushes. One flag: there is no `--amend`, no `--no-verify`, no
  `--allow-empty` and no `--push`, because each of them is a way to make the command
  succeed by weakening the claim it makes. Reference:
  [`docs/commit.md`](docs/commit.md).
- **`REVIEWABLE` is now reachable — and only from a verified commit.** A completely
  green check still yields `INCOMPLETE` with `BOUNDED_COMMIT_NOT_CREATED`. The receipt
  says `Owned scope VERIFIED · Foreign staged EXCLUDED · Checked content BOUND ·
  Commit CREATED · Push NOT_PERFORMED_BY_AIQE · Verdict REVIEWABLE` only when the
  commit's parent, changed pathset, committed content and foreign staged preservation
  have each been proved against the object database.
- **Effective Git commit-policy preflight.** Unlike Doctor's bounded static inspection,
  commit resolves the configuration the real commit would use — system, global, local,
  worktree and command scope, with `include` and `includeIf` — by asking Git rather
  than reimplementing it. Five refusals, all exit 3 and all fail-closed: an active
  `pre-commit`, `prepare-commit-msg`, `commit-msg` or `post-commit` hook under the
  effective `core.hooksPath`; automatic commit signing; an external `clean` or
  `process` filter bound to an owned path; an unresolvable effective configuration; and
  an unsupported topology or operation state. No `--no-verify` and no `--no-gpg-sign`:
  AIQE refuses rather than disabling a policy its user set. A driver that is configured
  but bound to no owned path is deliberately **not** a blocker.
- **Expected check-in state, derived before any mutation.** Each owned path is bound to
  a blob OID and Git mode, or to an absence, using `git hash-object --path`, which
  applies exactly the transformations Git would apply and writes nothing. This closes
  the documented raw-bytes conservatism for the commit proof: under `core.autocrlf` or
  a `* text` attribute the committed blob is deliberately not the worktree bytes, and
  `CHECKED_CONTENT_BOUND` still holds. `core.fileMode` semantics are honoured in both
  directions, measured rather than assumed.
- **Transactional intent-to-add.** A new owned file is marked with `git add -N` over
  exact literal paths only. A failure before a commit exists scope-rolls back exactly
  the entries AIQE created and verifies the rollback; a whole saved index is
  deliberately never restored, because that would discard concurrent foreign staged
  work. An unprovable rollback is `ITA_ROLLBACK_INCOMPLETE`, exit 2, and no completion
  claim.
- **The pre-mutation staleness recheck.** HEAD, the owned-content binding, the
  `aiqe.toml` digest and the validator definition digests are recomputed immediately
  before the first index mutation, after every expensive preflight step. Drift stops
  the operation with `commit = NONE` and `index mutation = NONE`.
- **Structured foreign staged preservation.** The staged delta over every non-owned
  path is captured against the pre-commit HEAD immediately before the first index
  mutation and again immediately after the commit — as addition, modification,
  deletion and mode or type change, NUL-safe with rename detection disabled, hashing
  no foreign content. `PRE == POST` is what `EXCLUDED` means; any difference, including
  a newly appearing entry, is `UNKNOWN` and at best `INCOMPLETE`.
- **`COMMIT_EVIDENCE_SCHEMA_VERSION = 1`**, one local record per task, holding the
  proof and not the commit message. `aiqe task end` removes it alongside the check
  evidence, so a new task can never inherit a previous task's completion commit. A
  second `aiqe commit` for the same task refuses.
- **The `BOUNDED_COMMIT` benchmark family** — 37 cases and 8 negative controls under
  `bench/fixtures/commit/`, with retained results. Every control reproduces its
  failure, including a concurrent process that stages a foreign path inside AIQE's own
  mutation window.
- **`aiqe init`, `aiqe check` and `aiqe receipt`.** The complete assurance workflow:
  `init` → `task start --own` → change the owned files → `check` → `commit` →
  `receipt`.
- **Configuration schema v1** in `./aiqe.toml`, with exactly two declaration types,
  `[[surface]]` and `[[validator]]`. Parsing is fail-closed: an unknown field, a
  missing `quant`, a missing `required`, a missing or out-of-range `timeout`, an empty
  argument vector, a duplicate validator id or an invalid pattern is a refusal (exit 3)
  rather than a default. `quant = false` is never inferred from an absence of evidence.
- **An AIQE surface pattern grammar** — `*`, `?`, `**`, `[abc]` — matched on raw path
  bytes, with no case folding and no Unicode normalisation. It is AIQE's own and is
  never handed to Git as a pathspec. `**` must be a whole component; `a**b` is refused
  rather than quietly demoted to `a*b`.
- **All-matching surface classification.** Every matching declaration is evaluated, not
  the first, and quant contract obligations union across them, so adding a surface can
  never reduce an obligation. A path matched by both a quant and a non-quant surface is
  `CONFIG_CONFLICT`: exit 3, no evidence, no receipt.
- **The six launch contract families** — `CAUSALITY`, `DATA_ALIGNMENT`,
  `EXECUTION_REALISM`, `ACCOUNTING`, `TRAIN_TEST_SEPARATION`, `DETERMINISM` — each with
  its own deterministic fixtures proving covered, failed, and coverage gap. Custom
  contract identifiers remain legal.
- **`COVERAGE_GAP`.** An applicable contract with zero *required* validators bound to it
  is a gap, not a pass. An optional validator never satisfies coverage, and a generic
  suite never covers a quant contract.
- **Validator consent, per definition digest, machine-local.** Tracked configuration is
  executable trust material, not authorization. A validator's identity is its id,
  argument vector, timeout, required flag and contracts, bound by a digest over a
  length-delimited binary serialisation; changing any of them revokes consent by
  identity mismatch, with no migration. `--allow <id>` authorises one run and persists
  nothing. A non-interactive or `--format json` check never prompts and reports
  `UNKNOWN` / `CONSENT_REQUIRED`.
- **Mandatory validator timeouts**, and a timeout is a `FAIL`. On timeout AIQE
  terminates the process group it created for that validator: a script's children
  inherit its pipes, and killing only the process AIQE started let a one-second timeout
  run for thirty seconds. It does not bound a descendant that leaves that group, and
  does not claim to.
- **Checked-content binding**, bounded to the owned pathset — content digests, modes,
  deletion and pending markers, the baseline and current HEAD, the raw `aiqe.toml`
  digest and every validator definition digest. No whole-tree fingerprint.
- **Validator-induced change detection.** The bounded authority is measured immediately
  before and after validator execution. A validator that edits the file it is checking
  and exits 0 does not produce current evidence; the previous record is removed rather
  than left looking current.
- **Staleness without re-running anything.** `aiqe receipt` recomputes the owned
  binding, HEAD, the configuration digest and the validator definition digests, and
  reports `STALE_OWNED_CONTENT`, `STALE_HEAD`, `STALE_CONFIG` or
  `STALE_VALIDATOR_DEFINITION`.
- **A correlation-minimised default receipt**, carrying counts, states, reason ids and a
  verdict — and no path, filename, repository name, remote, branch, commit id,
  validator command line, output, username, hostname or task label. The exclusion list
  is property-tested against the fixture's real values, and the serialiser is bound to
  a redaction policy id. `aiqe receipt --local` is the richer local surface.
- **`REVIEWABLE` is unreachable before a bounded commit.** A completely green check
  produces the internal state `REVIEWABLE_CANDIDATE`; the receipt still reports
  `INCOMPLETE` with reason `BOUNDED_COMMIT_NOT_CREATED`. Asserted as a property over
  every valid pre-commit state combination, not as examples.
- **Evidence schema version 1**, one active record per task, replaced whole by each
  check and removed by `task end`. No history. Recorded consent survives task end.
- A new benchmark family, `CHECK_RECEIPT_EVIDENCE`: 33 cases and four negative
  controls — `NC_CHECK_STALENESS`, `NC_MISSING_QUANT_VALIDATOR`, `NC_CONSENT`,
  `NC_VALIDATOR_MUTATES_OWNED` — all reproducing their failures.
- References: [`docs/config.md`](docs/config.md), [`docs/check.md`](docs/check.md),
  [`docs/receipt.md`](docs/receipt.md).

### Changed

- **`RECEIPT_SCHEMA_VERSION` is now 2.** Version 1 promised that `commit` was always
  `NONE` and had no `checked_content` or `push` field, so a version 1 reader would
  misread a post-commit receipt as a pre-commit one. The default receipt gains two
  states and one count and still carries no identifier: no commit SHA, no filename, no
  branch, no repository identity. `aiqe receipt --local` gains the allowlisted commit
  identifiers, because you are standing in the repository they name.
- **A post-commit receipt stops claiming a current state once HEAD moves off the
  completion commit**, reporting `COMPLETION_COMMIT_SUPERSEDED`. This is not a verifier
  for arbitrary historical commits and does not become one.
- **A second Git layer, for the one operation that writes.** `gitq` stays read-only and
  configuration-isolated. `gitwrite` runs the commit under effective Git semantics,
  because the commit AIQE creates must be the commit your Git would create. It carries
  its own allowlist, which contains no network subcommand, and suppresses only
  non-semantic execution behaviour — `core.fsmonitor`, `gc.auto`, `maintenance.auto`.
  Process creation in AIQE core now has three doors, and the test suite names them.
- **A broken global Git configuration is diagnosed, not mistaken for an absent
  repository.** Discovery reads the user's real configuration, so a `~/.gitconfig` Git
  cannot parse makes every invocation fail. `aiqe commit` establishes that cause before
  reporting the symptom and returns `EFFECTIVE_CONFIG_UNRESOLVED`.
- **Pre-existing AIQE local state is validated before it is used.** Creating state
  privately is half the job; state that is already there may have been placed. Every
  AIQE-managed component — the state root, the per-worktree directory, the salt, the
  task record, the check evidence, the consent record, the lock — must be a real
  directory or regular file, not a symlink, owned by this user, and 0700 or 0600.
  Anything else is `LOCAL_STATE_UNSAFE`: exit 3, no validator executed, recorded consent
  not trusted, and the refusal stands even with `--allow`. AIQE does not `chmod`,
  `chown`, replace or follow what it finds. Adversarial fixtures cover a world-writable
  root, a group-readable worktree directory, a 0644 consent store, a symlinked consent
  store, a foreign owner, and ordinary state continuing to work under `umask(0)`.
- **Repository-controlled text is escaped on every human surface.** A validator's
  identifier, argument vector and output are written by anyone who can land a commit,
  and all three are printed back to a person. The configuration grammar refuses what it
  can — an identifier containing a newline or an escape never reaches a renderer — and
  the rest goes through the escaping AIQE already used for repository paths, now applied
  to the consent prompt, `aiqe check`, `aiqe receipt --local` and every configuration
  refusal message including rejected TOML key names. Escaped, never stripped: a prompt
  that removed part of the command it is asking about would stop describing what is
  being consented to. The definition digest is still taken over the real argument
  vector, never over the displayed text. Fixtures drive a real pseudo-terminal with an
  argv carrying `ESC[2J` and a second prompt of its own, and a validator that fails
  while printing a screen clear and the word `PASS`; raw terminal control bytes reaching
  a human surface is a new zero-tolerance benchmark quantity.
- **Validator output is bounded while it is read**, not buffered whole and truncated
  afterwards. Both pipes are drained incrementally into a fixed-size tail through one
  deadline-bounded loop, so peak memory is the retention budget plus one read buffer per
  stream whatever the validator emits — measured across a thirty-two-fold change in
  output volume — and a validator that fills the pipe cannot deadlock. The retention
  policy is documented as `tail`, and output is still discarded for `PASS`.
- **The termination claim is stated exactly.** On timeout AIQE terminates the process
  group it created for that validator, and nothing more. Wording that implied it bounds
  every descendant, contains a process tree, or that a validator spawning children
  cannot outlive its deadline has been corrected across the product, the security
  policy and the references. A benchmark fixture spawns a child that calls `setsid` and
  observes it surviving the group kill, so the stronger and false claim cannot return
  unnoticed.
- **Consent is proved through a real pseudo-terminal**, driving the real CLI, in both
  directions: denied (nothing executes, nothing is recorded) and accepted (the validator
  runs once, consent is recorded against the exact definition digest, a later
  non-interactive run acts on it, and changing one semantic field ends it). An injected
  prompt callable cannot prove this, because the decision under test is whether AIQE
  asks at all.
- **Machine-local state is owner-only regardless of umask.** Directories are 0700 and
  every record is 0600 — the salt, the task record, the check evidence, the consent
  record — including the temporary file each is written through. Asserted under
  `umask(0)`, so the modes are AIQE's doing rather than the environment's.
- `git ls-tree` and `git cat-file` joined the Git subcommand allowlist. `check` needs an
  owned path's baseline content, and asking Git whether a file changed would make it
  read worktree content through any configured check-in filter. Both new subcommands
  read the object database only.
- The measured invariant for `check` is `UNCONSENTED_VALIDATOR_EXECUTIONS = 0`, not the
  absence of repository-defined execution: here that execution is expected, after
  consent. AIQE core's own repository writes remain zero-tolerance, and the benchmark
  attributes every observed repository change to an authorised `init` write, a
  validator, the fixture, or AIQE core.

- **Task state moved out of Git metadata** to `$XDG_STATE_HOME/aiqe/` (falling back to
  `~/.local/state`), in a directory named by
  `HMAC-SHA256(salt, canonical common-dir || 0x00 || canonical git-dir)` under a
  machine-local 32-byte salt at mode 0600. The key names no repository, and the
  canonical paths are inputs only — nothing identifying is stored. A task operation now
  changes nothing inside the repository at all, `.git` included.
- The salt is created on the **first write only**: `doctor`, `task` and a refused
  `task start` leave the filesystem exactly as they found it. Creation links into place,
  so concurrent first-ever writers converge on one salt rather than two.
- **Symlinks and special files are refused** as owned paths (`OWNED_PATH_IS_SYMLINK`,
  `OWNED_PATH_NOT_REGULAR`), matching the frozen rule that v1 owns regular files, their
  creation and their deletion. A symlink is refused as a link, not judged by its target.
- **Duplicate declarations are refused** (`DUPLICATE_OWNED_PATH`) rather than merged.
- **`task start` in a repository with no commits is refused.** A task records the commit
  it started from. `doctor` and `task` still work there.
- The record carries `foreign_staged_count_at_start`, informational and local. It is not
  the foreign-staged guarantee, which belongs to `aiqe commit`.
- **Task state schema version 3.** A record from a superseded schema is refused and left
  untouched rather than reinterpreted; `task end` discards it. No migrations.
- Added `NC_TASK_STATE_IN_GITDIR`: task state written inside the Git directory. The
  naive implementation writes into `.git`; AIQE writes nothing there.
- The benchmark snapshot describes special files instead of opening them — hashing a
  FIFO blocks forever, and a fixture containing one is a real case the harness has to
  survive measuring.
- **Ownership is an exact literal pathset**, correcting the component-prefix semantics
  that landed in the previous entry. Owning `foo` owns `foo`, and not `foo/bar` or
  `foobar`. A prefix rule would let a task authorise files that did not exist when the
  scope was declared, which is the widening an owned scope exists to prevent, and it
  cannot support the claim the product makes: AIQE knows the exact declared owned
  pathset.
- **A declared path that exists today as a directory is refused**
  (`OWNED_PATH_IS_DIRECTORY`, exit 3). It is not expanded and not owned as a single
  path. A path that does not exist is still accepted, and a symlink is owned as the
  link rather than as its target.
- **Task state schema version 2**, with `ownership_semantics`, `owned_paths` and
  `owned_pathset_digest` replacing the ambiguous version-1 names. A version-1 record is
  refused and left untouched rather than reinterpreted — reading it under exact
  semantics would quietly narrow a live task's authority. `aiqe task end` discards it;
  there is no migration.
- The owned-pathset digest is domain-separated as `aiqe.owned-pathset.v1`.
- Added `NC_TASK_PREFIX_OWNERSHIP_BROADENING`: a task declares a path that does not
  exist, the path later materialises as a directory, and the prefix rule silently
  authorises files inside it. It reproduces; exact ownership does not.

### Added

- **`aiqe task` is implemented**: `task start --own <path>... [--label <text>]`,
  `task`, and `task end`. One active task per worktree, working before `aiqe init`,
  which still does not exist.
- Owned scope as an exact literal pathset. Declared paths are literal data — glob
  characters, pathspec magic and arguments that look like flags are all just filenames —
  and never reach Git as a pathspec.
- Scope is a declaration, not an observation: an owned path need not exist yet.
- Owned paths round-trip as raw bytes, stored base64-encoded in the record and proven
  end to end on Linux with a path that is not valid UTF-8.
- A documented deterministic owned-pathset digest binding the exact path bytes,
  component boundaries and canonical ordering.
- Machine-local task state, so two linked worktrees hold two independent tasks. Atomic
  writes with fsync and rename; an exclusive `flock` over start and end, so two
  concurrent starts produce one winner and one refusal.
- Terminal-safe rendering of owned paths and labels: a filename containing a newline or
  an escape sequence cannot forge an output row or repaint the terminal, and the stored
  value is untouched.
- Task benchmark family under `bench/fixtures/task/`, with 25 cases and five negative
  controls — state inside the Git directory, prefix-ownership broadening, pathspec
  expansion, shared worktree state, and a lost start race — all reproducing.
- Reference documentation for the task surface and its local state schema:
  [`docs/task.md`](docs/task.md).

### Changed

- Benchmark fixtures are now a package tree, with the measurement primitives and the
  fixture-construction helpers shared between families rather than duplicated. Doctor
  results are unchanged.
- `bench/compare-results.py` selects the retained artifact from the family the fresh run
  names.

### Security

- **Doctor no longer inherits command-scope Git configuration.** Git reads
  configuration from the process environment — `GIT_CONFIG_COUNT` with
  `GIT_CONFIG_KEY_<n>`/`GIT_CONFIG_VALUE_<n>`, and `GIT_CONFIG_PARAMETERS` — and it
  outranks every configuration file, so silencing `GIT_CONFIG_SYSTEM` and
  `GIT_CONFIG_GLOBAL` said nothing about it. An injected `filter.<name>.clean` was
  executed straight through file-level isolation. The invocations that read the index
  or the worktree now start from an environment with those variables removed, bounded
  to the documented command-scope mechanism. Negative control added; it reproduces.
- **Doctor no longer executes a filter driver defined outside the repository.**
  A tracked `.gitattributes` can bind a path to a driver whose command lives in the
  user's global configuration or behind a local `include`; reading only the
  repository's own configuration and concluding no filter was present was wrong, and
  measured canaries fired. Every invocation that reads the index or the worktree now
  runs with system and global configuration switched off, and the comparison is refused
  outright when repository configuration, an unfollowed include, or a repository
  attributes binding makes execution safety unresolved.
- **Doctor no longer descends into submodules.** A submodule's own configuration is
  repository scope for that submodule, so isolating the superproject's does not reach
  it, and `git status` ran the submodule's filter. `status` is now invoked with
  `--ignore-submodules=dirty`, which prevents the descent while still reporting a
  changed submodule pointer.
- Two negative controls added for the above, both reproducing.
- **Doctor disables Git background maintenance per invocation** (`gc.auto=0`,
  `maintenance.auto=false`). Maintenance outlives the command that starts it and
  writes into the repository afterwards; "nothing changed, except by a process we
  started" is not the zero-write contract. Fixture construction disables it too, and
  the harness now refuses to measure a repository that is not quiescent - a lingering
  lock file fails loudly instead of reading as a Doctor mutation.

### Changed

- **Python 3.11 is the support floor** (`requires-python >=3.11`), with 3.11 and 3.14
  as the tested endpoints. 3.9 is end of life and is no longer tested or advertised.
- The unstaged count is now reported as `UNKNOWN` in more situations: an unfollowed
  config include, or repository attributes binding any path to a filter driver. A
  repository using Git LFS is now in that category. False unknown is preferred to
  executing a repository-selected command.
- Working-state counts exclude submodule worktree changes and disclose that they do.
  They are computed under repository-scope configuration, so a custom global
  `core.excludesFile` no longer applies to the untracked count.
- **Working-state counts are labelled with their scope.** JSON carries
  `working_state_scope`, which is `"repository_safe_view"` whenever counts were taken
  under configuration isolation and `"not_applicable"` when there was no worktree to
  inspect; the human output says `repository-safe view` beside the counts. A
  repository-safe view is not what `git status` prints under every user and global Git
  configuration, and a number whose scope is unstated invites being read as the wrong
  one. No finding family was added.
- `working_state.submodule_worktrees_excluded` added to the JSON output, and
  `commit_policy` gained `attributes_bind_filter`, `attributes_readable` and
  `submodules_present`. No finding code was added or removed.

### Added

- **End-to-end arbitrary-byte path proof.** A real repository whose tracked, staged and
  untracked paths are not valid UTF-8, exercised through the whole pipeline rather than
  fed to a parser. Restricted to Linux because APFS refuses such filenames; CI runs it
  with skipping turned into an error, so it cannot quietly stop happening.
- Six adversarial fixtures for the external-configuration boundary, covering a global
  filter driver, a global fsmonitor, a local include resolving to a filter, a fully
  external attributes binding, an external binding with a local driver, and a
  submodule-local driver.
- Benchmark cases may declare a platform restriction; a case that does not apply is
  reported as skipped with its restriction named, never dropped.

### Added (doctor)

- **`aiqe doctor` is implemented**: first-contact repository diagnosis in human and
  deterministic JSON form, working before `init`, on an unconfigured repository, and on
  a directory that is not a repository at all.
- `aiqe --version`. The rest of the frozen command surface remains unregistered rather
  than stubbed.
- Runtime selected: a Python package with no third-party runtime dependencies and no
  third-party test dependencies. See the runtime section of
  [`docs/architecture.md`](docs/architecture.md).
- Doctor reference documentation, including the finding codes, the JSON shape, the exit
  semantics and the known limitations: [`docs/doctor.md`](docs/doctor.md).
- Deterministic test suite on the standard library `unittest` module, covering the
  command surface, repository and working states, operations in progress, topology,
  Git policy signals, agent surface detection, rendering determinism, and the zero-write
  and no-network proofs.
- Doctor benchmark family materialised under `bench/`: deterministic fixture builders,
  expected outcomes declared as data, the external measurement harness, four negative
  controls, and the retained result artifact.
- CI now runs the test suite, the Doctor benchmark family, and a clean-environment
  install of the console script, alongside the existing sanitisation and link checks.

### Changed

- Doctor's Git invocations are hardened against two measured behaviours: `git status`
  rewrites `.git/index` on a stat-dirty worktree, and `git status` executes a configured
  `core.fsmonitor` command as a child process. Both have reproducing negative controls.
- When a check-in filter driver is configured, Doctor does not compare worktree content
  at all and reports the unstaged count as `UNKNOWN`, because answering would require
  Git to execute a command the repository defined.
- Documentation that described the runtime as unselected, or the repository as
  containing no source or tests, has been corrected.

### Added (bootstrap)

- Repository bootstrap: product specification, architecture summary, and clean-room
  provenance manifest.
- Benchmark protocol and the six numerical-integrity contract families, with the
  negative-control taxonomy and the zero-tolerance release gates.
- Specification for the failure-first lookahead demo.
- Public sanitisation tooling (`tools/public-scan/`) and the bootstrap CI workflow.
- Apache-2.0 licence, security policy, and contribution guidelines.

### Notes

- No version has been released and no tag has been created. `doctor` and `task` are
  implemented; `init`, `check`, `commit` and `receipt` remain design targets and are not
  stubbed.
- The Doctor and Task benchmark families have results. `check`, `receipt` and bounded
  commit remain `NOT_RUN`, and no aggregate benchmark completion is claimed.
- macOS is the supported target. The suite is also run on Linux in CI, which is evidence
  but not a release claim.
