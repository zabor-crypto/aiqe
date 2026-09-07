# `aiqe.toml` and `aiqe init`

The repository's declaration of what it contains and what checks it.

```
aiqe init [--print] [--yes]
```

## The file

`./aiqe.toml`, at the worktree root. Two declaration types, and no others.

```toml
schema = 1

[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY", "DATA_ALIGNMENT"]

[[surface]]
paths = ["tests/**", "docs/**"]
quant = false

[[validator]]
id = "unit"
run = ["pytest", "-q", "tests/unit"]
required = true
timeout = 300

[[validator]]
id = "causality"
run = ["python", "checks/no_lookahead.py"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
```

**The file is executable trust material, not authorization.** A `[[validator]]`
block names a command AIQE would otherwise run as you, and anyone who can land a
commit can write one. Nothing in the configuration decides that a command may run;
see [`check.md`](check.md#consent).

## Parsing is fail-closed

Every other configuration reader in a developer's day is permissive: unknown keys
are ignored, missing values take defaults, a typo silently means something else.
That is a reasonable trade when the cost is a wrong colour scheme. Here the cost is
a quant surface that classifies as ordinary code, or a required validator that
quietly became optional — and either one produces a green result that means nothing.

So every refusal below exits `3`, and names the block and field it refused.

```
CONFIG_ABSENT                     no ./aiqe.toml at the repository root
CONFIG_NOT_A_REGULAR_FILE         it exists as a link, a directory, or worse
CONFIG_UNREADABLE                 it could not be read
CONFIG_MALFORMED                  not valid UTF-8, or not valid TOML
CONFIG_SCHEMA_MISSING             no `schema` key
CONFIG_SCHEMA_UNSUPPORTED         a schema this build does not interpret
CONFIG_UNKNOWN_FIELD              a key AIQE does not understand
CONFIG_BLOCK_MALFORMED            `surface` or `validator` is not [[table]] form
CONFIG_SURFACE_PATHS_INVALID      missing, empty, or not an array of strings
CONFIG_SURFACE_PATTERN_INVALID    a pattern the grammar refuses
CONFIG_SURFACE_QUANT_INVALID      `quant` missing or not a boolean
CONFIG_QUANT_WITHOUT_CONTRACTS    quant = true with no contract
CONFIG_NON_QUANT_WITH_CONTRACTS   quant = false carrying contracts
CONFIG_CONTRACT_INVALID           a contract identifier, or a duplicate
CONFIG_VALIDATOR_ID_INVALID       missing id, or one outside the id grammar
CONFIG_VALIDATOR_ID_DUPLICATE     two validators with one id
CONFIG_VALIDATOR_ARGV_INVALID     missing, empty, or not a vector of strings
CONFIG_VALIDATOR_REQUIRED_INVALID `required` missing or not a boolean
CONFIG_VALIDATOR_TIMEOUT_INVALID  missing, not a whole number, or out of range
```

Three of those deserve their reason stated rather than assumed.

**`quant` is never inferred.** A surface that does not declare it is refused, not
treated as `quant = false`. A path nobody classified is not the same as a path
somebody classified as ordinary code, and collapsing the two is the false green
this product exists to refuse.

**`required` is never defaulted.** Whether a validator is a completion obligation or
a signal is the most consequential thing about it.

**`timeout` is mandatory**, in seconds, between 1 and 86400. A validator runs as an
unsupervised child process; a check that can never report anything is not a check.

## Surface patterns

`paths` are AIQE patterns, matched on raw path bytes. They are not Git pathspec and
are never handed to Git — pathspec carries magic prefixes, `:(glob)`, `:(icase)`,
exclusions and attribute selectors, and their meaning depends on Git's version and
configuration. A rule that decides which contracts apply cannot rest on a syntax
whose meaning is negotiable.

```
literal bytes   match themselves
*               zero or more bytes, within one path component
?               exactly one byte, within one path component
**              an entire component: zero or more whole path components
[abc] [a-z]     a byte class, within one path component; a leading ! or ^ negates,
                and a ] immediately after the bracket is literal
```

There is no backslash escape, no character-class name and no collating element.

Matching is on bytes throughout: a repository path is a byte string, and decoding one
to classify it would give a repository with an unusual filename a different answer —
or an exception — from the component that decides which contracts apply to it. There
is no case folding and no Unicode normalisation, because either would make two
distinct files look like one.

`**` is a whole component, so `src/**` matches `src`, `src/a` and `src/a/b/c.py` but
not `srcx`. A pattern like `a**b` is refused rather than quietly treated as `a*b`:
an author who wrote it meant recursion, and silently giving them one component's
worth of matching is a classification gap nobody sees.

Also refused: an empty pattern, an absolute pattern, a trailing separator, an empty
or `.` or `..` component, a NUL byte, and an unterminated byte class.

## Contracts

Six umbrella families ship at launch:

```
CAUSALITY              future information reaches a decision made before it existed
DATA_ALIGNMENT         series joined on mismatched indices or timestamps
EXECUTION_REALISM      fills assume prices or liquidity that were not available
ACCOUNTING             positions, cash and PnL fail to reconcile
TRAIN_TEST_SEPARATION  evaluation data informed fitting
DETERMINISM            identical inputs produce different results across runs
```

They are umbrellas on purpose. A detailed sub-taxonomy would be a claim about how a
defect must be detected, and AIQE does not detect defects — it runs the repository's
own validators and reports what they said.

Custom contract identifiers are legal. An identifier is upper-case ASCII letters,
digits and underscores, beginning with a letter; the grammar is narrow so that a
lower-case or hyphenated spelling of a launch family is a configuration error rather
than a silently distinct contract that nothing covers.

## The configuration digest

Taken over the file's **raw bytes**, not over the parsed structure. A digest of the
parsed form would be stable across an edit that changed a comment explaining why a
validator is required, and staleness detection is more useful when it is
conservative: if the file a check ran against is not byte-identical to the file you
are reading, the evidence does not describe that file.

## `aiqe init`

```
aiqe init            render the proposed file, ask, then write
aiqe init --print    render it and write nothing at all
aiqe init --yes      render it and write without asking
```

`init` writes exactly one repository path: `./aiqe.toml`. Never `.gitignore`, never a
hook, never `.git/config`, never a shell profile, never an agent configuration file.
A tool that installs itself into the places a developer did not look is a tool whose
behaviour they cannot predict, and the first command a person runs is the worst
moment to demonstrate that.

`--print` has no side effects at all — no file, no machine-local state, no salt — so
that "what would this do" is answerable without doing it.

Without `--yes`, `init` needs an interactive terminal. On a non-interactive one it
exits `3` with `CONFIRMATION_REQUIRED` rather than assuming yes. Declining at the
prompt writes nothing and exits `0`: it is an answer, not an error.

**An existing `aiqe.toml` is never overwritten** — `CONFIG_ALREADY_PRESENT`, exit `3`,
even with `--yes`. It is somebody's declaration of what their repository contains, and
replacing it with a scaffold would silently discard classification rules. A symlink
at that path counts as something already there, not as a path to write through.

### The scaffold declares nothing

It is a commented template: `schema = 1`, and every `[[surface]]` and `[[validator]]`
example commented out.

That is not laziness. AIQE has no safe way to discover what in a repository is
quant-critical. It could match directory names against a list of conventions and be
right often enough to be dangerous — a `src/strategy/` declared `quant = true` with
plausible contracts would be a configuration nobody wrote and everybody trusts, and a
`quant = false` inferred from an absence of evidence is exactly the false green this
product exists to refuse.

Until a surface is declared, a changed owned path is `UNCLASSIFIED` and `aiqe check`
reports a classification gap rather than a pass. That is the honest state, and it is
visible rather than silent.

### What you would grow it into

[`examples/aiqe.toml`](../examples/aiqe.toml) is a worked illustration of the same
scaffold filled in: five surfaces across a research repository, all six launch
contracts declared, and a required validator bound to each.

It is an illustration and not a starting point, which is the useful part. Its validator
commands are placeholders: AIQE ships no validators, so implementing or replacing them is
the adopter's work, and what a copied configuration reports depends on which declared
surface changed and on which of those commands actually exist and succeed.

Change a path under one of its `quant = true` surfaces with the placeholders still
unwritten and the bound validators come back `UNAVAILABLE`, their contracts
`CONTRACT_UNKNOWN`, and the completion is refused. Change a path the example declares
non-quant — `scripts/**`, say — and no quant contract applies at all; if every applicable
declared check exists and passes, the result can legitimately be `REVIEWABLE`. That is the
verdict describing the checks that applied to the change that was made, which is what a
verdict is for.

So copying the file establishes nothing about whether your numerical work is adequately
checked. Contract evidence exists only for validators actually bound to an applicable
contract and actually executed. `tests/test_documentation.py` drives both paths end to
end against the real check path, so neither the guarantee nor its limit can quietly
change.

## Exit status

```
0   the proposal was rendered, and written if that was asked for
3   nothing was written: no repository, an existing configuration, an
    unconfirmable invocation, or contradictory flags
```
