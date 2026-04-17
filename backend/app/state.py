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
from app.providers import get_cursor_agent
from app.providers import get_integration_statuses
from app.providers import launch_cursor_agent
from app.providers import list_github_repositories
from app.providers import list_linear_issues
from app.providers import list_repo_documents
from app.providers import resolve_current_user
from app.providers import summarize_repository_names


RUN_STORE: List[Dict[str, Any]] = deepcopy(RUN_SUMMARIES)
STREAM_STEP_SECONDS = 4


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
            "title": "Approved and merged"
            if run["status"] == "Merged"
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

    # Return the completed execution view for runs that are no longer actively streaming.
    return {
        "isLive": False,
        "statusLabel": "Awaiting decision" if run["status"] == "Review" else "Execution complete",
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
        # Poll the Cursor-backed run so the control pane reflects the latest agent status.
        try:
            latest_agent = get_cursor_agent(settings, str(run["_cursorAgent"].get("id", "")))
        except CursorAgentError:
            # Keep the last known state when the Cursor status lookup fails.
            return

        cursor_status = str(latest_agent.get("status", "CREATING"))
        mapped_status = _map_cursor_agent_status(cursor_status)
        target_payload = latest_agent.get("target", {}) if isinstance(latest_agent, dict) else {}
        run["_cursorAgent"] = latest_agent
        run["status"] = mapped_status
        run["branch"] = str(target_payload.get("branchName", "")).strip() or run["branch"]

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


def _fallback_repositories() -> List[Dict[str, Any]]:
    """Builds a fallback repository catalog from the seeded run summaries."""

    unique_names: List[str] = []

    # Preserve the first-seen order of repository names from the seeded data.
    for run in RUN_STORE:
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
    issue_url = str(issue.get("url", "")).strip()
    assignee = issue.get("assignee", {}) or {}
    assignee_name = str(assignee.get("name", "")).strip()
    assignee_email = str(assignee.get("email", "")).strip()

    if assignee_name:
        # Add the assignee when the originating issue included one.
        issue_lines.append(f"Assignee: {assignee_name}")

    if assignee_email:
        # Add the assignee email so reviewers can trace issue ownership across systems.
        issue_lines.append(f"Assignee Email: {assignee_email}")

    if description:
        # Add the issue description when the originating issue included one.
        issue_lines.append(f"Description: {description}")

    if issue_url:
        # Add the canonical issue URL so launched agents keep ticket traceability in context.
        issue_lines.append(f"Issue URL: {issue_url}")

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
        "Use the issue context below to scope the implementation and keep the work traceable to the originating Linear ticket.",
        issue_block,
        f"Task summary:\n{task_prompt or run.get('summary', 'No task summary was provided.')}",
        f"Acceptance criteria:\n{acceptance_criteria or 'Use the issue details and repository context to determine completion.'}",
        docs_block,
        "Implementation instructions:",
        "- Make the requested code changes in the target repository.",
        "- Keep the branch and pull request aligned with the issue ticket.",
        "- Run the most relevant validation before handing off the work.",
        "- Summarize the changes and any follow-up reviewer notes in the final response.",
    ]

    # Return the composed task prompt that will be sent to the Cursor Cloud Agents API.
    return "\n\n".join(prompt_sections)


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


def _build_run_extensions(
    run: Dict[str, Any],
    *,
    issue: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
    current_user: Optional[Dict[str, str]] = None,
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
        "role": "tech_lead",
        "provider": "fallback",
    }
    cloud_agent = deepcopy(run.get("_cursorAgent"))
    target_payload = cloud_agent.get("target", {}) if isinstance(cloud_agent, dict) else {}
    pull_request_url = str(target_payload.get("prUrl", "")).strip()
    pull_request = {
        "number": run["ticket"],
        "status": "draft" if run["status"] == "Running" else "ready_for_review",
        "url": pull_request_url or f"https://github.com/example/{run['repo']}/pull/{run['ticket'].lower()}",
    }
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


def _compute_metrics() -> List[Dict[str, str]]:
    """Computes dashboard metrics from the in-memory run state."""

    active_runs = 0
    blocked_runs = 0
    merged_runs = 0
    review_ready = 0

    # Aggregate the run counts needed by the dashboard cards.
    for run in RUN_STORE:
        status = str(run.get("status", ""))

        if status in {"Running", "Review", "Blocked", "Retry"}:
            # Count non-terminal runs as active.
            active_runs += 1

        if status == "Blocked":
            # Count blocked runs for the operational dashboard.
            blocked_runs += 1

        if status == "Merged":
            # Count merged runs for the daily summary card.
            merged_runs += 1

        if status == "Review":
            # Count review-ready runs for reviewer load visibility.
            review_ready += 1

    # Return the derived dashboard metrics.
    return [
        {"label": "Active runs", "value": str(active_runs), "hint": f"{review_ready} review-ready right now"},
        {"label": "Blocked tasks", "value": str(blocked_runs), "hint": "Provider or policy issues may require attention"},
        {"label": "Merged today", "value": str(merged_runs), "hint": "Includes approved AI-assisted runs"},
        {"label": "Review effort", "value": "18 min", "hint": "Average review time per accepted run"},
    ]


