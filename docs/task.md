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

The filesystem is consulted for one purpose only — refusing a path that exists
today as something a v1 task cannot own:

```
absent                accepted   a path declared before it exists
regular file          accepted   tracked or untracked makes no difference
directory             refused    OWNED_PATH_IS_DIRECTORY
symlink               refused    OWNED_PATH_IS_SYMLINK
anything else         refused    OWNED_PATH_NOT_REGULAR
```

`lstat`, not `stat`, and no target is followed. A symlink is refused *as a
symlink* rather than judged by what it points at, because v1's owned-path,
checked-content and commit semantics are defined over regular files, their
creation and their deletion. Supporting links is not required for launch, and
pretending to would put the hole in the content binding rather than in the
path rules.

If a declared path that did not exist later materialises as something other
than a regular file, a future operation that must resolve path identity fails
closed rather than reinterpreting the declaration. The record says a path was
declared, never what kind of object it would become.

**A duplicate declaration is refused**, not merged:

```
aiqe task start --own src/a.py --own ./src/a.py
  -> DUPLICATE_OWNED_PATH, exit 3
```

Two spellings of one path in one declaration means the user believes they
declared two things. Silently agreeing with half of that belief is how a scope
ends up meaning something its author did not intend.

**Paths keep their bytes.** A repository path is a byte string. Declared paths
round-trip exactly, including bytes that are not valid UTF-8 — proven end to
end on Linux, where such a filename can exist. Display is escaped; the stored
value is not.

### Resolution and canonicalisation

A relative path means what it looks like from where it was typed. From
`tests/`, `--own ../src/a.py` declares `src/a.py`.

Canonicalisation is limited to what is safe without touching the filesystem:
`.` components and repeated or trailing separators collapse. There is deliberately **no** Unicode
normalisation and **no** case folding — both would make two different
filenames look like one — and **no** symlink resolution, because the owned
identity is the repository path.

Two *distinct* paths never collapse, even when one is a lexical parent of the
other. Declaring both `docs` and `docs/guide.md` records two paths: under
exact ownership neither implies the other, so neither can absorb it. Two
spellings of the *same* path are a duplicate, and refused.

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
OWNED_PATH_IS_DIRECTORY            exists today as a directory
OWNED_PATH_IS_SYMLINK              exists today as a symbolic link
OWNED_PATH_NOT_REGULAR             exists today as some other kind of object
DUPLICATE_OWNED_PATH               declared more than once
```

`--own .` is refused. AIQE's purpose is an explicit bounded pathset, and
owning everything is not one.

`src/../etc` is refused rather than silently treated as `etc`: the two are
only the same if `src` is not a symlink, and AIQE does not resolve symlinks to
decide what a path means. Leading `..` is fine — it walks back through the
invocation directory, which the operating system has already resolved.

Every refusal exits 3 and writes nothing at all: no task, no state directory,
and no machine-local salt.

## A task needs a commit to start from

```
aiqe task start        in a repository with no commits
  -> exit 3
