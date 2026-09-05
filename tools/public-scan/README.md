# Public sanitisation scan

Bootstrap tooling. This is **not** AIQE product code and it is not part of the
assurance layer — it exists to keep private material out of a repository that is
intended to become public.

## Running it

```
./tools/public-scan/public-scan.sh
```

```
exit 0   clean
exit 1   findings
exit 2   the scanner could not run
```

It runs in CI on every push and pull request, and must be run locally before any push.

## Testing the scanner itself

```
./tools/public-scan/self-test.sh
```

A gate that has never been shown to fail is not a gate. The self-test builds a temporary
tree, scans a corpus of synthetic positive controls, and asserts that **every** declared
pattern class fires **on its own control** — the corpus line carrying that class's name
as a leading label. A class added without a control fails the self-test, and so does a
class that was tightened until it no longer detects anything.

Attributing each control to its class is what makes the assertion worth making. "The
class produced a finding somewhere" is too weak: one control can satisfy two classes by
accident, and then deleting one class's control leaves the gate green. `GIT_SHA_40` was
exactly that — the `CRYPTO_WALLET_EVM` control is `0x` followed by forty hex characters,
which is also a bare object id — so its control could be removed without failing
anything. It cannot now.

It then scans a second tree of benign content and asserts a clean result. That half
records the strings that previously produced false positives, so that a later
"simplification" which reintroduces the noise is caught here rather than discovered by
someone switching the gate off.

The controls live in [`self-test-corpus.txt`](self-test-corpus.txt), which is excluded
from the scan for the same reason `patterns.txt` is: a corpus of the shapes the scanner
looks for necessarily contains them. Every value in it is a synthetic, non-functional
placeholder.

## What it covers

Every text file in the working tree — Markdown, JSON, YAML, shell, and SVG once SVG
assets exist. SVG matters more than it looks: generated assets embed live text, so a
receipt card or terminal cast produced on a real machine can carry a real absolute path
or username while the surrounding Markdown is spotless.

Pattern classes are in [`patterns.txt`](patterns.txt): absolute home paths, personal
email addresses, SSH remotes, internal hostnames, cloud bucket URIs, credential and key
shapes, wallet addresses, bare 40-character Git object identifiers, benchmark economics,
and internal project vocabulary.

## Two rules that are easy to get wrong

**The public pattern file may not contain private literals.** A denylist listing real
strategy names, project names, buckets, or hostnames publishes precisely the strings it
was built to suppress. `patterns.txt` therefore contains only generic *classes*.

Literal private terms belong in a local-only file:

```
tools/public-scan/private-literals.txt     one term per line, never committed
```

It is covered by `.gitignore`. CI runs the public classes; a local run applies both.

**No overbroad rules.** Banning every version string, every digit, or every hex sequence
produces noise, the noise gets ignored, the rule gets disabled, and a disabled gate is
not a gate. Patterns are narrow on purpose.

The corollary: a pattern may be **tightened** against a demonstrated false positive, and
must never be widened into an ignore. A tightening is only accepted with the false
positive recorded in `self-test.sh` and the class's positive control still firing. If a
legitimate file trips a pattern, the answer is a narrower pattern or a different file —
not a broader exception.

## Scanning an artifact, and the two recorded exceptions

```
./tools/public-scan/public-scan.sh                     the source tree
./tools/public-scan/public-scan.sh <directory>         an extracted sdist or wheel
./tools/public-scan/public-scan.sh <file>              the release-proof manifest
```

A source tree that scans clean says nothing about what a build backend swept into a
distribution, so the extracted artifacts are scanned as trees in their own right rather
than assumed to inherit the source result.

One class is deliberately not applied in two places, and they are the only exceptions in
the scanner:

```
GIT_SHA_40   not applied to a file whose content identifies it as the
             release-proof manifest
GIT_SHA_40   not applied to a line that is nothing but a pinned action
             reference: `- uses: owner/repo@<40 hex> # v1.2.3`
```

The manifest's job is to record which commit an artifact was built from, so it
necessarily contains a bare 40-character object id. The exception is recognised by
content rather than by path, because the manifest is scanned both inside the source tree
and as a single named file straight out of a CI job, and a path-shaped rule would stop
applying in the second case.

Blanket-excluding the file would blind the scan to the thing the class exists to
catch — an object id from *another* repository — so a stronger check replaces it there.
`tests/test_release_proof.py` asserts that every 40-character object id in the manifest
is an object that exists in this repository; a foreign id fails that test. Every skipped
match is reported as `JUSTIFIED` and counted in the summary, never silently dropped.

The second exception is the supply-chain control itself. Every `uses:` in the release
workflow is pinned to a full commit id rather than to a mutable major tag, because a tag
resolves to whatever it points at when the job runs — so the code producing release
evidence could change with no change in this repository. Those pins are bare
40-character object ids, and without an exception the scan would report the control as a
leak.

That exception is scoped to a *line shape*, not to a file, and the shape is anchored at
both ends: the whole line must be a `uses:` pin and nothing else. A bare object id
anywhere else in the same workflow is still a finding, which is what keeps the class
doing its job. The stronger check that replaces it is
`tests/test_workflow_pinning.py`, which asserts that every `uses:` in every workflow is
pinned to a 40-character object id, carries a readable version comment, and names a
first-party action owner from a short reviewed list — none of which `GIT_SHA_40` was
checking. `tools/public-scan/self-test.sh` carries a pinned reference among its benign
strings, so dropping the exception fails the self-test rather than passing quietly.

A third exception would need the same treatment: a named reason, and a check stronger
than the one being skipped.

## What it does not prove

This scan is a floor. It matches shapes it was told about. It cannot detect paraphrased
private material, a diagram label that reveals an internal system, or an asset traced
from a real screenshot.

**Human provenance review is mandatory before any push and is not replaced by this
script.** Read the full staged diff, confirm each new mechanism's provenance category
against [`../../docs/provenance.md`](../../docs/provenance.md), and confirm that no claim
outruns a retained artifact.
