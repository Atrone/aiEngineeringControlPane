"""Additional coverage for state.py helper and state-machine branches."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import state
from app.config import get_settings


class StateGapCoverageTests(unittest.TestCase):
    """Verifies the remaining uncovered state.py branches."""

    def setUp(self) -> None:
        """Snapshots the mutable run store before each test case."""

        # Preserve the in-memory run list so each test can mutate it safely.
        self.original_run_store = deepcopy(state.RUN_STORE)

    def tearDown(self) -> None:
        """Restores the mutable run store after each test case."""

        # Put the global run store back so later tests start from the seeded data.
        state.RUN_STORE[:] = deepcopy(self.original_run_store)

    def test_small_helpers_cover_fallback_and_empty_result_paths(self) -> None:
        """Covers small helper branches around fallbacks, empty inputs, and skipped records."""

        # Confirm malformed numeric runtime fragments safely collapse to zero seconds.
        self.assertEqual(state._parse_runtime_seconds("aa:bb"), 0)

        with patch("app.state._utc_timestamp", return_value="2026-04-24T12:00:00+00:00"), patch(
            "app.state._build_static_timeline",
            return_value=[],
        ), patch(
            "app.state._build_static_logs",
            return_value=[],
        ), patch(
            "app.state._build_evidence_entries",
            return_value=[],
        ):
            # Confirm approved static runs receive the approved-awaiting-merge status label.
            static_live_view = state._build_static_live_view({"status": "Approved", "runtime": "00:10", "evidence": {}})
        self.assertEqual(static_live_view["statusLabel"], "Approved - awaiting PR merge")

        with patch("app.state.list_repo_documents", return_value=[]):
            # Confirm the docs fallback returns an empty list when no repo docs exist.
            self.assertEqual(state._fallback_documents(get_settings()), [])

        # Confirm issue lookup returns no record when the selected issue ID is absent.
        self.assertIsNone(state._find_issue([{"id": "issue-1"}], "missing-issue"))

        # Confirm malformed uploaded documents are skipped during normalization.
        self.assertEqual(
            state._normalize_uploaded_documents(
                [
                    {"id": "doc-1", "path": "docs/guide.md", "title": "Guide"},
                    {"id": "", "path": "docs/bad.md", "title": "Bad"},
                ]
            ),
            [
                {
                    "id": "doc-1",
                    "title": "Guide",
                    "path": "docs/guide.md",
                    "source": "uploaded_repo_document",
                    "updatedAt": "",
                }
            ],
        )

        # Confirm invalid uploads can be skipped while later valid uploads still normalize correctly.
        self.assertEqual(
            state._normalize_uploaded_documents(
                [
                    {"id": "", "path": "", "title": ""},
                    {"id": "doc-2", "path": "docs/reference.md", "title": "Reference"},
                ]
            ),
            [
                {
                    "id": "doc-2",
                    "title": "Reference",
                    "path": "docs/reference.md",
                    "source": "uploaded_repo_document",
                    "updatedAt": "",
                }
            ],
        )

        # Confirm closed PR states render with the public closed badge.
        closed_pull_request = state._build_pull_request_view(
            {"status": "Blocked", "repo": "platform-web", "ticket": "ACP-1"},
            {"state": "closed", "merged": False, "approved": False, "source": "github"},
        )
        self.assertEqual(closed_pull_request["status"], "closed")

        with patch("app.state._build_live_view", return_value={"isLive": False}):
            # Confirm run extension building falls back to the cached skipped PR state when settings are absent.
            run_extensions = state._build_run_extensions(
                {
                    "id": "run-1",
                    "ticket": "ACP-1",
                    "title": "Task title",
                    "repo": "platform-web",
                    "owner": "Maya Chen",
                    "agent": "impl-agent",
                    "runtime": "00:00",
                    "cost": "$0.00",
                    "status": "Blocked",
                    "risk": "Medium",
                    "currentStep": "Waiting",
                    "summary": "Task summary",
                    "blockers": ["Needs input"],
                    "approvalHistory": [],
                }
            )
        self.assertEqual(run_extensions["pullRequest"]["source"], "skipped")
        self.assertEqual(run_extensions["issueTraceability"]["provider"], "fallback")

        # Confirm blank blockers are ignored in dashboard blocker summaries.
        self.assertFalse(state._is_actionable_blocker("   "))

        with patch("app.state._collect_blocker_counts", return_value={}):
            # Confirm dashboard blocker summaries expose a stable empty state message.
            self.assertEqual(
                state._build_dashboard_blocked_reasons(),
                ["No actionable blocker reasons are currently reported."],
            )

        # Confirm run lookup returns an empty list when the caller passes no IDs.
        self.assertEqual(state.get_runs_by_ids([], get_settings(), {}), [])

    def test_dashboard_helpers_cover_blocker_fallbacks_metric_counts_and_suggestion_edges(self) -> None:
        """Covers dashboard blocker counting, metric hints, and suggestion fallbacks."""

        state.RUN_STORE[:] = [
            {
                "id": "run-retry",
                "status": "Retry",
                "runtime": "00:30",
                "blockers": ["No active blockers"],
                "currentStep": "Awaiting QA environment",
            },
            {
                "id": "run-running",
                "status": "Running",
                "runtime": "01:00",
                "blockers": ["Streaming execution in progress"],
                "currentStep": "Executing plan",
            },
            {
                "id": "run-approved",
                "status": "Approved",
                "runtime": "02:00",
                "blockers": ["Awaiting pull-request merge on GitHub"],
                "currentStep": "Waiting on merge",
            },
        ]

        # Confirm blocker counting falls back to currentStep when explicit blockers are non-actionable.
        blocker_counts = state._collect_blocker_counts()
        self.assertEqual(blocker_counts, {"Awaiting QA environment": 1})

        metrics = state._compute_metrics()
        active_runs_metric = next(metric for metric in metrics if metric["label"] == "Active runs")

        # Confirm metric hints include the running and approved-awaiting-merge summaries.
        self.assertIn("1 running", active_runs_metric["hint"])
        self.assertIn("1 approved awaiting merge", active_runs_metric["hint"])

        with patch.object(state, "RUN_STORE", []):
            # Confirm disconnected Cursor surfaces the live-agent setup suggestion.
            self.assertEqual(
                state._build_dashboard_suggested_actions(
                    repository_names=[],
                    integration_statuses=[
                        {"id": "linear", "connected": True},
                        {"id": "github", "connected": True},
                        {"id": "cursor_cloud_agents", "connected": False},
                        {"id": "repo_docs", "connected": True},
                    ],
                ),
                ["Connect Cursor Cloud Agents so runs launch against the live agent service."],
            )

            # Confirm disconnected GitHub surfaces the repository-launch suggestion.
            self.assertEqual(
                state._build_dashboard_suggested_actions(
                    repository_names=[],
                    integration_statuses=[
                        {"id": "linear", "connected": True},
                        {"id": "github", "connected": False},
                        {"id": "cursor_cloud_agents", "connected": True},
                        {"id": "repo_docs", "connected": True},
                    ],
                ),
                ["Connect GitHub so new runs can target real repositories."],
            )

            # Confirm disconnected repo docs surfaces the repo-docs grounding suggestion.
            self.assertEqual(
                state._build_dashboard_suggested_actions(
                    repository_names=[],
                    integration_statuses=[
                        {"id": "linear", "connected": True},
                        {"id": "github", "connected": True},
                        {"id": "cursor_cloud_agents", "connected": True},
                        {"id": "repo_docs", "connected": False},
                    ],
                ),
                ["Connect repo docs so new tasks attach real markdown context."],
            )

            # Confirm fully connected repos still produce a launch-new-work suggestion.
            self.assertEqual(
                state._build_dashboard_suggested_actions(
                    repository_names=["platform-web"],
                    integration_statuses=[
                        {"id": "linear", "connected": True},
                        {"id": "github", "connected": True},
                        {"id": "cursor_cloud_agents", "connected": True},
                        {"id": "repo_docs", "connected": True},
                    ],
                ),
                ["Launch new work against 1 available repos in the intake flow."],
            )

            # Confirm the dashboard returns a stable empty state when nothing needs follow-up.
            self.assertEqual(
                state._build_dashboard_suggested_actions(
                    repository_names=[],
                    integration_statuses=[
                        {"id": "linear", "connected": True},
                        {"id": "github", "connected": True},
                        {"id": "cursor_cloud_agents", "connected": True},
                        {"id": "repo_docs", "connected": True},
                    ],
                ),
                ["No immediate follow-up actions are suggested."],
            )

    def test_run_sync_and_creation_helpers_cover_remaining_error_and_transition_paths(self) -> None:
        """Covers live-run sync branches plus task and run creation error handling."""

        settings = replace(
            get_settings(),
            cursor_api_key="cursor-token",
            github_owner="acme",
            github_repositories=["platform-web"],
        )

        cursor_run = {
            "id": "run-1",
            "status": "Running",
            "branch": "ai/original",
            "currentStep": "Original step",
            "blockers": ["Original blocker"],
            "summary": "Original summary",
            "_cursorAgent": {"id": "agent-1"},
        }

        with patch("app.state.get_cursor_agent", side_effect=state.CursorAgentError("offline")):
            # Confirm Cursor polling failures leave the last known run state untouched.
            state._sync_run_progress(cursor_run, settings)
        self.assertEqual(cursor_run["currentStep"], "Original step")

        with patch(
            "app.state.get_cursor_agent",
            return_value={"id": "agent-1", "status": "ERROR", "target": {}, "summary": "Provider summary"},
        ):
            # Confirm Cursor error states move the run into a readable blocked state.
            state._sync_run_progress(cursor_run, settings)
        self.assertEqual(cursor_run["currentStep"], "Cursor Cloud Agent ended with status ERROR")
        self.assertEqual(cursor_run["blockers"][0], "Cursor status is ERROR")

        # Reset the run to an active state so the next poll exercises the running branch.
        cursor_run["status"] = "Running"

        with patch(
            "app.state.get_cursor_agent",
            return_value={"id": "agent-1", "status": "RUNNING", "target": {"branchName": "ai/new"}, "summary": ""},
        ):
            # Confirm active Cursor runs expose the running-status message and updated branch name.
            state._sync_run_progress(cursor_run, settings)
        self.assertEqual(cursor_run["currentStep"], "Cursor Cloud Agent status: RUNNING")
        self.assertEqual(cursor_run["blockers"][0], "Cursor Cloud Agent is still running")
        self.assertEqual(cursor_run["branch"], "ai/new")

        with patch("app.state.update_linear_issue_status") as mock_update_linear_issue_status:
            # Confirm non-dict Linear issue snapshots are ignored before sync is attempted.
            state._sync_linear_issue_status_from_pr(
                {"_issueSnapshot": "invalid"},
                settings=settings,
                pr_state={"source": "github", "state": "open", "merged": False},
            )

            # Confirm Linear issue snapshots without an ID are ignored before sync is attempted.
            state._sync_linear_issue_status_from_pr(
                {"_issueSnapshot": {"provider": "linear", "id": ""}},
                settings=settings,
                pr_state={"source": "github", "state": "open", "merged": False},
            )
        mock_update_linear_issue_status.assert_not_called()

        with patch("app.state.update_jira_issue_status") as mock_update_jira_issue_status:
            # Confirm non-dict Jira issue snapshots are ignored before sync is attempted.
            state._sync_jira_issue_status_from_pr(
                {"_issueSnapshot": "invalid"},
                settings=settings,
                pr_state={"source": "github", "state": "open", "merged": False},
            )

            # Confirm Jira issue snapshots without an ID are ignored before sync is attempted.
            state._sync_jira_issue_status_from_pr(
                {"_issueSnapshot": {"provider": "jira", "id": ""}},
                settings=settings,
                pr_state={"source": "github", "state": "open", "merged": False},
            )

            # Confirm unmapped PR states do not trigger Jira status updates.
            state._sync_jira_issue_status_from_pr(
                {"_issueSnapshot": {"provider": "jira", "id": "jira-1"}},
                settings=settings,
                pr_state={"source": "gitlab", "state": "open", "merged": False},
            )
        mock_update_jira_issue_status.assert_not_called()

        review_run = {
            "id": "run-2",
            "ticket": "ACP-2",
            "repo": "platform-web",
            "status": "Review",
            "currentStep": "Waiting for review",
            "blockers": ["Waiting for reviewer decision"],
            "approvalHistory": [],
        }

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={
                "source": "github",
                "state": "approved",
                "merged": False,
                "approved": True,
                "approvedAt": "2026-04-24T12:00:00+00:00",
                "approvedBy": "reviewer1",
            },
        ), patch("app.state._sync_issue_tracker_status_from_pr"):
            # Confirm approved GitHub reviews promote Review runs into Approved.
            approved_state = state._sync_pull_request_status(review_run, settings)
        self.assertEqual(approved_state["state"], "approved")
        self.assertEqual(review_run["status"], "Approved")
        self.assertEqual(review_run["blockers"], ["Awaiting pull-request merge on GitHub"])

        with patch(
            "app.state._resolve_pull_request_state",
            return_value={
                "source": "github",
                "state": "merged",
                "merged": True,
                "mergedAt": "2026-04-24T12:05:00+00:00",
                "approved": True,
                "approvedAt": "2026-04-24T12:00:00+00:00",
                "approvedBy": "reviewer1",
            },
        ), patch("app.state._sync_issue_tracker_status_from_pr"):
            # Confirm merged GitHub PRs promote Approved runs into Merged.
            merged_state = state._sync_pull_request_status(review_run, settings)
        self.assertEqual(merged_state["state"], "merged")
        self.assertEqual(review_run["status"], "Merged")
        self.assertEqual(review_run["blockers"], ["No active blockers"])

        initial_run_count = len(state.RUN_STORE)
        integration_catalog = {
            "issues": [],
            "documents": [],
            "repositories": [{"name": "platform-web", "url": "https://github.com/acme/platform-web"}],
            "currentUser": {
                "name": "Maya Chen",
                "email": "maya.chen@example.com",
                "role": "admin",
                "provider": "guided_sign_in",
            },
        }

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state.create_run",
            side_effect=RuntimeError("launch failed"),
        ):
            with self.assertRaises(RuntimeError):
                # Confirm failed automatic run starts clean up the just-created task entry.
                state.create_task(
                    settings,
                    {},
                    {
                        "repoName": "platform-web",
                        "title": "Task title",
                        "prompt": "Task prompt",
                        "acceptanceCriteria": "Ship it",
                        "executionMode": "implement",
                    },
                )
        self.assertEqual(len(state.RUN_STORE), initial_run_count)

        state.RUN_STORE[:] = [
            {
                "id": "task-1",
                "ticket": "ACP-3",
                "title": "Task title",
                "repo": "platform-web",
                "branch": "ai/acp-3-task-title",
                "owner": "Maya Chen",
                "agent": "impl-agent",
                "runtime": "00:00",
                "cost": "$0.00",
                "status": "Running",
                "risk": "Medium",
                "currentStep": "Starting",
                "summary": "Task prompt",
                "blockers": ["Starting run"],
                "approvalHistory": [],
                "_issueSnapshot": None,
                "_documentSnapshots": [],
                "_requestedBySnapshot": integration_catalog["currentUser"],
            }
        ]

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state.launch_cursor_agent",
            side_effect=state.CursorAgentError("provider launch failed"),
        ):
            with self.assertRaises(HTTPException) as cursor_launch_error:
                # Confirm provider launch failures become a 502 API error for the caller.
                state.create_run(
                    settings,
                    {},
                    {"taskId": "task-1", "agentName": "impl-agent", "executionMode": "implement"},
                )
        self.assertEqual(cursor_launch_error.exception.status_code, 502)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
