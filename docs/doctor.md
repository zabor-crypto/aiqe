# `aiqe doctor`

First-contact repository diagnosis. It runs before `aiqe init`, needs no configuration,
and is the only AIQE command that is implemented today.

```
aiqe doctor
aiqe doctor --format json
```

## What it is for

You point AIQE at a repository it has never seen. Before anything is written, Doctor
answers: is this a repository AIQE can work in, what state is it in right now, and what
about this repository would change what AIQE is later able to do?

It is not a linter. It emits no generic engineering advice, and every finding it
produces is specific to the repository in front of it.

## The safety contract

Doctor is the first thing that touches a stranger's repository, so what it does *not* do
is the specification.

```
repository mutations              0
tracked-file mutations            0
index mutations                   0
AIQE local state writes           0

repository-defined executions     0
repository validators executed    0
hooks executed                    0

network requests                  0
model calls                       0

Git configuration mutations       0
hooks installed                   0
```

None of this is self-reported. The benchmark harness takes a byte-level snapshot of the
whole isolated fixture directory before and after each run — content hashes, sizes,
modes and modification times — and compares them. Fixtures that configure a hook, an
fsmonitor, a filter driver or a shell alias install a canary that would leave a marker
if it were ever executed. The harness asserts that no canary fired.

See [`../bench/fixtures/doctor/harness.py`](../bench/fixtures/doctor/harness.py) for the
measurement and [`../bench/results/doctor/results.json`](../bench/results/doctor/results.json)
for the retained result.

## Why `git status` is not safe by default

Four behaviours drive most of Doctor's implementation. All were measured, not
assumed, and each has a negative control that reproduces the failure on demand.

**`git status` writes the index.** On a worktree that is stat-dirty but
content-identical — a tracked file rewritten with the same bytes, or merely
touched — a plain `git status` refreshes the cached stat information and
rewrites `.git/index`. Content and modification time both change.
`--no-optional-locks` suppresses that write while leaving the reported state
correct, and Doctor passes it on every invocation.

**`git status` executes repository-defined commands.** `core.fsmonitor` is run
as a child process during the index refresh, and `--no-optional-locks` does not
prevent it; a per-invocation `-c core.fsmonitor=false` override does, in every
configuration scope, and Doctor passes that too.

**The command a repository selects need not be defined in the repository.** A
tracked `.gitattributes` saying `*.dat filter=lfs` binds a path to a driver
whose `clean` or `process` command may be defined in the user's global
configuration, or in a file pulled in by a local `include`. Repository content
selects; external configuration supplies the executable. Reading only the
repository's own configuration and concluding "no filter here" is not enough —
and it was not: the canaries fired.

**`git status` descends into submodules and runs their filters.** A submodule's
own local configuration is repository scope for that submodule, so isolating
the superproject's configuration does not reach it.

## The two defences

**Configuration isolation.** Every invocation that reads the index or the
worktree — `status`, `diff-index`, `ls-files` — runs with system and global
configuration switched off. Git cannot execute a definition that is not in
scope. Discovery invocations are deliberately *not* isolated: they answer
"which repository is this", and answering that differently from the user's own
Git would be its own defect.

**Static refusal.** Isolation cannot help once a definition is already in
repository scope. Doctor therefore declines to compare worktree content, and
reports the unstaged count as `UNKNOWN`, whenever any of these hold:

```
a filter driver is defined in the repository's own configuration
the repository configuration includes a file Doctor will not follow
repository attributes bind any path to a filter driver
a repository attributes file is declared but could not be read
```

The third is deliberately broad. Doctor cannot see everywhere a driver might be
defined, so the binding alone is treated as unsafe — a repository using Git LFS
will report an unknown unstaged count rather than a number obtained by running
`git-lfs`.

Submodules are handled separately, because refusing there would cost more than
it buys: `status` is invoked with `--ignore-submodules=dirty`, which prevents
the descent while still reporting a changed submodule pointer. The counts then
exclude submodule worktree changes, and say so.

`UNKNOWN` is the correct product answer in all of these. A precise number
obtained by running a repository's own command is not a better answer; it is
the wrong answer to a different question.

### What isolation costs

Stated rather than hidden. A working-state count is computed under
repository-scope configuration only, so:

- a custom global `core.excludesFile` does not apply, and the untracked count
  may exceed what plain `git status` reports;
- a repository whose access depends on a global `safe.directory` entry yields
  an unknown working state rather than a wrong one;
- where a filter is bound entirely outside the repository — the binding in a
  global attributes file as well as the driver — Doctor cannot detect the
  binding at all. Isolation still prevents the execution, but the comparison is
  then made on raw bytes, ignoring a filter the user's own Git would apply.

