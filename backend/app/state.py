"""In-memory application state that mixes live integrations with safe fallbacks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Mapping, Optional

from fastapi import HTTPException
from fastapi import status

from app.config import Settings
from app.mock_data import POLICY_RULES
from app.mock_data import RUN_SUMMARIES
from app.providers import CursorAgentError
from app.providers import fetch_github_pull_request_status
from app.providers import get_cursor_agent
from app.providers import get_integration_statuses
from app.providers import launch_cursor_agent
from app.providers import list_github_repositories
from app.providers import list_jira_issues
from app.providers import list_linear_issues
from app.providers import list_repo_documents
from app.providers import parse_github_pull_request_url
from app.providers import resolve_current_user
from app.providers import summarize_repository_names
from app.providers import update_jira_issue_status
from app.providers import update_linear_issue_status


RUN_STORE: List[Dict[str, Any]] = deepcopy(RUN_SUMMARIES)
STREAM_STEP_SECONDS = 4
# Seconds between reviewer approval and the simulated GitHub PR merge event.
SIMULATED_PR_MERGE_DELAY_SECONDS = 12
# Actor payload used when a GitHub webhook-like event is synthesized in the approval history.
GITHUB_APPROVAL_ACTOR: Dict[str, str] = {
    "name": "GitHub",
    "email": "noreply@github.com",
    "role": "admin",
    "provider": "github",
}
LINEAR_STATUS_IN_PROGRESS = "In Progress"
LINEAR_STATUS_DONE = "Done"
JIRA_STATUS_IN_PROGRESS = "In Progress"
JIRA_STATUS_DONE = "Done"


def _normalize_team_id(team_id: str) -> str:
    """Normalizes a team identifier used for run-lobby isolation."""

    normalized_team_id = str(team_id or "").strip().lower()

    if normalized_team_id:
        # Return the caller-provided team id in canonical lowercase form.
        return normalized_team_id

    # Fall back to the legacy single-user team key for backwards compatibility.
    return "default-team"


def _resolve_team_id_from_headers(headers: Mapping[str, str]) -> str:
    """Resolves the active team id from normalized request headers."""

    # Prefer the explicit team header attached by authenticated session middleware.
    return _normalize_team_id(str(headers.get("x-demo-team-id", "")))


def _run_belongs_to_team(run: Mapping[str, Any], team_id: str) -> bool:
    """Reports whether the run belongs to the requested team."""

    # Compare the run's stored team id with the active request team id.
    return _normalize_team_id(str(run.get("_teamId", ""))) == _normalize_team_id(team_id)


def _list_team_runs(team_id: str) -> List[Dict[str, Any]]:
    """Returns all in-memory runs visible to the requested team."""

    visible_runs: List[Dict[str, Any]] = []

    # Keep only runs whose stored team id matches the active team scope.
    for run in RUN_STORE:
        if _run_belongs_to_team(run, team_id):
            visible_runs.append(run)

    # Return the team-scoped run list while preserving insertion order.
    return visible_runs


def _utc_now() -> datetime:
    """Returns the current UTC time used for live run simulation."""

    # Use a timezone-aware clock so generated timeline timestamps stay consistent.
    return datetime.now(timezone.utc)


def _utc_timestamp() -> str:
    """Builds an ISO timestamp for generated task and approval records."""

    # Return a consistent UTC timestamp for in-memory audit events.
    return _utc_now().isoformat()


def _parse_timestamp(value: Optional[str]) -> datetime:
    """Parses an ISO timestamp into a timezone-aware UTC datetime."""

    if not value:
        # Fall back to the current UTC time when no timestamp is present.
        return _utc_now()

    normalized_value = value.replace("Z", "+00:00")

    try:
        parsed_timestamp = datetime.fromisoformat(normalized_value)
    except ValueError:
        # Fall back to the current UTC time when the stored value is malformed.
        return _utc_now()

    if parsed_timestamp.tzinfo is None:
        # Attach UTC when the stored timestamp did not preserve timezone info.
        return parsed_timestamp.replace(tzinfo=timezone.utc)

    # Normalize all parsed timestamps back into UTC.
    return parsed_timestamp.astimezone(timezone.utc)


def _parse_runtime_seconds(runtime_value: str) -> int:
    """Converts an mm:ss runtime string into total seconds."""

    minute_text, separator, second_text = runtime_value.partition(":")

    if not separator:
        # Fall back to zero seconds when the runtime does not follow the expected format.
        return 0

    try:
        # Convert the minute and second fragments into a single second count.
        return max(0, (int(minute_text) * 60) + int(second_text))
    except ValueError:
        # Fall back to zero seconds when the runtime fragments are not numeric.
        return 0


def _format_runtime(total_seconds: int) -> str:
    """Formats a total second count as an mm:ss string."""

    normalized_seconds = max(0, total_seconds)
    minutes, seconds = divmod(normalized_seconds, 60)

    # Return a consistent mm:ss runtime string for the frontend display.
    return f"{minutes:02d}:{seconds:02d}"


def _format_cursor_agent_runtime(agent: Mapping[str, Any], *, require_nonzero: bool) -> str:
    """Formats the elapsed runtime for a Cursor Cloud Agent payload."""

    # Parse the provider creation timestamp so Cursor-backed runs get a live runtime.
    created_at = _parse_timestamp(str(agent.get("createdAt", "")))
    elapsed_seconds = max(0, int((_utc_now() - created_at).total_seconds()))

    if require_nonzero:
        # Finished review handoffs should not display as a zero-second review runtime.
        elapsed_seconds = max(1, elapsed_seconds)

    # Return the shared mm:ss display string used by dashboard and run-room views.
    return _format_runtime(elapsed_seconds)


def _build_step_timestamp(started_at: datetime, offset_seconds: int) -> str:
    """Builds an ISO timestamp for a simulated run step."""

    # Offset the run start time so every timeline entry has a concrete timestamp.
    return (started_at + timedelta(seconds=offset_seconds)).isoformat()


def _build_static_timepoints(runtime_value: str, count: int) -> List[str]:
    """Builds evenly spaced ISO timestamps for a non-streaming run view."""

    total_items = max(1, count)
    total_seconds = max(total_items - 1, _parse_runtime_seconds(runtime_value))
    started_at = _utc_now() - timedelta(seconds=total_seconds)
    step_span = total_seconds / max(1, total_items - 1)
    timepoints: List[str] = []

    # Spread timestamps across the recorded runtime so static views still feel chronological.
    for index in range(total_items):
        timepoints.append(_build_step_timestamp(started_at, int(round(index * step_span))))

    # Return the generated timestamp list for the caller.
    return timepoints


def _build_stream_plan(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Builds the simulated streaming plan for a live run."""

    evidence = run.get("evidence", {})
    diff_items = list(evidence.get("diff", []))
    test_items = list(evidence.get("tests", []))
    rationale_items = list(evidence.get("rationale", []))
    first_diff = diff_items[0] if diff_items else "Prepared the first implementation pass for the requested scope."
    first_test = test_items[0] if test_items else "Queued validation after the code edit step."
    first_rationale = rationale_items[0] if rationale_items else "The run is building a review package with evidence attached."
    execution_mode = str(run.get("_executionMode", "implement"))
    agent_name = str(run.get("agent", "impl-agent"))
    repo_name = str(run.get("repo", "repo"))
    branch_name = str(run.get("branch", "ai/generated"))

    # Return the ordered step plan used to simulate a live agent run.
    return [
        {
            "id": "accepted",
            "offsetSeconds": 0,
            "title": "Task accepted",
            "detail": f"{agent_name} picked up {run['ticket']} in {execution_mode} mode.",
            "currentStep": "Loading task context",
            "logs": [
                {"level": "info", "source": "orchestrator", "message": f"Queued {run['ticket']} for {agent_name}."},
                {"level": "info", "source": "agent", "message": f"Loading repository context for {repo_name} on {branch_name}."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Scoped the live run",
                        "detail": f"Execution mode {execution_mode} was selected for {repo_name}.",
                    },
                ],
            },
        },
        {
            "id": "plan",
            "offsetSeconds": STREAM_STEP_SECONDS,
            "title": "Plan generated",
            "detail": "Agent reviewed the task context and drafted an implementation approach.",
            "currentStep": "Drafting plan and selecting files",
            "logs": [
                {"level": "info", "source": "agent", "message": "Summarized acceptance criteria and matched nearby files."},
                {"level": "info", "source": "planner", "message": "Prepared an execution plan with diff, validation, and review milestones."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Planning rationale captured",
                        "detail": first_rationale,
                    },
                ],
            },
        },
        {
            "id": "edit",
            "offsetSeconds": STREAM_STEP_SECONDS * 2,
            "title": "Files edited",
            "detail": "Implementation changes were written to the working tree.",
            "currentStep": "Editing files and collecting diff evidence",
            "logs": [
                {"level": "info", "source": "agent", "message": "Applied the first code change set to the target branch."},
                {"level": "success", "source": "git", "message": "Working tree updated without policy violations."},
            ],
            "evidence": {
                "diff": [
                    {
                        "summary": "Working diff captured",
                        "detail": first_diff,
                    },
                ],
            },
        },
        {
            "id": "tests",
            "offsetSeconds": STREAM_STEP_SECONDS * 3,
            "title": "Validation running",
            "detail": "The agent started validation and is collecting proof for reviewer handoff.",
            "currentStep": "Running validation and summarizing evidence",
            "logs": [
                {"level": "info", "source": "runner", "message": "Started the validation command group for the current changes."},
                {"level": "success", "source": "runner", "message": first_test},
            ],
            "evidence": {
                "tests": [
                    {
                        "summary": "Validation evidence captured",
                        "detail": first_test,
                    },
                ],
            },
        },
        {
            "id": "handoff",
            "offsetSeconds": STREAM_STEP_SECONDS * 4,
            "title": "Review package ready",
            "detail": "The run finished streaming and is ready for human review.",
            "currentStep": "Review package ready",
            "logs": [
                {"level": "success", "source": "agent", "message": "Review bundle assembled with diff, tests, and rationale tabs."},
                {"level": "info", "source": "orchestrator", "message": "Streaming paused while awaiting a reviewer decision."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Reviewer handoff prepared",
                        "detail": "The agent packaged the run timeline, streamed logs, and evidence for approval.",
                    },
                ],
            },
        },
    ]


