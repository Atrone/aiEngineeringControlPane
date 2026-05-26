"""Pull-request state, issue-tracker sync, and traceability helpers."""

from copy import deepcopy
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional

from app.config import Settings


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


def _state():
    """Returns the public state facade for compatibility-level helper access."""

    # Import lazily to avoid circular imports while app.state loads these helper modules.
    from app import state

    # Return the facade module that owns the backward-compatible patch points.
    return state

def _clear_issue_tracker_sync_state(run: Dict[str, Any]) -> None:
    """Clears any cached issue-tracker sync markers from a run record."""

    # Remove the cached Linear sync marker so the next run state can resync cleanly.
    run.pop("_linearSyncedStatusName", None)

    # Remove the cached Jira sync marker so the next run state can resync cleanly.
    run.pop("_jiraSyncedStatusName", None)


def _resolve_pull_request_url(run: Dict[str, Any], settings: Optional[Settings] = None) -> str:
    """Resolves the pull-request URL recorded for the given run."""

    cloud_agent = run.get("_cursorAgent") or run.get("_githubCopilotAgent") or {}
    target_payload = _state()._extract_cloud_agent_target(cloud_agent if isinstance(cloud_agent, Mapping) else {})
    pull_request_url = str(target_payload.get("prUrl", "") or "").strip()

    if pull_request_url:
        # Prefer the live cloud-agent-created PR URL when the run was launched against GitHub.
        return pull_request_url

    # Prefer the connected GitHub owner so task detail links mirror the active integration setup.
    configured_owner = str(settings.github_owner if settings is not None else "").strip() or "example"

    # Fall back to a deterministic GitHub URL so the demo data still links somewhere.
    return f"https://github.com/{configured_owner}/{run['repo']}/pull/{run['ticket'].lower()}"


def _is_real_github_pull_request_url(pull_request_url: str) -> bool:
    """Reports whether the run is pointing at a real GitHub PR URL."""

    parsed_components = _state().parse_github_pull_request_url(pull_request_url)

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
        "title": f"{run.get('ticket', 'Run')}: {run.get('title', 'Generated task')}",
        "body": str(run.get("summary", "") or "").strip(),
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
        approved_at_datetime = _state()._parse_timestamp(approved_at_value)
        elapsed_since_approval = (_state()._utc_now() - approved_at_datetime).total_seconds()

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
    pull_request_url = _state()._resolve_pull_request_url(run, settings=settings)

    if _state()._is_real_github_pull_request_url(pull_request_url):
        # Prefer real GitHub data when the run is linked to a real repository PR.
        live_pull_request_state = _state().fetch_github_pull_request_status(settings, pull_request_url)

        if live_pull_request_state:
            # Return the live GitHub PR state so the state machine uses real events.
            return live_pull_request_state

    # Fall back to the simulated PR state for demo and offline runs.
    return _state()._simulated_pull_request_state(run)


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

    if _state()._approval_history_has_entry(history, decision, source):
        # Skip duplicate entries so repeated polling does not re-record the same event.
        return

    history.append(
        {
            "decision": decision,
            "source": source,
            "notes": notes,
            "actor": deepcopy(actor) if actor else deepcopy(GITHUB_APPROVAL_ACTOR),
            "timestamp": timestamp or _state()._utc_timestamp(),
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

    if _state().update_linear_issue_status(settings, issue_id=issue_id, status_name=pr_status_name):
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

    if _state().update_jira_issue_status(settings, issue_id=issue_id, status_name=pr_status_name):
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
    _state()._sync_linear_issue_status_from_pr(run, settings=settings, pr_state=pr_state)

    # Attempt the Jira sync path when the run originated from Jira.
    _state()._sync_jira_issue_status_from_pr(run, settings=settings, pr_state=pr_state)


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

    if run_status == "Running" and not _state()._is_real_github_pull_request_url(_state()._resolve_pull_request_url(run)):
        # Keep simulated in-flight runs in the draft state until a real GitHub PR exists.
        return {"state": "open", "merged": False, "approved": False, "source": "skipped"}

    pr_state = _state()._resolve_pull_request_state(run, settings)
    _state()._sync_issue_tracker_status_from_pr(run, settings=settings, pr_state=pr_state)

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

        _state()._append_pull_request_event(
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
        _state()._append_pull_request_event(
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
        run["_mergedAt"] = str(pr_state.get("mergedAt") or _state()._utc_timestamp())

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
    run_ticket = str(run.get("ticket") or run.get("id") or "")
    run_title = str(run.get("title") or "Untitled task")
    # Resolve the displayed PR URL with the effective settings when they are available.
    pull_request_url = _state()._resolve_pull_request_url(run, settings=settings)
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
        "number": pr_state.get("number") or run_ticket,
        "title": pr_state.get("title") or f"{run_ticket}: {run_title}",
        "body": pr_state.get("body") or run.get("summary", ""),
        "status": display_status,
        "state": resolved_state if pr_state.get("source") != "skipped" else display_status,
        "url": pr_state.get("htmlUrl") or pull_request_url,
        "merged": bool(pr_state.get("merged", False)),
        "mergedAt": pr_state.get("mergedAt"),
        "approved": bool(pr_state.get("approved", False)),
        "approvedAt": pr_state.get("approvedAt"),
        "approvedBy": pr_state.get("approvedBy"),
        "reviewInProgress": bool(pr_state.get("reviewInProgress", False)),
        "reviewActivityAt": pr_state.get("reviewActivityAt"),
        "reviewActivityBy": pr_state.get("reviewActivityBy"),
        "reviewActivityState": pr_state.get("reviewActivityState"),
        "source": pr_state.get("source", "simulated"),
    }


def _build_traceability_snapshot(
    run: Dict[str, Any],
    *,
    issue: Dict[str, Any],
    pull_request: Dict[str, Any],
    approval_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Builds a compact traceability summary for task-detail review handoff."""

    evidence = run.get("evidence", {}) if isinstance(run.get("evidence"), dict) else {}
    live_view = run.get("liveView", {}) if isinstance(run.get("liveView"), dict) else {}
    evidence_tabs = live_view.get("evidenceTabs", {}) if isinstance(live_view, dict) else {}
    latest_decision = ""

    if approval_history:
        # Capture the latest reviewer or provider decision for the traceability summary.
        latest_decision = str(approval_history[-1].get("decision", "")).strip()

    captured_evidence_count = 0

    # Count the static evidence strings currently attached to the run payload.
    for evidence_key in ("diff", "tests", "commands", "rationale"):
        captured_evidence_count += len(list(evidence.get(evidence_key, [])))

    # Count live evidence tab entries so streaming runs expose the same evidence metric.
    for evidence_key in ("diff", "tests", "rationale"):
        captured_evidence_count += len(list(evidence_tabs.get(evidence_key, [])))

    issue_status_at_launch = str(issue.get("status", "")).strip()

    # Return a normalized traceability snapshot for task detail rendering.
    return {
        "ticket": str(run.get("ticket", "")).strip(),
        "issueProvider": str(issue.get("provider", "fallback")).strip() or "fallback",
        "issueStatusAtLaunch": issue_status_at_launch,
        "runStatus": str(run.get("status", "")).strip(),
        "pullRequestStatus": str(pull_request.get("status", "draft")).strip(),
        "pullRequestSource": str(pull_request.get("source", "simulated")).strip(),
        "capturedEvidenceCount": captured_evidence_count,
        "latestDecision": latest_decision,
        "preservedFromInProgress": issue_status_at_launch.lower() == "in progress",
    }
