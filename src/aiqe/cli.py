"""AIQE command-line entry point.

This build implements exactly the surface below:

    aiqe --version
    aiqe doctor [--format json]

The frozen v1 surface is larger. `init`, `task`, `check`, `commit` and
`receipt` are not registered here, not stubbed, and not advertised: a command
that parses but does nothing is worse than one that does not exist, because it
implies a capability the product has not built. They arrive with their
implementations.

The parser is written out rather than delegated, so that every exit status is
this module's decision. A generic parser exits 2 on a usage error, and 2 is
INCOMPLETE in the canonical AIQE exit vocabulary - a completion verdict, and a
meaning a bad flag has no business claiming.
"""

import sys

from . import exits
from . import report as report_module
from .doctor import inspect

USAGE = """usage: aiqe --version
       aiqe doctor [--format json]

This build implements the doctor surface only."""

_FORMATS = ("human", "json")


def main(argv, stdout, stderr, cwd, env=None):
    """Run one AIQE invocation. Returns the process exit status."""
    if not argv:
        return _usage(stderr, "no command given")

    if argv[0] == "--version":
        if len(argv) > 1:
            return _usage(stderr, "--version takes no arguments")
        from . import __version__

        stdout.write("aiqe %s\n" % __version__)
        return exits.OK

    if argv[0] == "doctor":
        return _doctor(argv[1:], stdout, stderr, cwd, env)

    return _usage(stderr, "unknown command %r" % (argv[0],))


def _doctor(argv, stdout, stderr, cwd, env):
    output_format, error = _parse_format(argv)
    if error is not None:
        return _usage(stderr, error)

    from . import __version__

    result = inspect(cwd, env=env)

    if output_format == "json":
        stdout.write(report_module.render_json(result, __version__))
    else:
        stdout.write(report_module.render_human(result))

    return result.exit_code()


def _parse_format(argv):
    """Parse the one flag Doctor accepts.

    Returns (format, error). An unrecognised flag or value is an error rather
    than a default, because silently falling back to human output would make a
    typo in a script look like a passing run.
    """
    output_format = "human"
    index = 0
    seen = False

    while index < len(argv):
        argument = argv[index]
        if argument == "--format":
            if index + 1 >= len(argv):
                return None, "--format requires a value"
            value = argv[index + 1]
            index += 2
        elif argument.startswith("--format="):
            value = argument[len("--format="):]
            index += 1
        else:
            return None, "unknown argument %r" % (argument,)

        if seen:
            return None, "--format given more than once"
        if value not in _FORMATS:
            return None, "unknown --format value %r (expected: json)" % (value,)
        output_format = value
        seen = True

    return output_format, None


def _usage(stderr, message):
    stderr.write("aiqe: %s\n%s\n" % (message, USAGE))
    return exits.UNSUPPORTED


def main_entry():
    """Console-script entry point."""
    import os

    sys.exit(main(sys.argv[1:], sys.stdout, sys.stderr, os.getcwd(), os.environ))
