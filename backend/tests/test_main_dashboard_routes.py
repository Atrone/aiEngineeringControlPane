"""Route coverage for dashboard, approvals, policy, user, and integrations endpoints."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.providers import OpenAIEnrichmentError
from app.schemas import DashboardSuggestedActionsRequest


class MainDashboardRouteTests(unittest.TestCase):
    """Verifies dashboard-adjacent route wrappers in main.py."""

    def test_dashboard_and_suggested_actions_routes_delegate_correctly(self) -> None:
        """Covers dashboard fetch, run-detail fetch, and suggested-actions behavior."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_dashboard_payload",
            return_value={"metrics": [], "runs": []},
        ) as mock_get_dashboard_payload:
            # Confirm the dashboard route passes the authorized settings and headers through.
            dashboard_payload = main.get_dashboard(request)
            self.assertEqual(dashboard_payload["runs"], [])
            mock_get_dashboard_payload.assert_called_once_with("settings", {"x": "y"})

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_runs_by_ids",
            return_value=[{"id": "run-1"}],
        ), patch(
            "app.main.suggest_next_actions_for_runs",
            return_value={"suggestedActions": ["Review the blocked run."]},
        ) as mock_suggest:
            # Confirm the suggested-actions route resolves visible runs before calling OpenAI.
            payload = DashboardSuggestedActionsRequest.model_validate({"runIds": ["run-1"]})
            response = main.post_dashboard_suggested_actions(payload, request)
            self.assertEqual(response["suggestedActions"], ["Review the blocked run."])
            mock_suggest.assert_called_once_with("settings", runs=[{"id": "run-1"}])

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_runs_by_ids",
            return_value=[{"id": "run-1"}],
        ), patch(
            "app.main.suggest_next_actions_for_runs",
            side_effect=OpenAIEnrichmentError("provider-failed"),
        ):
            # Confirm OpenAI failures are translated into route-facing HTTP exceptions.
            with self.assertRaises(HTTPException) as suggestion_error:
                main.post_dashboard_suggested_actions(
                    DashboardSuggestedActionsRequest.model_validate({"runIds": ["run-1"]}),
                    request,
                )
            self.assertEqual(suggestion_error.exception.status_code, 502)

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_run_detail",
            return_value={"id": "run-1"},
        ):
            # Confirm run detail returns the state-layer payload when the run exists.
            self.assertEqual(main.read_run_detail("run-1", request)["id"], "run-1")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_run_detail",
            side_effect=KeyError("missing"),
        ):
            # Confirm missing runs become 404 responses.
            with self.assertRaises(HTTPException) as run_error:
                main.read_run_detail("missing", request)
            self.assertEqual(run_error.exception.status_code, 404)

    def test_approval_policy_user_and_integrations_routes_delegate_correctly(self) -> None:
        """Covers approval, policy, current-user, and integrations route wrappers."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        session = SimpleNamespace(name="User", email="user@example.com", role="admin", provider="guided_sign_in")

        with patch("app.main._authorized_request_with_roles", return_value=("settings", {"x": "y"}, session)), patch(
            "app.main.get_approval_payload",
            return_value={"summary": {"queueSize": 1}},
        ) as mock_get_approval_payload:
            # Confirm the approvals route requires admin authorization and forwards the request context.
            approvals_payload = main.get_approvals(request)
            self.assertEqual(approvals_payload["summary"]["queueSize"], 1)
            mock_get_approval_payload.assert_called_once_with("settings", {"x": "y"})

        with patch("app.main._authorized_request_with_roles") as mock_authorized_request_with_roles, patch(
            "app.main.get_policy_payload",
            return_value={"scope": "web-app"},
        ) as mock_get_policy_payload:
            # Confirm the policies route enforces admin access and returns the policy payload.
            policy_payload = main.get_policies(request, scope="web-app")
            self.assertEqual(policy_payload["scope"], "web-app")
            mock_authorized_request_with_roles.assert_called_once_with(request, ("admin",))
            mock_get_policy_payload.assert_called_once_with("web-app")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, session)), patch(
            "app.main.build_current_user",
            return_value={"email": "user@example.com"},
        ) as mock_build_current_user:
            # Confirm the current-user route exposes the auth-layer user payload.
            me_payload = main.get_current_user(request)
            self.assertEqual(me_payload["email"], "user@example.com")
            mock_build_current_user.assert_called_once_with(session)

        with patch("app.main._authorized_request_with_roles", return_value=("settings", {"x": "y"}, session)), patch(
            "app.main.get_integrations_payload",
            return_value={"statuses": []},
        ) as mock_get_integrations_payload:
            # Confirm the integrations route uses the admin-gated request context.
            integrations_payload = main.get_integrations(request)
            self.assertEqual(integrations_payload["statuses"], [])
            mock_get_integrations_payload.assert_called_once_with("settings", {"x": "y"})


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
