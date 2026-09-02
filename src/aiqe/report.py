"""Rendering for Doctor results.

Two renderings of one report. Neither invents information the report does not
hold, and neither discloses more than the diagnosis requires.

What is deliberately absent from both: the branch name, the commit
identifier, the remote URL, the worktree path, the home directory and the
username. A Doctor result is the thing users paste into an issue and put in a
screenshot. It carries counts, booleans and categories, and the local
diagnosis does not need the rest.

There is no safety score. There is no aggregate pass banner. A clean
repository renders as an absence of findings, because an assurance layer that
prints a green shield has started making a claim it did not earn.
"""

import json
import textwrap

from . import findings as f

#: Bump only when the shape changes in a way an existing consumer would
#: misread. Adding a new finding code is not such a change: codes are data.
SCHEMA_VERSION = 1

_WIDTH = 78
_LABEL_WIDTH = 15


def render_json(report, aiqe_version):
    """Deterministic machine-readable output.

    Keys are sorted, findings are ordered by state and then by code, and no
    value depends on wall-clock time, environment or run order. The same
    repository state renders the same bytes.
    """
    document = {
        "schema_version": SCHEMA_VERSION,
        "aiqe_version": aiqe_version,
        "command": "doctor",
        "result": report.result,
        "exit_code": report.exit_code(),
        "git": {
            "available": report.git["available"],
            "version": report.git["version"],
        },
        "repository": {
            "detected": report.repository["detected"],
            "kind": report.repository["kind"],
            "head": report.repository["head"],
        },
        "topology": {
            "linked_worktree": report.topology["linked_worktree"],
            "sparse_checkout": report.topology["sparse_checkout"],
        },
        "operations_in_progress": list(report.operations),
        "working_state": {
            "determined": report.working_state["determined"],
            "staged": report.working_state["staged"],
            "unstaged": report.working_state["unstaged"],
            "untracked": report.working_state["untracked"],
            "unmerged": report.working_state["unmerged"],
            "submodule_worktrees_excluded": report.working_state[
                "submodule_worktrees_excluded"
            ],
        },
        "aiqe": {"config_present": report.aiqe["config_present"]},
        "commit_policy": dict(report.commit_policy),
        "agent_surface": dict(report.agent_surface),
        "findings": [finding.as_dict() for finding in report.sorted_findings()],
        "state_counts": report.state_counts(),
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def render_human(report):
    """Compact terminal output.

    No colour and no box drawing. Colour would be a runtime dependency or a
    hand-rolled escape-code layer, and neither buys anything a stable layout
    does not already give: the state word carries the emphasis, and it is the
    unresolved states that sort to the top.
    """
    lines = ["AIQE DOCTOR", ""]
    for label, value in _summary_rows(report):
        lines.append("  %-*s %s" % (_LABEL_WIDTH, label, value))

    ordered = report.sorted_findings()
    if ordered:
        for finding in ordered:
            lines.append("")
            lines.append("  %-12s %s" % (finding.state, finding.code))
            for wrapped in textwrap.wrap(finding.summary, width=_WIDTH - 6):
                lines.append("      " + wrapped)
        lines.append("")
        lines.append("  " + _tally(report))
    else:
        lines.append("")
        lines.append("  No findings.")

    lines.append("")
    return "\n".join(lines)


def _summary_rows(report):
    rows = [("Repository", _repository_row(report))]

    if not report.repository["detected"]:
        return rows
    if report.repository["kind"] == "bare":
        return rows

    rows.append(("Git state", _git_state_row(report)))
    rows.append(("Topology", _topology_row(report)))
    rows.append(("Operations", _operations_row(report)))
    rows.append(("AIQE config", "present" if report.aiqe["config_present"] else "absent"))
    rows.append(("Agent surface", _agent_row(report)))
    rows.append(("Commit policy", _commit_policy_row(report)))
    return rows


def _repository_row(report):
    if not report.git["available"]:
        return "Git unavailable"

    version = report.git["version"]
    git_part = ("git " + version) if version else "git version unknown"

    if not report.repository["detected"]:
        kind = "none detected"
    elif report.repository["kind"] == "bare":
        kind = "bare repository"
    elif report.topology["linked_worktree"]:
        kind = "linked worktree"
    else:
        kind = "ordinary worktree"
    return _join([kind, git_part])


def _git_state_row(report):
    head = report.repository["head"]
    parts = [
        {
            "branch": "on a branch",
            "detached": "detached HEAD",
            "unborn": "no commits yet",
        }.get(head, "HEAD unresolved")
    ]

    state = report.working_state
    for label, key in (("staged", "staged"), ("unstaged", "unstaged"), ("untracked", "untracked")):
        value = state[key]
        parts.append("%s %s" % (("?" if value is None else value), label))
    if state["unmerged"]:
        parts.append("%d unmerged" % state["unmerged"])
    if state["submodule_worktrees_excluded"]:
        # The qualification belongs next to the numbers it qualifies, not in a
        # footnote: these counts do not include submodule worktree changes.
        parts.append("submodule worktrees not counted")
    return _join(parts)


def _topology_row(report):
    parts = [
        "linked worktree" if report.topology["linked_worktree"] else "single worktree",
        {
            "on": "sparse checkout on",
            "off": "sparse checkout off",
            "unknown": "sparse checkout unresolved",
        }[report.topology["sparse_checkout"]],
    ]
    return _join(parts)


def _operations_row(report):
    if not report.operations:
        return "none in progress"
    names = {
        f.OPERATION_MERGE_IN_PROGRESS: "merge",
        f.OPERATION_REBASE_IN_PROGRESS: "rebase",
        f.OPERATION_CHERRY_PICK_IN_PROGRESS: "cherry-pick",
        f.OPERATION_REVERT_IN_PROGRESS: "revert",
        f.OPERATION_BISECT_IN_PROGRESS: "bisect",
    }
    return _join([names.get(code, code) + " in progress" for code in report.operations])


def _agent_row(report):
    surface = report.agent_surface
    parts = []
    for label, present_key, permission_key in (
        ("Claude Code", "claude_config_present", "claude_permissions"),
        ("Codex", "codex_config_present", "codex_permissions"),
    ):
        if not surface[present_key]:
            parts.append(label + " absent")
        elif surface[permission_key] == "broad":
            parts.append(label + " present, unconstrained")
        elif surface[permission_key] == "unknown":
            parts.append(label + " present, permissions unknown")
        else:
            parts.append(label + " present")
    return _join(parts)


def _commit_policy_row(report):
    policy = report.commit_policy
    parts = []
    if policy["hooks_present"]:
        parts.append("hooks installed")
    if policy["hooks_path_configured"]:
        parts.append("custom hooks path")
    if policy["signing_configured"]:
        parts.append("signing configured")
    if policy["checkin_filter_configured"]:
        parts.append("check-in filter configured")
    if policy["tracked_gitattributes"]:
        parts.append("tracked .gitattributes")
    if policy["config_include_present"]:
        parts.append("config includes unresolved")
    if not policy["local_config_readable"]:
        parts.append("config unreadable")
    if not parts:
        return "no local policy signals"
    return _join(parts)


def _tally(report):
    counts = report.state_counts()
    parts = []
    for state, singular in (
        (f.UNSUPPORTED, "unsupported"),
        (f.UNKNOWN, "unknown"),
        (f.FINDING, "finding"),
    ):
        count = counts[state]
        if not count:
            continue
        if state is f.FINDING:
            parts.append("%d %s" % (count, singular if count == 1 else "findings"))
        else:
            parts.append("%d %s" % (count, singular))
    return _join(parts)


def _join(parts):
    return " · ".join(parts)
