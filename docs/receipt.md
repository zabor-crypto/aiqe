# `aiqe receipt`

What is proven, what is excluded, and what is unknown.

```
aiqe receipt [--local] [--format json]
```

Two surfaces, and the difference between them is the point.

```
aiqe receipt            the default, correlation-minimised, meant to be shared
aiqe receipt --local    the richer local view, meant to be read here
```

`receipt` executes no validator and writes no repository path.

## Pre-commit truth

Before a bounded AIQE commit exists:

```
Owned scope      DECLARED or CHECKED
Foreign staged   OBSERVED
Commit           NONE
```

The words `VERIFIED`, `EXCLUDED` and `CREATED` do not appear on this surface. They
are post-commit claims, and emitting one now would mean quietly redefining the
vocabulary later — a verdict vocabulary that shifts is not a verdict vocabulary.

### The states

**No active task.** A deterministic refusal, exit `3`. Not a fabricated receipt about
nothing.

**A task with no check.**

```
Owned scope   DECLARED     Evidence  NONE     Commit  NONE
Verdict       INCOMPLETE   reason    EVIDENCE_NONE          exit 2
```

**A required validator failed.**

```
Owned scope   CHECKED      Evidence  CURRENT  Commit  NONE
Verdict       NOT_REVIEWABLE                                exit 1
```

**A gap, an unknown, or stale evidence.**

```
Verdict       INCOMPLETE                                    exit 2
```

**Every pre-commit obligation green.** The check produced the internal completion
state `REVIEWABLE_CANDIDATE`, and the receipt still says:

```
Owned scope   CHECKED      Evidence  CURRENT  Commit  NONE
Verdict       INCOMPLETE   reason    BOUNDED_COMMIT_NOT_CREATED   exit 2
```

This distinction is load-bearing. `REVIEWABLE` is a claim about a commit whose content
is provably the checked content, and no commit has been created. **No pre-commit state
can reach `REVIEWABLE`**, and the test suite asserts that as a property over every
combination of classification, coverage, consent, staleness and validator outcome
this build can produce — not as a set of examples.

## Post-commit truth

`aiqe commit` creates a bounded completion commit and records its proof. That record,
and only that record, turns this surface into:

```
Owned scope       VERIFIED
Foreign staged    EXCLUDED
Checked content   BOUND
Commit            CREATED
Push              NOT_PERFORMED_BY_AIQE
Verdict           REVIEWABLE                                   exit 0
```

`EXCLUDED` requires both halves: the commit's changed pathset was proved equal to the
expected owned changed pathset, *and* the staged state AIQE does not own was the same
immediately before and immediately after. Either alone is not exclusion.

Nothing is re-proved when the receipt renders. The parent, pathset and content were
verified against a tree at the moment the commit was created, and re-deriving them now
would answer a different question — "is this true of some commit today" — which is the
generic historical verifier this product deliberately does not build.

### The post-commit states that are not `REVIEWABLE`

**Foreign staged state changed inside the mutation window.** The owned scope is
verified and the content is bound, and AIQE still will not say `EXCLUDED`:

```
Owned scope   VERIFIED   Checked content  BOUND
Foreign staged  UNKNOWN  Commit           CREATED
Verdict       INCOMPLETE                                       exit 2
```

AIQE does not claim it caused the drift, and does not claim it did not.

**A commit exists and violates its construction.** A parent that is not the pre-commit
HEAD, a changed pathset that is not the expected one, or committed content that is not
the checked content:

```
Verdict       NOT_REVIEWABLE                                   exit 1
```

The commit is not reset, reverted or amended away. Evidence truth outranks tidiness.

**The repository has moved past the completion commit.**

```
Evidence      STALE      Commit  CREATED
Verdict       INCOMPLETE  reason  COMPLETION_COMMIT_SUPERSEDED  exit 2
```

The proof is still true of that commit; it is no longer a statement about where this
worktree is, so the receipt stops making one.

Full reference: [`commit.md`](commit.md).

## Staleness

Freshness is recomputed, never re-run. Four things, and only these four:

```
the owned path binding          content, states and modes of the owned pathset
HEAD                            the commit the work sits on
aiqe.toml                       the file's raw bytes
validator definition digests    what the validators actually are
```

```
owned content, mode or state changes    STALE_OWNED_CONTENT
HEAD moves                              STALE_HEAD
aiqe.toml changes                       STALE_CONFIG
a validator definition changes          STALE_VALIDATOR_DEFINITION
```

Re-running the validators to answer "is this still true" would make the answer depend
on running them again, which is the question it was supposed to settle. And there is
no whole-worktree fingerprint: a foreign file changing is not a statement about this
task's owned scope, and hashing somebody's whole repository to find that out would
make a receipt cost more than the check did.

## The default receipt's privacy contract

The default receipt is the artifact a person pastes into a pull request, a chat, or a
screenshot. It is built from counts, states, reason identifiers and a verdict, and
from nothing else.

Excluded, and property-tested against the fixture's real values rather than against a
pattern:

```
absolute paths                  repository-relative filenames
the repository name             the remote URL
the branch                      any commit identifier
a persistent repository id      the machine-local state key
validator argument vectors      validator stdout or stderr
the username                    the hostname
agent private configuration     the task label
```

Not because any one of them is secret, but because together they are an inventory of
somebody's work, and an assurance artifact that quietly discloses one is not a good
trade for its user.

Error strings are part of that surface. A receipt refused because of a
`CONFIG_CONFLICT` names no path; it says to run `aiqe check`, which names it locally.

The document is bound to a redaction policy identifier, so a receipt cannot silently
start carrying more than the policy it names:

```
aiqe.receipt.default.v1
aiqe.receipt.local.v1
```

## `--local`

Adds task identity, the label you typed, timestamps, the local commit identifiers,
the owned pathset and its binding, each validator's identity, definition digest,
outcome and bounded output tail, and — once a completion commit exists — the parent
and created commit ids, both changed pathsets, the foreign staged digests before and
after, and the commit-policy preflight results.

A commit id belongs here and nowhere else. You are standing in the repository it
names, so withholding it would make the local receipt useless; putting it in the
shareable one would make that receipt an index into your project. The raw commit
message is absent from both, because nothing needs it and it is your text.

Still excluded: the process environment, unbounded output, file contents, and
anything scraped opportunistically from the repository. `--local` is a local terminal
surface, not a verbose sharing surface — there is no such surface in v1.

## Refusals

```
no active task                          exit 3
an owned path's identity is unresolved  exit 3
aiqe.toml cannot be interpreted         exit 3
CONFIG_CONFLICT                         exit 3, and no receipt artifact
```

A refusal produces no receipt in either format. Rendering a partial one would be a
receipt that says less than it appears to.

An **absent** `aiqe.toml` is not a refusal: a task without a configuration is an
ordinary state, reported as `INCOMPLETE` with `CONFIG_ABSENT`.

## Exit status

```
0   REVIEWABLE          only after a verified bounded commit
1   NOT_REVIEWABLE
2   INCOMPLETE
3   no receipt could be produced
```

## Schema

```
RECEIPT_SCHEMA_VERSION = 2
```

Version 1 promised that `commit` was always `NONE` and had no `checked_content` or
`push` field, so a reader of version 1 would misread a post-commit receipt as a
pre-commit one. That is exactly the condition this number exists to signal.
