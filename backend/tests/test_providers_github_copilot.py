"""Unit coverage for GitHub Copilot cloud agent provider helpers."""

import io
import unittest
from dataclasses import replace
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderGitHubCopilotTests(unittest.TestCase):
    """Verifies GitHub Copilot connection and launch helpers."""

    def test_github_copilot_connection_and_launch_cover_success_and_errors(self) -> None:
        """Covers Copilot connectivity plus issue-assignment launch behavior."""

        disconnected_settings = get_settings()

        # Confirm Copilot connectivity is false when the token is missing.
        self.assertFalse(providers.is_github_copilot_connected(disconnected_settings))

        connected_settings = replace(
            get_settings(),
            github_copilot_token="gh-token",
            github_copilot_model="gpt",
            github_copilot_custom_agent="reviewer",
        )
        issue_payload = {
            "id": 123,
            "number": 42,
            "html_url": "https://github.com/acme/platform-web/issues/42",
            "created_at": "2026-05-11T17:00:00Z",
        }

        with patch("app.provider_github_copilot._request_json", side_effect=[{"login": "developer"}, issue_payload]) as mock_request:
            # Confirm Copilot connectivity is true when GitHub returns a user login.
            self.assertTrue(providers.is_github_copilot_connected(connected_settings))

            # Confirm live launch creates a Copilot-assigned issue and normalizes metadata.
            launch_payload = providers.launch_github_copilot_agent(
                connected_settings,
                target_repo="acme/platform-web",
                base_ref="main",
                prompt_text="Implement the task.",
                issue_title="Add feature",
                source_issue={"url": "https://linear.app/acme/issue/ACP-1"},
            )

        self.assertEqual(launch_payload["id"], "github-copilot-123")
        self.assertEqual(launch_payload["provider"], "github-copilot-cloud-agent")
        self.assertEqual(launch_payload["target"]["url"], "https://github.com/acme/platform-web/issues/42")
        self.assertEqual(mock_request.call_args.kwargs["payload"]["assignees"], ["copilot-swe-agent[bot]"])
        self.assertEqual(mock_request.call_args.kwargs["payload"]["agent_assignment"]["target_repo"], "acme/platform-web")
        self.assertEqual(mock_request.call_args.kwargs["payload"]["agent_assignment"]["custom_agent"], "reviewer")

        with self.assertRaises(providers.GitHubCopilotAgentError):
            # Confirm live launch is rejected when Copilot is not configured.
            providers.launch_github_copilot_agent(
                disconnected_settings,
                target_repo="acme/platform-web",
                base_ref="main",
                prompt_text="Implement the task.",
                issue_title="Add feature",
                source_issue={},
            )

        launch_error = HTTPError(
            url="https://api.github.com/repos/acme/platform-web/issues",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"Copilot cannot be assigned"}'),
        )

        with patch("app.provider_github_copilot._request_json", side_effect=launch_error):
            # Confirm provider HTTP failures are translated into readable Copilot errors.
            with self.assertRaises(providers.GitHubCopilotAgentError) as github_error:
                providers.launch_github_copilot_agent(
                    connected_settings,
                    target_repo="acme/platform-web",
                    base_ref="main",
                    prompt_text="Implement the task.",
                    issue_title="Add feature",
                    source_issue={},
                )
            self.assertIn("Copilot cannot be assigned", str(github_error.exception))

        with patch("app.provider_github_copilot._request_json", side_effect=URLError("offline")):
            # Confirm transport failures are translated into stable Copilot error messages.
            with self.assertRaises(providers.GitHubCopilotAgentError):
                providers.launch_github_copilot_agent(
                    connected_settings,
                    target_repo="acme/platform-web",
                    base_ref="main",
                    prompt_text="Implement the task.",
                    issue_title="Add feature",
                    source_issue={},
                )


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
