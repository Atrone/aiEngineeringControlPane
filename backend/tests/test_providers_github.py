"""Unit coverage for GitHub provider helpers and integration summaries."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderGitHubTests(unittest.TestCase):
    """Verifies GitHub repository, PR-status, and integration-summary helpers."""

    def test_github_repository_and_pull_request_helpers_cover_expected_behavior(self) -> None:
        """Covers GitHub repository listing plus pull-request fetch and normalization helpers."""

        settings = replace(
            get_settings(),
            github_owner="acme",
            github_repositories=["platform-web"],
            github_token="gh-token",
        )

        with patch(
            "app.providers._request_json",
            return_value={
                "id": 101,
                "name": "platform-web",
                "full_name": "acme/platform-web",
                "default_branch": "main",
                "private": False,
                "html_url": "https://github.com/acme/platform-web",
            },
        ):
            # Confirm repository listing normalizes GitHub repo payloads into the app shape.
            repositories = providers.list_github_repositories(settings)
            self.assertEqual(repositories[0]["fullName"], "acme/platform-web")

        with patch(
            "app.providers._request_json",
            return_value={"state": "open", "merged": False, "html_url": "https://github.com/acme/platform-web/pull/42"},
        ):
            # Confirm raw PR fetches return the provider payload when GitHub responds.
            pr_payload = providers._fetch_github_pull_request_payload(settings, "acme", "platform-web", "42")
            self.assertEqual(pr_payload["state"], "open")

        with patch(
            "app.providers._request_json",
            return_value=[
                {"state": "APPROVED", "submitted_at": "2026-04-24T11:59:00Z", "user": {"login": "first"}},
                {"state": "APPROVED", "submitted_at": "2026-04-24T12:00:00Z", "user": {"login": "latest"}},
            ],
        ):
            # Confirm review fetches return a normalized list and latest approval selection works.
            reviews = providers._fetch_github_pull_request_reviews(settings, "acme", "platform-web", "42")
            self.assertEqual(providers._extract_latest_approved_review(reviews)["user"]["login"], "latest")

        with patch(
            "app.providers._fetch_github_pull_request_payload",
            return_value={
                "state": "open",
                "merged": False,
                "title": "Review dashboard lobby",
                "body": "Shows PR content in the lobby.",
                "html_url": "https://github.com/acme/platform-web/pull/42",
            },
        ), patch(
            "app.providers._fetch_github_pull_request_reviews",
            return_value=[{"state": "APPROVED", "submitted_at": "2026-04-24T12:00:00Z", "user": {"login": "reviewer"}}],
        ):
            # Confirm PR status normalization folds merge/review data into the app's PR model.
            pr_status = providers.fetch_github_pull_request_status(
                settings,
                "https://github.com/acme/platform-web/pull/42",
            )
            self.assertEqual(pr_status["state"], "approved")
            self.assertEqual(pr_status["approvedBy"], "reviewer")
            self.assertEqual(pr_status["title"], "Review dashboard lobby")
            self.assertEqual(pr_status["body"], "Shows PR content in the lobby.")

        # Confirm invalid PR URLs or missing GitHub config return None so simulation can take over.
        self.assertIsNone(providers.fetch_github_pull_request_status(settings, "https://example.com/not-a-pr"))
        self.assertIsNone(
            providers.fetch_github_pull_request_status(
                replace(settings, github_owner="", github_repositories=[]),
                "https://github.com/acme/platform-web/pull/42",
            )
        )

    def test_integration_statuses_cover_multi_provider_summary_logic(self) -> None:
        """Covers the top-level integration-status summary helper."""

        settings = replace(
            get_settings(),
            github_owner="acme",
            github_repositories=["platform-web"],
            linear_api_key="lin-token",
            jira_site_url="https://acme.atlassian.net",
            jira_email="owner@example.com",
            jira_api_token="jira-token",
            cursor_api_key="cursor-token",
            cursor_model="default",
            google_client_id="client",
            google_client_secret="secret",
            google_redirect_uri="http://localhost/callback",
        )

        with patch("app.providers.list_github_repositories", return_value=[{"name": "platform-web"}]), patch(
            "app.providers.is_linear_connected",
            return_value=True,
        ), patch(
            "app.providers.is_jira_connected",
            return_value=True,
        ), patch(
            "app.providers.is_cursor_connected",
            return_value=True,
        ), patch(
            "app.providers.list_linear_issues",
            return_value=[{"id": "linear-1"}],
        ), patch(
            "app.providers.list_jira_issues",
            return_value=[{"id": "jira-1"}],
        ), patch(
            "app.providers._utc_timestamp",
            return_value="2026-04-24T12:00:00+00:00",
        ):
            # Confirm integration summaries reflect the current live/mocked provider state.
            statuses = providers.get_integration_statuses(settings)
            self.assertEqual(statuses[0]["id"], "github")
            self.assertEqual(next(item for item in statuses if item["id"] == "linear")["mode"], "live")
            self.assertEqual(next(item for item in statuses if item["id"] == "jira")["details"], "1 issues available")
            self.assertEqual(next(item for item in statuses if item["id"] == "cursor_cloud_agents")["connected"], True)
            self.assertEqual(next(item for item in statuses if item["id"] == "google_sso")["connected"], True)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