## The configuration boundary

Doctor reads the repository's own Git configuration files as text. It does **not** ask
Git to resolve configuration, and it does **not** follow `include` or `includeIf`.

Asking Git for a value resolves the whole chain, so an `include.path` pointing anywhere
on the filesystem silently becomes part of the answer. When a chain is present, Doctor
reports `GIT_CONFIG_INCLUDE_UNRESOLVED` and stops there rather than presenting a value
pulled out of it as established fact.

Resolving the effective configuration is a higher-authority operation belonging to
commit preflight, which must either resolve it unambiguously or refuse. Doctor is not
that operation.

Two files are in scope: the repository configuration in the common Git directory, and
the per-worktree configuration when the `worktreeConfig` extension is enabled. No
configuration outside the repository is read, and nothing above the worktree root is
inspected.

## States

```
OK           determined, and needs no attention. Doctor emits no finding for an OK
             condition: silence in the findings list is what OK looks like.
FINDING      determined, and worth attention, because it changes what AIQE can do here.
UNKNOWN      not determinable inside the first-contact safety boundary. A real result,
             never rendered as a pass.
UNSUPPORTED  a condition AIQE does not support, such that the operation cannot proceed.
```

These are Doctor's own states. They are deliberately not `REVIEWABLE`, `INCOMPLETE` or
`NOT_REVIEWABLE`, which are task receipt verdicts. Doctor describes a repository; it
adjudicates nothing.

There is no safety score, and a clean repository renders as an absence of findings
rather than a green badge.

## Finding codes

The code is the machine identity. The summary prose may be reworded; a consumer that
matches on prose is doing it wrong.

### Repository

```
REPOSITORY_ABSENT                  no Git repository at this location
REPOSITORY_BARE                    bare repository; AIQE requires a worktree
REPOSITORY_UNBORN_HEAD             HEAD points at a branch with no commits yet
HEAD_DETACHED                      HEAD is at a commit rather than on a branch
REPOSITORY_TOPOLOGY_UNRESOLVED     the repository layout could not be resolved
GIT_UNAVAILABLE                    Git could not be run
GIT_VERSION_UNKNOWN                Git ran but reported no recognisable version
```

### Working state

```
WORKING_STATE_UNKNOWN              Git did not report the working state
WORKING_STATE_UNSTAGED_UNKNOWN     the unstaged count was not determined, because
                                   determining it would execute a check-in filter
UNMERGED_PATHS_PRESENT             the index contains unmerged paths
```

### Topology

```
LINKED_WORKTREE                    a linked worktree sharing a Git directory
SPARSE_CHECKOUT_ACTIVE             the worktree does not contain every tracked path
SPARSE_CHECKOUT_UNRESOLVED         a sparse pattern file exists but the enabling
                                   setting was not found
```

### Operations in progress

```
OPERATION_MERGE_IN_PROGRESS
OPERATION_REBASE_IN_PROGRESS
OPERATION_CHERRY_PICK_IN_PROGRESS
OPERATION_REVERT_IN_PROGRESS
OPERATION_BISECT_IN_PROGRESS
```

### Git policy and execution-capable configuration

```
GIT_CONFIG_UNREADABLE              a configuration file could not be parsed
GIT_CONFIG_INCLUDE_UNRESOLVED      an include chain is present and was not followed
GIT_HOOKS_PATH_CONFIGURED          core.hooksPath is set
GIT_HOOKS_PRESENT                  executable hooks are installed
COMMIT_SIGNING_CONFIGURED          commit signing is configured locally
CHECKIN_FILTER_CONFIGURED          a filter driver is configured
TRACKED_GITATTRIBUTES              a tracked .gitattributes is present
FSMONITOR_CONFIGURED               core.fsmonitor is configured
EXECUTABLE_ALIAS_CONFIGURED        shell-executing Git aliases are configured
```

### Agent surface

```
AGENT_CONFIG_UNREADABLE            an agent settings file could not be parsed
CLAUDE_PERMISSIONS_BROAD           Claude Code settings grant unconstrained execution
CODEX_PERMISSIONS_BROAD            Codex configuration disables approval or sandboxing
```

The two "broad" findings are claimed only under rules that can be stated exactly.

For Claude Code, a repository `.claude/settings.json` or `.claude/settings.local.json`
is broad when `permissions.defaultMode` is `bypassPermissions`, or when
`permissions.allow` contains an entry granting shell access with no constraint on the
command.

For Codex, a repository `.codex/config.toml` is broad when a top-level assignment, after
comment stripping, is exactly `approval_policy = "never"` or
`sandbox_mode = "danger-full-access"`. This is a bounded textual scan, not a TOML
evaluation.

