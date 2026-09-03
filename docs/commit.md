# `aiqe commit`

One bounded completion commit, and the proof that it is one.

```
aiqe commit -m <message>
```

That is the whole surface. There is no `--amend`, no `--no-verify`, no
`--allow-empty`, no `--push` and no `--force`, and their absence is the feature:
every one of them is a way to make the command succeed by weakening the claim it
makes.

`aiqe commit` **consumes** a green check. It does not run one, and it never reruns a
validator.

## The guarantee

The claim is not "Git returned zero". It is:

```
expected checked pathset  ==  actual parent-to-commit changed pathset
committed owned tree state ==  expected checked-in tree state
foreign staged state PRE   ==  foreign staged state POST
```

Only when all three hold does the receipt say:

```
Owned scope       VERIFIED
Foreign staged    EXCLUDED
Checked content   BOUND
Commit            CREATED
Push              NOT_PERFORMED_BY_AIQE
Verdict           REVIEWABLE
```

`REVIEWABLE` is reachable from here and from nowhere else.

## Order of operations

```
 1  the active task, and no completion commit for it yet
 2  current check evidence, at REVIEWABLE_CANDIDATE
 3  supported topology and operation state
 4  effective Git configuration, includes resolved
 5  commit policy: hooks, signing, external check-in filters
 6  the expected checked-in state of every owned path
 7  the expected parent-to-commit changed pathset
 8  staleness, recomputed immediately before the mutation window
 9  the authoritative foreign staged snapshot
10  transactional intent-to-add
11  the bounded commit
12  HEAD before and HEAD after, not the exit status
13  parent, pathset and content proof
14  the foreign staged snapshot again, against the same baseline
```

Steps 1 to 8 write nothing. The first byte AIQE writes is step 10.

## Preconditions

```
an active task in this worktree
no prior AIQE completion commit for that task
current HEAD == checked HEAD == task start HEAD
current aiqe.toml digest == checked digest
current validator definition digests == checked digests
current bounded owned-content binding == checked binding
internal completion state == REVIEWABLE_CANDIDATE
```

Drifted authority is exit `2` with the reason named — `STALE_OWNED_CONTENT`,
`STALE_HEAD`, `STALE_CONFIG`, `STALE_VALIDATOR_DEFINITION` — and no index mutation.

## Effective Git semantics

This is deliberately different from Doctor.

Doctor reads repository-scope configuration files, does not follow `include`, and
reports "unresolved" rather than presenting a value pulled out of a chain it did not
follow. That boundary is right for first-contact inspection.

A commit cannot use it. The commit AIQE creates is the commit your Git would create,
so the policy it must respect is the **effective** one: system, global, local,
worktree and command scope, with `include` and `includeIf` resolved, exactly as Git
resolves them. AIQE asks Git for that resolution rather than reimplementing it.

If it cannot be resolved:

```
exit 3   EFFECTIVE_CONFIG_UNRESOLVED
```

A `~/.gitconfig` Git cannot parse makes *every* Git invocation fail, including the one
that answers "which repository is this". AIQE establishes that cause before reporting
the symptom, so you are told the configuration is unresolvable rather than that there
is no repository here.

### What is suppressed, and what is not

Only non-semantic execution behaviour is neutralised:

```
core.fsmonitor      a child process started during an index refresh
gc.auto             background maintenance, which writes after the command
maintenance.auto    has already returned
```

None of the three changes what a commit contains. Nothing that does is touched.

## Commit policy: five refusals, all fail-closed

Each is exit `3`, with `commit = NONE`, the index unchanged, and zero executions of
the thing being refused.

**An active commit hook.** `pre-commit`, `prepare-commit-msg`, `commit-msg` and
`post-commit`, under the effective `core.hooksPath` or the repository's own hooks
directory. Active means what Git means: a regular file with an execute bit. A hook
path that is a symbolic link, a directory or anything else is ambiguous rather than
absent, and ambiguity fails closed — resolving the link to see what is on the other
side is already acting on a path AIQE has decided it cannot characterise.

```
exit 3   COMMIT_HOOK_POLICY_UNSUPPORTED
```

AIQE does not pass `--no-verify`. v1 does not run hooks, and the honest form of "does
not run" is a refusal, not a bypass.

**Automatic commit signing.** An effective `commit.gpgSign` that is true, from any
scope including one reached through `include` or `includeIf`.

```
exit 3   COMMIT_SIGNING_POLICY_UNSUPPORTED
```

AIQE does not pass `--no-gpg-sign`. Disabling your signing policy to make a commit
succeed is not a feature.

**An external check-in filter on an owned path.** The `filter` attribute is resolved
with Git's own attribute machinery — tracked `.gitattributes` at every level,
`$GIT_DIR/info/attributes`, and the effective `core.attributesFile` — and the driver's
configuration is resolved from the effective chain. If the pair exists, and the driver
defines `clean` or `process`:

```
exit 3   CHECKIN_FILTER_UNSUPPORTED
```

