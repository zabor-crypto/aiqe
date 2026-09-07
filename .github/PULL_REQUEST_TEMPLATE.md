## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Provenance attestation

- [ ] I have the right to submit this contribution.
- [ ] I have disclosed any non-original or third-party material, with its licence.
- [ ] This contribution follows AIQE's clean-room and public-data rules.

## Checks

- [ ] **Tests** — deterministic test added or updated, or N/A with a reason.
- [ ] **Conformance** — affected case IDs listed and results regenerated, or no
      covered behaviour changed.
- [ ] **Security boundary** — does this touch Doctor's boundaries, commit preflight,
      effective config resolution, or checked-content binding? If yes, name the
      conformance case that covers it and request maintainer review.
- [ ] **Quant-contract semantics** — does this change what a contract asserts?
- [ ] **Public-data safety** — no private paths, hostnames, usernames, credentials,
      real market data, or private identifiers, including inside generated assets.
      `./tools/public-scan/public-scan.sh` passes.

<!--
Security vulnerabilities: do not open a PR or a public issue.
Follow SECURITY.md instead.
-->
