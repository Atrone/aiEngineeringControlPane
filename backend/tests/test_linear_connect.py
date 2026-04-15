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

        with patch("app.providers._request_json", return_value={"data": {"issues": {"nodes": []}}}):
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

    def test_connect_linear_handles_graphql_error_payloads(self) -> None:
        """Returns a successful connect response even when Linear omits a data payload."""

        # Create an authorized session for the integration update request.
        session_token = self._sign_in()

        with patch("app.providers._request_json", return_value={"data": None, "errors": [{"message": "Bad request"}]}):
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


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
