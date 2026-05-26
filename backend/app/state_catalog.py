"""Catalog helpers for team-scoped state payloads."""

from copy import deepcopy
from typing import Any, Callable, Dict, List, Mapping, Optional

from app.config import Settings


def normalize_team_id(team_id: str, *, default: str = "default-team") -> str:
    """Normalizes a team identifier used for run-lobby isolation."""

    # Coerce caller input into the canonical lowercase team identifier.
    normalized_team_id = str(team_id or "").strip().lower()

    if normalized_team_id:
        # Return the caller-provided team id in canonical lowercase form.
        return normalized_team_id

    # Fall back to the requested default key for backwards-compatible scopes.
    return default


def resolve_team_id_from_headers(headers: Mapping[str, str]) -> str:
    """Resolves the active team id from normalized request headers."""

    # Prefer the explicit team header attached by authenticated session middleware.
    return normalize_team_id(str(headers.get("x-demo-team-id", "")))


def run_belongs_to_team(run: Mapping[str, Any], team_id: str) -> bool:
    """Reports whether the run belongs to the requested team."""

    # Compare the run's stored team id with the active request team id.
    return normalize_team_id(str(run.get("_teamId", ""))) == normalize_team_id(team_id)


def list_team_runs(run_store: List[Dict[str, Any]], team_id: str) -> List[Dict[str, Any]]:
    """Returns all in-memory runs visible to the requested team."""

    visible_runs: List[Dict[str, Any]] = []

    # Keep only runs whose stored team id matches the active team scope.
    for run in run_store:
        if run_belongs_to_team(run, team_id):
            # Preserve each matching run in insertion order.
            visible_runs.append(run)

    # Return the team-scoped run list while preserving insertion order.
    return visible_runs


def fallback_issues(run_store: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Builds a fallback issue catalog from the seeded run summaries."""

    issues: List[Dict[str, Any]] = []

    # Convert seeded runs into fallback issue records for task intake.
    for run in run_store:
        issues.append(
            {
                "id": run["id"],
                "ticket": run["ticket"],
                "title": run["title"],
                "description": run["summary"],
                "priority": "2",
                "status": run["status"],
                "url": "",
                "assignee": {"name": run["owner"], "email": f"{run['owner'].lower()}@example.com"},
                "provider": "fallback",
            }
        )

    # Return the fallback issue catalog.
    return issues


def fallback_repositories(
    run_store: List[Dict[str, Any]],
    runs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Builds a fallback repository catalog from the seeded run summaries."""

    source_runs = run_store if runs is None else runs
    unique_names: List[str] = []

    # Preserve the first-seen order of repository names from the seeded data.
    for run in source_runs:
        repo_name = str(run.get("repo", ""))

        if repo_name and repo_name not in unique_names:
            # Keep the unique repository name for the fallback catalog.
            unique_names.append(repo_name)

    repositories: List[Dict[str, Any]] = []

    # Convert the unique repository names into normalized catalog records.
    for repo_name in unique_names:
        repositories.append(
            {
                "id": repo_name,
                "name": repo_name,
                "fullName": repo_name,
                "defaultBranch": "main",
                "private": False,
                "provider": "fallback",
                "url": "",
            }
        )

    # Return the fallback repository catalog.
    return repositories


def fallback_documents(
    settings: Settings,
    list_repo_documents: Callable[[Settings], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Returns repo markdown docs or an empty fallback list."""

    documents = list_repo_documents(settings)

    if documents:
        # Prefer real repo markdown documents whenever they are available.
        return documents

    # Return an empty list when no repo docs could be discovered.
    return []


def list_connected_issues(
    settings: Settings,
    list_linear_issues: Callable[[Settings], List[Dict[str, Any]]],
    list_jira_issues: Callable[[Settings], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Builds the combined live issue catalog across connected issue trackers."""

    linear_issues = list_linear_issues(settings)
    jira_issues = list_jira_issues(settings)

    # Return the combined issue-tracker catalog while preserving provider-local ordering.
    return [*linear_issues, *jira_issues]


def catalog_team_runs(integration_catalog: Mapping[str, Any], run_store: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns team-scoped runs from an integration catalog."""

    catalog_runs = integration_catalog.get("teamRuns")

    if catalog_runs is None:
        # Preserve compatibility with older mocked catalogs that predate team scoping.
        return list(run_store)

    # Materialize the catalog runs so downstream payload builders can iterate safely.
    return list(catalog_runs)


def normalize_repository_context_for_api(repository: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Maps an internal repository record into the public task-detail repository context shape."""

    if not repository or not isinstance(repository, dict):
        # Return nothing when the repository payload is missing or not a mapping.
        return None

    # Read each field explicitly so the response keeps the expected camelCase shape.
    repo_id = str(repository.get("id", "")).strip()
    repo_name = str(repository.get("name", "")).strip()
    full_name = str(repository.get("fullName", "") or repo_name).strip()
    default_branch = str(repository.get("defaultBranch", "")).strip()
    repo_url = str(repository.get("url", "")).strip()
    provider = str(repository.get("provider", "")).strip()
    is_private = bool(repository.get("private", False))

    if not full_name and not repo_name and not repo_url:
        # Avoid returning an empty shell when every meaningful field was blank.
        return None

    # Return the normalized repository context object for JSON responses.
    return {
        "id": repo_id,
        "name": repo_name,
        "fullName": full_name,
        "defaultBranch": default_branch,
        "url": repo_url,
        "provider": provider,
        "private": is_private,
    }
