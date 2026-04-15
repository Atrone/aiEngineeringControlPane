"""Regression coverage for the Cursor Cloud Agents integration and run launch flow."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import SESSION_STORE
from app.main import app


class CursorAgentLaunchTests(unittest.TestCase):
    """Verifies Cursor Cloud Agents can be connected and launched from a task run."""

    def setUp(self) -> None:
        """Creates a clean API client and clears shared in-memory session state."""

        # Reset the in-memory session store so each test runs in isolation.
        SESSION_STORE.clear()

        # Create a fresh FastAPI test client for the endpoint checks.
        self.client = TestClient(app)

    def _sign_in(self) -> str:
        """Signs in a tech lead user and returns the bearer token for follow-up requests."""

        # Create a session that is allowed to mutate integration settings and start runs.
        response = self.client.post(
            "/api/auth/sign-in",
            json={"name": "Test User", "email": "test@example.com", "role": "tech_lead"},
        )

        # Ensure the test only continues when sign-in succeeded.
        self.assertEqual(response.status_code, 200)

        # Return the generated session token for authenticated requests.
        return response.json()["sessionToken"]

    def test_connect_cursor_saves_model_and_reports_live_status(self) -> None:
        """Stores the Cursor API key and model while returning a live integration status."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        with patch(
            "app.providers._request_json",
            return_value={"apiKeyName": "Test Key", "userEmail": "developer@example.com"},
        ):
            # Save the Cursor connection for the current session.
            response = self.client.post(
                "/api/integrations/cursor/connect",
                json={"apiKey": "cursor_api_example", "model": "default"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the endpoint accepted the setup payload.
        self.assertEqual(response.status_code, 200)

        # Confirm the saved session values were stored for later live launches.
        self.assertEqual(SESSION_STORE[session_token].cursor_api_key, "cursor_api_example")
        self.assertEqual(SESSION_STORE[session_token].cursor_model, "default")

        # Confirm the Cursor integration is reported as live for the current session.
        cursor_status = next(item for item in response.json()["statuses"] if item["id"] == "cursor_cloud_agents")
        self.assertTrue(cursor_status["connected"])
        self.assertEqual(cursor_status["mode"], "live")

    def test_create_run_launches_cursor_agent_with_linear_issue_context(self) -> None:
        """Launches a real Cursor agent request using the selected Linear issue and GitHub repo."""

        # Create an authorized session for the task and run requests.
        session_token = self._sign_in()
        session = SESSION_STORE[session_token]
        session.github_owner = "acme"
        session.github_repositories = ["platform-web"]
        session.linear_api_key = "lin_api_example"
        session.cursor_api_key = "cursor_api_example"
        session.cursor_model = "default"
        launched_payloads = []

        def mock_provider_request(
            url: str,
            *,
            method: str = "GET",
            headers=None,
            payload=None,
        ):
            """Returns provider fixtures while capturing the Cursor launch payload."""

            if url == "https://api.cursor.com/v0/me":
                # Return the Cursor API identity used by the integration status checks.
                return {"apiKeyName": "Test Key", "userEmail": "developer@example.com"}

            if url == "https://api.github.com/repos/acme/platform-web":
                # Return the repository metadata used to build the GitHub launch target.
                return {
                    "id": 101,
                    "name": "platform-web",
                    "full_name": "acme/platform-web",
                    "default_branch": "main",
                    "private": False,
                    "html_url": "https://github.com/acme/platform-web",
                }

            if url == "https://api.linear.app/graphql":
                query_text = (payload or {}).get("query", "")

                if "viewer" in query_text:
                    # Return the Linear auth-check payload used by the integration status checks.
                    return {"data": {"viewer": {"id": "viewer-123"}}}

                # Return the live Linear issue used during task creation.
                return {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "issue-42",
                                    "identifier": "ENG-42",
                                    "title": "Wire Cursor Cloud Agents into run launch",
                                    "description": "Use the selected GitHub repository and preserve issue traceability.",
                                    "priority": 1,
                                    "url": "https://linear.app/acme/issue/ENG-42",
                                    "state": {"name": "Todo"},
                                    "assignee": {"name": "Maya", "email": "maya@example.com"},
                                }
                            ]
                        }
                    }
                }

            if url == "https://api.cursor.com/v0/agents" and method == "POST":
                # Capture the launch payload so the test can inspect the Cursor prompt and target.
                launched_payloads.append(payload or {})

                return {
                    "id": "bc_123",
                    "name": "ENG-42 launch",
                    "status": "CREATING",
                    "createdAt": "2026-04-15T12:00:00Z",
                    "source": {
                        "repository": "https://github.com/acme/platform-web",
                        "ref": "main",
                    },
                    "target": {
                        "branchName": "ai/eng-42-wire-cursor-cloud-agents-into-run-launch",
                        "url": "https://cursor.com/agents?id=bc_123",
                        "prUrl": "",
                        "autoCreatePr": True,
                        "openAsCursorGithubApp": False,
                        "skipReviewerRequest": False,
                    },
                }

            # Fail fast when the backend reaches for an unexpected provider request.
            raise AssertionError(f"Unexpected provider request: {method} {url}")

        with patch("app.providers._request_json", side_effect=mock_provider_request):
            # Create a task that is linked to the mocked Linear issue.
            task_response = self.client.post(
                "/api/tasks",
                json={
                    "issueId": "issue-42",
                    "repoName": "platform-web",
                    "title": "Wire Cursor Cloud Agents into run launch",
                    "prompt": "Launch the live cloud agent from the backend.",
                    "acceptanceCriteria": "Launch against GitHub and preserve the Linear issue ticket context.",
                    "documentIds": [],
                    "executionMode": "implement",
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )

            # Confirm the task creation request succeeded before starting the run.
            self.assertEqual(task_response.status_code, 200)
            created_run = task_response.json()

            # Start the run so the backend launches a real Cursor Cloud Agent request.
            run_response = self.client.post(
                "/api/runs",
                json={"taskId": created_run["id"], "agentName": "impl-agent", "executionMode": "implement"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the live run launch request succeeded.
        self.assertEqual(run_response.status_code, 200)
        launched_run = run_response.json()

        # Confirm the backend surfaced the launched Cursor agent metadata.
        self.assertEqual(launched_run["agent"], "cursor-cloud-agent")
        self.assertEqual(launched_run["cloudAgent"]["id"], "bc_123")
        self.assertEqual(launched_run["cloudAgent"]["source"]["repository"], "https://github.com/acme/platform-web")

        # Confirm the backend sent one concrete Cursor launch request.
        self.assertEqual(len(launched_payloads), 1)
        launch_payload = launched_payloads[0]
        self.assertEqual(launch_payload["source"]["repository"], "https://github.com/acme/platform-web")
        self.assertEqual(launch_payload["source"]["ref"], "main")
        self.assertEqual(launch_payload["target"]["autoCreatePr"], True)
        self.assertIn("ENG-42", launch_payload["prompt"]["text"])
        self.assertIn("Wire Cursor Cloud Agents into run launch", launch_payload["prompt"]["text"])
        self.assertIn("Launch against GitHub and preserve the Linear issue ticket context.", launch_payload["prompt"]["text"])


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
