"""Unit coverage for integration-catalog and dashboard payload helpers in state.py."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class StateIntegrationPayloadTests(unittest.TestCase):
    """Verifies integration-catalog, dashboard, and summary helpers in state.py."""

    def setUp(self) -> None:
        """Preserves the shared run store before each test mutates it."""

        # Snapshot the shared in-memory run store so tests stay isolated.
        self.original_run_store = deepcopy(state.RUN_STORE)

    def tearDown(self) -> None:
        """Restores the shared run store after each test finishes."""

        # Restore the original in-memory run state for later tests.
        state.RUN_STORE = deepcopy(self.original_run_store)

    def test_fallback_catalog_and_blocker_helpers_cover_expected_behavior(self) -> None:
        """Covers fallback catalogs, blocker logic, and dashboard summary helpers."""

        settings = get_settings()

        # Confirm fallback issue and repo catalogs are derived from the seeded run store.
        fallback_issues = state._fallback_issues()
        fallback_repositories = state._fallback_repositories()
        self.assertGreaterEqual(len(fallback_issues), 1)
        self.assertGreaterEqual(len(fallback_repositories), 1)

        with patch("app.state.list_repo_documents", return_value=[{"id": "doc-1"}]):
            # Confirm fallback documents prefer real markdown docs when available.
            self.assertEqual(state._fallback_documents(settings), [{"id": "doc-1"}])

        with patch("app.state.list_linear_issues", return_value=[{"id": "linear-1"}]), patch(
            "app.state.list_jira_issues",
            return_value=[{"id": "jira-1"}],
        ):
            # Confirm connected issues concatenate the Linear and Jira catalogs.
            self.assertEqual(
                state._list_connected_issues(settings),
                [{"id": "linear-1"}, {"id": "jira-1"}],
            )

        # Confirm blocker filtering hides passive statuses and keeps actionable blockers.
        self.assertFalse(state._is_actionable_blocker("No active blockers"))
        self.assertTrue(state._is_actionable_blocker("Missing secret"))

        # Confirm blocker counts and derived blocked reasons are built from blocked/retry runs only.
        blocker_counts = state._collect_blocker_counts()
        blocked_reasons = state._build_dashboard_blocked_reasons()
        self.assertGreaterEqual(len(blocker_counts), 1)
        self.assertGreaterEqual(len(blocked_reasons), 1)

        # Confirm review-effort formatting covers empty and non-empty lobby run sets.
        self.assertEqual(state._build_review_effort_value(0, 0), "0 min")
        self.assertEqual(state._build_review_effort_value(2, 720), "12 min")

        # Confirm dashboard metrics expose the expected summary cards.
        metrics = state._compute_metrics()
        self.assertEqual(metrics[0]["label"], "Active runs")

        statuses = [{"id": "linear", "connected": True}, {"id": "github", "connected": False}]

        # Confirm the integration-status helper finds matching provider entries.
        self.assertEqual(state._find_integration_status(statuses, "linear")["id"], "linear")
        self.assertIsNone(state._find_integration_status(statuses, "missing"))

        # Confirm dashboard suggestions respond to review load and missing integrations.
        suggested_actions = state._build_dashboard_suggested_actions(
            repository_names=["platform-web"],
            integration_statuses=[
                {"id": "linear", "connected": False},
                {"id": "jira", "connected": False},
                {"id": "github", "connected": False},
                {"id": "cursor_cloud_agents", "connected": False},
                {"id": "repo_docs", "connected": False},
            ],
        )
        self.assertGreaterEqual(len(suggested_actions), 1)

    def test_catalog_and_payload_builders_cover_public_state_read_helpers(self) -> None:
        """Covers integration catalog plus dashboard, detail, intake, and approvals payloads."""

        settings = get_settings()
        integration_catalog = {
            "repositories": [{"id": "platform-web", "name": "platform-web"}],
            "issues": [{"id": "issue-1"}],
            "documents": [{"id": "doc-1"}],
            "currentUser": {"email": "user@example.com"},
            "statuses": [{"id": "github", "connected": True}],
        }

        with patch("app.state.list_github_repositories", return_value=[]), patch(
            "app.state._list_connected_issues",
            return_value=[],
        ), patch(
            "app.state.list_repo_documents",
            return_value=[],
        ), patch(
            "app.state._fallback_documents",
            return_value=[{"id": "doc-1"}],
        ), patch(
            "app.state.resolve_current_user",
            return_value={"email": "user@example.com"},
        ), patch(
            "app.state.get_integration_statuses",
            return_value=[{"id": "github", "connected": True}],
        ):
            # Confirm the integration catalog falls back when live sources are empty.
            catalog = state.get_integration_catalog(settings, {})
            self.assertIn("repositories", catalog)
            self.assertIn("statuses", catalog)

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state._sync_run_progress"
        ), patch(
            "app.state._build_run_extensions",
            side_effect=lambda run, **kwargs: {"id": run["id"], "requestedBy": kwargs["current_user"]},
        ):
            # Confirm the dashboard payload exposes metrics, runs, blocker reasons, and integration status.
            dashboard_payload = state.get_dashboard_payload(settings, {})
            self.assertIn("metrics", dashboard_payload)
            self.assertIn("integrationStatuses", dashboard_payload)

            # Confirm run detail returns the matching enriched run payload.
            run_detail = state.get_run_detail(state.RUN_STORE[0]["id"], settings, {})
            self.assertEqual(run_detail["id"], state.RUN_STORE[0]["id"])

            # Confirm ordered run lookup preserves input order and skips unknown IDs.
            ordered_runs = state.get_runs_by_ids(
                [state.RUN_STORE[1]["id"], "missing", state.RUN_STORE[0]["id"]],
                settings,
                {},
            )
            self.assertEqual(
                [run["id"] for run in ordered_runs],
                [state.RUN_STORE[1]["id"], state.RUN_STORE[0]["id"]],
            )

            # Confirm the approval payload includes queue summary and current-user context.
            approval_payload = state.get_approval_payload(settings, {})
            self.assertIn("summary", approval_payload)
            self.assertIn("currentUser", approval_payload)

            # Confirm policy, intake, and integrations payload builders expose their public shapes.
            self.assertEqual(state.get_policy_payload("web-app")["scope"], "web-app")
            self.assertIn("repositories", state.get_intake_payload(settings, {}))
            self.assertIn("statuses", state.get_integrations_payload(settings, {}))

        # Confirm unknown run details still raise a key error for the API layer to translate.
        with self.assertRaises(KeyError):
            state.get_run_detail("missing-run", settings, {})


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
