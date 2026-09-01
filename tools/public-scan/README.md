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

## What it does not prove

This scan is a floor. It matches shapes it was told about. It cannot detect paraphrased
private material, a diagram label that reveals an internal system, or an asset traced
from a real screenshot.

**Human provenance review is mandatory before any push and is not replaced by this
script.** Read the full staged diff, confirm each new mechanism's provenance category
against [`../../docs/provenance.md`](../../docs/provenance.md), and confirm that no claim
outruns a retained artifact.
