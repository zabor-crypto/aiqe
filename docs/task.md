# `aiqe task`

The task boundary: which repository paths this unit of work owns.

```
aiqe task start --own <path>... [--label <text>]
aiqe task
aiqe task end
```

It works before `aiqe init`, which does not exist yet. A task needs a
repository and nothing else.

## What a task is, and is not

A task answers exactly one question:

> Which exact repository paths does this AIQE task own?

It does not answer whether checks passed, whether evidence is fresh, whether
the work is reviewable, or whether it can be committed. Those belong to
`check`, `receipt` and `commit`, none of which is implemented. Answering them
now would mean inventing completion semantics before the evidence that
justifies them exists.

One worktree holds one active task. Starting a second is refused.

## Owned pathset

**Ownership is exact.** Owning `foo` owns `foo`, and nothing else:

```
owns(foo, foo)      TRUE
owns(foo, foo/bar)  FALSE
owns(foo, foobar)   FALSE
```

There is no descendant ownership and no directory scope in v1. That is a
deliberate limitation, not an omission. A prefix rule would let a task
authorise files that did not exist when the scope was declared — declare
`build` today, and every file that appears under it tomorrow is inside the
scope — which is exactly the widening an owned scope exists to prevent. The
benchmark's `NC_TASK_PREFIX_OWNERSHIP_BROADENING` control demonstrates it
happening.

The claim the product makes is the strong one:

> AIQE knows the exact declared owned pathset.

A prefix rule cannot support that sentence. Directory ergonomics may be
reconsidered later, on measured demand; they are not in v1.

**Declared paths are literal.** A path is data, never a pattern:

```
--own '*'          declares a file named *
--own ':(top)'     declares a file named :(top)
--own --help       declares a file named --help
```

Nothing is expanded, and no declared path reaches Git as a pathspec. The
benchmark's `NC_TASK_PATHSPEC_EXPANSION` control shows the alternative: in a
repository containing a file legally named `*`, pathspec handling turns one
declaration into ownership of every tracked file.

**A declaration is not an observation.** An owned path need not exist:

```
aiqe task start --own src/new_module.py
```

is the normal case when the task is about to create it.

The filesystem is consulted for exactly one thing — refusing a path that
exists **today as a directory**:

```
aiqe task start --own src        # src/ exists
  -> OWNED_PATH_IS_DIRECTORY, exit 3
```

A directory declaration has no meaning under exact ownership, and both
tempting readings are wrong: expanding it would authorise files nobody
declared, and treating it as one path would own something that cannot be a
file. Declare the files the task owns instead. There is no flag to bypass
this.

If a declared path that did not exist later materialises as a directory, a
future operation that must resolve path identity fails closed rather than
reinterpreting the declaration as a scope. The record says a path was
declared, never that a directory was.

**Symlinks are path objects.** `--own link` owns `link`, not whatever it
resolves to. A symlink pointing at a directory is therefore accepted: the
declaration is about the link. Nothing follows a link to decide what is
owned.

**Paths keep their bytes.** A repository path is a byte string. Declared paths
round-trip exactly, including bytes that are not valid UTF-8 — proven end to
end on Linux, where such a filename can exist. Display is escaped; the stored
value is not.

### Resolution and canonicalisation

A relative path means what it looks like from where it was typed. From
`tests/`, `--own ../src/a.py` declares `src/a.py`.

Canonicalisation is limited to what is safe without touching the filesystem:
`.` components and repeated or trailing separators collapse, and exact
duplicate declarations become one. There is deliberately **no** Unicode
normalisation and **no** case folding — both would make two different
filenames look like one — and **no** symlink resolution, because the owned
identity is the repository path.

Two *distinct* paths never collapse, even when one is a lexical parent of the
other. Declaring both `docs` and `docs/guide.md` records two paths: under
exact ownership neither implies the other, so neither can absorb it.

### Refusals

