"""Additional coverage for OpenAI-facing provider helpers and PR-state guards."""

import io
import json
import unittest
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderOpenAIGapCoverageTests(unittest.TestCase):
    """Verifies the remaining uncovered OpenAI and PR helper branches."""

    def test_enrichment_helpers_cover_remaining_validation_and_transport_paths(self) -> None:
        """Covers enrichment field normalization, uploaded-doc filtering, and error translation."""

        # Confirm unknown enrichment fields fall back to their normalized snake_case name.
        self.assertEqual(providers._normalize_enrichment_field("Custom-Field"), "custom_field")

        uploaded_context = providers._build_uploaded_doc_context(
            [
                {"path": "docs/empty.md", "content": "   "},
                {"path": "docs/guide.md", "content": "Guide body"},
            ]
        )

        # Confirm empty uploaded docs are skipped while non-empty docs are included.
        self.assertIn("docs/guide.md", uploaded_context)
        self.assertNotIn("docs/empty.md", uploaded_context)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm OpenAI responses without choices are rejected clearly.
            providers._extract_openai_message({})

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm OpenAI responses without any text content are rejected clearly.
            providers._extract_openai_message({"choices": [{"message": {"content": []}}]})

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm unsupported enrichment fields are rejected before any provider call.
            providers.enrich_intake_field(
                get_settings().__class__(**{**get_settings().__dict__, "openai_api_key": "openai-token"}),
                field="repoName",
                value="platform-web",
                title="Task title",
                prompt="Task prompt",
                acceptance_criteria="Ship it",
                repo_name="platform-web",
                execution_mode="implement",
            )

        settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "openai_api_key": "openai-token",
                "openai_model": "gpt-4.1",
                "openai_base_url": "https://example-openai.test/v1",
            }
        )

        http_error = HTTPError(
            url="https://example-openai.test/v1/chat/completions",
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=None,
        )

        def raising_read():
            """Raises while reading the provider error body."""

            # Simulate a provider connection that closed before the body could be read.
            raise ValueError("body unavailable")

        http_error.read = raising_read  # type: ignore[assignment]

        with patch("app.provider_openai._build_uploaded_doc_context", return_value="Uploaded context"), patch(
            "app.provider_openai._request_json",
            side_effect=http_error,
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as http_error_result:
                # Confirm unreadable OpenAI HTTP bodies still produce a readable error message.
                providers.enrich_intake_field(
                    settings,
                    field="title",
                    value="Task title",
                    title="Task title",
                    prompt="Task prompt",
                    acceptance_criteria="Ship it",
                    repo_name="platform-web",
                    execution_mode="implement",
                )
        self.assertIn("status 502", str(http_error_result.exception))

        with patch("app.provider_openai._build_uploaded_doc_context", return_value="Uploaded context"), patch(
            "app.provider_openai._request_json",
            side_effect=URLError("offline"),
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as url_error_result:
                # Confirm OpenAI transport failures are translated into enrichment-specific errors.
                providers.enrich_intake_field(
                    settings,
                    field="title",
                    value="Task title",
                    title="Task title",
                    prompt="Task prompt",
                    acceptance_criteria="Ship it",
                    repo_name="platform-web",
                    execution_mode="implement",
                )
        self.assertIn("Could not reach OpenAI for enrichment", str(url_error_result.exception))

        with patch("app.provider_openai._build_uploaded_doc_context", return_value="Uploaded context"), patch(
            "app.provider_openai._request_json",
            side_effect=json.JSONDecodeError("bad", "doc", 0),
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as decode_error_result:
                # Confirm malformed OpenAI JSON responses are translated cleanly.
                providers.enrich_intake_field(
                    settings,
                    field="title",
                    value="Task title",
                    title="Task title",
                    prompt="Task prompt",
                    acceptance_criteria="Ship it",
                    repo_name="platform-web",
                    execution_mode="implement",
                )
        self.assertIn("could not be parsed as JSON", str(decode_error_result.exception))

    def test_issue_scope_and_repo_identification_helpers_cover_error_paths(self) -> None:
        """Covers issue-scoping and repo-identification parsing plus transport error branches."""

        issues = [
            {"id": "issue-1", "title": "Scoped issue"},
            {"id": "issue-2", "title": "Needs clarification"},
        ]

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-JSON scoping responses are rejected.
            providers._parse_issue_scope_classification_response("not-json", issues)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-object scoping responses are rejected.
            providers._parse_issue_scope_classification_response("[]", issues)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm missing scoping arrays are rejected.
            providers._parse_issue_scope_classification_response('{"wellScopedIssueIds":[]}', issues)

        scoping_result = providers._parse_issue_scope_classification_response(
            '{"wellScopedIssueIds":["issue-1"],"poorlyScopedIssueIds":["issue-1","issue-2","missing"]}',
            issues,
        )

        # Confirm duplicate and unknown IDs are filtered while preserving valid assignments.
        self.assertEqual(scoping_result["wellScopedIssueIds"], ["issue-1"])
        self.assertEqual(scoping_result["poorlyScopedIssueIds"], ["issue-2"])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm empty issue lists are rejected before any OpenAI request is made.
            providers.classify_intake_issues_by_scope(get_settings(), issues=[])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm scoping requests are rejected when OpenAI is not configured.
            providers.classify_intake_issues_by_scope(get_settings(), issues=issues)

        settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "openai_api_key": "openai-token",
                "openai_model": "gpt-4.1",
                "openai_base_url": "https://example-openai.test/v1",
            }
        )

        classification_http_error = HTTPError(
            url="https://example-openai.test/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )

        def raising_classification_read():
            """Raises while reading the scoping provider error body."""

            # Simulate a truncated provider error body for the scoping request.
            raise ValueError("body unavailable")

        classification_http_error.read = raising_classification_read  # type: ignore[assignment]

        with patch("app.provider_openai._request_json", side_effect=classification_http_error):
            with self.assertRaises(providers.OpenAIEnrichmentError) as classification_http_error_result:
                # Confirm unreadable HTTP errors still surface a usable scoping message.
                providers.classify_intake_issues_by_scope(settings, issues=issues)
        self.assertIn("issue scoping request", str(classification_http_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=URLError("offline")):
            with self.assertRaises(providers.OpenAIEnrichmentError) as classification_url_error_result:
                # Confirm transport failures are translated into scoping-specific errors.
                providers.classify_intake_issues_by_scope(settings, issues=issues)
        self.assertIn("Could not reach OpenAI for issue scoping", str(classification_url_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=json.JSONDecodeError("bad", "doc", 0)):
            with self.assertRaises(providers.OpenAIEnrichmentError) as classification_decode_error_result:
                # Confirm malformed OpenAI JSON responses are translated for issue scoping.
                providers.classify_intake_issues_by_scope(settings, issues=issues)
        self.assertIn("could not be parsed as JSON", str(classification_decode_error_result.exception))

        repositories = [
            {"name": "platform-web", "fullName": "acme/platform-web"},
            {"name": "api-service", "fullName": "acme/api-service"},
        ]

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-JSON repo-identification responses are rejected.
            providers._parse_repo_identification_response("not-json", repositories)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-object repo-identification responses are rejected.
            providers._parse_repo_identification_response("[]", repositories)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm repo-identification responses must include repoName.
            providers._parse_repo_identification_response('{"confidence": 0.8}', repositories)

        identification_result = providers._parse_repo_identification_response(
            '{"repoName":"PLATFORM-WEB","confidence": 1.4,"reasoning":"Owns the UI."}',
            repositories,
        )

        # Confirm case-insensitive repo matches succeed and confidence is clamped into range.
        self.assertEqual(identification_result["repoName"], "platform-web")
        self.assertEqual(identification_result["confidence"], 1.0)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm repo-identification responses cannot invent repositories.
            providers._parse_repo_identification_response('{"repoName":"unknown"}', repositories)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm repo identification requires at least one integrated repository.
            providers.identify_repository_for_issue(settings, issue={"id": "issue-1"}, repositories=[])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm repo identification requires a selected issue.
            providers.identify_repository_for_issue(settings, issue={}, repositories=repositories)

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm repo identification requires OpenAI credentials.
            providers.identify_repository_for_issue(get_settings(), issue={"id": "issue-1"}, repositories=repositories)

        identification_http_error = HTTPError(
            url="https://example-openai.test/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

        def raising_identification_read():
            """Raises while reading the repo-identification provider error body."""

            # Simulate a provider error body that cannot be read back.
            raise ValueError("body unavailable")

        identification_http_error.read = raising_identification_read  # type: ignore[assignment]

        with patch("app.provider_openai._collect_doc_context", return_value="Repo docs"), patch(
            "app.provider_openai._request_json",
            side_effect=identification_http_error,
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as identification_http_error_result:
                # Confirm unreadable HTTP errors still surface a usable repository-identification message.
                providers.identify_repository_for_issue(settings, issue={"id": "issue-1"}, repositories=repositories)
        self.assertIn("repository identification request", str(identification_http_error_result.exception))

        with patch("app.provider_openai._collect_doc_context", return_value="Repo docs"), patch(
            "app.provider_openai._request_json",
            side_effect=URLError("offline"),
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as identification_url_error_result:
                # Confirm transport failures are translated into identification-specific errors.
                providers.identify_repository_for_issue(settings, issue={"id": "issue-1"}, repositories=repositories)
        self.assertIn("Could not reach OpenAI for repository identification", str(identification_url_error_result.exception))

        with patch("app.provider_openai._collect_doc_context", return_value="Repo docs"), patch(
            "app.provider_openai._request_json",
            side_effect=json.JSONDecodeError("bad", "doc", 0),
        ):
            with self.assertRaises(providers.OpenAIEnrichmentError) as identification_decode_error_result:
                # Confirm malformed OpenAI JSON responses are translated for repo identification.
                providers.identify_repository_for_issue(settings, issue={"id": "issue-1"}, repositories=repositories)
        self.assertIn("could not be parsed as JSON", str(identification_decode_error_result.exception))

    def test_suggested_actions_and_github_pr_helpers_cover_remaining_branches(self) -> None:
        """Covers suggestion parsing, suggestion transport errors, and PR helper edge cases."""

        # Confirm fenced JSON without a newline still parses correctly.
        self.assertEqual(
            providers._parse_suggested_actions_response('```{"suggestedActions":["Review the blocked run."]}```'),
            ["Review the blocked run."],
        )

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-JSON suggestions payloads are rejected.
            providers._parse_suggested_actions_response("not-json")

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-object suggestions payloads are rejected.
            providers._parse_suggested_actions_response("[]")

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm suggestions payloads must include the suggestedActions array.
            providers._parse_suggested_actions_response('{"notSuggestedActions":[]}')

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-JSON review-effort payloads are rejected.
            providers._parse_review_effort_response("not-json", [{"id": "run-1"}])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm non-object review-effort payloads are rejected.
            providers._parse_review_effort_response("[]", [{"id": "run-1"}])

        with self.assertRaises(providers.OpenAIEnrichmentError):
            # Confirm review-effort payloads must include the reviewEfforts array.
            providers._parse_review_effort_response('{"notReviewEfforts":[]}', [{"id": "run-1"}])

        parsed_actions = providers._parse_suggested_actions_response(
            json.dumps(
                {
                    "suggestedActions": [
                        "  ",
                        123,
                        "A" * 260,
                        "Review the blocked run.",
                    ]
                }
            )
        )

        # Confirm non-string and blank suggestions are dropped while long ones are truncated.
        self.assertEqual(len(parsed_actions), 2)
        self.assertLessEqual(len(parsed_actions[0]), 240)
        self.assertEqual(parsed_actions[1], "Review the blocked run.")

        settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "openai_api_key": "openai-token",
                "openai_model": "gpt-4.1",
                "openai_base_url": "https://example-openai.test/v1",
            }
        )
        runs = [{"id": "run-1", "ticket": "ACP-1", "title": "Blocked run", "status": "Blocked"}]

        suggestion_http_error = HTTPError(
            url="https://example-openai.test/v1/chat/completions",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )

        def raising_suggestion_read():
            """Raises while reading the suggestions provider error body."""

            # Simulate an unreadable provider error body for the suggestions call.
            raise ValueError("body unavailable")

        suggestion_http_error.read = raising_suggestion_read  # type: ignore[assignment]

        with patch("app.provider_openai._request_json", side_effect=suggestion_http_error):
            with self.assertRaises(providers.OpenAIEnrichmentError) as suggestion_http_error_result:
                # Confirm unreadable HTTP errors still surface a usable suggestions message.
                providers.suggest_next_actions_for_runs(settings, runs=runs)
        self.assertIn("suggested actions request", str(suggestion_http_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=URLError("offline")):
            with self.assertRaises(providers.OpenAIEnrichmentError) as suggestion_url_error_result:
                # Confirm transport failures are translated into suggestions-specific errors.
                providers.suggest_next_actions_for_runs(settings, runs=runs)
        self.assertIn("Could not reach OpenAI for suggested actions", str(suggestion_url_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=json.JSONDecodeError("bad", "doc", 0)):
            with self.assertRaises(providers.OpenAIEnrichmentError) as suggestion_decode_error_result:
                # Confirm malformed OpenAI JSON responses are translated for suggestions.
                providers.suggest_next_actions_for_runs(settings, runs=runs)
        self.assertIn("could not be parsed as JSON", str(suggestion_decode_error_result.exception))

        effort_http_error = HTTPError(
            url="https://example-openai.test/v1/chat/completions",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )

        def raising_effort_read():
            """Raises while reading the review-effort provider error body."""

            # Simulate an unreadable provider error body for the review-effort call.
            raise ValueError("body unavailable")

        effort_http_error.read = raising_effort_read  # type: ignore[assignment]

        with patch("app.provider_openai._request_json", side_effect=effort_http_error):
            with self.assertRaises(providers.OpenAIEnrichmentError) as effort_http_error_result:
                # Confirm unreadable HTTP errors still surface a usable review-effort message.
                providers.estimate_review_effort_for_runs(settings, runs=[{"id": "run-1"}])
        self.assertIn("review-effort request", str(effort_http_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=URLError("offline")):
            with self.assertRaises(providers.OpenAIEnrichmentError) as effort_url_error_result:
                # Confirm transport failures are translated into review-effort-specific errors.
                providers.estimate_review_effort_for_runs(settings, runs=[{"id": "run-1"}])
        self.assertIn("Could not reach OpenAI for review effort", str(effort_url_error_result.exception))

        with patch("app.provider_openai._request_json", side_effect=json.JSONDecodeError("bad", "doc", 0)):
            with self.assertRaises(providers.OpenAIEnrichmentError) as effort_decode_error_result:
                # Confirm malformed OpenAI JSON responses are translated for review-effort estimation.
                providers.estimate_review_effort_for_runs(settings, runs=[{"id": "run-1"}])
        self.assertIn("could not be parsed as JSON", str(effort_decode_error_result.exception))

        # Confirm invalid GitHub PR inputs are rejected before URL parsing.
        self.assertIsNone(providers.parse_github_pull_request_url(None))  # type: ignore[arg-type]

        with patch("app.provider_openai._request_json", side_effect=URLError("offline")):
            # Confirm GitHub PR payload fetches fail safely when the provider is offline.
            self.assertIsNone(providers._fetch_github_pull_request_payload(settings, "acme", "repo", "42"))

        with patch("app.provider_openai._request_json", side_effect=URLError("offline")):
            # Confirm GitHub PR review fetches fail safely when the provider is offline.
            self.assertEqual(providers._fetch_github_pull_request_reviews(settings, "acme", "repo", "42"), [])

        with patch("app.provider_openai._request_json", return_value={"not": "a-list"}):
            # Confirm GitHub PR review fetches reject non-list payloads.
            self.assertEqual(providers._fetch_github_pull_request_reviews(settings, "acme", "repo", "42"), [])

        # Confirm the latest-approved-review helper returns no review when none are approved.
        self.assertIsNone(providers._extract_latest_approved_review([{"state": "COMMENTED"}]))

        github_settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "github_owner": "acme",
                "github_repositories": ["platform-web"],
            }
        )

        with patch(
            "app.provider_github._fetch_github_pull_request_payload",
            return_value=None,
        ):
            # Confirm missing GitHub payloads fall back to the simulated PR path.
            self.assertIsNone(
                providers.fetch_github_pull_request_status(
                    github_settings,
                    "https://github.com/acme/platform-web/pull/42",
                )
            )

        with patch(
            "app.provider_github._fetch_github_pull_request_payload",
            return_value={"state": "open", "merged": True, "merged_at": "2026-04-24T12:00:00Z", "html_url": "https://github.com/acme/platform-web/pull/42"},
        ), patch(
            "app.provider_github._fetch_github_pull_request_reviews",
            return_value=[],
        ):
            # Confirm merged GitHub payloads resolve to the merged PR state.
            merged_status = providers.fetch_github_pull_request_status(
                github_settings,
                "https://github.com/acme/platform-web/pull/42",
            )
        self.assertEqual(merged_status["state"], "merged")

        with patch(
            "app.provider_github._fetch_github_pull_request_payload",
            return_value={"state": "closed", "merged": False, "html_url": "https://github.com/acme/platform-web/pull/42"},
        ), patch(
            "app.provider_github._fetch_github_pull_request_reviews",
            return_value=[],
        ):
            # Confirm closed-but-unmerged GitHub payloads resolve to the closed PR state.
            closed_status = providers.fetch_github_pull_request_status(
                github_settings,
                "https://github.com/acme/platform-web/pull/42",
            )
        self.assertEqual(closed_status["state"], "closed")

        with patch(
            "app.provider_github._fetch_github_pull_request_payload",
            return_value={"state": "open", "merged": False, "html_url": "https://github.com/acme/platform-web/pull/42"},
        ), patch(
            "app.provider_github._fetch_github_pull_request_reviews",
            return_value=[],
        ):
            # Confirm open GitHub payloads without approvals resolve to the open PR state.
            open_status = providers.fetch_github_pull_request_status(
                github_settings,
                "https://github.com/acme/platform-web/pull/42",
            )
        self.assertEqual(open_status["state"], "open")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
