"""Route coverage for integration connect callables in main.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import main
from app.schemas import CursorConnectRequest
from app.schemas import DocsConnectRequest
from app.schemas import GitHubConnectRequest
from app.schemas import GitHubCopilotConnectRequest
from app.schemas import JiraConnectRequest
from app.schemas import LinearConnectRequest


class MainIntegrationRouteTests(unittest.TestCase):
    """Verifies integration connect route wrappers in main.py."""

    def test_connect_routes_mutate_session_and_refresh_integrations(self) -> None:
        """Covers GitHub, Linear, Jira, docs, Cursor, and Copilot route wrappers."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        session = SimpleNamespace()

        with patch("app.main._authorized_request_with_roles", return_value=("settings", {"x": "y"}, session)), patch(
            "app.main.build_effective_settings",
            return_value="effective-settings",
        ), patch(
            "app.main.build_request_headers",
            return_value={"x-demo-user-email": "user@example.com"},
        ), patch(
            "app.main.get_integrations_payload",
            return_value={"statuses": []},
        ) as mock_get_integrations_payload, patch(
            "app.main.connect_github"
        ) as mock_connect_github, patch(
            "app.main.connect_linear"
        ) as mock_connect_linear, patch(
            "app.main.connect_jira"
        ) as mock_connect_jira, patch(
            "app.main.connect_docs"
        ) as mock_connect_docs, patch(
            "app.main.connect_cursor"
        ) as mock_connect_cursor, patch(
            "app.main.connect_github_copilot"
        ) as mock_connect_github_copilot:
            # Confirm GitHub connect delegates to the auth helper and refreshes integrations.
            github_response = main.post_github_connect(
                GitHubConnectRequest(owner="acme", repositories="repo-one", token="gh-token"),
                request,
            )
            self.assertEqual(github_response["statuses"], [])
            mock_connect_github.assert_called_once_with(session, "acme", "repo-one", "gh-token")

            # Confirm Linear connect delegates to the auth helper and refreshes integrations.
            linear_response = main.post_linear_connect(
                LinearConnectRequest.model_validate({"apiKey": "lin-token", "teamId": "team-1"}),
                request,
            )
            self.assertEqual(linear_response["statuses"], [])
            mock_connect_linear.assert_called_once_with(session, "lin-token", "team-1")

            # Confirm Jira connect delegates to the auth helper and refreshes integrations.
            jira_response = main.post_jira_connect(
                JiraConnectRequest.model_validate(
                    {
                        "siteUrl": "https://acme.atlassian.net",
                        "email": "owner@example.com",
                        "apiToken": "jira-token",
                        "projectKey": "ACP",
                    }
                ),
                request,
            )
            self.assertEqual(jira_response["statuses"], [])
            mock_connect_jira.assert_called_once_with(
                session,
                "https://acme.atlassian.net",
                "owner@example.com",
                "jira-token",
                "ACP",
            )

            # Confirm docs connect delegates to the auth helper and refreshes integrations.
            docs_response = main.post_docs_connect(
                DocsConnectRequest.model_validate({"docsDirectory": "docs"}),
                request,
            )
            self.assertEqual(docs_response["statuses"], [])
            mock_connect_docs.assert_called_once_with(session, "docs")

            # Confirm Cursor connect delegates to the auth helper and refreshes integrations.
            cursor_response = main.post_cursor_connect(
                CursorConnectRequest.model_validate({"apiKey": "cursor-token", "model": "default"}),
                request,
            )
            self.assertEqual(cursor_response["statuses"], [])
            mock_connect_cursor.assert_called_once_with(session, "cursor-token", "default")

            # Confirm GitHub Copilot connect delegates to the auth helper and refreshes integrations.
            copilot_response = main.post_github_copilot_connect(
                GitHubCopilotConnectRequest.model_validate({"token": "gh-token", "model": "gpt", "customAgent": "reviewer"}),
                request,
            )
            self.assertEqual(copilot_response["statuses"], [])
            mock_connect_github_copilot.assert_called_once_with(session, "gh-token", "gpt", "reviewer")

            # Confirm each connect route requested a fresh integrations payload.
            self.assertEqual(mock_get_integrations_payload.call_count, 6)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
