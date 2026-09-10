# Support, packaging and release proof

What AIQE has been shown to do, on which machines, and what has not been shown.

This document describes the *method*. The current verdicts are in the retained
release-proof manifest, [`bench/results/release/release-proof.json`](../bench/results/release/release-proof.json),
because a verdict written in prose cannot fail a build and a verdict written in
a manifest can.

```
The package version is 0.1.0a0. The artifacts described here are
release-proof artifacts, not release assets.
```

Retained release-proof evidence records what was built and what was executed
against it. It does not, by itself, establish whether a Git tag, a GitHub
Release or a package-index entry exists: those are created outside the source
tree, after any commit that could describe them. Whether a Git tag, a GitHub
Release or a package-index entry exists is established from that object —
the tag, the release, the index — not from this repository.

## 1. How a support claim is decided

A support matrix is the easiest document in a project to write dishonestly,
because the dishonest version is also the tidier one:

- two runs at the ends of a version range look like a range;
- one green hosted runner looks like an operating system;
- a pure-Python wheel looks like every architecture at once.

None of those inferences are made here. Every job that is support evidence
writes a **surface record** — a JSON document naming the machine, the
interpreter, the Git version, the runner provenance, the evidence level, and
every test it skipped. [`bench/aggregate-release-proof.py`](../bench/aggregate-release-proof.py)
collects the records and applies the gate in
[`bench/release/support.py`](../bench/release/support.py).

Two evidence levels exist, and they mean exactly what they name:

```
FULL_SUITE               the whole unit suite ran on this surface
INSTALLED_ARTIFACT_E2E   a wheel and an sdist were built, installed into fresh
                         environments, and the complete workflow ran from the
                         installed console script, ending in REVIEWABLE
```

A Python minor version is `PROVEN` only with:

```
INSTALLED_ARTIFACT_E2E   on every claimed OS family
FULL_SUITE               on at least one claimed OS family
```

One without the other is `NOT_PROVEN`:

- the full suite alone proves the source tree runs there, and says nothing
  about the artifact a user installs;
- the installed end-to-end alone proves the artifact starts, and says nothing
  about the several hundred behavioural cases.

The asymmetry between the two is a **documented tiering**, not a
rounding-down. The artifact is what a user installs, and whether it installs
and runs is exactly what differs between operating systems, so that evidence
is required everywhere. The behavioural suite is several hundred cases about
Git and filesystem semantics, and running all of them on every interpreter on
every platform mostly re-answers the same question at ten times the price on
macOS.

What the tiering gives up, stated plainly: a defect that appears **only** on
one OS family, **only** on one interpreter minor, and **only** in a case the
end-to-end does not exercise would not be caught. In the current matrix that
means macOS on Python 3.12 and 3.13. The manifest records, per minor, which
families actually ran the full suite — `python_support.<minor>.families_by_level`
— so the basis of each claim is readable rather than implied by the word
`PROVEN`.

A failing observation is not evidence, and a **skipped** observation is not
evidence either. Skips are recorded by name in the surface record, so a
required portability case that quietly stopped running appears in the manifest
rather than in a scrollback buffer.

`NC-SUPPORT-CLAIM` is the negative control for this gate. It builds the
extrapolation an ordinary matrix invites — 3.11 passed, 3.14 passed, therefore
3.11–3.14 — and requires that the gate refuses it. If that control stops
reproducing, the gate has stopped gating.

### 1.1 Two evidence lanes, and what a green run means

[`.github/workflows/checks.yml`](../.github/workflows/checks.yml) runs in one
of two lanes, because a macOS runner bills at ten times a Linux one and
running the whole matrix on every push exhausted a month's CI allowance in
three days:

```
FAST   push, pull_request         Linux surfaces only
FULL   tag, manual dispatch       every claimed surface, macOS included
```

