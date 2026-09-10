"""AIQE - quant engineering assurance layer.

AIQE v1 is deterministic. It contains no model calls, makes no network
requests, and installs nothing into a repository.
"""

#: The one place AIQE's version is written.
#:
#: `0.1.0a0` is the package version, in PEP 440's spelling; a Git tag for this
#: version, if one is made, is `v0.1.0a0`. It is a *package* version and
#: nothing more - what an artifact calls itself, not a claim that anybody can
#: obtain it. Whether a Git tag, a GitHub Release or a package-index entry
#: exists for it is established from that object, not from this string.
__version__ = "0.1.0a0"

__all__ = ["__version__"]
