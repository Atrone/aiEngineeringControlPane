"""Unit coverage for shared provider normalization and low-level helpers."""

import io
import json
import unittest
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderNormalizationTests(unittest.TestCase):
    """Verifies shared provider helpers used across multiple integrations."""

    def test_low_level_request_and_normalization_helpers_cover_expected_behavior(self) -> None:
        """Covers request helpers, normalization, auth headers, and shared payload builders."""

        class FakeResponse:
            """Provides a simple context-manager HTTP response stub."""

            def __init__(self, payload, status=204):
                """Stores the response body and status code for the fake response."""

                # Preserve the payload and status for later read/assertion calls.
                self.payload = payload
                self.status = status

            def __enter__(self):
                """Returns the fake response itself for the context manager."""

                # Yield this fake response object to the caller.
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                """Implements the context-manager exit hook."""

                # Report that exceptions should still propagate normally.
                return False

            def read(self):
                """Returns the encoded JSON response body."""

                # Serialize the stored payload into the byte body providers.py expects.
                return json.dumps(self.payload).encode("utf-8")

        with patch("app.provider_common.urlopen", return_value=FakeResponse({"ok": True})):
            # Confirm the shared JSON request helper decodes a normal JSON response body.
            self.assertEqual(providers._request_json("https://example.test"), {"ok": True})

        fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
        with patch("app.provider_common.datetime") as mock_datetime:
            # Keep other datetime behaviors intact while fixing now() to a known instant.
            mock_datetime.now.return_value = fixed_now
            self.assertEqual(providers._utc_timestamp(), fixed_now.isoformat())

        # Confirm provider normalization helpers trim whitespace and clean pasted prefixes.
        self.assertEqual(providers.normalize_linear_api_key(" Bearer lin_key "), "lin_key")
        self.assertEqual(providers.normalize_jira_site_url(" acme.atlassian.net/ "), "https://acme.atlassian.net")
        self.assertEqual(providers.normalize_cursor_api_key(" Bearer cursor_key "), "cursor_key")

        # Confirm Cursor and Jira auth-header helpers build the expected auth schemes.
        self.assertIn("Basic ", providers._build_cursor_headers("cursor_key")["Authorization"])
        jira_headers = providers._build_jira_headers(
            replace(get_settings(), jira_email="owner@example.com", jira_api_token="jira-token")
        )
        self.assertIn("Basic ", jira_headers["Authorization"])

        error = providers.HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"Readable provider error"}'),
        )

        # Confirm provider error extraction prefers readable JSON messages.
        self.assertEqual(
            providers._extract_provider_error_message(error),
            "Readable provider error",
        )

    def test_jira_github_identity_and_connection_helpers_cover_expected_behavior(self) -> None:
        """Covers Jira request wrappers plus identity and connection summary helpers."""

        settings = replace(
            get_settings(),
            jira_site_url="https://acme.atlassian.net",
            jira_email="owner@example.com",
            jira_api_token="jira-token",
            github_owner="acme",
            github_repositories=["platform-web"],
            github_token="gh-token",
            linear_api_key="lin-token",
            linear_team_id="ENG",
            cursor_api_key="cursor-token",
            cursor_model="default",
            github_copilot_token="copilot-token",
            github_copilot_model="gpt",
            github_copilot_custom_agent="reviewer",
            docs_directory="docs",
            google_client_id="client",
            google_client_secret="secret",
            google_redirect_uri="http://localhost/callback",
        )

        with patch("app.provider_jira._request_json", return_value={"accountId": "acct-1"}):
            # Confirm Jira REST requests are wrapped with the normalized site URL and headers.
            jira_response = providers._request_jira_json(settings, path="/myself")
            self.assertEqual(jira_response["accountId"], "acct-1")

        with patch("app.provider_jira.urlopen", return_value=type("FakeTransitionResponse", (), {"status": 204, "__enter__": lambda self: self, "__exit__": lambda self, exc_type, exc_value, traceback: False})()):
            # Confirm Jira transition updates report success for 2xx responses.
            self.assertTrue(
                providers._request_jira_transition_update(
                    settings,
                    issue_id="10001",
                    transition_id="31",
                )
            )

        # Confirm identity resolution prefers SSO headers and falls back to configured defaults.
        current_user = providers.resolve_current_user(
            settings,
            {"x-goog-authenticated-user-email": "accounts.google.com:user@example.com"},
        )
        self.assertEqual(current_user["email"], "user@example.com")
        self.assertEqual(current_user["provider"], "google_sso")
        self.assertEqual(current_user["teamId"], "default")

        # Confirm connection payloads summarize non-secret integration fields.
        self.assertEqual(providers._build_connection_payload(settings, "github")["values"]["owner"], "acme")
        self.assertEqual(providers._build_connection_payload(settings, "linear")["values"]["teamId"], "ENG")
        self.assertEqual(providers._build_connection_payload(settings, "jira")["values"]["projectKey"], settings.jira_project_key)
        self.assertEqual(providers._build_connection_payload(settings, "cursor_cloud_agents")["values"]["model"], "default")
        self.assertEqual(providers._build_connection_payload(settings, "github_copilot_cloud_agent")["values"]["customAgent"], "reviewer")
        self.assertEqual(providers._build_connection_payload(settings, "repo_docs")["values"]["docsDirectory"], "docs")
        self.assertEqual(providers._build_connection_payload(settings, "google_sso")["label"], "Google OAuth configured")

        # Confirm repository-name summarization drops empty names and preserves order.
        self.assertEqual(
            providers.summarize_repository_names([{"name": "platform-web"}, {"name": ""}, {"name": "api-service"}]),
            ["platform-web", "api-service"],
        )

        # Confirm GitHub PR parsing and headers expose the expected fragments.
        self.assertEqual(
            providers.parse_github_pull_request_url("https://github.com/acme/platform-web/pull/42")["number"],
            "42",
        )
        self.assertIsNone(providers.parse_github_pull_request_url("https://example.com/not-a-pr"))
        self.assertIn("Authorization", providers._build_github_request_headers(settings))


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
