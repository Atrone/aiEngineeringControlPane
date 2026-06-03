"""Unit coverage for run live-view and run-progress helpers in state.py."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class StateLiveViewTests(unittest.TestCase):
    """Verifies stream, static, and Cursor-backed live-view helpers."""

    def setUp(self) -> None:
        """Preserves the shared run store before each test mutates it."""

        # Snapshot the shared in-memory run store so tests stay isolated.
        self.original_run_store = deepcopy(state.RUN_STORE)

    def tearDown(self) -> None:
        """Restores the shared run store after each test finishes."""

        # Restore the original in-memory run state for later tests.
        state.RUN_STORE = deepcopy(self.original_run_store)

    def _build_run(self) -> dict:
        """Builds a representative run payload for live-view helpers."""

        # Return a run fixture with evidence and metadata used across state tests.
        return {
            "id": "run-1",
            "ticket": "ACP-200",
            "title": "Wire state live views",
            "repo": "platform-web",
            "branch": "ai/acp-200-wire-state-live-views",
            "owner": "Maya",
            "agent": "impl-agent",
            "runtime": "08:00",
            "cost": "$1.00",
            "status": "Running",
            "risk": "Medium",
            "currentStep": "Loading task context",
            "summary": "Build live execution views for the dashboard.",
            "evidence": {
                "diff": ["Updated state helpers."],
                "tests": ["12 tests passed."],
                "commands": ["python -m unittest"],
                "rationale": ["Kept the live view compact and deterministic."],
            },
            "blockers": ["Awaiting run start"],
            "approvalHistory": [],
            "_executionMode": "implement",
            "_streamStartedAt": "2026-04-24T11:59:40+00:00",
        }

    def test_stream_and_static_live_views_build_expected_shapes(self) -> None:
        """Covers stream plans, stream views, static views, and live-view dispatch."""

        run = self._build_run()

        # Confirm the stream plan exposes the expected lifecycle steps.
        stream_plan = state._build_stream_plan(run)
        self.assertEqual(stream_plan[0]["id"], "accepted")
        self.assertEqual(stream_plan[-1]["id"], "handoff")

        with patch("app.state._utc_now", return_value=state._parse_timestamp("2026-04-24T11:59:48+00:00")), patch(
            "app.state._utc_timestamp",
            return_value="2026-04-24T11:59:48+00:00",
        ):
            # Confirm the streaming live view exposes timeline, logs, and evidence tabs.
            stream_live_view = state._build_stream_live_view(run)
            self.assertTrue(stream_live_view["isLive"])
            self.assertGreaterEqual(len(stream_live_view["timeline"]), 1)
            self.assertIn("diff", stream_live_view["evidenceTabs"])

        run["status"] = "Review"
        run["_streamStartedAt"] = ""

        with patch(
            "app.state._build_static_timepoints",
            return_value=[
                "2026-04-24T11:50:00+00:00",
                "2026-04-24T11:52:00+00:00",
                "2026-04-24T11:54:00+00:00",
                "2026-04-24T11:56:00+00:00",
                "2026-04-24T11:58:00+00:00",
            ],
        ), patch("app.state._utc_timestamp", return_value="2026-04-24T12:00:00+00:00"):
            # Confirm the static timeline and static logs expose the seeded evidence.
            static_timeline = state._build_static_timeline(run)
            static_logs = state._build_static_logs(run)
            static_live_view = state._build_static_live_view(run)
            self.assertEqual(static_timeline[0]["id"], "created")
            self.assertEqual(static_logs[-1]["message"], "Loading task context")
            self.assertEqual(static_live_view["statusLabel"], "Awaiting decision")

        # Confirm live-view dispatch selects the stream and static paths appropriately.
        run["_streamStartedAt"] = "2026-04-24T11:59:40+00:00"
        with patch("app.state._build_stream_live_view", return_value={"mode": "stream"}):
            self.assertEqual(state._build_live_view(run), {"mode": "stream"})
        run["_streamStartedAt"] = ""
        with patch("app.state._build_static_live_view", return_value={"mode": "static"}):
            self.assertEqual(state._build_live_view(run), {"mode": "static"})

    def test_cursor_cloud_live_views_and_run_progress_cover_status_transitions(self) -> None:
        """Covers Cursor-specific live views, status mapping, and progress syncing."""

        run = self._build_run()
        run["_cursorAgent"] = {
            "id": "agent-1",
            "status": "RUNNING",
            "createdAt": "2026-04-24T11:58:00+00:00",
            "target": {"branchName": "ai/acp-200", "prUrl": "https://github.com/acme/platform-web/pull/1"},
        }

        with patch("app.state._utc_timestamp", return_value="2026-04-24T12:00:00+00:00"):
            # Confirm the Cursor live view exposes its own timeline, logs, and rationale entries.
            cursor_live_view = state._build_cursor_cloud_live_view(run)
            self.assertTrue(cursor_live_view["isLive"])
            self.assertEqual(cursor_live_view["timeline"][0]["id"], "cursor-launch")
            self.assertEqual(cursor_live_view["evidenceTabs"]["rationale"][0]["summary"], "Live cloud agent launched")

        # Confirm status mapping collapses Cursor statuses into the app status model.
        self.assertEqual(state._map_cursor_agent_status("FINISHED"), "Review")
        self.assertEqual(state._map_cursor_agent_status("ERROR"), "Blocked")
        self.assertEqual(state._map_cursor_agent_status("RUNNING"), "Running")

        settings = get_settings()

        with patch(
            "app.state.get_cursor_agent",
            return_value={
                "id": "agent-1",
                "status": "FINISHED",
                "createdAt": "2026-04-24T11:58:00+00:00",
                "summary": "Cursor finished cleanly.",
                "target": {"branchName": "ai/acp-200", "prUrl": "https://github.com/acme/platform-web/pull/1"},
            },
        ), patch("app.state._utc_now", return_value=state._parse_timestamp("2026-04-24T11:58:00+00:00")):
            # Confirm Cursor-backed runs are updated from the live Cursor status payload.
            state._sync_run_progress(run, settings)
            self.assertEqual(run["status"], "Review")
            self.assertEqual(run["runtime"], "00:01")
            self.assertEqual(run["currentStep"], "Cursor Cloud Agent finished and prepared the review handoff")
            self.assertEqual(run["summary"], "Cursor finished cleanly.")

        reviewer_decided_run = self._build_run()
        reviewer_decided_run["status"] = "Approved"
        reviewer_decided_run["currentStep"] = "Approved by reviewer - awaiting pull request merge"
        reviewer_decided_run["blockers"] = ["Awaiting pull-request merge on GitHub"]
        reviewer_decided_run["_cursorAgent"] = {
            "id": "agent-1",
            "status": "FINISHED",
            "createdAt": "2026-04-24T11:58:00+00:00",
            "target": {"branchName": "ai/acp-200", "prUrl": "https://github.com/acme/platform-web/pull/1"},
        }

        with patch("app.state.get_cursor_agent") as get_cursor_agent_mock:
            # Confirm reviewer-driven states are not overwritten by subsequent Cursor polling.
            state._sync_run_progress(reviewer_decided_run, settings)
            self.assertEqual(reviewer_decided_run["status"], "Approved")
            self.assertEqual(reviewer_decided_run["currentStep"], "Approved by reviewer - awaiting pull request merge")
            get_cursor_agent_mock.assert_not_called()

        simulated_run = self._build_run()
        with patch("app.state._utc_now", return_value=state._parse_timestamp("2026-04-24T11:59:50+00:00")):
            # Confirm simulator-backed runs update runtime, cost, and current step while in progress.
            state._sync_run_progress(simulated_run, settings)
            self.assertEqual(simulated_run["status"], "Running")
            self.assertEqual(simulated_run["runtime"], "00:10")
            self.assertEqual(simulated_run["blockers"][0], "Streaming execution in progress")

        completed_run = self._build_run()
        with patch("app.state._utc_now", return_value=state._parse_timestamp("2026-04-24T12:00:20+00:00")):
            # Confirm simulated runs advance into review once the final stream step is visible.
            state._sync_run_progress(completed_run, settings)
            self.assertEqual(completed_run["status"], "Review")
            self.assertEqual(completed_run["currentStep"], "Review package ready")

    def test_github_copilot_live_view_builds_timeline_logs_and_pr_rationale(self) -> None:
        """Covers state_live_views._build_github_copilot_live_view via the state wrapper."""

        run = self._build_run()
        run["_githubCopilotAgent"] = {
            "id": "github-copilot-123",
            "status": "ASSIGNED",
            "createdAt": "2026-04-24T11:58:00+00:00",
            "target": {
                "url": "https://github.com/acme/platform-web/issues/42",
                "prUrl": "https://github.com/acme/platform-web/pull/43",
            },
        }
        run["_githubCopilotPromptSummary"] = "Sent the task to GitHub Copilot."

        with patch("app.state._utc_timestamp", return_value="2026-04-24T12:00:00+00:00"):
            # Confirm the Copilot live view exposes timeline, logs, and PR rationale entries.
            copilot_live_view = state._build_github_copilot_live_view(run)
            self.assertEqual(copilot_live_view["timeline"][0]["id"], "github-copilot-launch")
            self.assertIn("issues/42", copilot_live_view["logs"][0]["message"])
            self.assertEqual(copilot_live_view["evidenceTabs"]["rationale"][-1]["summary"], "Pull request link available")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
