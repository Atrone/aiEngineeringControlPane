"""Provider adapters for GitHub, Linear, repo docs, and identity resolution."""

import base64
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import Settings


# Pattern matching GitHub pull-request URLs so we can extract owner/repo/number.
_GITHUB_PR_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

# Fallback Linear workflow-state types used when team-specific names differ.
_LINEAR_STATE_TYPE_BY_STATUS_NAME: Dict[str, str] = {
    "in progress": "started",
    "done": "completed",
}

# Fallback Jira status categories used when project-specific transition names differ.
_JIRA_STATUS_CATEGORY_BY_STATUS_NAME: Dict[str, str] = {
    "in progress": "in progress",
    "done": "done",
}


class CursorAgentError(Exception):
    """Captures a readable Cursor Cloud Agents API failure."""


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


def _build_cursor_headers(api_key: str) -> Dict[str, str]:
    """Builds the authenticated request headers for the Cursor Cloud Agents API."""

    token_bytes = f"{normalize_cursor_api_key(api_key)}:".encode("utf-8")
    authorization_value = base64.b64encode(token_bytes).decode("utf-8")

    # Return the shared Cursor API headers with basic-auth credentials applied.
    return {
        "Authorization": f"Basic {authorization_value}",
        "Content-Type": "application/json",
    }


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


