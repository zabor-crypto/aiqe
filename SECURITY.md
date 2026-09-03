# Security Policy

AIQE is an assurance tool. Its security posture and the precise limits of its guarantees
are part of the product, not an appendix to it. This document states both.

## Supported versions

AIQE has not yet published an installable artifact. There is no supported version.

Once releases begin, the policy before `v1.0.0` is:

| Version | Supported |
|---|---|
| Latest minor | Yes |
| Anything older | No |

Pre-1.0 releases carry no backport commitment.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting on this repository (Security → Report a
vulnerability). It will be enabled before the repository becomes public.

Please include what you observed, the steps to reproduce it, the platform and Git
version, and what you believe the impact is. A proof-of-concept against a synthetic
fixture is more useful than one against a real repository — and please do not send
material from a private repository of your own.

This project is maintained by a small team. Response times are a good-faith target,
not a service-level agreement, and we would rather say that plainly than publish a
number we cannot honour.

## Threat model summary

AIQE runs locally, on a developer machine or a CI runner, against a Git repository the
operator already controls. It reads repository state and configuration, it runs
validator commands the repository itself declares, and it may create one bounded commit.

The operator is trusted. The repository's declared validators are trusted to the exact
extent the operator trusts their own repository — see the validator boundary below.
The adversary AIQE is designed against is not a malicious operator; it is *ambiguity*:
concurrent index activity, config that resolves differently than it appears to, stale
evidence, and checks that silently do not exist.

This is a summary. It is not a reproduction of the full internal threat model.

## AIQE core write boundary

Outside `aiqe init` — which writes exactly one repository path, `./aiqe.toml`, after
showing you the file and asking — AIQE core writes no repository path at all. `check`
and `receipt` write only AIQE's own machine-local state.

That claim is scoped, and the scope matters: it is about **AIQE core's own writes**. It
is not a claim that a validator cannot modify your worktree, that Git cannot mutate its
own internal state, or that another process cannot change files while AIQE runs. The
benchmark attributes every observed repository change to one cause — an authorised
`init` write, a validator, the fixture, or AIQE core — and only the last is
zero-tolerance.

## Doctor trust boundary

`aiqe doctor` is the first thing that touches an unfamiliar repository, so its boundary
is the strictest in the product.

- It performs **no repository mutation**.
- It executes **no repository-defined code**.
- It writes **no local state**.
- Its configuration inspection is a bounded, static, first-contact inspection. It does
  **not** follow arbitrary configuration include chains.

These are benchmark gates with zero tolerance, not aspirations.

## Validator execution boundary

Repository-native validators are ordinary child processes, launched after explicit local
consent.

`aiqe.toml` is tracked content, so anyone who can land a commit can declare a validator
naming any command on your machine. AIQE therefore treats a declaration as a proposal,
never as authorization. Consent is:

- **machine-local** — never written into `aiqe.toml`, tracked content, or `.git`;
- **bound to a definition digest** over the validator's id, argument vector, timeout,
  required flag and contracts, so changing any of them revokes it by identity mismatch;
- **never assumed** — a non-interactive or `--format json` check does not prompt and
  reports `UNKNOWN` / `CONSENT_REQUIRED` rather than running anything.

`--allow <id>` authorises one run and records nothing. The measured invariant is
`UNCONSENTED_VALIDATOR_EXECUTIONS = 0`, and it is a benchmark gate with zero tolerance.

Timeouts are mandatory, and a timeout is a `FAIL`. On timeout AIQE terminates **the
process group it created** for that validator, so a script's ordinary children go with
it.

That claim stops exactly there. AIQE does not bound every descendant and does not
supervise a process tree: a child that calls `setsid` is in a different session and
survives, and the benchmark keeps a fixture that demonstrates it rather than wording
around it. Delivering containment would mean building the sandbox this document says
AIQE is not.

### Repository-controlled text and your terminal

A validator's identifier, argument vector and output are written by anyone who can land
a commit, and all three are printed back to a person — the argument vector next to the
question AIQE wants a truthful answer to. Terminal control sequences are escaped, never
executed and never stripped: a prompt that removed part of the command it is asking
about would stop describing what is being consented to. The configuration grammar
refuses what it can first, so an identifier containing a newline never reaches a
renderer at all.

The definition digest is taken over the argument vector AIQE will execute, never over
the escaped text it displayed.

AIQE makes **no sandbox claim**, **no filesystem-restriction claim** and **no
network-restriction claim** about a validator. It runs as you, with your environment,
and can do anything your shell can do — including modifying files outside the owned
scope and reaching the network. The consent prompt states this before it asks.

Correspondingly:

> `PASS` means your validator succeeded. Nothing more.

AIQE records that the declared validator command was invoked under the recorded task and
configuration state, and records its process outcome. AIQE does not verify that the
validator consumed the sources you intended, that interpreter or build caches were fresh,
that its dependencies or external data were current, or that its logic is correct.

A stale bytecode or build cache can make a validator report success against source it
never read. That is a real failure mode, it is a documented limitation of validator
trust, and it is outside AIQE's guarantee.

