"""GitHub Copilot cloud agent provider adapter."""

import json
from typing import Any, Dict, Mapping
from urllib.error import HTTPError, URLError

from app.config import Settings
from app.provider_common import _extract_provider_error_message
from app.provider_common import _request_json
from app.provider_common import _utc_timestamp
from app.provider_common import normalize_github_copilot_token


class GitHubCopilotAgentError(Exception):
    """Captures a readable GitHub Copilot cloud agent API failure."""


def _build_github_copilot_headers(token: str) -> Dict[str, str]:
    """Builds the authenticated request headers for GitHub Copilot cloud agent calls."""

    normalized_token = normalize_github_copilot_token(token)

    # Return GitHub's recommended JSON headers plus the user token.
    return {
        "Authorization": f"Bearer {normalized_token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-control-pane",
    }


def is_github_copilot_connected(settings: Settings) -> bool:
    """Checks whether the configured GitHub token can reach Copilot assignment APIs."""

    normalized_token = normalize_github_copilot_token(settings.github_copilot_token)

    if not normalized_token:
        # Report no live connection when Copilot has not been configured yet.
        return False

    try:
        response = _request_json(
            "https://api.github.com/user",
            headers=_build_github_copilot_headers(normalized_token),
        )
    except (HTTPError, URLError, json.JSONDecodeError):
        # Report no live connection when GitHub rejects the token or transport fails.
        return False

    # Report a live connection only when GitHub returns the authenticated user identity.
    return bool(str(response.get("login", "")).strip())


def _build_github_copilot_issue_body(prompt_text: str, source_issue: Mapping[str, Any]) -> str:
    """Builds the GitHub issue body used to start a Copilot cloud agent session."""

    source_url = str(source_issue.get("url", "")).strip()
    body_sections = [
        "This issue was created by AI Control Pane to launch GitHub Copilot cloud agent.",
        prompt_text.strip(),
    ]

    if source_url:
        # Preserve the upstream tracker link so the Copilot-created PR remains traceable.
        body_sections.append(f"Source issue: {source_url}")

    # Return a compact issue body that carries the full implementation context.
    return "\n\n".join(section for section in body_sections if section)


def launch_github_copilot_agent(
    settings: Settings,
    *,
    target_repo: str,
    base_ref: str,
    prompt_text: str,
    issue_title: str,
    source_issue: Mapping[str, Any],
) -> Dict[str, Any]:
    """Launches GitHub Copilot cloud agent by creating an assigned GitHub issue."""

    normalized_token = normalize_github_copilot_token(settings.github_copilot_token)

    if not normalized_token:
        # Reject launch attempts when the GitHub Copilot token has not been configured.
        raise GitHubCopilotAgentError("Connect GitHub Copilot cloud agent before launching a live agent.")

    normalized_target_repo = target_repo.strip()

    if "/" not in normalized_target_repo:
        # Reject malformed repository names before constructing the GitHub REST URL.
        raise GitHubCopilotAgentError("GitHub Copilot cloud agent requires a target repository in owner/repo format.")

    agent_assignment: Dict[str, str] = {
        "target_repo": normalized_target_repo,
        "base_branch": base_ref.strip() or "main",
        "custom_instructions": prompt_text.strip(),
        "custom_agent": settings.github_copilot_custom_agent.strip(),
        "model": settings.github_copilot_model.strip(),
    }
    payload = {
        "title": issue_title.strip() or "AI Control Pane task",
        "body": _build_github_copilot_issue_body(prompt_text, source_issue),
        "assignees": ["copilot-swe-agent[bot]"],
        "agent_assignment": agent_assignment,
    }

    try:
        issue_response = _request_json(
            f"https://api.github.com/repos/{normalized_target_repo}/issues",
            method="POST",
            headers=_build_github_copilot_headers(normalized_token),
            payload=payload,
        )
    except HTTPError as error:
        # Surface the upstream GitHub API error message with a product-specific prefix.
        raise GitHubCopilotAgentError(f"GitHub Copilot cloud agent launch failed: {_extract_provider_error_message(error)}") from error
    except (URLError, json.JSONDecodeError) as error:
        # Surface transport and parsing failures with a stable product-specific message.
        raise GitHubCopilotAgentError("GitHub Copilot cloud agent launch failed because the API response could not be read.") from error

    issue_number = str(issue_response.get("number", "")).strip()
    issue_url = str(issue_response.get("html_url", "")).strip()
    issue_id = str(issue_response.get("id", issue_number or "unknown")).strip()
    created_at = str(issue_response.get("created_at", "")).strip() or _utc_timestamp()

    # Return a Cursor-compatible cloudAgent payload so the frontend can render both providers.
    return {
        "id": f"github-copilot-{issue_id}",
        "name": "GitHub Copilot cloud agent",
        "provider": "github-copilot-cloud-agent",
        "status": "ASSIGNED",
        "createdAt": created_at,
        "summary": "GitHub Copilot cloud agent was assigned to the generated issue.",
        "source": {
            "repository": normalized_target_repo,
            "ref": base_ref.strip() or "main",
        },
        "target": {
            "branchName": "",
            "url": issue_url,
            "prUrl": "",
            "autoCreatePr": True,
            "issueUrl": issue_url,
        },
        "issue": {
            "id": issue_id,
            "number": issue_number,
            "url": issue_url,
        },
    }