```
OWNERSHIP_PATH_ABSOLUTE            an absolute path
OWNERSHIP_PATH_EMPTY               an empty path
OWNERSHIP_PATH_ESCAPES_REPOSITORY  a path that leaves the repository
OWNERSHIP_PATH_PARENT_AMBIGUOUS    '..' after a named component
OWNERSHIP_PATH_ADMINISTRATIVE      inside the Git administrative directory
OWNERSHIP_PATH_INVALID             a path containing a NUL byte
OWNERSHIP_SCOPE_TOO_BROAD          the repository root
OWNERSHIP_SCOPE_EMPTY              no owned path declared
OWNED_PATH_IS_DIRECTORY            a path that exists today as a directory
```

`--own .` is refused. AIQE's purpose is an explicit bounded pathset, and
owning everything is not one.

`src/../etc` is refused rather than silently treated as `etc`: the two are
only the same if `src` is not a symlink, and AIQE does not resolve symlinks to
decide what a path means. Leading `..` is fine — it walks back through the
invocation directory, which the operating system has already resolved.

## Where task state lives

```
<worktree git directory>/aiqe/task.json    the active task, if any
<worktree git directory>/aiqe/task.lock    the start/end mutex
```

Repository-local, Git-private, untracked by design. Not `$HOME`, not an XDG
directory, not the tracked worktree.

Not the *common* Git directory either, and that is the subtle part. A linked
worktree has its own Git directory under `…/.git/worktrees/<name>` while
sharing the common one. Task state in the common directory would give two
worktrees one task between them; the benchmark's
`NC_TASK_SHARED_WORKTREE_STATE` control shows exactly that happening. Two
linked worktrees hold two independent tasks.

Nothing here writes to anything Git owns: no config, no index, no refs, no
hooks, no HEAD.

### If the location is unsafe

If `…/aiqe` or `task.json` exists as something other than the expected kind — a
symlink, a directory where a file belongs — AIQE refuses rather than following
it. Writing through a symlink planted in a repository would put AIQE's own
writes somewhere it never promised to write.

## Local internal state schema

```
LOCAL INTERNAL STATE SCHEMA
version 2 · not user-edited · not a public integration surface before 1.0
```

Do not build on this shape yet. It is documented so the state is auditable,
not so it can be integrated against.

```
schema_version        2
ownership_semantics   "exact_literal_pathset_v1"
task_id               opaque random local identifier
aiqe_version
started_at            UTC, to the second
start_head_state      "commit" | "unborn"
start_head_sha        the commit, or null when HEAD is unborn
owned_paths           [ { "path_b64": base64(raw repository-relative bytes) } ]
owned_pathset_digest  "sha256:<hex>"
label                 the text given to --label, or null
```

`ownership_semantics` is recorded in every task so a reader never has to infer
from a version number what a declared path meant.

Paths are base64-encoded because the record is JSON and JSON is text. A path is
bytes, and round-tripping it through a text encoding is exactly the lossy step
this product cannot afford.

Deliberately absent: the worktree path, the remote URL, the repository owner or
name, the branch, the hostname, the username and the email address. None is
needed to say which paths a task owns, and every one turns a local state file
into something that identifies a person or a project if it is ever shared.

`task_id` is random and nothing but random. It encodes no username, hostname,
repository, branch or readable timestamp.

### Schema version 1 is refused, not migrated

Version 1 recorded ownership under different semantics: a declared path owned
its descendants. Reading such a record as an exact pathset would quietly narrow
a live task's authority, so this build refuses it:

```
aiqe task            -> exit 2, naming the schema mismatch
aiqe task start      -> exit 2, the record is left untouched
aiqe task end        -> discards it; a new task can then be started
```

There is no migration and no migration framework. This is local pre-release
state, and a sentence telling the user to end the task and start it again is a
better answer than machinery that guesses what an older record would have meant.

### The owned-pathset digest

Deterministic, and documented so a reviewer can recompute it:

```
SHA-256( "aiqe.owned-pathset.v1\0" + concat(path + "\0" for each sorted path) )
```

It binds the raw path bytes, the component boundaries and the canonical
ordering — and nothing else. It does not bind display text: two pathsets that
render alike but differ in bytes must produce different digests, and changing
how paths are printed must not change the digest. NUL is a safe delimiter
because a POSIX path cannot contain one.

Two spellings of the same path produce the same digest. `--own docs/` and
`--own ./docs` and `--own docs//` are one path; declaring a path twice is one
pathset entry. Two distinct paths never merge, so `docs` and `docs/guide.md`
digest differently from `docs` alone.

