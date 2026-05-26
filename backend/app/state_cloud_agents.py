"""Cloud-agent payload normalization helpers."""

from typing import Any, Dict, Mapping


def _extract_cloud_agent_target(cloud_agent: Mapping[str, Any]) -> Dict[str, Any]:
    """Returns a normalized target payload from a cloud-agent record."""

    target_payload = cloud_agent.get("target", {}) if isinstance(cloud_agent, Mapping) else {}

    if isinstance(target_payload, Mapping):
        # Copy the target so callers can read it without mutating provider payloads.
        return dict(target_payload)

    # Treat null or malformed target values as missing metadata instead of crashing polling.
    return {}


def _merge_cloud_agent_update(previous_agent: Mapping[str, Any], latest_agent: Mapping[str, Any]) -> Dict[str, Any]:
    """Merges a provider status update without dropping previously known PR target data."""

    merged_agent = dict(previous_agent)
    latest_agent_payload = dict(latest_agent)
    previous_target = _extract_cloud_agent_target(previous_agent)
    latest_target = _extract_cloud_agent_target(latest_agent_payload)

    # Apply the latest provider fields while keeping a mutable copy for normalization.
    merged_agent.update(latest_agent_payload)

    if latest_target:
        # Prefer fresh PR metadata when the provider includes a structured target payload.
        merged_agent["target"] = latest_target
    elif previous_target:
        # Preserve the launch-time PR target when later status polls omit or null it.
        merged_agent["target"] = previous_target
    else:
        # Remove malformed target metadata so downstream URL resolution can use its fallback.
        merged_agent.pop("target", None)

    # Return the normalized cloud-agent record stored with the run.
    return merged_agent


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
