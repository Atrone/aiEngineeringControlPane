"""Repository markdown document discovery provider."""

from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import Settings


def _read_markdown_title(path: Path) -> str:
    """Extracts a readable title from a markdown document."""

    try:
        # Read the markdown file contents so the first heading can become the document title.
        contents = path.read_text(encoding="utf-8")
    except OSError:
        # Fall back to the file stem if the document cannot be read.
        return path.stem.replace("-", " ").replace("_", " ").title()

    # Search the file for the first markdown heading.
    for line in contents.splitlines():
        if line.startswith("#"):
            # Use the heading text without leading markdown syntax.
            return line.lstrip("#").strip()

    # Fall back to a title derived from the filename when there is no heading.
    return path.stem.replace("-", " ").replace("_", " ").title()


def _normalize_repo_doc_key(value: str) -> str:
    """Normalizes a repository or docs-folder name for matching."""

    # Collapse punctuation differences so GitHub names and local folder names match.
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _repo_doc_name_candidates(repo_name: str) -> List[str]:
    """Builds possible local docs-folder names for a repository selection."""

    normalized_repo_name = str(repo_name or "").strip()
    candidates: List[str] = []

    if normalized_repo_name:
        # Match the raw repo name first because local docs folders usually mirror it.
        candidates.append(normalized_repo_name)

        if "/" in normalized_repo_name:
            # Also match the slug from owner/repo names used by GitHub fullName fields.
            candidates.append(normalized_repo_name.rsplit("/", 1)[-1])

    normalized_candidates: List[str] = []

    # Deduplicate candidates after applying the same normalization used for folder matching.
    for candidate in candidates:
        normalized_candidate = _normalize_repo_doc_key(candidate)

        if normalized_candidate and normalized_candidate not in normalized_candidates:
            normalized_candidates.append(normalized_candidate)

    # Return the normalized folder names the docs resolver should look for.
    return normalized_candidates


def _resolve_repo_docs_root(docs_root: Path, repo_name: str) -> Optional[Path]:
    """Finds the docs subfolder that belongs to a selected repository."""

    repo_candidates = _repo_doc_name_candidates(repo_name)

    if not repo_candidates:
        # Return no repo-specific root when the caller did not select a repository.
        return None

    if _normalize_repo_doc_key(docs_root.name) in repo_candidates:
        # Support configurations that already point directly at one repo's docs folder.
        return docs_root

    if not docs_root.exists():
        # Avoid scanning a missing docs root.
        return None

    # Search one level under the configured docs directory for a repo-named folder.
    for child_path in docs_root.iterdir():
        if child_path.is_dir() and _normalize_repo_doc_key(child_path.name) in repo_candidates:
            # Return the selected repository docs folder.
            return child_path

    # Return no match when the selected repo has no local docs folder.
    return None


def _infer_document_repo_name(path: Path, docs_root: Path, explicit_repo_name: str = "") -> str:
    """Infers the repository name attached to a local docs record."""

    if explicit_repo_name:
        # Prefer the repository name that was already resolved by the caller.
        return explicit_repo_name

    try:
        # Look for docs stored under docs/<repo-name>/...
        relative_to_docs_root = path.relative_to(docs_root)
    except ValueError:
        # Root README files are shared docs and should not be tied to one repo.
        return ""

    if len(relative_to_docs_root.parts) > 1:
        # Treat the first docs-folder segment as the repository key.
        return relative_to_docs_root.parts[0]

    # Direct children of the docs root are shared docs.
    return ""


def _to_document_record(path: Path, docs_root: Path, repo_name: str = "") -> Dict[str, Any]:
    """Converts a markdown file into a document metadata record."""

    relative_path = path.relative_to(docs_root.parent).as_posix()
    document_record = {
        "id": relative_path.replace("/", "__"),
        "title": _read_markdown_title(path),
        "path": relative_path,
        "source": "repo_markdown",
        "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
    inferred_repo_name = _infer_document_repo_name(path, docs_root, repo_name)

    if inferred_repo_name:
        # Attach the repo key so the work intake page can filter docs by selection.
        document_record["repoName"] = inferred_repo_name

    # Return the normalized document metadata used by the intake and task detail views.
    return document_record


def list_repo_documents(settings: Settings, repo_name: str = "") -> List[Dict[str, Any]]:
    """Lists repo markdown documents used by the knowledge integration."""

    docs_root = Path(settings.docs_directory)
    documents: List[Dict[str, Any]] = []

    if not docs_root.exists():
        # Return no repo documents if the configured docs directory does not exist.
        return documents

    selected_docs_root = _resolve_repo_docs_root(docs_root, repo_name) if repo_name else None
    search_root = selected_docs_root or docs_root
    use_shared_top_level_docs = bool(repo_name and selected_docs_root is None)

    markdown_paths: List[Path] = []

    # Include the selected repo README or the root README for the shared catalog.
    repo_readme = search_root / "README.md" if selected_docs_root else docs_root.parent / "README.md"

    if repo_readme.exists() and not use_shared_top_level_docs:
        # Capture the README as part of the knowledge source list.
        markdown_paths.append(repo_readme)

    if use_shared_top_level_docs:
        # Use direct docs/*.md files as shared selected-repo context.
        candidate_paths = search_root.glob("*.md")
    else:
        # Include all markdown files from the selected docs directory.
        candidate_paths = search_root.rglob("*.md")

    for path in candidate_paths:
        if path.is_file():
            # Keep each markdown file for later normalization.
            markdown_paths.append(path)

    # Normalize and sort the markdown documents for consistent UI output.
    for path in sorted(set(markdown_paths)):
        documents.append(_to_document_record(path, docs_root, repo_name if repo_name else ""))

    # Return the list of repo knowledge sources.
    return documents
