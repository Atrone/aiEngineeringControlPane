"""Document-context helpers for OpenAI-backed provider prompts."""

import base64
import json
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


FetchGithubJson = Callable[[str, Mapping[str, str]], Any]
DecodeGithubContents = Callable[[Mapping[str, Any]], str]
FormatRemoteDocSection = Callable[[str, str, int], str]
ReadDocExcerpt = Callable[[Path, int], str]
ResolveRepoDocsRoot = Callable[[Path, str], Optional[Path]]


def read_doc_excerpt(path: Path, max_chars: int) -> str:
    """Reads a truncated markdown excerpt used for enrichment grounding."""

    try:
        # Read the markdown document from disk so it can ground the enrichment prompt.
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        # Skip documents that cannot be read from disk.
        return ""

    if len(text) <= max_chars:
        # Return the full document when it already fits in the context budget.
        return text

    # Truncate long documents so the combined prompt stays within OpenAI context limits.
    return text[:max_chars].rstrip() + "\n...[truncated]..."


def fetch_github_json_body(url: str, headers: Mapping[str, str]) -> Any:
    """Executes a GitHub REST GET and returns the raw JSON body."""

    # Copy the caller's headers so GitHub's accept header takes precedence over defaults.
    request_headers = dict(headers)
    request = Request(url, headers=request_headers, method="GET")

    with urlopen(request, timeout=12) as response:
        # Decode the GitHub response body into native Python data.
        return json.loads(response.read().decode("utf-8"))


def decode_github_contents_body(payload: Mapping[str, Any]) -> str:
    """Decodes the base64-encoded body returned by the GitHub contents API."""

    # Read the raw base64 payload and encoding label GitHub advertises.
    encoded_content = str(payload.get("content") or "")
    encoding_label = str(payload.get("encoding") or "").lower()

    if not encoded_content or encoding_label != "base64":
        # Bail out when the response does not carry a base64 body we can decode.
        return ""

    try:
        # Decode the base64 blob back into markdown/plaintext for the prompt.
        return base64.b64decode(encoded_content).decode("utf-8", errors="ignore")
    except (ValueError, TypeError):
        # Swallow malformed content so callers can simply skip this document.
        return ""


def list_github_markdown_paths(
    base_api_url: str,
    headers: Mapping[str, str],
    *,
    directory_path: str,
    max_files: int,
    fetch_github_json_body: FetchGithubJson,
) -> List[str]:
    """Returns markdown file paths under a GitHub repository directory."""

    markdown_paths: List[str] = []

    if max_files <= 0 or not directory_path:
        # Short-circuit when the caller has no remaining budget or no directory.
        return markdown_paths

    try:
        # Ask GitHub for the contents of the requested directory path.
        listing_payload = fetch_github_json_body(f"{base_api_url}/contents/{directory_path}", headers)
    except (HTTPError, URLError, json.JSONDecodeError):
        # Skip missing or unreachable directories so the enrichment can proceed.
        return markdown_paths

    if not isinstance(listing_payload, list):
        # Treat a single GitHub contents object as a terminal markdown candidate.
        if isinstance(listing_payload, dict):
            entry_path = str(listing_payload.get("path") or "").strip()
            entry_type = str(listing_payload.get("type") or "")

            if entry_type == "file" and entry_path.lower().endswith(".md"):
                # Capture the single-file match inside the remaining budget.
                markdown_paths.append(entry_path)

        return markdown_paths[:max_files]

    for entry in listing_payload:
        if len(markdown_paths) >= max_files:
            # Stop once we have enough markdown files to satisfy the budget.
            break

        if not isinstance(entry, dict):
            # Skip malformed entries so a single bad row cannot poison the walk.
            continue

        entry_type = str(entry.get("type") or "")
        entry_path = str(entry.get("path") or "").strip()

        if not entry_path:
            # Ignore entries lacking a usable path.
            continue

        if entry_type == "file" and entry_path.lower().endswith(".md"):
            # Record the markdown file so its body can be fetched later.
            markdown_paths.append(entry_path)
        elif entry_type == "dir":
            # Recurse into subdirectories using the remaining file budget.
            nested_paths = list_github_markdown_paths(
                base_api_url,
                headers,
                directory_path=entry_path,
                max_files=max_files - len(markdown_paths),
                fetch_github_json_body=fetch_github_json_body,
            )
            markdown_paths.extend(nested_paths)

    # Clamp the aggregated list so nested recursion cannot exceed the budget.
    return markdown_paths[:max_files]


def format_remote_doc_section(label: str, text: str, per_doc_chars: int) -> str:
    """Formats a single remote doc body into a labeled, bounded prompt section."""

    if len(text) > per_doc_chars:
        # Truncate long docs so the combined prompt stays within OpenAI context limits.
        excerpt_text = text[:per_doc_chars].rstrip() + "\n...[truncated]..."
    else:
        # Keep short docs unchanged.
        excerpt_text = text

    # Return a markdown-header-labeled excerpt matching the local docs formatting.
    return f"### {label}\n{excerpt_text}"


