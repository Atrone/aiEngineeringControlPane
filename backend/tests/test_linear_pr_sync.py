"""Regression coverage for syncing Linear issue state from GitHub PR events."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings
from app.providers import update_linear_issue_status


class LinearIssueStatusUpdateTests(unittest.TestCase):
    """Verifies the Linear provider can resolve and update workflow states safely."""

    def setUp(self) -> None:
        """Creates a settings object with a configured Linear API key."""

        # Start from the default settings and inject a fake Linear API key for provider tests.
        self.settings = replace(get_settings(), linear_api_key="lin_api_example")

    def test_update_linear_issue_status_prefers_exact_state_name_match(self) -> None:
        """Updates the issue using the exact team state whose name matches the requested status."""

        with patch(
            "app.providers._request_json",
            side_effect=[
                {
                    "data": {
                        "issue": {
                            "id": "issue-123",
                            "state": {"id": "state-todo", "name": "Todo", "type": "unstarted"},
                            "team": {
                                "id": "team-1",
                                "states": {
                                    "nodes": [
                                        {"id": "state-progress", "name": "In Progress", "type": "started"},
                                        {"id": "state-done", "name": "Done", "type": "completed"},
                                    ]
                                },
                            },
                        }
                    }
                },
                {
                    "data": {
                        "issueUpdate": {
                            "success": True,
                            "issue": {
                                "id": "issue-123",
                                "state": {"id": "state-progress", "name": "In Progress", "type": "started"},
                            },
                        }
                    }
                },
            ],
        ) as mock_request_json:
            # Update the issue into the exact team state that matches the requested display name.
            updated = update_linear_issue_status(self.settings, issue_id="issue-123", status_name="In Progress")

        # Confirm the provider reported a successful Linear mutation.
        self.assertTrue(updated)

        # Confirm the mutation targeted the state whose name exactly matched "In Progress".
        mutation_payload = mock_request_json.call_args_list[1].kwargs["payload"]
        self.assertEqual(mutation_payload["variables"]["stateId"], "state-progress")

    def test_update_linear_issue_status_falls_back_to_state_type_when_names_differ(self) -> None:
        """Updates the issue using the canonical Linear state type when team labels differ."""

        with patch(
            "app.providers._request_json",
            side_effect=[
                {
                    "data": {
                        "issue": {
                            "id": "issue-456",
                            "state": {"id": "state-todo", "name": "Todo", "type": "unstarted"},
                            "team": {
                                "id": "team-1",
                                "states": {
                                    "nodes": [
                                        {"id": "state-doing", "name": "Doing", "type": "started"},
                                        {"id": "state-shipped", "name": "Shipped", "type": "completed"},
                                    ]
                                },
                            },
                        }
                    }
                },
                {
                    "data": {
                        "issueUpdate": {
                            "success": True,
                            "issue": {
                                "id": "issue-456",
                                "state": {"id": "state-doing", "name": "Doing", "type": "started"},
                            },
                        }
                    }
                },
            ],
        ) as mock_request_json:
            # Request the public status name even though the team labels it as "Doing".
            updated = update_linear_issue_status(self.settings, issue_id="issue-456", status_name="In Progress")

        # Confirm the provider still succeeded by falling back to the "started" state type.
        self.assertTrue(updated)

        # Confirm the selected target state came from the workflow type fallback path.
        mutation_payload = mock_request_json.call_args_list[1].kwargs["payload"]
        self.assertEqual(mutation_payload["variables"]["stateId"], "state-doing")

    def test_update_linear_issue_status_skips_mutation_when_issue_is_already_in_target_state(self) -> None:
        """Avoids a redundant Linear mutation when the issue already matches the requested state."""

        with patch(
            "app.providers._request_json",
            return_value={
                "data": {
                    "issue": {
                        "id": "issue-789",
                        "state": {"id": "state-done", "name": "Done", "type": "completed"},
                        "team": {
                            "id": "team-1",
                            "states": {
                                "nodes": [
                                    {"id": "state-progress", "name": "In Progress", "type": "started"},
                                    {"id": "state-done", "name": "Done", "type": "completed"},
                                ]
                            },
                        },
                    }
                }
            },
        ) as mock_request_json:
            # Ask for the same state that the issue is already in.
            updated = update_linear_issue_status(self.settings, issue_id="issue-789", status_name="Done")

        # Confirm the provider treated the already-correct state as a success.
        self.assertTrue(updated)

        # Confirm only the catalog lookup ran because no mutation was needed.
        self.assertEqual(mock_request_json.call_count, 1)


class PullRequestLinearSyncTests(unittest.TestCase):
    """Verifies the run-state poller syncs Linear when GitHub PR state changes."""

    def setUp(self) -> None:
        """Preserves the shared run store and prepares a reusable settings snapshot."""

        # Snapshot the shared run store so these focused tests cannot leak state.
        self.original_run_store = deepcopy(state.RUN_STORE)

        # Start from the default settings for the PR sync tests.
        self.settings = get_settings()

    def tearDown(self) -> None:
        """Restores the shared run store after each PR sync test completes."""

        # Restore the original in-memory run state after each test.
        state.RUN_STORE = deepcopy(self.original_run_store)

    def test_sync_pull_request_status_marks_linear_issue_in_progress_when_pr_opens(self) -> None:
        """Updates Linear to In Progress when a real GitHub pull request is open."""

        run = {
            "id": "run-1",
            "ticket": "ACP-123",
            "repo": "platform-web",
            "status": "Running",
            "currentStep": "Cursor Cloud Agent status: RUNNING",
            "blockers": [],
            "approvalHistory": [],
            "_cursorAgent": {
                "target": {
                    "prUrl": "https://github.com/acme/platform-web/pull/42",
                }
            },
            "_issueSnapshot": {
                "id": "issue-123",
                "provider": "linear",
            },
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={"source": "github", "state": "open", "merged": False, "approved": False},
        ), patch("app.state.update_linear_issue_status", return_value=True) as mock_update_linear_issue_status:
            # Poll the PR state while the run is still executing and the PR is already open.
            pr_state = state._sync_pull_request_status(run, self.settings)

        # Confirm the run kept the live GitHub PR state instead of falling back to draft.
        self.assertEqual(pr_state["state"], "open")
        self.assertEqual(run["_pullRequestState"]["state"], "open")

        # Confirm the run stayed in the Running state while Linear was moved to In Progress.
        self.assertEqual(run["status"], "Running")
        self.assertEqual(run["_linearSyncedStatusName"], "In Progress")
        mock_update_linear_issue_status.assert_called_once_with(
            self.settings,
            issue_id="issue-123",
            status_name="In Progress",
        )

    def test_sync_pull_request_status_marks_linear_issue_done_when_pr_merges(self) -> None:
        """Updates Linear to Done when GitHub reports the pull request as merged."""

        run = {
            "id": "run-2",
            "ticket": "ACP-456",
            "repo": "platform-web",
            "status": "Approved",
            "currentStep": "Pull request approved - awaiting merge",
            "blockers": ["Awaiting pull-request merge on GitHub"],
            "approvalHistory": [],
            "_issueSnapshot": {
                "id": "issue-456",
                "provider": "linear",
            },
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={
                "source": "github",
                "state": "merged",
                "merged": True,
                "mergedAt": "2026-04-17T12:34:56+00:00",
                "approved": True,
                "approvedAt": "2026-04-17T12:00:00+00:00",
                "approvedBy": "reviewer-user",
            },
        ), patch("app.state.update_linear_issue_status", return_value=True) as mock_update_linear_issue_status:
            # Poll the PR state after approval so the merge transition can complete.
            pr_state = state._sync_pull_request_status(run, self.settings)

        # Confirm the merged PR advanced the run into the terminal merged state.
        self.assertEqual(pr_state["state"], "merged")
        self.assertEqual(run["status"], "Merged")
        self.assertEqual(run["currentStep"], "Pull request merged")

        # Confirm the Linear issue was promoted into Done exactly once for the merge event.
        self.assertEqual(run["_linearSyncedStatusName"], "Done")
        mock_update_linear_issue_status.assert_called_once_with(
            self.settings,
            issue_id="issue-456",
            status_name="Done",
        )

    def test_sync_pull_request_status_skips_duplicate_linear_updates_for_the_same_pr_state(self) -> None:
        """Avoids repeating the same Linear status sync on subsequent dashboard polls."""

        run = {
            "id": "run-3",
            "ticket": "ACP-789",
            "repo": "platform-web",
            "status": "Running",
            "currentStep": "Cursor Cloud Agent status: RUNNING",
            "blockers": [],
            "approvalHistory": [],
            "_cursorAgent": {
                "target": {
                    "prUrl": "https://github.com/acme/platform-web/pull/77",
                }
            },
            "_issueSnapshot": {
                "id": "issue-789",
                "provider": "linear",
            },
            "_linearSyncedStatusName": "In Progress",
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={"source": "github", "state": "open", "merged": False, "approved": False},
        ), patch("app.state.update_linear_issue_status", return_value=True) as mock_update_linear_issue_status:
            # Poll the same open PR state again after it was already synced once.
            state._sync_pull_request_status(run, self.settings)

        # Confirm the cached sync marker prevented a redundant Linear mutation.
        mock_update_linear_issue_status.assert_not_called()


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