A driver that is configured and bound to nothing is **not** a blocker. Refusing there
would make AIQE unusable on any machine that has ever installed Git LFS, and would
teach its users that its refusals are noise.

The ordering here is the safety property, and it is measured rather than reasoned
about: `git check-attr` leaves a filter canary unwritten, and `git hash-object --path`
fires it. So the refusal happens before any expected-state derivation.

**Unsupported topology or operation state.**

```
exit 3   MERGE_IN_PROGRESS · REBASE_IN_PROGRESS · CHERRY_PICK_IN_PROGRESS
         REVERT_IN_PROGRESS · SEQUENCER_IN_PROGRESS · BISECT_IN_PROGRESS
         UNMERGED_INDEX_ENTRIES · SPARSE_CHECKOUT_UNSUPPORTED
         DETACHED_HEAD_UNSUPPORTED
```

Linked worktrees are supported and proved. A detached HEAD is refused because it has
not been proved as a completion surface, and claiming support AIQE has not tested is
the thing this product exists not to do.

**An unresolvable effective configuration**, above.

## Literal paths

Every Git invocation carries `--literal-pathspecs`. A repository path is a byte
string, and `*`, `?`, `[abc]`, `:(top)` and a leading dash are names rather than
syntax. `--` is used as an option terminator and is *not* the mechanism that makes a
path literal.

Because pathspec magic is globally off, a `:(literal)` prefix would be read as part of
the filename, so none is used. Machine-readable Git path output is NUL-delimited
everywhere Git supports it.

Retained fixtures cover `star*.py`, `q?.py`, `br[ack].py`, `:(top)magic.py`,
`-dash.py`, names containing spaces, tabs and newlines, and — on Linux — a filename
that is not valid UTF-8.

## Expected checked-in state

Before any mutation, each owned path is bound to one expected committed state:

```
regular blob OID + Git mode
absent (a deletion)
absent (declared but never created)
```

The blob identity comes from `git hash-object --path=<repository-relative path>`,
which applies exactly the check-in transformations Git would apply and writes nothing.

This matters most where it is least obvious. Under `core.autocrlf` or a `* text`
attribute, the committed blob is deliberately **not** the worktree bytes:

```
checked raw worktree bytes  !=  committed blob bytes
committed blob  ==  Git-supported transformation of the exact checked bytes
→ CHECKED_CONTENT_BOUND = TRUE
```

`aiqe check` compares raw bytes and is conservative in the safe direction — it can
over-report a change. A commit cannot afford that conservatism, because comparing raw
bytes against the stored blob would report a mismatch on a *correct* commit: a false
alarm from the mechanism whose whole job is to be believed.

Modes follow the effective `core.fileMode`. Where it is true the worktree execute bit
decides; where it is false Git preserves the recorded mode, so the expectation does
too. Both were measured, not assumed. `100644`, `100755` and a mode change are
retained fixtures.

The **expected changed pathset** is the subset of owned paths whose expected committed
state differs from the pre-commit HEAD tree. If it is empty:

```
exit 2   NO_OWNED_CHANGES_TO_COMMIT
```

No `--allow-empty`. A commit that records nothing is not a bounded completion commit;
it is a marker pretending to be one.

## The pre-mutation staleness check

Everything above takes time — resolving configuration, hashing owned content,
resolving attributes — and an owned file edited during that time would otherwise be
committed against a check that never saw it. So immediately before the first index
mutation the bounded authority is recomputed once more: HEAD, the owned-content
binding, the `aiqe.toml` digest and the validator definition digests.

Any drift stops the operation with `commit = NONE`, `index mutation = NONE`, exit `2`.

This is the canonical check-edit-commit defence, and it is the negative control
`NC-COMMIT-STALE`.

## Transactional intent-to-add

A new owned file Git does not yet know about needs `git add -N` before
`git commit --only` will accept it. Intent-to-add is transactional:

```
ITA paths are exact owned paths only
literal-pathspec semantics are mandatory
no foreign path is touched
```

If anything fails before a completion commit exists, the AIQE-created entries are
removed one at a time and the removal is verified. A whole saved index file is
deliberately **not** restored: that would overwrite whatever a concurrent process
staged in the meantime, trading a small failure for a large one.

If the scoped rollback cannot be completed and proved:

```
exit 2   ITA_ROLLBACK_INCOMPLETE
```

and no completion is claimed.

## The commit

```
git --literal-pathspecs commit --only -m <message> -- <expected changed paths...>
```

Never `git commit`, `git commit -a`, `--amend`, `--no-verify`, `--no-gpg-sign` or
`--allow-empty`. No editor is involved, because `-m` is mandatory.

The message is your data. AIQE stores none of it and echoes none of it, so no commit
message can reach a shareable receipt.

## Never infer success from an exit code

`git commit` can fail after creating a commit. So what is recorded is HEAD before and
HEAD after.

**No commit created.** The AIQE-created intent-to-add entries are rolled back, the
rollback is verified, and no successful-commit evidence is stored.