def _build_evidence_entries(
    items: List[str],
    *,
    tab_name: str,
    runtime_value: str,
    status: str,
) -> List[Dict[str, str]]:
    """Builds timestamped evidence entries for a static run."""

    entries: List[Dict[str, str]] = []
    timepoints = _build_static_timepoints(runtime_value, max(1, len(items)))

    # Convert each plain evidence string into a richer entry used by the tabbed UI.
    for index, item in enumerate(items):
        entries.append(
            {
                "id": f"{tab_name}-{index}",
                "timestamp": timepoints[index],
                "summary": f"{tab_name.title()} evidence {index + 1}",
                "detail": item,
                "status": status,
            }
        )

    # Return the evidence entry list for the requested tab.
    return entries


def _build_static_timeline(run: Dict[str, Any]) -> List[Dict[str, str]]:
    """Builds a completed timeline for a non-streaming run."""

    evidence = run.get("evidence", {})
    rationale_items = list(evidence.get("rationale", []))
    diff_items = list(evidence.get("diff", []))
    test_items = list(evidence.get("tests", []))
    timeline_templates = [
        {
            "id": "created",
            "title": "Task created",
            "detail": "Issue, repository, and policy context were attached to the run.",
        },
        {
            "id": "plan",
            "title": "Plan generated",
            "detail": rationale_items[0] if rationale_items else "The agent planned the requested change.",
        },
        {
            "id": "edit",
            "title": "Files edited",
            "detail": diff_items[0] if diff_items else "Code changes were prepared for review.",
        },
        {
            "id": "validate",
            "title": "Validation completed" if run["status"] in {"Review", "Merged"} else "Validation attempted",
            "detail": test_items[0] if test_items else str(run["currentStep"]),
        },
        {
            "id": "final",
            "title": "Merged"
            if run["status"] == "Merged"
            else "Approved - awaiting merge"
            if run["status"] == "Approved"
            else "Run blocked"
            if run["status"] == "Blocked"
            else "Retry prepared"
            if run["status"] == "Retry"
            else "Review package ready",
            "detail": str(run["currentStep"]),
        },
    ]
    timepoints = _build_static_timepoints(str(run.get("runtime", "00:00")), len(timeline_templates))
    timeline_entries: List[Dict[str, str]] = []

    # Pair each static run step with a timestamp so the execution history still reads chronologically.
    for index, template in enumerate(timeline_templates):
        timeline_entries.append(
            {
                "id": template["id"],
                "title": template["title"],
                "detail": template["detail"],
                "timestamp": timepoints[index],
                "status": "complete",
            }
        )

    # Return the completed timeline for the run.
    return timeline_entries


def _build_static_logs(run: Dict[str, Any]) -> List[Dict[str, str]]:
    """Builds the log stream for a non-streaming run."""

    log_entries: List[Dict[str, str]] = []
    commands = list(run.get("evidence", {}).get("commands", []))
    timepoints = _build_static_timepoints(str(run.get("runtime", "00:00")), max(2, len(commands) + 2))
    status_level = "warning" if run["status"] in {"Blocked", "Retry"} else "success"

    log_entries.append(
        {
            "id": "static-log-start",
            "timestamp": timepoints[0],
            "level": "info",
            "source": "orchestrator",
            "message": f"Loaded run summary for {run['ticket']} in {run['repo']}.",
        }
    )

    # Convert recorded commands into readable log lines for the execution stream panel.
    for index, command in enumerate(commands):
        log_entries.append(
            {
                "id": f"static-log-command-{index}",
                "timestamp": timepoints[min(index + 1, len(timepoints) - 1)],
                "level": "info",
                "source": "runner",
                "message": f"Executed: {command}",
            }
        )

    log_entries.append(
        {
            "id": "static-log-finish",
            "timestamp": timepoints[-1],
            "level": status_level,
            "source": "agent",
            "message": str(run["currentStep"]),
        }
    )

    # Return the static log stream for the task detail view.
    return log_entries


def _build_stream_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the live timeline, log stream, and evidence tabs for a streaming run."""

    started_at = _parse_timestamp(str(run.get("_streamStartedAt", "")))
    step_plan = _build_stream_plan(run)
    elapsed_seconds = max(0, int((_utc_now() - started_at).total_seconds()))
    final_offset = int(step_plan[-1]["offsetSeconds"])
    is_complete = elapsed_seconds >= final_offset
    active_index = 0
    timeline_entries: List[Dict[str, Any]] = []
    log_entries: List[Dict[str, Any]] = []
    evidence_tabs: Dict[str, List[Dict[str, Any]]] = {"diff": [], "tests": [], "rationale": []}

    # Resolve which step should be shown as active for the current elapsed time.
    for index, step in enumerate(step_plan):
        if elapsed_seconds >= int(step["offsetSeconds"]):
            active_index = index

    # Build the timeline, visible logs, and evidence tabs from the revealed stream steps.
    for index, step in enumerate(step_plan):
        if is_complete or index < active_index:
            step_status = "complete"
        elif index == active_index:
            step_status = "complete" if is_complete else "active"
        else:
            step_status = "pending"

        step_timestamp = _build_step_timestamp(started_at, int(step["offsetSeconds"]))
        timeline_entries.append(
            {
                "id": step["id"],
                "title": step["title"],
                "detail": step["detail"],
                "timestamp": step_timestamp,
                "status": step_status,
            }
        )

        if not is_complete and index > active_index:
            # Keep future logs and evidence hidden until the step becomes visible.
            continue

        evidence_status = "captured" if is_complete or index < active_index else "running"

        # Surface every visible step log inside the streamed execution panel.
        for log_index, log in enumerate(step.get("logs", [])):
            log_entries.append(
                {
                    "id": f"{step['id']}-log-{log_index}",
                    "timestamp": step_timestamp,
                    "level": log["level"],
                    "source": log["source"],
                    "message": log["message"],
                }
            )

        # Group visible evidence into the diff, tests, and rationale tabs.
        for tab_name, tab_items in step.get("evidence", {}).items():
            for item_index, item in enumerate(tab_items):
                evidence_tabs[tab_name].append(
                    {
                        "id": f"{step['id']}-{tab_name}-{item_index}",
                        "timestamp": step_timestamp,
                        "summary": item["summary"],
                        "detail": item["detail"],
                        "status": evidence_status,
                    }
                )

    # Return the live execution snapshot consumed by the task detail page.
    return {
        "isLive": not is_complete and run["status"] == "Running",
        "statusLabel": "Streaming live" if not is_complete and run["status"] == "Running" else "Stream complete",
        "lastUpdatedAt": _utc_timestamp(),
        "timeline": timeline_entries,
        "logs": log_entries,
        "evidenceTabs": evidence_tabs,
    }


def _build_cursor_cloud_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the task detail live view for a run backed by Cursor Cloud Agents."""

    cloud_agent = run.get("_cursorAgent", {}) or {}
    target_payload = cloud_agent.get("target", {}) if isinstance(cloud_agent, dict) else {}
    created_at = str(cloud_agent.get("createdAt", "")).strip() or _utc_timestamp()
    cursor_status = str(cloud_agent.get("status", "CREATING"))
    timeline_status = "complete" if run["status"] != "Running" else "active"
    review_status = "pending" if run["status"] == "Running" else "complete"
    timeline = [
        {
            "id": "cursor-launch",
            "title": "Cursor Cloud Agent launched",
            "detail": f"{cloud_agent.get('id', 'Unknown agent')} was started for {run['repo']}.",
            "timestamp": created_at,
            "status": "complete",
        },
        {
            "id": "cursor-progress",
            "title": f"Cursor status: {cursor_status}",
            "detail": run["currentStep"],
            "timestamp": _utc_timestamp(),
            "status": timeline_status,
        },
        {
            "id": "cursor-review",
            "title": "Review handoff",
            "detail": "The task will move into review once the Cursor Cloud Agent finishes.",
            "timestamp": _utc_timestamp(),
            "status": review_status,
        },
    ]
    logs = [
        {
            "id": "cursor-log-launch",
            "timestamp": created_at,
            "level": "info",
            "source": "cursor-cloud",
            "message": f"Launched agent {cloud_agent.get('id', 'unknown')} for repository {run['repo']}.",
        },
        {
            "id": "cursor-log-status",
            "timestamp": _utc_timestamp(),
            "level": "warning" if run["status"] == "Blocked" else "success" if run["status"] == "Review" else "info",
            "source": "cursor-cloud",
            "message": run["currentStep"],
        },
    ]
    rationale_entries = [
        {
            "id": "cursor-rationale-launch",
            "timestamp": created_at,
            "summary": "Live cloud agent launched",
            "detail": str(run.get("_cursorPromptSummary", "The run was sent to Cursor Cloud Agents using the selected task context.")),
            "status": "captured" if run["status"] != "Running" else "running",
        },
    ]

    if str(target_payload.get("prUrl", "")).strip():
        # Add the generated pull request URL when Cursor already created one.
        rationale_entries.append(
            {
                "id": "cursor-rationale-pr",
                "timestamp": _utc_timestamp(),
                "summary": "Pull request link available",
                "detail": f"Cursor attached PR {target_payload.get('prUrl')}.",
                "status": "captured",
            }
        )

    # Return the live execution snapshot consumed by the task detail page.
    return {
        "isLive": run["status"] == "Running",
        "statusLabel": "Cursor Cloud Agent running" if run["status"] == "Running" else "Cursor Cloud Agent complete",
        "lastUpdatedAt": _utc_timestamp(),
        "timeline": timeline,
        "logs": logs,
        "evidenceTabs": {
            "diff": [],
            "tests": [],
            "rationale": rationale_entries,
        },
    }


