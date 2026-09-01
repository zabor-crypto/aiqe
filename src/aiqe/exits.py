"""Canonical AIQE exit vocabulary.

The exit codes are uniform across commands and closed at four values. A
command never invents a fifth code; machine-readable reason codes carry the
detail that the exit status deliberately does not.

    0   successful / reviewable operation
    1   FAIL / NOT_REVIEWABLE
    2   INCOMPLETE
    3   UNSUPPORTED / invalid configuration / operation cannot safely proceed

Doctor's application of that vocabulary:

    0   a valid first-contact diagnostic was produced.
        Findings are part of a valid diagnostic. Doctor does not turn an
        ordinary finding into a process failure.

    3   a valid Doctor result could not be produced: the invocation was not a
        supported one, or the repository is in a topology Doctor does not
        support diagnosing (for example a bare repository).

Doctor never exits 1 or 2. Those codes belong to commands that adjudicate
completion, and Doctor adjudicates nothing.
"""

OK = 0
FAIL = 1
INCOMPLETE = 2
UNSUPPORTED = 3

__all__ = ["OK", "FAIL", "INCOMPLETE", "UNSUPPORTED"]
