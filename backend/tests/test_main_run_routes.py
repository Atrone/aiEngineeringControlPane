"""Route coverage for task, run, and approval callables in main.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.schemas import ApprovalDecisionRequest
from app.schemas import RunCreateRequest
from app.schemas import TaskCreateRequest


class MainRunRouteTests(unittest.TestCase):
    """Verifies task, run, and approval route wrappers in main.py."""

    def test_task_and_run_routes_delegate_to_state_helpers(self) -> None:
        """Covers task creation plus run creation success and not-found paths."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        task_payload = TaskCreateRequest.model_validate(
            {
                "issueId": "issue-1",
                "repoName": "platform-web",
                "title": "Task title",
                "prompt": "Task prompt",
                "acceptanceCriteria": "criterion",
                "documentIds": ["doc-1"],
                "executionMode": "implement",
            }
        )

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.create_task",
            return_value={"id": "task-1"},
        ) as mock_create_task:
            # Confirm task creation forwards the alias-preserving payload into the state layer.
            task_response = main.post_task(task_payload, request)
            self.assertEqual(task_response["id"], "task-1")
            self.assertEqual(mock_create_task.call_args.args[2]["repoName"], "platform-web")

        run_payload = RunCreateRequest.model_validate(
            {"taskId": "task-1", "agentName": "impl-agent", "executionMode": "plan"}
        )

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.create_run",
            return_value={"id": "task-1", "status": "Running"},
        ) as mock_create_run:
            # Confirm run creation forwards the alias-preserving payload into the state layer.
            run_response = main.post_run(run_payload, request)
            self.assertEqual(run_response["status"], "Running")
            self.assertEqual(mock_create_run.call_args.args[2]["taskId"], "task-1")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.create_run",
            side_effect=KeyError("missing-task"),
        ):
            # Confirm missing tasks become 404 responses from the run route.
            with self.assertRaises(HTTPException) as run_error:
                main.post_run(run_payload, request)
            self.assertEqual(run_error.exception.status_code, 404)

    def test_run_artifacts_route_downloads_cursor_artifact_contents(self) -> None:
        """Covers the run artifacts route for Cursor-backed and missing runs."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_run_detail",
            return_value={"cloudAgent": {"id": "agent-1"}},
        ), patch(
            "app.main._build_cursor_artifact_results",
            return_value={"agentId": "agent-1", "items": [{"path": "artifacts/result.txt"}]},
        ) as mock_build_cursor_artifact_results:
            # Confirm the route resolves the run and delegates artifact assembly to the Cursor helper.
            artifact_response = main.read_run_artifacts("run-1", request)
            self.assertEqual(artifact_response["agentId"], "agent-1")
            self.assertEqual(mock_build_cursor_artifact_results.call_args.args[1], "agent-1")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_run_detail",
            return_value={"cloudAgent": None},
        ):
            # Confirm non-Cursor runs return a stable empty artifact payload.
            artifact_response = main.read_run_artifacts("run-1", request)
            self.assertEqual(artifact_response, {"agentId": "", "items": []})

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_run_detail",
            side_effect=KeyError("missing-run"),
        ):
            # Confirm missing runs become 404 responses from the artifact route.
            with self.assertRaises(HTTPException) as artifact_error:
                main.read_run_artifacts("missing-run", request)
            self.assertEqual(artifact_error.exception.status_code, 404)

    def test_approval_route_delegates_and_translates_missing_runs(self) -> None:
        """Covers approval submission success and missing-run translation behavior."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        approval_payload = ApprovalDecisionRequest.model_validate(
            {"runId": "run-1", "decision": "approve", "notes": "Looks good"}
        )

        with patch("app.main._authorized_request_with_roles", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.record_approval",
            return_value={"id": "run-1", "status": "Approved"},
        ) as mock_record_approval:
            # Confirm the approval route enforces admin access and forwards the payload.
            approval_response = main.post_approval(approval_payload, request)
            self.assertEqual(approval_response["status"], "Approved")
            self.assertEqual(mock_record_approval.call_args.args[2]["runId"], "run-1")

        with patch("app.main._authorized_request_with_roles", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.record_approval",
            side_effect=KeyError("missing-run"),
        ):
            # Confirm missing runs become 404 responses from the approval route.
            with self.assertRaises(HTTPException) as approval_error:
                main.post_approval(approval_payload, request)
            self.assertEqual(approval_error.exception.status_code, 404)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