def _build_static_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the timeline, logs, and evidence tabs for a static run."""

    evidence = run.get("evidence", {})
    test_status = "blocked" if run["status"] == "Blocked" else "captured"

    if run["status"] == "Review":
        static_status_label = "Awaiting decision"
    elif run["status"] == "Approved":
        static_status_label = "Approved - awaiting PR merge"
    elif run["status"] == "Merged":
        static_status_label = "Pull request merged"
    else:
        static_status_label = "Execution complete"

    # Return the completed execution view for runs that are no longer actively streaming.
    return {
        "isLive": False,
        "statusLabel": static_status_label,
        "lastUpdatedAt": _utc_timestamp(),
        "timeline": _build_static_timeline(run),
        "logs": _build_static_logs(run),
        "evidenceTabs": {
            "diff": _build_evidence_entries(list(evidence.get("diff", [])), tab_name="diff", runtime_value=str(run.get("runtime", "00:00")), status="captured"),
            "tests": _build_evidence_entries(list(evidence.get("tests", [])), tab_name="tests", runtime_value=str(run.get("runtime", "00:00")), status=test_status),
            "rationale": _build_evidence_entries(list(evidence.get("rationale", [])), tab_name="rationale", runtime_value=str(run.get("runtime", "00:00")), status="captured"),
        },
    }


def _build_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the task detail live view for the requested run."""

    if run.get("_cursorAgent"):
        # Prefer the Cursor-specific live view when the run is backed by a cloud agent.
        return _build_cursor_cloud_live_view(run)

    if run.get("_streamStartedAt"):
        # Prefer the streaming execution view when the run was started in the live simulator.
        return _build_stream_live_view(run)

    # Fall back to a completed execution view for static seeded runs.
    return _build_static_live_view(run)


def _sync_run_progress(run: Dict[str, Any], settings: Settings) -> None:
    """Updates a live run based on elapsed time inside the simulated stream."""

    if run.get("_cursorAgent"):
        current_status = str(run.get("status", ""))

        if current_status in {"Approved", "Blocked", "Retry", "Merged"}:
            # Preserve reviewer-driven or terminal states after the live agent has already finished.
            return

        # Poll the Cursor-backed run so the control pane reflects the latest agent status.
        try:
            latest_agent = get_cursor_agent(settings, str(run["_cursorAgent"].get("id", "")))
        except CursorAgentError:
            # Keep the last known state when the Cursor status lookup fails.
            return

        previous_agent = dict(run["_cursorAgent"])
        cursor_status = str(latest_agent.get("status", "CREATING"))
        mapped_status = _map_cursor_agent_status(cursor_status)
        target_payload = latest_agent.get("target", {}) if isinstance(latest_agent, dict) else {}
        agent_runtime_payload = dict(previous_agent)
        agent_runtime_payload.update(latest_agent)
        run["_cursorAgent"] = latest_agent
        run["status"] = mapped_status
        run["branch"] = str(target_payload.get("branchName", "")).strip() or run["branch"]
        run["runtime"] = _format_cursor_agent_runtime(agent_runtime_payload, require_nonzero=cursor_status == "FINISHED")

        if cursor_status == "FINISHED":
            # Move finished Cursor runs into the review-ready state.
            run["currentStep"] = "Cursor Cloud Agent finished and prepared the review handoff"
            run["blockers"] = ["No active blockers", "Waiting for reviewer decision"]
        elif cursor_status in {"ERROR", "EXPIRED"}:
            # Move failed Cursor runs into the blocked state with a readable reason.
            run["currentStep"] = f"Cursor Cloud Agent ended with status {cursor_status}"
            run["blockers"] = [f"Cursor status is {cursor_status}", "Review the Cursor agent log and retry after unblocking the issue"]
        else:
            # Keep active Cursor runs in the running state until the provider reports completion.
            run["currentStep"] = f"Cursor Cloud Agent status: {cursor_status}"
            run["blockers"] = ["Cursor Cloud Agent is still running", "Reviewer controls unlock after the live agent finishes"]

        if str(latest_agent.get("summary", "")).strip():
            # Replace the placeholder task summary when Cursor returns a richer summary.
            run["summary"] = str(latest_agent["summary"])

        return

    if run["status"] != "Running" or not run.get("_streamStartedAt"):
        # Skip progress updates when the run is not currently in the live streaming state.
        return

    started_at = _parse_timestamp(str(run.get("_streamStartedAt", "")))
    step_plan = _build_stream_plan(run)
    elapsed_seconds = max(0, int((_utc_now() - started_at).total_seconds()))
    active_index = 0

    # Resolve the active step so the summary fields stay aligned with the stream state.
    for index, step in enumerate(step_plan):
        if elapsed_seconds >= int(step["offsetSeconds"]):
            active_index = index

    run["runtime"] = _format_runtime(elapsed_seconds)
    run["cost"] = f"${0.24 + (elapsed_seconds / 18):.2f}"
    run["currentStep"] = str(step_plan[active_index]["currentStep"])
    run["blockers"] = ["Streaming execution in progress", "Reviewer controls will unlock after the run completes"]

    if elapsed_seconds >= int(step_plan[-1]["offsetSeconds"]):
        # Promote completed live runs into the review state once the final step is visible.
        run["status"] = "Review"
        run["currentStep"] = "Review package ready"
        run["blockers"] = ["No active blockers", "Waiting for reviewer decision"]


def _fallback_issues() -> List[Dict[str, Any]]:
    """Builds a fallback issue catalog from the seeded run summaries."""

    issues: List[Dict[str, Any]] = []

    # Convert seeded runs into fallback issue records for task intake.
    for run in RUN_STORE:
        issues.append(
            {
                "id": run["id"],
                "ticket": run["ticket"],
                "title": run["title"],
                "description": run["summary"],
                "priority": "2",
                "status": run["status"],
                "url": "",
                "assignee": {"name": run["owner"], "email": f"{run['owner'].lower()}@example.com"},
                "provider": "fallback",
            }
        )

    # Return the fallback issue catalog.
    return issues


