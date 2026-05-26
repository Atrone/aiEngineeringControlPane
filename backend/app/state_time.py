"""Time and runtime helpers for in-memory run simulation."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional


STREAM_STEP_SECONDS = 4


def _state():
    """Returns the public state facade so compatibility patches stay effective."""

    # Import lazily to avoid circular imports while app.state re-exports these helpers.
    from app import state

    # Return the facade module that owns backward-compatible helper names.
    return state


def _utc_now() -> datetime:
    """Returns the current UTC time used for live run simulation."""

    # Use a timezone-aware clock so generated timeline timestamps stay consistent.
    return _state().datetime.now(timezone.utc)


def _utc_timestamp() -> str:
    """Builds an ISO timestamp for generated task and approval records."""

    # Return a consistent UTC timestamp for in-memory audit events.
    return _state()._utc_now().isoformat()


def _parse_timestamp(value: Optional[str]) -> datetime:
    """Parses an ISO timestamp into a timezone-aware UTC datetime."""

    if not value:
        # Fall back to the current UTC time when no timestamp is present.
        return _state()._utc_now()

    normalized_value = value.replace("Z", "+00:00")

    try:
        parsed_timestamp = _state().datetime.fromisoformat(normalized_value)
    except ValueError:
        # Fall back to the current UTC time when the stored value is malformed.
        return _state()._utc_now()

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
    created_at = _state()._parse_timestamp(str(agent.get("createdAt", "")))
    elapsed_seconds = max(0, int((_state()._utc_now() - created_at).total_seconds()))

    if require_nonzero:
        # Finished review handoffs should not display as a zero-second review runtime.
        elapsed_seconds = max(1, elapsed_seconds)

    # Return the shared mm:ss display string used by dashboard and run-room views.
    return _state()._format_runtime(elapsed_seconds)


def _build_step_timestamp(started_at: datetime, offset_seconds: int) -> str:
    """Builds an ISO timestamp for a simulated run step."""

    # Offset the run start time so every timeline entry has a concrete timestamp.
    return (started_at + timedelta(seconds=offset_seconds)).isoformat()


def _build_static_timepoints(runtime_value: str, count: int) -> List[str]:
    """Builds evenly spaced ISO timestamps for a non-streaming run view."""

    total_items = max(1, count)
    total_seconds = max(total_items - 1, _state()._parse_runtime_seconds(runtime_value))
    started_at = _state()._utc_now() - timedelta(seconds=total_seconds)
    step_span = total_seconds / max(1, total_items - 1)
    timepoints: List[str] = []

    # Spread timestamps across the recorded runtime so static views still feel chronological.
    for index in range(total_items):
        timepoints.append(_state()._build_step_timestamp(started_at, int(round(index * step_span))))

    # Return the generated timestamp list for the caller.
    return timepoints
