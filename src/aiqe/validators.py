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

Output is **drained incrementally into a fixed-size tail**, never buffered
whole and truncated afterwards. A validator may be buggy or hostile and emit
gigabytes; the memory AIQE spends on it must not be a function of how much it
decided to print. The drain is also what stops the child deadlocking on a full
pipe, so it runs for the whole lifetime of the process rather than only at the
end.

What AIQE does **not** claim about a validator it runs: no sandbox, no
filesystem restriction, no network restriction. It runs as the user, with the
user's environment, and can do anything the user's shell can do. That is
stated to the user before consent is asked for, because it is the only
honest basis on which to ask.

The termination claim is bounded in the same spirit, and is worth stating
exactly because the tempting sentence is wrong:

> On timeout, AIQE terminates the validator process group it created.

Not "every descendant", and not "the process tree". A child that deliberately
calls `setsid` leaves that group and is outside the mechanism. Nothing here
supervises a process tree, and adding a supervisor would be building the
sandbox this product says it does not have.
"""

import hashlib
import json
import os
import selectors
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
#:
#: This is a retention budget *and* a memory budget. Output is drained into a
#: tail of this size as it arrives, so peak accumulation is the budget plus one
#: read buffer per stream - not the total the validator emitted.
OUTPUT_BUDGET_BYTES = 8192

#: How much is read from a ready pipe at a time. Small and fixed: it is the
#: only term besides the budget in AIQE's memory use during a validator run.
READ_CHUNK_BYTES = 8192

#: How long to keep draining after the process group has been killed. Bounded,
#: because a detached descendant can hold the inherited pipe open forever and
#: the timeout is a promise about how long a check can take.
DRAIN_SECONDS = 5.0

#: The retention policy, named so that output and documentation cannot drift
#: apart about which end of the stream is kept.
RETENTION_POLICY = "tail"

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


class _BoundedTail(object):
    """A fixed-size tail of a byte stream, and a count of what went past.

    The whole reason this class exists instead of a `bytes` accumulator: a
    validator's output is not bounded by anything AIQE controls, so the buffer
    it lands in has to be. Chunks are appended and the front is dropped, so the
    memory held is the budget plus at most one read, whatever the validator
    emits.

    `total` is a counter, not a buffer. It is what lets the rendering say that
    earlier output existed without having kept it.
    """

    __slots__ = ("_buffer", "_budget", "total")

    def __init__(self, budget):
        self._buffer = bytearray()
        self._budget = budget
        self.total = 0

    def add(self, chunk):
        self.total += len(chunk)
        self._buffer += chunk
        excess = len(self._buffer) - self._budget
        if excess > 0:
            del self._buffer[:excess]

    @property
    def truncated(self):
        return self.total > self._budget

    def value(self):
        return bytes(self._buffer)


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
            # Its own process group, so that a timeout has something to
            # terminate other than the single process AIQE started. A script's
            # children inherit its pipes, and killing only the top of that
            # leaves them holding the pipe open - measured, not assumed: a
            # `sh -c "sleep 30"` under a one-second timeout took thirty
            # seconds before this line existed.
            #
            # This bounds the group AIQE created. It does not bound a
            # descendant that deliberately leaves the group, and nothing here
            # pretends otherwise.
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

    stdout, stderr, timed_out = _drain(process, validator.timeout)
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
            stdout_tail=_render(stdout),
            stderr_tail=_render(stderr),
        )

    if process.returncode == 0:
        # Output from a passing validator is discarded. It is not evidence of
        # anything the exit status did not already say, and retaining it is
        # how a local evidence file quietly acquires the contents of a log.
        # It was drained rather than ignored, because an undrained pipe is how
        # a validator deadlocks instead of passing.
        return Outcome(
            validator, digest, PASS, exit_code=0, duration_ms=duration
        )

    return Outcome(
        validator,
        digest,
        FAIL,
        exit_code=process.returncode,
        duration_ms=duration,
        stdout_tail=_render(stdout),
        stderr_tail=_render(stderr),
    )


def _drain(process, timeout):
    """Read both pipes into bounded tails until exit, or until the timeout.

    Returns (stdout tail, stderr tail, timed out).

    Three jobs at once, which is why it is one loop rather than three:

    **Keep the child alive.** A pipe nobody reads fills and blocks the writer
    forever. `communicate()` avoids that by reading everything into memory,
    which is precisely what must not happen here.

    **Keep memory bounded.** Each chunk goes into a fixed-size tail, so what is
    held is the budget plus one read buffer per stream, whatever the validator
    emits.

    **Keep the wall clock bounded.** Every wait has a deadline. After the
    timeout the process group is terminated and draining continues briefly, so
    that a failing validator's last words survive - but only briefly, because a
    descendant that left the group can hold the inherited pipe open forever and
    the timeout is a promise about how long a check can take.
    """
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    tails = {
        stdout_fd: _BoundedTail(OUTPUT_BUDGET_BYTES),
        stderr_fd: _BoundedTail(OUTPUT_BUDGET_BYTES),
    }

    selector = selectors.DefaultSelector()
    for stream in (process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)

    deadline = time.monotonic() + timeout
    try:
        timed_out = bool(_pump(selector, tails, deadline))

        if not timed_out:
            # Both pipes reached end of file, which is not the same as the
            # process having been reaped. The kernel closes the descriptors
            # when the process exits and `waitpid` reports a moment later, and
            # on a loaded machine that gap is wide enough to observe - a
            # single non-blocking poll here reported "still running" for a
            # script that had already exited 0, and the check called it a
            # timeout. Waiting inside the remaining budget closes the gap,
            # while a validator that closed its pipes and kept running still
            # times out.
            try:
                process.wait(timeout=max(deadline - time.monotonic(), 0.0))
            except subprocess.TimeoutExpired:
                timed_out = True

        if timed_out:
            _terminate(process)
            _pump(selector, tails, time.monotonic() + DRAIN_SECONDS)
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    try:
        process.wait(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired:
        # Left for the operating system to reap. Waiting further would trade a
        # bounded check for an unbounded one, which is the trade this whole
        # function exists to refuse.
        pass

    return tails[stdout_fd], tails[stderr_fd], timed_out


def _pump(selector, tails, deadline):
    """Drain every registered stream until end of file or the deadline.

    Returns the descriptors still open.
    """
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        for key, _events in selector.select(timeout=min(remaining, 0.1)):
            descriptor = key.fileobj.fileno()
            try:
                chunk = os.read(descriptor, READ_CHUNK_BYTES)
            except BlockingIOError:
                continue
            except OSError:
                # The pipe went away underneath us. That is end of file, not a
                # failure of the check.
                selector.unregister(key.fileobj)
                continue
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            tails[descriptor].add(chunk)
    return list(selector.get_map())


def _terminate(process):
    """Terminate the process group AIQE created for this validator.

    The group, not the process, so that a script's children go with it. Falls
    back to killing the process alone if the group is already gone, which is a
    race rather than an error.

    What this does **not** do is bound every descendant. A child that calls
    `setsid` is in a different session and survives, and AIQE says so rather
    than implying a containment it does not provide. Delivering that guarantee
    would mean supervising a process tree, which is the sandbox this product
    explicitly does not claim to be.
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


def _render(tail):
    """Render an already-bounded tail as terminal-safe text.

    The tail rather than the head: a failing command's last lines are the ones
    that say why. Nothing is truncated here - the bound was applied while the
    output was being read, which is the point - so this only turns bytes into
    something safe to print.

    Rendering happens at this boundary so that nothing downstream has to
    remember that a validator's output is attacker-controlled bytes.
    """
    from .textsafe import display_bytes

    raw = tail.value()
    if not raw:
        return None
    rendered = "\n".join(
        display_bytes(line) for line in raw.split(b"\n")
    ).strip()
    if not rendered:
        return None
    if tail.truncated:
        rendered = "[earlier output not retained]\n" + rendered
    return rendered
