# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

An `Unreleased` section is always present. Entries are added in the pull request that
makes the change, not at release time.

## [Unreleased]

### Security

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

- No version has been released and no tag has been created. `doctor` is implemented;
  `init`, `task`, `check`, `commit` and `receipt` remain design targets and are not
  stubbed.
- Only the Doctor benchmark family has results. Every other family remains `NOT_RUN`,
  and no aggregate benchmark completion is claimed.
- macOS is the supported target. The suite is also run on Linux in CI, which is evidence
  but not a release claim.
