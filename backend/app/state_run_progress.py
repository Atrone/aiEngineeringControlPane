"""Run progress synchronization for live and simulated agents."""

from typing import Any, Dict

from app.config import Settings
from app.providers import CursorAgentError


def _state():
    """Returns the public state facade for compatibility-level helper access."""

    # Import lazily to avoid circular imports while app.state loads these helper modules.
    from app import state

    # Return the facade module that owns the backward-compatible patch points.
    return state

def _sync_run_progress(run: Dict[str, Any], settings: Settings) -> None:
    """Updates a live run based on elapsed time inside the simulated stream."""

    if run.get("_cursorAgent"):
        current_status = str(run.get("status", ""))

        if current_status in {"Approved", "Blocked", "Retry", "Merged"}:
            # Preserve reviewer-driven or terminal states after the live agent has already finished.
            return

        # Poll the Cursor-backed run so the control pane reflects the latest agent status.
        try:
            latest_agent = _state().get_cursor_agent(settings, str(run["_cursorAgent"].get("id", "")))
        except CursorAgentError:
            # Keep the last known state when the Cursor status lookup fails.
            return

        previous_agent = dict(run["_cursorAgent"])
        cursor_status = str(latest_agent.get("status", "CREATING"))
        mapped_status = _state()._map_cursor_agent_status(cursor_status)
        agent_runtime_payload = _state()._merge_cloud_agent_update(previous_agent, latest_agent)
        target_payload = _state()._extract_cloud_agent_target(agent_runtime_payload)
        run["_cursorAgent"] = agent_runtime_payload
        run["status"] = mapped_status
        run["branch"] = str(target_payload.get("branchName", "")).strip() or run["branch"]
        run["runtime"] = _state()._format_cursor_agent_runtime(agent_runtime_payload, require_nonzero=cursor_status == "FINISHED")

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

    if run.get("_githubCopilotAgent"):
        current_status = str(run.get("status", ""))

        if current_status in {"Approved", "Blocked", "Retry", "Merged"}:
            # Preserve reviewer-driven or terminal states after the live agent has already finished.
            return

        cloud_agent = run.get("_githubCopilotAgent", {}) or {}
        target_payload = cloud_agent.get("target", {}) if isinstance(cloud_agent, dict) else {}
        copilot_status = str(cloud_agent.get("status", "ASSIGNED"))
        run["runtime"] = _state()._format_cursor_agent_runtime(cloud_agent, require_nonzero=False)

        if str(target_payload.get("prUrl", "")).strip():
            # Move Copilot runs to review once a pull request URL is known.
            run["status"] = "Review"
            run["currentStep"] = "GitHub Copilot cloud agent opened a pull request for review"
            run["blockers"] = ["No active blockers", "Waiting for reviewer decision"]
        else:
            # Keep Copilot runs active while GitHub works from the assigned issue.
            run["status"] = "Running"
            run["currentStep"] = f"GitHub Copilot cloud agent status: {copilot_status}"
            run["blockers"] = ["GitHub Copilot cloud agent is still running", "Reviewer controls unlock after Copilot opens a pull request"]

        return

    if run["status"] != "Running" or not run.get("_streamStartedAt"):
        # Skip progress updates when the run is not currently in the live streaming state.
        return

    started_at = _state()._parse_timestamp(str(run.get("_streamStartedAt", "")))
    step_plan = _state()._build_stream_plan(run)
    elapsed_seconds = max(0, int((_state()._utc_now() - started_at).total_seconds()))
    active_index = 0

    # Resolve the active step so the summary fields stay aligned with the stream state.
    for index, step in enumerate(step_plan):
        if elapsed_seconds >= int(step["offsetSeconds"]):
            active_index = index

    run["runtime"] = _state()._format_runtime(elapsed_seconds)
    run["cost"] = f"${0.24 + (elapsed_seconds / 18):.2f}"
    run["currentStep"] = str(step_plan[active_index]["currentStep"])
    run["blockers"] = ["Streaming execution in progress", "Reviewer controls will unlock after the run completes"]

    if elapsed_seconds >= int(step_plan[-1]["offsetSeconds"]):
        # Promote completed live runs into the review state once the final step is visible.
        run["status"] = "Review"
        run["currentStep"] = "Review package ready"
        run["blockers"] = ["No active blockers", "Waiting for reviewer decision"]
