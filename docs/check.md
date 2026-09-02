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
validator becomes a permanent excuse. The timeout ends the validator's whole process
group, not only the process AIQE started: a script's children inherit its pipes, and
killing just the top would let a bounded wait run as long as whatever it spawned.

Output is captured within one fixed budget per stream, retained locally only for
`FAIL`, timeout and `UNAVAILABLE`, and discarded for `PASS` — a passing validator's
output is not evidence of anything its exit status did not already say, and retaining
it is how a local evidence file acquires the contents of a log. Retained output is
rendered terminal-safe, because it is attacker-controlled bytes. None of it reaches
the default shareable receipt.

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

This binding is the authority a future `aiqe commit` will verify against. That
command does not exist, and nothing here verifies a commit.

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