```

A task records the commit it started from, and without a parent there is
nothing for later evidence to be relative to. `aiqe doctor` still works there,
and `aiqe task` still answers; the rule is about starting one.

## Foreign staged entries at start

The record carries `foreign_staged_count_at_start`: how many entries were
staged when the task began.

It is informational and local. It is **not** the foreign-staged guarantee —
the load-bearing before-and-after comparison that decides whether a bounded
commit excluded work the task never mentioned belongs to `aiqe commit`, and
recording a number here does not make that comparison.

The count comes from `diff-index --cached`, which compares the index against
HEAD and reads no worktree content, so it cannot refresh the index and cannot
trigger a filter driver. Filenames are counted, never stored and never
printed.

## Where task state lives

Machine-local, and deliberately nowhere near the repository:

```
$XDG_STATE_HOME/aiqe/salt              32 random bytes, mode 0600
$XDG_STATE_HOME/aiqe/<key>/task.json   the active task, if any
$XDG_STATE_HOME/aiqe/<key>/task.lock   the start/end mutex
```

When `XDG_STATE_HOME` is unset the conventional Unix fallback applies:
`~/.local/state`.

Nothing goes inside `.git` — not the worktree Git directory, not the common
one, not the index, not the configuration. A tool whose claim is that it does
not touch your repository should not keep its own filing cabinet inside it,
and state written there is state a fresh clone or a `git clean` silently
disagrees with.

### The lookup key names no repository

```
key = HMAC-SHA256(salt, canonical common-dir || 0x00 || canonical git-dir)
```

rendered as hex. The paths are inputs only; they are never stored. Without the
machine-local salt the key reveals nothing about which repository it belongs
to, which is what keeps a state directory listing — and any future receipt —
from being an inventory of someone's projects.

Including the per-worktree Git directory as well as the common one is what
gives two linked worktrees two distinct keys, and therefore two independent
tasks. NUL separates them because a POSIX path cannot contain one, so no two
different pairs of paths share an input.

### The salt is created on the first write, never on a read

`aiqe doctor` creates nothing. `aiqe task`, on a machine with no salt and no
state, answers that there is no active task and leaves the filesystem exactly
as it found it. A *refused* `task start` also writes nothing: validation
happens before the first write, on purpose.

Creation is a link into place, which is atomic and fails rather than
overwrites. Two processes racing to be the first-ever writer both end up using
whichever salt won, never two. A crash mid-write leaves a temporary file that
was never linked, not a short salt that would silently change every derived
key.

### If the location is unsafe

If a path in the state directory already exists as something other than the
expected kind — a symlink, a directory where a file belongs — AIQE refuses
rather than following it. Writing through a symlink planted there would put
AIQE's own writes somewhere it never promised to write.

## Local internal state schema

```
LOCAL INTERNAL STATE SCHEMA
version 3 · not user-edited · not a public integration surface before 1.0
```

Do not build on this shape yet. It is documented so the state is auditable,
not so it can be integrated against.

```
schema_version                 3
ownership_semantics            "exact_literal_pathset_v1"
task_id                        opaque random local identifier
aiqe_version
started_at                     UTC, to the second
start_head_sha                 the commit the task started from
owned_paths                    [ { "path_b64": base64(raw repo-relative bytes) } ]
owned_pathset_digest           "sha256:<hex>"
foreign_staged_count_at_start  informational; see above
label                          the text given to --label, or null
```

`ownership_semantics` is recorded in every task so a reader never has to infer
from a version number what a declared path meant.

Paths are base64-encoded because the record is JSON and JSON is text. A path is
bytes, and round-tripping it through a text encoding is exactly the lossy step
this product cannot afford.

Deliberately absent: the worktree path, the Git directory, the remote URL, the
repository owner or name, the branch, the hostname, the username and the email
address. None is needed to say which paths a task owns, and every one turns a
local state file into something that identifies a person or a project if it is
ever shared. The canonical Git paths are inputs to the machine-local lookup key
and are stored nowhere.

`task_id` is random and nothing but random. It encodes no username, hostname,
repository, branch or readable timestamp.

### An older schema is refused, not migrated

Earlier versions recorded ownership under different semantics, and kept state
in a different place. Reading such a record today would say something untrue
about a live task, so this build refuses it:

```
aiqe task            -> exit 2, naming the schema mismatch
aiqe task start      -> exit 2, the record is left untouched
aiqe task end        -> discards it; a new task can then be started
```

There is no migration and no migration framework. This is local pre-release
state, and a sentence telling the user to end the task and start it again is a
better answer than machinery that guesses what an older record would have
meant.

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

Two distinct paths never merge, so `docs` and `docs/guide.md` digest
differently from `docs` alone.

`start_head_sha` is the state the task began from. A task is **not**
invalidated in this slice because HEAD later changed — evidence freshness
belongs to `check`, and enforcing it here would be inventing a completion rule
ahead of the evidence.

## Atomicity and concurrency

Every state transition is a write to a temporary file in the same directory,
an `fsync`, and an atomic rename. A reader sees the old state or the new one,
never half of either. A process killed between the two leaves a temporary file
that is not a task: status says there is none, and the next start succeeds.

`start` and `end` take an exclusive `flock` on that worktree's machine-local
lock file. Two concurrent starts in one worktree produce one winner and one
deterministic refusal. The kernel releases the lock if a process dies, so a crash cannot
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
a record from a superseded schema      2
no commits yet, so no task can start   3
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

AIQE's own writes stay inside its machine-local state home,
`$XDG_STATE_HOME/aiqe/`. Starting, showing or ending a task changes **nothing
inside the repository at all** — not a tracked file, not an untracked one, not
the index, not a ref, not a hook, not the configuration, and nothing under
`.git`. A repository with staged work it never told AIQE about keeps it: the
index is byte-identical across start, status and end.

The claim is scoped deliberately. It is about AIQE's own writes, not a promise
that nothing else on the machine can change the repository while AIQE runs.

Nothing a repository defines is executed to establish ownership — no hook, no
filter, no fsmonitor, no alias, no validator. Task operations use the same
hardened Git invocation Doctor uses, and only for discovery and an
index-versus-HEAD comparison: no worktree content is read, so nothing can
trigger a filter driver.

## Known limitations

**Ambiguity is not resolved here.** Whether two declared paths could refer to
the same file on a case-insensitive or normalising filesystem is not decided at
task start, because it depends on state that does not exist yet. It becomes a
question when a later operation must resolve path identity against actual
changes, and it fails closed there. The same applies to a declared path that
did not exist and later materialises as something other than a regular file.

**No directory ownership, and no links.** v1 owns an exact pathset of regular
files. Declaring a directory, a symlink or a special file is refused, and
declaring a path does not own anything under it. Directory ergonomics and link
support may be reconsidered on measured demand; they are not in v1.

**State is keyed to a location.** The machine-local key is derived from the
canonical Git directories, so moving a repository makes its task state
unreachable — a new one can simply be started. There is no registry mapping
keys back to repositories, by design: such a registry would be the inventory
the key exists to avoid.

**Task end is not proven durable against power loss.** `clear_active` unlinks
the record and then fsyncs the containing directory, which is the mechanism
that would make the deletion survive, and a test asserts that fsync happens.
Demonstrating power-loss durability needs power loss, so the classification
stays `TASK_END_POWER_LOSS_DURABILITY = NOT_PROVEN` rather than being upgraded
by assertion. The frozen requirement — that a process crash never leaves a
half-written record a reader accepts — is met and tested separately.

**The staged count is informational.** `foreign_staged_count_at_start` is not
the foreign-staged guarantee; that comparison belongs to `aiqe commit`.

**No task history.** Ending a task removes the active record. Retaining an
ended one would be the first row of a task history database, which is out of
scope; completion evidence belongs to receipts, which are artifacts in their
own right.

**One active task per worktree**, by design.
