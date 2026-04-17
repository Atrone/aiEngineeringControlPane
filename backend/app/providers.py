"""Provider adapters for GitHub, Linear, repo docs, and identity resolution."""

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


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


def resolve_current_user(settings: Settings, headers: Mapping[str, str]) -> Dict[str, str]:
    """Resolves the current user from SSO-like headers or configured defaults."""

    email_header = (
        headers.get("x-goog-authenticated-user-email")
        or headers.get("x-forwarded-email")
        or headers.get("x-demo-user-email")
        or settings.default_user_email
    )
    name_header = headers.get("x-demo-user-name") or settings.default_user_name
    role_header = headers.get("x-demo-user-role") or settings.default_user_role

    normalized_email = email_header.split(":")[-1].strip()

    # Return the resolved user identity used for approvals and audit history.
    return {
        "name": name_header,
        "email": normalized_email,
        "role": role_header,
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

    documents = list_repo_documents(settings)
    repositories = list_github_repositories(settings)
    linear_connected = is_linear_connected(settings)
    cursor_connected = is_cursor_connected(settings)
    issues = list_linear_issues(settings)
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
            "requiredRole": "tech_lead",
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
            "requiredRole": "tech_lead",
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
            "requiredRole": "tech_lead",
            "recommendedAction": "Connect a Linear API key so intake can pull live issues and team ownership.",
            "connection": _build_connection_payload(settings, "linear"),
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
            "requiredRole": "tech_lead",
            "recommendedAction": "Connect a Cursor API key so new runs launch real cloud agents against your GitHub repos.",
            "connection": _build_connection_payload(settings, "cursor_cloud_agents"),
            "checkedAt": timestamp,
        },
        {
            "id": "repo_docs",
            "name": "Repo Markdown",
            "mode": "live" if documents else "mock",
            "connected": bool(documents),
            "capabilities": [
                "Knowledge source discovery",
                "Task context attachment",
                "Provenance tracking",
            ],
            "configured": bool(settings.docs_directory),
            "details": f"{len(documents)} markdown documents indexed" if documents else "No repo documents found",
            "requiredRole": "tech_lead",
            "recommendedAction": "Choose the docs directory that should ground agent context and reviewer evidence.",
            "connection": _build_connection_payload(settings, "repo_docs"),
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
                "Sign in with Google to receive a role from the configured email and domain rules."
                if google_sso_configured
                else "Configure Google OAuth plus role-mapping rules to replace the local guided sign-in fallback."
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

    docs_context = _collect_doc_context(settings)
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