def is_linear_connected(settings: Settings) -> bool:
    """Checks whether the configured Linear credentials can authenticate successfully."""

    normalized_api_key = normalize_linear_api_key(settings.linear_api_key)

    if not normalized_api_key:
        # Report no live connection when Linear has not been configured yet.
        return False

    headers = {
        "Authorization": normalized_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "query": """
        query ControlPaneViewer {
          viewer {
            id
          }
        }
        """,
    }

    try:
        response = _request_json(
            "https://api.linear.app/graphql",
            method="POST",
            headers=headers,
            payload=payload,
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Report no live connection when the auth check request fails.
        return False

    data = response.get("data")

    if not isinstance(data, dict):
        # Report no live connection when Linear returns a malformed payload.
        return False

    viewer = data.get("viewer")

    if not isinstance(viewer, dict):
        # Report no live connection when the auth check did not return a viewer object.
        return False

    # Report a live connection only when the viewer payload includes a concrete identifier.
    return bool(str(viewer.get("id", "")).strip())


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


def _build_linear_issue_query(team_field: Optional[str] = None) -> str:
    """Builds the Linear issues query for either unscoped or team-scoped issue reads."""

    if not team_field:
        # Return the unscoped issue query when no team filter was requested.
        return """
        query ControlPaneIssues {
          issues(first: 20) {
            nodes {
              id
              identifier
              title
              description
              priority
              url
              state {
                name
              }
              assignee {
                name
                email
              }
            }
          }
        }
        """

    # Return the legacy scoped issue query for the requested team field.
    return f"""
    query ControlPaneIssues($teamScope: String!) {{
      issues(first: 20, filter: {{ team: {{ {team_field}: {{ eq: $teamScope }} }} }}) {{
        nodes {{
          id
          identifier
          title
          description
          priority
          url
          state {{
            name
          }}
          assignee {{
            name
            email
          }}
        }}
      }}
    }}
    """


def _build_linear_team_lookup_query(team_field: str, comparator: str = "eq") -> str:
    """Builds a Linear team lookup query for a specific team field and comparator."""

    variable_type = "ID!" if team_field == "id" else "String!"

    # Return the team lookup query for the requested field match strategy.
    return f"""
    query ControlPaneTeams($teamScope: {variable_type}) {{
      teams(filter: {{ {team_field}: {{ {comparator}: $teamScope }} }}, first: 1) {{
        nodes {{
          id
          key
          name
        }}
      }}
    }}
    """


def _build_linear_team_issue_query() -> str:
    """Builds the Linear query that reads issues from a resolved team record."""

    # Return the team-scoped issue query that traverses the team relation directly.
    return """
    query ControlPaneTeamIssues($teamId: String!) {
      team(id: $teamId) {
        id
        issues(first: 20) {
          nodes {
            id
            identifier
            title
            description
            priority
            url
            state {
              name
            }
            assignee {
              name
              email
            }
          }
        }
      }
    }
    """


def _extract_linear_issue_nodes(response: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Extracts the Linear issue node list from a GraphQL response payload."""

    data = response.get("data")

    if not isinstance(data, dict):
        # Return no nodes when Linear omits the GraphQL data envelope.
        return None

    issues_payload = data.get("issues")

    if not isinstance(issues_payload, dict):
        # Return no nodes when the issues envelope is missing or malformed.
        return None

    nodes = issues_payload.get("nodes", [])

    if not isinstance(nodes, list):
        # Return no nodes when Linear returns an unexpected nodes payload.
        return None

    # Return the parsed node list when the response shape is valid.
    return nodes


def _extract_linear_team_node(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts the first matching Linear team node from a GraphQL response payload."""

    data = response.get("data")

    if not isinstance(data, dict):
        # Return no team when Linear omits the GraphQL data envelope.
        return None

    teams_payload = data.get("teams")

    if not isinstance(teams_payload, dict):
        # Return no team when the teams envelope is missing or malformed.
        return None

    nodes = teams_payload.get("nodes", [])

    if not isinstance(nodes, list) or not nodes:
        # Return no team when the lookup produced no matching team nodes.
        return None

    team = nodes[0]

    if not isinstance(team, dict):
        # Return no team when the first team node is malformed.
        return None

    # Return the resolved team node for later team-scoped issue queries.
    return team


def _extract_linear_team_issue_nodes(response: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Extracts issue nodes from a team-scoped Linear GraphQL response payload."""

    data = response.get("data")

    if not isinstance(data, dict):
        # Return no nodes when Linear omits the GraphQL data envelope.
        return None

    team = data.get("team")

    if not isinstance(team, dict):
        # Return no nodes when the team envelope is missing or malformed.
        return None

    issues_payload = team.get("issues")

    if not isinstance(issues_payload, dict):
        # Return no nodes when the nested issues envelope is missing or malformed.
        return None

    nodes = issues_payload.get("nodes", [])

    if not isinstance(nodes, list):
        # Return no nodes when Linear returns an unexpected nodes payload.
        return None

    # Return the parsed team issue node list when the response shape is valid.
    return nodes


def _build_linear_headers(settings: Settings) -> Dict[str, str]:
    """Builds the authenticated headers used for Linear GraphQL requests."""

    normalized_api_key = normalize_linear_api_key(settings.linear_api_key)

    # Return the shared Linear GraphQL headers with the normalized API key attached.
    return {
        "Authorization": normalized_api_key,
        "Content-Type": "application/json",
    }


def _request_linear_graphql(
    settings: Settings,
    *,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Executes a Linear GraphQL request and returns the parsed response payload."""

    if not settings.linear_api_key:
        # Skip the request entirely when Linear has not been configured.
        return None

    request_payload: Dict[str, Any] = {"query": query}

    if variables:
        # Attach GraphQL variables only when the caller supplied them.
        request_payload["variables"] = variables

    try:
        # Submit the GraphQL request to Linear using the shared auth headers.
        return _request_json(
            "https://api.linear.app/graphql",
            method="POST",
            headers=_build_linear_headers(settings),
            payload=request_payload,
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return no payload when Linear rejects or fails the request.
        return None


def _extract_linear_issue_state_catalog(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts the current Linear issue state and the team's available states."""

    data = response.get("data")

    if not isinstance(data, dict):
        # Return no catalog when Linear omits the GraphQL data envelope.
        return None

    issue_payload = data.get("issue")

    if not isinstance(issue_payload, dict):
        # Return no catalog when the issue payload is missing or malformed.
        return None

    team_payload = issue_payload.get("team")

    if not isinstance(team_payload, dict):
        # Return no catalog when the issue does not expose a usable team payload.
        return None

    states_payload = team_payload.get("states")

    if not isinstance(states_payload, dict):
        # Return no catalog when the team states envelope is missing or malformed.
        return None

    team_states = states_payload.get("nodes", [])

    if not isinstance(team_states, list):
        # Return no catalog when the team states payload is not a list.
        return None

    current_state = issue_payload.get("state")

    if current_state is not None and not isinstance(current_state, dict):
        # Return no catalog when the current state payload is malformed.
        return None

    # Return the normalized issue-state catalog for the caller's state matching logic.
    return {
        "currentState": current_state or {},
        "teamStates": [state for state in team_states if isinstance(state, dict)],
    }


def _find_linear_state_node(team_states: List[Dict[str, Any]], status_name: str) -> Optional[Dict[str, Any]]:
    """Finds the best Linear team state matching the requested public status name."""

    normalized_status_name = status_name.strip().lower()
    target_state_type = _LINEAR_STATE_TYPE_BY_STATUS_NAME.get(normalized_status_name, "")

    # Prefer an exact case-insensitive state-name match so team-specific labels win.
    for state in team_states:
        if str(state.get("name", "")).strip().lower() == normalized_status_name:
            # Return the exact state-name match immediately.
            return state

    if target_state_type:
        # Fall back to the canonical Linear state type when names differ across teams.
        for state in team_states:
            if str(state.get("type", "")).strip().lower() == target_state_type:
                # Return the first state whose workflow type matches the requested status.
                return state

    # Return no state when neither the name nor type lookup found a usable match.
    return None


def update_linear_issue_status(settings: Settings, *, issue_id: str, status_name: str) -> bool:
    """Updates a Linear issue into the requested workflow state when possible."""

    normalized_issue_id = issue_id.strip()
    normalized_status_name = status_name.strip()

    if not normalized_issue_id or not normalized_status_name:
        # Skip updates that do not identify both an issue and a target state.
        return False

    issue_catalog_response = _request_linear_graphql(
        settings,
        query="""
        query ControlPaneIssueStateCatalog($issueId: String!) {
          issue(id: $issueId) {
            id
            state {
              id
              name
              type
            }
            team {
              id
              states(first: 50) {
                nodes {
                  id
                  name
                  type
                }
              }
            }
          }
        }
        """,
        variables={"issueId": normalized_issue_id},
    )

    if not issue_catalog_response:
        # Stop when the issue catalog lookup could not be loaded from Linear.
        return False

    issue_state_catalog = _extract_linear_issue_state_catalog(issue_catalog_response)

    if not issue_state_catalog:
        # Stop when the response does not expose the issue's current/team states.
        return False

    current_state = issue_state_catalog["currentState"]
    team_states = issue_state_catalog["teamStates"]
    matched_state = _find_linear_state_node(team_states, normalized_status_name)

    if not matched_state:
        # Stop when the team does not have a state matching the requested status.
        return False

    current_state_id = str(current_state.get("id", "")).strip()
    matched_state_id = str(matched_state.get("id", "")).strip()

    if current_state_id and current_state_id == matched_state_id:
        # Treat the update as successful when the issue is already in the target state.
        return True

    mutation_response = _request_linear_graphql(
        settings,
        query="""
        mutation ControlPaneIssueStateUpdate($issueId: String!, $stateId: String!) {
          issueUpdate(id: $issueId, input: { stateId: $stateId }) {
            success
            issue {
              id
              state {
                id
                name
                type
              }
            }
          }
        }
        """,
        variables={
            "issueId": normalized_issue_id,
            "stateId": matched_state_id,
        },
    )

    if not mutation_response:
        # Report failure when the mutation response could not be read safely.
        return False

    mutation_data = mutation_response.get("data")

    if not isinstance(mutation_data, dict):
        # Report failure when Linear omits the GraphQL data envelope.
        return False

    update_payload = mutation_data.get("issueUpdate")

    if not isinstance(update_payload, dict):
        # Report failure when the issueUpdate payload is missing or malformed.
        return False

    # Return the Linear mutation success flag so callers can avoid duplicate retries.
    return bool(update_payload.get("success"))


def _read_markdown_title(path: Path) -> str:
    """Extracts a readable title from a markdown document."""

    try:
        # Read the markdown file contents so the first heading can become the document title.
        contents = path.read_text(encoding="utf-8")
    except OSError:
        # Fall back to the file stem if the document cannot be read.
        return path.stem.replace("-", " ").replace("_", " ").title()

    # Search the file for the first markdown heading.
    for line in contents.splitlines():
        if line.startswith("#"):
            # Use the heading text without leading markdown syntax.
            return line.lstrip("#").strip()

    # Fall back to a title derived from the filename when there is no heading.
    return path.stem.replace("-", " ").replace("_", " ").title()


def _to_document_record(path: Path, docs_root: Path) -> Dict[str, Any]:
    """Converts a markdown file into a document metadata record."""

    relative_path = path.relative_to(docs_root.parent).as_posix()

    # Return the normalized document metadata used by the intake and task detail views.
    return {
        "id": relative_path.replace("/", "__"),
        "title": _read_markdown_title(path),
        "path": relative_path,
        "source": "repo_markdown",
        "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def list_repo_documents(settings: Settings) -> List[Dict[str, Any]]:
    """Lists repo markdown documents used by the knowledge integration."""

    docs_root = Path(settings.docs_directory)
    documents: List[Dict[str, Any]] = []

    if not docs_root.exists():
        # Return no repo documents if the configured docs directory does not exist.
        return documents

    markdown_paths: List[Path] = []

    # Include the repo README when it exists because it often contains important context.
    repo_readme = docs_root.parent / "README.md"

    if repo_readme.exists():
        # Capture the repo root README as part of the knowledge source list.
        markdown_paths.append(repo_readme)

    # Include all markdown files from the configured docs directory.
    for path in docs_root.rglob("*.md"):
        if path.is_file():
            # Keep each markdown file for later normalization.
            markdown_paths.append(path)

    # Normalize and sort the markdown documents for consistent UI output.
    for path in sorted(markdown_paths):
        documents.append(_to_document_record(path, docs_root))

    # Return the list of repo knowledge sources.
    return documents


def list_github_repositories(settings: Settings) -> List[Dict[str, Any]]:
    """Lists GitHub repositories from live configuration or returns an empty list."""

    repositories: List[Dict[str, Any]] = []

    if not settings.github_owner or not settings.github_repositories:
        # Return no live repository records when the GitHub config is incomplete.
        return repositories

    headers = {"User-Agent": "ai-control-pane"}

    if settings.github_token:
        # Attach the GitHub token when available for higher rate limits and private repo access.
        headers["Authorization"] = f"Bearer {settings.github_token}"

    for repository_name in settings.github_repositories:
        url = f"https://api.github.com/repos/{settings.github_owner}/{repository_name}"

        try:
            response = _request_json(url, headers=headers)
        except (HTTPError, URLError, json.JSONDecodeError):
            # Skip repositories that cannot be fetched from GitHub.
            continue

        # Normalize the GitHub repository payload into the app's shared shape.
        repositories.append(
            {
                "id": str(response.get("id", repository_name)),
                "name": response.get("name", repository_name),
                "fullName": response.get("full_name", f"{settings.github_owner}/{repository_name}"),
                "defaultBranch": response.get("default_branch", "main"),
                "private": bool(response.get("private", False)),
                "provider": "github",
                "url": response.get("html_url", ""),
            }
        )

    # Return the normalized GitHub repository list.
    return repositories


def list_linear_issues(settings: Settings) -> List[Dict[str, Any]]:
    """Lists Linear issues from live configuration or returns an empty list."""

    if not settings.linear_api_key:
        # Return no live issue records when Linear is not configured.
        return []

    team_scope = settings.linear_team_id.strip()

    headers = {
        "Authorization": normalize_linear_api_key(settings.linear_api_key),
        "Content-Type": "application/json",
    }

    if team_scope:
        team_lookup_payloads = [
            {
                "query": _build_linear_team_lookup_query("id"),
                "variables": {"teamScope": team_scope},
            },
            {
                "query": _build_linear_team_lookup_query("key"),
                "variables": {"teamScope": team_scope.upper()},
            },
            {
                "query": _build_linear_team_lookup_query("name", comparator="eqIgnoreCase"),
                "variables": {"teamScope": team_scope},
            },
        ]
        resolved_team: Optional[Dict[str, Any]] = None

        # Try the common team scope formats that operators paste into the setup form.
        for payload in team_lookup_payloads:
            try:
                response = _request_json(
                    "https://api.linear.app/graphql",
                    method="POST",
                    headers=headers,
                    payload=payload,
                )
            except (HTTPError, URLError, json.JSONDecodeError):
                # Skip failed lookups so alternate team-scope formats can still succeed.
                continue

            resolved_team = _extract_linear_team_node(response)

            if resolved_team:
                # Stop retrying once a matching Linear team has been resolved.
                break

        if not resolved_team:
            # Return no scoped issues when the saved team scope does not resolve to a real team.
            return []

        try:
            response = _request_json(
                "https://api.linear.app/graphql",
                method="POST",
                headers=headers,
                payload={
                    "query": _build_linear_team_issue_query(),
                    "variables": {"teamId": str(resolved_team.get("id", "")).strip()},
                },
            )
        except (HTTPError, URLError, json.JSONDecodeError):
            # Fall back to mock mode when the team-scoped issue request fails.
            return []

        nodes = _extract_linear_team_issue_nodes(response)

        if nodes is None:
            # Fall back to mock mode when the team-scoped issue response is malformed.
            return []
    else:
        try:
            response = _request_json(
                "https://api.linear.app/graphql",
                method="POST",
                headers=headers,
                payload={"query": _build_linear_issue_query()},
            )
        except (HTTPError, URLError, json.JSONDecodeError):
            # Fall back to mock mode when the unscoped Linear issue request fails.
            return []

        nodes = _extract_linear_issue_nodes(response)

        if nodes is None:
            # Fall back to mock mode when the unscoped Linear issue response is malformed.
            return []

    issues: List[Dict[str, Any]] = []

    # Normalize each Linear issue into the app's shared issue shape.
    for node in nodes:
        issues.append(
            {
                "id": node.get("id", ""),
                "ticket": node.get("identifier", ""),
                "title": node.get("title", ""),
                "description": node.get("description", ""),
                "priority": str(node.get("priority", "0")),
                "status": node.get("state", {}).get("name", "Backlog"),
                "url": node.get("url", ""),
                "assignee": node.get("assignee", {}) or {},
                "provider": "linear",
            }
        )

    # Return the normalized Linear issue list.
    return issues


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


def resolve_current_user(settings: Settings, headers: Mapping[str, str]) -> Dict[str, str]:
    """Resolves the current user from SSO-like headers or configured defaults."""

    email_header = (
        headers.get("x-goog-authenticated-user-email")
        or headers.get("x-forwarded-email")
        or headers.get("x-demo-user-email")
        or settings.default_user_email
    )
    name_header = headers.get("x-demo-user-name") or settings.default_user_name
    team_header = headers.get("x-demo-team-id") or "default"
    normalized_email = email_header.split(":")[-1].strip()
    normalized_team_id = team_header.strip().lower() or "default"

    # Return the resolved user identity used for approvals and audit history.
    return {
        "name": name_header,
        "email": normalized_email,
        "role": "admin",
        "teamId": normalized_team_id,
        "provider": "google_sso" if settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri else "configured_default",
    }


def _build_connection_payload(settings: Settings, integration_id: str) -> Optional[Dict[str, Any]]:
    """Builds the non-secret connection details shown in the integrations UI."""

    if integration_id == "github" and settings.github_owner and settings.github_repositories:
        # Return the GitHub owner and repository list without exposing the token.
        return {
            "label": f"{settings.github_owner} / {len(settings.github_repositories)} repos",
            "values": {
                "owner": settings.github_owner,
                "repositories": ", ".join(settings.github_repositories),
            },
        }

    if integration_id == "linear" and settings.linear_api_key:
        # Return the Linear team hint without exposing the API key.
        return {
            "label": settings.linear_team_id or "Workspace access configured",
            "values": {
                "teamId": settings.linear_team_id,
            },
        }

    if integration_id == "jira" and settings.jira_site_url and settings.jira_email and settings.jira_api_token:
        jira_label = settings.jira_project_key or settings.jira_site_url

        # Return the Jira scope hint without exposing the API token.
        return {
            "label": jira_label,
            "values": {
                "siteUrl": normalize_jira_site_url(settings.jira_site_url),
                "email": settings.jira_email,
                "projectKey": settings.jira_project_key,
            },
        }

    if integration_id == "cursor_cloud_agents" and settings.cursor_api_key:
        # Return the saved Cursor model hint without exposing the API key.
        return {
            "label": settings.cursor_model or "default",
            "values": {
                "model": settings.cursor_model or "default",
            },
        }

    if integration_id == "repo_docs" and settings.docs_directory:
        # Return the docs directory currently used for markdown discovery.
        return {
            "label": settings.docs_directory,
            "values": {
                "docsDirectory": settings.docs_directory,
            },
        }

    if integration_id == "google_sso":
        google_domain_label = settings.google_hosted_domain or "Google OAuth configured"

        # Return the configured Google SSO label without exposing any secrets.
        return {
            "label": google_domain_label,
            "values": {
                "hostedDomain": settings.google_hosted_domain,
            },
        }

    # Return no connection payload when the integration has not been configured.
    return None


def get_integration_statuses(settings: Settings) -> List[Dict[str, Any]]:
    """Builds the integration status list for all required provider categories."""

    repositories = list_github_repositories(settings)
    linear_connected = is_linear_connected(settings)
    jira_connected = is_jira_connected(settings)
    cursor_connected = is_cursor_connected(settings)
    issues = list_linear_issues(settings)
    jira_issues = list_jira_issues(settings)
    google_sso_configured = bool(settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri)
    timestamp = _utc_timestamp()

    # Return the provider connectivity summary used by the integrations UI.
    return [
        {
            "id": "github",
            "name": "GitHub",
            "mode": "live" if repositories else "mock",
            "connected": bool(repositories),
            "capabilities": [
                "Repository metadata",
                "Branch selection",
                "Pull request linking",
            ],
            "configured": bool(settings.github_owner and settings.github_repositories),
            "details": f"{len(repositories)} repositories available" if repositories else "Using fallback repository catalog",
            "requiredRole": "admin",
            "recommendedAction": "Connect an org and repository list to launch work against real repos.",
            "connection": _build_connection_payload(settings, "github"),
            "checkedAt": timestamp,
        },
        {
            "id": "github_actions",
            "name": "GitHub Actions",
            "mode": "live" if repositories else "mock",
            "connected": bool(repositories),
            "capabilities": [
                "Workflow status",
                "Build and test visibility",
                "Retry guidance context",
            ],
            "configured": bool(settings.github_owner and settings.github_repositories),
            "details": "Readiness depends on GitHub repository access",
            "requiredRole": "admin",
            "recommendedAction": "GitHub Actions becomes active automatically after GitHub is connected.",
            "connection": _build_connection_payload(settings, "github"),
            "checkedAt": timestamp,
        },
        {
            "id": "linear",
            "name": "Linear",
            "mode": "live" if linear_connected else "mock",
            "connected": linear_connected,
            "capabilities": [
                "Issue import",
                "Acceptance criteria grounding",
                "Task traceability",
            ],
            "configured": bool(settings.linear_api_key),
            "details": (
                f"{len(issues)} issues available"
                if issues
                else "Connected to Linear, but no issues are currently available for this scope."
                if linear_connected
                else "Using fallback issue catalog"
            ),
            "requiredRole": "admin",
            "recommendedAction": "Connect a Linear API key so intake can pull live issues and team ownership.",
            "connection": _build_connection_payload(settings, "linear"),
            "checkedAt": timestamp,
        },
        {
            "id": "jira",
            "name": "Jira",
            "mode": "live" if jira_connected else "mock",
            "connected": jira_connected,
            "capabilities": [
                "Issue import",
                "Acceptance criteria grounding",
                "Task traceability",
            ],
            "configured": bool(settings.jira_site_url and settings.jira_email and settings.jira_api_token),
            "details": (
                f"{len(jira_issues)} issues available"
                if jira_issues
                else "Connected to Jira, but no issues are currently available for this scope."
                if jira_connected
                else "Using fallback issue catalog"
            ),
            "requiredRole": "admin",
            "recommendedAction": "Connect Jira Cloud so intake can pull live issues and project ownership.",
            "connection": _build_connection_payload(settings, "jira"),
            "checkedAt": timestamp,
        },
        {
            "id": "cursor_cloud_agents",
            "name": "Cursor Cloud Agents",
            "mode": "live" if cursor_connected else "mock",
            "connected": cursor_connected,
            "capabilities": [
                "Launch GitHub-targeted agents",
                "Auto-create pull requests",
                "Read live cloud-agent status",
            ],
            "configured": bool(settings.cursor_api_key),
            "details": (
                f"Ready to launch against GitHub with model {settings.cursor_model or 'default'}"
                if cursor_connected
                else "Connect Cursor so Start run launches a real cloud agent instead of the simulator"
            ),
            "requiredRole": "admin",
            "recommendedAction": "Connect a Cursor API key so new runs launch real cloud agents against your GitHub repos.",
            "connection": _build_connection_payload(settings, "cursor_cloud_agents"),
            "checkedAt": timestamp,
        },
        {
            "id": "google_sso",
            "name": "Google SSO",
            "mode": "live" if google_sso_configured else "mock",
            "connected": google_sso_configured,
            "capabilities": [
                "User identity",
                "Role mapping",
                "Approval audit attribution",
            ],
            "configured": google_sso_configured,
            "details": (
                f"OAuth ready for {settings.google_hosted_domain}"
                if google_sso_configured and settings.google_hosted_domain
                else "Google OAuth is configured"
                if google_sso_configured
                else "Header-based identity fallback is active"
            ),
            "requiredRole": "admin",
            "recommendedAction": (
                "Sign in with Google to create an admin session after the configured access checks pass."
                if google_sso_configured
                else "Configure Google OAuth to replace the local guided sign-in fallback."
            ),
            "connection": _build_connection_payload(settings, "google_sso"),
            "checkedAt": timestamp,
        },
    ]


class OpenAIEnrichmentError(Exception):
    """Captures a readable OpenAI enrichment API failure."""


# Human-readable field labels for the enrichment prompt.
_ENRICH_FIELD_LABELS: Dict[str, str] = {
    "title": "Task title",
    "prompt": "Implementation prompt",
    "acceptanceCriteria": "Acceptance criteria",
    "acceptance_criteria": "Acceptance criteria",
}

# Per-field guidance for the enrichment model output.
_ENRICH_FIELD_GUIDANCE: Dict[str, str] = {
    "title": (
        "Return a single concise task title (max ~12 words) that names the concrete outcome. "
        "Respond with the title only, no quotes, no trailing period."
    ),
    "prompt": (
        "Return a clear implementation prompt (3-7 sentences). Call out the repository surfaces that "
        "should change, reference the relevant docs, preserve any user intent already present, and keep "
        "guardrails the agent must respect. Plain prose, no markdown headings."
    ),
    "acceptance_criteria": (
        "Return 3-6 testable acceptance criteria as a markdown checklist (each line begins with '- [ ] '). "
        "Each item should be observable, scoped to this task, and aligned with repo policy and evidence expectations."
    ),
}


def _read_doc_excerpt(path: Path, max_chars: int) -> str:
    """Reads a truncated markdown excerpt used for enrichment grounding."""

    try:
        # Read the markdown document from disk so it can ground the enrichment prompt.
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        # Skip documents that cannot be read from disk.
        return ""

    if len(text) <= max_chars:
        # Return the full document when it already fits in the context budget.
        return text

    # Truncate long documents so the combined prompt stays within OpenAI context limits.
    return text[:max_chars].rstrip() + "\n...[truncated]..."


def _fetch_github_json_body(url: str, headers: Mapping[str, str]) -> Any:
    """Executes a GitHub REST GET and returns the raw JSON body (dict or list).

    GitHub content listings return JSON arrays, so we cannot reuse the stricter
    ``_request_json`` helper that narrows the return type to ``Dict``. This
    wrapper keeps the low-level network behavior identical while permitting the
    parsed JSON body to be either an object or an array.
    """

    # Copy the caller's headers so GitHub's accept header takes precedence over defaults.
    request_headers = dict(headers)
    request = Request(url, headers=request_headers, method="GET")

    with urlopen(request, timeout=12) as response:
        # Decode the GitHub response body into native Python data.
        return json.loads(response.read().decode("utf-8"))


def _decode_github_contents_body(payload: Mapping[str, Any]) -> str:
    """Decodes the base64-encoded body returned by the GitHub contents API.

    The ``/contents`` endpoint returns each file as a JSON object with a base64
    encoded ``content`` field. This helper reverses that encoding into UTF-8
    text so callers can feed it directly into the OpenAI enrichment prompt.
    """

    # Read the raw base64 payload and encoding label GitHub advertises.
    encoded_content = str(payload.get("content") or "")
    encoding_label = str(payload.get("encoding") or "").lower()

    if not encoded_content or encoding_label != "base64":
        # Bail out when the response does not carry a base64 body we can decode.
        return ""

    try:
        # Decode the base64 blob back into markdown/plaintext for the prompt.
        return base64.b64decode(encoded_content).decode("utf-8", errors="ignore")
    except (ValueError, TypeError):
        # Swallow malformed content so callers can simply skip this document.
        return ""


def _list_github_markdown_paths(
    base_api_url: str,
    headers: Mapping[str, str],
    *,
    directory_path: str,
    max_files: int,
) -> List[str]:
    """Returns markdown file paths under ``directory_path`` inside the repo.

    The helper walks the GitHub contents listing recursively so docs nested in
    subfolders are still discovered. The traversal stops once ``max_files``
    markdown files have been collected to keep the OpenAI context bounded.
    """

    markdown_paths: List[str] = []

    if max_files <= 0 or not directory_path:
        # Short-circuit when the caller has no remaining budget or no directory.
        return markdown_paths

    try:
        # Ask GitHub for the contents of the requested directory path.
        listing_payload = _fetch_github_json_body(
            f"{base_api_url}/contents/{directory_path}",
            headers,
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Skip missing or unreachable directories so the enrichment can proceed.
        return markdown_paths

    if not isinstance(listing_payload, list):
        # GitHub returns an object when the path points at a single file; treat
        # that as a terminal case and evaluate it as a lone markdown candidate.
        if isinstance(listing_payload, dict):
            entry_path = str(listing_payload.get("path") or "").strip()
            entry_type = str(listing_payload.get("type") or "")

            if entry_type == "file" and entry_path.lower().endswith(".md"):
                # Capture the single-file match inside the remaining budget.
                markdown_paths.append(entry_path)

        return markdown_paths[:max_files]

    for entry in listing_payload:
        if len(markdown_paths) >= max_files:
            # Stop once we have enough markdown files to satisfy the budget.
            break

        if not isinstance(entry, dict):
            # Skip malformed entries so a single bad row cannot poison the walk.
            continue

        entry_type = str(entry.get("type") or "")
        entry_path = str(entry.get("path") or "").strip()

        if not entry_path:
            # Ignore entries lacking a usable path.
            continue

        if entry_type == "file" and entry_path.lower().endswith(".md"):
            # Record the markdown file so its body can be fetched later.
            markdown_paths.append(entry_path)
        elif entry_type == "dir":
            # Recurse into subdirectories using the remaining file budget.
            nested_paths = _list_github_markdown_paths(
                base_api_url,
                headers,
                directory_path=entry_path,
                max_files=max_files - len(markdown_paths),
            )
            markdown_paths.extend(nested_paths)

    # Clamp the aggregated list so nested recursion cannot exceed the budget.
    return markdown_paths[:max_files]


def _format_remote_doc_section(label: str, text: str, per_doc_chars: int) -> str:
    """Formats a single remote doc body into a labeled, bounded prompt section."""

    # Truncate long docs so the combined prompt stays within OpenAI context limits.
    if len(text) > per_doc_chars:
        excerpt_text = text[:per_doc_chars].rstrip() + "\n...[truncated]..."
    else:
        excerpt_text = text

    # Return a markdown-header-labeled excerpt matching the local docs formatting.
    return f"### {label}\n{excerpt_text}"


def _fetch_remote_repo_doc_context(
    settings: Settings,
    *,
    repo_name: str,
    per_doc_chars: int = 4000,
    max_docs: int = 8,
) -> str:
    """Builds an enrichment context blob from the selected remote GitHub repo.

    The intake "Enrich" buttons ground their suggestions in the repo docs, so
    this helper pulls the repository's README and any markdown files inside the
    repo's ``docs`` directory via the GitHub contents API. Fetches are guarded
    so transient GitHub errors simply yield an empty context instead of failing
    the enrichment call outright.
    """

    repo_slug = (repo_name or "").strip()

    if not repo_slug or not settings.github_owner:
        # Skip remote lookups when the repo or owner are not configured yet.
        return ""

    # Reuse the shared GitHub headers so the token (when present) is attached.
    headers = _build_github_request_headers(settings)
    base_api_url = f"https://api.github.com/repos/{settings.github_owner}/{repo_slug}"

    collected_sections: List[str] = []

    try:
        # Always include the repo README so the model anchors on the top-level pitch.
        readme_payload = _fetch_github_json_body(f"{base_api_url}/readme", headers)
    except (HTTPError, URLError, json.JSONDecodeError):
        # Skip README when GitHub is unreachable or the repo has no README.
        readme_payload = None

    if isinstance(readme_payload, dict):
        readme_body = _decode_github_contents_body(readme_payload)

        if readme_body.strip():
            # Label the README with its repo-scoped path for traceability.
            readme_label = f"{repo_slug}/{str(readme_payload.get('path') or 'README.md')}"
            collected_sections.append(
                _format_remote_doc_section(readme_label, readme_body, per_doc_chars)
            )

    # Reserve the rest of the budget for files discovered under the repo docs folder.
    remaining_budget = max(0, max_docs - len(collected_sections))

    if remaining_budget > 0:
        markdown_paths = _list_github_markdown_paths(
            base_api_url,
            headers,
            directory_path="docs",
            max_files=remaining_budget,
        )

        for markdown_path in markdown_paths:
            if len(collected_sections) >= max_docs:
                # Respect the hard cap even if the listing returned extra files.
                break

            try:
                # Fetch the individual file so we get the base64 body GitHub returns.
                file_payload = _fetch_github_json_body(
                    f"{base_api_url}/contents/{markdown_path}",
                    headers,
                )
            except (HTTPError, URLError, json.JSONDecodeError):
                # Skip any file we cannot read so one failure cannot block the rest.
                continue

            if not isinstance(file_payload, dict):
                # Guard against unexpected response shapes returned by GitHub.
                continue

            file_body = _decode_github_contents_body(file_payload)

            if not file_body.strip():
                # Drop empty documents so they do not bloat the enrichment prompt.
                continue

            collected_sections.append(
                _format_remote_doc_section(
                    f"{repo_slug}/{markdown_path}", file_body, per_doc_chars
                )
            )

    # Return the combined context so the enrichment prompt can embed it directly.
    return "\n\n".join(collected_sections)


def _collect_doc_context(settings: Settings, *, per_doc_chars: int = 4000, max_docs: int = 8) -> str:
    """Builds a combined markdown context blob from repo docs."""

    docs_root = Path(settings.docs_directory)
    context_parts: List[str] = []

    if not docs_root.exists():
        # Skip context collection when the docs directory is missing.
        return ""

    markdown_paths: List[Path] = []
    repo_readme = docs_root.parent / "README.md"

    if repo_readme.exists():
        # Always anchor enrichment context on the repo README when available.
        markdown_paths.append(repo_readme)

    # Pull every markdown file from the configured docs directory for grounding.
    for candidate_path in sorted(docs_root.rglob("*.md")):
        if candidate_path.is_file():
            markdown_paths.append(candidate_path)

    # Keep the document set bounded so prompts remain within OpenAI context limits.
    markdown_paths = markdown_paths[:max_docs]

    for markdown_path in markdown_paths:
        excerpt = _read_doc_excerpt(markdown_path, per_doc_chars)

        if not excerpt.strip():
            # Skip empty or unreadable docs so they do not bloat the prompt.
            continue

        try:
            relative_label = markdown_path.relative_to(docs_root.parent).as_posix()
        except ValueError:
            # Fall back to the filename when the doc lives outside the docs parent.
            relative_label = markdown_path.name

        context_parts.append(f"### {relative_label}\n{excerpt}")

    # Return a single combined context string suitable for the enrichment prompt.
    return "\n\n".join(context_parts)


def _normalize_enrichment_field(raw_field: str) -> str:
    """Normalizes the requested enrichment field name."""

    normalized_field = (raw_field or "").strip().lower().replace("-", "_")

    if normalized_field in ("acceptancecriteria", "acceptance_criteria", "criteria"):
        # Collapse the acceptance criteria aliases into the canonical snake_case form.
        return "acceptance_criteria"

    if normalized_field in ("title", "task_title"):
        # Collapse the title aliases into the canonical form.
        return "title"

    if normalized_field in ("prompt", "description"):
        # Collapse the prompt aliases into the canonical form.
        return "prompt"

    # Return the normalized field name so callers can validate it.
    return normalized_field


def _build_enrichment_messages(
    *,
    field: str,
    value: str,
    title: str,
    prompt: str,
    acceptance_criteria: str,
    repo_name: str,
    execution_mode: str,
    docs_context: str,
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for a work intake enrichment call."""

    field_label = _ENRICH_FIELD_LABELS.get(field, field)
    field_guidance = _ENRICH_FIELD_GUIDANCE.get(field, "Return a refined value for this field.")

    system_content = (
        "You refine work intake fields for the AI Engineering Control Pane. "
        "Ground every refinement in the repository's docs, the intake context, and the product's "
        "MVP workflow so the final text is ready for a tech-lead reviewer and an implementing agent. "
        "Do not invent integrations, repositories, or policies that are not supported by the docs. "
        "Preserve any user-written intent in the current value while improving clarity, specificity, and alignment."
    )

    intake_context_lines = [
        f"- Field to refine: {field_label}",
        f"- Repository: {repo_name or 'unspecified'}",
        f"- Execution mode: {execution_mode or 'implement'}",
        f"- Current task title: {title or '(empty)'}",
        f"- Current prompt: {prompt or '(empty)'}",
        f"- Current acceptance criteria: {acceptance_criteria or '(empty)'}",
    ]

    docs_section = docs_context.strip() or "(no repo docs were available)"

    user_content = (
        "Repo docs (use these as the source of truth for tone, scope, and terminology):\n"
        f"{docs_section}\n\n"
        "Current intake state:\n"
        + "\n".join(intake_context_lines)
        + "\n\n"
        f"Current value of {field_label}:\n"
        f"{value.strip() or '(empty)'}\n\n"
        f"Instructions: {field_guidance}\n"
        "Only return the refined value itself, with no preamble, explanation, or surrounding markdown fences."
    )

    # Return the chat-completion message list for OpenAI.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _build_uploaded_doc_context(
    uploaded_documents: List[Mapping[str, Any]],
    *,
    per_doc_chars: int = 4000,
    max_docs: int = 8,
) -> str:
    """Builds an enrichment context blob from documents uploaded in the intake UI."""

    context_sections: List[str] = []

    # Clamp the uploaded document list so large uploads stay within prompt budget.
    for uploaded_document in uploaded_documents[:max_docs]:
        # Read the uploaded file body and skip entries that do not carry any content.
        document_body = str(uploaded_document.get("content") or "").strip()

        if not document_body:
            # Ignore empty uploaded documents so the prompt stays focused.
            continue

        # Prefer the original path label so the model can cite the uploaded source cleanly.
        document_label = str(
            uploaded_document.get("path")
            or uploaded_document.get("title")
            or uploaded_document.get("id")
            or "uploaded-document"
        ).strip()

        context_sections.append(
            _format_remote_doc_section(document_label, document_body, per_doc_chars)
        )

    # Return the combined uploaded-doc context for the enrichment request.
    return "\n\n".join(context_sections)


def _extract_openai_message(response_payload: Dict[str, Any]) -> str:
    """Extracts the assistant text from an OpenAI chat completion response."""

    choices = response_payload.get("choices") or []

    if not choices:
        # Reject responses that do not include a usable assistant message.
        raise OpenAIEnrichmentError("OpenAI returned an empty choices list.")

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content")

    if isinstance(content, list):
        text_parts: List[str] = []

        # Handle the list-of-parts content shape used by newer OpenAI responses.
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])

        content = "".join(text_parts)

    if not isinstance(content, str) or not content.strip():
        # Reject responses that do not contain a non-empty string body.
        raise OpenAIEnrichmentError("OpenAI response did not contain any text content.")

    # Return the trimmed assistant message so callers can use it directly.
    return content.strip()


def enrich_intake_field(
    settings: Settings,
    *,
    field: str,
    value: str,
    title: str,
    prompt: str,
    acceptance_criteria: str,
    repo_name: str,
    execution_mode: str,
    uploaded_documents: Optional[List[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Refines a work intake field with OpenAI using repo doc context."""

    normalized_field = _normalize_enrichment_field(field)

    if normalized_field not in ("title", "prompt", "acceptance_criteria"):
        # Reject unsupported fields so the frontend does not silently misuse the route.
        raise OpenAIEnrichmentError(
            "Only the title, prompt, and acceptance criteria fields can be enriched."
        )

    if not settings.openai_api_key:
        # Reject enrichment requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable enrichment."
        )

    # Prefer the documents uploaded in the intake form so Enrich uses the exact
    # repo context the operator supplied for this task.
    docs_context = _build_uploaded_doc_context(list(uploaded_documents or []))

    if not docs_context:
        # Fall back to the selected remote repository docs when no uploads were provided.
        docs_context = _fetch_remote_repo_doc_context(settings, repo_name=repo_name)

    messages = _build_enrichment_messages(
        field=normalized_field,
        value=value,
        title=title,
        prompt=prompt,
        acceptance_criteria=acceptance_criteria,
        repo_name=repo_name,
        execution_mode=execution_mode,
        docs_context=docs_context,
    )

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can refine the intake field against repo docs.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the enrichment request (status {http_error.code}): {error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable enrichment error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for enrichment: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    refined_text = _extract_openai_message(response_payload)

    # Return the refined field value plus the metadata the UI may surface.
    return {
        "field": normalized_field,
        "value": refined_text,
        "model": settings.openai_model,
        "docsConsidered": bool(docs_context),
    }


def _build_issue_scope_classification_messages(
    *,
    issues: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for classifying intake issues by scope."""

    issue_lines: List[str] = []

    # Flatten each issue into a compact line the model can classify consistently.
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        issue_ticket = str(issue.get("ticket") or "").strip()
        issue_title = str(issue.get("title") or "").strip()
        issue_description = str(issue.get("description") or "").strip()
        issue_status = str(issue.get("status") or "").strip()
        issue_priority = str(issue.get("priority") or "").strip()
        issue_provider = str(issue.get("provider") or "").strip()

        issue_lines.append(
            f"- id: {issue_id or '(n/a)'} | ticket: {issue_ticket or '(n/a)'} | "
            f"title: {issue_title or '(n/a)'} | status: {issue_status or '(n/a)'} | "
            f"priority: {issue_priority or '(n/a)'} | provider: {issue_provider or '(n/a)'} | "
            f"description: {issue_description or '(n/a)'}"
        )

    system_content = (
        "You are classifying work intake issues for whether an autonomous coding agent is "
        "extremely likely to complete the task fully without needing major clarification. "
        "Classify each issue into exactly one bucket. "
        "Use 'well scoped' only when the task is concrete, implementation-ready, and likely "
        "to be completed end-to-end by a coding agent. "
        "Use 'poorly scoped' when the task is ambiguous, missing success criteria, likely to "
        "require discovery, cross-team coordination, product decisions, or substantial human clarification. "
        "When uncertain, classify the issue as poorly scoped. "
        "Return a JSON object only, with exactly these keys: "
        '"wellScopedIssueIds" (array of issue id strings) and "poorlyScopedIssueIds" '
        "(array of issue id strings). "
        "Every provided issue id must appear exactly once across the two arrays."
    )

    user_content = (
        "Classify these intake issues using the definitions above:\n"
        + ("\n".join(issue_lines) if issue_lines else "(no issues available)")
        + "\n\nReturn only JSON shaped like: "
        '{"wellScopedIssueIds": ["issue-1"], "poorlyScopedIssueIds": ["issue-2"]}'
    )

    # Return the chat-completion message list used by the issue scoping call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_issue_scope_classification_response(
    response_text: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Parses and validates the OpenAI response used for intake issue scoping."""

    # Strip markdown fences so JSON parsing survives minor formatting drift.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence before parsing the remaining JSON body.
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[:-3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each array.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON issue scoping payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for issue scoping."
        )

    raw_well_scoped_ids = parsed_payload.get("wellScopedIssueIds")
    raw_poorly_scoped_ids = parsed_payload.get("poorlyScopedIssueIds")

    if not isinstance(raw_well_scoped_ids, list) or not isinstance(raw_poorly_scoped_ids, list):
        # Reject responses that do not include both required arrays.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include both issue scoping arrays."
        )

    valid_issue_ids: List[str] = []

    # Preserve the intake issue order so the dropdown stays stable after regrouping.
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if issue_id:
            valid_issue_ids.append(issue_id)

    valid_issue_id_set = set(valid_issue_ids)
    assigned_issue_ids = set()
    well_scoped_issue_ids: List[str] = []
    poorly_scoped_issue_ids: List[str] = []

    # Normalize the model's well-scoped list, ignoring duplicates and unknown ids.
    for raw_issue_id in raw_well_scoped_ids:
        normalized_issue_id = str(raw_issue_id or "").strip()
        if normalized_issue_id in valid_issue_id_set and normalized_issue_id not in assigned_issue_ids:
            well_scoped_issue_ids.append(normalized_issue_id)
            assigned_issue_ids.add(normalized_issue_id)

    # Normalize the model's poorly-scoped list after the well-scoped assignments.
    for raw_issue_id in raw_poorly_scoped_ids:
        normalized_issue_id = str(raw_issue_id or "").strip()
        if normalized_issue_id in valid_issue_id_set and normalized_issue_id not in assigned_issue_ids:
            poorly_scoped_issue_ids.append(normalized_issue_id)
            assigned_issue_ids.add(normalized_issue_id)

    # Conservatively place any unassigned issue into poorly scoped.
    for issue_id in valid_issue_ids:
        if issue_id not in assigned_issue_ids:
            poorly_scoped_issue_ids.append(issue_id)
            assigned_issue_ids.add(issue_id)

    # Return the normalized scoping result for the intake route.
    return {
        "wellScopedIssueIds": well_scoped_issue_ids,
        "poorlyScopedIssueIds": poorly_scoped_issue_ids,
    }


def classify_intake_issues_by_scope(
    settings: Settings,
    *,
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to separate intake issues into well-scoped and poorly-scoped groups."""

    if not issues:
        # Reject calls when there are no issues available to classify.
        raise OpenAIEnrichmentError(
            "No integrated issues are available to classify."
        )

    if not settings.openai_api_key:
        # Reject scoping requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable issue scoping."
        )

    messages = _build_issue_scope_classification_messages(issues=issues)
    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can separate the intake issues into the two scope buckets.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the issue scoping request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable issue scoping error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for issue scoping: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    scoping_result = _parse_issue_scope_classification_response(raw_response_text, issues)

    # Return the normalized issue groups together with the model metadata.
    return {
        "wellScopedIssueIds": scoping_result["wellScopedIssueIds"],
        "poorlyScopedIssueIds": scoping_result["poorlyScopedIssueIds"],
        "model": settings.openai_model,
        "issueCount": len(issues),
    }


def _build_repo_identification_messages(
    *,
    issue: Dict[str, Any],
    repositories: List[Dict[str, Any]],
    docs_context: str,
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for identifying the repo that fits an issue.

    The model is instructed to return a strict JSON object containing the chosen
    repository name, a confidence score, and a short rationale so the backend
    can parse it deterministically.
    """

    # Build a compact, LLM-friendly description of each candidate repository.
    repo_lines: List[str] = []
    for repository in repositories:
        repo_name = str(repository.get("name") or "").strip()
        full_name = str(repository.get("fullName") or repository.get("full_name") or "").strip()
        default_branch = str(repository.get("defaultBranch") or repository.get("default_branch") or "").strip()
        provider = str(repository.get("provider") or "").strip()
        url = str(repository.get("url") or "").strip()

        # Collapse each candidate into a single line the model can reason over.
        repo_lines.append(
            f"- name: {repo_name} | fullName: {full_name or '(n/a)'} | "
            f"defaultBranch: {default_branch or '(n/a)'} | provider: {provider or '(n/a)'} | url: {url or '(n/a)'}"
        )

    # Gather the descriptive fields from the issue to ground the match.
    issue_ticket = str(issue.get("ticket") or "").strip()
    issue_title = str(issue.get("title") or "").strip()
    issue_description = str(issue.get("description") or "").strip()
    issue_status = str(issue.get("status") or "").strip()
    issue_priority = str(issue.get("priority") or "").strip()

    system_content = (
        "You are the repository router for the AI Engineering Control Pane. "
        "Given a work issue and the catalog of integrated repositories, pick the single "
        "repository that best fits the work described in the issue. "
        "Only choose from the provided repositories. Do not invent repositories. "
        "Respond with a JSON object only, no prose, no markdown fences. "
        "The JSON object must have exactly these keys: "
        '"repoName" (string, must match one of the candidate names exactly), '
        '"confidence" (number between 0 and 1), '
        '"reasoning" (short string explaining the choice).'
    )

    docs_section = docs_context.strip() or "(no repo docs were available)"

    user_content = (
        "Issue to route:\n"
        f"- Ticket: {issue_ticket or '(n/a)'}\n"
        f"- Title: {issue_title or '(n/a)'}\n"
        f"- Status: {issue_status or '(n/a)'}\n"
        f"- Priority: {issue_priority or '(n/a)'}\n"
        f"- Description: {issue_description or '(n/a)'}\n\n"
        "Candidate repositories (choose exactly one 'name' value from this list):\n"
        + ("\n".join(repo_lines) if repo_lines else "(no repositories available)")
        + "\n\nRepo docs (use these to disambiguate which repo owns the work):\n"
        f"{docs_section}\n\n"
        "Return only a JSON object shaped like: "
        '{"repoName": "<exact name from list>", "confidence": 0.0-1.0, "reasoning": "<short explanation>"}'
    )

    # Return the chat-completion message list used by the repo identification call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_repo_identification_response(
    response_text: str,
    repositories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Parses the OpenAI response text into a validated repo identification result.

    Rejects responses that cannot be parsed as JSON or that do not reference
    a repository that exists in the provided catalog.
    """

    # Strip common markdown code fences the model sometimes adds despite instructions.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence (optionally followed by a language tag).
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[: -3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each field.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON repository identification payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for repository identification."
        )

    suggested_repo_name = str(parsed_payload.get("repoName") or "").strip()
    if not suggested_repo_name:
        # Reject responses missing the required repository name field.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include a repoName value."
        )

    # Match the suggested name against the provided catalog (case-insensitive fallback).
    matched_repository: Optional[Dict[str, Any]] = None
    for repository in repositories:
        candidate_name = str(repository.get("name") or "").strip()
        if candidate_name == suggested_repo_name:
            matched_repository = repository
            break
    if matched_repository is None:
        # Retry with case-insensitive matching so capitalization quirks do not fail the match.
        lowered_suggestion = suggested_repo_name.lower()
        for repository in repositories:
            candidate_name = str(repository.get("name") or "").strip().lower()
            if candidate_name == lowered_suggestion:
                matched_repository = repository
                break

    if matched_repository is None:
        # Reject suggestions that do not correspond to a known repository.
        raise OpenAIEnrichmentError(
            f"OpenAI suggested '{suggested_repo_name}' which is not in the integrated repository catalog."
        )

    raw_confidence = parsed_payload.get("confidence")
    confidence_value: Optional[float] = None
    if isinstance(raw_confidence, (int, float)):
        # Clamp the confidence value to the [0, 1] range expected by the UI.
        confidence_value = max(0.0, min(1.0, float(raw_confidence)))

    reasoning_text = str(parsed_payload.get("reasoning") or "").strip()

    # Return the validated identification result for the route handler.
    return {
        "repoName": str(matched_repository.get("name") or "").strip(),
        "repoFullName": str(matched_repository.get("fullName") or matched_repository.get("full_name") or "").strip(),
        "confidence": confidence_value,
        "reasoning": reasoning_text,
    }


def identify_repository_for_issue(
    settings: Settings,
    *,
    issue: Dict[str, Any],
    repositories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to pick the repository that best fits a work intake issue.

    Uses the integrated repository catalog and the repo docs context as grounding
    so the model can only select from known repositories. Returns a structured
    payload with the chosen repo name, confidence, reasoning, and model metadata.
    """

    if not repositories:
        # Reject calls when no repositories exist to choose from.
        raise OpenAIEnrichmentError(
            "No integrated repositories are available to identify against."
        )

    if not issue:
        # Reject calls made without an issue to match.
        raise OpenAIEnrichmentError(
            "An issue must be selected before identifying a repository."
        )

    if not settings.openai_api_key:
        # Reject identification requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable repository identification."
        )

    docs_context = _collect_doc_context(settings)
    messages = _build_repo_identification_messages(
        issue=issue,
        repositories=repositories,
        docs_context=docs_context,
    )

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can pick the best-fit repository for the issue.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the repository identification request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable identification error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for repository identification: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    identification_result = _parse_repo_identification_response(raw_response_text, repositories)

    # Return the chosen repository plus the model metadata the UI may surface.
    return {
        "repoName": identification_result["repoName"],
        "repoFullName": identification_result["repoFullName"],
        "confidence": identification_result["confidence"],
        "reasoning": identification_result["reasoning"],
        "model": settings.openai_model,
        "docsConsidered": bool(docs_context),
    }


def _summarize_run_for_suggestions(run: Dict[str, Any]) -> str:
    """Builds a compact single-run summary line for the suggestions prompt."""

    # Extract the descriptive fields the LLM needs to reason about the run.
    ticket = str(run.get("ticket") or run.get("id") or "").strip()
    title = str(run.get("title") or "").strip()
    status = str(run.get("status") or "").strip()
    risk = str(run.get("risk") or "").strip()
    repo = str(run.get("repo") or "").strip()
    owner = str(run.get("owner") or "").strip()
    agent = str(run.get("agent") or "").strip()
    runtime = str(run.get("runtime") or "").strip()
    current_step = str(run.get("currentStep") or "").strip()

    # Flatten the blocker list so the LLM sees each reason verbatim.
    blockers_raw = run.get("blockers") or []
    blocker_texts: List[str] = []
    for blocker in blockers_raw:
        blocker_text = str(blocker or "").strip()
        if blocker_text:
            blocker_texts.append(blocker_text)

    blockers_text = "; ".join(blocker_texts) if blocker_texts else "none"

    # Pull the PR status and approval context so suggestions can reference merge state.
    pull_request = run.get("pullRequest") or {}
    pr_state = str(pull_request.get("state") or pull_request.get("status") or "").strip()
    pr_merged = bool(pull_request.get("merged", False))
    pr_approved = bool(pull_request.get("approved", False))

    # Compose a single line that keeps the prompt compact but informative.
    return (
        f"- {ticket or '(no ticket)'} | title: {title or '(untitled)'} | status: {status or '(unknown)'} | "
        f"risk: {risk or '(unknown)'} | repo: {repo or '(unknown)'} | owner: {owner or '(unknown)'} | "
        f"agent: {agent or '(unknown)'} | runtime: {runtime or '00:00'} | step: {current_step or '(none)'} | "
        f"blockers: {blockers_text} | pr_state: {pr_state or '(none)'} | pr_approved: {pr_approved} | pr_merged: {pr_merged}"
    )


def _build_suggested_actions_messages(runs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages that request the suggested next actions list."""

    # Convert each visible run into a compact line for the prompt.
    run_lines: List[str] = []
    for run in runs:
        run_lines.append(_summarize_run_for_suggestions(run))

    runs_section = "\n".join(run_lines) if run_lines else "(no runs are currently visible on the dashboard)"

    system_content = (
        "You are the operations copilot for the AI Engineering Control Pane dashboard. "
        "Given a snapshot of the runs currently displayed in the 'Active and recent runs' panel, "
        "produce a short, prioritized list of suggested next actions for the operator. "
        "Only reason about the runs provided; do not invent integrations, repositories, or policies. "
        "Prefer actions that unblock stalled runs, clear the review queue, or confirm merges. "
        "Respond with a JSON object only, no prose, no markdown fences. "
        "The JSON object must have exactly one key: \"suggestedActions\" whose value is a JSON array of "
        "1 to 5 short sentences (each sentence ends with a period). "
        "Each sentence must be actionable, under 140 characters, and clearly tied to the visible runs."
    )

    user_content = (
        "Visible runs in the dashboard 'Active and recent runs' container:\n"
        f"{runs_section}\n\n"
        "Return JSON shaped like: {\"suggestedActions\": [\"Sentence 1.\", \"Sentence 2.\"]}."
    )

    # Return the chat-completion message list used by the suggestions call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_suggested_actions_response(response_text: str) -> List[str]:
    """Parses the OpenAI response text into a validated suggestions list."""

    # Strip common markdown code fences the model sometimes adds despite instructions.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence (optionally followed by a language tag).
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[: -3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each field.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON suggestions payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for suggested actions."
        )

    raw_actions = parsed_payload.get("suggestedActions")

    if not isinstance(raw_actions, list):
        # Reject responses that do not include the expected array field.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include a suggestedActions array."
        )

    suggested_actions: List[str] = []

    # Normalize each entry into a clean sentence, dropping empties and non-strings.
    for raw_action in raw_actions:
        if not isinstance(raw_action, str):
            continue

        action_text = raw_action.strip()

        if not action_text:
            continue

        # Clamp each suggestion to a sensible length for the dashboard rail.
        if len(action_text) > 240:
            action_text = action_text[:237].rstrip() + "..."

        suggested_actions.append(action_text)

    # Clamp the overall list so the dashboard rail stays scannable.
    return suggested_actions[:5]


def suggest_next_actions_for_runs(
    settings: Settings,
    *,
    runs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to produce suggested next actions for the visible dashboard runs.

    The caller should pass the runs currently shown in the dashboard's
    'Active and recent runs' container so the suggestions stay consistent with
    what the operator is looking at.
    """

    if not settings.openai_api_key:
        # Reject suggestion requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable suggested actions."
        )

    messages = _build_suggested_actions_messages(runs)

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can propose next actions for the visible runs.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the suggested actions request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable suggestions error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for suggested actions: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    suggested_actions = _parse_suggested_actions_response(raw_response_text)

    # Return the suggestions plus the model metadata the UI may surface.
    return {
        "suggestedActions": suggested_actions,
        "model": settings.openai_model,
        "runCount": len(runs),
    }


def parse_github_pull_request_url(pull_request_url: str) -> Optional[Dict[str, str]]:
    """Parses a GitHub pull-request URL into owner/repo/number fragments.

    Returns None when the URL does not match a real GitHub PR URL so callers can
    safely fall back to the simulated detection path used in the demo app.
    """

    # Guard against empty or non-string inputs before running the regex.
    if not pull_request_url or not isinstance(pull_request_url, str):
        # Reject empty or invalid PR URLs before attempting to match the pattern.
        return None

    match_result = _GITHUB_PR_URL_PATTERN.match(pull_request_url.strip())

    if not match_result:
        # Return None when the URL is not a real github.com pull-request link.
        return None

    # Return the parsed components for a later GitHub REST API lookup.
    return {
        "owner": match_result.group("owner"),
        "repo": match_result.group("repo"),
        "number": match_result.group("number"),
    }


def _build_github_request_headers(settings: Settings) -> Dict[str, str]:
    """Builds the shared headers used for GitHub REST API calls."""

    request_headers: Dict[str, str] = {
        "User-Agent": "ai-control-pane",
        "Accept": "application/vnd.github+json",
    }

    if settings.github_token:
        # Attach the GitHub token so private-repo and rate-limit-safe calls can succeed.
        request_headers["Authorization"] = f"Bearer {settings.github_token}"

    # Return the shared GitHub REST headers used across PR status lookups.
    return request_headers


def _fetch_github_pull_request_payload(
    settings: Settings,
    owner: str,
    repo: str,
    number: str,
) -> Optional[Dict[str, Any]]:
    """Fetches the raw GitHub pull-request payload for the requested PR."""

    pull_request_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"

    try:
        # Read the GitHub PR record so we can detect state, reviews, and merges.
        return _request_json(pull_request_url, headers=_build_github_request_headers(settings))
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return None when the PR metadata cannot be read from GitHub.
        return None


def _fetch_github_pull_request_reviews(
    settings: Settings,
    owner: str,
    repo: str,
    number: str,
) -> List[Dict[str, Any]]:
    """Fetches the GitHub review list for the requested PR."""

    reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews"

    try:
        response_payload = _request_json(reviews_url, headers=_build_github_request_headers(settings))
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return no reviews when the GitHub review list cannot be fetched.
        return []

    if isinstance(response_payload, list):
        # Return the review list directly when GitHub replied with a JSON array.
        return [review for review in response_payload if isinstance(review, dict)]

    # Return no reviews when the response shape is not the expected array.
    return []


def _extract_latest_approved_review(reviews: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Finds the most recent GitHub review that left an APPROVED decision."""

    latest_approved_review: Optional[Dict[str, Any]] = None
    latest_submitted_at: Optional[str] = None

    # Scan the review list for the most recent "APPROVED" submission.
    for review in reviews:
        if str(review.get("state", "")).upper() != "APPROVED":
            # Skip reviews that did not leave an approval decision.
            continue

        submitted_at = str(review.get("submitted_at", "")).strip()

        if latest_submitted_at is None or submitted_at > latest_submitted_at:
            # Keep the latest approved review based on submission timestamp.
            latest_submitted_at = submitted_at
            latest_approved_review = review

    # Return the latest approved GitHub review if one was found.
    return latest_approved_review


def fetch_github_pull_request_status(
    settings: Settings,
    pull_request_url: str,
) -> Optional[Dict[str, Any]]:
    """Fetches the normalized PR state payload from GitHub for an existing PR URL.

    Returns None when the caller should fall back to the simulated detection flow
    (for example when the URL is not a real GitHub PR link or GitHub is offline).
    """

    pr_components = parse_github_pull_request_url(pull_request_url)

    if not pr_components:
        # Return None when the URL does not resolve to a real GitHub PR.
        return None

    if not settings.github_owner or not settings.github_repositories:
        # Return None when GitHub is not configured so simulation can take over.
        return None

    pull_request_payload = _fetch_github_pull_request_payload(
        settings,
        pr_components["owner"],
        pr_components["repo"],
        pr_components["number"],
    )

    if not pull_request_payload:
        # Return None so the simulated detection path can still drive the demo UI.
        return None

    state_value = str(pull_request_payload.get("state", "open")).lower()
    merged_flag = bool(pull_request_payload.get("merged", False))
    merged_at_value = str(pull_request_payload.get("merged_at", "") or "").strip() or None
    reviews = _fetch_github_pull_request_reviews(
        settings,
        pr_components["owner"],
        pr_components["repo"],
        pr_components["number"],
    )
    latest_approved_review = _extract_latest_approved_review(reviews)
    approved_flag = latest_approved_review is not None
    approved_at_value = (
        str(latest_approved_review.get("submitted_at", "") or "").strip() or None
        if latest_approved_review
        else None
    )
    approved_by_login = (
        str(latest_approved_review.get("user", {}).get("login", "")).strip() or None
        if latest_approved_review
        else None
    )

    if merged_flag:
        # Treat merged PRs as the terminal state for the downstream state machine.
        resolved_state = "merged"
    elif state_value == "closed":
        # Treat closed-but-not-merged PRs as a terminal closed state.
        resolved_state = "closed"
    elif approved_flag:
        # Treat at-least-one APPROVED review as the approved-but-open PR state.
        resolved_state = "approved"
    else:
        # Treat every remaining case as the open-awaiting-review state.
        resolved_state = "open"

    # Return the normalized GitHub PR state payload for the state machine.
    return {
        "source": "github",
        "state": resolved_state,
        "merged": merged_flag,
        "mergedAt": merged_at_value,
        "approved": approved_flag,
        "approvedAt": approved_at_value,
        "approvedBy": approved_by_login,
        "number": pr_components["number"],
        "owner": pr_components["owner"],
        "repo": pr_components["repo"],
        "htmlUrl": pull_request_payload.get("html_url", pull_request_url),
    }


def summarize_repository_names(records: Iterable[Dict[str, Any]]) -> List[str]:
    """Builds a repository name list from normalized repository records."""

    names: List[str] = []

    # Extract the repository display name from each normalized record.
    for record in records:
        name = record.get("name", "")

        if name:
            # Keep only non-empty repository names.
            names.append(str(name))

    # Return the normalized repository name list.
    return names
