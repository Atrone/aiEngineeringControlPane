"""Configuration helpers for integration-aware backend behavior."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Settings:
    """Stores environment-driven configuration for provider integrations."""

    github_token: str
    github_owner: str
    github_repositories: List[str]
    linear_api_key: str
    linear_team_id: str
    docs_directory: str
    default_user_name: str
    default_user_email: str
    default_user_role: str
    google_client_id: str


def _parse_csv(raw_value: str) -> List[str]:
    """Parses a comma-separated environment value into a trimmed list."""

    values: List[str] = []

    # Split the raw environment value and normalize each entry.
    for item in raw_value.split(","):
        normalized = item.strip()

        if normalized:
            # Keep only non-empty configuration values.
            values.append(normalized)

    # Return the normalized list of configured values.
    return values


def _resolve_docs_directory() -> str:
    """Resolves the docs directory used by the repo-markdown knowledge integration."""

    configured_directory = os.getenv("CONTROL_PANE_DOCS_DIR", "").strip()

    if configured_directory:
        # Use the explicit docs directory when one is configured.
        return configured_directory

    repo_root = Path(__file__).resolve().parents[2]
    default_directory = repo_root / "docs"

    # Fall back to the repository docs folder when no override is present.
    return str(default_directory)


def get_settings() -> Settings:
    """Builds the immutable settings object from environment variables."""

    github_repositories = _parse_csv(os.getenv("GITHUB_REPOSITORIES", ""))

    # Return the provider configuration used by the integration layer.
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        github_owner=os.getenv("GITHUB_OWNER", "").strip(),
        github_repositories=github_repositories,
        linear_api_key=os.getenv("LINEAR_API_KEY", "").strip(),
        linear_team_id=os.getenv("LINEAR_TEAM_ID", "").strip(),
        docs_directory=_resolve_docs_directory(),
        default_user_name=os.getenv("CONTROL_PANE_DEFAULT_USER_NAME", "Maya Chen").strip(),
        default_user_email=os.getenv("CONTROL_PANE_DEFAULT_USER_EMAIL", "maya.chen@example.com").strip(),
        default_user_role=os.getenv("CONTROL_PANE_DEFAULT_USER_ROLE", "tech_lead").strip(),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
    )