**A green FAST run is not a support claim, and does not pretend to be one.**
It produces no macOS surface record, so the gate above marks every claimed
Python minor `NOT_PROVEN` and names the observation it did not get —
`INSTALLED_ARTIFACT_E2E on macos`. That is the gate working. Only the FULL
lane is aggregated with `--require-all-claims`, so it remains impossible to
reach a manifest that passes the gate without the whole matrix having actually
run.

What this trades away is latency, not honesty: a macOS-only regression is now
found when a release is prepared rather than on the push that introduced it.
Nothing that is claimed is narrowed, and no run reports a surface it did not
touch. The manifest artifact is named for its lane
(`release-proof-manifest-full` / `-fast`) so a fast run's record cannot later
be mistaken for release evidence.

Run the full lane from the Actions tab (**Run workflow → lane: full**), or by
pushing a tag.

## 2. Architecture is never inferred

A pure-Python wheel is not an argument about a processor. `macos / arm64`
proven says nothing about `macos / x86_64`, and the manifest's surface table
does not merge them: it lists the surfaces that ran, in the words of the
machines that ran them.

## 3. The Git compatibility boundary

```
GIT_MINIMUM = 2.32
AIQE refuses to run below it.
```

This floor was not read off a changelog. It was found by running the suite on
a real old Git, and it is the one place where a frozen surface changed —
because what that surface reproduced was a silent safety defect.

**What happened.** Every AIQE command rests on one invariant: nothing the
repository defines is executed. That invariant is delivered by pointing
`GIT_CONFIG_SYSTEM` and `GIT_CONFIG_GLOBAL` at the null device before any
invocation that reads the index or the worktree. Both variables were
introduced in **Git 2.32**. An older Git does not know the names, so it does
not read them *and does not complain*: the isolation is applied, the command
succeeds, and `$HOME/.gitconfig` is in scope the whole time.
`GIT_CONFIG_NOSYSTEM` is not a fallback for this — it declines the *system*
file and has no opinion about the per-user one.

**How it was caught.** On Debian 11 (Git 2.30.2), the Doctor negative control
`NC_DOCTOR_GLOBAL_FILTER_EXECUTION` stopped reproducing: the fixture's
globally defined filter driver was never in scope at all. In the same run the
bounded-commit policy preflight returned `0` and created a commit where it must
return `3` and refuse, for a repository whose signing and filter policy was
defined through a global `include`. Fourteen cases failed, all from the one
cause.

A control that stops reproducing is this project's loudest signal, and here it
was pointing at a real hazard: on such a Git, a user gets a confident answer
that the isolation behind it never happened.

**What AIQE does now.** It fails closed. Before any command that reaches Git,
AIQE reads `git --version`; below 2.32, or when the version cannot be read at
all, it refuses with exit `3` and reason `GIT_TOO_OLD_FOR_CONFIG_ISOLATION` or
`GIT_VERSION_UNKNOWN`, naming the version it found and the floor it needs.
`aiqe --version` and `aiqe --help` still answer, because they reach no
repository.

Refusing on an *unreadable* version is deliberate: the alternative is assuming
the best about an unknown toolchain, which is the shape of the defect this
floor exists to close.

The `debian-11-old-git` job in
[`.github/workflows/checks.yml`](../.github/workflows/checks.yml) keeps the
finding alive. It does not run the suite — on that Git, AIQE refuses — it
proves the refusal, and it proves that the artifact still builds and installs
there, because declining to run is not the same as failing to install.

Below 2.32 nothing is claimed and nothing is attempted. Above it, AIQE
publishes the versions it was actually run against; the manifest's
`git_compatibility.exercised` list is that record. The frozen core leans on
the behaviours below, and inferring anything further from when each one was
introduced would be publishing a version nobody ran.

