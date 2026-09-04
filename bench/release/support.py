"""Turning observations into support claims, and refusing to turn anything else into one.

A support matrix is the easiest document in a project to write dishonestly,
because the dishonest version is also the tidy one. Two runs at the ends of a
range look like a range. One green hosted runner looks like an operating
system. A pure-Python wheel looks like every architecture at once.

None of those are inferences this module will make. It takes a list of
surfaces that were actually executed, and a list of surfaces somebody wants to
claim, and it marks each claim `PROVEN` or `NOT_PROVEN` with the observations
that decided it. There is no third state and no override.

`naive_python_range` is the unsafe reference the negative control needs. It is
the extrapolation an ordinary matrix makes without noticing, written out
explicitly so it can be shown to be wrong.
"""

PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"

from .environment import FULL_SUITE, INSTALLED_ARTIFACT_E2E


#: What a Python minor version must have behind it before AIQE claims support
#: for it.
#:
#: Two requirements, and they are deliberately not the same shape:
#:
#:     INSTALLED_ARTIFACT_E2E   on *every* claimed OS family
#:     FULL_SUITE               on *at least one* claimed OS family
#:
#: The asymmetry is a documented tiering, not a rounding-down. The artifact is
#: what a user installs, and whether it installs and runs is exactly the thing
#: that differs between operating systems, so that evidence is required
#: everywhere. The behavioural suite is several hundred cases about Git and
#: filesystem semantics; running all of them on every interpreter on every
#: platform costs a great deal and mostly re-answers the same question.
#:
#: What the tiering gives up is stated rather than glossed: a defect that
#: appears only on one OS family *and* only on one interpreter minor, and only
#: in a case the end-to-end does not exercise, would not be caught. The
#: manifest records, per minor, which families actually ran the full suite, so
#: a reader can see the basis of each claim instead of taking the word
#: `PROVEN` at face value.
REQUIRED_EVERYWHERE = (INSTALLED_ARTIFACT_E2E,)
REQUIRED_SOMEWHERE = (FULL_SUITE,)

#: Retained for readers of older records: the levels that participate at all.
REQUIRED_PYTHON_LEVELS = (FULL_SUITE, INSTALLED_ARTIFACT_E2E)


def _matching(observations, **criteria):
    matched = []
    for observation in observations:
        if all(observation.get(key) == value for key, value in criteria.items()):
            matched.append(observation)
    return matched


def _identify(observation):
    """A short, stable description of one observation, for a claim's evidence."""
    return "%s %s / %s / python %s / %s / %s" % (
        observation.get("os_family"),
        observation.get("os_release"),
        observation.get("arch"),
        observation.get("python_version"),
        observation.get("level"),
        observation.get("runner_provenance"),
    )


def python_support(observations, minors, os_families):
    """Which claimed Python minors are proven, on every claimed OS family.

    `observations` are records that carry an environment identity, a `level`,
    and an `outcome`. Only observations whose outcome is `PASS` count: a job
    that ran and failed is evidence of a failure, and a job that was skipped is
    evidence of nothing at all.
    """
    passing = [o for o in observations if o.get("outcome") == "PASS"]
    claims = {}
    for minor in minors:
        missing = []
        evidence = []
        families_by_level = {}

        for level in REQUIRED_EVERYWHERE:
            for family in os_families:
                found = _matching(
                    passing, python_minor=minor, os_family=family, level=level
                )
                if found:
                    evidence.extend(_identify(o) for o in found)
                    families_by_level.setdefault(level, set()).add(family)
                else:
                    missing.append("%s on %s" % (level, family))

        for level in REQUIRED_SOMEWHERE:
            found = [
                o
                for o in passing
                if o.get("python_minor") == minor
                and o.get("level") == level
                and o.get("os_family") in os_families
            ]
            if found:
                evidence.extend(_identify(o) for o in found)
                families_by_level.setdefault(level, set()).update(
                    o.get("os_family") for o in found
                )
            else:
                missing.append(
                    "%s on any of %s" % (level, ", ".join(sorted(os_families)))
                )

        claims[minor] = {
            "verdict": PROVEN if not missing else NOT_PROVEN,
            "missing": missing,
            "evidence": sorted(set(evidence)),
            "families_by_level": {
                level: sorted(families)
                for level, families in sorted(families_by_level.items())
            },
        }
    return claims


def naive_python_range(observations, minors):
    """The extrapolation this project refuses to make, written out.

    An ordinary CI matrix tests the endpoints of a supported range because
    testing every minor costs money, and then the README states the range. The
    interior versions were never executed. This function reproduces that
    reasoning exactly - if the lowest and highest claimed minors have any
    passing observation, everything between them is called supported - so that
    a control can demonstrate the difference between it and `python_support`.

    It is the unsafe reference. Nothing in the release proof consumes its
    output as a claim.
    """
    passing = {
        o.get("python_minor") for o in observations if o.get("outcome") == "PASS"
    }
    ordered = sorted(minors, key=lambda minor: tuple(int(p) for p in minor.split(".")))
    if not ordered:
        return {}
    lowest, highest = ordered[0], ordered[-1]
    endpoints_pass = lowest in passing and highest in passing
    return {
        minor: {"verdict": PROVEN if endpoints_pass else NOT_PROVEN}
        for minor in ordered
    }


