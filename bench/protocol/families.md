# Benchmark families

Six case families, all P0 for launch. Families A, B, and C carry the zero-tolerance
gates; D, E, and F characterise the product rather than gate it.

## A — Change integrity

Does the bounded commit contain exactly the expected owned changed pathset, and nothing
else?

Covers: owned-scope immutability; literal-pathspec handling of filenames containing
metacharacters; foreign staged state observed before and after, with any drift —
including a newly appearing entry — reported as `UNKNOWN` rather than ignored;
transactional intent-to-add; and the absence of any pushed ref.

Materialised in [`../fixtures/commit/`](../fixtures/commit/): owned modification,
multiple owned paths, deletion, a new untracked path through intent-to-add, executable
mode and mode change, filenames that are pathspec syntax, a leading dash, whitespace
and control characters, a non-UTF-8 filename on Linux, a linked worktree, foreign
staged modification, addition, deletion and mode change, a foreign untracked path, an
empty expected changed pathset, a commit driven from a subdirectory of the worktree,
and the check-edit-commit stale refusal.

Also covers path identity on case-insensitive filesystems and under Unicode
normalisation, where two spellings of a path may or may not denote the same file.

## B — Completion and evidence truth

Does a `REVIEWABLE` verdict ever appear without the evidence that justifies it?

Covers checked-content binding end to end: the binding recorded at `check`, its
recomputation before mutation, refusal when it has gone stale, and post-commit
verification that committed content corresponds to checked content.

Covers the commit-policy refusals — active hooks, effective signing requirements, and
check-in filters on owned paths — including effective configuration resolved through
`include` and `includeIf` chains, and refusal when that configuration cannot be resolved
unambiguously.

The controlling question is negative: no unjustified `REVIEWABLE`, ever. Both halves
are now materialised — the pre-commit half in [`../fixtures/check/`](../fixtures/check/),
where `REVIEWABLE` is unreachable by construction, and the post-commit half in
[`../fixtures/commit/`](../fixtures/commit/), where it is reachable only behind the
parent, pathset, content and foreign-staged proofs.

Eight negative controls gate this family, and each must reproduce its failure:

```
NC-COMMIT-SHARED-INDEX      a plain commit absorbs unrelated staged work
NC-COMMIT-PATHSPEC          a declared path handed to Git as a pathspec broadens
NC-COMMIT-STALE             check, edit, commit: the edit is never validated
NC-COMMIT-ITA-ROLLBACK      a failed staging sequence leaves index residue
NC-COMMIT-HOOK-POLICY       committing runs the repository's commit hook
NC-COMMIT-SIGNING-POLICY    --no-gpg-sign makes the error go away, silently
NC-COMMIT-FILTER            checking in a bound path executes its clean filter
NC-COMMIT-FOREIGN-RACE      foreign staged state changes inside the window
```

## C — Numerical-integrity routing

Are the right contracts applied to the right surfaces, and is missing coverage reported
as missing?

One control per umbrella contract, each a defect that generic tests do not catch:

```
CAUSALITY               future information reaches a decision made before it existed
DATA_ALIGNMENT          series are joined on mismatched indices or timestamps
EXECUTION_REALISM       fills assume prices or liquidity that were not available
ACCOUNTING              positions, cash, and PnL fail to reconcile
TRAIN_TEST_SEPARATION   evaluation data informed fitting
DETERMINISM             identical inputs produce different results across runs
```

Each family also has a **missing-validator variant**: the contract applies, no required
validator is bound, and the correct answer is `COVERAGE_GAP`. A pass here is a false
green and a release blocker.

The pre-commit half of this family is materialised in
[`../fixtures/check/`](../fixtures/check/): three fixtures per contract — required
validator passes, required validator fails, and zero required validators bound —
eighteen in all, plus the classification and configuration cases. No family is
represented by another.

Also covers surface classification: overlapping quant and non-quant declarations must
produce `CONFIG_CONFLICT` and fail closed, and obligations from multiple matching
surfaces must union rather than override. Declaration order has no semantic effect, and
that is asserted over every permutation rather than over an example.

## D — Doctor first contact

Is the first command safe to run against an unfamiliar repository, and is it worth
running?

Safety assertions, all zero-tolerance: no repository mutation, no execution of
repository-defined code, no local state write, and no traversal of arbitrary
configuration include chains.

Value: does Doctor identify the conditions that would make later operations unsupported,
before the user invests any work?

## E — Product friction and time to value

How long does a first useful result take on a clean machine, and how many steps does it
take to get there? Measured, not estimated, on the documented install path.

## F — Context efficiency

**Deferred.** No public claim until the methodology is defensible under its own
description.
