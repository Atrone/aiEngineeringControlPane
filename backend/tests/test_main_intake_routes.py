"""Route coverage for intake-facing callables in main.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.providers import OpenAIEnrichmentError
from app.schemas import IntakeEnrichRequest
from app.schemas import IntakeIdentifyRepositoryRequest
from app.schemas import IntakeIssueScopingRequest


class MainIntakeRouteTests(unittest.TestCase):
    """Verifies intake route wrappers in main.py."""

    def test_get_intake_and_issue_scoping_route_paths(self) -> None:
        """Covers intake fetch plus issue-scoping success and failure paths."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        intake_catalog = {
            "repositories": [],
            "issues": [
                {"id": "issue-1", "title": "First issue"},
                {"id": "issue-2", "title": "Second issue"},
            ],
            "documents": [],
            "currentUser": {"email": "user@example.com"},
            "integrationStatuses": [],
        }

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ):
            # Confirm the intake route simply returns the integrated catalog payload.
            self.assertEqual(main.get_intake(request)["issues"][0]["id"], "issue-1")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ), patch(
            "app.main.classify_intake_issues_by_scope",
            return_value={"wellScopedIssueIds": ["issue-1"], "poorlyScopedIssueIds": ["issue-2"]},
        ) as mock_classify:
            # Confirm scoped issue classification preserves requested issue ordering.
            payload = IntakeIssueScopingRequest.model_validate({"issueIds": ["issue-2", "issue-1"]})
            response = main.post_intake_issue_scoping(payload, request)
            self.assertEqual(response["poorlyScopedIssueIds"], ["issue-2"])
            self.assertEqual(
                mock_classify.call_args.kwargs["issues"],
                [intake_catalog["issues"][1], intake_catalog["issues"][0]],
            )

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ):
            # Confirm unknown issue IDs produce a 404 for the route caller.
            with self.assertRaises(HTTPException) as not_found_error:
                main.post_intake_issue_scoping(
                    IntakeIssueScopingRequest.model_validate({"issueIds": ["missing"]}),
                    request,
                )
            self.assertEqual(not_found_error.exception.status_code, 404)

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ), patch(
            "app.main.classify_intake_issues_by_scope",
            side_effect=OpenAIEnrichmentError("scoping-failed"),
        ):
            # Confirm classifier failures are translated into route-facing HTTP exceptions.
            with self.assertRaises(HTTPException) as scoping_error:
                main.post_intake_issue_scoping(
                    IntakeIssueScopingRequest.model_validate({"issueIds": []}),
                    request,
                )
            self.assertEqual(scoping_error.exception.status_code, 502)

    def test_enrich_and_identify_repository_routes_delegate_correctly(self) -> None:
        """Covers intake enrichment and repository-identification success and failure paths."""

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        intake_catalog = {
            "repositories": [{"name": "platform-web", "fullName": "acme/platform-web"}],
            "issues": [{"id": "issue-1", "title": "First issue"}],
            "documents": [],
            "currentUser": {"email": "user@example.com"},
            "integrationStatuses": [],
        }

        enrich_payload = IntakeEnrichRequest.model_validate(
            {
                "field": "prompt",
                "value": "Current prompt",
                "title": "Task title",
                "prompt": "Current prompt",
                "acceptanceCriteria": "criterion",
                "repoName": "platform-web",
                "executionMode": "implement",
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

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.enrich_intake_field",
            return_value={"field": "prompt", "value": "Refined prompt"},
        ) as mock_enrich:
            # Confirm the enrich route forwards the payload fields to the provider helper.
            response = main.post_intake_enrich(enrich_payload, request)
            self.assertEqual(response["value"], "Refined prompt")
            self.assertEqual(mock_enrich.call_args.kwargs["repo_name"], "platform-web")
            self.assertEqual(mock_enrich.call_args.kwargs["uploaded_documents"][0].path, "uploads/architecture.md")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.enrich_intake_field",
            side_effect=OpenAIEnrichmentError("enrichment-failed"),
        ):
            # Confirm enrich failures are translated into route-facing HTTP exceptions.
            with self.assertRaises(HTTPException) as enrich_error:
                main.post_intake_enrich(enrich_payload, request)
            self.assertEqual(enrich_error.exception.status_code, 502)

        identify_payload = IntakeIdentifyRepositoryRequest.model_validate({"issueId": "issue-1"})

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ), patch(
            "app.main.identify_repository_for_issue",
            return_value={"repoName": "platform-web"},
        ) as mock_identify:
            # Confirm the identify route resolves the selected issue before prompting OpenAI.
            response = main.post_intake_identify_repository(identify_payload, request)
            self.assertEqual(response["repoName"], "platform-web")
            self.assertEqual(mock_identify.call_args.kwargs["issue"]["id"], "issue-1")

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ):
            # Confirm missing issue IDs produce a 404 for repository identification.
            with self.assertRaises(HTTPException) as missing_issue_error:
                main.post_intake_identify_repository(
                    IntakeIdentifyRepositoryRequest.model_validate({"issueId": "missing"}),
                    request,
                )
            self.assertEqual(missing_issue_error.exception.status_code, 404)

        with patch("app.main._authorized_request", return_value=("settings", {"x": "y"}, "session")), patch(
            "app.main.get_intake_payload",
            return_value=intake_catalog,
        ), patch(
            "app.main.identify_repository_for_issue",
            side_effect=OpenAIEnrichmentError("identify-failed"),
        ):
            # Confirm provider failures are translated into route-facing HTTP exceptions.
            with self.assertRaises(HTTPException) as identify_error:
                main.post_intake_identify_repository(identify_payload, request)
            self.assertEqual(identify_error.exception.status_code, 502)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
