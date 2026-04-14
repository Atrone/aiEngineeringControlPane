"""In-memory application state that mixes live integrations with safe fallbacks."""

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Mapping, Optional

from app.config import Settings
from app.mock_data import POLICY_RULES
from app.mock_data import RUN_SUMMARIES
from app.providers import get_integration_statuses
from app.providers import list_github_repositories
from app.providers import list_linear_issues
from app.providers import list_repo_documents
from app.providers import resolve_current_user
from app.providers import summarize_repository_names


RUN_STORE: List[Dict[str, Any]] = deepcopy(RUN_SUMMARIES)


def _utc_timestamp() -> str:
    """Builds an ISO timestamp for generated task and approval records."""

    # Return a consistent UTC timestamp for in-memory audit events.
    return datetime.now(timezone.utc).isoformat()


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


def _build_run_extensions(
    run: Dict[str, Any],
    *,
    issue: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
    current_user: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adds integration context fields to a run record."""

    attached_documents = documents or []
    resolved_issue = issue or {
        "id": run["id"],
        "ticket": run["ticket"],
        "title": run["title"],
        "status": run["status"],
        "provider": "fallback",
        "url": "",
    }
    resolved_user = current_user or {
        "name": run["owner"],
        "email": f"{run['owner'].lower()}@example.com",
        "role": "tech_lead",
        "provider": "fallback",
    }

    pull_request = {
        "number": run["ticket"],
        "status": "draft" if run["status"] == "Running" else "ready_for_review",
        "url": f"https://github.com/example/{run['repo']}/pull/{run['ticket'].lower()}",
    }
    ci_status = {
        "workflow": "CI",
        "status": "blocked" if run["status"] == "Blocked" else "passed",
        "summary": run["currentStep"],
    }
    approval_history = run.get("approvalHistory", [])

    # Return the run plus normalized integration context fields.
    return {
        **run,
        "issue": resolved_issue,
        "pullRequest": pull_request,
        "ci": ci_status,
        "documents": attached_documents,
        "requestedBy": resolved_user,
        "approvalHistory": approval_history,
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


def create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Starts or restarts an AI run for an existing task."""

    # Search the in-memory run store for the task being started.
    for run in RUN_STORE:
        if run["id"] == payload["taskId"]:
            run["status"] = "Running"
            run["agent"] = payload.get("agentName", "impl-agent")
            run["currentStep"] = f"Run started in {payload.get('executionMode', 'implement')} mode"

            # Return the updated run record.
            return deepcopy(run)

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
