"""Linear provider adapter for connectivity, issue listing, and status updates."""

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError

from app.config import Settings
from app.provider_common import _request_json
from app.provider_common import normalize_linear_api_key

# Fallback Linear workflow-state types used when team-specific names differ.
_LINEAR_STATE_TYPE_BY_STATUS_NAME: Dict[str, str] = {
    "in progress": "started",
    "done": "completed",
}


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
