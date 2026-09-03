"""What AIQE claims about where it runs, in one place.

These constants are the *proposal*. Nothing here is a support statement: the
gate in `support.py` compares each of them against observations and decides.
Keeping the proposal separate from the evidence is what makes it possible for
a claim to be refused, and for the refusal to appear in the manifest instead
of being quietly dropped from the list.

The documentation test reads these too, so a claim cannot be widened in the
README without widening it here, where the gate will ask for evidence.
"""

#: The contiguous Python range the project wants to support.
CLAIMED_PYTHON_MINORS = ("3.11", "3.12", "3.13", "3.14")

#: The OS families the product targets. Every claimed Python minor must be
#: proven on every one of these before the range itself is claimed.
CLAIMED_OS_FAMILIES = ("macos", "linux")

#: Explicitly not a v1 target. Named so that the manifest states it rather
#: than leaving its absence to be interpreted.
OUT_OF_SCOPE = ("windows",)

#: The floor in package metadata. Not a claim by itself - `Requires-Python`
#: refusing to install on 3.10 is a different statement from 3.11 having been
#: tested - but the two must agree, and a test asserts that they do.
REQUIRES_PYTHON = ">=3.11"
