"""Unit coverage for run/task mutation helpers in state.py."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import state
from app.config import get_settings


class StateRunMutationTests(unittest.TestCase):
    """Verifies task creation, run creation, and approval mutation helpers."""

    def setUp(self) -> None:
        """Preserves the shared run store before each test mutates it."""

        # Snapshot the shared in-memory run store so tests stay isolated.
        self.original_run_store = deepcopy(state.RUN_STORE)

    def tearDown(self) -> None:
        """Restores the shared run store after each test finishes."""

        # Restore the original in-memory run state for later tests.
        state.RUN_STORE = deepcopy(self.original_run_store)

    def test_create_task_creates_a_new_run_with_selected_context(self) -> None:
        """Covers task creation and the automatic run start it triggers."""

        settings = get_settings()
        integration_catalog = {
            "repositories": [{"id": "platform-web", "name": "platform-web", "fullName": "acme/platform-web"}],
            "issues": [{"id": "issue-1", "ticket": "ACP-500", "title": "Selected issue", "provider": "linear"}],
            "documents": [{"id": "doc-1", "path": "docs/architecture.md"}],
            "currentUser": {"name": "Maya", "email": "maya@example.com", "role": "admin", "provider": "guided"},
            "statuses": [],
        }

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state.create_run",
            side_effect=lambda settings_arg, headers_arg, payload_arg: {
                "id": payload_arg["taskId"],
                "executionMode": payload_arg["executionMode"],
            },
        ) as mock_create_run:
            # Confirm task creation stores a new run and immediately starts it.
            created_task = state.create_task(
                settings,
                {},
                {
                    "issueId": "issue-1",
                    "repoName": "platform-web",
                    "title": "Create new task",
                    "prompt": "Implement the requested feature.",
                    "acceptanceCriteria": "- [ ] Add tests",
                    "documentIds": ["doc-1"],
                    "uploadedDocuments": [
                        {
                            "id": "upload-doc-1",
                            "title": "Architecture",
                            "path": "uploads/architecture.md",
                            "source": "uploaded_repo_document",
                            "updatedAt": "2026-04-24T18:00:00Z",
                            "content": "# Architecture",
                        }
                    ],
                    "executionMode": "implement",
                },
            )
            self.assertEqual(created_task["executionMode"], "implement")
            self.assertEqual(state.RUN_STORE[0]["repo"], "platform-web")
            self.assertEqual(state.RUN_STORE[0]["_issueSnapshot"]["id"], "issue-1")
            self.assertEqual(state.RUN_STORE[0]["_documentSnapshots"][0]["id"], "upload-doc-1")
            self.assertEqual(state.RUN_STORE[0]["_documentSnapshots"][0]["path"], "uploads/architecture.md")
            self.assertEqual(state.RUN_STORE[0]["_requestedBySnapshot"]["name"], "Maya")
            mock_create_run.assert_called_once()

    def test_create_run_covers_simulated_live_launch_and_cursor_live_launch_paths(self) -> None:
        """Covers simulated runs plus live Cursor-agent launches and error paths."""

        settings = get_settings()
        run = {
            "id": "task-1",
            "ticket": "ACP-600",
            "title": "Existing task",
            "repo": "platform-web",
            "branch": "ai/acp-600-existing-task",
            "owner": "Maya",
            "agent": "planner-agent",
            "runtime": "00:00",
            "cost": "$0.00",
            "status": "Retry",
            "risk": "Medium",
            "currentStep": "Awaiting another agent attempt",
            "summary": "Existing task summary",
            "evidence": {"diff": [], "tests": [], "commands": [], "rationale": []},
            "blockers": ["Awaiting run start"],
            "approvalHistory": [],
            "_issueSnapshot": {"id": "issue-1", "ticket": "ACP-600", "provider": "linear"},
            "_documentSnapshots": [{"id": "doc-1"}],
            "_requestedBySnapshot": {"name": "Maya", "email": "maya@example.com", "role": "admin", "provider": "guided"},
        }
        state.RUN_STORE.insert(0, run)

        integration_catalog = {
            "repositories": [{"name": "platform-web", "fullName": "acme/platform-web", "url": "https://github.com/acme/platform-web", "defaultBranch": "main"}],
            "documents": [{"id": "doc-1"}],
            "currentUser": {"name": "Maya", "email": "maya@example.com", "role": "admin", "provider": "guided"},
            "issues": [],
            "statuses": [],
        }

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state._build_run_extensions",
            side_effect=lambda run, **kwargs: {"id": run["id"], "status": run["status"], "agent": run["agent"], "cloudAgent": run.get("_cursorAgent")},
        ):
            # Confirm the simulated run-start path updates the run in place.
            simulated_response = state.create_run(
                settings,
                {},
                {"taskId": "task-1", "agentName": "impl-agent", "executionMode": "plan"},
            )
            self.assertEqual(simulated_response["status"], "Running")
            self.assertEqual(simulated_response["agent"], "impl-agent")

        live_settings = get_settings().__class__(**{**get_settings().__dict__, "cursor_api_key": "cursor-key"})

        with patch("app.state.get_integration_catalog", return_value=integration_catalog), patch(
            "app.state._build_cursor_prompt",
            return_value="Cursor prompt",
        ), patch(
            "app.state.launch_cursor_agent",
            return_value={"id": "agent-1", "target": {"branchName": "ai/acp-600-existing-task", "prUrl": ""}},
        ), patch(
            "app.state._build_run_extensions",
            side_effect=lambda run, **kwargs: {"id": run["id"], "status": run["status"], "agent": run["agent"], "cloudAgent": run.get("_cursorAgent")},
        ):
            # Confirm the live launch path switches the run into Cursor-backed execution.
            live_response = state.create_run(
                live_settings,
                {},
                {"taskId": "task-1", "agentName": "impl-agent", "executionMode": "implement"},
            )
            self.assertEqual(live_response["agent"], "cursor-cloud-agent")
            self.assertEqual(live_response["cloudAgent"]["id"], "agent-1")

        with patch("app.state.get_integration_catalog", return_value={"repositories": [], "documents": [], "currentUser": {}, "issues": [], "statuses": []}):
            # Confirm live launches fail cleanly when the selected repo lacks GitHub connection data.
            with self.assertRaises(HTTPException) as repo_error:
                state.create_run(
                    live_settings,
                    {},
                    {"taskId": "task-1", "agentName": "impl-agent", "executionMode": "implement"},
                )
            self.assertEqual(repo_error.exception.status_code, 400)

        # Confirm unknown task IDs still raise a key error for the API layer to translate.
        with self.assertRaises(KeyError):
            state.create_run(settings, {}, {"taskId": "missing-task", "agentName": "impl-agent"})

    def test_record_approval_covers_decision_branches_and_missing_runs(self) -> None:
        """Covers approval updates for approve, retry, re-scope, and fallback decisions."""

        settings = get_settings()
        run = {
            "id": "run-1",
            "ticket": "ACP-700",
            "title": "Approval target",
            "repo": "platform-web",
            "branch": "ai/acp-700-approval-target",
            "owner": "Maya",
            "agent": "impl-agent",
            "runtime": "10:00",
            "cost": "$1.50",
            "status": "Review",
            "risk": "High",
            "currentStep": "Review package ready",
            "summary": "Review me",
            "evidence": {"diff": [], "tests": [], "commands": [], "rationale": []},
            "blockers": [],
            "approvalHistory": [],
        }
        state.RUN_STORE.insert(0, run)

        with patch("app.state.resolve_current_user", return_value={"name": "Reviewer", "email": "reviewer@example.com", "role": "admin", "provider": "guided"}), patch(
            "app.state._build_run_extensions",
            side_effect=lambda run, **kwargs: {"id": run["id"], "status": run["status"], "approvalHistory": run["approvalHistory"]},
        ):
            # Confirm approval transitions move the run into Approved and record reviewer metadata.
            approved_response = state.record_approval(settings, {}, {"runId": "run-1", "decision": "approve", "notes": "Looks good"})
            self.assertEqual(approved_response["status"], "Approved")

            # Confirm retry decisions move the run into Retry.
            retry_response = state.record_approval(settings, {}, {"runId": "run-1", "decision": "retry", "notes": ""})
            self.assertEqual(retry_response["status"], "Retry")

            # Confirm re-scope decisions move the run into Blocked with the scope message.
            rescope_response = state.record_approval(settings, {}, {"runId": "run-1", "decision": "re-scope", "notes": ""})
            self.assertEqual(rescope_response["status"], "Blocked")

            # Confirm unrecognized decisions also fall back to the blocked escalation path.
            escalate_response = state.record_approval(settings, {}, {"runId": "run-1", "decision": "escalate", "notes": ""})
            self.assertEqual(escalate_response["status"], "Blocked")

        # Confirm unknown run IDs still raise a key error for the API layer to translate.
        with self.assertRaises(KeyError):
            state.record_approval(settings, {}, {"runId": "missing-run", "decision": "approve"})


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
