"""Release-proof machinery: what an installable AIQE artifact has been shown to do.

The benchmark families under `bench/fixtures/` measure what AIQE does to a
repository. This package measures something different and equally unproven
by them: whether the thing a user would actually install is the thing that was
tested, and on which surfaces that has been demonstrated rather than assumed.

Three modules carry the whole idea.

`environment` records who ran a measurement - OS, release, architecture,
interpreter, Git version, source commit. A run whose environment identity is
unknown is not support evidence, so the identity is part of every record
rather than a log line.

`artifacts` inspects built distributions against an allowlist. Not a
denylist: a wheel is small and completely enumerable, so the question worth
asking is "is every member something we meant to ship", not "does any member
match a shape we thought of".

`support` turns observations into claims, and refuses to turn anything else
into one. It is the component that says NOT_PROVEN, and the reason it exists
as code rather than as a paragraph in a document is that a paragraph cannot
fail a build.
"""
