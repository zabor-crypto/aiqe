"""AIQE command-line entry point.

This build implements exactly the surface below:

    aiqe --help | -h | help
    aiqe --version
    aiqe doctor  [--format json]
    aiqe init    [--print] [--yes]
    aiqe task    start --own <path>... [--label <text>]
    aiqe task
    aiqe task    end
    aiqe check   [--allow <validator-id>]... [--format json]
    aiqe commit  -m <message>
    aiqe receipt [--local] [--format json]

That is the whole frozen v1 surface, and `commit` arrived with its
implementation rather than as a stub, because a command that parses and does
nothing implies a capability the product has not built.

`commit` takes exactly one flag. There is no `--amend`, no `--no-verify`, no
`--allow-empty` and no `--push`, and their absence is the feature: every one
of them is a way to make the command succeed by weakening the claim it makes.

One parsing rule matters more than it looks. The value after `--own` is taken
literally, whatever it is. `--own --help` declares a path named `--help`, and
`--own *` declares a path named `*`. Owned paths are data, and a parser that
second-guessed a filename would be the first place the literal-path guarantee
broke.

The parser is written out rather than delegated, so that every exit status is
this module's decision. A generic parser exits 2 on a usage error, and 2 is
INCOMPLETE in the canonical AIQE exit vocabulary - a completion verdict, and a
meaning a bad flag has no business claiming.

**Prompting is decided here, and only here.** A machine-readable invocation and
a non-interactive one never prompt: they report `CONSENT_REQUIRED` instead.
`main` therefore takes an explicit `prompt`, which the console entry point
supplies only when both standard input and standard output are terminals. A
library caller passes nothing and gets the non-interactive behaviour, which is
also what the test suite exercises.
"""

import json
import os
import sys

from . import exits
from . import gitq
from . import report as report_module
from .doctor import inspect
from .gitq import GitRunner, parse_version

USAGE = """usage: aiqe --help | -h | help
       aiqe --version
       aiqe doctor  [--format json]
       aiqe init    [--print] [--yes]
       aiqe task    start --own <path>... [--label <text>]
       aiqe task
       aiqe task    end
       aiqe check   [--allow <validator-id>]... [--format json]
       aiqe commit  -m <message>
       aiqe receipt [--local] [--format json]

`aiqe commit` creates one bounded completion commit. It never pushes."""

_FORMATS = ("human", "json")


def main(argv, stdout, stderr, cwd, env=None, prompt=None):
    """Run one AIQE invocation. Returns the process exit status."""
    if not argv:
        return _usage(stderr, "no command given")

    if argv[0] in ("--help", "-h", "help"):
        # Answered before the Git preflight below, and before anything reaches
        # a repository. Asking a tool how to invoke it is the one question it
        # must be able to answer on a machine where it would refuse to do
        # anything else, and an exit status is part of the answer: a help
        # request that succeeded exits 0. Every spelling prints the same
        # canonical text, so no two of them can drift apart.
        if len(argv) > 1:
            return _usage(stderr, "%s takes no arguments" % (argv[0],))
        stdout.write(USAGE + "\n")
        return exits.OK

    if argv[0] == "--version":
        if len(argv) > 1:
            return _usage(stderr, "--version takes no arguments")
        from . import __version__

        stdout.write("aiqe %s\n" % __version__)
        return exits.OK

    # Every command below this line reaches Git, and every one of them relies
    # on AIQE's configuration isolation actually isolating. On a Git that does
    # not know `GIT_CONFIG_SYSTEM` and `GIT_CONFIG_GLOBAL`, applying them
    # succeeds and changes nothing, so the isolation is silently absent while
    # every answer still looks confident. AIQE refuses there rather than
    # producing one.
    refusal = _refuse_unsupported_git(stderr, cwd, env)
    if refusal is not None:
        return refusal

    if argv[0] == "doctor":
        return _doctor(argv[1:], stdout, stderr, cwd, env)
    if argv[0] == "init":
        return _init(argv[1:], stdout, stderr, cwd, env, prompt)
    if argv[0] == "task":
        return _task(argv[1:], stdout, stderr, cwd, env)
    if argv[0] == "check":
        return _check(argv[1:], stdout, stderr, cwd, env, prompt)
    if argv[0] == "commit":
        return _commit(argv[1:], stdout, stderr, cwd, env)
    if argv[0] == "receipt":
        return _receipt(argv[1:], stdout, stderr, cwd, env)

    return _usage(stderr, "unknown command %r" % (argv[0],))


