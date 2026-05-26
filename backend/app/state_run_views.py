"""Shared run-view helpers for state payload builders."""

from typing import Any, Callable, Dict, List, Mapping, Optional

from app.config import Settings


BuildRunExtensions = Callable[..., Dict[str, Any]]
SyncRunProgress = Callable[[Dict[str, Any], Settings], None]


def enrich_run_for_catalog(
    run: Dict[str, Any],
    *,
    integration_catalog: Mapping[str, Any],
    settings: Settings,
    build_run_extensions: BuildRunExtensions,
    sync_run_progress: SyncRunProgress,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Synchronizes a run and attaches the common catalog-backed view fields."""

    # Advance live or simulated progress before building the public run payload.
    sync_run_progress(run, settings)
    attached_documents = documents if documents is not None else list(integration_catalog["documents"])[:2]

    # Return the same enriched run shape used by dashboard, detail, and approval views.
    return build_run_extensions(
        run,
        documents=attached_documents,
        current_user=integration_catalog["currentUser"],
        settings=settings,
        repositories=integration_catalog["repositories"],
    )


def enrich_runs_for_catalog(
    runs: List[Dict[str, Any]],
    *,
    integration_catalog: Mapping[str, Any],
    settings: Settings,
    build_run_extensions: BuildRunExtensions,
    sync_run_progress: SyncRunProgress,
) -> List[Dict[str, Any]]:
    """Builds enriched public run payloads for a list of stored runs."""

    enriched_runs: List[Dict[str, Any]] = []

    # Keep enrichment ordering identical to the source run list.
    for run in runs:
        enriched_runs.append(
            enrich_run_for_catalog(
                run,
                integration_catalog=integration_catalog,
                settings=settings,
                build_run_extensions=build_run_extensions,
                sync_run_progress=sync_run_progress,
            )
        )

    # Return the materialized run payload list for API responses.
    return enriched_runs


def index_runs_by_id(runs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Indexes stored runs by their public run identifier."""

    runs_by_id: Dict[str, Dict[str, Any]] = {}

    # Build a lookup table so requested run IDs can be resolved in O(1).
    for run in runs:
        run_id_value = str(run.get("id") or "")

        if run_id_value:
            # Keep the latest matching run for the identifier.
            runs_by_id[run_id_value] = run

    # Return the lookup table used by ordered run resolution.
    return runs_by_id
