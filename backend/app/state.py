"""In-memory run store and API payload facade for state-related helpers."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Mapping, Optional

from fastapi import HTTPException
from fastapi import status

from app.config import Settings
from app.mock_data import POLICY_RULES
from app.mock_data import RUN_SUMMARIES
from app.provider_cursor import CursorAgentError
from app.provider_cursor import get_cursor_agent
from app.provider_cursor import launch_cursor_agent
from app.provider_docs import list_repo_documents
from app.provider_github import fetch_github_pull_request_status
from app.provider_github import list_github_repositories
from app.provider_github import parse_github_pull_request_url
from app.provider_github import summarize_repository_names
from app.provider_github_copilot import GitHubCopilotAgentError
from app.provider_github_copilot import launch_github_copilot_agent
from app.provider_identity import get_integration_statuses
from app.provider_identity import resolve_current_user
from app.provider_jira import list_jira_issues
from app.provider_jira import update_jira_issue_status
from app.provider_linear import list_linear_issues
from app.provider_linear import update_linear_issue_status

from app import state_catalog
from app.state_cloud_agents import _extract_cloud_agent_target
from app.state_cloud_agents import _map_cursor_agent_status
from app.state_cloud_agents import _merge_cloud_agent_update
from app.state_live_views import _build_cursor_cloud_live_view
from app.state_live_views import _build_evidence_entries
from app.state_live_views import _build_github_copilot_live_view
from app.state_live_views import _build_live_view
from app.state_live_views import _build_static_live_view
from app.state_live_views import _build_static_logs
from app.state_live_views import _build_static_timeline
from app.state_live_views import _build_stream_live_view
from app.state_live_views import _build_stream_plan
from app.state_prompt import _build_cursor_docs_block
from app.state_prompt import _build_cursor_issue_block
from app.state_prompt import _build_cursor_prompt
from app.state_pull_requests import GITHUB_APPROVAL_ACTOR
from app.state_pull_requests import JIRA_STATUS_DONE
from app.state_pull_requests import JIRA_STATUS_IN_PROGRESS
from app.state_pull_requests import LINEAR_STATUS_DONE
from app.state_pull_requests import LINEAR_STATUS_IN_PROGRESS
from app.state_pull_requests import SIMULATED_PR_MERGE_DELAY_SECONDS
from app.state_pull_requests import _append_pull_request_event
from app.state_pull_requests import _approval_history_has_entry
from app.state_pull_requests import _build_pull_request_view
from app.state_pull_requests import _build_traceability_snapshot
from app.state_pull_requests import _clear_issue_tracker_sync_state
from app.state_pull_requests import _is_real_github_pull_request_url
from app.state_pull_requests import _resolve_pull_request_state
from app.state_pull_requests import _resolve_pull_request_url
from app.state_pull_requests import _simulated_pull_request_state
from app.state_pull_requests import _sync_issue_tracker_status_from_pr
from app.state_pull_requests import _sync_jira_issue_status_from_pr
from app.state_pull_requests import _sync_linear_issue_status_from_pr
from app.state_pull_requests import _sync_pull_request_status
from app.state_run_progress import _sync_run_progress
from app.state_run_mutations import apply_common_run_start
from app.state_run_mutations import build_issue_snapshot
from app.state_run_mutations import clear_previous_launch_metadata
from app.state_run_views import enrich_run_for_catalog
from app.state_run_views import enrich_runs_for_catalog
from app.state_run_views import index_runs_by_id
from app.state_time import STREAM_STEP_SECONDS
from app.state_time import _build_static_timepoints
from app.state_time import _build_step_timestamp
from app.state_time import _format_cursor_agent_runtime
from app.state_time import _format_runtime
from app.state_time import _parse_runtime_seconds
from app.state_time import _parse_timestamp
from app.state_time import _utc_now
from app.state_time import _utc_timestamp


RUN_STORE: List[Dict[str, Any]] = deepcopy(RUN_SUMMARIES)


def _normalize_team_id(team_id: str) -> str:
    """Normalizes a team identifier used for run-lobby isolation."""

    # Delegate team-id normalization to the catalog helper module.
    return state_catalog.normalize_team_id(team_id)


def _resolve_team_id_from_headers(headers: Mapping[str, str]) -> str:
    """Resolves the active team id from normalized request headers."""

    # Delegate request header parsing to the catalog helper module.
    return state_catalog.resolve_team_id_from_headers(headers)


def _run_belongs_to_team(run: Mapping[str, Any], team_id: str) -> bool:
    """Reports whether the run belongs to the requested team."""

    # Delegate team membership checks to the catalog helper module.
    return state_catalog.run_belongs_to_team(run, team_id)


def _list_team_runs(team_id: str) -> List[Dict[str, Any]]:
    """Returns all in-memory runs visible to the requested team."""

    # Delegate run filtering to the catalog helper module.
    return state_catalog.list_team_runs(RUN_STORE, team_id)


def _fallback_issues() -> List[Dict[str, Any]]:
    """Builds a fallback issue catalog from the seeded run summaries."""

    # Delegate fallback issue construction to the catalog helper module.
    return state_catalog.fallback_issues(RUN_STORE)


def _fallback_repositories(runs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Builds a fallback repository catalog from the seeded run summaries."""

    # Delegate fallback repository construction to the catalog helper module.
    return state_catalog.fallback_repositories(RUN_STORE, runs)


