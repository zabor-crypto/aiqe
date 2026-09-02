# Benchmark protocol

The benchmark exists to test the frozen architecture, not to discover one. It was
specified before the implementation for exactly that reason.

## Result vocabulary

Every case reports one of:

```
PASS          the expected outcome was observed
FAIL          the expected outcome was not observed
INCOMPLETE    the outcome could not be fully determined
UNSUPPORTED   the case cannot safely proceed in this configuration
NOT_RUN       the case was not executed
```

`NOT_RUN` is a first-class result. It is reported, rendered, and counted. It is never
collapsed into a blank cell, and a family containing `NOT_RUN` cases is never described
as passing.

Three states are kept strictly separate throughout:

```
OBSERVED_BASELINE   what was measured
EXPECTED_TARGET     what the design says should happen
NOT_RUN             what has not been measured
```

Conflating the second with the first is the failure mode this separation exists to
prevent.

## Lanes

**Deterministic lane.** Requires no language model. Every case is reproducible from a
fixed seed with no network access. This is the only lane that produces published
results in v1.

**Agent experiment lane.** Deferred. Measuring agent behaviour honestly requires
controls this project does not yet have.

**Context efficiency.** Deferred. No public claim will be made until the methodology is
defensible; a number that cannot survive its own methodology section is not evidence.

## Fixtures

Fixtures are synthetic, deterministic, and redistribution-safe. They contain no real
market data, no real strategy, and nothing derived from a private source.

Fixtures must additionally be **hermetic against stale interpreter and build caches**.
Timestamp-based bytecode invalidation can consider a cache current when source content
changed but its recorded metadata did not, which would let a validator report success
against source it never read — and would falsify the fixture's own expected result.
Fixture setup therefore isolates or clears such caches, or uses validators that
provably consume current source.

This is a property of the fixtures, not a guarantee AIQE makes. Validator freshness is
outside AIQE's boundary; see the validator-trust limitation in `SECURITY.md`.

## Negative controls

Every safety-relevant case has a negative control: a variant constructed so that the
failure the case guards against actually occurs.

```
control_reproduces_failure    P0
```

If the control does not reproduce the failure, the control is broken and the
corresponding positive result proves nothing. A green suite whose controls never fail is
a suite that is not measuring anything.

Required negative-control classes:

- shared-index absorption of unrelated staged work;
- validator execution from tracked configuration without local consent;
- a validator that edits the owned file it is checking and then exits 0;
- pathspec expansion via metacharacters in filenames;
- the check-then-edit-then-commit staleness window;
- missing-validator silent-green (coverage gap) for each contract family;
- commit-policy cases: active hooks, signing bypass, `include`/`includeIf` effective
  policy, and check-in filter transformation;
- validator freshness against a stale build or bytecode cache;
- path identity on case-insensitive and Unicode-normalising filesystems.

## Acceptance

Security-critical acceptance uses zero-tolerance gates. There is no weighted score and
no aggregate safety number, because an aggregate lets a real failure be averaged away.

```
CHANGE_INTEGRITY_SECURITY_FAILURES        = 0
UNJUSTIFIED_REVIEWABLE_VERDICTS           = 0
QUANT_COVERAGE_FALSE_GREENS               = 0
DOCTOR_REPOSITORY_MUTATIONS               = 0
DOCTOR_REPOSITORY_DEFINED_EXECUTIONS      = 0
DOCTOR_LOCAL_STATE_WRITES                 = 0
STALE_BINDING_COMMITS                     = 0
POLICY_BYPASSES_TO_OBTAIN_AIQE_COMMIT     = 0
MODEL_CALLS_IN_DETERMINISTIC_SUITE        = 0
REFS_PUSHED_BY_AIQE                       = 0
```

Any non-zero value blocks release. There is no threshold at which one of these becomes
acceptable.

## Reporting

Result artifacts are the authority. Visuals are generated from them; documentation quotes
them. Nothing is typed by hand into a README.

No case is omitted from a published result set. If a case was not run, the result says
`NOT_RUN` and says why.