| Git behaviour AIQE relies on | Where | Why it matters |
|---|---|---|
| `--literal-pathspecs`, and `GIT_LITERAL_PATHSPECS` as its documented equivalent | every caller path in `gitq` and `gitwrite` | a filename containing a glob character must not silently widen the change |
| `--no-optional-locks` | every index- or worktree-reading query | a plain `git status` writes `.git/index`; this suppresses that write |
| `-c core.fsmonitor=false` | every isolated query | `core.fsmonitor` is executed as a child process during an index refresh |
| `GIT_CONFIG_SYSTEM` / `GIT_CONFIG_GLOBAL` pointing at the null device, and `GIT_CONFIG_NOSYSTEM` | configuration isolation | an externally defined filter driver must have no command in scope to run |
| `--ignore-submodules=dirty` | working-state counting | prevents descending into a submodule and running *its* filters |
| `rev-parse --git-dir` / `--git-common-dir` | worktree topology | a linked worktree's own state must not be confused with the shared one |
| NUL-terminated output (`-z`) from `status --porcelain=v2`, `ls-files`, `diff-index`, `diff-tree` | every parse | a repository path is a byte string, and a newline is a legal byte in one |
| `check-attr -z --stdin` | commit policy preflight | decides whether an attributes file binds an owned path to a filter driver |
| `hash-object --path` | expected check-in state | applies exactly the transformations Git would apply, and writes nothing |
| `commit --only <pathset>` | the bounded commit | commits exactly the owned pathset without disturbing foreign staged work |
| `update-index --add --intent-to-add`, and its scoped rollback | transactional ITA | a failure must undo what AIQE created, not restore a whole saved index |
| `diff-tree --raw -z --no-renames` | post-commit proof | reads the changed pathset back out of the object database |
| effective configuration resolution with `include` / `includeIf` | commit policy preflight | the policy that matters is the one the real commit would use |

Of these, only the configuration-isolation variables have been shown to have a
version boundary that matters, and that boundary is the floor above. The rest
are exercised on every surface the matrix runs, and no claim is made about how
far back any of them goes.

## 4. Windows

```
WINDOWS = OUT_OF_SCOPE_V1
```

No Windows implementation work is done, and no Windows support is claimed.
Package metadata carries **no** `Operating System ::` classifier at all — a
classifier is a support claim, and this project's claims are gated — and a test
asserts that the string `windows` does not appear in `pyproject.toml`.

## 5. Distribution: what is shipped, and what was declined

Three paths were compared. Only the ones currently relevant; Go and Rust are
not reopened.

**A. Wheel + sdist — required, and implemented.** The wheel is
`py3-none-any`, pure-lib, with the `aiqe` console script,
`Requires-Python >=3.11`, Apache-2.0 metadata, a bundled `LICENSE`, and
**zero** third-party runtime dependencies. Measured, not asserted: the release
proof installs it into a fresh environment and lists what else arrived.

**B. uv / uvx — required, and implemented.** Both `uv tool install <wheel>`
and `uvx --from <wheel> aiqe` are exercised against a local artifact, and both
then run `aiqe --version` and `aiqe doctor`. No registry publication is
involved. Obtaining uv itself uses the network; that is *tool installation*
network, and it is recorded separately from AIQE's runtime, which is
network-free.

**C. A standalone bundled executable — deferred.**

```
STANDALONE_BUNDLE = DEFERRED
```

The gate asks which measured installation problem a bundle would solve, and
after building and installing the real artifacts there is not one. `pip
install` from a wheel, `pip install` from an sdist, `uv tool install` and
`uvx --from` all succeed on every exercised surface, with no compiler, no
system library and no third-party dependency to resolve — a pure-Python
package with an empty dependency list is already the low-friction case a
bundle exists to create. Against that, a bundle would add a per-platform
build matrix, a per-platform artifact to sign and host, an interpreter
embedded in every release, and a second definition of "the artifact" for
every proof in this document to cover. Nobody has asked for it, and no
measured friction justifies it. It can be added later without changing
anything here; adding it now would be paying a maintenance cost to solve a
problem that has not been observed.

## 6. What may appear inside an artifact

A source tree that scans clean says nothing about what a build backend swept
into a distribution, so distribution members are checked against an
**allowlist** rather than a denylist. A wheel is small and completely
enumerable, which makes "is every member something we meant to ship" a
question that can actually be answered — and unlike a denylist, it catches the
file nobody thought of.

