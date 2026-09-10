# Contributing to AIQE

Thank you for considering a contribution. This document is short on ceremony and
specific about the few things that genuinely matter for this project.

## Before you start

The v1 workflow — `doctor`, `init`, `task`, `check`, `receipt` and `commit` — is
implemented and tested, and the conformance corpus materialises four families over it:
Doctor, task, check and commit. Useful contributions are to any of
those commands, to the conformance fixtures, to the specification, and to the
documentation.

The architecture and the conformance protocol are **frozen**. That is deliberate: the
product was specified before it was built so that the corpus tests the design rather
than discovering one. A change to frozen material needs a demonstrated contradiction,
not a preference.

## Development setup

AIQE is a Python package with no third-party runtime dependencies and no third-party
test dependencies. There is nothing to install in order to run the tests.

Python 3.11 is the support floor; 3.11 and 3.14 are the endpoints CI tests. Please do
not use syntax or standard-library features newer than 3.11.

```
python3 -m unittest discover -s tests -t . --verbose
```

To exercise the installed console script rather than the source tree:

```
python3 -m venv .venv && .venv/bin/pip install . && .venv/bin/aiqe doctor
```

The other checks CI runs:

```
python3 bench/run-doctor-fixtures.py
python3 bench/run-task-fixtures.py
python3 bench/run-check-fixtures.py
python3 bench/run-commit-fixtures.py
python3 bench/render-assets.py
./tools/public-scan/self-test.sh
./tools/public-scan/public-scan.sh
```

`render-assets.py` checks rather than writes: it fails if the captures or the README
conformance block have drifted from the retained result artifacts.

Two cases are restricted to Linux: the arbitrary-byte path fixtures need a filesystem
that accepts non-UTF-8 filenames, and APFS does not. They are reported as skipped
elsewhere, never dropped from the listing.

Please keep the dependency count at zero unless there is a measured reason not to. An
assurance layer that drags in a dependency tree is harder to audit than the thing it is
auditing.

## Test expectations

Every behavioural change needs a deterministic test. Not a probabilistic one, not one
that depends on wall-clock time, network access, or the contents of the machine it runs
on. If a behaviour cannot be tested deterministically, say so in the pull request and
explain why.

## Conformance expectations

If a change affects behaviour the conformance corpus covers:

- name the affected case IDs in the pull request;
- regenerate the result artifacts;
- do not hand-edit a result file, ever.

Results are retained, including failures, unsupported cases, and cases that were not
run. A change that makes a case disappear from the results is a change that needs
explaining, not a change that needs merging.

## Clean-room contribution rule

This repository is a clean-room implementation and publishes a provenance manifest
(see [`docs/provenance.md`](docs/provenance.md)). That manifest is only worth something
if every contribution honours it.

Contribute only material you have the right to submit. Do not paste code from
proprietary, unlicensed, or unclear-licence sources. If any part of your contribution is
derived from an external source, disclose it in the pull request along with its licence.

There is **no CLA and no DCO**. Apache-2.0 makes inbound licensing the same as outbound.
In exchange, the attestation in the pull request template is taken seriously.

## New quant-contract proposals

The six umbrella contracts are frozen for v1. A proposal for a seventh needs, in order:

1. a failing negative control that the existing six do not catch;
2. evidence that the failure is real in practice, not merely constructible;
3. a proposed validator obligation that can be checked deterministically.

A contract without a negative control is an opinion.

## Adapter changes

Agent adapters sit behind a narrow common interface. An adapter may not widen the core
command surface, add a flag to the core, or introduce a code path that only exists for
one agent. If an adapter appears to need that, the interface is wrong and that is the
conversation to have.

## Security-sensitive changes

Anything touching Doctor's boundaries, commit preflight, effective configuration
resolution, or checked-content binding requires explicit maintainer review and must name
the conformance case that covers it. Flag it in the pull request checklist.

For vulnerabilities, follow [`SECURITY.md`](SECURITY.md) — not a public issue.

## Public-data safety

This repository must contain no private paths, hostnames, usernames, credentials, real
market data, or private identifiers. That includes text inside generated assets. Run the
public scanner before opening a pull request. The scanner catches shapes it was told
about; it is a floor, not a proof.

## Release process

Releases follow the milestones in the README. Every user-visible change adds a
`CHANGELOG.md` entry in its own pull request, not at release time. Changes to a public
claim, a documented limitation, or an exit code are always user-visible, however small
the diff.
