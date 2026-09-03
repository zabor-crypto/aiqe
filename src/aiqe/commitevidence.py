"""The one local record of an AIQE completion commit, and what it may hold.

One record, for one task, written once. Not a history, for the same reason
check evidence is not a history: the question a receipt answers is "is this
true now", and a table of what was true at various past moments invites the
answer "it passed on Tuesday".

What the record holds is allowlisted, and the allowlist is the interesting
part. Locally, a commit identifier is exactly the right thing to keep: the
user is standing in that repository, and a receipt that would not tell them
which commit it is about would be useless to them. In the **shareable**
receipt the same identifier is an inventory - it names a commit, which names a
branch, which names a project - so the default receipt carries none of it.

Kept here, and only here:

```
task id, timestamps, AIQE version
parent commit and created commit
expected and actual changed pathsets
expected and actual owned tree state
foreign staged structured delta, before and after, and their digests
the commit-policy preflight results
reason identifiers
```

Deliberately absent, here as everywhere: the repository name, the remote, the
branch, the worktree location, the raw commit message, the environment, and
any validator output. The commit message is user-supplied data that would end
up in a shareable artifact by way of a local one, and nothing needs it.
"""

import json

from . import taskstate

#: Bump when a reader of an older record would misread a newer one. Local
#: internal state, not a public integration surface.
COMMIT_EVIDENCE_SCHEMA_VERSION = 1

COMMIT_FILE_NAME = "commit.json"


def build_record(
    task_record,
    aiqe_version,
    parent_sha,
    commit_sha,
    expected,
    expected_changed,
    actual_changed,
    committed,
    foreign_pre,
    foreign_post,
    preflight,
    result,
    timestamp,
):
    """Assemble the commit evidence record. Every field is on the allowlist."""
    import base64

    from . import checkin

    return {
        "schema_version": COMMIT_EVIDENCE_SCHEMA_VERSION,
        "aiqe_version": aiqe_version,
        "task_id": task_record["task_id"],
        "committed_at": timestamp,
        "parent_sha": parent_sha,
        "commit_sha": commit_sha,
        "owned_expected": [entry.as_record() for entry in expected],
        "expected_changed_paths_b64": sorted(
            base64.b64encode(path).decode("ascii") for path in expected_changed
        ),
        "actual_changed_paths_b64": sorted(
            base64.b64encode(path).decode("ascii") for path in actual_changed
        ),
        "owned_committed": [
            {
                "path_b64": base64.b64encode(path).decode("ascii"),
                "kind": kind,
                "blob": blob.decode("ascii", "replace") if blob else None,
                "mode": mode.decode("ascii", "replace") if mode else None,
            }
            for path, (kind, blob, mode) in sorted(committed.items())
        ],
        "foreign_staged_pre": checkin.delta_record(foreign_pre),
        "foreign_staged_post": checkin.delta_record(foreign_post),
        "foreign_staged_pre_digest": checkin.delta_digest(foreign_pre),
        "foreign_staged_post_digest": checkin.delta_digest(foreign_post),
        "preflight": dict(preflight),
        "push_performed_by_aiqe": False,
        "result": dict(result),
    }


def write(state_directory, record):
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    taskstate.write_local_file(state_directory, COMMIT_FILE_NAME, payload)


def remove(state_directory):
    return taskstate.remove_local_file(state_directory, COMMIT_FILE_NAME)


def read(state_directory, task_id=None):
    """The commit evidence for the active task, or None.

    A record written under a different schema, or belonging to a different
    task, is not read and is not migrated. A new task never inherits an old
    task's completion commit.
    """
    raw = taskstate.read_local_file(state_directory, COMMIT_FILE_NAME)
    if raw is None:
        return None
    try:
        record = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("schema_version") != COMMIT_EVIDENCE_SCHEMA_VERSION:
        return None
    if task_id is not None and record.get("task_id") != task_id:
        return None
    return record