def _fallback_documents(settings: Settings) -> List[Dict[str, Any]]:
    """Returns repo markdown docs or an empty fallback list."""

    # Delegate document fallback handling while preserving the patchable list function.
    return state_catalog.fallback_documents(settings, list_repo_documents)


def _list_connected_issues(settings: Settings) -> List[Dict[str, Any]]:
    """Builds the combined live issue catalog across connected issue trackers."""

    # Delegate provider aggregation while preserving the patchable provider functions.
    return state_catalog.list_connected_issues(settings, list_linear_issues, list_jira_issues)


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


def _normalize_repository_context_for_api(repository: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Maps an internal repository record into the public task-detail repository context shape.

    The frontend expects camelCase keys so the control pane can deep-link GitHub metadata
    without re-querying the intake catalog on every poll.
    """

    # Delegate repository shape normalization to the catalog helper module.
    return state_catalog.normalize_repository_context_for_api(repository)


def _build_run_extensions(
    run: Dict[str, Any],
    *,
    issue: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
    current_user: Optional[Dict[str, str]] = None,
    settings: Optional[Settings] = None,
    repositories: Optional[List[Dict[str, Any]]] = None,
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
    resolved_user = deepcopy(run.get("_requestedBySnapshot")) or current_user or {
        "name": run["owner"],
        "email": f"{run['owner'].lower()}@example.com",
        "role": "admin",
        "provider": "fallback",
    }
    cloud_agent = deepcopy(run.get("_cursorAgent") or run.get("_githubCopilotAgent"))

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
    public_run["liveView"] = _build_live_view(run)
    traceability = _build_traceability_snapshot(
        run,
        issue=resolved_issue,
        pull_request=pull_request,
        approval_history=approval_history,
    )

    # Prefer the repository snapshot captured at intake so delegation context stays stable.
    repository_snapshot = run.get("_repositorySnapshot")
    repository_context = None
    if isinstance(repository_snapshot, dict) and repository_snapshot:
        # Normalize the snapshot captured when the tech lead delegated the task.
        repository_context = _normalize_repository_context_for_api(repository_snapshot)
    elif repositories:
        # Fall back to the live integration catalog when legacy runs lack a snapshot.
        matched_repository = _find_repository(repositories, str(run.get("repo", "")))
        # Normalize the matched catalog entry for the same public shape.
        repository_context = _normalize_repository_context_for_api(matched_repository)

    # Surface intake fields so task detail can show the delegated scope without hidden underscore keys.
    acceptance_criteria = str(run.get("_acceptanceCriteria", "")).strip()
    # Surface the original agent instructions separate from the short summary line.
    task_prompt = str(run.get("_taskPrompt", "")).strip()
    # Surface the execution mode chosen during intake or run restart.
    execution_mode = str(run.get("_executionMode", "implement")).strip()

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
        "traceability": traceability,
        "acceptanceCriteria": acceptance_criteria,
        "taskPrompt": task_prompt,
        "executionMode": execution_mode,
        "repositoryContext": repository_context,
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


def _build_review_effort_value(review_run_count: int, total_review_runtime_seconds: int) -> str:
    """Formats the review-effort metric from the total lobby runtime."""

    if review_run_count == 0:
        # Return a stable zero state when no lobby runs are visible.
        return "0 min"

    total_review_minutes = round(total_review_runtime_seconds / 60)

    # Return the summed runtime in minutes for the dashboard metric value.
    return f"{max(0, total_review_minutes)} min"


def _compute_metrics(runs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Computes dashboard metrics from the in-memory run state."""

    metric_runs = RUN_STORE if runs is None else runs
    active_runs = 0
    running_runs = 0
    blocked_runs = 0
    merged_runs = 0
    approved_runs = 0
    review_ready = 0
    review_effort_run_count = 0
    total_review_runtime_seconds = 0
    blocker_counts = _collect_blocker_counts()

    # Aggregate the run counts needed by the dashboard cards.
    for run in metric_runs:
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

        if str(run.get("runtime", "")).strip():
            # Sum the per-run effort shown in the lobby channel list.
            review_effort_run_count += 1
            total_review_runtime_seconds += _parse_runtime_seconds(str(run.get("runtime", "00:00")))

    review_effort_value = _build_review_effort_value(review_effort_run_count, total_review_runtime_seconds)
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
        f"Total runtime across {review_effort_run_count} run{'s' if review_effort_run_count != 1 else ''} in this lobby"
        if review_effort_run_count
        else "No runs are available to estimate review effort"
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
    runs: Optional[List[Dict[str, Any]]] = None,
    repository_names: List[str],
    integration_statuses: List[Dict[str, Any]],
) -> List[str]:
    """Builds dashboard suggestions from current run and integration state."""

    suggestion_runs = RUN_STORE if runs is None else runs
    review_ready_count = len([run for run in suggestion_runs if run.get("status") == "Review"])
    stalled_runs = len([run for run in suggestion_runs if run.get("status") in {"Blocked", "Retry"}])
    blocker_counts = _collect_blocker_counts()
    suggested_actions: List[str] = []
    top_blocker = next(iter(blocker_counts), "")
    linear_status = _find_integration_status(integration_statuses, "linear")
    jira_status = _find_integration_status(integration_statuses, "jira")
    github_status = _find_integration_status(integration_statuses, "github")
    cursor_status = _find_integration_status(integration_statuses, "cursor_cloud_agents")
    github_copilot_status = _find_integration_status(integration_statuses, "github_copilot_cloud_agent")
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
    elif github_copilot_status and not bool(github_copilot_status.get("connected")):
        # Recommend connecting Copilot when no alternate live cloud-agent surface is available.
        suggested_actions.append("Connect GitHub Copilot cloud agent so runs can assign Copilot to GitHub issues.")
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