```
wheel   aiqe/<module>.py  and  aiqe-<version>.dist-info/{METADATA,RECORD,WHEEL,
        entry_points.txt,top_level.txt,licenses/LICENSE}

sdist   LICENSE MANIFEST.in PKG-INFO README.md pyproject.toml setup.cfg
        src/aiqe/<module>.py
        src/aiqe.egg-info/{PKG-INFO,SOURCES.txt,dependency_links.txt,
                           entry_points.txt,top_level.txt}
```

`src/aiqe.egg-info/` is setuptools' own build metadata, present in every
setuptools sdist. It is listed explicitly rather than tolerated by an
exception.

The sdist does **not** contain the test suite, and that is a decision rather
than an oversight. setuptools' default manifest collects `tests/test*.py` and
nothing else from that directory — not `tests/__init__.py`, not
`tests/support.py` — which produces a test package that cannot be imported: a
tree that looks like evidence and is not. Shipping the suite *completely* was
the alternative, and it was declined because these tests import the benchmark
fixture builders under `bench/`, read the retained result artifacts, and
assert against `README.md` and `docs/`, so a runnable suite means shipping
most of the repository inside every sdist. `MANIFEST.in` prunes the directory,
and the allowlist is what notices if that prune ever stops working.

Public sanitisation scanning runs against four targets, not one:

```
the source tree
the extracted sdist
the extracted wheel
the release-proof manifest
```

The scan is a pattern floor over text. It is **not** what catches a private
file that matches no pattern — the allowlist is, and the
`NC-PACKAGE-PRIVATE-FILE` control demonstrates the difference by planting a
synthetic private file that the scan passes and the allowlist rejects.

## 7. The offline runtime claim, stated narrowly

```
AIQE core requires no network.
Installing AIQE, uv, or anything else does.
```

Those are different claims and they are never merged. The release proof runs
the whole core command set — `--version`, `doctor`, `task`, `check` with a
real local validator, `commit`, `receipt` — with every socket entry point in
the standard library replaced by a recorder that appends to a file and raises.
The canary is **proved to fire** on a deliberate connection attempt before its
silence during the run is accepted as evidence; a canary that was accidentally
not installed is otherwise indistinguishable from a clean run.

Its limit: this is not a network namespace or a packet filter. It is
conclusive for Python code and says nothing about a non-Python child process.
Git is that child process, and the argument for Git is the frozen subcommand
allowlist, which contains no network subcommand.

Validator network behaviour remains the user's decision, taken knowingly. AIQE
makes no sandbox and no network claim about a validator, and says so before
asking for consent.

## 8. Build reproducibility, measured

Two builds of the same source, in two clean isolated surfaces, compared four
ways: with the environment as it comes, and with `SOURCE_DATE_EPOCH` fixed,
for both the wheel and the sdist. The numbers are in the manifest under
`reproducibility`, and the comparison is decomposed rather than reduced to one
boolean, because these are different facts:

```
content_identical              every packaged file is byte-identical
identical_bytes                the archives themselves are byte-identical
differing_metadata_fields      which archive metadata differs, if any
```

"Every packaged file is identical and the archive metadata is not" and "the
code differs" are the same red light on a checklist and completely different
findings. Only the second is about artifact integrity, and
`affects_artifact_integrity` in the manifest is the field that says which one
occurred.

The documented reproducible build procedure, when the manifest reports it
working, is:

```
export the tracked content of one commit into an empty directory
SOURCE_DATE_EPOCH=<fixed>  python -m build
```

No reproducible-build claim is made beyond what those hashes show.

## 9. Installing it

AIQE is a Python package with no third-party dependencies, needing Python 3.11
or newer. Every path below installs it from a local artifact or a clone and
needs no package index; whether an index also carries it is established from
that index, not from this document.

```bash
python3 -m venv .venv && .venv/bin/pip install .
```

```bash
.venv/bin/aiqe doctor
```

