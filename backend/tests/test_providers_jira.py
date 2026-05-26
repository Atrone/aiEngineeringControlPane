"""Unit coverage for Jira provider helpers beyond endpoint regressions."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderJiraTests(unittest.TestCase):
    """Verifies Jira connectivity, normalization, and issue-catalog helpers."""

    def test_jira_helper_functions_cover_expected_behavior(self) -> None:
        """Covers JQL, description parsing, priority, assignee, and transition helpers."""

        # Confirm JQL generation supports both unscoped and project-scoped searches.
        self.assertEqual(providers._build_jira_search_jql(""), "ORDER BY updated DESC")
        self.assertIn('project = "ACP"', providers._build_jira_search_jql("acp"))

        description_payload = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Line one"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Line two"}]},
            ],
        }

        # Confirm nested Jira document-format descriptions flatten into plain text.
        self.assertIn("Line one", providers._extract_jira_description_text(description_payload))
        self.assertEqual(providers._extract_jira_description_text("Plain text"), "Plain text")

        # Confirm priority and assignee helpers normalize missing and present values.
        self.assertEqual(providers._normalize_jira_priority({"priority": {"name": "High"}}), "High")
        self.assertEqual(providers._normalize_jira_priority({}), "Medium")
        self.assertEqual(
            providers._normalize_jira_assignee({"assignee": {"displayName": "Maya", "emailAddress": "maya@example.com"}}),
            {"name": "Maya", "email": "maya@example.com"},
        )
        self.assertEqual(providers._normalize_jira_assignee({}), {})

        # Confirm status-category extraction and transition matching prefer exact names then categories.
        self.assertEqual(
            providers._extract_jira_status_category_name({"statusCategory": {"name": "Done"}}),
            "done",
        )
        matched_transition = providers._find_jira_transition(
            [
                {"id": "1", "name": "Start work", "to": {"name": "Doing", "statusCategory": {"name": "In Progress"}}},
                {"id": "2", "name": "Ship it", "to": {"name": "Done", "statusCategory": {"name": "Done"}}},
            ],
            "Done",
        )
        self.assertEqual(matched_transition["id"], "2")

    def test_jira_connectivity_and_issue_listing_cover_expected_behavior(self) -> None:
        """Covers Jira auth checks and normalized issue catalog generation."""

        settings = replace(
            get_settings(),
            jira_site_url="https://acme.atlassian.net",
            jira_email="owner@example.com",
            jira_api_token="jira-token",
            jira_project_key="ACP",
        )

        with patch("app.provider_jira._request_jira_json", return_value={"accountId": "acct-1"}):
            # Confirm Jira connectivity succeeds when the auth check resolves an account id.
            self.assertTrue(providers.is_jira_connected(settings))

        with patch(
            "app.provider_jira._request_jira_json",
            return_value={
                "issues": [
                    {
                        "id": "10001",
                        "key": "ACP-1",
                        "fields": {
                            "summary": "Jira issue",
                            "description": "Plain description",
                            "priority": {"name": "High"},
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Maya", "emailAddress": "maya@example.com"},
                        },
                    }
                ]
            },
        ):
            # Confirm Jira issue listing normalizes the REST issue payload into the app shape.
            issues = providers.list_jira_issues(settings)
            self.assertEqual(issues[0]["ticket"], "ACP-1")
            self.assertEqual(issues[0]["priority"], "High")
            self.assertEqual(issues[0]["provider"], "jira")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