**A commit exists, whatever Git returned.** Nothing is rolled back and nothing is
rewritten. The proof runs, and its result is reported.

## Post-commit proof

**Ancestry.** Exactly one parent, and it is the pre-commit HEAD.

**Pathset.** The actual parent-to-commit changed pathset, read NUL-safely with rename
detection disabled, must equal the expected owned changed pathset — no foreign path,
no missing expected path.

**Content.** For every owned path, the committed blob OID and Git mode must equal the
precomputed expected checked-in state, or the path must be absent as expected. Bounded
to the owned pathset: there is no whole-tree fingerprint.

A commit that exists and violates any of these is reported, not concealed:

```
Verdict  NOT_REVIEWABLE   exit 1
```

AIQE does not reset, revert or amend it away. Evidence truth outranks tidiness.

## Foreign staged state

Immediately before the first index mutation, and again immediately after the commit
against the **same** pre-commit HEAD, AIQE captures the staged delta over every
non-owned path — as a structured record, not a count:

```
addition · modification · deletion · mode or type change
```

NUL-safe, rename detection disabled, and no foreign worktree or untracked content is
ever hashed.

```
PRE == POST   →  FOREIGN_STAGED_NON_RESET proven  →  EXCLUDED
any difference →  FOREIGN_STAGED_STATE = UNKNOWN  →  INCOMPLETE, exit 2
```

A difference includes a *newly appearing* foreign entry. AIQE does not discard one as
"not pre-existing", and does not claim it caused the drift. This is the negative
control `NC-COMMIT-FOREIGN-RACE`.

## Exit semantics

```
0   bounded completion commit created and fully verified
1   a completion defect: a commit exists and violates parent, pathset or content
2   incomplete: stale evidence before mutation, an empty expected pathset,
    ITA rollback incomplete, or foreign staged state UNKNOWN
3   unsupported, configuration or policy refusal
```

There is no exit `4`.

## Task lifecycle

A completion commit stays associated with the active task so `aiqe receipt` can render
its proof. A second `aiqe commit` for the same task refuses:

```
exit 3   COMPLETION_COMMIT_ALREADY_CREATED
```

`aiqe task end` removes the task's check evidence *and* its commit evidence. Recorded
validator consent survives, because consenting to run a command is a statement about
that command rather than about one unit of work. A new task can never inherit a
previous task's completion commit.

If HEAD moves off the completion commit before the task ends, the receipt stops
claiming a current reviewable state and reports `COMPLETION_COMMIT_SUPERSEDED`. This
is not a verifier for arbitrary historical commits and does not become one.

## AIQE never pushes

```
AIQE_PUSH_CALLS = 0
```

This is a property of the code rather than a promise in prose: the Git allowlist
`aiqe commit` runs through contains no network subcommand, the guard raises rather
than degrading, and the test suite asserts both.

The receipt wording is `Push = NOT_PERFORMED_BY_AIQE`. It is a statement about AIQE,
and deliberately not a claim that nobody else pushed concurrently.

## Write confinement

During `aiqe commit` the expected Git mutations are the index, the object database,
HEAD, the ref and its reflog, and ordinary commit metadata, plus AIQE's own
machine-local evidence record. `.git` byte immutability is **not** claimed, because a
command whose job is to create a commit cannot make that claim honestly.

What is claimed, and measured from outside the process:

```
AIQE_CORE_WORKTREE_MUTATIONS = 0
exact bounded commit pathset
foreign staged structured-delta preservation
```

## Commit evidence

One local record per task, `COMMIT_EVIDENCE_SCHEMA_VERSION = 1`, alongside the check
evidence in AIQE's machine-local state. It holds the task id, timestamps, the parent
and created commit, both changed pathsets, the expected and actual owned tree states,
the foreign staged structured deltas and their digests, the commit-policy preflight
results and the AIQE version.

It does not hold the commit message, the repository name, the remote, the branch, the
worktree location or the environment. There is no commit history database.

The default receipt still carries no commit identifier, no filename, no branch and no
repository identity: it gains a state and a count. `aiqe receipt --local` shows the
allowlisted identifiers, because you are standing in that repository.

## Residual limitations

- The post-commit receipt checks that HEAD is still the completion commit. It does not
  re-verify the commit's content on every render, and an owned file edited *after* a
  correct commit does not falsify the claim the receipt makes about that commit.
- A detached HEAD is refused rather than supported.
- No fixture produces a post-commit `NOT_REVIEWABLE`, because a commit AIQE constructs
  correctly cannot violate its own construction. The verdict table is exercised
  directly instead, so the defect AIQE would report is one it can be shown to report.
- Symbolic links, submodules and special files are refused by Task Core's owned-path
  rules and are not committed.
- Only EOL normalisation has a retained fixture. Other built-in attribute-driven
  transformations — `ident`, `working-tree-encoding` — are covered by construction
  rather than by a case, because the expected state comes from Git's own
  `hash-object --path` rather than from a reimplementation of Git's rules. Only
  external `clean` and `process` drivers cause refusal.
- Windows is out of scope in v1.
