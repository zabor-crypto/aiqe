"""`aiqe init`: write `./aiqe.toml`, and nothing else.

The whole design of this command is what it refuses to do.

**It writes exactly one repository path.** `./aiqe.toml`, at the worktree root,
and only after the user has seen the complete file and said yes. Not
`.gitignore`, not a hook, not `.git/config`, not a shell profile, not an agent
configuration file. A tool that installs itself into the places a developer
did not look is a tool whose behaviour they cannot predict, and the first
command a person runs is the worst possible moment to demonstrate that.

**It does not overwrite.** An existing `aiqe.toml` is somebody's declaration
of what their repository contains and what checks it. Replacing it with a
scaffold - even a well-meaning merged one - would silently discard
classification rules, which is how a quant surface becomes unclassified
without anyone seeing a message.

**It does not guess.** The scaffold declares no `[[surface]]` and no
`[[validator]]`, because AIQE has no safe way to discover either. It could
match directory names against a list of conventions and be right often
enough to be dangerous: a `src/strategy/` that got declared `quant = true`
with plausible contracts would produce a config nobody wrote and everybody
trusts, and a `quant = false` inferred from an absence of evidence is exactly
the false green this product exists to refuse. So the scaffold is a commented
template. Until a surface is declared, a changed owned path is `UNCLASSIFIED`
and `aiqe check` reports a classification gap - which is the honest state, and
is visible rather than silent.

`--print` is a preview with no side effects at all: no file, no machine-local
state, no salt. It exists so that "what would this do" is answerable without
doing it.
"""

import os

from . import config as config_module
from . import contracts as contracts_module
from . import exits
from . import task as task_module

INIT_WRITTEN = "INIT_WRITTEN"
INIT_PREVIEWED = "INIT_PREVIEWED"
INIT_DECLINED = "INIT_DECLINED"
CONFIG_ALREADY_PRESENT = "CONFIG_ALREADY_PRESENT"
CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
CONFIG_WRITE_FAILED = "CONFIG_WRITE_FAILED"

#: The proposed file. Written out in full rather than assembled from
#: fragments, because the user is shown the exact bytes that would land and
#: any generated part of it would be a place for the two to diverge.
SCAFFOLD = '''\
# AIQE configuration.
#
# Two declaration types, and no others:
#
#   [[surface]]    which paths carry which quant contract obligations
#   [[validator]]  which commands discharge them
#
# `aiqe init` declared neither, on purpose. AIQE has no safe way to discover
# what in this repository is quant-critical, and a guess that happened to be
# wrong would be a configuration nobody wrote and everybody trusted. In
# particular AIQE never infers `quant = false` from an absence of evidence:
# until a [[surface]] below matches a changed owned path, that path is
# UNCLASSIFIED and `aiqe check` reports a classification gap rather than a
# pass.
#
# Reference: docs/config.md

schema = 1

# --- Surfaces ---------------------------------------------------------------
#
# `paths` are AIQE patterns, matched on raw bytes. They are not Git pathspec
# and are never handed to Git:
#
#   *       zero or more bytes, within one path component
#   ?       exactly one byte, within one path component
#   **      an entire component: zero or more whole path components
#   [abc]   a byte class, within one path component
#
# Every matching declaration is evaluated - not the first one - and quant
# contract obligations union across them, so adding a surface can never
# reduce an obligation. A path matched by both a `quant = true` and a
# `quant = false` surface is a CONFIG_CONFLICT and fails closed.
#
# The six launch contract families, and what each one is about:
#
%s#
# Custom contract identifiers are legal. An obligation these six do not name
# should be said in your own words rather than misfiled under one of them.
#
# [[surface]]
# paths = ["src/strategy/**"]
# quant = true
# contracts = ["CAUSALITY", "DATA_ALIGNMENT"]
#
# [[surface]]
# paths = ["tests/**", "docs/**"]
# quant = false

# --- Validators -------------------------------------------------------------
#
# `run` is an argument vector. There is no shell, so nothing here is
# word-split, glob-expanded or substituted.
#
# `timeout` is mandatory, in seconds. A validator runs as an unsupervised
# child process, and a check that can never report anything is not a check.
#
# `required = true` makes a validator a completion obligation. An optional
# validator is visible in the output and never satisfies coverage.
#
# A validator that declares no `contracts` is a generic task validator: it
# applies to every checked task. A generic pass never covers a quant
# contract. An applicable contract with zero required validators bound to it
# is a COVERAGE_GAP, and a COVERAGE_GAP is not a pass.
#
# AIQE runs a validator only after explicit consent recorded on this machine,
# and it makes no sandbox, filesystem or network claim about what a validator
# then does.
#
# [[validator]]
# id = "unit"
# run = ["pytest", "-q", "tests/unit"]
# required = true
# timeout = 300
#
# [[validator]]
# id = "causality"
# run = ["python", "checks/no_lookahead.py"]
# required = true
# timeout = 120
# contracts = ["CAUSALITY"]
'''