def os_arch_support(observations):
    """Every OS/architecture surface that was actually executed, and at what level.

    Nothing is aggregated up to an OS family here. `macos / arm64` proven says
    nothing about `macos / x86_64`, and this function will not merge them: the
    matrix is a list of surfaces that ran, in the words of the machines that
    ran them.
    """
    surfaces = {}
    for observation in observations:
        if observation.get("outcome") != "PASS":
            continue
        key = (
            observation.get("os_family"),
            observation.get("os_release"),
            observation.get("arch"),
        )
        entry = surfaces.setdefault(
            key,
            {
                "os_family": key[0],
                "os_release": key[1],
                "arch": key[2],
                "levels": set(),
                "python_versions": set(),
                "git_versions": set(),
                "runner_provenance": set(),
            },
        )
        entry["levels"].add(observation.get("level"))
        entry["python_versions"].add(observation.get("python_version"))
        if observation.get("git_version"):
            entry["git_versions"].add(observation["git_version"])
        entry["runner_provenance"].add(observation.get("runner_provenance"))
    ordered = []
    for key in sorted(surfaces, key=lambda k: tuple(str(part) for part in k)):
        entry = surfaces[key]
        ordered.append(
            {
                "os_family": entry["os_family"],
                "os_release": entry["os_release"],
                "arch": entry["arch"],
                "levels": sorted(entry["levels"]),
                "python_versions": sorted(entry["python_versions"]),
                "git_versions": sorted(entry["git_versions"]),
                "runner_provenance": sorted(entry["runner_provenance"]),
            }
        )
    return ordered


def git_boundary(observations, enforced_minimum=None):
    """What is known about the Git compatibility boundary, and what is not.

    Three different things get confused under the phrase "minimum supported
    version", so this returns them separately:

        enforced      the floor the product refuses below, and why
        exercised     the versions AIQE was actually run against
        gap           the range that is enforced but never exercised

    The gap is the interesting field and the reason this is not one number.
    AIQE refuses below 2.32 because that is the release in which the
    configuration isolation it depends on became available at all - a
    mechanism argument, backed by a refusal that is proven on a real 2.30.2
    surface. It is not a claim that 2.32 was run. If every runner in the
    matrix ships the same modern Git, then the versions between the floor and
    that one are enforced and untested, and saying so is the whole job.
    """
    versions = {}
    for observation in observations:
        if observation.get("outcome") != "PASS":
            continue
        reported = observation.get("git_version")
        if not reported:
            continue
        versions.setdefault(reported, set()).add(
            "%s %s / %s / %s"
            % (
                observation.get("os_family"),
                observation.get("os_release"),
                observation.get("arch"),
                observation.get("level"),
            )
        )

    def numeric(reported):
        for token in reported.split():
            parts = token.split(".")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                collected = []
                for part in parts:
                    if not part.isdigit():
                        break
                    collected.append(int(part))
                return tuple(collected)
        return ()

    exercised = sorted(versions, key=numeric)
    lowest = exercised[0] if exercised else None
    floor = (
        ".".join(str(part) for part in enforced_minimum) if enforced_minimum else None
    )

    gap = None
    if floor and exercised:
        # Compare only as many components as the floor names. `2.32.0` and
        # `(2, 32)` are the same version; Python's tuple ordering would call
        # the first one greater purely because it is longer, and report a gap
        # against the very version that was run.
        floor_numbers = tuple(enforced_minimum)

        def at_or_above_floor(version):
            comparable = numeric(version)[: len(floor_numbers)]
            return bool(comparable) and comparable >= floor_numbers

        # Only a version AIQE will actually run can close the gap. A surface
        # below the floor is exercised as a *refusal* - it proves the product
        # fails closed there, and says nothing about any supported version. It
        # was previously allowed to be `lowest`, which made the gap disappear
        # for the one reason that cannot close it.
        supported = [version for version in exercised if at_or_above_floor(version)]
        lowest_supported = supported[0] if supported else None
        if lowest_supported is not None and numeric(lowest_supported)[
            : len(floor_numbers)
        ] > floor_numbers:
            gap = (
                "Git %s is enforced but not exercised: the lowest version AIQE "
                "was actually run against is %s. Versions from %s up to that "
                "one are permitted by the floor and covered by no run."
                % (floor, lowest_supported, floor)
            )

    return {
        "enforced_minimum": floor,
        "enforced_minimum_basis": (
            "GIT_CONFIG_SYSTEM and GIT_CONFIG_GLOBAL, which AIQE's configuration "
            "isolation is built on, were introduced in Git 2.32. Below that they "
            "are ignored silently. The refusal is proven on a real Git 2.30.2 "
            "surface; the floor itself is a mechanism argument, not a run."
        )
        if floor
        else None,
        "lowest_exercised": lowest,
        "highest_exercised": exercised[-1] if exercised else None,
        "exercised": [
            {"git_version": version, "surfaces": sorted(versions[version])}
            for version in exercised
        ],
        "enforced_but_unexercised_range": gap,
        "minimum_claimed": floor,
        "minimum_status": PROVEN if floor else NOT_PROVEN,
        "statement": (
            "AIQE refuses to run below the enforced minimum rather than running "
            "under-isolated. Above it, AIQE publishes the versions it was "
            "actually run against and does not interpolate between them."
        ),
    }


def unproven(claims):
    """Every claim that is not proven, as a flat list. Empty means all proven."""
    return sorted(
        name for name, claim in claims.items() if claim["verdict"] != PROVEN
    )
