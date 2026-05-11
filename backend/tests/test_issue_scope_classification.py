"""Regression coverage for OpenAI-backed intake issue scoping."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import SESSION_STORE
from app.config import Settings
from app.main import app
from app.providers import classify_intake_issues_by_scope


class IssueScopeClassificationTests(unittest.TestCase):
    """Verifies the OpenAI-backed issue scoping behavior stays stable."""

    def setUp(self) -> None:
        """Clears shared session state before each isolated test case."""

        # Reset the in-memory session store so auth-dependent tests stay isolated.
        SESSION_STORE.clear()

    def _build_settings(self) -> Settings:
        """Builds a minimal settings fixture for direct provider unit tests."""

        # Return a complete settings object with only the OpenAI fields meaningfully populated.
        return Settings(
            github_token="",
            github_owner="",
            github_repositories=[],
            linear_api_key="",
            linear_team_id="",
            jira_site_url="",
            jira_email="",
            jira_api_token="",
            jira_project_key="",
            cursor_api_key="",
            cursor_model="default",
            github_copilot_token="",
            github_copilot_model="",
            github_copilot_custom_agent="",
            docs_directory="",
            default_user_name="Test User",
            default_user_email="test@example.com",
            default_user_role="admin",
            frontend_base_url="http://localhost:5173",
            google_client_id="",
            google_client_secret="",
            google_redirect_uri="",
            google_hosted_domain="",
            google_allowed_domains=[],
            google_authorized_emails=[],
            google_authorized_domains=[],
            openai_api_key="test-openai-key",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        )

    def test_classify_issue_scope_defaults_unassigned_issues_to_poorly_scoped(self) -> None:
        """Places omitted issue IDs into the poorly-scoped bucket as a safe fallback."""

        settings = self._build_settings()
        issues = [
            {
                "id": "issue-1",
                "ticket": "ACP-1",
                "title": "Add retry button to failed runs",
                "description": "Add a retry button on blocked runs and reuse the existing restart API.",
                "priority": "High",
                "status": "Todo",
                "provider": "jira",
            },
            {
                "id": "issue-2",
                "ticket": "ACP-2",
                "title": "Improve onboarding",
                "description": "Figure out the best onboarding experience for admins and engineers.",
                "priority": "Medium",
                "status": "Todo",
                "provider": "linear",
            },
        ]
        openai_payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"wellScopedIssueIds": ["issue-1"], "poorlyScopedIssueIds": []}',
                    }
                }
            ]
        }

        with patch("app.providers._request_json", return_value=openai_payload):
            # Run the direct provider helper so response normalization is exercised end to end.
            result = classify_intake_issues_by_scope(settings, issues=issues)

        # Confirm OpenAI's explicit well-scoped assignment is preserved.
        self.assertEqual(result["wellScopedIssueIds"], ["issue-1"])

        # Confirm omitted issues fall back to poorly scoped instead of disappearing.
        self.assertEqual(result["poorlyScopedIssueIds"], ["issue-2"])
        self.assertEqual(result["model"], "gpt-4o-mini")
        self.assertEqual(result["issueCount"], 2)


class IssueScopeEndpointTests(unittest.TestCase):
    """Verifies the FastAPI intake issue scoping route keeps working for the UI."""

    def setUp(self) -> None:
        """Creates a fresh API client and clears shared in-memory session state."""

        # Reset the in-memory session store so each endpoint test runs in isolation.
        SESSION_STORE.clear()

        # Create a clean FastAPI test client for the authenticated route checks.
        self.client = TestClient(app)

    def _sign_in(self) -> str:
        """Signs in an admin user and returns the bearer token for follow-up requests."""

        # Create a session that is allowed to access the intake routes.
        response = self.client.post(
            "/api/auth/sign-in",
            json={"name": "Test User", "email": "test@example.com", "role": "admin"},
        )

        # Ensure the test only continues when sign-in succeeded.
        self.assertEqual(response.status_code, 200)

        # Return the generated session token for authenticated requests.
        return response.json()["sessionToken"]

    def test_issue_scoping_endpoint_preserves_requested_issue_order(self) -> None:
        """Passes the requested issue subset to the classifier in the same UI order."""

        session_token = self._sign_in()
        issue_one = {
            "id": "issue-1",
            "ticket": "ACP-1",
            "title": "Add retry button to failed runs",
            "description": "Add a retry button on blocked runs and reuse the existing restart API.",
            "priority": "High",
            "status": "Todo",
            "provider": "jira",
        }
        issue_two = {
            "id": "issue-2",
            "ticket": "ACP-2",
            "title": "Investigate onboarding strategy",
            "description": "Explore several onboarding options and recommend the best approach.",
            "priority": "Medium",
            "status": "Todo",
            "provider": "linear",
        }
        intake_payload = {
            "repositories": [],
            "issues": [issue_one, issue_two],
            "documents": [],
            "currentUser": {"name": "Test User", "email": "test@example.com", "role": "admin", "provider": "guided"},
            "integrationStatuses": [],
        }
        scoping_payload = {
            "wellScopedIssueIds": ["issue-1"],
            "poorlyScopedIssueIds": ["issue-2"],
            "model": "gpt-4o-mini",
            "issueCount": 2,
        }

        with patch("app.main.get_intake_payload", return_value=intake_payload), patch(
            "app.main.classify_intake_issues_by_scope",
            return_value=scoping_payload,
        ) as mock_classify:
            # Call the route the intake form uses when it needs the categorized issue list.
            response = self.client.post(
                "/api/intake/issue-scoping",
                json={"issueIds": ["issue-2", "issue-1"]},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        # Confirm the route accepted the request and returned the classifier payload.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), scoping_payload)

        # Confirm the backend preserved the request order when filtering the issue subset.
        self.assertEqual(
            mock_classify.call_args.kwargs["issues"],
            [issue_two, issue_one],
        )


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
