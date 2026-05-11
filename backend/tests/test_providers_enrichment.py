"""Unit coverage for OpenAI-backed provider enrichment and suggestion helpers."""

import io
import unittest
from dataclasses import replace
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderEnrichmentTests(unittest.TestCase):
    """Verifies OpenAI-backed enrichment, routing, and suggestion helpers."""

    def test_enrichment_message_and_response_helpers_cover_expected_behavior(self) -> None:
        """Covers enrichment normalization, message building, and response parsing helpers."""

        # Confirm field normalization maps the supported aliases into canonical field names.
        self.assertEqual(providers._normalize_enrichment_field("acceptanceCriteria"), "acceptance_criteria")
        self.assertEqual(providers._normalize_enrichment_field("task-title"), "title")
        self.assertEqual(providers._normalize_enrichment_field("description"), "prompt")

        # Confirm enrichment messages embed repo docs, intake context, and current field state.
        enrichment_messages = providers._build_enrichment_messages(
            field="prompt",
            value="Current prompt",
            title="Task title",
            prompt="Current prompt",
            acceptance_criteria="- [ ] Add tests",
            repo_name="platform-web",
            execution_mode="implement",
            docs_context="### README.md\nProject docs",
        )
        self.assertEqual(enrichment_messages[0]["role"], "system")
        self.assertIn("platform-web", enrichment_messages[1]["content"])
        self.assertIn(
            "uploads/architecture.md",
            providers._build_uploaded_doc_context(
                [{"path": "uploads/architecture.md", "content": "# Architecture"}]
            ),
        )

        # Confirm OpenAI content extraction handles both string and list-of-parts payloads.
        self.assertEqual(
            providers._extract_openai_message({"choices": [{"message": {"content": "Refined text"}}]}),
            "Refined text",
        )
        self.assertEqual(
            providers._extract_openai_message({"choices": [{"message": {"content": [{"text": "Part 1"}, {"text": "Part 2"}]}}]}),
            "Part 1Part 2",
        )

        # Confirm issue-scoping prompts flatten issue details and normalize fenced JSON results.
        scope_messages = providers._build_issue_scope_classification_messages(
            issues=[{"id": "issue-1", "ticket": "ACP-1", "title": "Scope me", "description": "Detailed task", "status": "Todo", "priority": "High", "provider": "jira"}]
        )
        scope_result = providers._parse_issue_scope_classification_response(
            '```json\n{"wellScopedIssueIds":["issue-1"],"poorlyScopedIssueIds":[]}\n```',
            [{"id": "issue-1"}],
        )
        self.assertEqual(scope_messages[0]["role"], "system")
        self.assertEqual(scope_result["wellScopedIssueIds"], ["issue-1"])

        # Confirm repo-identification prompts and responses use the provided repository catalog.
        repo_messages = providers._build_repo_identification_messages(
            issue={"ticket": "ACP-1", "title": "Route issue", "description": "Repo routing", "status": "Todo", "priority": "High"},
            repositories=[{"name": "platform-web", "fullName": "acme/platform-web", "defaultBranch": "main", "provider": "github", "url": "https://github.com/acme/platform-web"}],
            docs_context="### README.md\nProject docs",
        )
        repo_result = providers._parse_repo_identification_response(
            '```json\n{"repoName":"platform-web","confidence":0.7,"reasoning":"Matches the UI repo."}\n```',
            [{"name": "platform-web", "fullName": "acme/platform-web"}],
        )
        self.assertEqual(repo_messages[1]["role"], "user")
        self.assertEqual(repo_result["repoName"], "platform-web")

        # Confirm run-summary and suggestions helpers flatten runs and clamp large outputs.
        run_summary = providers._summarize_run_for_suggestions(
            {
                "ticket": "ACP-1",
                "title": "Summarize me",
                "status": "Blocked",
                "risk": "High",
                "repo": "platform-web",
                "owner": "Maya",
                "agent": "impl-agent",
                "runtime": "08:00",
                "currentStep": "Waiting for secret",
                "blockers": ["Missing secret"],
                "pullRequest": {"state": "open", "approved": False, "merged": False},
            }
        )
        suggestions_messages = providers._build_suggested_actions_messages([{"ticket": "ACP-1"}])
        parsed_suggestions = providers._parse_suggested_actions_response(
            '{"suggestedActions":["A short action.","' + ('x' * 300) + '"]}'
        )
        self.assertIn("Missing secret", run_summary)
        self.assertEqual(suggestions_messages[0]["role"], "system")
        self.assertLessEqual(len(parsed_suggestions[1]), 240)

        # Confirm review-effort helpers use PR summaries and normalize model guesses.
        review_effort_line = providers._summarize_run_for_review_effort(
            {
                "id": "run-1",
                "ticket": "ACP-1",
                "title": "Review me",
                "status": "Review",
                "pullRequest": {"title": "PR title", "body": "Small UI-only change."},
            }
        )
        review_effort_messages = providers._build_review_effort_messages([{"id": "run-1", "pullRequest": {"body": "Small change."}}])
        parsed_review_efforts = providers._parse_review_effort_response(
            '{"reviewEfforts":[{"runId":"run-1","effortMinutes":12,"confidence":1.5,"rationale":"Clear scope."},{"runId":"missing","effortMinutes":99}]}',
            [{"id": "run-1"}],
        )
        self.assertIn("Small UI-only change", review_effort_line)
        self.assertEqual(review_effort_messages[0]["role"], "system")
        self.assertEqual(parsed_review_efforts[0]["label"], "Moderate review")
        self.assertEqual(parsed_review_efforts[0]["confidence"], 1.0)

    def test_openai_backed_helpers_cover_success_and_error_paths(self) -> None:
        """Covers direct enrichment, repo identification, and dashboard suggestions helpers."""

        settings = replace(
            get_settings(),
            openai_api_key="openai-token",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        )

        with patch(
            "app.providers._fetch_remote_repo_doc_context",
            return_value="### README.md\nDocs",
        ) as mock_remote_docs, patch(
            "app.providers._request_json",
            return_value={"choices": [{"message": {"content": "Refined prompt"}}]},
        ):
            # Confirm intake enrichment returns the refined value and docs metadata.
            enrichment_result = providers.enrich_intake_field(
                settings,
                field="prompt",
                value="Current prompt",
                title="Task title",
                prompt="Current prompt",
                acceptance_criteria="- [ ] Add tests",
                repo_name="platform-web",
                execution_mode="implement",
                uploaded_documents=[
                    {
                        "id": "upload-doc-1",
                        "title": "Architecture",
                        "path": "uploads/architecture.md",
                        "content": "# Architecture",
                    }
                ],
            )
            self.assertEqual(enrichment_result["value"], "Refined prompt")
            self.assertTrue(enrichment_result["docsConsidered"])
            mock_remote_docs.assert_not_called()

        with patch("app.providers._collect_doc_context", return_value="### README.md\nDocs"), patch(
            "app.providers._request_json",
            return_value={"choices": [{"message": {"content": '{"repoName":"platform-web","confidence":0.8,"reasoning":"Best fit"}'}}]},
        ):
            # Confirm repository identification returns the chosen repo plus model metadata.
            identification_result = providers.identify_repository_for_issue(
                settings,
                issue={"ticket": "ACP-1", "title": "Route issue"},
                repositories=[{"name": "platform-web", "fullName": "acme/platform-web"}],
            )
            self.assertEqual(identification_result["repoName"], "platform-web")
            self.assertTrue(identification_result["docsConsidered"])

        with patch(
            "app.providers._request_json",
            return_value={"choices": [{"message": {"content": '{"suggestedActions":["Review the blocked run."]}'}}]},
        ):
            # Confirm dashboard suggestions return the parsed suggestion list and run count.
            suggestions_result = providers.suggest_next_actions_for_runs(settings, runs=[{"ticket": "ACP-1"}])
            self.assertEqual(suggestions_result["suggestedActions"], ["Review the blocked run."])
            self.assertEqual(suggestions_result["runCount"], 1)

        with patch(
            "app.providers._request_json",
            return_value={"choices": [{"message": {"content": '{"reviewEfforts":[{"runId":"run-1","effortMinutes":18,"confidence":0.8,"rationale":"Small PR summary."}]}'}}]},
        ):
            # Confirm review-effort estimation returns parsed estimates and run count.
            review_effort_result = providers.estimate_review_effort_for_runs(
                settings,
                runs=[{"id": "run-1", "pullRequest": {"body": "Small PR summary."}}],
            )
            self.assertEqual(review_effort_result["reviewEfforts"][0]["effortMinutes"], 18)
            self.assertEqual(review_effort_result["runCount"], 1)

        # Confirm missing OpenAI configuration is rejected for enrichment use cases.
        with self.assertRaises(providers.OpenAIEnrichmentError):
            providers.enrich_intake_field(
                replace(settings, openai_api_key=""),
                field="prompt",
                value="Current prompt",
                title="Task title",
                prompt="Current prompt",
                acceptance_criteria="",
                repo_name="platform-web",
                execution_mode="implement",
            )

        with self.assertRaises(providers.OpenAIEnrichmentError):
            providers.identify_repository_for_issue(
                replace(settings, openai_api_key=""),
                issue={"ticket": "ACP-1", "title": "Route issue"},
                repositories=[{"name": "platform-web"}],
            )

        with self.assertRaises(providers.OpenAIEnrichmentError):
            providers.suggest_next_actions_for_runs(replace(settings, openai_api_key=""), runs=[{"ticket": "ACP-1"}])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            providers.estimate_review_effort_for_runs(replace(settings, openai_api_key=""), runs=[{"id": "run-1"}])

        http_error = HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"bad request body"),
        )

        with patch("app.providers._fetch_remote_repo_doc_context", return_value=""), patch(
            "app.providers._request_json",
            side_effect=http_error,
        ):
            # Confirm upstream OpenAI HTTP failures are translated into readable enrichment errors.
            with self.assertRaises(providers.OpenAIEnrichmentError):
                providers.enrich_intake_field(
                    settings,
                    field="prompt",
                    value="Current prompt",
                    title="Task title",
                    prompt="Current prompt",
                    acceptance_criteria="",
                    repo_name="platform-web",
                    execution_mode="implement",
                )

        with patch("app.providers._request_json", side_effect=URLError("offline")):
            # Confirm transport-level OpenAI failures are translated into readable errors.
            with self.assertRaises(providers.OpenAIEnrichmentError):
                providers.suggest_next_actions_for_runs(settings, runs=[{"ticket": "ACP-1"}])


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