def _refuse_unsupported_git(stderr, cwd, env):
    """Refuse, before any command runs, on a Git AIQE cannot isolate.

    Returns an exit status to return, or None to proceed.

    This is a refusal, not a diagnosis: the invariant every AIQE command
    stands on - that nothing the repository defines is executed - cannot be
    demonstrated on a Git older than the floor, and a bounded commit's policy
    preflight silently stops seeing a globally defined hook, filter or signing
    configuration. Reporting a confident result there would be the exact
    failure this product exists to refuse.
    """
    runner = GitRunner(cwd, env=env)
    result = runner.run("--version")
    if not result.ok:
        # Git missing or unrunnable is Doctor's own diagnosis to make, and it
        # already makes it. Nothing to add here.
        return None

    version = parse_version(result.stdout)
    supported, reason = gitq.config_isolation_supported(version)
    if supported:
        return None

    if reason == gitq.GIT_TOO_OLD:
        stderr.write(
            "aiqe: UNSUPPORTED %s\n"
            "    Git %s cannot apply the configuration isolation AIQE relies\n"
            "    on. GIT_CONFIG_SYSTEM and GIT_CONFIG_GLOBAL arrived in Git\n"
            "    %s; an older Git ignores them silently, so a filter driver or\n"
            "    hook defined in your global configuration stays in scope and\n"
            "    can be executed while AIQE reports that nothing was.\n"
            "    AIQE refuses rather than answering without the isolation.\n"
            "    Upgrade Git to %s or newer.\n"
            % (
                reason,
                version,
                ".".join(str(part) for part in gitq.MINIMUM_GIT_VERSION),
                ".".join(str(part) for part in gitq.MINIMUM_GIT_VERSION),
            )
        )
    else:
        stderr.write(
            "aiqe: UNSUPPORTED %s\n"
            "    Git ran, but did not report a version AIQE could read, so it\n"
            "    cannot be established that the configuration isolation AIQE\n"
            "    relies on is honoured. AIQE fails closed on an unknown\n"
            "    toolchain rather than assuming the best about it.\n"
            "    Git %s or newer is required.\n"
            % (
                reason,
                ".".join(str(part) for part in gitq.MINIMUM_GIT_VERSION),
            )
        )
    return exits.UNSUPPORTED


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


def _init(argv, stdout, stderr, cwd, env, prompt):
    from . import init as init_module

    print_only = False
    assume_yes = False
    for argument in argv:
        if argument == "--print":
            if print_only:
                return _usage(stderr, "--print given more than once")
            print_only = True
        elif argument == "--yes":
            if assume_yes:
                return _usage(stderr, "--yes given more than once")
            assume_yes = True
        else:
            return _usage(stderr, "unknown argument %r" % (argument,))

    if print_only and assume_yes:
        # `--print` writes nothing and `--yes` means write without asking.
        # Together they are two different instructions, and guessing which one
        # the user meant is how a preview writes a file.
        return _usage(stderr, "--print and --yes contradict each other")

    outcome = init_module.run(
        cwd, print_only=print_only, assume_yes=assume_yes, env=env, prompt=prompt
    )
    stream = stdout if outcome.exit_code == 0 else stderr
    stream.write(outcome.render())
    return outcome.exit_code


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


