"""Cursor Cloud Agents provider adapter."""

import base64
import json
from typing import Any, Dict
from urllib.error import HTTPError, URLError

from app.config import Settings
from app.provider_common import _extract_provider_error_message
from app.provider_common import _request_json
from app.provider_common import normalize_cursor_api_key


class CursorAgentError(Exception):
    """Captures a readable Cursor Cloud Agents API failure."""


def _build_cursor_headers(api_key: str) -> Dict[str, str]:
    """Builds the authenticated request headers for the Cursor Cloud Agents API."""

    token_bytes = f"{normalize_cursor_api_key(api_key)}:".encode("utf-8")
    authorization_value = base64.b64encode(token_bytes).decode("utf-8")

    # Return the shared Cursor API headers with basic-auth credentials applied.
    return {
        "Authorization": f"Basic {authorization_value}",
        "Content-Type": "application/json",
    }


def is_cursor_connected(settings: Settings) -> bool:
    """Checks whether the configured Cursor credentials can authenticate successfully."""

    normalized_api_key = normalize_cursor_api_key(settings.cursor_api_key)

    if not normalized_api_key:
        # Report no live connection when Cursor has not been configured yet.
        return False

    try:
        response = _request_json(
            "https://api.cursor.com/v0/me",
            headers=_build_cursor_headers(normalized_api_key),
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Report no live connection when the auth check request fails.
        return False

    # Report a live connection only when Cursor returns the API key owner identity.
    return bool(str(response.get("userEmail", "")).strip())


def launch_cursor_agent(
    settings: Settings,
    *,
    repository_url: str,
    base_ref: str,
    branch_name: str,
    prompt_text: str,
) -> Dict[str, Any]:
    """Launches a Cursor Cloud Agent against the requested GitHub repository."""

    normalized_api_key = normalize_cursor_api_key(settings.cursor_api_key)

    if not normalized_api_key:
        # Reject launch attempts when the Cursor API key has not been configured.
        raise CursorAgentError("Connect Cursor Cloud Agents before launching a live agent.")

    payload = {
        "prompt": {
            "text": prompt_text,
        },
        "model": settings.cursor_model or "default",
        "source": {
            "repository": repository_url,
            "ref": base_ref,
        },
        "target": {
            "autoCreatePr": True,
            "branchName": branch_name,
        },
    }

    try:
        response = _request_json(
            "https://api.cursor.com/v0/agents",
            method="POST",
            headers=_build_cursor_headers(normalized_api_key),
            payload=payload,
        )
    except HTTPError as error:
        # Surface the upstream Cursor API error message with a product-specific prefix.
        raise CursorAgentError(f"Cursor Cloud Agents launch failed: {_extract_provider_error_message(error)}") from error
    except (URLError, json.JSONDecodeError) as error:
        # Surface transport and parsing failures with a stable product-specific message.
        raise CursorAgentError("Cursor Cloud Agents launch failed because the API response could not be read.") from error

    # Return the launch response so callers can persist the created agent metadata.
    return response


def get_cursor_agent(settings: Settings, agent_id: str) -> Dict[str, Any]:
    """Fetches the latest Cursor Cloud Agent status payload for a running agent."""

    normalized_api_key = normalize_cursor_api_key(settings.cursor_api_key)

    if not normalized_api_key:
        # Reject status lookups when the Cursor API key has not been configured.
        raise CursorAgentError("Connect Cursor Cloud Agents before checking live agent status.")

    try:
        response = _request_json(
            f"https://api.cursor.com/v0/agents/{agent_id}",
            headers=_build_cursor_headers(normalized_api_key),
        )
    except HTTPError as error:
        # Surface the upstream Cursor API error message with a product-specific prefix.
        raise CursorAgentError(f"Cursor Cloud Agents status lookup failed: {_extract_provider_error_message(error)}") from error
    except (URLError, json.JSONDecodeError) as error:
        # Surface transport and parsing failures with a stable product-specific message.
        raise CursorAgentError("Cursor Cloud Agents status lookup failed because the API response could not be read.") from error

    # Return the latest agent payload so callers can map it into app state.
    return response
