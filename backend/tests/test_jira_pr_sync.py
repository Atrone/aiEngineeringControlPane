"""Regression coverage for syncing Jira issue state from GitHub PR events."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings
from app.providers import update_jira_issue_status


class JiraIssueStatusUpdateTests(unittest.TestCase):
    """Verifies the Jira provider can resolve and update workflow states safely."""

    def setUp(self) -> None:
        """Creates a settings object with configured Jira Cloud credentials."""

        # Start from the default settings and inject fake Jira Cloud credentials for provider tests.
        self.settings = replace(
            get_settings(),
            jira_site_url="https://acme.atlassian.net",
            jira_email="owner@example.com",
            jira_api_token="jira_api_token",
        )

    def test_update_jira_issue_status_prefers_exact_status_name_match(self) -> None:
        """Updates the issue using the exact Jira transition whose status name matches the request."""

        with patch(
            "app.provider_jira._request_json",
            side_effect=[
                {
                    "fields": {
                        "status": {
                            "name": "To Do",
                            "statusCategory": {"name": "To Do"},
                        }
                    }
                },
                {
                    "transitions": [
                        {
                            "id": "21",
                            "name": "In Progress",
                            "to": {
                                "name": "In Progress",
                                "statusCategory": {"name": "In Progress"},
                            },
                        },
                        {
                            "id": "31",
                            "name": "Done",
                            "to": {
                                "name": "Done",
                                "statusCategory": {"name": "Done"},
                            },
                        },
                    ]
                },
            ],
        ), patch("app.provider_jira._request_jira_transition_update", return_value=True) as mock_transition_update:
            # Update the issue into the exact Jira status whose name matches the request.
            updated = update_jira_issue_status(self.settings, issue_id="10001", status_name="In Progress")

        # Confirm the provider reported a successful Jira transition.
        self.assertTrue(updated)

        # Confirm the transition targeted the exact Jira transition match.
        mock_transition_update.assert_called_once_with(
            self.settings,
            issue_id="10001",
            transition_id="21",
        )

    def test_update_jira_issue_status_falls_back_to_status_category_when_names_differ(self) -> None:
        """Updates the issue using the Jira status category when project labels differ."""

        with patch(
            "app.provider_jira._request_json",
            side_effect=[
                {
                    "fields": {
                        "status": {
                            "name": "Backlog",
                            "statusCategory": {"name": "To Do"},
                        }
                    }
                },
                {
                    "transitions": [
                        {
                            "id": "41",
                            "name": "Start work",
                            "to": {
                                "name": "Doing",
                                "statusCategory": {"name": "In Progress"},
                            },
                        },
                        {
                            "id": "51",
                            "name": "Ship it",
                            "to": {
                                "name": "Released",
                                "statusCategory": {"name": "Done"},
                            },
                        },
                    ]
                },
            ],
        ), patch("app.provider_jira._request_jira_transition_update", return_value=True) as mock_transition_update:
            # Request the public status name even though the Jira workflow labels it differently.
            updated = update_jira_issue_status(self.settings, issue_id="10002", status_name="In Progress")

        # Confirm the provider still succeeded by falling back to the Jira status category.
        self.assertTrue(updated)

        # Confirm the selected target transition came from the status-category fallback path.
        mock_transition_update.assert_called_once_with(
            self.settings,
            issue_id="10002",
            transition_id="41",
        )

    def test_update_jira_issue_status_skips_mutation_when_issue_is_already_in_target_status(self) -> None:
        """Avoids a redundant Jira transition when the issue already matches the requested status."""

        with patch(
            "app.provider_jira._request_json",
            return_value={
                "fields": {
                    "status": {
                        "name": "Done",
                        "statusCategory": {"name": "Done"},
                    }
                }
            },
        ) as mock_request_json, patch("app.provider_jira._request_jira_transition_update") as mock_transition_update:
            # Ask for the same Jira status that the issue is already in.
            updated = update_jira_issue_status(self.settings, issue_id="10003", status_name="Done")

        # Confirm the provider treated the already-correct status as a success.
        self.assertTrue(updated)

        # Confirm only the current-status lookup ran because no transition was needed.
        self.assertEqual(mock_request_json.call_count, 1)
        mock_transition_update.assert_not_called()


class PullRequestJiraSyncTests(unittest.TestCase):
    """Verifies the run-state poller syncs Jira when GitHub PR state changes."""

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

    def test_sync_pull_request_status_marks_jira_issue_in_progress_when_pr_opens(self) -> None:
        """Updates Jira to In Progress when a real GitHub pull request is open."""

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
                "id": "10001",
                "provider": "jira",
            },
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={"source": "github", "state": "open", "merged": False, "approved": False},
        ), patch("app.state.update_jira_issue_status", return_value=True) as mock_update_jira_issue_status:
            # Poll the PR state while the run is still executing and the PR is already open.
            pr_state = state._sync_pull_request_status(run, self.settings)

        # Confirm the run kept the live GitHub PR state instead of falling back to draft.
        self.assertEqual(pr_state["state"], "open")
        self.assertEqual(run["_pullRequestState"]["state"], "open")

        # Confirm the run stayed in the Running state while Jira was moved to In Progress.
        self.assertEqual(run["status"], "Running")
        self.assertEqual(run["_jiraSyncedStatusName"], "In Progress")
        mock_update_jira_issue_status.assert_called_once_with(
            self.settings,
            issue_id="10001",
            status_name="In Progress",
        )

    def test_sync_pull_request_status_marks_jira_issue_done_when_pr_merges(self) -> None:
        """Updates Jira to Done when GitHub reports the pull request as merged."""

        run = {
            "id": "run-2",
            "ticket": "ACP-456",
            "repo": "platform-web",
            "status": "Approved",
            "currentStep": "Pull request approved - awaiting merge",
            "blockers": ["Awaiting pull-request merge on GitHub"],
            "approvalHistory": [],
            "_issueSnapshot": {
                "id": "10002",
                "provider": "jira",
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
        ), patch("app.state.update_jira_issue_status", return_value=True) as mock_update_jira_issue_status:
            # Poll the PR state after approval so the merge transition can complete.
            pr_state = state._sync_pull_request_status(run, self.settings)

        # Confirm the merged PR advanced the run into the terminal merged state.
        self.assertEqual(pr_state["state"], "merged")
        self.assertEqual(run["status"], "Merged")
        self.assertEqual(run["currentStep"], "Pull request merged")

        # Confirm the Jira issue was promoted into Done exactly once for the merge event.
        self.assertEqual(run["_jiraSyncedStatusName"], "Done")
        mock_update_jira_issue_status.assert_called_once_with(
            self.settings,
            issue_id="10002",
            status_name="Done",
        )

    def test_sync_pull_request_status_skips_duplicate_jira_updates_for_the_same_pr_state(self) -> None:
        """Avoids repeating the same Jira status sync on subsequent dashboard polls."""

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
                "id": "10003",
                "provider": "jira",
            },
            "_jiraSyncedStatusName": "In Progress",
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={"source": "github", "state": "open", "merged": False, "approved": False},
        ), patch("app.state.update_jira_issue_status", return_value=True) as mock_update_jira_issue_status:
            # Poll the same open PR state again after it was already synced once.
            state._sync_pull_request_status(run, self.settings)

        # Confirm the cached sync marker prevented a redundant Jira transition.
        mock_update_jira_issue_status.assert_not_called()

    def test_cursor_progress_preserves_pr_target_when_status_payload_omits_target(self) -> None:
        """Keeps the previously known PR URL when Cursor status polling omits target metadata."""

        run = {
            "id": "run-cursor",
            "ticket": "ACP-101",
            "title": "Cursor task",
            "repo": "platform-web",
            "branch": "ai/acp-101-cursor-task",
            "status": "Running",
            "runtime": "00:00",
            "currentStep": "Cursor Cloud Agent status: RUNNING",
            "blockers": [],
            "_cursorAgent": {
                "id": "agent-1",
                "status": "RUNNING",
                "createdAt": "2026-04-17T12:00:00+00:00",
                "target": {
                    "branchName": "ai/acp-101-cursor-task",
                    "prUrl": "https://github.com/acme/platform-web/pull/42",
                },
            },
        }

        with patch(
            "app.state.get_cursor_agent",
            return_value={
                "id": "agent-1",
                "status": "FINISHED",
                "createdAt": "2026-04-17T12:00:00+00:00",
                "summary": "The PR is ready for review.",
            },
        ):
            # Poll a completion payload that does not repeat the target object.
            state._sync_run_progress(run, self.settings)

        # Confirm the run moved into review without losing the PR link used by detail and lobby views.
        self.assertEqual(run["status"], "Review")
        self.assertEqual(
            run["_cursorAgent"]["target"]["prUrl"],
            "https://github.com/acme/platform-web/pull/42",
        )
        self.assertEqual(
            state._resolve_pull_request_url(run, settings=self.settings),
            "https://github.com/acme/platform-web/pull/42",
        )

    def test_pull_request_url_resolution_tolerates_null_cloud_agent_target(self) -> None:
        """Falls back to a deterministic PR URL when provider target metadata is null."""

        run = {
            "id": "run-null-target",
            "ticket": "ACP-102",
            "repo": "platform-web",
            "_cursorAgent": {
                "id": "agent-2",
                "target": None,
            },
        }

        # Resolve the PR URL from a malformed provider target without raising an exception.
        pull_request_url = state._resolve_pull_request_url(run, settings=self.settings)

        # Confirm the fallback URL still points at the run's connected repository context.
        self.assertIn("/platform-web/pull/acp-102", pull_request_url)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
