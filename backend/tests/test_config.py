"""Unit coverage for environment-driven backend configuration helpers."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config


class ConfigHelpersTests(unittest.TestCase):
    """Verifies CSV parsing, docs resolution, and settings construction."""

    def test_parse_csv_and_resolve_docs_directory_normalize_values(self) -> None:
        """Covers the small config helpers for parsing and docs-path resolution."""

        # Confirm CSV parsing trims whitespace and removes empty entries.
        self.assertEqual(config._parse_csv(" one , , two,three "), ["one", "two", "three"])

        with patch.dict(os.environ, {"CONTROL_PANE_DOCS_DIR": "custom-docs"}, clear=False):
            # Confirm the explicit docs directory override wins when configured.
            self.assertEqual(config._resolve_docs_directory(), "custom-docs")

        with patch.dict(os.environ, {"CONTROL_PANE_DOCS_DIR": ""}, clear=False):
            # Confirm the helper falls back to the repository docs directory.
            resolved_docs_directory = Path(config._resolve_docs_directory())
            self.assertEqual(resolved_docs_directory.name, "docs")

    def test_get_settings_reads_environment_and_applies_defaults(self) -> None:
        """Covers settings construction from both configured and default values."""

        env = {
            "GITHUB_TOKEN": "gh-token",
            "GITHUB_OWNER": "acme",
            "GITHUB_REPOSITORIES": "repo-one, repo-two",
            "LINEAR_API_KEY": "lin-token",
            "LINEAR_TEAM_ID": "team-1",
            "JIRA_SITE_URL": "https://acme.atlassian.net/",
            "JIRA_EMAIL": "owner@example.com",
            "JIRA_API_TOKEN": "jira-token",
            "JIRA_PROJECT_KEY": "ACP",
            "CURSOR_API_KEY": "cursor-token",
            "CURSOR_MODEL": "gpt",
            "GITHUB_COPILOT_TOKEN": "copilot-token",
            "GITHUB_COPILOT_MODEL": "claude-sonnet-4.5",
            "GITHUB_COPILOT_CUSTOM_AGENT": "security-reviewer",
            "CONTROL_PANE_DOCS_DIR": "docs/custom",
            "CONTROL_PANE_DEFAULT_USER_NAME": "Config User",
            "CONTROL_PANE_DEFAULT_USER_EMAIL": "config@example.com",
            "CONTROL_PANE_DEFAULT_USER_ROLE": "admin",
            "CONTROL_PANE_FRONTEND_URL": "http://frontend.example.com/",
            "GOOGLE_CLIENT_ID": "google-client",
            "GOOGLE_CLIENT_SECRET": "google-secret",
            "GOOGLE_REDIRECT_URI": "http://frontend.example.com/callback",
            "GOOGLE_HOSTED_DOMAIN": "example.com",
            "GOOGLE_ALLOWED_DOMAINS": "example.com,example.org",
            "GOOGLE_ADMIN_EMAILS": "admin@example.com",
            "GOOGLE_TECH_LEAD_EMAILS": "lead@example.com",
            "GOOGLE_ENGINEER_EMAILS": "engineer@example.com",
            "GOOGLE_ADMIN_DOMAINS": "example.com",
            "GOOGLE_TECH_LEAD_DOMAINS": "engineering.example.com",
            "GOOGLE_ENGINEER_DOMAINS": "contractors.example.com",
            "OPENAI_API_KEY": "openai-token",
            "OPENAI_MODEL": "gpt-4.1",
            "OPENAI_BASE_URL": "https://example-openai.test/v1/",
        }

        with patch.dict(os.environ, env, clear=True):
            # Confirm the settings object reflects the configured environment.
            settings = config.get_settings()

        self.assertEqual(settings.github_owner, "acme")
        self.assertEqual(settings.github_repositories, ["repo-one", "repo-two"])
        self.assertEqual(settings.jira_site_url, "https://acme.atlassian.net")
        self.assertEqual(settings.cursor_model, "gpt")
        self.assertEqual(settings.github_copilot_model, "claude-sonnet-4.5")
        self.assertEqual(settings.github_copilot_custom_agent, "security-reviewer")
        self.assertEqual(settings.docs_directory, "docs/custom")
        self.assertEqual(settings.frontend_base_url, "http://frontend.example.com/")
        self.assertEqual(settings.google_authorized_emails, ["admin@example.com", "lead@example.com", "engineer@example.com"])
        self.assertEqual(
            settings.google_authorized_domains,
            ["example.com", "engineering.example.com", "contractors.example.com"],
        )
        self.assertEqual(settings.openai_base_url, "https://example-openai.test/v1")

        with patch.dict(os.environ, {}, clear=True):
            # Confirm the helper falls back to built-in defaults when env vars are missing.
            default_settings = config.get_settings()

        self.assertEqual(default_settings.cursor_model, "default")
        self.assertEqual(default_settings.github_copilot_token, "")
        self.assertEqual(default_settings.default_user_name, "Maya Chen")
        self.assertEqual(default_settings.openai_model, "gpt-4o-mini")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