def _check(argv, stdout, stderr, cwd, env, prompt):
    from . import check as check_module

    allow = []
    index = 0
    format_arguments = []
    while index < len(argv):
        argument = argv[index]
        if argument == "--allow":
            if index + 1 >= len(argv):
                return _usage(stderr, "--allow requires a validator id")
            allow.append(argv[index + 1])
            index += 2
            continue
        if argument.startswith("--allow="):
            value = argument[len("--allow="):]
            if not value:
                return _usage(stderr, "--allow requires a validator id")
            allow.append(value)
            index += 1
            continue
        format_arguments.append(argument)
        index += 1

    output_format, error = _parse_format(format_arguments)
    if error is not None:
        return _usage(stderr, error)

    if output_format == "json":
        # A machine-readable check never prompts. There is nobody at the
        # terminal to answer, and a prompt written into a JSON stream is a
        # corrupted document and a hung script.
        prompt = None

    outcome = check_module.run(cwd, allow=allow, env=env, prompt=prompt)

    if output_format == "json":
        if outcome.document is None:
            stderr.write(outcome.render())
        else:
            stdout.write(json.dumps(outcome.document, indent=2, sort_keys=True) + "\n")
        return outcome.exit_code

    stream = stdout if outcome.exit_code in (0, 1, 2) else stderr
    stream.write(outcome.render())
    return outcome.exit_code


def _commit(argv, stdout, stderr, cwd, env):
    """`aiqe commit -m <message>`. One flag, and no way to widen it.

    The message is required and is taken literally, whatever it is. It is user
    data: AIQE stores none of it and echoes none of it, so there is no path by
    which a commit message reaches a shareable receipt.
    """
    from . import commit as commit_module

    message = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "-m":
            if index + 1 >= len(argv):
                return _usage(stderr, "-m requires a commit message")
            if message is not None:
                return _usage(stderr, "-m given more than once")
            message = argv[index + 1]
            index += 2
            continue
        return _usage(stderr, "unknown argument %r" % (argument,))

    if message is None:
        return _usage(stderr, "commit requires -m <message>")
    if not message.strip():
        # Git refuses an empty message and so does this. A completion commit
        # with nothing written on it is a worse artifact than no commit.
        return _usage(stderr, "-m requires a non-empty commit message")

    outcome = commit_module.run(cwd, message, env=env)
    stream = stdout if outcome.exit_code in (0, 1, 2) else stderr
    stream.write(outcome.render())
    return outcome.exit_code


def _receipt(argv, stdout, stderr, cwd, env):
    from . import receipt as receipt_module

    local = False
    format_arguments = []
    for argument in argv:
        if argument == "--local":
            if local:
                return _usage(stderr, "--local given more than once")
            local = True
            continue
        format_arguments.append(argument)

    output_format, error = _parse_format(format_arguments)
    if error is not None:
        return _usage(stderr, error)

    outcome = receipt_module.run(cwd, local=local, env=env)

    if outcome.document is None:
        # A refused receipt produces no artifact in either format. Rendering a
        # partial one would be a receipt that says less than it appears to.
        stderr.write(outcome.render())
        return outcome.exit_code

    if output_format == "json":
        stdout.write(json.dumps(outcome.document, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(outcome.render())
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
    """Parse the one flag that is common to the machine-readable commands.

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


def _terminal_prompt(stdin, stdout):
    """A yes/no prompt, or None when there is nobody to ask.

    Both streams must be terminals. Standard output alone is not enough: a
    command whose output is piped into a file still has a person at the
    keyboard, but a command whose *input* is redirected does not, and reading
    a stray line from that input as an answer would be consent invented by the
    shell.
    """
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return None
    except (AttributeError, ValueError):
        return None

    def ask(text):
        stdout.write(text + "\n")
        stdout.write("Proceed? Type 'yes' to continue: ")
        stdout.flush()
        try:
            answer = stdin.readline()
        except (KeyboardInterrupt, EOFError, OSError):
            stdout.write("\n")
            return False
        # Nothing but an unambiguous yes. A bare Return is not consent, and
        # neither is a `y` typed at a prompt somebody did not read.
        return answer.strip().lower() == "yes"

    return ask


def main_entry():
    """Console-script entry point."""
    sys.exit(
        main(
            sys.argv[1:],
            sys.stdout,
            sys.stderr,
            os.getcwd(),
            os.environ,
            prompt=_terminal_prompt(sys.stdin, sys.stdout),
        )
    )
