"""Validator identity, consent, and execution.

A validator is a command the repository declares. Running one is the only
thing in AIQE that executes code AIQE did not write, and the three sections
below are the three decisions that make that defensible.

**Identity.** A validator's semantic definition is its id, its argument
vector, its timeout, whether it is required, and the contracts it discharges.
Those five fields, and nothing else, are hashed into a definition digest. The
digest is over a length-delimited binary serialisation, not over a rendering:
a rendering has quoting and separators, and two different definitions must not
be able to render to the same string. Comments, key order and whitespace in
`aiqe.toml` change the *configuration* digest, which is what staleness uses,
and deliberately do not change a validator's identity, which is what consent
uses.

**Consent.** Tracked configuration is executable trust material, not
authorization. Anyone who can land a commit can add a `[[validator]]` block
naming any command on the machine, so the fact that a command is declared is
not a reason to run it. Consent is machine-local, recorded per definition
digest, and never written into `aiqe.toml`, tracked content, or `.git`.
Changing any semantic field produces a different digest, and a definition
whose digest is not the one that was consented to has no consent - not
"probably fine", not migrated. Without consent the outcome is `UNKNOWN` with
reason `CONSENT_REQUIRED`, which is neither a pass nor a failure, because
AIQE genuinely does not know what that validator would have said.

`--allow <id>` authorises the exact definition for one run and records
nothing.

**Execution.** As an argument vector, with no shell, from the repository root,
under a mandatory timeout.

```
exit 0                  PASS
non-zero                FAIL
timeout                 FAIL
executable unavailable  UNAVAILABLE
consent withheld        UNKNOWN
```

A timeout is a `FAIL`, not an unknown. A check that hangs is a check that
failed to establish what it was asked to establish, and treating it as merely
unknown is how an unbounded validator becomes a permanent excuse.

What AIQE does **not** claim about a validator it runs: no sandbox, no
filesystem restriction, no network restriction. It runs as the user, with the
user's environment, and can do anything the user's shell can do. That is
stated to the user before consent is asked for, because it is the only
honest basis on which to ask.
"""

import hashlib
import json
import os
import signal
import subprocess
import time

#: Domain separator for the validator definition digest.
_DEFINITION_DOMAIN = b"aiqe.validator-definition.v1\0"

#: The consent record's own schema. Machine-local internal state.
CONSENT_SCHEMA_VERSION = 1
CONSENT_FILE_NAME = "consents.json"

#: One fixed budget for retained validator output, per stream. Bounded rather
#: than configurable: a budget the user can raise is a budget that ends up
#: holding a megabyte of somebody's test log in a local evidence file.
OUTPUT_BUDGET_BYTES = 8192

PASS = "PASS"
FAIL = "FAIL"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"

OUTCOMES = (PASS, FAIL, UNAVAILABLE, UNKNOWN, NOT_APPLICABLE)

CONSENT_REQUIRED = "CONSENT_REQUIRED"
CONSENT_DECLINED = "CONSENT_DECLINED"
TIMED_OUT = "TIMED_OUT"
EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
NOT_EXECUTABLE = "NOT_EXECUTABLE"
CONTRACT_NOT_APPLICABLE = "CONTRACT_NOT_APPLICABLE"


def definition_digest(validator):
    """The digest that is this validator's identity.

    Length-delimited and binary-safe:

        "aiqe.validator-definition.v1\\0"
        field(id)
        count(argv) field(argument)...
        field(timeout, decimal)
        field(required, 0x00 or 0x01)
        count(contracts) field(contract)...   sorted

    Contracts are sorted because their order carries no meaning: reordering a
    list must not revoke a user's consent, and adding one must.
    """
    stream = bytearray(_DEFINITION_DOMAIN)
    _field(stream, validator.id.encode("utf-8"))
    _sequence(stream, [argument.encode("utf-8") for argument in validator.argv])
    _field(stream, b"%d" % (validator.timeout,))
    _field(stream, b"\x01" if validator.required else b"\x00")
    _sequence(stream, [name.encode("utf-8") for name in sorted(validator.contracts)])
    return "sha256:" + hashlib.sha256(bytes(stream)).hexdigest()


def _field(stream, value):
    stream += len(value).to_bytes(8, "big")
    stream += value


def _sequence(stream, values):
    stream += len(values).to_bytes(8, "big")
    for value in values:
        _field(stream, value)


# --- Consent ---------------------------------------------------------------


