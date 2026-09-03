"""AIQE - quant engineering assurance layer.

AIQE v1 is deterministic. It contains no model calls, makes no network
requests, and installs nothing into a repository.
"""

#: The one place AIQE's version is written.
#:
#: `0.1.0a0` is PEP 440's spelling of the frozen milestone `v0.1.0-alpha`:
#: the first installable real product. It is a *package* version and nothing
#: more. No Git tag exists, no release exists, and nothing is published to any
#: index - a version string is what an artifact calls itself, not a claim that
#: anybody can obtain it.
__version__ = "0.1.0a0"

__all__ = ["__version__"]