def fetch_remote_repo_doc_context(
    settings: Settings,
    *,
    repo_name: str,
    per_doc_chars: int,
    max_docs: int,
    build_github_request_headers: Callable[[Settings], Mapping[str, str]],
    fetch_github_json_body: FetchGithubJson,
    decode_github_contents_body: DecodeGithubContents,
    list_github_markdown_paths: Callable[..., List[str]],
    format_remote_doc_section: FormatRemoteDocSection,
) -> str:
    """Builds an enrichment context blob from the selected remote GitHub repo."""

    repo_slug = (repo_name or "").strip()

    if not repo_slug or not settings.github_owner:
        # Skip remote lookups when the repo or owner are not configured yet.
        return ""

    # Reuse the shared GitHub headers so the token is attached when present.
    headers = build_github_request_headers(settings)
    base_api_url = f"https://api.github.com/repos/{settings.github_owner}/{repo_slug}"
    collected_sections: List[str] = []

    try:
        # Always include the repo README so the model anchors on the top-level pitch.
        readme_payload = fetch_github_json_body(f"{base_api_url}/readme", headers)
    except (HTTPError, URLError, json.JSONDecodeError):
        # Skip README when GitHub is unreachable or the repo has no README.
        readme_payload = None

    if isinstance(readme_payload, dict):
        # Decode and include the README when GitHub returns a readable body.
        readme_body = decode_github_contents_body(readme_payload)

        if readme_body.strip():
            # Label the README with its repo-scoped path for traceability.
            readme_label = f"{repo_slug}/{str(readme_payload.get('path') or 'README.md')}"
            collected_sections.append(format_remote_doc_section(readme_label, readme_body, per_doc_chars))

    remaining_budget = max(0, max_docs - len(collected_sections))

    if remaining_budget > 0:
        # Discover bounded markdown docs under the repo docs folder.
        markdown_paths = list_github_markdown_paths(
            base_api_url,
            headers,
            directory_path="docs",
            max_files=remaining_budget,
            fetch_github_json_body=fetch_github_json_body,
        )

        for markdown_path in markdown_paths:
            if len(collected_sections) >= max_docs:
                # Respect the hard cap even if the listing returned extra files.
                break

            try:
                # Fetch the individual file so we get the base64 body GitHub returns.
                file_payload = fetch_github_json_body(f"{base_api_url}/contents/{markdown_path}", headers)
            except (HTTPError, URLError, json.JSONDecodeError):
                # Skip any file we cannot read so one failure cannot block the rest.
                continue

            if not isinstance(file_payload, dict):
                # Guard against unexpected response shapes returned by GitHub.
                continue

            file_body = decode_github_contents_body(file_payload)

            if not file_body.strip():
                # Drop empty documents so they do not bloat the enrichment prompt.
                continue

            collected_sections.append(format_remote_doc_section(f"{repo_slug}/{markdown_path}", file_body, per_doc_chars))

    # Return the combined context so the enrichment prompt can embed it directly.
    return "\n\n".join(collected_sections)


def collect_doc_context(
    settings: Settings,
    *,
    repo_name: str,
    per_doc_chars: int,
    max_docs: int,
    resolve_repo_docs_root: ResolveRepoDocsRoot,
    read_doc_excerpt: ReadDocExcerpt,
) -> str:
    """Builds a combined markdown context blob from local repo docs."""

    docs_root = Path(settings.docs_directory)
    context_parts: List[str] = []

    if not docs_root.exists():
        # Skip context collection when the docs directory is missing.
        return ""

    markdown_paths: List[Path] = []
    selected_docs_root = resolve_repo_docs_root(docs_root, repo_name) if repo_name else None
    search_root = selected_docs_root or docs_root

    if repo_name and selected_docs_root is None:
        # Avoid grounding a selected repo on shared or unrelated docs.
        return ""

    repo_readme = search_root / "README.md" if selected_docs_root else docs_root.parent / "README.md"

    if repo_readme.exists():
        # Always anchor enrichment context on the repo README when available.
        markdown_paths.append(repo_readme)

    for candidate_path in sorted(search_root.rglob("*.md")):
        if candidate_path.is_file():
            # Pull every markdown file from the selected docs directory for grounding.
            markdown_paths.append(candidate_path)

    # De-duplicate while preserving README-first ordering for consistent grounding.
    markdown_paths = list(dict.fromkeys(markdown_paths))[:max_docs]

    for markdown_path in markdown_paths:
        # Read each local markdown excerpt through the caller-provided helper.
        excerpt = read_doc_excerpt(markdown_path, per_doc_chars)

        if not excerpt.strip():
            # Skip empty or unreadable docs so they do not bloat the prompt.
            continue

        try:
            # Prefer a stable label relative to the docs parent.
            relative_label = markdown_path.relative_to(docs_root.parent).as_posix()
        except ValueError:
            # Fall back to the filename when the doc lives outside the docs parent.
            relative_label = markdown_path.name

        context_parts.append(f"### {relative_label}\n{excerpt}")

    # Return a single combined context string suitable for the enrichment prompt.
    return "\n\n".join(context_parts)
