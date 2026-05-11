"""Regression coverage for the dashboard summary payload."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class DashboardPayloadTests(unittest.TestCase):
    """Verifies the dashboard metrics and side panels are derived from live app state."""

    def setUp(self) -> None:
        """Preserves the shared run store so each dashboard test runs in isolation."""

        # Snapshot the shared in-memory run store before a test mutates or reads it.
        self.original_run_store = deepcopy(state.RUN_STORE)

    def tearDown(self) -> None:
        """Restores the shared run store after each dashboard test completes."""

        # Restore the original in-memory run state so other tests see the seeded fixtures.
        state.RUN_STORE = deepcopy(self.original_run_store)

    def test_dashboard_payload_uses_dynamic_metric_and_summary_text(self) -> None:
        """Builds dashboard metrics, blocker reasons, and suggestions from current state."""

        integration_catalog = {
            "repositories": [
                {
                    "id": "platform-web",
                    "name": "platform-web",
                    "fullName": "acme/platform-web",
                    "defaultBranch": "main",
                    "private": False,
                    "provider": "github",
                    "url": "https://github.com/acme/platform-web",
                },
                {
                    "id": "api-service",
                    "name": "api-service",
                    "fullName": "acme/api-service",
                    "defaultBranch": "main",
                    "private": False,
                    "provider": "github",
                    "url": "https://github.com/acme/api-service",
                },
            ],
            "issues": [],
            "documents": [],
            "currentUser": {
                "name": "Test User",
                "email": "test@example.com",
                "role": "admin",
                "provider": "configured_default",
            },
            "statuses": [
                {"id": "github", "connected": True},
                {"id": "linear", "connected": True},
                {"id": "cursor_cloud_agents", "connected": False},
                {"id": "repo_docs", "connected": True},
            ],
        }

        with patch("app.state.get_integration_catalog", return_value=integration_catalog):
            # Build the dashboard payload using a fixed integration snapshot.
            payload = state.get_dashboard_payload(get_settings(), {})

        metrics_by_label = {metric["label"]: metric for metric in payload["metrics"]}

        # Confirm the active-runs card reflects the current run-state counts.
        self.assertEqual(metrics_by_label["Active runs"]["value"], "4")
        self.assertEqual(metrics_by_label["Active runs"]["hint"], "0 running, 2 waiting for review")

        # Confirm the blocked-tasks card summarizes actionable blocker reasons instead of static copy.
        self.assertEqual(metrics_by_label["Blocked tasks"]["value"], "1")
        self.assertEqual(metrics_by_label["Blocked tasks"]["hint"], "3 unique blocker reasons need follow-up")

        # Confirm the merged-today card uses current run-state data instead of a fixture string.
        self.assertEqual(metrics_by_label["Merged today"]["value"], "1")
        self.assertEqual(
            metrics_by_label["Merged today"]["hint"],
            "1 run reached the merged state in the current session",
        )

        # Confirm the review-effort card is derived from the summed lobby runtimes.
        self.assertEqual(metrics_by_label["Review effort"]["value"], "59 min")
        self.assertEqual(
            metrics_by_label["Review effort"]["hint"],
            "Total runtime across 5 runs in this lobby",
        )

        # Confirm the blocked-reasons panel is built from the current blocked and retry runs.
        self.assertEqual(
            payload["blockedReasons"],
            [
                "Missing test environment secret (1 run)",
                "High-risk auth flow requires approval before merge (1 run)",
                "Flaky CI environment (1 run)",
            ],
        )

        # Confirm the suggested-actions panel is derived from current run and integration state.
        self.assertEqual(
            payload["suggestedActions"],
            [
                "Review 2 runs waiting in the approval inbox.",
                "Unblock 2 stalled runs. Top blocker: Missing test environment secret.",
                "Connect Cursor Cloud Agents so runs launch against the live agent service.",
            ],
        )

    def test_dashboard_runs_expose_delegation_fields_for_task_detail(self) -> None:
        """Ensures SIG-16 delegation context is present on enriched run payloads."""

        integration_catalog = {
            "repositories": [
                {
                    "id": "web-app",
                    "name": "web-app",
                    "fullName": "acme/web-app",
                    "defaultBranch": "main",
                    "private": False,
                    "provider": "github",
                    "url": "https://github.com/acme/web-app",
                },
            ],
            "issues": [],
            "documents": [],
            "currentUser": {
                "name": "Test User",
                "email": "test@example.com",
                "role": "admin",
                "provider": "configured_default",
            },
            "statuses": [],
        }

        with patch("app.state.get_integration_catalog", return_value=integration_catalog):
            # Build the dashboard payload so the first lobby run can be inspected for delegation keys.
            payload = state.get_dashboard_payload(get_settings(), {})

        first_run = payload["runs"][0]

        # Confirm the public API exposes intake-backed fields for the control pane task detail view.
        self.assertIn("acceptanceCriteria", first_run)
        self.assertIn("taskPrompt", first_run)
        self.assertIn("executionMode", first_run)
        self.assertIn("repositoryContext", first_run)
        # Confirm the seeded fixture still carries checklist text for reviewers.
        self.assertIn("Settings UI lists model routing", first_run["acceptanceCriteria"])
        # Confirm repository metadata resolves from the catalog using the run's repo short name.
        self.assertEqual(first_run["repositoryContext"]["fullName"], "acme/web-app")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
