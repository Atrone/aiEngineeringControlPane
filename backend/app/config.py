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
    cursor_api_key: str
    cursor_model: str
    docs_directory: str
    default_user_name: str
    default_user_email: str
    default_user_role: str
    frontend_base_url: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_hosted_domain: str
    google_allowed_domains: List[str]
    google_authorized_emails: List[str]
    google_authorized_domains: List[str]
    openai_api_key: str
    openai_model: str
    openai_base_url: str


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
    google_allowed_domains = _parse_csv(os.getenv("GOOGLE_ALLOWED_DOMAINS", ""))
    google_authorized_emails = [
        *_parse_csv(os.getenv("GOOGLE_ADMIN_EMAILS", "")),
        *_parse_csv(os.getenv("GOOGLE_TECH_LEAD_EMAILS", "")),
        *_parse_csv(os.getenv("GOOGLE_ENGINEER_EMAILS", "")),
    ]
    google_authorized_domains = [
        *_parse_csv(os.getenv("GOOGLE_ADMIN_DOMAINS", "")),
        *_parse_csv(os.getenv("GOOGLE_TECH_LEAD_DOMAINS", "")),
        *_parse_csv(os.getenv("GOOGLE_ENGINEER_DOMAINS", "")),
    ]

    # Return the provider configuration used by the integration layer.
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        github_owner=os.getenv("GITHUB_OWNER", "").strip(),
        github_repositories=github_repositories,
        linear_api_key=os.getenv("LINEAR_API_KEY", "").strip(),
        linear_team_id=os.getenv("LINEAR_TEAM_ID", "").strip(),
        cursor_api_key=os.getenv("CURSOR_API_KEY", "").strip(),
        cursor_model=os.getenv("CURSOR_MODEL", "default").strip() or "default",
        docs_directory=_resolve_docs_directory(),
        default_user_name=os.getenv("CONTROL_PANE_DEFAULT_USER_NAME", "Maya Chen").strip(),
        default_user_email=os.getenv("CONTROL_PANE_DEFAULT_USER_EMAIL", "maya.chen@example.com").strip(),
        default_user_role=os.getenv("CONTROL_PANE_DEFAULT_USER_ROLE", "admin").strip(),
        frontend_base_url=os.getenv("CONTROL_PANE_FRONTEND_URL", "http://localhost:5173").strip(),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
        google_hosted_domain=os.getenv("GOOGLE_HOSTED_DOMAIN", "").strip(),
        google_allowed_domains=google_allowed_domains,
        google_authorized_emails=google_authorized_emails,
        google_authorized_domains=google_authorized_domains,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        openai_base_url=(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip() or "https://api.openai.com/v1").rstrip("/"),
    )
