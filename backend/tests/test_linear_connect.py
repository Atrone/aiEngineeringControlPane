"""Regression coverage for the Linear connect endpoint."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import SESSION_STORE
from app.main import app


class LinearConnectEndpointTests(unittest.TestCase):
    """Verifies the Linear connect flow stays resilient for valid credentials."""

    def setUp(self) -> None:
        """Creates a clean API client and clears shared in-memory session state."""

        # Reset the in-memory session store so each test runs in isolation.
        SESSION_STORE.clear()

        # Create a fresh FastAPI test client for the endpoint checks.
        self.client = TestClient(app)

    def _sign_in(self) -> str:
        """Signs in a tech lead user and returns the bearer token for follow-up requests."""

        # Create a session that is allowed to mutate integration settings.
        response = self.client.post(
            "/api/auth/sign-in",
            json={"name": "Test User", "email": "test@example.com", "role": "tech_lead"},
        )

        # Ensure the test only continues when sign-in succeeded.
        self.assertEqual(response.status_code, 200)

        # Return the generated session token for authenticated requests.
        return response.json()["sessionToken"]

    def test_connect_linear_accepts_bearer_prefixed_keys(self) -> None:
        """Stores pasted bearer-prefixed keys in the raw Linear token format."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        with patch(
            "app.providers._request_json",
            side_effect=[
                {"data": {"issues": {"nodes": []}}},
                {"data": {"viewer": {"id": "viewer-123"}}},
                {"data": {"issues": {"nodes": []}}},
            ],
        ):
            # Post a Linear key copied from an Authorization header.
            response = self.client.post(
                "/api/integrations/linear/connect",
                json={"apiKey": "Bearer lin_api_example", "teamId": ""},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the endpoint accepted the pasted key format.
        self.assertEqual(response.status_code, 200)

        # Confirm the saved session value was normalized back to the raw API key.
        self.assertEqual(SESSION_STORE[session_token].linear_api_key, "lin_api_example")

        # Confirm the Linear integration is reported as live even with zero visible issues.
        linear_status = next(item for item in response.json()["statuses"] if item["id"] == "linear")
        self.assertTrue(linear_status["connected"])
        self.assertEqual(linear_status["mode"], "live")

    def test_connect_linear_handles_graphql_error_payloads(self) -> None:
        """Returns a successful connect response even when Linear omits a data payload."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        with patch(
            "app.providers._request_json",
            side_effect=[
                {"data": None, "errors": [{"message": "Bad request"}]},
                {"data": {"viewer": {"id": "viewer-123"}}},
                {"data": None, "errors": [{"message": "Bad request"}]},
            ],
        ):
            # Connect Linear while simulating a GraphQL error-shaped provider response.
            response = self.client.post(
                "/api/integrations/linear/connect",
                json={"apiKey": "lin_api_example", "teamId": ""},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the endpoint still saves the connection instead of failing the request.
        self.assertEqual(response.status_code, 200)

        # Confirm the integration remains marked as configured for the current session.
        linear_status = next(item for item in response.json()["statuses"] if item["id"] == "linear")
        self.assertTrue(linear_status["configured"])
        self.assertTrue(linear_status["connected"])
        self.assertEqual(linear_status["mode"], "live")

    def test_connect_linear_accepts_team_keys_for_scoped_issue_lookup(self) -> None:
        """Loads scoped issues when the saved team scope is a Linear team key instead of a team ID."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        def mock_linear_request(
            url: str,
            *,
            method: str = "GET",
            headers=None,
            payload=None,
        ):
            """Returns GraphQL fixtures that emulate a successful team-key fallback lookup."""

            query_text = (payload or {}).get("query", "")

            if "viewer" in query_text:
                # Return a successful auth check for the saved Linear credentials.
                return {"data": {"viewer": {"id": "viewer-123"}}}

            if "teams(filter:" in query_text and "id: { eq:" in query_text:
                # Return no team for the team-id attempt so the provider retries other scope formats.
                return {"data": {"teams": {"nodes": []}}}

            if "teams(filter:" in query_text and "key: { eq:" in query_text:
                # Return a matching team when the provider retries using the team key.
                return {
                    "data": {
                        "teams": {
                            "nodes": [
                                {
                                    "id": "team-123",
                                    "key": "ENG",
                                    "name": "Engineering",
                                }
                            ]
                        }
                    }
                }

            if "team(id:" in query_text:
                # Return a matching issue from the resolved team relation.
                return {
                    "data": {
                        "team": {
                            "issues": {
                                "nodes": [
                                    {
                                        "id": "issue-1",
                                        "identifier": "ENG-123",
                                        "title": "Scoped issue",
                                        "description": "Issue found through the team key fallback.",
                                        "priority": 2,
                                        "url": "https://linear.app/example/issue/ENG-123",
                                        "state": {"name": "Backlog"},
                                        "assignee": {"name": "Taylor", "email": "taylor@example.com"},
                                    }
                                ]
                            }
                        }
                    }
                }

            # Return no data for any other query shape used in the fallback chain.
            return {"data": {"teams": {"nodes": []}}}

        with patch("app.providers._request_json", side_effect=mock_linear_request):
            # Save a team key so the provider must retry team lookup formats.
            response = self.client.post(
                "/api/integrations/linear/connect",
                json={"apiKey": "lin_api_example", "teamId": "ENG"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the request succeeded for a valid team key scope.
        self.assertEqual(response.status_code, 200)

        # Confirm the scoped Linear status now reports live issue availability.
        linear_status = next(item for item in response.json()["statuses"] if item["id"] == "linear")
        self.assertTrue(linear_status["connected"])
        self.assertEqual(linear_status["mode"], "live")
        self.assertEqual(linear_status["details"], "1 issues available")

    def test_connect_linear_accepts_team_uuid_for_scoped_issue_lookup(self) -> None:
        """Loads scoped issues when the saved team scope is a concrete Linear team UUID."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        def mock_linear_request(
            url: str,
            *,
            method: str = "GET",
            headers=None,
            payload=None,
        ):
            """Returns GraphQL fixtures that emulate a successful team-id lookup."""

            query_text = (payload or {}).get("query", "")
            variables = (payload or {}).get("variables", {})

            if "viewer" in query_text:
                # Return a successful auth check for the saved Linear credentials.
                return {"data": {"viewer": {"id": "viewer-123"}}}

            if (
                "query ControlPaneTeams($teamScope: ID!)" in query_text
                and "teams(filter:" in query_text
                and variables.get("teamScope") == "b86658c9-96ae-4e47-a20d-669a1b1fc569"
            ):
                # Return the matching team when the provider looks it up by UUID.
                return {
                    "data": {
                        "teams": {
                            "nodes": [
                                {
                                    "id": "b86658c9-96ae-4e47-a20d-669a1b1fc569",
                                    "key": "SIG",
                                    "name": "Signal Craft Pro",
                                }
                            ]
                        }
                    }
                }

            if "team(id:" in query_text and variables.get("teamId") == "b86658c9-96ae-4e47-a20d-669a1b1fc569":
                # Return a matching issue from the resolved team relation.
                return {
                    "data": {
                        "team": {
                            "issues": {
                                "nodes": [
                                    {
                                        "id": "issue-2",
                                        "identifier": "SIG-42",
                                        "title": "Signal team issue",
                                        "description": "Issue found through the team UUID lookup.",
                                        "priority": 1,
                                        "url": "https://linear.app/example/issue/SIG-42",
                                        "state": {"name": "Todo"},
                                        "assignee": {"name": "Morgan", "email": "morgan@example.com"},
                                    }
                                ]
                            }
                        }
                    }
                }

            # Return no matches for any alternate lookup branches.
            return {"data": {"teams": {"nodes": []}}}

        with patch("app.providers._request_json", side_effect=mock_linear_request):
            # Save a UUID team scope so the provider resolves the team before reading its issues.
            response = self.client.post(
                "/api/integrations/linear/connect",
                json={"apiKey": "lin_api_example", "teamId": "b86658c9-96ae-4e47-a20d-669a1b1fc569"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the request succeeded for a valid team UUID scope.
        self.assertEqual(response.status_code, 200)

        # Confirm the scoped Linear status now reports live issue availability.
        linear_status = next(item for item in response.json()["statuses"] if item["id"] == "linear")
        self.assertTrue(linear_status["connected"])
        self.assertEqual(linear_status["mode"], "live")
        self.assertEqual(linear_status["details"], "1 issues available")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
