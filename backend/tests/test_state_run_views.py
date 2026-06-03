"""Unit coverage for run enrichment helpers in state_run_views.py."""

import unittest
from unittest.mock import patch

from app import state_run_views
from app.config import get_settings


class StateRunViewTests(unittest.TestCase):
    """Verifies run enrichment and run-id indexing helpers."""

    def test_index_runs_by_id_builds_lookup_table(self) -> None:
        """Covers state_run_views.index_runs_by_id."""

        runs = [
            {"id": "run-1", "title": "First"},
            {"id": "", "title": "Missing id"},
            {"id": "run-2", "title": "Second"},
        ]

        # Confirm only non-empty run ids are indexed for O(1) lookup.
        self.assertEqual(
            state_run_views.index_runs_by_id(runs),
            {
                "run-1": runs[0],
                "run-2": runs[2],
            },
        )

    def test_enrich_run_for_catalog_syncs_progress_and_builds_extensions(self) -> None:
        """Covers state_run_views.enrich_run_for_catalog."""

        run = {"id": "run-1", "status": "Running"}
        integration_catalog = {
            "documents": [{"id": "doc-1"}],
            "currentUser": {"name": "Maya"},
            "repositories": [{"id": "repo-1"}],
        }
        settings = get_settings()

        def fake_sync_run_progress(run_arg, settings_arg):
            """Marks the run as synced for the enrichment assertion."""

            # Mutate the run so the test can confirm sync_run_progress was invoked.
            run_arg["_synced"] = True

        def fake_build_run_extensions(run_arg, **kwargs):
            """Returns a deterministic enriched payload for assertions."""

            # Echo the synced marker and attached documents for verification.
            return {"id": run_arg["id"], "synced": run_arg.get("_synced"), "documents": kwargs["documents"]}

        # Confirm enrichment syncs progress and delegates to the shared extension builder.
        enriched_run = state_run_views.enrich_run_for_catalog(
            run,
            integration_catalog=integration_catalog,
            settings=settings,
            build_run_extensions=fake_build_run_extensions,
            sync_run_progress=fake_sync_run_progress,
        )
        self.assertEqual(enriched_run["synced"], True)
        self.assertEqual(enriched_run["documents"], [{"id": "doc-1"}])

    def test_enrich_runs_for_catalog_preserves_order(self) -> None:
        """Covers state_run_views.enrich_runs_for_catalog."""

        runs = [{"id": "run-1"}, {"id": "run-2"}]
        integration_catalog = {
            "documents": [],
            "currentUser": {},
            "repositories": [],
        }
        settings = get_settings()

        with patch(
            "app.state_run_views.enrich_run_for_catalog",
            side_effect=lambda run, **kwargs: {"id": run["id"], "enriched": True},
        ) as mock_enrich:
            # Confirm batch enrichment preserves source ordering.
            enriched_runs = state_run_views.enrich_runs_for_catalog(
                runs,
                integration_catalog=integration_catalog,
                settings=settings,
                build_run_extensions=lambda *args, **kwargs: {},
                sync_run_progress=lambda *args, **kwargs: None,
            )

        self.assertEqual(enriched_runs, [{"id": "run-1", "enriched": True}, {"id": "run-2", "enriched": True}])
        self.assertEqual(mock_enrich.call_count, 2)


if __name__ == "__main__":
    unittest.main()
