"""AIQE command-line entry point.

This build implements exactly the surface below:

    aiqe --version
    aiqe doctor [--format json]
    aiqe task start --own <path>... [--label <text>]
    aiqe task
    aiqe task end

The frozen v1 surface is larger. `init`, `check`, `commit` and `receipt` are
not registered here, not stubbed, and not advertised: a command that parses but
does nothing is worse than one that does not exist, because it implies a
capability the product has not built. They arrive with their implementations.

One parsing rule matters more than it looks. The value after `--own` is taken
literally, whatever it is. `--own --help` declares a path named `--help`, and
`--own *` declares a path named `*`. Owned paths are data, and a parser that
second-guessed a filename would be the first place the literal-path guarantee
broke.

The parser is written out rather than delegated, so that every exit status is
this module's decision. A generic parser exits 2 on a usage error, and 2 is
INCOMPLETE in the canonical AIQE exit vocabulary - a completion verdict, and a
meaning a bad flag has no business claiming.
"""

import os
import sys

from . import exits
from . import report as report_module
from .doctor import inspect

USAGE = """usage: aiqe --version
       aiqe doctor [--format json]
       aiqe task start --own <path>... [--label <text>]
       aiqe task
       aiqe task end

This build implements the doctor and task surfaces only."""

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

    if argv[0] == "task":
        return _task(argv[1:], stdout, stderr, cwd, env)

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


def _task(argv, stdout, stderr, cwd, env):
    from . import task as task_module

    if not argv:
        outcome = task_module.status(cwd, env=env)
    elif argv[0] == "end":
        if len(argv) > 1:
            return _usage(stderr, "task end takes no arguments")
        outcome = task_module.end(cwd, env=env)
    elif argv[0] == "start":
        owned, label, error = _parse_task_start(argv[1:])
        if error is not None:
            return _usage(stderr, error)
        outcome = task_module.start(cwd, owned, label=label, env=env)
    else:
        return _usage(stderr, "unknown task subcommand %r" % (argv[0],))

    stream = stdout if outcome.exit_code == 0 else stderr
    stream.write(outcome.render())
    return outcome.exit_code


def _parse_task_start(argv):
    """Parse `--own` and `--label`.

    Returns (owned paths as bytes, label, error). Every `--own` value is
    consumed as a literal path with no inspection: that is the point.
    """
    owned = []
    label = None
    index = 0

    while index < len(argv):
        argument = argv[index]
        if argument == "--own":
            if index + 1 >= len(argv):
                return None, None, "--own requires a path"
            owned.append(os.fsencode(argv[index + 1]))
            index += 2
        elif argument == "--label":
            if index + 1 >= len(argv):
                return None, None, "--label requires a value"
            if label is not None:
                return None, None, "--label given more than once"
            label = argv[index + 1]
            index += 2
        else:
            return None, None, "unknown argument %r" % (argument,)

    if not owned:
        return None, None, "task start requires at least one --own <path>"
    return owned, label, None


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
    sys.exit(main(sys.argv[1:], sys.stdout, sys.stderr, os.getcwd(), os.environ))
