# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

An `Unreleased` section is always present. Entries are added in the pull request that
makes the change, not at release time.

## [Unreleased]

### Changed

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