What AIQE *does* detect is a validator that changes the thing it was checking. The
bounded authority — the owned path binding, HEAD, the raw `aiqe.toml` bytes and the
validator definition digests — is measured immediately before and after execution, and
if any of it moved, the result is not current evidence. A validator's writes elsewhere
in the worktree are outside that boundary and are attributed to the validator, not to
AIQE core.

## `aiqe commit` boundary

`aiqe commit` is implemented. It is optional: when used it creates one bounded
completion commit and nothing else, and it never pushes.

`AIQE_PUSH_CALLS = 0` is a property of the code rather than a promise in prose. The Git
allowlist `aiqe commit` runs through contains no network subcommand, the guard raises
rather than degrading, and the test suite asserts both. The receipt wording is
`Push = NOT_PERFORMED_BY_AIQE`: a statement about AIQE, and deliberately
not a claim that nobody else pushed concurrently.

AIQE **refuses rather than bypassing repository governance.** These conditions make the
operation unsupported rather than triggering a workaround:

```
ACTIVE_COMMIT_HOOK                              -> UNSUPPORTED   exit 3
EFFECTIVE_COMMIT_SIGNING_REQUIRED               -> UNSUPPORTED   exit 3
EXTERNAL_CLEAN_OR_PROCESS_FILTER_ON_OWNED_PATH  -> UNSUPPORTED   exit 3
EFFECTIVE_CONFIG_UNRESOLVED                     -> UNSUPPORTED   exit 3
UNSUPPORTED_TOPOLOGY                            -> UNSUPPORTED   exit 3
```

There is no `--no-verify` and no `--no-gpg-sign`. Every refusal is measured with the
thing being refused installed as a canary that records the fact that it ran, in a
directory outside the repository, and the retained fixtures assert the marker is
absent: `hook, filter and signer executions = 0`.

A driver that is configured and bound to no owned path is **not** a blocker. Refusing
there would make AIQE unusable on any machine that has ever installed Git LFS, and
would teach its users that its refusals are noise.

Commit preflight reasons about the **effective** Git configuration the actual commit
would use — hooks path, signing, and filter drivers — including applicable `include` and
`includeIf` chains. If the relevant effective configuration cannot be resolved without
ambiguity, the answer is `UNSUPPORTED`. Absence is never assumed.

Write confinement during a commit is stated rather than overstated. The expected Git
mutations are the index, the object database, HEAD, the ref and its reflog, and ordinary
commit metadata, plus AIQE's own machine-local evidence record. `.git` byte immutability
is **not** claimed. What is claimed, and measured from outside the process, is
`AIQE_CORE_WORKTREE_MUTATIONS = 0`, the exact bounded commit pathset, and preservation
of the foreign staged structured delta.

When commit is unsupported, `aiqe check` and `aiqe receipt` remain fully available and
you commit with ordinary Git. AIQE does not intercept or police ordinary Git.

An assurance layer that quietly disabled your signing policy to produce a nicer receipt
would be worse than useless.

## Unsupported: hostile local Git metadata

A repository whose own Git metadata is adversarial is **outside the v1 trust boundary**.
AIQE assumes the repository's metadata is merely complicated, not malicious. Hardening
against deliberately hostile local metadata is not a v1 guarantee, and we would rather
say so than imply a defence we have not built.

## Privacy and local evidence

- All evidence is local. Nothing is transmitted.
- The default receipt is correlation-minimised: counts, states, reason ids and a
  verdict, and no path, filename, repository name, remote, branch, commit id, validator
  command line, validator output, username, hostname or task label. The exclusion list
  is property-tested against real fixture values, and the serialiser is bound to a
  named redaction policy.
- Validator output is captured within a fixed budget, retained locally only for
  failures, and never reaches the default receipt. A passing validator's output is
  discarded.
- `--local` produces richer evidence. It is opt-in, allowlisted, and bounded.
- AIQE stores its local state outside the repository. Recorded validator consent lives
  there too, and outlives the task it was granted during.
- **Local state is owner-only regardless of your umask.** The state directories are
  0700 and every record in them — the salt, the task record, the check evidence, the
  consent record — is 0600, including the temporary file each is written through, so
  there is no window in which one is broader than its final form. This matters because
  local evidence can hold a failing validator's output, and AIQE is in no position to
  promise there is nothing sensitive in it. The modes are asserted under `umask(0)`.
- **State AIQE did not create is not trusted.** Every AIQE-managed component is
  validated before it is read or written — a real directory or regular file, not a
  symlink, owned by you, 0700 or 0600. Anything else is `LOCAL_STATE_UNSAFE`: exit 3,
  no validator executed, recorded consent not trusted. AIQE does not repair it: no
  `chmod`, no `chown`, no replacement, and it does not follow the symlink to see what is
  behind it. This validates AIQE's own components only; the directories above
  `$XDG_STATE_HOME` are the operating system's business.

## Network behaviour

None.

No telemetry, no update check, no daemon, no background watcher, no hook installation,
and no model calls. The deterministic product contains no network client.

## Non-goals

AIQE is not a sandbox, not a linter, not a CI system, not a secret scanner, and not a
substitute for review. It produces no aggregate safety score, it does not verify commits
it did not create, and it does not guarantee that your validators are the right ones.