def _fallback_repositories(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Builds a fallback repository catalog from the seeded run summaries."""

    unique_names: List[str] = []

    # Preserve the first-seen order of repository names from the seeded data.
    for run in runs:
        repo_name = str(run.get("repo", ""))

        if repo_name and repo_name not in unique_names:
            # Keep the unique repository name for the fallback catalog.
            unique_names.append(repo_name)

    repositories: List[Dict[str, Any]] = []

    # Convert the unique repository names into normalized catalog records.
    for repo_name in unique_names:
        repositories.append(
            {
                "id": repo_name,
                "name": repo_name,
                "fullName": repo_name,
                "defaultBranch": "main",
                "private": False,
                "provider": "fallback",
                "url": "",
            }
        )

    # Return the fallback repository catalog.
    return repositories


def _fallback_documents(settings: Settings) -> List[Dict[str, Any]]:
    """Returns repo markdown docs or an empty fallback list."""

    documents = list_repo_documents(settings)

    if documents:
        # Prefer real repo markdown documents whenever they are available.
        return documents

    # Return an empty list when no repo docs could be discovered.
    return []


def _list_connected_issues(settings: Settings) -> List[Dict[str, Any]]:
    """Builds the combined live issue catalog across connected issue trackers."""

    linear_issues = list_linear_issues(settings)
    jira_issues = list_jira_issues(settings)

    # Return the combined issue-tracker catalog while preserving provider-local ordering.
    return [*linear_issues, *jira_issues]


def _slugify(value: str) -> str:
    """Creates a stable slug from a task or run title."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    if slug:
        # Return the normalized slug when the title yields a usable value.
        return slug

    # Fall back to a generic slug when the title has no usable characters.
    return "generated-task"


def _find_issue(issues: List[Dict[str, Any]], issue_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds an issue record by ID from the provided issue catalog."""

    if not issue_id:
        # Return no issue when the caller did not select one.
        return None

    # Search the issue catalog for the selected record.
    for issue in issues:
        if issue.get("id") == issue_id:
            # Return the matching issue record.
            return issue

    # Return no issue when the selected issue cannot be found.
    return None


def _find_repository(repositories: List[Dict[str, Any]], repo_name: str) -> Optional[Dict[str, Any]]:
    """Finds a repository record by display name from the provided repository catalog."""

    normalized_repo_name = repo_name.strip()

    # Search the repository catalog for the selected record.
    for repository in repositories:
        if str(repository.get("name", "")).strip() == normalized_repo_name:
            # Return the matching repository record.
            return repository

    # Return no repository when the selected repo cannot be found.
    return None


def _select_documents(all_documents: List[Dict[str, Any]], document_ids: List[str]) -> List[Dict[str, Any]]:
    """Selects the documents attached to a task request."""

    selected_documents: List[Dict[str, Any]] = []

    # Filter the document catalog down to the chosen document IDs.
    for document in all_documents:
        if document.get("id") in document_ids:
            # Keep each explicitly selected document for the task context.
            selected_documents.append(document)

    # Return the selected task document list.
    return selected_documents


def _normalize_uploaded_documents(uploaded_documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalizes uploaded intake documents into stored task document snapshots."""

    normalized_documents: List[Dict[str, Any]] = []

    # Convert each upload into the same document shape used by the task detail UI.
    for uploaded_document in uploaded_documents:
        document_id = str(uploaded_document.get("id") or "").strip()
        document_path = str(uploaded_document.get("path") or "").strip()
        document_title = str(uploaded_document.get("title") or "").strip()

        if not document_id or not document_path or not document_title:
            # Skip malformed uploads so a partial browser payload does not poison task creation.
            continue

        normalized_documents.append(
            {
                "id": document_id,
                "title": document_title,
                "path": document_path,
                "source": str(uploaded_document.get("source") or "uploaded_repo_document"),
                "updatedAt": str(uploaded_document.get("updatedAt") or ""),
            }
        )

    # Return the sanitized upload list for run snapshots and task detail rendering.
    return normalized_documents


def _build_cursor_issue_block(issue: Dict[str, Any]) -> str:
    """Builds the issue-context section used inside the Cursor Cloud Agent prompt."""

    issue_lines: List[str] = [
        f"Ticket: {issue.get('ticket', 'Unknown ticket')}",
        f"Title: {issue.get('title', 'Untitled task')}",
        f"Status: {issue.get('status', 'Unknown')}",
        f"Priority: {issue.get('priority', 'Unknown')}",
        f"Provider: {issue.get('provider', 'unknown')}",
    ]
    description = str(issue.get("description", "")).strip()
    assignee = issue.get("assignee", {}) or {}
    assignee_name = str(assignee.get("name", "")).strip()

    if assignee_name:
        # Add the assignee when the originating issue included one.
        issue_lines.append(f"Assignee: {assignee_name}")

    if description:
        # Add the issue description when the originating issue included one.
        issue_lines.append(f"Description: {description}")

    # Return the issue block as a newline-delimited prompt section.
    return "\n".join(issue_lines)


def _build_cursor_docs_block(documents: List[Dict[str, Any]]) -> str:
    """Builds the attached-documents section used inside the Cursor Cloud Agent prompt."""

    if not documents:
        # Return a neutral docs section when the task was launched without attached docs.
        return "Attached docs:\n- No repo markdown documents were attached."

    document_lines = ["Attached docs:"]

    # Add each attached document path so the launched agent knows the intended grounding set.
    for document in documents:
        document_lines.append(f"- {document.get('path', document.get('title', 'Unknown document'))}")

    # Return the docs block as a newline-delimited prompt section.
    return "\n".join(document_lines)


def _build_cursor_prompt(
    run: Dict[str, Any],
    *,
    issue: Dict[str, Any],
    documents: List[Dict[str, Any]],
    repository: Dict[str, Any],
) -> str:
    """Builds the Cursor Cloud Agent prompt from the task, issue, and docs context."""

    task_prompt = str(run.get("_taskPrompt", run.get("summary", ""))).strip()
    acceptance_criteria = str(run.get("_acceptanceCriteria", "")).strip()
    repo_full_name = str(repository.get("fullName", repository.get("name", run.get("repo", "repository"))))
    issue_block = _build_cursor_issue_block(issue)
    docs_block = _build_cursor_docs_block(documents)
    prompt_sections = [
        f"You are launching work for the GitHub repository {repo_full_name}.",
        "Use the issue context below to scope the implementation and keep the work traceable to the originating issue-tracker ticket.",
        issue_block,
        f"Task summary:\n{task_prompt or run.get('summary', 'No task summary was provided.')}",
        f"Acceptance criteria:\n{acceptance_criteria or 'Use the issue details and repository context to determine completion.'}",
        docs_block,
        "Implementation instructions:",
        "- Make the requested code changes in the target repository.",
        "- Keep the branch and pull request aligned with the issue ticket.",
        "- Run the most relevant validation before handing off the work.",
        "- Summarize the changes and any follow-up reviewer notes in the final response.",
        "Include a raw git diff in the final message using:\n"
        "git diff origin/main...HEAD",
    ]

    # Return the composed task prompt that will be sent to the Cursor Cloud Agents API.
    return "\n\n".join(prompt_sections)


def _clear_issue_tracker_sync_state(run: Dict[str, Any]) -> None:
    """Clears any cached issue-tracker sync markers from a run record."""

    # Remove the cached Linear sync marker so the next run state can resync cleanly.
    run.pop("_linearSyncedStatusName", None)

    # Remove the cached Jira sync marker so the next run state can resync cleanly.
    run.pop("_jiraSyncedStatusName", None)


def _map_cursor_agent_status(cursor_status: str) -> str:
    """Maps a Cursor Cloud Agent status into the control pane's run-status model."""

    if cursor_status == "FINISHED":
        # Map completed Cursor runs into the app's review-ready state.
        return "Review"

    if cursor_status in {"ERROR", "EXPIRED"}:
        # Map failed or expired Cursor runs into the app's blocked state.
        return "Blocked"

    # Keep all remaining Cursor states inside the app's running state.
    return "Running"


def _resolve_pull_request_url(run: Dict[str, Any], settings: Optional[Settings] = None) -> str:
    """Resolves the pull-request URL recorded for the given run."""

    cloud_agent = run.get("_cursorAgent") or {}
    target_payload = cloud_agent.get("target", {}) if isinstance(cloud_agent, dict) else {}
    pull_request_url = str(target_payload.get("prUrl", "") or "").strip()

    if pull_request_url:
        # Prefer the live Cursor-created PR URL when the run was launched against GitHub.
        return pull_request_url

    # Prefer the connected GitHub owner so task detail links mirror the active integration setup.
    configured_owner = str(settings.github_owner if settings is not None else "").strip() or "example"

    # Fall back to a deterministic GitHub URL so the demo data still links somewhere.
    return f"https://github.com/{configured_owner}/{run['repo']}/pull/{run['ticket'].lower()}"


def _is_real_github_pull_request_url(pull_request_url: str) -> bool:
    """Reports whether the run is pointing at a real GitHub PR URL."""

    parsed_components = parse_github_pull_request_url(pull_request_url)

    if not parsed_components:
        # Return False when the URL does not resolve to a real GitHub PR link.
        return False

    # Treat the example.com / example placeholders as fake so simulation stays in charge.
    return parsed_components.get("owner", "").lower() != "example"


def _simulated_pull_request_state(run: Dict[str, Any]) -> Dict[str, Any]:
    """Computes the simulated GitHub PR state payload for a run.

    The simulation advances the PR through open -> approved -> merged based on
    the timestamps we record on the run after reviewer decisions.
    """

    simulated_state: Dict[str, Any] = {
        "source": "simulated",
        "state": "open",
        "merged": False,
        "mergedAt": None,
        "approved": False,
        "approvedAt": None,
        "approvedBy": None,
    }

    approved_at_value = str(run.get("_approvedAt", "") or "").strip()
    merged_at_value = str(run.get("_mergedAt", "") or "").strip()

    if approved_at_value:
        # Surface the reviewer-driven approval as the baseline PR state.
        simulated_state["approved"] = True
        simulated_state["approvedAt"] = approved_at_value
        simulated_state["state"] = "approved"
        simulated_state["approvedBy"] = str(run.get("_approvedBy", "") or "") or None

    if merged_at_value:
        # Promote the PR into the merged state once a recorded merge timestamp exists.
        simulated_state["merged"] = True
        simulated_state["mergedAt"] = merged_at_value
        simulated_state["state"] = "merged"

        # Return early; merged is terminal so no additional auto-advance is needed.
        return simulated_state

    if approved_at_value:
        approved_at_datetime = _parse_timestamp(approved_at_value)
        elapsed_since_approval = (_utc_now() - approved_at_datetime).total_seconds()

        if elapsed_since_approval >= SIMULATED_PR_MERGE_DELAY_SECONDS:
            # Auto-advance the simulated PR into the merged state after the configured delay.
            simulated_merge_timestamp = (
                approved_at_datetime + timedelta(seconds=SIMULATED_PR_MERGE_DELAY_SECONDS)
            ).isoformat()
            simulated_state["merged"] = True
            simulated_state["mergedAt"] = simulated_merge_timestamp
            simulated_state["state"] = "merged"

    # Return the simulated PR state payload for the state machine.
    return simulated_state


def _resolve_pull_request_state(run: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """Resolves the PR state for a run using live GitHub data or the simulation."""

    # Resolve the PR URL with the effective settings so fallback links use the active GitHub owner.
    pull_request_url = _resolve_pull_request_url(run, settings=settings)

    if _is_real_github_pull_request_url(pull_request_url):
        # Prefer real GitHub data when the run is linked to a real repository PR.
        live_pull_request_state = fetch_github_pull_request_status(settings, pull_request_url)

        if live_pull_request_state:
            # Return the live GitHub PR state so the state machine uses real events.
            return live_pull_request_state

    # Fall back to the simulated PR state for demo and offline runs.
    return _simulated_pull_request_state(run)


def _approval_history_has_entry(history: List[Dict[str, Any]], decision: str, source: str) -> bool:
    """Reports whether the approval history already contains a matching event."""

    # Scan the history for an existing entry with the same decision and source tuple.
    for entry in history:
        if str(entry.get("decision", "")) == decision and str(entry.get("source", "")) == source:
            # Return True so the caller knows the event was already recorded.
            return True

    # Return False when the event has not yet been recorded in the approval history.
    return False


def _append_pull_request_event(
    run: Dict[str, Any],
    *,
    decision: str,
    source: str,
    notes: str,
    timestamp: Optional[str],
    actor: Optional[Dict[str, str]] = None,
) -> None:
    """Appends a pull-request-derived approval history entry if missing."""

    history = list(run.get("approvalHistory", []))

    if _approval_history_has_entry(history, decision, source):
        # Skip duplicate entries so repeated polling does not re-record the same event.
        return

    history.append(
        {
            "decision": decision,
            "source": source,
            "notes": notes,
            "actor": deepcopy(actor) if actor else deepcopy(GITHUB_APPROVAL_ACTOR),
            "timestamp": timestamp or _utc_timestamp(),
        }
    )

    run["approvalHistory"] = history


def _sync_linear_issue_status_from_pr(
    run: Dict[str, Any],
    *,
    settings: Settings,
    pr_state: Dict[str, Any],
) -> None:
    """Pushes the mapped PR state into Linear for runs backed by a Linear issue."""

    issue_snapshot = run.get("_issueSnapshot") or {}

    if not isinstance(issue_snapshot, dict):
        # Skip sync when the run has no structured issue snapshot to target.
        return

    if str(issue_snapshot.get("provider", "")).strip().lower() != "linear":
        # Skip sync for fallback or non-Linear issues.
        return

    issue_id = str(issue_snapshot.get("id", "")).strip()

    if not issue_id:
        # Skip sync when the issue snapshot does not carry a concrete Linear issue ID.
        return

    pr_source = str(pr_state.get("source", "")).strip().lower()
    pr_status_name = ""

    if bool(pr_state.get("merged", False)):
        # Promote merged PRs into the requested Linear "Done" state.
        pr_status_name = LINEAR_STATUS_DONE
    elif pr_source == "github":
        resolved_pr_state = str(pr_state.get("state", "")).strip().lower()

        if resolved_pr_state in {"open", "approved"}:
            # Treat any open GitHub PR state as "In Progress" for the Linear issue.
            pr_status_name = LINEAR_STATUS_IN_PROGRESS

    if not pr_status_name:
        # Skip sync when the current PR state does not map to a Linear workflow update.
        return

    last_synced_status_name = str(run.get("_linearSyncedStatusName", "")).strip()

    if last_synced_status_name == pr_status_name:
        # Skip duplicate sync attempts when the target Linear status is already recorded.
        return

    if update_linear_issue_status(settings, issue_id=issue_id, status_name=pr_status_name):
        # Cache the applied Linear status so repeated dashboard polls stay idempotent.
        run["_linearSyncedStatusName"] = pr_status_name


def _sync_jira_issue_status_from_pr(
    run: Dict[str, Any],
    *,
    settings: Settings,
    pr_state: Dict[str, Any],
) -> None:
    """Pushes the mapped PR state into Jira for runs backed by a Jira issue."""

    issue_snapshot = run.get("_issueSnapshot") or {}

    if not isinstance(issue_snapshot, dict):
        # Skip sync when the run has no structured issue snapshot to target.
        return

    if str(issue_snapshot.get("provider", "")).strip().lower() != "jira":
        # Skip sync for fallback or non-Jira issues.
        return

    issue_id = str(issue_snapshot.get("id", "")).strip()

    if not issue_id:
        # Skip sync when the issue snapshot does not carry a concrete Jira issue ID.
        return

    pr_source = str(pr_state.get("source", "")).strip().lower()
    pr_status_name = ""

    if bool(pr_state.get("merged", False)):
        # Promote merged PRs into the requested Jira "Done" state.
        pr_status_name = JIRA_STATUS_DONE
    elif pr_source == "github":
        resolved_pr_state = str(pr_state.get("state", "")).strip().lower()

        if resolved_pr_state in {"open", "approved"}:
            # Treat any open GitHub PR state as "In Progress" for the Jira issue.
            pr_status_name = JIRA_STATUS_IN_PROGRESS

    if not pr_status_name:
        # Skip sync when the current PR state does not map to a Jira workflow update.
        return

    last_synced_status_name = str(run.get("_jiraSyncedStatusName", "")).strip()

    if last_synced_status_name == pr_status_name:
        # Skip duplicate sync attempts when the target Jira status is already recorded.
        return

    if update_jira_issue_status(settings, issue_id=issue_id, status_name=pr_status_name):
        # Cache the applied Jira status so repeated dashboard polls stay idempotent.
        run["_jiraSyncedStatusName"] = pr_status_name


def _sync_issue_tracker_status_from_pr(
    run: Dict[str, Any],
    *,
    settings: Settings,
    pr_state: Dict[str, Any],
) -> None:
    """Routes PR-derived issue status sync to the matching issue tracker provider."""

    # Attempt the Linear sync path when the run originated from Linear.
    _sync_linear_issue_status_from_pr(run, settings=settings, pr_state=pr_state)

    # Attempt the Jira sync path when the run originated from Jira.
    _sync_jira_issue_status_from_pr(run, settings=settings, pr_state=pr_state)


def _sync_pull_request_status(run: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """Updates the run status and approval history based on the current PR state.

    The state machine only advances runs that are in Review, Approved, or Merged.
    Runs that are still running, blocked, or in retry are returned untouched so
    the rest of the pipeline can continue to manage them.
    """

    run_status = str(run.get("status", ""))

    if run_status not in {"Running", "Review", "Approved", "Merged"}:
        # Return an empty PR state when the run is not a review-candidate yet.
        return {"state": "open", "merged": False, "approved": False, "source": "skipped"}

    if run_status == "Running" and not _is_real_github_pull_request_url(_resolve_pull_request_url(run)):
        # Keep simulated in-flight runs in the draft state until a real GitHub PR exists.
        return {"state": "open", "merged": False, "approved": False, "source": "skipped"}

    pr_state = _resolve_pull_request_state(run, settings)
    _sync_issue_tracker_status_from_pr(run, settings=settings, pr_state=pr_state)

    if run_status == "Running":
        # Keep actively executing runs in the running state even if a PR already exists.
        run["_pullRequestState"] = pr_state
        return pr_state

    if run_status == "Merged":
        # Skip further transitions for runs already in the terminal merged state.
        run["_pullRequestState"] = pr_state
        return pr_state

    if pr_state.get("approved") and run_status == "Review":
        approved_by_login = str(pr_state.get("approvedBy", "") or "").strip()
        review_note = (
            f"GitHub review approved by {approved_by_login}"
            if approved_by_login
            else "GitHub review approved the pull request"
        )

        _append_pull_request_event(
            run,
            decision="pr_review_approved",
            source=pr_state.get("source", "github"),
            notes=review_note,
            timestamp=str(pr_state.get("approvedAt") or ""),
        )

        # Promote Review runs into Approved once the PR was approved upstream.
        run["status"] = "Approved"
        run["currentStep"] = "Pull request approved - awaiting merge"
        run["blockers"] = ["Awaiting pull-request merge on GitHub"]
        run_status = "Approved"

    if pr_state.get("merged"):
        _append_pull_request_event(
            run,
            decision="pr_merged",
            source=pr_state.get("source", "github"),
            notes="Pull request merged on GitHub",
            timestamp=str(pr_state.get("mergedAt") or ""),
        )

        # Promote Approved runs into Merged once the PR has been merged upstream.
        run["status"] = "Merged"
        run["currentStep"] = "Pull request merged"
        run["blockers"] = ["No active blockers"]
        run["_mergedAt"] = str(pr_state.get("mergedAt") or _utc_timestamp())

    run["_pullRequestState"] = pr_state

    # Return the PR state used to advance the run so callers can reuse it.
    return pr_state


def _build_pull_request_view(
    run: Dict[str, Any],
    pr_state: Dict[str, Any],
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Builds the public pull-request payload shown in the task detail UI."""

    run_status = str(run.get("status", ""))
    # Resolve the displayed PR URL with the effective settings when they are available.
    pull_request_url = _resolve_pull_request_url(run, settings=settings)
    resolved_state = str(pr_state.get("state", "open"))

    if pr_state.get("source") == "skipped":
        # Keep pre-review runs in the original draft/ready-for-review states.
        display_status = "draft" if run_status == "Running" else "ready_for_review"
    elif resolved_state == "merged":
        display_status = "merged"
    elif resolved_state == "approved":
        display_status = "approved"
    elif resolved_state == "closed":
        display_status = "closed"
    else:
        display_status = "draft" if run_status == "Running" else "open"

    # Return the extended pull-request payload used by the frontend.
    return {
        "number": pr_state.get("number") or run["ticket"],
        "status": display_status,
        "state": resolved_state if pr_state.get("source") != "skipped" else display_status,
        "url": pr_state.get("htmlUrl") or pull_request_url,
        "merged": bool(pr_state.get("merged", False)),
        "mergedAt": pr_state.get("mergedAt"),
        "approved": bool(pr_state.get("approved", False)),
        "approvedAt": pr_state.get("approvedAt"),
        "approvedBy": pr_state.get("approvedBy"),
        "source": pr_state.get("source", "simulated"),
    }


def _build_run_extensions(
    run: Dict[str, Any],
    *,
    issue: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
    current_user: Optional[Dict[str, str]] = None,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Adds integration context fields to a run record."""

    attached_documents = documents or deepcopy(run.get("_documentSnapshots", [])) or []
    resolved_issue = issue or deepcopy(run.get("_issueSnapshot")) or {
        "id": run["id"],
        "ticket": run["ticket"],
        "title": run["title"],
        "status": run["status"],
        "provider": "fallback",
        "url": "",
    }
    resolved_user = current_user or deepcopy(run.get("_requestedBySnapshot")) or {
        "name": run["owner"],
        "email": f"{run['owner'].lower()}@example.com",
        "role": "admin",
        "provider": "fallback",
    }
    cloud_agent = deepcopy(run.get("_cursorAgent"))

    if settings is not None:
        # Advance the PR state machine before building the public run payload.
        pr_state = _sync_pull_request_status(run, settings)
    else:
        # Fall back to a previously cached PR state when the caller did not pass settings.
        pr_state = deepcopy(run.get("_pullRequestState")) or {
            "state": "open",
            "merged": False,
            "approved": False,
            "source": "skipped",
        }

    # Build the PR payload with the same effective settings used for state sync.
    pull_request = _build_pull_request_view(run, pr_state, settings=settings)
    ci_status = {
        "workflow": "CI",
        "status": "blocked" if run["status"] == "Blocked" else "passed",
        "summary": run["currentStep"],
    }
    approval_history = run.get("approvalHistory", [])

    public_run = {key: value for key, value in run.items() if not str(key).startswith("_")}

    # Return the run plus normalized integration context fields.
    return {
        **public_run,
        "issue": resolved_issue,
        "pullRequest": pull_request,
        "ci": ci_status,
        "documents": attached_documents,
        "requestedBy": resolved_user,
        "approvalHistory": approval_history,
        "cloudAgent": cloud_agent,
        "liveView": _build_live_view(run),
    }


def _is_actionable_blocker(blocker: str) -> bool:
    """Reports whether a blocker string should appear in dashboard summaries."""

    normalized_blocker = blocker.strip().lower()

    if not normalized_blocker:
        # Ignore empty blocker text so dashboard summaries stay meaningful.
        return False

    ignored_blockers = {
        "none",
        "no active blockers",
        "awaiting run start",
        "streaming execution in progress",
        "reviewer controls will unlock after the run completes",
        "waiting for reviewer decision",
        "cursor cloud agent is still running",
        "reviewer controls unlock after the live agent finishes",
        "awaiting pull-request merge on github",
    }

    # Return true only when the blocker adds real operator context.
    return normalized_blocker not in ignored_blockers


def _collect_blocker_counts() -> Dict[str, int]:
    """Counts actionable blocker reasons across blocked and retry runs."""

    blocker_counts: Dict[str, int] = {}

    # Scan the run store for the blocker reasons that need dashboard visibility.
    for run in RUN_STORE:
        if run.get("status") not in {"Blocked", "Retry"}:
            # Skip runs that are not currently stalled.
            continue

        run_blockers = list(run.get("blockers", []))
        run_has_explicit_blocker = False

        # Count each actionable blocker while preserving first-seen order.
        for blocker in run_blockers:
            if _is_actionable_blocker(str(blocker)):
                blocker_counts[str(blocker)] = blocker_counts.get(str(blocker), 0) + 1
                run_has_explicit_blocker = True

        if run_has_explicit_blocker:
            # Skip the current-step fallback when explicit blockers were already captured.
            continue

        current_step = str(run.get("currentStep", "")).strip()

        if _is_actionable_blocker(current_step):
            # Count the current step when the run has no better blocker list.
            blocker_counts[current_step] = blocker_counts.get(current_step, 0) + 1

    # Return the collected blocker counts for dashboard metrics and side panels.
    return blocker_counts


def _build_dashboard_blocked_reasons() -> List[str]:
    """Builds the blocked-reasons panel from the current run blocker state."""

    blocker_counts = _collect_blocker_counts()

    if not blocker_counts:
        # Return a state-based empty result when no actionable blockers are present.
        return ["No actionable blocker reasons are currently reported."]

    ordered_blockers = sorted(blocker_counts.items(), key=lambda item: -item[1])
    blocked_reasons: List[str] = []

    # Surface the most common blocker reasons with their affected-run counts.
    for blocker, count in ordered_blockers[:3]:
        blocked_reasons.append(f"{blocker} ({count} run{'s' if count != 1 else ''})")

    # Return the blocked-reason list shown in the dashboard side rail.
    return blocked_reasons


def _build_review_effort_value(review_candidate_count: int, total_review_runtime_seconds: int) -> str:
    """Formats the review-effort metric from review-ready and merged run runtimes."""

    if review_candidate_count == 0:
        # Return a stable zero state when no runs have reached review yet.
        return "0 min"

    average_runtime_seconds = round(total_review_runtime_seconds / review_candidate_count)

    # Return the average runtime in minutes for the dashboard metric value.
    return f"{max(1, round(average_runtime_seconds / 60))} min"


def _compute_metrics(runs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Computes dashboard metrics from the in-memory run state."""

    active_runs = 0
    running_runs = 0
    blocked_runs = 0
    merged_runs = 0
    approved_runs = 0
    review_ready = 0
    review_candidate_count = 0
    total_review_runtime_seconds = 0
    blocker_counts = _collect_blocker_counts()

    # Aggregate the run counts needed by the dashboard cards.
    for run in runs:
        status = str(run.get("status", ""))

        if status in {"Running", "Review", "Approved", "Blocked", "Retry"}:
            # Count non-terminal runs as active.
            active_runs += 1

        if status == "Running":
            # Count live runs that are still actively executing.
            running_runs += 1

        if status == "Blocked":
            # Count blocked runs for the operational dashboard.
            blocked_runs += 1

        if status == "Merged":
            # Count merged runs for the daily summary card.
            merged_runs += 1

        if status == "Approved":
            # Count runs that are approved but still waiting for the PR to merge.
            approved_runs += 1

        if status == "Review":
            # Count review-ready runs for reviewer load visibility.
            review_ready += 1

        if status in {"Review", "Approved", "Merged"}:
            # Include review-ready, approved, and merged runs in the review-effort estimate.
            review_candidate_count += 1
            total_review_runtime_seconds += _parse_runtime_seconds(str(run.get("runtime", "00:00")))

    review_effort_value = _build_review_effort_value(review_candidate_count, total_review_runtime_seconds)
    active_runs_hint_parts: List[str] = []

    # Call out live runs first since they directly reflect current agent activity.
    active_runs_hint_parts.append(f"{running_runs} running")

    if review_ready:
        # Highlight review-ready runs so reviewers know where their inbox stands.
        active_runs_hint_parts.append(f"{review_ready} waiting for review")

    if approved_runs:
        # Surface approved-but-not-merged runs so operators can watch PR merge state.
        active_runs_hint_parts.append(f"{approved_runs} approved awaiting merge")

    active_runs_hint = (
        ", ".join(active_runs_hint_parts)
        if active_runs_hint_parts
        else "No active runs are currently in flight"
    )
    blocked_runs_hint = (
        f"{len(blocker_counts)} unique blocker reason{'s' if len(blocker_counts) != 1 else ''} need follow-up"
        if blocked_runs or blocker_counts
        else "No blocked runs currently need follow-up"
    )
    merged_runs_hint = (
        f"{merged_runs} run{'s' if merged_runs != 1 else ''} reached the merged state in the current session"
        if merged_runs
        else "No merged runs are recorded in the current session"
    )
    review_effort_hint = (
        f"Average runtime across {review_candidate_count} run{'s' if review_candidate_count != 1 else ''} that reached review or merge"
        if review_candidate_count
        else "No review-ready or merged runs are available to estimate review effort"
    )

    # Return the derived dashboard metrics.
    return [
        {"label": "Active runs", "value": str(active_runs), "hint": active_runs_hint},
        {"label": "Blocked tasks", "value": str(blocked_runs), "hint": blocked_runs_hint},
        {"label": "Merged today", "value": str(merged_runs), "hint": merged_runs_hint},
        {"label": "Review effort", "value": review_effort_value, "hint": review_effort_hint},
    ]


def _find_integration_status(statuses: List[Dict[str, Any]], integration_id: str) -> Optional[Dict[str, Any]]:
    """Finds a dashboard integration status by provider identifier."""

    # Search the integration status list for the requested provider entry.
    for status in statuses:
        if status.get("id") == integration_id:
            # Return the first matching provider status record.
            return status

    # Return no status when the provider is not present in the payload.
    return None


def _build_dashboard_suggested_actions(
    *,
    runs: List[Dict[str, Any]],
    repository_names: List[str],
    integration_statuses: List[Dict[str, Any]],
) -> List[str]:
    """Builds dashboard suggestions from current run and integration state."""

    review_ready_count = len([run for run in runs if run.get("status") == "Review"])
    stalled_runs = len([run for run in runs if run.get("status") in {"Blocked", "Retry"}])
    blocker_counts = _collect_blocker_counts()
    suggested_actions: List[str] = []
    top_blocker = next(iter(blocker_counts), "")
    linear_status = _find_integration_status(integration_statuses, "linear")
    jira_status = _find_integration_status(integration_statuses, "jira")
    github_status = _find_integration_status(integration_statuses, "github")
    cursor_status = _find_integration_status(integration_statuses, "cursor_cloud_agents")
    docs_status = _find_integration_status(integration_statuses, "repo_docs")
    issue_tracker_connected = bool(
        (linear_status and bool(linear_status.get("connected")))
        or (jira_status and bool(jira_status.get("connected")))
    )

    if review_ready_count:
        # Prompt reviewers to clear the runs already waiting in the approval inbox.
        suggested_actions.append(
            f"Review {review_ready_count} run{'s' if review_ready_count != 1 else ''} waiting in the approval inbox."
        )

    if stalled_runs:
        blocker_suffix = f" Top blocker: {top_blocker}." if top_blocker else ""

        # Surface the blocked-run follow-up work directly in the dashboard suggestions.
        suggested_actions.append(
            f"Unblock {stalled_runs} stalled run{'s' if stalled_runs != 1 else ''}.{blocker_suffix}"
        )

    if not issue_tracker_connected:
        # Recommend enabling a live issue tracker when neither Linear nor Jira is connected.
        suggested_actions.append("Connect Linear or Jira so dashboard and intake views use real tickets.")
    elif github_status and not bool(github_status.get("connected")):
        # Recommend connecting GitHub when real repository launches are still unavailable.
        suggested_actions.append("Connect GitHub so new runs can target real repositories.")
    elif cursor_status and not bool(cursor_status.get("connected")):
        # Recommend connecting Cursor when runs cannot launch against the live cloud agent surface.
        suggested_actions.append("Connect Cursor Cloud Agents so runs launch against the live agent service.")
    elif docs_status and not bool(docs_status.get("connected")):
        # Recommend connecting repo docs when runs are missing grounded markdown context.
        suggested_actions.append("Connect repo docs so new tasks attach real markdown context.")

    if repository_names and len(suggested_actions) < 3:
        # Suggest launching new work when repositories are already available for intake.
        suggested_actions.append(
            f"Launch new work against {len(repository_names)} available repos in the intake flow."
        )

    if not suggested_actions:
        # Return a stable empty state when the dashboard has no urgent follow-up.
        return ["No immediate follow-up actions are suggested."]

    # Return the highest-signal suggestions for the dashboard side rail.
    return suggested_actions[:3]


def get_integration_catalog(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the shared integration catalog used by the intake and integrations views."""

    active_team_id = _resolve_team_id_from_headers(headers)
    team_runs = _list_team_runs(active_team_id)
    repositories = list_github_repositories(settings)
    issues = _list_connected_issues(settings)
    documents = list_repo_documents(settings)

    if not repositories:
        # Fall back to repo records derived from the seeded task data.
        repositories = _fallback_repositories(team_runs)

    if not issues:
        # Fall back to issue records derived from the seeded task data.
        issues = _fallback_issues()

    if not documents:
        # Fall back to repo markdown documents when no richer docs source is present.
        documents = _fallback_documents(settings)

    current_user = resolve_current_user(settings, headers)

    # Return the integration catalog and current-user context used across the app.
    return {
        "repositories": repositories,
        "issues": issues,
        "documents": documents,
        "currentUser": current_user,
        "statuses": get_integration_statuses(settings),
        "teamRuns": team_runs,
        "teamId": active_team_id,
    }


def get_dashboard_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the dashboard payload from the live-or-fallback run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = list(integration_catalog.get("teamRuns", []))
    repository_names = summarize_repository_names(integration_catalog["repositories"])
    runs: List[Dict[str, Any]] = []

    # Enrich each run with integration context for the task detail view.
    for run in team_runs:
        _sync_run_progress(run, settings)
        documents = integration_catalog["documents"][:2]
        runs.append(
            _build_run_extensions(
                run,
                documents=documents,
                current_user=integration_catalog["currentUser"],
                settings=settings,
            )
        )

    blocked_reasons = _build_dashboard_blocked_reasons()
    suggested_actions = _build_dashboard_suggested_actions(
        runs=team_runs,
        repository_names=repository_names,
        integration_statuses=integration_catalog["statuses"],
    )

    # Return the derived dashboard payload plus integration status context.
    return {
        "metrics": _compute_metrics(team_runs),
        "runs": runs,
        "blockedReasons": blocked_reasons,
        "suggestedActions": suggested_actions,
        "integrationStatuses": integration_catalog["statuses"],
        "currentUser": integration_catalog["currentUser"],
    }


def get_run_detail(run_id: str, settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Returns the enriched run detail payload for a specific run."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = list(integration_catalog.get("teamRuns", []))

    # Search the in-memory run store for the requested record.
    for run in team_runs:
        if run["id"] == run_id:
            _sync_run_progress(run, settings)
            documents = integration_catalog["documents"][:2]

            # Return the matching run with integration context attached.
            return _build_run_extensions(
                run,
                documents=documents,
                current_user=integration_catalog["currentUser"],
                settings=settings,
            )

    # Raise a key error when the requested run does not exist.
    raise KeyError(run_id)


def get_runs_by_ids(
    run_ids: List[str],
    settings: Settings,
    headers: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """Returns enriched run payloads for a specific set of run IDs.

    Preserves the order of the provided IDs and silently skips any IDs that do
    not correspond to a record in the in-memory run store so the caller can
    pass a snapshot of the dashboard's visible runs without worrying about
    stale references.
    """

    if not run_ids:
        # Return an empty list when the caller passed no IDs to look up.
        return []

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = list(integration_catalog.get("teamRuns", []))
    runs_by_id: Dict[str, Dict[str, Any]] = {}

    # Index the current run store by ID so lookups stay O(n) instead of O(n*m).
    for run in team_runs:
        run_id_value = str(run.get("id") or "")
        if run_id_value:
            runs_by_id[run_id_value] = run

    resolved_runs: List[Dict[str, Any]] = []

    # Preserve the caller-provided ordering while skipping unknown IDs.
    for requested_id in run_ids:
        run = runs_by_id.get(str(requested_id))

        if run is None:
            # Skip IDs that no longer exist in the run store.
            continue

        _sync_run_progress(run, settings)
        documents = integration_catalog["documents"][:2]
        resolved_runs.append(
            _build_run_extensions(
                run,
                documents=documents,
                current_user=integration_catalog["currentUser"],
                settings=settings,
            )
        )

    # Return the resolved run payloads in the requested order.
    return resolved_runs


def get_approval_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the approval inbox payload from the current run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = list(integration_catalog.get("teamRuns", []))
    queue: List[Dict[str, str]] = []
    enriched_runs: List[Dict[str, Any]] = []
    review_count = 0
    high_risk_count = 0
    sla_risk = 0

    # Build the review queue and queue summary from the current run store.
    for run in team_runs:
        _sync_run_progress(run, settings)
        enriched_runs.append(
            _build_run_extensions(
                run,
                documents=integration_catalog["documents"][:2],
                current_user=integration_catalog["currentUser"],
                settings=settings,
            )
        )

        if run["status"] in {"Review", "Blocked", "Retry"}:
            waiting_time = "12 min" if run["status"] == "Review" else "8 min"
            outcome_needed = "Approve or retry" if run["status"] == "Review" else "Escalate or unblock"

            queue.append(
                {
                    "runId": run["id"],
                    "waitingTime": waiting_time,
                    "outcomeNeeded": outcome_needed,
                }
            )

        if run["status"] == "Review":
            # Count review-ready runs for the inbox summary.
            review_count += 1

        if run["risk"] == "High":
            # Count high-risk runs that may require deeper review.
            high_risk_count += 1

        if run["status"] in {"Blocked", "Retry"}:
            # Count SLA-risk items that are no longer moving cleanly.
            sla_risk += 1

    # Return the approval inbox payload plus the enriched run list.
    return {
        "summary": {
            "queueSize": len(queue),
            "highRisk": high_risk_count,
            "slaRisk": sla_risk,
            "reviewReady": review_count,
        },
        "queue": queue,
        "runs": enriched_runs,
        "currentUser": integration_catalog["currentUser"],
    }


def get_policy_payload(scope: str) -> Dict[str, Any]:
    """Builds the active policy payload for the requested scope."""

    # Return the policy rules for the requested repo or team scope.
    return {
        "scope": scope,
        "version": "3.1",
        "rules": deepcopy(POLICY_RULES),
    }


def get_intake_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the task intake payload that powers integrated work creation."""

    integration_catalog = get_integration_catalog(settings, headers)

    # Return the intake options and provider status overview.
    return {
        "repositories": integration_catalog["repositories"],
        "issues": integration_catalog["issues"],
        "documents": integration_catalog["documents"],
        "currentUser": integration_catalog["currentUser"],
        "integrationStatuses": integration_catalog["statuses"],
    }


def get_integrations_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the integrations overview payload for the management screen."""

    integration_catalog = get_integration_catalog(settings, headers)

    # Return the provider statuses together with the acting user identity.
    return {
        "statuses": integration_catalog["statuses"],
        "currentUser": integration_catalog["currentUser"],
    }


def create_task(
    settings: Settings,
    headers: Mapping[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Creates a new integrated AI work item from the intake flow."""

    integration_catalog = get_integration_catalog(settings, headers)
    issue = _find_issue(integration_catalog["issues"], payload.get("issueId"))
    uploaded_documents = _normalize_uploaded_documents(list(payload.get("uploadedDocuments", [])))

    if uploaded_documents:
        # Prefer the uploaded repo documents so the created task carries the same context used for enrichment.
        selected_documents = uploaded_documents
    else:
        # Fall back to document IDs selected from the integration catalog when no uploads were provided.
        selected_documents = _select_documents(
            integration_catalog["documents"],
            list(payload.get("documentIds", [])),
        )

    current_user = integration_catalog["currentUser"]
    active_team_id = str(integration_catalog.get("teamId", "default-team"))
    title = str(payload.get("title", "")).strip() or str(issue["title"] if issue else "Generated task")
    ticket = str(issue["ticket"] if issue else f"ACP-{len(RUN_STORE) + 200}")
    run_id = f"{ticket.lower()}-{_slugify(title)}"

    new_run = {
        "id": run_id,
        "ticket": ticket,
        "title": title,
        "repo": payload["repoName"],
        "branch": f"ai/{_slugify(ticket)}-{_slugify(title)}",
        "owner": current_user["name"],
        "agent": "impl-agent",
        "runtime": "00:00",
        "cost": "$0.00",
        "status": "Running",
        "risk": "Medium",
        "currentStep": "Starting run from integrated intake",
        "summary": payload["prompt"],
        "evidence": {
            "diff": ["Waiting for the run to produce code changes."],
            "tests": ["Waiting for the run to report validation results."],
            "commands": ["Run requested from task intake"],
            "rationale": ["The run was created from issue, repo, and docs context selected in the intake flow."],
        },
        "blockers": ["Starting run"],
        "approvalHistory": [],
        "_streamStartedAt": "",
        "_executionMode": str(payload.get("executionMode", "implement")),
        "_taskPrompt": str(payload.get("prompt", "")),
        "_acceptanceCriteria": str(payload.get("acceptanceCriteria", "")),
        "_issueSnapshot": deepcopy(issue) if issue else None,
        "_documentSnapshots": deepcopy(selected_documents),
        "_requestedBySnapshot": deepcopy(current_user),
        "_teamId": active_team_id,
    }

    # Add the newly created run to the top of the in-memory run store.
    RUN_STORE.insert(0, new_run)

    try:
        # Immediately start the run so intake creation follows the same path as the run-start action.
        return create_run(
            settings,
            headers,
            {
                "taskId": run_id,
                "agentName": "impl-agent",
                "executionMode": str(payload.get("executionMode", "implement")),
            },
        )
    except Exception:
        # Remove the half-created task when the automatic run start fails.
        RUN_STORE[:] = [run for run in RUN_STORE if run["id"] != run_id]
        raise


def create_run(
    settings: Settings,
    headers: Mapping[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Starts or restarts an AI run for an existing task."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = list(integration_catalog.get("teamRuns", []))

    # Search the in-memory run store for the task being started.
    for run in team_runs:
        if run["id"] == payload["taskId"]:
            issue = deepcopy(run.get("_issueSnapshot")) or {
                "id": run["id"],
                "ticket": run["ticket"],
                "title": run["title"],
                "description": run["summary"],
                "status": run["status"],
                "priority": "2",
                "provider": "fallback",
                "assignee": {},
            }
            documents = deepcopy(run.get("_documentSnapshots", []))
            current_user = deepcopy(run.get("_requestedBySnapshot")) or integration_catalog["currentUser"]

            if settings.cursor_api_key:
                repository = _find_repository(integration_catalog["repositories"], run["repo"])

                if not repository or not str(repository.get("url", "")).strip():
                    # Reject live launches when GitHub is not configured for the selected repository.
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Connect GitHub for the selected repository before launching a live Cursor Cloud Agent.",
                    )

                prompt_text = _build_cursor_prompt(
                    run,
                    issue=issue,
                    documents=documents,
                    repository=repository,
                )

                try:
                    launched_agent = launch_cursor_agent(
                        settings,
                        repository_url=str(repository["url"]),
                        base_ref=str(repository.get("defaultBranch", "main")),
                        branch_name=str(run.get("branch", "")),
                        prompt_text=prompt_text,
                    )
                except CursorAgentError as error:
                    # Translate provider launch failures into a clear API response.
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

                target_payload = launched_agent.get("target", {}) if isinstance(launched_agent, dict) else {}
                run["status"] = "Running"
                run["agent"] = "cursor-cloud-agent"
                run["currentStep"] = "Cursor Cloud Agent launched against the connected GitHub repository"
                run["runtime"] = "00:00"
                run["cost"] = "$0.00"
                run["branch"] = str(target_payload.get("branchName", "")).strip() or run["branch"]
                run["blockers"] = ["Cursor Cloud Agent is still running", "Reviewer controls unlock after the live agent finishes"]
                run["_streamStartedAt"] = ""
                run["_executionMode"] = str(payload.get("executionMode", "implement"))
                run["_cursorAgent"] = launched_agent
                run["_cursorPromptSummary"] = f"Launched Cursor Cloud Agent {launched_agent.get('id', 'unknown')} for {issue.get('ticket', run['ticket'])}."
                run.pop("_approvedAt", None)
                run.pop("_approvedBy", None)
                run.pop("_mergedAt", None)
                run.pop("_pullRequestState", None)
                _clear_issue_tracker_sync_state(run)
                run["evidence"]["commands"] = [f"POST /v0/agents -> {launched_agent.get('id', 'unknown')}"]
                run["evidence"]["diff"] = ["Waiting for the live Cursor Cloud Agent to produce changes."]
                run["evidence"]["tests"] = ["Waiting for the live Cursor Cloud Agent to report validation results."]
                run["evidence"]["rationale"] = [
                    f"Live launch targeted {repository.get('fullName', repository.get('name', run['repo']))} using issue {issue.get('ticket', run['ticket'])}.",
                ]

                # Return the updated run record with the live Cursor metadata attached.
                return _build_run_extensions(
                    run,
                    issue=issue,
                    documents=documents,
                    current_user=current_user,
                    settings=settings,
                )

            run["status"] = "Running"
            run["agent"] = payload.get("agentName", "impl-agent")
            run["currentStep"] = "Loading task context"
            run["runtime"] = "00:00"
            run["cost"] = "$0.24"
            run["blockers"] = ["Streaming execution in progress", "Reviewer controls will unlock after the run completes"]
            run["_streamStartedAt"] = _utc_timestamp()
            run["_executionMode"] = str(payload.get("executionMode", "implement"))
            run.pop("_cursorAgent", None)
            run.pop("_cursorPromptSummary", None)
            run.pop("_approvedAt", None)
            run.pop("_approvedBy", None)
            run.pop("_mergedAt", None)
            run.pop("_pullRequestState", None)
            _clear_issue_tracker_sync_state(run)

            # Return the updated simulated run record.
            return _build_run_extensions(
                run,
                issue=issue,
                documents=documents,
                current_user=current_user,
                settings=settings,
            )

    # Raise a key error when the task ID cannot be found.
    raise KeyError(payload["taskId"])


def record_approval(
    settings: Settings,
    headers: Mapping[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Records an approval decision against a run and updates its state."""

    current_user = resolve_current_user(settings, headers)
    decision = str(payload["decision"]).lower()
    notes = str(payload.get("notes", "")).strip()

    active_team_id = _resolve_team_id_from_headers(headers)

    # Search the in-memory run store for the run being approved or redirected.
    for run in RUN_STORE:
        if not _run_belongs_to_team(run, active_team_id):
            # Skip runs that are outside the active team's isolated review queue.
            continue
        if run["id"] == payload["runId"]:
            approval_timestamp = _utc_timestamp()
            approval_entry = {
                "decision": decision,
                "source": "reviewer",
                "notes": notes,
                "actor": current_user,
                "timestamp": approval_timestamp,
            }
            history = list(run.get("approvalHistory", []))
            history.append(approval_entry)
            run["approvalHistory"] = history

            if decision == "approve":
                # Mark the run as reviewer-approved and hand control to the PR merge watcher.
                run["status"] = "Approved"
                run["currentStep"] = "Approved by reviewer - awaiting pull request merge"
                run["blockers"] = ["Awaiting pull-request merge on GitHub"]
                run["_approvedAt"] = approval_timestamp
                run["_approvedBy"] = current_user.get("name", "")
                run.pop("_mergedAt", None)
                run.pop("_pullRequestState", None)
            elif decision == "retry":
                # Mark retry decisions so the queue can keep tracking the task.
                run["status"] = "Retry"
                run["currentStep"] = "Awaiting another agent attempt"
                run.pop("_approvedAt", None)
                run.pop("_approvedBy", None)
                run.pop("_mergedAt", None)
                run.pop("_pullRequestState", None)
                _clear_issue_tracker_sync_state(run)
            elif decision == "re-scope":
                # Mark re-scoped runs as blocked until the task definition changes.
                run["status"] = "Blocked"
                run["currentStep"] = "Waiting on updated scope"
                run.pop("_approvedAt", None)
                run.pop("_approvedBy", None)
                run.pop("_mergedAt", None)
                run.pop("_pullRequestState", None)
                _clear_issue_tracker_sync_state(run)
            else:
                # Treat all other decisions as escalation to a human engineer.
                run["status"] = "Blocked"
                run["currentStep"] = "Escalated to a human engineer"
                run.pop("_approvedAt", None)
                run.pop("_approvedBy", None)
                run.pop("_mergedAt", None)
                run.pop("_pullRequestState", None)
                _clear_issue_tracker_sync_state(run)

            # Return the updated run with the new approval history.
            return _build_run_extensions(run, current_user=current_user, settings=settings)

    # Raise a key error when the run ID cannot be found.
    raise KeyError(payload["runId"])
