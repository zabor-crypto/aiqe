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

AIQE makes **no sandbox claim** and **no network-restriction claim** about them. A
validator can do anything your shell can do, including modifying files outside the owned
scope and reaching the network.

Correspondingly:

> `PASS` means your validator succeeded. Nothing more.

AIQE records that the declared validator command was invoked under the recorded task and
configuration state, and records its process outcome. AIQE does not verify that the
validator consumed the sources you intended, that interpreter or build caches were fresh,
that its dependencies or external data were current, or that its logic is correct.

A stale bytecode or build cache can make a validator report success against source it
never read. That is a real failure mode, it is a documented limitation of validator
trust, and it is outside AIQE's guarantee.

## `aiqe commit` boundary

`aiqe commit` is optional. When used, it creates a bounded completion commit and nothing
else. It never pushes.

AIQE will **refuse rather than bypass repository governance.** Specifically, these
conditions make the operation unsupported rather than triggering a workaround:

```
ACTIVE_COMMIT_HOOK                              -> UNSUPPORTED
EFFECTIVE_COMMIT_SIGNING_REQUIRED               -> UNSUPPORTED
EXTERNAL_CLEAN_OR_PROCESS_FILTER_ON_OWNED_PATH  -> UNSUPPORTED
```

Commit preflight reasons about the **effective** Git configuration the actual commit
would use — hooks path, signing, and filter drivers — including applicable `include` and
`includeIf` chains. If the relevant effective configuration cannot be resolved without
ambiguity, the answer is `UNSUPPORTED`. Absence is never assumed.

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
- The default receipt is correlation-minimised.
- `--local` produces richer evidence. It is opt-in, allowlisted, and bounded.
- AIQE stores its local state outside the repository.

## Network behaviour

None.

No telemetry, no update check, no daemon, no background watcher, no hook installation,
and no model calls. The deterministic product contains no network client.

## Non-goals

AIQE is not a sandbox, not a linter, not a CI system, not a secret scanner, and not a
substitute for review. It produces no aggregate safety score, it does not verify commits
it did not create, and it does not guarantee that your validators are the right ones.
