"""Shared provider utilities for HTTP, timestamps, and credential normalization."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, Mapping, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _utc_timestamp() -> str:
    """Builds an ISO timestamp for provider status payloads."""

    # Return a consistent UTC timestamp for integration status snapshots.
    return datetime.now(timezone.utc).isoformat()


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes a JSON HTTP request for a provider API call."""

    encoded_payload = None

    if payload is not None:
        # Encode the JSON payload for APIs that expect a request body.
        encoded_payload = json.dumps(payload).encode("utf-8")

    request_headers = {"Accept": "application/json"}

    if headers:
        # Merge caller-provided headers into the base JSON request headers.
        request_headers.update(headers)

    request = Request(url, data=encoded_payload, headers=request_headers, method=method)

    with urlopen(request, timeout=12) as response:
        # Decode the provider response body into a Python dictionary.
        return json.loads(response.read().decode("utf-8"))


def normalize_linear_api_key(api_key: str) -> str:
    """Normalizes a pasted Linear API key into the raw token format Linear expects."""

    normalized_api_key = api_key.strip()

    if normalized_api_key.lower().startswith("bearer "):
        # Drop an accidental bearer prefix because Linear personal keys are sent raw.
        return normalized_api_key[7:].strip()

    # Return the caller-provided key when no prefix cleanup is needed.
    return normalized_api_key


def normalize_jira_site_url(site_url: str) -> str:
    """Normalizes a Jira Cloud site URL into the canonical base URL format."""

    normalized_site_url = site_url.strip().rstrip("/")

    if not normalized_site_url:
        # Return an empty value when the caller did not provide a site URL.
        return ""

    if normalized_site_url.lower().startswith(("https://", "http://")):
        # Preserve an already-qualified Jira base URL after trimming trailing slashes.
        return normalized_site_url

    # Default to HTTPS so pasted Jira subdomains become valid Cloud base URLs.
    return f"https://{normalized_site_url.lstrip('/')}"


def normalize_cursor_api_key(api_key: str) -> str:
    """Normalizes a pasted Cursor API key into the raw token format Cursor expects."""

    normalized_api_key = api_key.strip()

    if normalized_api_key.lower().startswith("bearer "):
        # Drop an accidental bearer prefix because Cursor API keys are sent via basic auth.
        return normalized_api_key[7:].strip()

    # Return the caller-provided key when no prefix cleanup is needed.
    return normalized_api_key


def normalize_github_copilot_token(token: str) -> str:
    """Normalizes a pasted GitHub token for Copilot cloud agent API calls."""

    normalized_token = token.strip()

    if normalized_token.lower().startswith("bearer "):
        # Drop an accidental bearer prefix because the header builder adds it.
        return normalized_token[7:].strip()

    # Return the caller-provided token when no prefix cleanup is needed.
    return normalized_token


def _extract_provider_error_message(error: HTTPError) -> str:
    """Extracts a readable provider error message from an HTTP error response body."""

    try:
        error_payload = json.loads(error.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        # Fall back to the HTTP status text when the provider body is unreadable.
        return f"{error.code} {error.reason}"

    if isinstance(error_payload, dict):
        message = error_payload.get("message")

        if isinstance(message, str) and message.strip():
            # Return the top-level provider error message when it is present.
            return message.strip()

        errors = error_payload.get("errors")

        if isinstance(errors, list) and errors:
            first_error = errors[0]

            if isinstance(first_error, dict):
                nested_message = first_error.get("message")

                if isinstance(nested_message, str) and nested_message.strip():
                    # Return the first nested provider error message when available.
                    return nested_message.strip()

    # Fall back to the HTTP status text when the provider payload has no message field.
    return f"{error.code} {error.reason}"