`start_head_sha` is recorded as the state the task began from. A task is **not**
invalidated in this slice because HEAD later changed — evidence freshness
belongs to `check`, and enforcing it here would be inventing a completion rule
ahead of the evidence.

## Atomicity and concurrency

Every state transition is a write to a temporary file in the same directory,
an `fsync`, and an atomic rename. A reader sees the old state or the new one,
never half of either. A process killed between the two leaves a temporary file
that is not a task: status says there is none, and the next start succeeds.

`start` and `end` take an exclusive `flock` on the state directory's lock file.
Two concurrent starts in one worktree produce one winner and one deterministic
refusal. The kernel releases the lock if a process dies, so a crash cannot
wedge a repository. Linked worktrees never contend, because the lock is where
the state is.

No daemon, no lock service, no database.

## Exit status

```
0   the operation succeeded
2   an active record exists but cannot be read
3   an invalid declaration, a refused operation, or an unsafe state location
```

Applied:

```
task start success                     0
task status, with or without a task    0
task end success                       0

invalid owned scope                    3
a task is already active               3
task end with no active task           3
unsafe state directory                 3
corrupt active task record             2
```

A task boundary adjudicates nothing, so it never exits 1 — that code is a FAIL
verdict and belongs to commands that produce one.

A corrupt record is `2` because it is *unknown*, not unsupported: something is
there and AIQE will not guess what. `aiqe task end` discards it, and that is
the documented way out — leaving a repository permanently unable to start a
task would be a worse answer than removing a record nothing can read.

## Terminal safety

Owned paths and labels are user-controlled data, and a repository can contain a
filename with a newline or an escape character. Printed literally, such a name
can move the cursor, colour the output, or draw a line that looks like another
status row.

Display escapes control characters and invalid bytes — `\n`, `\t`, `\xNN` — and
a backslash in a real filename is doubled so an escape and a literal cannot be
confused. The stored value is untouched: what AIQE records is the exact bytes,
what it prints is a rendering of them.

## What a task operation may change

```
TASK_WRITE_CONFINEMENT
```

AIQE's own writes stay inside `<worktree git directory>/aiqe/`. Starting,
showing or ending a task changes no tracked file, no untracked file, no index
entry, no ref, no hook and no configuration. A repository with staged work it
never told AIQE about keeps it: the index is byte-identical across start,
status and end.

The claim is scoped deliberately. It is about AIQE's own writes, not a promise
that nothing else on the machine can change the repository while AIQE runs.

Nothing a repository defines is executed to establish ownership — no hook, no
filter, no fsmonitor, no alias, no validator. Task operations use the same
hardened Git invocation Doctor uses, and only for discovery: no worktree
content is compared, so nothing can trigger a filter driver.

## Known limitations

**Ambiguity is not resolved here.** Whether two declared paths could refer to
the same file on a case-insensitive or normalising filesystem is not decided at
task start, because it depends on state that does not exist yet. It becomes a
question when a later operation must resolve path identity against actual
changes, and it fails closed there. The same applies to a declared path that
did not exist and later materialises as a directory.

**No directory ownership.** v1 owns an exact pathset. Declaring a directory is
refused, and declaring a path does not own anything under it. Directory
ergonomics may be reconsidered on measured demand; they are not in v1.

**Task end is not proven durable against power loss.** `clear_active` unlinks
the record and then fsyncs the containing directory, which is the mechanism
that would make the deletion survive, and a test asserts that fsync happens.
Demonstrating power-loss durability needs power loss, so the classification
stays `TASK_END_POWER_LOSS_DURABILITY = NOT_PROVEN` rather than being upgraded
by assertion. The frozen requirement — that a process crash never leaves a
half-written record a reader accepts — is met and tested separately.

**No task history.** Ending a task removes the active record. Retaining an
ended one would be the first row of a task history database, which is out of
scope; completion evidence belongs to receipts, which are artifacts in their
own right.

**HEAD movement is recorded, not enforced.** The starting HEAD is stored as
authority for later slices. Nothing in this one invalidates a task because HEAD
changed.

**One active task per worktree**, by design.
