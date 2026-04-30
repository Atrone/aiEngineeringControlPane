"""Unit coverage for request schema validation and alias behavior."""

import unittest

from pydantic import ValidationError

from app import schemas


class SchemaModelTests(unittest.TestCase):
    """Verifies every request schema accepts aliases and enforces required fields."""

    def test_task_and_run_request_models_apply_aliases_and_defaults(self) -> None:
        """Covers the task, run, approval, sign-in, and exchange request models."""

        # Confirm task creation accepts alias fields and applies list and mode defaults.
        task_request = schemas.TaskCreateRequest.model_validate(
            {
                "issueId": "issue-1",
                "repoName": "platform-web",
                "title": "Ship feature",
                "prompt": "Implement the feature.",
                "acceptanceCriteria": "Works end to end.",
                "uploadedDocuments": [
                    {
                        "id": "upload-doc-1",
                        "title": "Architecture",
                        "path": "uploads/architecture.md",
                        "updatedAt": "2026-04-24T18:00:00Z",
                        "content": "# Architecture",
                    }
                ],
            }
        )
        self.assertEqual(task_request.issue_id, "issue-1")
        self.assertEqual(task_request.repo_name, "platform-web")
        self.assertEqual(task_request.document_ids, [])
        self.assertEqual(task_request.uploaded_documents[0].path, "uploads/architecture.md")
        self.assertEqual(task_request.execution_mode, "implement")

        # Confirm run creation applies the default agent and execution mode.
        run_request = schemas.RunCreateRequest.model_validate({"taskId": "task-1"})
        self.assertEqual(run_request.task_id, "task-1")
        self.assertEqual(run_request.agent_name, "impl-agent")
        self.assertEqual(run_request.execution_mode, "implement")

        # Confirm approval decisions retain the optional notes default.
        approval_request = schemas.ApprovalDecisionRequest.model_validate(
            {"runId": "run-1", "decision": "approve"}
        )
        self.assertEqual(approval_request.run_id, "run-1")
        self.assertEqual(approval_request.notes, "")

        # Confirm sign-in and Google exchange schemas enforce the expected fields.
        sign_in_request = schemas.SignInRequest.model_validate(
            {"name": "User", "email": "user@example.com", "role": "admin", "teamId": "platform"}
        )
        exchange_request = schemas.GoogleAuthExchangeRequest.model_validate({"code": "exchange-code"})
        self.assertEqual(sign_in_request.email, "user@example.com")
        self.assertEqual(sign_in_request.team_id, "platform")
        self.assertEqual(exchange_request.code, "exchange-code")

    def test_connection_request_models_accept_expected_alias_shapes(self) -> None:
        """Covers the GitHub, Linear, Jira, Cursor, and docs connection request models."""

        # Confirm GitHub connect uses its direct field names.
        github_request = schemas.GitHubConnectRequest.model_validate(
            {"owner": "acme", "repositories": "repo-one,repo-two", "token": "gh-token"}
        )
        self.assertEqual(github_request.owner, "acme")
        self.assertEqual(github_request.token, "gh-token")

        # Confirm Linear, Jira, Cursor, and docs models accept aliased field names.
        linear_request = schemas.LinearConnectRequest.model_validate({"apiKey": "lin-key", "teamId": "team-1"})
        jira_request = schemas.JiraConnectRequest.model_validate(
            {
                "siteUrl": "https://acme.atlassian.net",
                "email": "owner@example.com",
                "apiToken": "jira-token",
                "projectKey": "ACP",
            }
        )
        cursor_request = schemas.CursorConnectRequest.model_validate({"apiKey": "cursor-key"})
        docs_request = schemas.DocsConnectRequest.model_validate({"docsDirectory": "docs"})
        self.assertEqual(linear_request.api_key, "lin-key")
        self.assertEqual(jira_request.project_key, "ACP")
        self.assertEqual(cursor_request.model, "default")
        self.assertEqual(docs_request.docs_directory, "docs")

    def test_intake_and_dashboard_request_models_support_alias_population(self) -> None:
        """Covers the intake enrichment, identification, scoping, and dashboard request models."""

        # Confirm the enrichment model supports aliased inputs and default values.
        enrich_request = schemas.IntakeEnrichRequest.model_validate(
            {
                "field": "prompt",
                "value": "Current prompt",
                "title": "Task title",
                "acceptanceCriteria": "A",
                "repoName": "platform-web",
                "executionMode": "plan",
                "issueId": "issue-1",
                "uploadedDocuments": [
                    {
                        "id": "upload-doc-1",
                        "title": "Architecture",
                        "path": "uploads/architecture.md",
                        "updatedAt": "2026-04-24T18:00:00Z",
                        "content": "# Architecture",
                    }
                ],
            }
        )
        self.assertEqual(enrich_request.acceptance_criteria, "A")
        self.assertEqual(enrich_request.repo_name, "platform-web")
        self.assertEqual(enrich_request.execution_mode, "plan")
        self.assertEqual(enrich_request.uploaded_documents[0].title, "Architecture")

        # Confirm the identify-repository, issue-scoping, and dashboard models accept aliases.
        identify_request = schemas.IntakeIdentifyRepositoryRequest.model_validate({"issueId": "issue-1"})
        scoping_request = schemas.IntakeIssueScopingRequest.model_validate({"issueIds": ["issue-1", "issue-2"]})
        dashboard_request = schemas.DashboardSuggestedActionsRequest.model_validate({"runIds": ["run-1"]})
        self.assertEqual(identify_request.issue_id, "issue-1")
        self.assertEqual(scoping_request.issue_ids, ["issue-1", "issue-2"])
        self.assertEqual(dashboard_request.run_ids, ["run-1"])

        # Confirm required alias-backed fields still raise validation errors when omitted.
        with self.assertRaises(ValidationError):
            schemas.TaskCreateRequest.model_validate({"title": "Missing aliases"})

        with self.assertRaises(ValidationError):
            schemas.IntakeIdentifyRepositoryRequest.model_validate({})


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
