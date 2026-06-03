"""Unit coverage for team-scoped catalog helpers in state_catalog.py."""

import unittest

from app import state
from app import state_catalog
from app.config import get_settings
from app.mock_data import RUN_SUMMARIES


class StateCatalogTests(unittest.TestCase):
    """Verifies team scoping, catalog materialization, and repository normalization."""

    def test_normalize_team_id_covers_caller_values_and_default_fallback(self) -> None:
        """Covers state_catalog.normalize_team_id and the state wrapper."""

        # Confirm caller-provided team ids are normalized to lowercase.
        self.assertEqual(state_catalog.normalize_team_id(" Platform Team "), "platform team")
        self.assertEqual(state._normalize_team_id(" Platform Team "), "platform team")

        # Confirm blank values fall back to the default team key.
        self.assertEqual(state_catalog.normalize_team_id(""), "default-team")
        self.assertEqual(state._normalize_team_id(""), "default-team")

    def test_resolve_team_id_from_headers_reads_demo_team_header(self) -> None:
        """Covers state_catalog.resolve_team_id_from_headers and the state wrapper."""

        # Confirm the demo team header is normalized into the active team scope.
        self.assertEqual(
            state_catalog.resolve_team_id_from_headers({"x-demo-team-id": " Alpha "}),
            "alpha",
        )
        self.assertEqual(
            state._resolve_team_id_from_headers({"x-demo-team-id": " Alpha "}),
            "alpha",
        )

    def test_run_belongs_to_team_and_list_team_runs_filter_run_store(self) -> None:
        """Covers team membership checks and run-store filtering helpers."""

        team_run = {"id": "run-a", "_teamId": "alpha"}
        other_run = {"id": "run-b", "_teamId": "beta"}
        run_store = [team_run, other_run]

        # Confirm membership checks compare normalized team ids.
        self.assertTrue(state_catalog.run_belongs_to_team(team_run, "Alpha"))
        self.assertFalse(state_catalog.run_belongs_to_team(other_run, "Alpha"))
        self.assertTrue(state._run_belongs_to_team(team_run, "Alpha"))

        # Confirm list_team_runs preserves insertion order for matching runs only.
        self.assertEqual(state_catalog.list_team_runs(run_store, "alpha"), [team_run])
        self.assertEqual(state._list_team_runs("alpha"), [])

        original_store = state.RUN_STORE[:]
        try:
            state.RUN_STORE[:] = [team_run, other_run]
            self.assertEqual(state._list_team_runs("alpha"), [team_run])
        finally:
            state.RUN_STORE[:] = original_store

    def test_catalog_team_runs_materializes_team_runs_or_falls_back(self) -> None:
        """Covers state_catalog.catalog_team_runs and the state wrapper."""

        catalog_runs = [{"id": "catalog-run"}]

        # Confirm explicit teamRuns entries are materialized for payload builders.
        self.assertEqual(
            state_catalog.catalog_team_runs({"teamRuns": catalog_runs}, RUN_SUMMARIES),
            catalog_runs,
        )
        self.assertEqual(
            state._catalog_team_runs({"teamRuns": catalog_runs}),
            catalog_runs,
        )

        # Confirm older catalogs without teamRuns still fall back to the run store.
        self.assertEqual(
            state_catalog.catalog_team_runs({}, RUN_SUMMARIES),
            list(RUN_SUMMARIES),
        )

    def test_normalize_repository_context_for_api_maps_public_shape(self) -> None:
        """Covers repository context normalization for task-detail responses."""

        repository = {
            "id": "repo-1",
            "name": "platform-web",
            "fullName": "acme/platform-web",
            "defaultBranch": "main",
            "url": "https://github.com/acme/platform-web",
            "provider": "github",
            "private": True,
        }

        # Confirm the helper maps internal repo records into the camelCase API shape.
        self.assertEqual(
            state_catalog.normalize_repository_context_for_api(repository),
            {
                "id": "repo-1",
                "name": "platform-web",
                "fullName": "acme/platform-web",
                "defaultBranch": "main",
                "url": "https://github.com/acme/platform-web",
                "provider": "github",
                "private": True,
            },
        )
        self.assertEqual(
            state._normalize_repository_context_for_api(repository),
            state_catalog.normalize_repository_context_for_api(repository),
        )

        # Confirm empty repository payloads are rejected instead of returning shells.
        self.assertIsNone(state_catalog.normalize_repository_context_for_api({}))
        self.assertIsNone(state_catalog.normalize_repository_context_for_api(None))

    def test_fallback_documents_and_list_connected_issues_delegate_to_providers(self) -> None:
        """Covers state_catalog.fallback_documents and list_connected_issues."""

        settings = get_settings()

        # Confirm fallback_documents returns repo docs when the provider finds them.
        self.assertEqual(
            state_catalog.fallback_documents(settings, lambda settings_arg: [{"id": "doc-1"}]),
            [{"id": "doc-1"}],
        )

        # Confirm fallback_documents returns an empty list when no docs are available.
        self.assertEqual(state_catalog.fallback_documents(settings, lambda settings_arg: []), [])

        # Confirm connected issue catalogs are merged in provider order.
        self.assertEqual(
            state_catalog.list_connected_issues(
                settings,
                lambda settings_arg: [{"id": "linear-1", "provider": "linear"}],
                lambda settings_arg: [{"id": "jira-1", "provider": "jira"}],
            ),
            [{"id": "linear-1", "provider": "linear"}, {"id": "jira-1", "provider": "jira"}],
        )

    def test_fallback_issues_and_repositories_build_catalog_records(self) -> None:
        """Covers state_catalog.fallback_issues and fallback_repositories."""

        sample_runs = [
            {
                "id": "run-1",
                "ticket": "ACP-1",
                "title": "First run",
                "summary": "Summary one",
                "status": "Review",
                "owner": "Maya",
                "repo": "platform-web",
            },
            {
                "id": "run-2",
                "ticket": "ACP-2",
                "title": "Second run",
                "summary": "Summary two",
                "status": "Running",
                "owner": "Alex",
                "repo": "platform-web",
            },
        ]

        # Confirm fallback issue records mirror seeded run summaries.
        fallback_issues = state_catalog.fallback_issues(sample_runs)
        self.assertEqual(fallback_issues[0]["ticket"], "ACP-1")
        self.assertEqual(fallback_issues[0]["provider"], "fallback")

        # Confirm fallback repository catalogs deduplicate repo names in first-seen order.
        fallback_repositories = state_catalog.fallback_repositories(sample_runs)
        self.assertEqual(fallback_repositories, [{"id": "platform-web", "name": "platform-web", "fullName": "platform-web", "defaultBranch": "main", "private": False, "provider": "fallback", "url": ""}])


if __name__ == "__main__":
    unittest.main()