def get_integration_catalog(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the shared integration catalog used by the intake and integrations views."""

    repositories = list_github_repositories(settings)
    issues = list_linear_issues(settings)
    documents = list_repo_documents(settings)

    if not repositories:
        # Fall back to repo records derived from the seeded task data.
        repositories = _fallback_repositories()

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
    }


def get_dashboard_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the dashboard payload from the live-or-fallback run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    repository_names = summarize_repository_names(integration_catalog["repositories"])
    runs: List[Dict[str, Any]] = []

    # Enrich each run with integration context for the task detail view.
    for run in RUN_STORE:
        _sync_run_progress(run, settings)
        documents = integration_catalog["documents"][:2]
        runs.append(
            _build_run_extensions(
                run,
                documents=documents,
                current_user=integration_catalog["currentUser"],
            )
        )

    blocked_reasons = [
        "Missing test environment secret",
        "Policy denied production-impacting command",
        "Linear issue moved without reviewer action",
    ]
    suggested_actions = [
        f"{len([run for run in RUN_STORE if run['status'] == 'Review'])} review-ready runs in the approval inbox",
        f"{len(repository_names)} repositories available for new task intake",
        "Knowledge sources are attached from repo markdown by default",
    ]

    # Return the derived dashboard payload plus integration status context.
    return {
        "metrics": _compute_metrics(),
        "runs": runs,
        "blockedReasons": blocked_reasons,
        "suggestedActions": suggested_actions,
        "integrationStatuses": integration_catalog["statuses"],
        "currentUser": integration_catalog["currentUser"],
    }


def get_run_detail(run_id: str, settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Returns the enriched run detail payload for a specific run."""

    integration_catalog = get_integration_catalog(settings, headers)

    # Search the in-memory run store for the requested record.
    for run in RUN_STORE:
        if run["id"] == run_id:
            _sync_run_progress(run, settings)
            documents = integration_catalog["documents"][:2]

            # Return the matching run with integration context attached.
            return _build_run_extensions(
                run,
                documents=documents,
                current_user=integration_catalog["currentUser"],
            )

    # Raise a key error when the requested run does not exist.
    raise KeyError(run_id)


def get_approval_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the approval inbox payload from the current run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    queue: List[Dict[str, str]] = []
    enriched_runs: List[Dict[str, Any]] = []
    review_count = 0
    high_risk_count = 0
    sla_risk = 0

    # Build the review queue and queue summary from the current run store.
    for run in RUN_STORE:
        _sync_run_progress(run, settings)
        enriched_runs.append(
            _build_run_extensions(
                run,
                documents=integration_catalog["documents"][:2],
                current_user=integration_catalog["currentUser"],
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
    selected_documents = _select_documents(
        integration_catalog["documents"],
        list(payload.get("documentIds", [])),
    )
    current_user = integration_catalog["currentUser"]
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
        "agent": "planner-agent",
        "runtime": "00:00",
        "cost": "$0.00",
        "status": "Running",
        "risk": "Medium",
        "currentStep": "Task created from integrated intake",
        "summary": payload["prompt"],
        "evidence": {
            "diff": ["Task created; no code changes yet."],
            "tests": ["No checks executed yet."],
            "commands": ["Pending run start"],
            "rationale": ["The run was created from issue, repo, and docs context selected in the intake flow."],
        },
        "blockers": ["Awaiting run start"],
        "approvalHistory": [],
        "_streamStartedAt": _utc_timestamp(),
        "_executionMode": str(payload.get("executionMode", "implement")),
        "_taskPrompt": str(payload.get("prompt", "")),
        "_acceptanceCriteria": str(payload.get("acceptanceCriteria", "")),
        "_issueSnapshot": deepcopy(issue) if issue else None,
        "_documentSnapshots": deepcopy(selected_documents),
        "_requestedBySnapshot": deepcopy(current_user),
    }

    # Add the newly created run to the top of the in-memory run store.
    RUN_STORE.insert(0, new_run)

    # Return the newly created run with its integration context.
    return _build_run_extensions(
        new_run,
        issue=issue,
        documents=selected_documents,
        current_user=current_user,
    )


def create_run(
    settings: Settings,
    headers: Mapping[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Starts or restarts an AI run for an existing task."""

    integration_catalog = get_integration_catalog(settings, headers)

    # Search the in-memory run store for the task being started.
    for run in RUN_STORE:
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

            # Return the updated simulated run record.
            return _build_run_extensions(
                run,
                issue=issue,
                documents=documents,
                current_user=current_user,
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

    # Search the in-memory run store for the run being approved or redirected.
    for run in RUN_STORE:
        if run["id"] == payload["runId"]:
            approval_entry = {
                "decision": decision,
                "notes": notes,
                "actor": current_user,
                "timestamp": _utc_timestamp(),
            }
            history = list(run.get("approvalHistory", []))
            history.append(approval_entry)
            run["approvalHistory"] = history

            if decision == "approve":
                # Mark approved runs as merged in the simplified workflow.
                run["status"] = "Merged"
                run["currentStep"] = "Approved and promoted into merge flow"
            elif decision == "retry":
                # Mark retry decisions so the queue can keep tracking the task.
                run["status"] = "Retry"
                run["currentStep"] = "Awaiting another agent attempt"
            elif decision == "re-scope":
                # Mark re-scoped runs as blocked until the task definition changes.
                run["status"] = "Blocked"
                run["currentStep"] = "Waiting on updated scope"
            else:
                # Treat all other decisions as escalation to a human engineer.
                run["status"] = "Blocked"
                run["currentStep"] = "Escalated to a human engineer"

            # Return the updated run with the new approval history.
            return _build_run_extensions(run, current_user=current_user)

    # Raise a key error when the run ID cannot be found.
    raise KeyError(payload["runId"])
