"""Doctor's finding vocabulary.

A finding has a stable machine identity - its `code` - and a human summary.
The prose is not the identity: it may be reworded without breaking a consumer,
and a consumer that matches on prose is doing it wrong.

Doctor's four states are its own. They are deliberately not the task receipt
verdicts `REVIEWABLE`, `INCOMPLETE` and `NOT_REVIEWABLE`, which adjudicate
whether a unit of work can be reviewed. Doctor adjudicates nothing; it
describes a repository on first contact.

    OK           the condition was determined and needs no attention.
                 Doctor emits no finding for an OK condition; silence in the
                 findings list is what OK looks like.

    FINDING      the condition was determined and is worth the user's
                 attention, because it changes what AIQE can later do here.

    UNKNOWN      the condition could not be determined inside Doctor's
                 first-contact safety boundary. This is a real result, not a
                 failure to produce one, and it is never rendered as a pass.

    UNSUPPORTED  the condition is one AIQE does not support, such that the
                 operation cannot safely proceed.
"""

OK = "OK"
FINDING = "FINDING"
UNKNOWN = "UNKNOWN"
UNSUPPORTED = "UNSUPPORTED"

STATES = (OK, FINDING, UNKNOWN, UNSUPPORTED)

#: Ranking used only for stable output ordering. It is not a severity score,
#: and Doctor publishes no aggregate number derived from it.
_STATE_ORDER = {UNSUPPORTED: 0, UNKNOWN: 1, FINDING: 2, OK: 3}


class Finding(object):
    """One repository-specific observation."""

    __slots__ = ("code", "state", "summary")

    def __init__(self, code, state, summary):
        if state not in STATES:
            raise ValueError("unknown Doctor state %r" % (state,))
        self.code = code
        self.state = state
        self.summary = summary

    def as_dict(self):
        return {"code": self.code, "state": self.state, "summary": self.summary}

    def __repr__(self):
        return "Finding(%r, %r)" % (self.code, self.state)


def sort_key(finding):
    """Deterministic ordering: unresolved first, then by code.

    Sorting by code within a state means the same repository always renders
    the same bytes, which is what makes the JSON output diffable and the
    human output stable enough to screenshot.
    """
    return (_STATE_ORDER[finding.state], finding.code)


# --- Repository ------------------------------------------------------------

REPOSITORY_ABSENT = "REPOSITORY_ABSENT"
REPOSITORY_BARE = "REPOSITORY_BARE"
REPOSITORY_UNBORN_HEAD = "REPOSITORY_UNBORN_HEAD"
HEAD_DETACHED = "HEAD_DETACHED"
GIT_UNAVAILABLE = "GIT_UNAVAILABLE"
GIT_VERSION_UNKNOWN = "GIT_VERSION_UNKNOWN"
REPOSITORY_TOPOLOGY_UNRESOLVED = "REPOSITORY_TOPOLOGY_UNRESOLVED"

# --- Working state ---------------------------------------------------------

WORKING_STATE_UNKNOWN = "WORKING_STATE_UNKNOWN"
WORKING_STATE_UNSTAGED_UNKNOWN = "WORKING_STATE_UNSTAGED_UNKNOWN"
UNMERGED_PATHS_PRESENT = "UNMERGED_PATHS_PRESENT"

# --- Topology --------------------------------------------------------------

LINKED_WORKTREE = "LINKED_WORKTREE"
SPARSE_CHECKOUT_ACTIVE = "SPARSE_CHECKOUT_ACTIVE"
SPARSE_CHECKOUT_UNRESOLVED = "SPARSE_CHECKOUT_UNRESOLVED"

# --- Operations in progress ------------------------------------------------

OPERATION_MERGE_IN_PROGRESS = "OPERATION_MERGE_IN_PROGRESS"
OPERATION_REBASE_IN_PROGRESS = "OPERATION_REBASE_IN_PROGRESS"
OPERATION_CHERRY_PICK_IN_PROGRESS = "OPERATION_CHERRY_PICK_IN_PROGRESS"
OPERATION_REVERT_IN_PROGRESS = "OPERATION_REVERT_IN_PROGRESS"
OPERATION_BISECT_IN_PROGRESS = "OPERATION_BISECT_IN_PROGRESS"

# --- Git policy and risk signals -------------------------------------------

GIT_CONFIG_UNREADABLE = "GIT_CONFIG_UNREADABLE"
GIT_CONFIG_INCLUDE_UNRESOLVED = "GIT_CONFIG_INCLUDE_UNRESOLVED"
GIT_HOOKS_PATH_CONFIGURED = "GIT_HOOKS_PATH_CONFIGURED"
GIT_HOOKS_PRESENT = "GIT_HOOKS_PRESENT"
COMMIT_SIGNING_CONFIGURED = "COMMIT_SIGNING_CONFIGURED"
CHECKIN_FILTER_CONFIGURED = "CHECKIN_FILTER_CONFIGURED"
TRACKED_GITATTRIBUTES = "TRACKED_GITATTRIBUTES"
FSMONITOR_CONFIGURED = "FSMONITOR_CONFIGURED"
EXECUTABLE_ALIAS_CONFIGURED = "EXECUTABLE_ALIAS_CONFIGURED"

# --- Agent surface ---------------------------------------------------------

AGENT_CONFIG_UNREADABLE = "AGENT_CONFIG_UNREADABLE"
CLAUDE_PERMISSIONS_BROAD = "CLAUDE_PERMISSIONS_BROAD"
CODEX_PERMISSIONS_BROAD = "CODEX_PERMISSIONS_BROAD"

#: Every code Doctor can emit. The test suite asserts that the codes actually
#: emitted are a subset of this set, so a code cannot be introduced by a
#: stray string literal without being declared here.
ALL_CODES = frozenset(
    {
        REPOSITORY_ABSENT,
        REPOSITORY_BARE,
        REPOSITORY_UNBORN_HEAD,
        HEAD_DETACHED,
        GIT_UNAVAILABLE,
        GIT_VERSION_UNKNOWN,
        REPOSITORY_TOPOLOGY_UNRESOLVED,
        WORKING_STATE_UNKNOWN,
        WORKING_STATE_UNSTAGED_UNKNOWN,
        UNMERGED_PATHS_PRESENT,
        LINKED_WORKTREE,
        SPARSE_CHECKOUT_ACTIVE,
        SPARSE_CHECKOUT_UNRESOLVED,
        OPERATION_MERGE_IN_PROGRESS,
        OPERATION_REBASE_IN_PROGRESS,
        OPERATION_CHERRY_PICK_IN_PROGRESS,
        OPERATION_REVERT_IN_PROGRESS,
        OPERATION_BISECT_IN_PROGRESS,
        GIT_CONFIG_UNREADABLE,
        GIT_CONFIG_INCLUDE_UNRESOLVED,
        GIT_HOOKS_PATH_CONFIGURED,
        GIT_HOOKS_PRESENT,
        COMMIT_SIGNING_CONFIGURED,
        CHECKIN_FILTER_CONFIGURED,
        TRACKED_GITATTRIBUTES,
        FSMONITOR_CONFIGURED,
        EXECUTABLE_ALIAS_CONFIGURED,
        AGENT_CONFIG_UNREADABLE,
        CLAUDE_PERMISSIONS_BROAD,
        CODEX_PERMISSIONS_BROAD,
    }
)
