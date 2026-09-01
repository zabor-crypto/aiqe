# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

An `Unreleased` section is always present. Entries are added in the pull request that
makes the change, not at release time.

## [Unreleased]

### Added

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
