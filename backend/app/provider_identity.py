"""User identity resolution and integration status aggregation."""

from typing import Any, Dict, List, Mapping, Optional

from app.config import Settings
from app.provider_common import _utc_timestamp
from app.provider_common import normalize_jira_site_url
from app.provider_cursor import is_cursor_connected
from app.provider_docs import list_repo_documents
from app.provider_github import list_github_repositories
from app.provider_github_copilot import is_github_copilot_connected
from app.provider_jira import is_jira_connected
from app.provider_jira import list_jira_issues
from app.provider_linear import is_linear_connected
from app.provider_linear import list_linear_issues


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

    if integration_id == "github_copilot_cloud_agent" and settings.github_copilot_token:
        # Return the saved Copilot model and custom-agent hints without exposing the token.
        return {
            "label": settings.github_copilot_model or "Default Copilot model",
            "values": {
                "model": settings.github_copilot_model,
                "customAgent": settings.github_copilot_custom_agent,
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
    github_copilot_connected = is_github_copilot_connected(settings)
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
            "id": "github_copilot_cloud_agent",
            "name": "GitHub Copilot cloud agent",
            "mode": "live" if github_copilot_connected else "mock",
            "connected": github_copilot_connected,
            "capabilities": [
                "Create Copilot-assigned GitHub issues",
                "Pass target repo, base branch, and custom instructions",
                "Auto-create pull requests through Copilot",
            ],
            "configured": bool(settings.github_copilot_token),
            "details": (
                f"Ready to assign Copilot with model {settings.github_copilot_model or 'default'}"
                if github_copilot_connected
                else "Connect GitHub Copilot so Start run can assign Copilot to a GitHub issue"
            ),
            "requiredRole": "admin",
            "recommendedAction": "Connect a GitHub token with Copilot assignment permissions so new runs can launch Copilot cloud agent.",
            "connection": _build_connection_payload(settings, "github_copilot_cloud_agent"),
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
