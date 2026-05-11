"""Unit coverage for pull-request and run-extension helpers in state.py."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class StatePullRequestSyncHelperTests(unittest.TestCase):
    """Verifies pull-request state resolution and run-extension helpers."""

    def test_pull_request_resolution_and_history_helpers_cover_expected_behavior(self) -> None:
        """Covers PR URL resolution, simulated state, live-state fallback, and history helpers."""

        run = {
            "id": "run-1",
            "ticket": "ACP-1",
            "repo": "platform-web",
            "status": "Review",
            "currentStep": "Review package ready",
            "blockers": [],
            "approvalHistory": [],
            "_approvedAt": "2026-04-24T11:59:00+00:00",
            "_approvedBy": "Priya",
        }

        # Confirm pull-request URL resolution uses the deterministic fallback when no cloud agent exists.
        self.assertEqual(
            state._resolve_pull_request_url(run),
            "https://github.com/example/platform-web/pull/acp-1",
        )

        # Confirm the connected GitHub owner replaces the placeholder in task-detail fallback links.
        self.assertEqual(
            state._resolve_pull_request_url(run, settings=replace(get_settings(), github_owner="acme")),
            "https://github.com/acme/platform-web/pull/acp-1",
        )

        # Confirm the GitHub URL helper distinguishes real GitHub PRs from example placeholders.
        self.assertFalse(state._is_real_github_pull_request_url("https://github.com/example/platform-web/pull/1"))
        self.assertTrue(state._is_real_github_pull_request_url("https://github.com/acme/platform-web/pull/1"))

        with patch("app.state._utc_now", return_value=state._parse_timestamp("2026-04-24T11:59:20+00:00")):
            # Confirm simulated PR state auto-advances from approved to merged after the delay.
            simulated_state = state._simulated_pull_request_state(run)
            self.assertTrue(simulated_state["merged"])
            self.assertEqual(simulated_state["state"], "merged")

        with patch("app.state.fetch_github_pull_request_status", return_value={"state": "open", "source": "github"}):
            # Confirm live GitHub state wins when the PR URL is real and GitHub returns data.
            resolved_state = state._resolve_pull_request_state(
                {
                    **run,
                    "_cursorAgent": {"target": {"prUrl": "https://github.com/acme/platform-web/pull/1"}},
                },
                get_settings(),
            )
            self.assertEqual(resolved_state["source"], "github")

        # Confirm history lookups detect existing decision/source tuples.
        self.assertFalse(state._approval_history_has_entry([], "approve", "reviewer"))
        self.assertTrue(
            state._approval_history_has_entry(
                [{"decision": "approve", "source": "reviewer"}],
                "approve",
                "reviewer",
            )
        )

        # Confirm pull-request events are appended only once for a given decision/source pair.
        state._append_pull_request_event(
            run,
            decision="pr_review_approved",
            source="github",
            notes="Approved upstream",
            timestamp="2026-04-24T12:00:00+00:00",
        )
        state._append_pull_request_event(
            run,
            decision="pr_review_approved",
            source="github",
            notes="Approved upstream",
            timestamp="2026-04-24T12:00:00+00:00",
        )
        self.assertEqual(len(run["approvalHistory"]), 1)

    def test_pull_request_view_and_run_extensions_include_expected_public_fields(self) -> None:
        """Covers pull-request view construction and public run extensions."""

        run = {
            "id": "run-1",
            "ticket": "ACP-1",
            "title": "Ship feature",
            "repo": "platform-web",
            "branch": "ai/acp-1-ship-feature",
            "owner": "Maya",
            "agent": "impl-agent",
            "runtime": "08:00",
            "cost": "$1.00",
            "status": "Review",
            "risk": "Medium",
            "currentStep": "Review package ready",
            "summary": "Build the requested feature.",
            "evidence": {"diff": [], "tests": [], "commands": [], "rationale": []},
            "blockers": [],
            "approvalHistory": [],
            "_pullRequestState": {
                "state": "open",
                "source": "github",
                "approved": False,
                "merged": False,
                "reviewInProgress": True,
                "reviewActivityAt": "2026-04-24T12:00:00+00:00",
                "reviewActivityBy": "reviewer",
                "reviewActivityState": "commented",
            },
            "_issueSnapshot": {"id": "issue-1", "ticket": "ACP-1", "provider": "linear"},
            "_documentSnapshots": [{"id": "doc-1", "path": "docs/architecture.md"}],
            "_requestedBySnapshot": {"name": "Maya", "email": "maya@example.com", "role": "admin", "provider": "guided"},
        }

        pull_request_view = state._build_pull_request_view(
            run,
            {"state": "approved", "source": "github", "approved": True, "merged": False},
            settings=replace(get_settings(), github_owner="acme"),
        )
        in_progress_pull_request_view = state._build_pull_request_view(
            run,
            {
                "state": "open",
                "source": "github",
                "approved": False,
                "merged": False,
                "reviewInProgress": True,
                "reviewActivityAt": "2026-04-24T12:00:00+00:00",
                "reviewActivityBy": "reviewer",
                "reviewActivityState": "commented",
            },
            settings=replace(get_settings(), github_owner="acme"),
        )

        # Confirm the pull-request payload exposes the normalized downstream fields.
        self.assertEqual(pull_request_view["status"], "approved")
        self.assertEqual(pull_request_view["state"], "approved")
        self.assertEqual(pull_request_view["url"], "https://github.com/acme/platform-web/pull/acp-1")
        self.assertTrue(in_progress_pull_request_view["reviewInProgress"])
        self.assertEqual(in_progress_pull_request_view["reviewActivityBy"], "reviewer")

        with patch("app.state._build_live_view", return_value={"timeline": []}):
            # Confirm run extensions expose issue, PR, CI, docs, user, and live-view fields.
            public_run = state._build_run_extensions(
                run,
                settings=replace(get_settings(), github_owner="acme"),
            )
            self.assertEqual(public_run["issue"]["id"], "issue-1")
            self.assertEqual(public_run["requestedBy"]["email"], "maya@example.com")
            self.assertEqual(public_run["ci"]["workflow"], "CI")
            self.assertEqual(public_run["liveView"], {"timeline": []})
            self.assertEqual(public_run["pullRequest"]["url"], "https://github.com/acme/platform-web/pull/acp-1")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
