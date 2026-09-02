"""The current check evidence for the active task, and whether it is still true.

One record, for one task, replaced whole by each check. Not a history.

A history would be the natural thing to build and the wrong thing to have. The
question a receipt answers is "is this true *now*", and a database of what was
true at various past moments does not help answer it - it invites the answer
"it passed on Tuesday", which is precisely the claim this product exists to
refuse. There is one active record; the next check replaces it atomically; and
ending a task removes it, because evidence about an abandoned unit of work is
not evidence about anything.

Recorded consent is the deliberate exception: it survives task end, because
consenting to run a command is a statement about the command rather than about
one task.

**Freshness is decided by bounded authority, never by re-running anything.**
Four things, and only these four:

```
owned path binding             the owned pathset's content, states and modes
HEAD                           the commit the work sits on
aiqe.toml                      the raw configuration bytes
validator definition digests   what the validators actually are
```

If any of them differs from what the check recorded, the evidence describes a
state that no longer exists and the receipt says `STALE`. There is no
whole-worktree fingerprint: a foreign file changing is not a statement about
this task's owned scope, and hashing somebody's whole repository to find that
out would make a receipt cost more than the check did.

The record holds no repository name, no remote, no branch, no absolute path
and no worktree location. It is machine-local, it is keyed by a token that
names no repository, and the fields it keeps are the ones a later operation
must recompute against.
"""

import json

from . import taskstate

#: Bump when a reader of an older record would misread a newer one. Local
#: internal state, not a public integration surface.
EVIDENCE_SCHEMA_VERSION = 1

CHECK_FILE_NAME = "check.json"

STALE_OWNED_CONTENT = "STALE_OWNED_CONTENT"
STALE_HEAD = "STALE_HEAD"
STALE_CONFIG = "STALE_CONFIG"
STALE_VALIDATOR_DEFINITION = "STALE_VALIDATOR_DEFINITION"

#: Every staleness trigger, in the order a receipt reports them.
STALENESS_REASONS = (
    STALE_OWNED_CONTENT,
    STALE_HEAD,
    STALE_CONFIG,
    STALE_VALIDATOR_DEFINITION,
)


class Authority(object):
    """The bounded state a check's conclusion depends on.

    Measured immediately before validators run and again immediately after, so
    that a validator which edited the very thing it was checking cannot leave
    behind evidence that calls itself current. Recomputed by `receipt` to
    decide freshness.
    """

    __slots__ = ("head_sha", "config_digest", "binding_digest", "definitions")

    def __init__(self, head_sha, config_digest, binding_digest, definitions):
        self.head_sha = head_sha
        self.config_digest = config_digest
        self.binding_digest = binding_digest
        #: {validator id: definition digest}
        self.definitions = dict(definitions)

    def as_record(self):
        return {
            "head_sha": self.head_sha,
            "config_digest": self.config_digest,
            "owned_binding_digest": self.binding_digest,
            "validator_definitions": dict(self.definitions),
        }

    @classmethod
    def from_record(cls, record):
        return cls(
            record.get("head_sha"),
            record.get("config_digest"),
            record.get("owned_binding_digest"),
            record.get("validator_definitions") or {},
        )

    def differences(self, other):
        """Which bounded authority differs. Empty means still current."""
        reasons = []
        if self.binding_digest != other.binding_digest:
            reasons.append(STALE_OWNED_CONTENT)
        if self.head_sha != other.head_sha:
            reasons.append(STALE_HEAD)
        if self.config_digest != other.config_digest:
            reasons.append(STALE_CONFIG)
        if self.definitions != other.definitions:
            reasons.append(STALE_VALIDATOR_DEFINITION)
        return tuple(reasons)


def build_record(
    task_record,
    aiqe_version,
    config,
    authority,
    owned_states,
    classification,
    outcomes,
    coverage_results,
    result,
    foreign_staged_count,
    timestamp,
):
    """Assemble the local evidence record.

    Every field here is on the allowlist: task identity, timestamps, local
    HEADs, the owned pathset and its binding, classification, validator
    definitions and outcomes, the coverage arithmetic, and version identity.
    Deliberately absent: the environment, the validator process environment,
    file contents, and any unbounded output. Validator output tails are
    bounded and local-only, and never reach a shareable receipt.
    """
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "aiqe_version": aiqe_version,
        "config_schema": config.schema,
        "task_id": task_record["task_id"],
        "label": task_record.get("label"),
        "checked_at": timestamp,
        "start_head_sha": task_record["start_head_sha"],
        "authority": authority.as_record(),
        "owned_binding": [state.as_record() for state in owned_states],
        "owned_pathset_digest": task_record["owned_pathset_digest"],
        "changed_owned_count": sum(1 for state in owned_states if state.changed),
        "foreign_staged_count": foreign_staged_count,
        "classification": classification.as_record(),
        "validators": [outcome.as_record() for outcome in outcomes],
        "coverage": [result.as_record() for result in coverage_results],
        "result": result,
    }


def write(state_directory, record):
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    taskstate.write_local_file(state_directory, CHECK_FILE_NAME, payload)


def remove(state_directory):
    return taskstate.remove_local_file(state_directory, CHECK_FILE_NAME)


def read(state_directory, task_id=None):
    """The current check evidence, or None.

    A record written under a different evidence schema, or belonging to a
    different task, is not read. It is not migrated either: this is local
    pre-release state, and a migration framework for it would be machinery
    where a sentence telling the user to check again would do.
    """
    raw = taskstate.read_local_file(state_directory, CHECK_FILE_NAME)
    if raw is None:
        return None
    try:
        record = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        return None
    if task_id is not None and record.get("task_id") != task_id:
        return None
    return record
