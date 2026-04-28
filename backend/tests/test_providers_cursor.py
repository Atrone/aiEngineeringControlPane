"""Unit coverage for Cursor Cloud Agent provider helpers."""

import io
import unittest
from dataclasses import replace
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderCursorTests(unittest.TestCase):
    """Verifies Cursor connection, launch, and status helpers."""

    def test_cursor_connection_and_agent_helpers_cover_success_and_error_paths(self) -> None:
        """Covers Cursor connectivity plus agent launch and lookup behavior."""

        disconnected_settings = get_settings()

        # Confirm Cursor connectivity is false when the API key is missing.
        self.assertFalse(providers.is_cursor_connected(disconnected_settings))

        connected_settings = replace(get_settings(), cursor_api_key="cursor-token", cursor_model="gpt")

        with patch("app.providers._request_json", return_value={"userEmail": "developer@example.com"}):
            # Confirm Cursor connectivity is true when the auth check returns a user email.
            self.assertTrue(providers.is_cursor_connected(connected_settings))

            # Confirm live agent launch returns the provider payload when the API call succeeds.
            launch_payload = providers.launch_cursor_agent(
                connected_settings,
                repository_url="https://github.com/acme/platform-web",
                base_ref="main",
                branch_name="ai/acp-1",
                prompt_text="Implement the task.",
            )
            self.assertEqual(launch_payload["userEmail"], "developer@example.com")

            # Confirm status lookup returns the provider payload when the API call succeeds.
            agent_payload = providers.get_cursor_agent(connected_settings, "agent-1")
            self.assertEqual(agent_payload["userEmail"], "developer@example.com")

        with patch(
            "app.providers._request_json",
            side_effect=[
                {"items": [{"path": "artifacts/result.txt", "sizeBytes": 12}]},
                {"url": "https://artifact.example.com/result.txt", "expiresAt": "2026-04-28T19:00:00Z"},
            ],
        ), patch("app.providers._request_bytes", return_value=(b"artifact body", "text/plain")):
            # Confirm Cursor artifact helpers list, download, and read artifact results.
            artifact_listing = providers.list_cursor_artifacts(connected_settings, "agent-1")
            artifact_download = providers.download_cursor_artifact(
                connected_settings,
                "agent-1",
                "artifacts/result.txt",
            )
            artifact_body, artifact_content_type = providers.read_cursor_artifact_content(artifact_download["url"])
            self.assertEqual(artifact_listing["items"][0]["path"], "artifacts/result.txt")
            self.assertEqual(artifact_download["url"], "https://artifact.example.com/result.txt")
            self.assertEqual(artifact_body, b"artifact body")
            self.assertEqual(artifact_content_type, "text/plain")

        with self.assertRaises(providers.CursorAgentError):
            # Confirm live launch is rejected when Cursor is not configured.
            providers.launch_cursor_agent(
                disconnected_settings,
                repository_url="https://github.com/acme/platform-web",
                base_ref="main",
                branch_name="ai/acp-1",
                prompt_text="Implement the task.",
            )

        with self.assertRaises(providers.CursorAgentError):
            # Confirm status lookup is rejected when Cursor is not configured.
            providers.get_cursor_agent(disconnected_settings, "agent-1")

        launch_error = HTTPError(
            url="https://api.cursor.com/v0/agents",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"Invalid Cursor token"}'),
        )
        lookup_error_response = HTTPError(
            url="https://api.cursor.com/v0/agents/agent-1",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"Invalid Cursor token"}'),
        )

        with patch("app.providers._request_json", side_effect=[launch_error, lookup_error_response]):
            # Confirm provider HTTP failures are translated into readable CursorAgentError messages.
            with self.assertRaises(providers.CursorAgentError) as launch_error:
                providers.launch_cursor_agent(
                    connected_settings,
                    repository_url="https://github.com/acme/platform-web",
                    base_ref="main",
                    branch_name="ai/acp-1",
                    prompt_text="Implement the task.",
                )
            self.assertIn("Invalid Cursor token", str(launch_error.exception))

            with self.assertRaises(providers.CursorAgentError) as lookup_error:
                providers.get_cursor_agent(connected_settings, "agent-1")
            self.assertIn("Invalid Cursor token", str(lookup_error.exception))

        with patch("app.providers._request_json", side_effect=URLError("offline")):
            # Confirm transport failures are translated into stable CursorAgentError messages.
            with self.assertRaises(providers.CursorAgentError):
                providers.launch_cursor_agent(
                    connected_settings,
                    repository_url="https://github.com/acme/platform-web",
                    base_ref="main",
                    branch_name="ai/acp-1",
                    prompt_text="Implement the task.",
                )

            with self.assertRaises(providers.CursorAgentError):
                providers.get_cursor_agent(connected_settings, "agent-1")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
