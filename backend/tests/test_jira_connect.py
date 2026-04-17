"""Regression coverage for the Jira Cloud connect endpoint."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import SESSION_STORE
from app.main import app


class JiraConnectEndpointTests(unittest.TestCase):
    """Verifies the Jira Cloud connect flow stays resilient for valid credentials."""

    def setUp(self) -> None:
        """Creates a clean API client and clears shared in-memory session state."""

        # Reset the in-memory session store so each test runs in isolation.
        SESSION_STORE.clear()

        # Create a fresh FastAPI test client for the endpoint checks.
        self.client = TestClient(app)

    def _sign_in(self) -> str:
        """Signs in an admin user and returns the bearer token for follow-up requests."""

        # Create a session that is allowed to mutate integration settings.
        response = self.client.post(
            "/api/auth/sign-in",
            json={"name": "Test User", "email": "test@example.com", "role": "admin"},
        )

        # Ensure the test only continues when sign-in succeeded.
        self.assertEqual(response.status_code, 200)

        # Return the generated session token for authenticated requests.
        return response.json()["sessionToken"]

    def test_connect_jira_normalizes_session_values_and_reports_live_status(self) -> None:
        """Stores normalized Jira values and reports Jira as live when issues are available."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        def mock_jira_request(
            url: str,
            *,
            method: str = "GET",
            headers=None,
            payload=None,
        ):
            """Returns Jira REST fixtures for the connect endpoint refresh flow."""

            if url.endswith("/rest/api/3/myself"):
                # Return a successful auth-check payload for the saved Jira credentials.
                return {"accountId": "acct-123"}

            if url.endswith("/rest/api/3/search"):
                # Return a visible Jira issue for both catalog and status refresh reads.
                return {
                    "issues": [
                        {
                            "id": "10001",
                            "key": "ENG-42",
                            "fields": {
                                "summary": "Wire Jira into the control pane",
                                "description": {
                                    "type": "doc",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": "Use Jira Cloud as a first-class issue tracker.",
                                                }
                                            ],
                                        }
                                    ],
                                },
                                "priority": {"name": "High"},
                                "status": {"name": "To Do"},
                                "assignee": {
                                    "displayName": "Taylor",
                                    "emailAddress": "taylor@example.com",
                                },
                            },
                        }
                    ]
                }

            # Fail fast when the backend reaches for an unexpected Jira request.
            raise AssertionError(f"Unexpected Jira request: {method} {url}")

        with patch("app.providers._request_json", side_effect=mock_jira_request):
            # Save the Jira connection using values copied from the Cloud UI.
            response = self.client.post(
                "/api/integrations/jira/connect",
                json={
                    "siteUrl": "your-team.atlassian.net/",
                    "email": "Taylor@example.com",
                    "apiToken": "jira_api_token",
                    "projectKey": "eng",
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the endpoint accepted the Jira Cloud connection details.
        self.assertEqual(response.status_code, 200)

        # Confirm the saved session values were normalized for later requests.
        self.assertEqual(SESSION_STORE[session_token].jira_site_url, "https://your-team.atlassian.net")
        self.assertEqual(SESSION_STORE[session_token].jira_email, "taylor@example.com")
        self.assertEqual(SESSION_STORE[session_token].jira_project_key, "ENG")

        jira_status = next(item for item in response.json()["statuses"] if item["id"] == "jira")

        # Confirm the Jira integration is reported as live with visible issues.
        self.assertTrue(jira_status["connected"])
        self.assertEqual(jira_status["mode"], "live")
        self.assertEqual(jira_status["details"], "1 issues available")
        self.assertEqual(jira_status["connection"]["values"]["siteUrl"], "https://your-team.atlassian.net")
        self.assertEqual(jira_status["connection"]["values"]["email"], "taylor@example.com")
        self.assertEqual(jira_status["connection"]["values"]["projectKey"], "ENG")

    def test_connect_jira_uses_the_saved_project_key_for_scoped_search(self) -> None:
        """Builds a project-scoped Jira search query when a project key is saved."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()
        seen_jql_values = []

        def mock_jira_request(
            url: str,
            *,
            method: str = "GET",
            headers=None,
            payload=None,
        ):
            """Captures the Jira search JQL so the test can verify project scoping."""

            if url.endswith("/rest/api/3/myself"):
                # Return a successful auth-check payload for the saved Jira credentials.
                return {"accountId": "acct-456"}

            if url.endswith("/rest/api/3/search"):
                # Record the JQL used by the Jira issue catalog read.
                seen_jql_values.append((payload or {}).get("jql", ""))

                # Return an empty issue list because the scope check is the regression target.
                return {"issues": []}

            # Fail fast when the backend reaches for an unexpected Jira request.
            raise AssertionError(f"Unexpected Jira request: {method} {url}")

        with patch("app.providers._request_json", side_effect=mock_jira_request):
            # Save a lower-case project key so the backend must normalize it for JQL.
            response = self.client.post(
                "/api/integrations/jira/connect",
                json={
                    "siteUrl": "https://acme.atlassian.net",
                    "email": "owner@example.com",
                    "apiToken": "jira_api_token",
                    "projectKey": "sig",
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the request succeeded before checking the captured JQL values.
        self.assertEqual(response.status_code, 200)

        # Confirm Jira search calls used the normalized project-scoped JQL.
        self.assertGreaterEqual(len(seen_jql_values), 1)
        self.assertTrue(all('project = "SIG"' in jql_value for jql_value in seen_jql_values))


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