class ConsentStore(object):
    """Machine-local record of which validator definitions may be executed.

    Keyed by definition digest, held beside the worktree's other machine-local
    state and never inside the repository. It outlives a task: consenting to
    run the project's test suite is a statement about a command, not about one
    unit of work, and asking again every time is how a prompt becomes noise
    somebody clicks through.

    A missing or unreadable store grants nothing. That is the fail-closed
    direction: the cost of a lost consent record is one more prompt, and the
    cost of the opposite mistake is executing something nobody agreed to.
    """

    def __init__(self, state_directory):
        self._state_directory = state_directory
        self._granted = self._read()

    def _path(self):
        if self._state_directory is None:
            return None
        return os.path.join(self._state_directory, CONSENT_FILE_NAME)

    def _read(self):
        path = self._path()
        if path is None:
            return {}
        try:
            with open(path, "rb") as handle:
                document = json.loads(handle.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
        if not isinstance(document, dict):
            return {}
        if document.get("schema_version") != CONSENT_SCHEMA_VERSION:
            # A record written under different meaning grants nothing here.
            return {}
        granted = document.get("granted")
        if not isinstance(granted, dict):
            return {}
        return {
            digest: entry
            for digest, entry in granted.items()
            if isinstance(digest, str) and isinstance(entry, dict)
        }

    def granted(self, digest):
        return digest in self._granted

    def grant(self, digest, validator_id):
        """Record consent for one definition digest, durably.

        Written through the same temporary-file-and-rename path as the rest of
        AIQE's local state, so an interrupted write leaves the previous record
        rather than half of a new one.
        """
        from . import taskstate

        if self._state_directory is None:
            return False
        self._granted[digest] = {
            "validator_id": validator_id,
            "granted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        document = {
            "schema_version": CONSENT_SCHEMA_VERSION,
            "granted": self._granted,
        }
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        taskstate.write_local_file(self._state_directory, CONSENT_FILE_NAME, payload)
        return True


# --- Execution -------------------------------------------------------------


class Outcome(object):
    """What one validator did, or why it was not run."""

    __slots__ = (
        "validator_id",
        "digest",
        "required",
        "contracts",
        "outcome",
        "reason",
        "exit_code",
        "timed_out",
        "duration_ms",
        "stdout_tail",
        "stderr_tail",
    )

    def __init__(
        self,
        validator,
        digest,
        outcome,
        reason=None,
        exit_code=None,
        timed_out=False,
        duration_ms=None,
        stdout_tail=None,
        stderr_tail=None,
    ):
        self.validator_id = validator.id
        self.digest = digest
        self.required = validator.required
        self.contracts = tuple(validator.contracts)
        self.outcome = outcome
        self.reason = reason
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.duration_ms = duration_ms
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail

    def as_record(self):
        """The local evidence entry. Output tails are local-only."""
        return {
            "validator_id": self.validator_id,
            "definition_digest": self.digest,
            "required": self.required,
            "contracts": list(self.contracts),
            "outcome": self.outcome,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


def execute(validator, digest, worktree, env):
    """Run one validator to completion, or to its timeout.

    The argument vector is passed as a vector. There is no shell, so nothing
    in `aiqe.toml` is word-split, glob-expanded or substituted, and a
    validator argument containing a space or a quote is one argument.
    """
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(validator.argv),
            cwd=worktree,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Its own process group, so the timeout can end the whole thing.
            # A validator is usually a script, and a script's children inherit
            # the pipes: killing only the process AIQE started leaves those
            # children holding the pipe open, and the read that was supposed
            # to be bounded blocks until they finish on their own. Measured,
            # not assumed - a `sh -c "sleep 30"` under a one-second timeout
            # took thirty seconds before this line existed.
            start_new_session=True,
        )
    except FileNotFoundError:
        return Outcome(
            validator,
            digest,
            UNAVAILABLE,
            reason=EXECUTABLE_NOT_FOUND,
            duration_ms=_elapsed(started),
        )
    except (PermissionError, NotADirectoryError, IsADirectoryError, OSError):
        return Outcome(
            validator,
            digest,
            UNAVAILABLE,
            reason=NOT_EXECUTABLE,
            duration_ms=_elapsed(started),
        )

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=validator.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)
        try:
            stdout, stderr = process.communicate(timeout=_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            # Something is still holding the pipes open despite the group
            # kill. The timeout is a promise about how long a check can take,
            # so it is kept: the outcome is a failure either way, and the
            # bounded output is a convenience, not evidence.
            process.kill()
            stdout, stderr = b"", b""

    duration = _elapsed(started)
    if timed_out:
        # R11 is explicit, and it is the right rule. A validator that did not
        # finish did not establish what it was asked to establish, and calling
        # that "unknown" turns an unbounded check into a permanent excuse.
        return Outcome(
            validator,
            digest,
            FAIL,
            reason=TIMED_OUT,
            exit_code=None,
            timed_out=True,
            duration_ms=duration,
            stdout_tail=_bounded(stdout),
            stderr_tail=_bounded(stderr),
        )

    if process.returncode == 0:
        # Output from a passing validator is discarded. It is not evidence of
        # anything the exit status did not already say, and retaining it is
        # how a local evidence file quietly acquires the contents of a log.
        return Outcome(
            validator, digest, PASS, exit_code=0, duration_ms=duration
        )

    return Outcome(
        validator,
        digest,
        FAIL,
        exit_code=process.returncode,
        duration_ms=duration,
        stdout_tail=_bounded(stdout),
        stderr_tail=_bounded(stderr),
    )


#: How long to wait for a killed validator's output after the group kill.
#: Short, because by this point the outcome is already decided.
_DRAIN_SECONDS = 5


def _terminate(process):
    """End a timed-out validator and everything it started.

    The process group, not the process. Falls back to killing the process
    alone if the group is already gone, which is a race rather than an error.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def _elapsed(started):
    return int((time.monotonic() - started) * 1000)


def _bounded(raw):
    """The tail of a stream, within the fixed budget, rendered terminal-safe.

    The tail rather than the head: a failing command's last lines are the ones
    that say why. Rendering happens here so that nothing downstream has to
    remember that a validator's output is attacker-controlled bytes.
    """
    from .textsafe import display_bytes

    if not raw:
        return None
    truncated = len(raw) > OUTPUT_BUDGET_BYTES
    tail = raw[-OUTPUT_BUDGET_BYTES:]
    rendered = "\n".join(
        display_bytes(line) for line in tail.split(b"\n")
    ).strip()
    if not rendered:
        return None
    if truncated:
        rendered = "[earlier output not retained]\n" + rendered
    return rendered