def _catalog_team_runs(integration_catalog: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Returns team-scoped runs from an integration catalog."""

    # Delegate catalog run materialization to the catalog helper module.
    return state_catalog.catalog_team_runs(integration_catalog, RUN_STORE)


def get_dashboard_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the dashboard payload from the live-or-fallback run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = _catalog_team_runs(integration_catalog)
    repository_names = summarize_repository_names(integration_catalog["repositories"])
    runs = enrich_runs_for_catalog(
        team_runs,
        integration_catalog=integration_catalog,
        settings=settings,
        build_run_extensions=_build_run_extensions,
        sync_run_progress=_sync_run_progress,
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
    team_runs = _catalog_team_runs(integration_catalog)

    # Search the in-memory run store for the requested record.
    for run in team_runs:
        if run["id"] == run_id:
            # Return the matching run with integration context attached.
            return enrich_run_for_catalog(
                run,
                integration_catalog=integration_catalog,
                settings=settings,
                build_run_extensions=_build_run_extensions,
                sync_run_progress=_sync_run_progress,
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
    team_runs = _catalog_team_runs(integration_catalog)
    runs_by_id = index_runs_by_id(team_runs)

    resolved_runs: List[Dict[str, Any]] = []

    # Preserve the caller-provided ordering while skipping unknown IDs.
    for requested_id in run_ids:
        run = runs_by_id.get(str(requested_id))

        if run is None:
            # Skip IDs that no longer exist in the run store.
            continue

        resolved_runs.append(
            enrich_run_for_catalog(
                run,
                integration_catalog=integration_catalog,
                settings=settings,
                build_run_extensions=_build_run_extensions,
                sync_run_progress=_sync_run_progress,
            )
        )

    # Return the resolved run payloads in the requested order.
    return resolved_runs


def get_approval_payload(settings: Settings, headers: Mapping[str, str]) -> Dict[str, Any]:
    """Builds the approval inbox payload from the current run state."""

    integration_catalog = get_integration_catalog(settings, headers)
    team_runs = _catalog_team_runs(integration_catalog)
    queue: List[Dict[str, str]] = []
    enriched_runs: List[Dict[str, Any]] = []
    review_count = 0
    high_risk_count = 0
    sla_risk = 0

    # Build the review queue and queue summary from the current run store.
    for run in team_runs:
        enriched_runs.append(
            enrich_run_for_catalog(
                run,
                integration_catalog=integration_catalog,
                settings=settings,
                build_run_extensions=_build_run_extensions,
                sync_run_progress=_sync_run_progress,
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

        if not selected_documents:
            # Attach docs from the selected repo's docs folder when the UI did not send explicit IDs.
            selected_documents = list_repo_documents(settings, str(payload.get("repoName", "")))

    current_user = integration_catalog["currentUser"]
    active_team_id = str(integration_catalog.get("teamId", "default-team"))
    title = str(payload.get("title", "")).strip() or str(issue["title"] if issue else "Generated task")
    ticket = str(issue["ticket"] if issue else f"ACP-{len(RUN_STORE) + 200}")
    run_id = f"{ticket.lower()}-{_slugify(title)}"
    # Resolve the repository record so delegation briefs can show full GitHub context on task detail.
    repository_record = _find_repository(integration_catalog["repositories"], str(payload.get("repoName", "")))
    # Snapshot the repository metadata at creation time for stable audit comparisons.
    repository_snapshot = deepcopy(repository_record) if repository_record else None

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
        "_repositorySnapshot": repository_snapshot,
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
    team_runs = _catalog_team_runs(integration_catalog)

    # Search the in-memory run store for the task being started.
    for run in team_runs:
        if run["id"] == payload["taskId"]:
            issue = build_issue_snapshot(run)
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

                target_payload = _extract_cloud_agent_target(launched_agent if isinstance(launched_agent, Mapping) else {})
                apply_common_run_start(
                    run,
                    agent_name="cursor-cloud-agent",
                    current_step="Cursor Cloud Agent launched against the connected GitHub repository",
                    cost="$0.00",
                    blockers=["Cursor Cloud Agent is still running", "Reviewer controls unlock after the live agent finishes"],
                    execution_mode=str(payload.get("executionMode", "implement")),
                    stream_started_at="",
                )
                run["branch"] = str(target_payload.get("branchName", "")).strip() or run["branch"]
                run["_cursorAgent"] = launched_agent
                run["_cursorPromptSummary"] = f"Launched Cursor Cloud Agent {launched_agent.get('id', 'unknown')} for {issue.get('ticket', run['ticket'])}."
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
                    repositories=integration_catalog["repositories"],
                )

            if settings.github_copilot_token:
                repository = _find_repository(integration_catalog["repositories"], run["repo"])

                if not repository or not str(repository.get("fullName", "")).strip():
                    # Reject live launches when GitHub is not configured for the selected repository.
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Connect GitHub for the selected repository before launching GitHub Copilot cloud agent.",
                    )

                prompt_text = _build_cursor_prompt(
                    run,
                    issue=issue,
                    documents=documents,
                    repository=repository,
                )

                try:
                    launched_agent = launch_github_copilot_agent(
                        settings,
                        target_repo=str(repository["fullName"]),
                        base_ref=str(repository.get("defaultBranch", "main")),
                        prompt_text=prompt_text,
                        issue_title=str(run.get("title", run.get("summary", "AI Control Pane task"))),
                        source_issue=issue,
                    )
                except GitHubCopilotAgentError as error:
                    # Translate provider launch failures into a clear API response.
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

                target_payload = _extract_cloud_agent_target(launched_agent if isinstance(launched_agent, Mapping) else {})
                apply_common_run_start(
                    run,
                    agent_name="github-copilot-cloud-agent",
                    current_step="GitHub Copilot cloud agent assigned through the connected GitHub repository",
                    cost="$0.00",
                    blockers=["GitHub Copilot cloud agent is still running", "Reviewer controls unlock after Copilot opens a pull request"],
                    execution_mode=str(payload.get("executionMode", "implement")),
                    stream_started_at="",
                )
                run["_githubCopilotAgent"] = launched_agent
                run["_githubCopilotPromptSummary"] = f"Assigned GitHub Copilot cloud agent through issue {target_payload.get('issueUrl', target_payload.get('url', 'unknown'))}."
                _clear_issue_tracker_sync_state(run)
                run["evidence"]["commands"] = [f"POST /repos/{repository['fullName']}/issues -> {launched_agent.get('id', 'unknown')}"]
                run["evidence"]["diff"] = ["Waiting for GitHub Copilot cloud agent to produce a pull request."]
                run["evidence"]["tests"] = ["Waiting for GitHub Copilot cloud agent to report validation in the pull request."]
                run["evidence"]["rationale"] = [
                    f"Live launch assigned Copilot in {repository.get('fullName', repository.get('name', run['repo']))} using issue {issue.get('ticket', run['ticket'])}.",
                ]

                # Return the updated run record with the live Copilot metadata attached.
                return _build_run_extensions(
                    run,
                    issue=issue,
                    documents=documents,
                    current_user=current_user,
                    settings=settings,
                    repositories=integration_catalog["repositories"],
                )

            apply_common_run_start(
                run,
                agent_name=payload.get("agentName", "impl-agent"),
                current_step="Loading task context",
                cost="$0.24",
                blockers=["Streaming execution in progress", "Reviewer controls will unlock after the run completes"],
                execution_mode=str(payload.get("executionMode", "implement")),
                stream_started_at=_utc_timestamp(),
            )
            _clear_issue_tracker_sync_state(run)

            # Return the updated simulated run record.
            return _build_run_extensions(
                run,
                issue=issue,
                documents=documents,
                current_user=current_user,
                settings=settings,
                repositories=integration_catalog["repositories"],
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
    # Load the integration catalog so repository context can enrich the returned run payload.
    integration_catalog = get_integration_catalog(settings, headers)
    # Read the repository list once for every approval response builder.
    repository_catalog = integration_catalog["repositories"]

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
            return _build_run_extensions(
                run,
                current_user=current_user,
                settings=settings,
                repositories=repository_catalog,
            )

    # Raise a key error when the run ID cannot be found.
    raise KeyError(payload["runId"])