Anything else is reported as **present**, never as *bounded*. Doctor does not certify an
agent configuration as safe; it reports the one shape it can recognise without
interpretation.

## Exit status

Doctor uses the canonical AIQE exit vocabulary and adds nothing to it.

```
0   a valid first-contact diagnostic was produced
3   a valid Doctor result could not be produced
```

A finding is part of a valid diagnostic, so findings never change the exit status.
Neither do unknowns. Doctor never exits 1 or 2: those codes belong to commands that
adjudicate completion.

Exit 3 covers an invalid invocation — an unknown command, an unknown flag, an unknown
`--format` value — and a repository whose topology cannot be diagnosed, such as a bare
repository.

Outside a repository, Doctor exits **0**. Reporting "this is not a repository" is a
valid diagnostic, and the `REPOSITORY_ABSENT` code carries the detail. Doctor does not
initialise anything and does not write anything there.

## JSON output

`--format json` is deterministic: keys are sorted, findings are ordered by state and
then by code, and nothing depends on wall-clock time, environment or run order. The same
repository state renders identical bytes.

```
schema_version          bumped only when the shape changes incompatibly
aiqe_version
command                 "doctor"
result                  "PRODUCED" | "UNSUPPORTED"
exit_code
git                     { available, version }
repository              { detected, kind, head }
topology                { linked_worktree, sparse_checkout }
operations_in_progress  [ finding codes ]
working_state           { determined, staged, unstaged, untracked, unmerged,
                          submodule_worktrees_excluded }
aiqe                    { config_present }
commit_policy           { ... booleans ... }
agent_surface           { ... presence and permission categories ... }
findings                [ { code, state, summary } ]
state_counts            { OK, FINDING, UNKNOWN, UNSUPPORTED }
```

A count that was not determined is `null`, never `0`.

## Privacy

Doctor is local. There is no telemetry, no analytics, no network access, no model call,
no crash upload and no update check.

Neither rendering discloses the branch name, the commit identifier, the remote URL, the
worktree path, the home directory or the username. A Doctor result is the thing users
paste into an issue and put in a screenshot, so it carries counts, booleans and
categories.

## Known limitations

**The unstaged count is unavailable whenever comparing content could execute
something the repository selected.** This is a deliberate refusal, not a
defect, and it is reported as `UNKNOWN` rather than guessed. A repository using
Git LFS, or any other filter driver, falls in this category.

**Submodule worktree changes are not counted.** Counting them means descending
into each submodule and running its filters. A changed submodule *pointer* is
still reported, and the output says when the counts exclude submodule
worktrees.

**Working-state counts use repository-scope configuration only.** A custom
global `core.excludesFile` does not apply to the untracked count; a repository
reachable only through a global `safe.directory` entry yields an unknown
working state; and a filter bound entirely outside the repository is invisible
to Doctor, so the comparison ignores it. See "What isolation costs" above.

**Effective Git configuration is not resolved.** Doctor reports the presence of
an include chain and nothing about its contents. A repository whose real policy
lives behind `includeIf` shows `GIT_CONFIG_INCLUDE_UNRESOLVED` and no policy
findings.

**Configuration outside the repository is not reported.** Global and system Git
configuration can enable commit signing or a hooks path that Doctor does not
report. Absence of a policy finding is not a claim that no policy applies.
Isolation prevents such configuration from *executing* during a Doctor run; it
does not make Doctor a reporter of it.

**Agent configuration detection is narrow.** It recognises the shapes described
above and nothing else, and inspects repository-level files only.

**The no-network evidence is not kernel-level.** AIQE Doctor contains no
network feature and no network code path, and made no network call in the
retained test harness: the package declares no third-party dependency and
imports no network-capable standard library module; a full run executes with
every socket entry point replaced by a trap, and nothing is called; and the
only program AIQE core spawns is Git, through a single choke point, restricted
to a frozen allowlist of local subcommands. No network namespace or packet
filter is applied, and no claim of operating-system-level impossibility is
made.

**Installing the package uses the network.** That is the installer's behaviour,
not AIQE's runtime behaviour, and the two are not interchangeable.

**Python 3.11 is the support floor**, and 3.11 and 3.14 are the tested
endpoints. Versions between them are not claimed. This is a support boundary,
not a claim that older interpreters fail.

**macOS is the supported target.** The suite is also run on Linux in CI —
which is where the arbitrary-byte path case can exist at all, since APFS
refuses non-UTF-8 filenames — but that is portability evidence, not a Linux
release claim. Windows is out of scope for v1.