class InitOutcome(object):
    __slots__ = ("code", "exit_code", "lines", "written")

    def __init__(self, code, exit_code, lines, written=()):
        self.code = code
        self.exit_code = exit_code
        self.lines = lines
        #: Repository-relative paths this invocation actually wrote.
        self.written = tuple(written)

    def render(self):
        # Trailing spaces are column padding, not content. Left in, they
        # survive into anything that quotes this output and break on the first
        # editor that strips whitespace on save.
        return "\n".join(line.rstrip() for line in self.lines) + "\n"


def proposal():
    """The complete proposed `aiqe.toml`, as text."""
    families = "".join(
        "#   %-22s %s\n" % (name, contracts_module.DESCRIPTIONS[name])
        for name in contracts_module.LAUNCH_CONTRACTS
    )
    return SCAFFOLD % (families,)


def run(cwd, print_only=False, assume_yes=False, env=None, prompt=None):
    """Preview or write `./aiqe.toml`."""
    repository, failure = task_module.discover(cwd, env)
    if failure is not None:
        return InitOutcome(failure.code, failure.exit_code, failure.lines)

    text = proposal()
    exists = _existing(repository.worktree)

    if print_only:
        # A preview, and nothing more. No file, no state directory, no salt:
        # `--print` must leave a machine AIQE has never written to exactly as
        # it found it, or it is not a preview.
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if exists:
            lines.extend(
                [
                    "",
                    "# NOTE: %s already exists here. `aiqe init` would refuse "
                    "rather than" % (config_module.CONFIG_FILENAME,),
                    "# overwrite it; the file above is what it would have "
                    "proposed.",
                ]
            )
        return InitOutcome(INIT_PREVIEWED, exits.OK, lines)

    if exists:
        return InitOutcome(
            CONFIG_ALREADY_PRESENT,
            exits.UNSUPPORTED,
            [
                "aiqe: %s already exists at the repository root."
                % (config_module.CONFIG_FILENAME,),
                "AIQE will not overwrite it: it declares which paths carry "
                "which contract",
                "obligations, and replacing that with a scaffold would "
                "discard classification",
                "rules without anyone seeing it. Edit it, or move it aside "
                "first.",
                "`aiqe init --print` shows what would have been proposed.",
            ],
        )

    if not assume_yes:
        if prompt is None:
            return InitOutcome(
                CONFIRMATION_REQUIRED,
                exits.UNSUPPORTED,
                [
                    "aiqe: writing %s needs confirmation, and this is not an "
                    "interactive terminal." % (config_module.CONFIG_FILENAME,),
                    "Run `aiqe init --print` to see the proposed file, or "
                    "`aiqe init --yes` to write it.",
                ],
            )
        if not prompt(_confirmation_request(text)):
            return InitOutcome(
                INIT_DECLINED,
                exits.OK,
                ["", "Nothing was written."],
            )

    try:
        _write(repository.worktree, text)
    except OSError as exc:
        return InitOutcome(
            CONFIG_WRITE_FAILED,
            exits.UNSUPPORTED,
            [
                "aiqe: %s could not be written: %s"
                % (config_module.CONFIG_FILENAME, exc.strerror),
            ],
        )

    return InitOutcome(
        INIT_WRITTEN,
        exits.OK,
        [
            "AIQE INIT",
            "",
            "  Wrote           ./%s" % (config_module.CONFIG_FILENAME,),
            "  Declared        no surfaces, no validators",
            "",
            "  Nothing was guessed. Until a [[surface]] declaration matches a",
            "  changed owned path, that path is UNCLASSIFIED and `aiqe check`",
            "  reports a classification gap rather than a pass.",
            "",
            "  Next            aiqe task start --own <path>...",
            "",
        ],
        written=("./" + config_module.CONFIG_FILENAME,),
    )


def _confirmation_request(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    lines.append(
        "The file above would be written to ./%s."
        % (config_module.CONFIG_FILENAME,)
    )
    lines.append("It is the only thing `aiqe init` writes.")
    return "\n".join(lines)


def _existing(worktree):
    """Is there anything at `./aiqe.toml`, of any kind?

    `lstat`, so that a symlink counts as something already there rather than
    as a path to write through.
    """
    try:
        os.lstat(config_module.config_path(worktree))
    except OSError:
        return False
    return True


def _write(worktree, text):
    """Create the file exclusively, and make it durable before returning.

    `O_EXCL` rather than a truncating open: the existence check above and the
    write are two moments, and the kernel deciding the race is better than
    AIQE deciding it.
    """
    path = config_module.config_path(worktree)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(descriptor, text.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