From a built wheel, or with uv:

```bash
python3 -m pip install ./dist/aiqe-0.1.0a0-py3-none-any.whl
```

```bash
uv tool install ./dist/aiqe-0.1.0a0-py3-none-any.whl
```

```bash
uvx --from ./dist/aiqe-0.1.0a0-py3-none-any.whl aiqe doctor
```

## 10. Reproducing the release proof

```bash
python3 bench/run-suite.py --output /tmp/surface-suite.json
```

```bash
python3 bench/run-release-proof.py --output /tmp/surface-artifact.json
```

```bash
python3 bench/aggregate-release-proof.py --surfaces /tmp/surfaces --output /tmp/release-proof.json
```

`--parts` selects a subset of the release proof, and the surface record always
states which parts ran and which did not, so a reduced run can never be read
as a full one.

## 11. The attestation this manifest does not carry

The retained manifest names the commit it was aggregated from, in its
`source_commit` field. That commit is not necessarily the current `HEAD`, and
the difference is evidence debt rather than a detail:

```bash
python3 -c "import json;print(json.load(open('bench/results/release/release-proof.json'))['source_commit'])"
git rev-parse HEAD
```

When those differ, the support claims in the README and in this document are
gated on runs against the earlier commit. They are not a claim that every
required CI job started and passed at the current `HEAD`.

```
OSS7_FINAL_HEAD_GITHUB_CI_ATTESTATION = NOT_CARRIED_IN_TRACKED_CONTENT
```

That field is scoped to what this repository tracks, and it does not move on
its own. A workflow run is an external object, created and read outside the
working tree, so no committed file can record whether one exists for the
commit you are reading. This document therefore states what the retained
evidence covers, and does not deny a run it cannot see.

Two structural things keep the tracked manifest behind `HEAD`.

The full matrix is dispatch-gated rather than automatic — see
[1.1](#11-two-evidence-lanes-and-what-a-green-run-means). An ordinary push
exercises the fast lane, which produces no macOS surface record and therefore
no support claim, by design. So the tracked manifest advances only when
somebody runs the full lane deliberately.

And a full-lane run that is never aggregated back into
[`bench/results/release/release-proof.json`](../bench/results/release/release-proof.json)
leaves the tracked manifest exactly where it was. A green run and an in-tree
support claim are two different objects; only the second is what a reader of
this repository is shown.

### 11.1 Reading an exact-head full-lane run

If you have been pointed at a run and want to know what it attests, the run
identifies itself. Four things have to hold, and a green tick is not a
substitute for checking them:

```
HEAD       the run's head SHA equals the commit you are reading, exactly
LANE       the run is the FULL matrix, not the fast lane — a fast run carries
           no macOS surface record and no support claim, whatever its colour
GATE       the manifest aggregation ran with --require-all-claims
OUTCOME    every required job started and every required job passed
```

The fast lane is never the full lane, however complete it looks.

### 11.2 The condition that moves the tracked manifest

```
EVENT      the full lane is dispatched at the then-current release-proof HEAD,
           with run capacity available
ACTION     one full-matrix run, aggregated with --require-all-claims
REQUIRED   every required job starts, every required job passes, and the
           release-proof manifest aggregation succeeds
```

That dispatch is an owner action. Nothing in a documentation task may trigger
it, retry it, or edit the workflow to make it cheaper to pass.

Nothing in this repository may show a CI badge, claim a green run at the
current `HEAD`, or present a support statement resting on anything weaker than
a retained manifest that names that commit.

### 11.3 Historical provenance

While this repository was private, hosted CI minutes were exhausted
account-wide and dispatches failed in seconds without starting a step. That
was a billing refusal rather than a regression, and it was never evidence
about the code. It is recorded here as the provenance of how the manifest fell
behind `HEAD`; it is not a statement about current capacity, and it is not the
reason any present claim is scoped the way it is. Reruns and workflow edits
intended only to manufacture a green result remain forbidden: they would
produce a badge rather than an attestation.
