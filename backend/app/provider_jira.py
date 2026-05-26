"""Jira Cloud provider adapter for connectivity, issue listing, and transitions."""

import base64
import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings
from app.provider_common import _request_json
from app.provider_common import normalize_jira_site_url

# Fallback Jira status categories used when project-specific transition names differ.
_JIRA_STATUS_CATEGORY_BY_STATUS_NAME: Dict[str, str] = {
    "in progress": "in progress",
    "done": "done",
}


def _build_jira_headers(settings: Settings) -> Dict[str, str]:
    """Builds the authenticated request headers for Jira Cloud REST API calls."""

    token_bytes = f"{settings.jira_email}:{settings.jira_api_token}".encode("utf-8")
    authorization_value = base64.b64encode(token_bytes).decode("utf-8")

    # Return the shared Jira REST headers with basic-auth credentials applied.
    return {
        "Authorization": f"Basic {authorization_value}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request_jira_json(
    settings: Settings,
    *,
    path: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Executes a Jira Cloud REST request and returns the parsed JSON payload."""

    normalized_site_url = normalize_jira_site_url(settings.jira_site_url)

    if not normalized_site_url or not settings.jira_email or not settings.jira_api_token:
        # Skip Jira calls entirely when the required credentials are incomplete.
        return None

    try:
        # Submit the Jira REST request using the shared authenticated headers.
        return _request_json(
            f"{normalized_site_url}/rest/api/3{path}",
            method=method,
            headers=_build_jira_headers(settings),
            payload=payload,
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return no payload when Jira rejects or fails the request.
        return None


def _request_jira_transition_update(
    settings: Settings,
    *,
    issue_id: str,
    transition_id: str,
) -> bool:
    """Executes a Jira issue transition request and reports whether it succeeded."""

    normalized_site_url = normalize_jira_site_url(settings.jira_site_url)

    if not normalized_site_url or not settings.jira_email or not settings.jira_api_token:
        # Skip transition requests when the Jira credentials are incomplete.
        return False

    encoded_payload = json.dumps({"transition": {"id": transition_id}}).encode("utf-8")
    request = Request(
        f"{normalized_site_url}/rest/api/3/issue/{issue_id}/transitions",
        data=encoded_payload,
        headers=_build_jira_headers(settings),
        method="POST",
    )

    try:
        with urlopen(request, timeout=12) as response:
            # Treat Jira's 2xx transition responses as success, even when the body is empty.
            return 200 <= getattr(response, "status", 0) < 300
    except (HTTPError, URLError):
        # Report failure when Jira rejects or fails the transition request.
        return False


def is_jira_connected(settings: Settings) -> bool:
    """Checks whether the configured Jira Cloud credentials can authenticate successfully."""

    response = _request_jira_json(settings, path="/myself")

    if not response:
        # Report no live connection when the Jira auth check request fails.
        return False

    # Report a live connection only when Jira returns the authenticated account identity.
    return bool(str(response.get("accountId", "")).strip())


def _build_jira_search_jql(project_key: str) -> str:
    """Builds the Jira JQL used to fetch the visible issue catalog."""

    normalized_project_key = project_key.strip().upper()

    if not normalized_project_key:
        # Return the unscoped JQL when no Jira project filter was configured.
        return "ORDER BY updated DESC"

    escaped_project_key = normalized_project_key.replace('"', '\\"')

    # Return the project-scoped JQL when the operator configured a Jira project key.
    return f'project = "{escaped_project_key}" ORDER BY updated DESC'


def _extract_jira_description_text(description_payload: Any) -> str:
    """Extracts plain text from Jira's nested Atlassian Document Format payloads."""

    if isinstance(description_payload, str):
        # Return plain-string descriptions directly when Jira already flattened the field.
        return description_payload.strip()

    if isinstance(description_payload, list):
        text_parts: List[str] = []

        # Recursively flatten each list item so nested text blocks are preserved.
        for item in description_payload:
            item_text = _extract_jira_description_text(item)

            if item_text:
                # Keep non-empty child text fragments in their original order.
                text_parts.append(item_text)

        # Join the flattened child text into a readable paragraph block.
        return "\n".join(text_parts).strip()

    if isinstance(description_payload, dict):
        text_parts = []
        node_text = str(description_payload.get("text", "")).strip()

        if node_text:
            # Preserve the current node's text content before walking its children.
            text_parts.append(node_text)

        child_content = description_payload.get("content", [])

        if isinstance(child_content, list):
            # Recursively flatten nested content nodes inside the Jira description document.
            for child_item in child_content:
                child_text = _extract_jira_description_text(child_item)

                if child_text:
                    # Keep each non-empty child text fragment in output order.
                    text_parts.append(child_text)

        # Join the node text and child content into a single plain-text description.
        return "\n".join(text_parts).strip()

    # Return an empty string when the Jira description payload uses an unknown shape.
    return ""


def _normalize_jira_priority(fields: Dict[str, Any]) -> str:
    """Builds the shared priority string from a Jira issue fields payload."""

    priority_payload = fields.get("priority")

    if isinstance(priority_payload, dict):
        priority_name = str(priority_payload.get("name", "")).strip()

        if priority_name:
            # Prefer the human-readable Jira priority label when one is present.
            return priority_name

    # Fall back to a neutral priority when Jira omits the field.
    return "Medium"


def _normalize_jira_assignee(fields: Dict[str, Any]) -> Dict[str, str]:
    """Builds the shared assignee payload from a Jira issue fields payload."""

    assignee_payload = fields.get("assignee")

    if not isinstance(assignee_payload, dict):
        # Return an empty assignee object when Jira omits the assignee field.
        return {}

    display_name = str(assignee_payload.get("displayName", "")).strip()
    email_address = str(assignee_payload.get("emailAddress", "")).strip()

    # Return the normalized assignee shape consumed by the frontend.
    return {
        "name": display_name,
        "email": email_address,
    }


def list_jira_issues(settings: Settings) -> List[Dict[str, Any]]:
    """Lists Jira Cloud issues from live configuration or returns an empty list."""

    response = _request_jira_json(
        settings,
        path="/search/jql",
        method="POST",
        payload={
            "jql": _build_jira_search_jql(settings.jira_project_key),
            "maxResults": 20,
            "fields": [
                "summary",
                "description",
                "priority",
                "status",
                "assignee",
            ],
        },
    )

    if not response:
        # Return no live issue records when Jira is not configured or the search fails.
        return []

    issue_payloads = response.get("issues", [])

    if not isinstance(issue_payloads, list):
        # Return no live issue records when Jira returns an unexpected issues payload.
        return []

    normalized_site_url = normalize_jira_site_url(settings.jira_site_url)
    issues: List[Dict[str, Any]] = []

    # Normalize each Jira issue into the app's shared issue shape.
    for issue_payload in issue_payloads:
        if not isinstance(issue_payload, dict):
            # Skip malformed Jira issue rows so one bad record does not poison the catalog.
            continue

        fields = issue_payload.get("fields", {})

        if not isinstance(fields, dict):
            # Skip issues that do not expose the expected Jira fields payload.
            continue

        status_payload = fields.get("status", {})
        status_name = ""

        if isinstance(status_payload, dict):
            # Read the Jira status display name when the provider returned one.
            status_name = str(status_payload.get("name", "")).strip()

        issue_key = str(issue_payload.get("key", "")).strip()
        issues.append(
            {
                "id": str(issue_payload.get("id", "")).strip(),
                "ticket": issue_key,
                "title": str(fields.get("summary", "")).strip(),
                "description": _extract_jira_description_text(fields.get("description")),
                "priority": _normalize_jira_priority(fields),
                "status": status_name or "To Do",
                "url": f"{normalized_site_url}/browse/{issue_key}" if normalized_site_url and issue_key else "",
                "assignee": _normalize_jira_assignee(fields),
                "provider": "jira",
            }
        )

    # Return the normalized Jira issue list.
    return issues


def _extract_jira_status_category_name(status_payload: Dict[str, Any]) -> str:
    """Extracts the normalized Jira status-category name from a status-like payload."""

    status_category_payload = status_payload.get("statusCategory")

    if not isinstance(status_category_payload, dict):
        # Return an empty category when Jira omits the status category field.
        return ""

    # Return the lower-cased Jira status-category name for fallback matching.
    return str(status_category_payload.get("name", "")).strip().lower()


def _find_jira_transition(transition_payloads: List[Dict[str, Any]], status_name: str) -> Optional[Dict[str, Any]]:
    """Finds the best Jira transition matching the requested public status name."""

    normalized_status_name = status_name.strip().lower()
    target_status_category = _JIRA_STATUS_CATEGORY_BY_STATUS_NAME.get(normalized_status_name, "")

    # Prefer an exact case-insensitive transition or destination-status name match.
    for transition_payload in transition_payloads:
        transition_name = str(transition_payload.get("name", "")).strip().lower()
        destination_status = transition_payload.get("to", {})
        destination_status_name = ""

        if isinstance(destination_status, dict):
            # Read the destination status label so project-specific transition names can still match.
            destination_status_name = str(destination_status.get("name", "")).strip().lower()

        if transition_name == normalized_status_name or destination_status_name == normalized_status_name:
            # Return the exact Jira transition match immediately.
            return transition_payload

    if target_status_category:
        # Fall back to the Jira status category when project-specific names differ.
        for transition_payload in transition_payloads:
            destination_status = transition_payload.get("to", {})

            if not isinstance(destination_status, dict):
                # Skip malformed transition payloads that lack a usable destination status.
                continue

            if _extract_jira_status_category_name(destination_status) == target_status_category:
                # Return the first transition whose destination category matches the requested status.
                return transition_payload

    # Return no transition when neither the name nor category lookup found a match.
    return None


def update_jira_issue_status(settings: Settings, *, issue_id: str, status_name: str) -> bool:
    """Updates a Jira issue into the requested workflow state when possible."""

    normalized_issue_id = issue_id.strip()
    normalized_status_name = status_name.strip()

    if not normalized_issue_id or not normalized_status_name:
        # Skip updates that do not identify both an issue and a target status.
        return False

    issue_response = _request_jira_json(
        settings,
        path=f"/issue/{normalized_issue_id}?fields=status",
    )

    if not issue_response:
        # Stop when the current Jira issue state could not be loaded.
        return False

    fields_payload = issue_response.get("fields", {})

    if not isinstance(fields_payload, dict):
        # Stop when Jira omits the issue fields envelope.
        return False

    current_status_payload = fields_payload.get("status", {})

    if not isinstance(current_status_payload, dict):
        # Stop when the Jira issue status payload is missing or malformed.
        return False

    current_status_name = str(current_status_payload.get("name", "")).strip()
    current_status_category = _extract_jira_status_category_name(current_status_payload)
    target_status_category = _JIRA_STATUS_CATEGORY_BY_STATUS_NAME.get(normalized_status_name.lower(), "")

    if current_status_name.lower() == normalized_status_name.lower():
        # Treat the update as successful when the issue is already in the target status.
        return True

    if target_status_category and current_status_category == target_status_category:
        # Treat the update as successful when Jira already reports the matching status category.
        return True

    transitions_response = _request_jira_json(
        settings,
        path=f"/issue/{normalized_issue_id}/transitions",
    )

    if not transitions_response:
        # Stop when Jira does not return the available transitions for the issue.
        return False

    transition_payloads = transitions_response.get("transitions", [])

    if not isinstance(transition_payloads, list):
        # Stop when Jira returns an unexpected transitions payload.
        return False

    normalized_transition_payloads = [
        transition_payload
        for transition_payload in transition_payloads
        if isinstance(transition_payload, dict)
    ]
    matched_transition = _find_jira_transition(normalized_transition_payloads, normalized_status_name)

    if not matched_transition:
        # Stop when Jira does not expose a transition matching the requested public status.
        return False

    transition_id = str(matched_transition.get("id", "")).strip()

    if not transition_id:
        # Stop when the matched Jira transition does not expose a concrete ID.
        return False

    # Return the Jira transition result so callers can avoid duplicate retries.
    return _request_jira_transition_update(
        settings,
        issue_id=normalized_issue_id,
        transition_id=transition_id,
    )
