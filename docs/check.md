# `aiqe check`

Run what the repository declared, and say what remains unknown.

```
aiqe check [--allow <validator-id>]... [--format json]
```

`check` needs an active task ([`task.md`](task.md)) and a valid `./aiqe.toml`
([`config.md`](config.md)). It writes no repository path.

## What it does, in order

```
1  the active task, and the commit it started from
2  the current state of every owned path, against that baseline
3  the configuration, parsed fail-closed
4  classification of the changed owned paths
5  which validators apply, and which of them have consent
6  bounded authority, measured
7  the validators run
8  bounded authority, measured again
9  coverage arithmetic
10 one evidence record, replacing the last
```

Steps 6 and 8 are the ones that are easy to leave out, and they are the reason this
command can say `CURRENT` at all. See [validator-induced change](#validator-induced-change).

## Owned path states

`check` classifies **changed owned paths**, not the repository. Each declared owned
path resolves against the task's baseline commit to one of:

```
TRACKED_UNCHANGED   in the baseline commit, same bytes on disk      not a change
TRACKED_MODIFIED    in the baseline commit, different bytes         changed
TRACKED_DELETED     in the baseline commit, absent from the worktree changed
NEW                 not in the baseline commit, present as a file   changed
PENDING_ABSENT      absent from both — declared before it exists    not a change
```

A task that declared a path and never touched it carries no obligation for it.

**Nothing here asks Git whether a file changed.** Answering that question makes Git
read worktree content through any configured check-in filter, which is
repository-defined code — and running it would put the thing AIQE refuses to do
inside the operation whose job is to say what was checked. The baseline blob's stored
bytes are read with `cat-file`, the worktree file's bytes are read directly, and the
comparison is AIQE's own. Under a check-in filter or a line-ending conversion this is
conservative in the safe direction: a file Git would call unchanged can read as
changed here, which adds obligations rather than removing them.

A declared path that has become a directory, a symbolic link or a device node — or
that is a tree or a link in the baseline commit — is refused, not reinterpreted.
That is the fail-closed resolution the frozen task contract deferred to this
operation.

## A glob-shaped declaration that owns nothing

`--own` takes literal paths. A caller who typed `--own 'src/strategy/**'` has
declared one path with that name, it does not exist, and the files they meant are
owned by nobody — so the arithmetic below is perfect and the answer is empty:
nought changed owned paths, no classification, no contracts, exit `0`.

`check` refuses that result rather than reporting it. When a declared value is
glob-shaped (`*`, `?` or `[`), names no file in either the baseline commit or the
worktree, and — read as a [surface pattern](config.md) — selects a changed
repository path the task does not own, the outcome is:

```
OWNED_PATH_GLOB_AMBIGUITY -> INCOMPLETE, exit 2
```

and the previous evidence record is removed. That removal is load-bearing rather
than tidy: the owned binding does not move when an *unowned* file changes, so a
green record written before the change would still look current to `aiqe receipt`
and would answer for it. `aiqe receipt` applies the same rule for the same reason,
so the two surfaces cannot disagree — see [receipt.md](receipt.md).

The paths considered are the baseline commit's, the index's, and the untracked ones.
The index is not an optional third source: a file that has been created and
`git add`-ed is absent from the baseline tree and is no longer untracked, so leaving
it out would miss precisely the file a caller has just staged. Names only are read
from Git; whether a path changed is still AIQE's own byte comparison.

The diagnostic names the declaration, one changed path that escaped it, and how
many did. It does not expand anything — no matched path becomes owned, because
claiming files the caller did not declare is the failure this command exists to
refuse, not a convenience it can offer. The remedy is to declare each path.

All three conditions are required, so the ordinary cases are untouched: an
existing file called `notes[1].md` is a filename, and a metacharacter-bearing
path declared before it is created stays legal until something it would have
matched actually changes.

## A moved baseline

The task records the commit it started from, and that stays the causal baseline. If
HEAD has moved since, `check` reports `TASK_BASELINE_MOVED` and exits `2`.

It does **not** rebaseline. Moving the baseline underneath a task would redefine what
"changed" means retroactively, in whichever direction happened to be convenient.

## Classification

For every changed owned path, **every** matching `[[surface]]` declaration is
evaluated — never the first one that matches.

```
no surface matches
    UNCLASSIFIED -> CLASSIFICATION_GAP -> INCOMPLETE

only quant = true surfaces match
    QUANT_SURFACE, contracts = the union across every one of them

only quant = false surfaces match
    EXPLICIT_NON_QUANT_SURFACE

both match
    CONFIG_CONFLICT -> exit 3, and no new evidence
```

Declaration order has no semantic effect. First-match-wins would make the answer
depend on it, and a reader who moved a block to group it with its neighbours would
silently change which contracts apply to a strategy file.

The union is the direction that cannot be gamed: **adding a surface can never reduce
a quant obligation.** If it could, the way to make a check pass would be to write
another declaration.

`CONFIG_CONFLICT` is a refusal rather than a resolution. Any rule for picking a
winner — most specific, last declared, quant wins — would hide a real disagreement
behind a result. `quant wins` looks safe and is not: it would produce a green check
nobody could explain from the file they are reading. Human `check` output names the
conflicting repository-relative path and the declarations; the shareable receipt does
not, and is not produced at all.

## Which validators apply

```
no contracts declared     a generic task validator: applies to every checked task
contracts declared        applies only when at least one of them applies here
```

A generic validator was written about the project rather than about a surface.
Running a causality check against a documentation change is noise, and noise is how a
check becomes something people skip.

## Consent

Tracked configuration is executable trust material, not authorization.

Consent is **machine-local**, recorded **per validator definition digest**, and never
written into `aiqe.toml`, tracked content, or `.git`. It lives beside the worktree's
other machine-local state, and it survives `task end`: consenting to run the
project's test suite is a statement about a command, not about one unit of work.

A validator's semantic definition is exactly five fields:

```
id · argument vector · timeout · required · contracts
```

The digest is over a length-delimited binary serialisation of those, not over a
rendering — two different definitions must not be able to render to the same string.
Contracts are sorted first, because their order carries no meaning: reordering a list
must not revoke consent, and adding one must. Comments and whitespace in `aiqe.toml`
change the *configuration* digest, which staleness uses, and deliberately do not
change a validator's identity, which consent uses.

Change any semantic field and the digest changes, so the recorded consent addresses a
definition that no longer exists. That validator is `UNKNOWN` again. There is no
migration and no heuristic.

```
--allow <id>    authorises that exact definition for one run, and records nothing
                an unknown id is exit 3
```

Without consent:

```
interactive terminal    the id, the exact argument vector, the timeout and an
                        explicit no-sandbox, no-filesystem-restriction,
                        no-network-restriction disclosure are shown, and consent is
                        asked for. Accepting may record it per digest.

--format json, or a
non-interactive run     never prompts. Outcome UNKNOWN, reason CONSENT_REQUIRED.
```

Consent withheld is never a pass and never a failure. AIQE genuinely does not know
what that validator would have said.

## Execution

As an argument vector, with no shell, from the repository root, under the mandatory
timeout. Nothing in `aiqe.toml` is word-split, glob-expanded or substituted, and a
validator gets no standard input.

```
exit 0                  PASS
non-zero                FAIL
timeout                 FAIL
executable unavailable  UNAVAILABLE
consent withheld        UNKNOWN
contract not applicable NOT_APPLICABLE
```

**A timeout is a `FAIL`.** A check that hangs is a check that failed to establish what
it was asked to establish, and treating it as merely unknown is how an unbounded
validator becomes a permanent excuse.

### What the timeout actually terminates

> On timeout, AIQE terminates the validator process group it created.

That sentence is the whole claim, and it is deliberately narrower than the one that
would be nicer to make. A validator runs in its own process group, so a script's
ordinary children are terminated with it — which matters, because those children
inherit its pipes, and killing only the process AIQE started would let a bounded wait
run as long as whatever it spawned. Measured, not assumed: a `sh -c "sleep 30"` under
a one-second timeout took thirty seconds before the group existed.

AIQE does **not** bound every descendant, does not contain a process tree, and does not
supervise one. A child that calls `setsid` is in a different session and outlives the
kill. The conformance corpus keeps a fixture that demonstrates exactly that, so the stronger and
false claim cannot quietly return to this page. Delivering containment would mean
building the sandbox AIQE says it is not.

Draining after the kill is therefore bounded too: a detached descendant can hold the
inherited pipe open indefinitely, and the timeout is a promise about how long a check
can take.

### Output

Output is **drained into a fixed-size tail as it arrives** — never read whole and
truncated afterwards. A validator may be buggy or hostile and emit gigabytes, and the
memory AIQE spends on it must not be a function of how much it decided to print. What
is held is the budget plus one read buffer per stream, whatever the validator emits;
the corpus measures peak allocation across a thirty-two-fold change in output volume
to keep that honest.

The drain is also what stops the child deadlocking on a full pipe, so it runs for the
whole life of the process rather than only at the end — including for a validator that
is going to pass.

The retention policy is one documented rule: the **tail**, because a failure's last
lines are the ones that say why. Output is retained locally for `FAIL`, timeout and
`UNAVAILABLE`, and discarded for `PASS` — a passing validator's output is not evidence
of anything its exit status did not already say, and retaining it is how a local
evidence file acquires the contents of a log.

The bound is on captured bytes. Retained output is rendered terminal-safe before it is
stored, because it is attacker-controlled bytes, and escaping can turn one byte into
four characters — so the stored field is bounded by four times the budget plus a fixed
marker saying earlier output was not kept. None of it reaches the default shareable
receipt.

AIQE makes **no sandbox, no filesystem-restriction and no network-restriction claim**
about a validator. It runs as you and can do anything your shell can do. AIQE core
itself still makes no network request.

## Coverage

For every applicable contract:

```
zero required validators declaring it     COVERAGE_GAP     -> INCOMPLETE
all of them PASS                          COVERED
any of them FAIL                          CONTRACT_FAILED  -> NOT_REVIEWABLE
none FAIL, any UNKNOWN or UNAVAILABLE     CONTRACT_UNKNOWN -> INCOMPLETE
```

`COVERAGE_GAP` is the single most important state in the product. A repository whose
generic suite passes, whose changed files sit on a declared quant surface, and which
has no required validator bound to that surface's contracts is not passing. It is
unmeasured — and it looks exactly like passing to every other tool.

An optional validator never closes a gap, however green it is: a signal is not a
guarantee. Neither does a generic validator, however thorough: a suite that was not
written to detect a lookahead defect does not become evidence about lookahead by
succeeding.

## Checked-content binding

A completed check records a bounded binding for every owned declaration:

```
the exact raw path identity
regular file          content digest, and the mode bits that matter
tracked deletion      a deletion marker
new regular file      content digest and mode
pending absent        a pending marker
the task's baseline and the current HEAD
the raw aiqe.toml digest
every validator's semantic definition digest
```

Bounded by the owned pathset. There is no whole-tree fingerprint, and there will not
be one: the cost of a check must not scale with the size of somebody's repository.

This binding is the authority `aiqe commit` verifies against, and it is recomputed
immediately before that command's first index mutation. Nothing in `check` verifies a
commit; see [`commit.md`](commit.md).

One conservatism is deliberate and is closed at commit time rather than here. The
comparison above is over raw bytes, so under EOL normalisation a file Git would call
unchanged reads as changed — which adds obligations rather than removing them.
`aiqe commit` derives the *expected* checked-in blob instead, so a correct commit under
`core.autocrlf` is not reported as a mismatch.

## Validator-induced change

A validator is arbitrary code. The naive shape of this feature — run the tests,
record that they passed — cannot tell the difference between a validator that checked
the code and a validator that edited the code and then reported success. A formatter,
a code generator, or a test that writes a fixture back to disk all do the latter.

So the bounded authority above is measured immediately before validators run and
again immediately after. If the owned binding, HEAD, the configuration bytes or the
validator definitions moved, the result is not current evidence:

```
AUTHORITY_CHANGED_DURING_CHECK -> exit 2, and the previous record is removed
```

Removed rather than left in place: the record described a state that certainly no
longer holds. This is not a failure — nothing was proven false — it is `INCOMPLETE`,
which is the honest word.

Foreign worktree state is not fingerprinted. A validator's writes outside the owned
pathset, the configuration and HEAD are outside AIQE's guarantees, and are attributed
to the validator rather than to AIQE core.

## Evidence

One active record per task, replaced whole by each check. Not a history: the question
a receipt answers is whether something is true *now*, and a database of what was true
at various past moments invites the answer "it passed on Tuesday".

```
EVIDENCE_SCHEMA_VERSION = 1
```

It lives under the existing worktree-specific machine-local key, alongside the task
record. `task end` removes it — evidence about an abandoned unit of work is not
evidence about anything — while recorded consent survives. A record belonging to a
different task, or written under a different evidence schema, is not read and is not
migrated.

Each check replaces the record with a rename, so a reader mid-replacement sees the
previous record whole or the new one whole, never half of either. A refused check —
`CONFIG_CONFLICT`, an invalid configuration — writes nothing at all, and leaves the
previous record untouched rather than replacing it with something misleading. There is
no second file: four checks leave one record.

### File modes

The record can hold a failing validator's bounded output, and that output can contain
anything the validator printed. So its privacy does not depend on the umask of whoever
ran the command:

```
$XDG_STATE_HOME/aiqe/                 0700
$XDG_STATE_HOME/aiqe/salt             0600
$XDG_STATE_HOME/aiqe/<key>/           0700
$XDG_STATE_HOME/aiqe/<key>/task.json  0600
$XDG_STATE_HOME/aiqe/<key>/task.lock  0600
$XDG_STATE_HOME/aiqe/<key>/check.json 0600
$XDG_STATE_HOME/aiqe/<key>/consents.json  0600
```

The temporary files these are written through are created at the same mode, so there is
no window in which a record is broader than its final form. Both are asserted under
`umask(0)`, the most permissive setting there is — a file that is 0600 under that umask
is 0600 because AIQE asked for it.

### State AIQE did not create

Creating its own state privately is only half the job. State that is *already there* is
state somebody else may have put there, and AIQE cannot tell a file it wrote last week
from one that was placed for it to find. So every AIQE-managed component that is
actually used is validated first:

```
directories   a real directory, not a symlink, owned by this user,
              with no group or world permission bits
files         a regular file, not a symlink, owned by this user, mode 0600
```

Anything else is `LOCAL_STATE_UNSAFE`: exit `3`, no validator executed, and recorded
consent not trusted. Consent is the reason this matters most — a `consents.json`
somebody else can write is a list of commands somebody else can have executed as you,
and reading it on the assumption that AIQE wrote it would be the whole authorization
boundary undone by a file mode. The refusal stands even with `--allow`, because AIQE
will not go on to write its evidence into a state area it has just decided it cannot
trust.

**AIQE does not repair what it finds.** No `chmod`, no `chown`, no replacing the file,
and no following the symlink to see what is on the other side — every one of those is an
action taken on a path AIQE has already decided it cannot trust, and a tool that "fixes"
a hostile symlink by writing through it has done the attacker's work. You are told what
is wrong and left to decide.

This is deliberately not a general local-security framework. It validates AIQE's own
managed components and nothing else: the directories above `$XDG_STATE_HOME`, your home
directory and the rest of the machine are the operating system's business.

### Repository text and your terminal

A validator's identifier, its argument vector and its output are all written by whoever
can land a commit, and all three are printed back to a person. A terminal acts on some
bytes rather than displaying them, so the rule is: **escape, never strip, and never
execute.**

Two defences, in order. The configuration grammar refuses what it can — an identifier
containing a newline or an escape never reaches a renderer at all — and everything else
goes through the same escaping AIQE already uses for repository paths:

```
ESC, C0 and C1 controls, CR, LF, tab, DEL   ->  \xNN, \r, \n, \t
a literal backslash                         ->  \\
```

Escaping rather than stripping matters. A consent prompt that quietly removed part of
the command it is asking about would stop describing the thing being consented to, and
evidence with the awkward bytes deleted is not evidence. What you see is a reversible
rendering of exactly what is there — an argument vector carrying `ESC[2J` and a
plausible second prompt appears as `\x1b[2J`, on the line AIQE put it on.

**Rendering and authority stay separate.** The validator definition digest is taken over
the argument vector AIQE will actually execute, never over the escaped text it printed.
If it bound the rendering, two different commands could share one consent.

## Exit status

```
0   every required obligation discharged, coverage complete, evidence current
1   a required validator failed, including by timeout
2   incomplete: unknown, unavailable, stale, coverage gap, classification gap
3   refused: invalid configuration, CONFIG_CONFLICT, unknown --allow id,
    unsupported path identity, or no active task
```

A required failure outranks an incompleteness. Both are true at once often enough,
and reporting the softer of the two would be the wrong round-off in the one direction
that matters.

A fully green check produces the internal completion state:

```
REVIEWABLE_CANDIDATE
```

It is **not** a receipt verdict. Every pre-commit obligation is discharged, and the
thing that would make the work reviewable — a bounded commit whose content is
provably the checked content — has not been created. See [`receipt.md`](receipt.md).

## `--format json`

A local development document. It may name repository-relative paths and validator
identifiers, because you are looking at that repository. The correlation-minimised
surface is `aiqe receipt`, and the two are deliberately different documents rather
than one document with a flag.

A refusal — exit `3` — produces no document at all. An invalid configuration is not a
result.
