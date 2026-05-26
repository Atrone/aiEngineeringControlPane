"""Mutation helpers shared by state task and run lifecycle code."""

from copy import deepcopy
from typing import Any, Dict, List, Mapping


def build_issue_snapshot(run: Mapping[str, Any]) -> Dict[str, Any]:
    """Builds the issue context used when starting an existing run."""

    snapshot = deepcopy(run.get("_issueSnapshot"))

    if snapshot:
        # Prefer the issue snapshot captured when the task was created.
        return snapshot

    # Return a fallback issue record for seeded or legacy runs.
    return {
        "id": run["id"],
        "ticket": run["ticket"],
        "title": run["title"],
        "description": run["summary"],
        "status": run["status"],
        "priority": "2",
        "provider": "fallback",
        "assignee": {},
    }


def clear_previous_launch_metadata(run: Dict[str, Any]) -> None:
    """Removes stale live-agent, approval, merge, and pull-request metadata."""

    # Drop cloud-agent-specific metadata before recording the new launch mode.
    run.pop("_cursorAgent", None)
    run.pop("_cursorPromptSummary", None)
    run.pop("_githubCopilotAgent", None)
    run.pop("_githubCopilotPromptSummary", None)

    # Drop review and merge fields because a restarted run needs a fresh lifecycle.
    run.pop("_approvedAt", None)
    run.pop("_approvedBy", None)
    run.pop("_mergedAt", None)
    run.pop("_pullRequestState", None)


def apply_common_run_start(
    run: Dict[str, Any],
    *,
    agent_name: str,
    current_step: str,
    cost: str,
    blockers: List[str],
    execution_mode: str,
    stream_started_at: str,
) -> None:
    """Applies fields shared by every run-start path."""

    # Reset the public run status fields to the beginning of a new attempt.
    run["status"] = "Running"
    run["agent"] = agent_name
    run["currentStep"] = current_step
    run["runtime"] = "00:00"
    run["cost"] = cost
    run["blockers"] = blockers
    run["_streamStartedAt"] = stream_started_at
    run["_executionMode"] = execution_mode

    # Remove stale metadata from any previous attempt.
    clear_previous_launch_metadata(run)
