# Launch claims

Every externally visible factual claim AIQE makes, what class it is in, and the
retained evidence it rests on. One row per claim, and only launch-relevant
claims: this is a boundary document, not a catalogue.

A claim that is not here may not be made on a public surface.

```
PROVEN        retained machine evidence demonstrates it
OBSERVED      it happened and was recorded, on one environment, once
NOT_PROVEN    stated so that its absence is not read as a yes
DESIGN_INTENT a target or a rule the project holds itself to, not a measurement
OUT_OF_SCOPE  deliberately not attempted in v1
```

`OBSERVED` is the class that decays. A number in it describes the machine that
produced it and no other.

## Evidence sources

```
BENCH      bench/results/{doctor,task,check,commit}/results.json
MANIFEST   bench/results/release/release-proof.json
DEMO       examples/lookahead-demo/results/demo.json
CAPTURES   docs/assets/captures/index.json
SUITE      the local project suite, named test module and assertion
```

`SUITE` is the weakest of the five and is used only where the claim is a
property of the code rather than a measurement over fixtures: a boundary that
is asserted every run, not a number that was observed once. A `SUITE` claim
names the module that would fail if the boundary moved.

`MANIFEST` was aggregated at source commit `5b477a9`, which is **not** the
current `HEAD`. Every claim resting on it inherits that gap; see
[`support.md`](support.md#11-the-attestation-this-manifest-does-not-carry).

## Semantic claims

| id | claim | class | evidence | limitation | surfaces |
|---|---|---|---|---|---|
| `doctor-no-mutation` | Doctor mutates no repository path | PROVEN | BENCH doctor `repository_mutations = 0`, 41 cases | measured over the fixture corpus, not over all repositories | README, `doctor.md`, `architecture.md` |
| `doctor-no-repo-exec` | Doctor executes nothing the repository defines | PROVEN | BENCH doctor `repository_defined_executions = 0`, 7 controls | canaries cover the classes the fixtures install | README, `doctor.md` |
| `task-exact-pathset` | An owned scope is exact literal paths and cannot widen | PROVEN | BENCH task, 25 cases, 5 controls | v1 declares no pattern grammar for ownership | README, `task.md` |
| `task-no-git-mutation` | A task operation mutates nothing in the repository, `.git` included | PROVEN | BENCH task `repository_mutations = 0` | AIQE's own machine-local state is written, and is counted separately as `aiqe_state_changes` | README, `task.md` |
| `check-consent` | No validator runs without explicit local consent bound to its definition digest | PROVEN | BENCH check `unconsented_validator_executions = 0`; consent driven through a real pty | consent is a gate on execution, never a sandbox | README, `check.md`, `SECURITY.md` |
| `contract-families` | Six umbrella contracts, each with covered / failed / coverage-gap fixtures | PROVEN | BENCH check, 46 cases | the contracts name defect classes; AIQE ships no validator for any of them | README, `families.md` |
| `coverage-gap` | An applicable contract with zero required validators is a `COVERAGE_GAP`, never a pass | PROVEN | BENCH check; control `NC_MISSING_QUANT_VALIDATOR` | — | README, `check.md` |
| `content-binding` | Committed blob and mode equal the content the validators checked | PROVEN | BENCH commit, 37 cases, 8 controls; proofs read back by the harness's own Git | binding covers owned paths, not a validator's internal inputs | README, `commit.md` |
| `precommit-not-reviewable` | `REVIEWABLE` is unreachable before a bounded commit | PROVEN | BENCH check + commit `precommit_reviewable_verdicts = 0` | asserted over every pre-commit state this build can produce | README, `receipt.md` |
| `bounded-pathset` | A bounded commit contains exactly the expected owned changed pathset | PROVEN | BENCH commit; control `NC-COMMIT-PATHSPEC` | the guarantee is about AIQE's commit, not about commits made any other way | README, `commit.md` |
| `foreign-staged` | Foreign staged state is byte-identical before and after, or the answer is `UNKNOWN` | PROVEN | BENCH commit; control `NC-COMMIT-FOREIGN-RACE` | drift is reported, not prevented | README, `commit.md` |
| `no-push` | AIQE never pushes | PROVEN | BENCH commit `aiqe_push_calls = 0`; Git allowlist carries no network subcommand | — | README, `architecture.md`, `SECURITY.md` |
| `pass-is-not-truth` | `PASS` is the recorded outcome of a declared command; it is not universal numerical correctness | DESIGN_INTENT | the product's own boundary statement, asserted by `test_documentation.py` | AIQE proves declared contract coverage and evidence, never universal quant truth | README, `check.md`, `product-spec.md` |
| `no-sandbox` | AIQE makes no filesystem or network claim about a validator | NOT_PROVEN (by design) | fixture `detached_child_escapes_the_process_group` | a descendant calling `setsid` outlives the group kill, and a fixture demonstrates it | README, `SECURITY.md` |
| `default-receipt-privacy` | The default receipt discloses no identity: no path, filename, repository name, remote, branch, commit or parent id, persistent repository identity, machine-local key, validator argv or output, username, hostname or task label | PROVEN | SUITE `test_receipt.py`, 30 tests: a closed field allowlist and a closed string-value allowlist, plus an exclusion list checked against the fixture's real values | the shareable surface is the default; `--local` is opt-in and deliberately richer | README, `SECURITY.md`, `receipt.md` |
| `local-state-owner-only` | AIQE's own local state is owner-only whatever the umask, and state AIQE did not create is refused rather than repaired | PROVEN | SUITE `test_local_state_privacy.py`, 28 tests: directory and file modes asserted under `umask(0)`, including each temporary file before its rename; symlink, ownership and permission refusals | validates AIQE's own components only; the directories above `$XDG_STATE_HOME` are the operating system's business | README, `SECURITY.md` |
| `starter-example-illustrative` | The published starter configuration declares all six contract families and binds a required validator to each; its validator commands are placeholders the adopter implements or replaces, and a change to one of its quant surfaces is refused while those commands are unwritten | PROVEN | SUITE `test_documentation.py`: parsed by the real fail-closed parser with all six families on a surface and bound to a required validator, plus an end-to-end case driving the real check path — the example copied byte-for-byte, a generic suite that passes, and the quant contracts still `CONTRACT_UNKNOWN` with no commit created | **it is not a claim that a copied file cannot reach `REVIEWABLE`.** A change to a path the example declares non-quant, such as `scripts/**`, applies no quant contract, and with every applicable declared check passing `REVIEWABLE` is correct; a second end-to-end case holds that open. Copying the file establishes nothing about whether a repository's quant work is adequately checked | README, `config.md`, `examples/aiqe.toml` |
| `no-network-client` | The deterministic product contains no network client | PROVEN | SUITE `test_network.py`, 9 tests: no network-capable import in any source file or on import of the package, no socket entry point reached during a Doctor run, Git the only program spawned, and no remote-contacting subcommand in either Git allowlist | a validator AIQE runs is ordinary local code and may reach the network; that is `no-sandbox`, not this | README, `SECURITY.md`, `architecture.md` |

## Numeric claims

Every number below is rendered or gated from a retained artifact. No number in
the README's conformance block was typed.

| id | claim | class | evidence | limitation | surfaces |
|---|---|---|---|---|---|
| `bench-totals` | 149 cases · 146 passed · 0 failed · 3 skipped · 24 of 24 controls | PROVEN | BENCH, rendered by `render-assets.py`, drift-checked in the suite | one retained run, AIQE 0.1.0a0 on darwin; skips are named, not dropped | README conformance block |
| `zero-tolerance` | Twelve zero-tolerance quantities, all at zero | PROVEN | BENCH `totals` in all four families | each counts what [`../bench/README.md`](../bench/README.md) defines; `local_state_writes = 0` is **not** "AIQE writes no local state" | README conformance block |
| `runtime-deps` | 0 third-party runtime dependencies | PROVEN | MANIFEST `runtime_dependency_count`, measured by installing into a fresh environment | — | README, `support.md`, `architecture.md` |
| `local-suite` | 963 passed, 0 failed, 0 errored, 21 skipped | OBSERVED | local run, this machine, 2026-09-07 | a local result; the surfaces CI proves are in MANIFEST | not published |
| `race-diagnostic` | `aiqe_commit_git_writes` | NOT_PROVEN (non-authoritative) | BENCH commit `diagnostics`, excluded from every comparison | two correct runs legitimately disagree; the stable fact is `aiqe_commit_git_writes_observed` | `bench/README.md` only |
| `user-effect-benchmark` | No user-effect benchmark has been published: no controlled comparison of productivity, development time, token or context use, model or agent performance, or defect-prevention rate exists | NOT_PROVEN | none — no such measurement has been made | conformance evidence measures AIQE's own behaviour and is not evidence about any of these; the README states the absence rather than reserving space for numbers that do not exist | README, `product-spec.md` |
| `time-to-value` | a first useful result in about five minutes | DESIGN_INTENT | none — family E is deferred | no fixture measures it, so no duration is published anywhere | README section title |

## Support and packaging claims

| id | claim | class | evidence | limitation | surfaces |
|---|---|---|---|---|---|
| `python-range` | Python 3.11 · 3.12 · 3.13 · 3.14 proven on macOS and Linux | PROVEN | MANIFEST `python_support`, each minor with `families_by_level` | tiered: installed-artifact end-to-end on both families for all four; full suite on Linux for all four and on macOS at 3.11 and 3.14 | README, `support.md` |
| `os-surfaces` | macOS 15 and 26, Ubuntu 22.04 and 24.04, x86_64 and arm64 | PROVEN | MANIFEST `tested_os_arch_surfaces` | exactly those releases; architecture is never inferred from a pure-Python wheel | README, `support.md` |
| `git-floor` | Git 2.32 is the enforced minimum; below it AIQE refuses | PROVEN | MANIFEST `git_compatibility`; refusal exercised on real Git 2.30.2 (Debian 11) | the floor is a mechanism argument about `GIT_CONFIG_SYSTEM`/`GIT_CONFIG_GLOBAL`, not a bisect | README, `support.md` |
| `git-unexercised` | Git 2.32 to 2.54 is permitted by the floor and covered by no run | NOT_PROVEN | MANIFEST `enforced_but_unexercised_range` | every surface that runs AIQE runs Git 2.55.0 | README, `support.md` |
| `install-paths` | wheel, sdist, `uv tool install`, `uvx --from`, all against a local artifact | PROVEN | MANIFEST `tested_install_paths`, `installed_artifact_e2e` | no registry publication is involved; obtaining uv itself uses the network | README, `support.md` |
| `wheel-reproducible` | The wheel is bitwise reproducible under a fixed `SOURCE_DATE_EPOCH` | PROVEN | MANIFEST `reproducibility.wheel_comparison_pinned.identical_bytes` | not bitwise reproducible by default | README, `support.md` |
| `sdist-reproducible` | The sdist is not bitwise reproducible | NOT_PROVEN | MANIFEST `reproducibility.sdist_comparison_pinned` | every packaged file is byte-identical; only archive metadata differs, so `affects_artifact_integrity` is false | README, `support.md` |
| `ci-head-attestation` | No complete CI run has attested the current `HEAD` | NOT_PROVEN | MANIFEST `source_commit` `5b477a9` ≠ `HEAD` | external billing capacity; no badge, and no green-CI claim | README (fold and `Where it runs`), `support.md` |
| `fold-platform-provenance` | The first fold states that macOS and Linux are proven by a retained full-lane release proof at the commit that manifest names, which is not the current one, and that no macOS evidence is claimed for any other commit | PROVEN | MANIFEST `source_commit` and `python_support`, restating `python-range` and `ci-head-attestation` in the fold rather than adding a claim | a restatement, carrying provenance into the fold so a reader who stops there is not left with a claim about `HEAD`; it must never be shortened to "proven on macOS and Linux", and it must not assert a CI run for the commit being read, which no unlanded candidate has | README (fold) |
| `windows` | Windows | OUT_OF_SCOPE | MANIFEST `out_of_scope`; no `Operating System ::` classifier in metadata | no implementation work done | README, `support.md` |
| `standalone` | A standalone bundled executable | OUT_OF_SCOPE | MANIFEST; the gate found no measured install friction | `DEFERRED` is not a roadmap entry: not planned, promised or dated | README, `support.md` |

## Demo and capture claims

| id | claim | class | evidence | limitation | surfaces |
|---|---|---|---|---|---|
| `demo-generic-suite` | A generic suite passes over the causality defect | PROVEN | DEMO `generic_suite_exit = 0`, `causality_validator_exit = 1` | one synthetic defect; the suite is not wrong, it answers a different question | README, demo README |
| `demo-coverage-gap` | Removing the validator leaves everything green and yields `COVERAGE_GAP` | PROVEN | DEMO act `nobody_looked` | — | README, demo README |
| `demo-absorbed-index` | An ordinary shared-index commit absorbs unrelated staged work the bounded commit excludes | PROVEN | DEMO `reference_changed_paths` vs `aiqe_changed_paths`, gated by `test_demo.py` | a statement about workflow semantics, not about Git being unsafe | README, demo README |
| `demo-stale` | Check, edit, commit: the reference workflow commits unchecked content; AIQE refuses | PROVEN | DEMO `reference_committed_unchecked_content = true`, `aiqe_commits_created = 0` | — | README, demo README |
| `demo-leaves-tree-clean` | Running the demo writes nothing inside the repository | PROVEN | SUITE `test_demo.py` `DemoOutputLocationTests`: output defaults to a fresh temporary directory, and the tracked results are asserted unmodified after a run | the retained artifacts are rewritten only when that path is passed to `--output` by name | README, demo README |
| `demo-summary-provenance` | Every value the demo prints is read from the record `expected.json` gates, not restated | PROVEN | SUITE `test_demo.py` `DemoSummaryTests`: the rendered summary is compared against the retained record, the `COVERAGE_GAP` row is lifted from the rendered check, and a perturbed record changes the rendering | the framing text and one sentence of interpretation are literal; every measured value is not | demo stdout, demo README |
| `captures` | Every published terminal block is retained output, not typed | PROVEN | CAPTURES index with per-capture digests; drift-checked by `render-assets.py` and the suite | seven captures, each naming its family, artifact, case and field | README, `docs/assets/` |

## Maintaining this file

A claim changes class only when its evidence does. Adding a row means naming
the retained artifact it rests on; if there is none, the claim is removed from
the public surface instead. Preferring removal over new measurement machinery
is the rule, not the exception.
