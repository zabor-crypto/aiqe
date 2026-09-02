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
the owned pathset and its binding, and each validator's identity, definition digest,
outcome and bounded output tail.

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
0   REVIEWABLE          unreachable in this build
1   NOT_REVIEWABLE
2   INCOMPLETE
3   no receipt could be produced
```
