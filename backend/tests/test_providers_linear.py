"""Unit coverage for Linear provider helpers beyond endpoint regressions."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderLinearTests(unittest.TestCase):
    """Verifies Linear connectivity, query, extraction, and catalog helpers."""

    def test_linear_query_and_extraction_helpers_cover_expected_behavior(self) -> None:
        """Covers Linear query builders, response extractors, and state catalog helpers."""

        # Confirm query builders emit the expected Linear GraphQL fragments.
        self.assertIn("issues(first: 20)", providers._build_linear_issue_query())
        self.assertIn("team:", providers._build_linear_issue_query("id"))
        self.assertIn("teams(filter:", providers._build_linear_team_lookup_query("key"))
        self.assertIn("team(id:", providers._build_linear_team_issue_query())

        response = {"data": {"issues": {"nodes": [{"id": "issue-1"}]}}}
        team_response = {"data": {"teams": {"nodes": [{"id": "team-1", "name": "Engineering"}]}}}
        team_issue_response = {"data": {"team": {"issues": {"nodes": [{"id": "issue-2"}]}}}}

        # Confirm the response extractors pull the expected node lists from GraphQL envelopes.
        self.assertEqual(providers._extract_linear_issue_nodes(response), [{"id": "issue-1"}])
        self.assertEqual(providers._extract_linear_team_node(team_response)["id"], "team-1")
        self.assertEqual(providers._extract_linear_team_issue_nodes(team_issue_response), [{"id": "issue-2"}])

        issue_catalog = providers._extract_linear_issue_state_catalog(
            {
                "data": {
                    "issue": {
                        "state": {"id": "todo"},
                        "team": {"states": {"nodes": [{"id": "doing", "name": "Doing", "type": "started"}]}},
                    }
                }
            }
        )

        # Confirm state-catalog extraction and fallback state matching behave as expected.
        self.assertEqual(issue_catalog["currentState"]["id"], "todo")
        self.assertEqual(
            providers._find_linear_state_node(issue_catalog["teamStates"], "In Progress")["id"],
            "doing",
        )

        settings = replace(get_settings(), linear_api_key="lin-token")

        # Confirm the shared Linear headers include the normalized token.
        self.assertEqual(providers._build_linear_headers(settings)["Authorization"], "lin-token")

        with patch("app.provider_linear._request_json", return_value={"data": {"viewer": {"id": "viewer-1"}}}):
            # Confirm the low-level GraphQL helper wraps the shared request call.
            self.assertEqual(
                providers._request_linear_graphql(settings, query="query Viewer { viewer { id } }")["data"]["viewer"]["id"],
                "viewer-1",
            )

        with patch("app.provider_linear._request_json", return_value={"data": {"viewer": {"id": "viewer-1"}}}):
            # Confirm connectivity succeeds when the Linear viewer auth check resolves an id.
            self.assertTrue(providers.is_linear_connected(settings))

    def test_list_linear_issues_covers_unscoped_and_scoped_catalog_reads(self) -> None:
        """Covers unscoped issue reads plus team-scoped fallback lookup behavior."""

        unscoped_settings = replace(get_settings(), linear_api_key="lin-token", linear_team_id="")

        with patch(
            "app.provider_linear._request_json",
            return_value={
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "issue-1",
                                "identifier": "ENG-1",
                                "title": "Linear issue",
                                "description": "Description",
                                "priority": 1,
                                "url": "https://linear.app/acme/issue/ENG-1",
                                "state": {"name": "Todo"},
                                "assignee": {"name": "Maya"},
                            }
                        ]
                    }
                }
            },
        ):
            # Confirm unscoped issue listing normalizes a standard Linear issue payload.
            issues = providers.list_linear_issues(unscoped_settings)
            self.assertEqual(issues[0]["ticket"], "ENG-1")
            self.assertEqual(issues[0]["provider"], "linear")

        scoped_settings = replace(get_settings(), linear_api_key="lin-token", linear_team_id="ENG")

        def fake_linear_request(url, *, method="GET", headers=None, payload=None):
            """Returns GraphQL fixtures that emulate a team-key scoped issue lookup."""

            query_text = (payload or {}).get("query", "")

            # Return no match for the team-id attempt so the helper retries the team key.
            if "teams(filter:" in query_text and "id:" in query_text:
                return {"data": {"teams": {"nodes": []}}}

            # Return the matching team when the helper retries by key.
            if "teams(filter:" in query_text and "key:" in query_text:
                return {"data": {"teams": {"nodes": [{"id": "team-1", "key": "ENG", "name": "Engineering"}]}}}

            # Return the team-scoped issues after the team lookup succeeds.
            if "team(id:" in query_text:
                return {
                    "data": {
                        "team": {
                            "issues": {
                                "nodes": [
                                    {
                                        "id": "issue-2",
                                        "identifier": "ENG-2",
                                        "title": "Scoped issue",
                                        "description": "Scoped description",
                                        "priority": 2,
                                        "url": "https://linear.app/acme/issue/ENG-2",
                                        "state": {"name": "Backlog"},
                                        "assignee": {"name": "Priya"},
                                    }
                                ]
                            }
                        }
                    }
                }

            # Return an empty fallback payload for any unexpected request shape.
            return {"data": {"teams": {"nodes": []}}}

        with patch("app.provider_linear._request_json", side_effect=fake_linear_request):
            # Confirm team-scoped issue listing retries common team-scope formats.
            scoped_issues = providers.list_linear_issues(scoped_settings)
            self.assertEqual(scoped_issues[0]["ticket"], "ENG-2")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
