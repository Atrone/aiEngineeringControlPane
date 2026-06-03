"""OpenAI-backed enrichment, classification, and dashboard suggestion helpers."""

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings
from app.provider_common import _request_json
from app.provider_docs import _resolve_repo_docs_root
from app.provider_github import _build_github_request_headers
from app import provider_openai_docs


class OpenAIEnrichmentError(Exception):
    """Captures a readable OpenAI enrichment API failure."""


# Human-readable field labels for the enrichment prompt.
_ENRICH_FIELD_LABELS: Dict[str, str] = {
    "title": "Task title",
    "prompt": "Implementation prompt",
    "acceptanceCriteria": "Acceptance criteria",
    "acceptance_criteria": "Acceptance criteria",
}

# Per-field guidance for the enrichment model output.
_ENRICH_FIELD_GUIDANCE: Dict[str, str] = {
    "title": (
        "Return a single concise task title (max ~12 words) that names the concrete outcome. "
        "Respond with the title only, no quotes, no trailing period."
    ),
    "prompt": (
        "Return a clear implementation prompt (3-7 sentences). Call out the repository surfaces that "
        "should change, reference the relevant docs, preserve any user intent already present, and keep "
        "guardrails the agent must respect. Plain prose, no markdown headings."
    ),
    "acceptance_criteria": (
        "Return 3-6 testable acceptance criteria as a markdown checklist (each line begins with '- [ ] '). "
        "Each item should be observable, scoped to this task, and aligned with repo policy and evidence expectations."
    ),
}


def _read_doc_excerpt(path: Path, max_chars: int) -> str:
    """Reads a truncated markdown excerpt used for enrichment grounding."""

    # Delegate file reading to the document-context helper module.
    return provider_openai_docs.read_doc_excerpt(path, max_chars)


def _fetch_github_json_body(url: str, headers: Mapping[str, str]) -> Any:
    """Executes a GitHub REST GET and returns the raw JSON body (dict or list).

    GitHub content listings return JSON arrays, so we cannot reuse the stricter
    ``_request_json`` helper that narrows the return type to ``Dict``. This
    wrapper keeps the low-level network behavior identical while permitting the
    parsed JSON body to be either an object or an array.
    """

    # Delegate raw GitHub JSON fetching to the document-context helper module.
    return provider_openai_docs.fetch_github_json_body(url, headers)


def _decode_github_contents_body(payload: Mapping[str, Any]) -> str:
    """Decodes the base64-encoded body returned by the GitHub contents API.

    The ``/contents`` endpoint returns each file as a JSON object with a base64
    encoded ``content`` field. This helper reverses that encoding into UTF-8
    text so callers can feed it directly into the OpenAI enrichment prompt.
    """

    # Delegate GitHub contents decoding to the document-context helper module.
    return provider_openai_docs.decode_github_contents_body(payload)


def _list_github_markdown_paths(
    base_api_url: str,
    headers: Mapping[str, str],
    *,
    directory_path: str,
    max_files: int,
    fetch_github_json_body: Optional[Any] = None,
) -> List[str]:
    """Returns markdown file paths under ``directory_path`` inside the repo.

    The helper walks the GitHub contents listing recursively so docs nested in
    subfolders are still discovered. The traversal stops once ``max_files``
    markdown files have been collected to keep the OpenAI context bounded.
    """

    # Prefer the caller-provided fetch helper when the docs module injects one.
    fetch_helper = fetch_github_json_body or _fetch_github_json_body

    # Delegate traversal while preserving this module's patchable fetch helper.
    return provider_openai_docs.list_github_markdown_paths(
        base_api_url,
        headers,
        directory_path=directory_path,
        max_files=max_files,
        fetch_github_json_body=fetch_helper,
    )


def _format_remote_doc_section(label: str, text: str, per_doc_chars: int) -> str:
    """Formats a single remote doc body into a labeled, bounded prompt section."""

    # Delegate remote doc formatting to the document-context helper module.
    return provider_openai_docs.format_remote_doc_section(label, text, per_doc_chars)


def _fetch_remote_repo_doc_context(
    settings: Settings,
    *,
    repo_name: str,
    per_doc_chars: int = 4000,
    max_docs: int = 8,
) -> str:
    """Builds an enrichment context blob from the selected remote GitHub repo.

    The intake "Enrich" buttons ground their suggestions in the repo docs, so
    this helper pulls the repository's README and any markdown files inside the
    repo's ``docs`` directory via the GitHub contents API. Fetches are guarded
    so transient GitHub errors simply yield an empty context instead of failing
    the enrichment call outright.
    """

    # Delegate remote context collection while preserving this module's patchable helpers.
    return provider_openai_docs.fetch_remote_repo_doc_context(
        settings,
        repo_name=repo_name,
        per_doc_chars=per_doc_chars,
        max_docs=max_docs,
        build_github_request_headers=_build_github_request_headers,
        fetch_github_json_body=_fetch_github_json_body,
        decode_github_contents_body=_decode_github_contents_body,
        list_github_markdown_paths=_list_github_markdown_paths,
        format_remote_doc_section=_format_remote_doc_section,
    )


def _collect_doc_context(
    settings: Settings,
    *,
    repo_name: str = "",
    per_doc_chars: int = 4000,
    max_docs: int = 8,
) -> str:
    """Builds a combined markdown context blob from repo docs."""

    # Delegate local context collection while preserving this module's patchable helpers.
    return provider_openai_docs.collect_doc_context(
        settings,
        repo_name=repo_name,
        per_doc_chars=per_doc_chars,
        max_docs=max_docs,
        resolve_repo_docs_root=_resolve_repo_docs_root,
        read_doc_excerpt=_read_doc_excerpt,
    )


def _normalize_enrichment_field(raw_field: str) -> str:
    """Normalizes the requested enrichment field name."""

    normalized_field = (raw_field or "").strip().lower().replace("-", "_")

    if normalized_field in ("acceptancecriteria", "acceptance_criteria", "criteria"):
        # Collapse the acceptance criteria aliases into the canonical snake_case form.
        return "acceptance_criteria"

    if normalized_field in ("title", "task_title"):
        # Collapse the title aliases into the canonical form.
        return "title"

    if normalized_field in ("prompt", "description"):
        # Collapse the prompt aliases into the canonical form.
        return "prompt"

    # Return the normalized field name so callers can validate it.
    return normalized_field


def _build_enrichment_messages(
    *,
    field: str,
    value: str,
    title: str,
    prompt: str,
    acceptance_criteria: str,
    repo_name: str,
    execution_mode: str,
    docs_context: str,
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for a work intake enrichment call."""

    field_label = _ENRICH_FIELD_LABELS.get(field, field)
    field_guidance = _ENRICH_FIELD_GUIDANCE.get(field, "Return a refined value for this field.")

    system_content = (
        "You refine work intake fields for the AI Engineering Control Pane. "
        "Ground every refinement in the repository's docs, the intake context, and the product's "
        "MVP workflow so the final text is ready for a tech-lead reviewer and an implementing agent. "
        "Do not invent integrations, repositories, or policies that are not supported by the docs. "
        "Preserve any user-written intent in the current value while improving clarity, specificity, and alignment."
    )

    intake_context_lines = [
        f"- Field to refine: {field_label}",
        f"- Repository: {repo_name or 'unspecified'}",
        f"- Execution mode: {execution_mode or 'implement'}",
        f"- Current task title: {title or '(empty)'}",
        f"- Current prompt: {prompt or '(empty)'}",
        f"- Current acceptance criteria: {acceptance_criteria or '(empty)'}",
    ]

    docs_section = docs_context.strip() or "(no repo docs were available)"

    user_content = (
        "Repo docs (use these as the source of truth for tone, scope, and terminology):\n"
        f"{docs_section}\n\n"
        "Current intake state:\n"
        + "\n".join(intake_context_lines)
        + "\n\n"
        f"Current value of {field_label}:\n"
        f"{value.strip() or '(empty)'}\n\n"
        f"Instructions: {field_guidance}\n"
        "Only return the refined value itself, with no preamble, explanation, or surrounding markdown fences."
    )

    # Return the chat-completion message list for OpenAI.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _build_uploaded_doc_context(
    uploaded_documents: List[Mapping[str, Any]],
    *,
    per_doc_chars: int = 4000,
    max_docs: int = 8,
) -> str:
    """Builds an enrichment context blob from documents uploaded in the intake UI."""

    context_sections: List[str] = []

    # Clamp the uploaded document list so large uploads stay within prompt budget.
    for uploaded_document in uploaded_documents[:max_docs]:
        # Read the uploaded file body and skip entries that do not carry any content.
        document_body = str(uploaded_document.get("content") or "").strip()

        if not document_body:
            # Ignore empty uploaded documents so the prompt stays focused.
            continue

        # Prefer the original path label so the model can cite the uploaded source cleanly.
        document_label = str(
            uploaded_document.get("path")
            or uploaded_document.get("title")
            or uploaded_document.get("id")
            or "uploaded-document"
        ).strip()

        context_sections.append(
            _format_remote_doc_section(document_label, document_body, per_doc_chars)
        )

    # Return the combined uploaded-doc context for the enrichment request.
    return "\n\n".join(context_sections)


def _extract_openai_message(response_payload: Dict[str, Any]) -> str:
    """Extracts the assistant text from an OpenAI chat completion response."""

    choices = response_payload.get("choices") or []

    if not choices:
        # Reject responses that do not include a usable assistant message.
        raise OpenAIEnrichmentError("OpenAI returned an empty choices list.")

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content")

    if isinstance(content, list):
        text_parts: List[str] = []

        # Handle the list-of-parts content shape used by newer OpenAI responses.
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])

        content = "".join(text_parts)

    if not isinstance(content, str) or not content.strip():
        # Reject responses that do not contain a non-empty string body.
        raise OpenAIEnrichmentError("OpenAI response did not contain any text content.")

    # Return the trimmed assistant message so callers can use it directly.
    return content.strip()


def enrich_intake_field(
    settings: Settings,
    *,
    field: str,
    value: str,
    title: str,
    prompt: str,
    acceptance_criteria: str,
    repo_name: str,
    execution_mode: str,
    uploaded_documents: Optional[List[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Refines a work intake field with OpenAI using repo doc context."""

    normalized_field = _normalize_enrichment_field(field)

    if normalized_field not in ("title", "prompt", "acceptance_criteria"):
        # Reject unsupported fields so the frontend does not silently misuse the route.
        raise OpenAIEnrichmentError(
            "Only the title, prompt, and acceptance criteria fields can be enriched."
        )

    if not settings.openai_api_key:
        # Reject enrichment requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable enrichment."
        )

    # Prefer the documents uploaded in the intake form so Enrich uses the exact
    # repo context the operator supplied for this task.
    docs_context = _build_uploaded_doc_context(list(uploaded_documents or []))

    if not docs_context:
        # Fall back to the selected local repo docs folder when no uploads were provided.
        docs_context = _collect_doc_context(settings, repo_name=repo_name)

    if not docs_context:
        # Fall back to the selected remote repository docs when no local docs were found.
        docs_context = _fetch_remote_repo_doc_context(settings, repo_name=repo_name)

    messages = _build_enrichment_messages(
        field=normalized_field,
        value=value,
        title=title,
        prompt=prompt,
        acceptance_criteria=acceptance_criteria,
        repo_name=repo_name,
        execution_mode=execution_mode,
        docs_context=docs_context,
    )

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can refine the intake field against repo docs.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the enrichment request (status {http_error.code}): {error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable enrichment error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for enrichment: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    refined_text = _extract_openai_message(response_payload)

    # Return the refined field value plus the metadata the UI may surface.
    return {
        "field": normalized_field,
        "value": refined_text,
        "model": settings.openai_model,
        "docsConsidered": bool(docs_context),
    }


def _build_issue_scope_classification_messages(
    *,
    issues: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for classifying intake issues by scope."""

    issue_lines: List[str] = []

    # Flatten each issue into a compact line the model can classify consistently.
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        issue_ticket = str(issue.get("ticket") or "").strip()
        issue_title = str(issue.get("title") or "").strip()
        issue_description = str(issue.get("description") or "").strip()
        issue_status = str(issue.get("status") or "").strip()
        issue_priority = str(issue.get("priority") or "").strip()
        issue_provider = str(issue.get("provider") or "").strip()

        issue_lines.append(
            f"- id: {issue_id or '(n/a)'} | ticket: {issue_ticket or '(n/a)'} | "
            f"title: {issue_title or '(n/a)'} | status: {issue_status or '(n/a)'} | "
            f"priority: {issue_priority or '(n/a)'} | provider: {issue_provider or '(n/a)'} | "
            f"description: {issue_description or '(n/a)'}"
        )

    system_content = (
        "You are classifying work intake issues for whether an autonomous coding agent is "
        "extremely likely to complete the task fully without needing major clarification. "
        "Classify each issue into exactly one bucket. "
        "Use 'well scoped' only when the task is concrete, implementation-ready, and likely "
        "to be completed end-to-end by a coding agent. "
        "Use 'poorly scoped' when the task is ambiguous, missing success criteria, likely to "
        "require discovery, cross-team coordination, product decisions, or substantial human clarification. "
        "When uncertain, classify the issue as poorly scoped. "
        "Return a JSON object only, with exactly these keys: "
        '"wellScopedIssueIds" (array of issue id strings) and "poorlyScopedIssueIds" '
        "(array of issue id strings). "
        "Every provided issue id must appear exactly once across the two arrays."
    )

    user_content = (
        "Classify these intake issues using the definitions above:\n"
        + ("\n".join(issue_lines) if issue_lines else "(no issues available)")
        + "\n\nReturn only JSON shaped like: "
        '{"wellScopedIssueIds": ["issue-1"], "poorlyScopedIssueIds": ["issue-2"]}'
    )

    # Return the chat-completion message list used by the issue scoping call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_issue_scope_classification_response(
    response_text: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Parses and validates the OpenAI response used for intake issue scoping."""

    # Strip markdown fences so JSON parsing survives minor formatting drift.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence before parsing the remaining JSON body.
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[:-3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each array.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON issue scoping payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for issue scoping."
        )

    raw_well_scoped_ids = parsed_payload.get("wellScopedIssueIds")
    raw_poorly_scoped_ids = parsed_payload.get("poorlyScopedIssueIds")

    if not isinstance(raw_well_scoped_ids, list) or not isinstance(raw_poorly_scoped_ids, list):
        # Reject responses that do not include both required arrays.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include both issue scoping arrays."
        )

    valid_issue_ids: List[str] = []

    # Preserve the intake issue order so the dropdown stays stable after regrouping.
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if issue_id:
            valid_issue_ids.append(issue_id)

    valid_issue_id_set = set(valid_issue_ids)
    assigned_issue_ids = set()
    well_scoped_issue_ids: List[str] = []
    poorly_scoped_issue_ids: List[str] = []

    # Normalize the model's well-scoped list, ignoring duplicates and unknown ids.
    for raw_issue_id in raw_well_scoped_ids:
        normalized_issue_id = str(raw_issue_id or "").strip()
        if normalized_issue_id in valid_issue_id_set and normalized_issue_id not in assigned_issue_ids:
            well_scoped_issue_ids.append(normalized_issue_id)
            assigned_issue_ids.add(normalized_issue_id)

    # Normalize the model's poorly-scoped list after the well-scoped assignments.
    for raw_issue_id in raw_poorly_scoped_ids:
        normalized_issue_id = str(raw_issue_id or "").strip()
        if normalized_issue_id in valid_issue_id_set and normalized_issue_id not in assigned_issue_ids:
            poorly_scoped_issue_ids.append(normalized_issue_id)
            assigned_issue_ids.add(normalized_issue_id)

    # Conservatively place any unassigned issue into poorly scoped.
    for issue_id in valid_issue_ids:
        if issue_id not in assigned_issue_ids:
            poorly_scoped_issue_ids.append(issue_id)
            assigned_issue_ids.add(issue_id)

    # Return the normalized scoping result for the intake route.
    return {
        "wellScopedIssueIds": well_scoped_issue_ids,
        "poorlyScopedIssueIds": poorly_scoped_issue_ids,
    }


def classify_intake_issues_by_scope(
    settings: Settings,
    *,
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to separate intake issues into well-scoped and poorly-scoped groups."""

    if not issues:
        # Reject calls when there are no issues available to classify.
        raise OpenAIEnrichmentError(
            "No integrated issues are available to classify."
        )

    if not settings.openai_api_key:
        # Reject scoping requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable issue scoping."
        )

    messages = _build_issue_scope_classification_messages(issues=issues)
    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can separate the intake issues into the two scope buckets.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the issue scoping request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable issue scoping error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for issue scoping: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    scoping_result = _parse_issue_scope_classification_response(raw_response_text, issues)

    # Return the normalized issue groups together with the model metadata.
    return {
        "wellScopedIssueIds": scoping_result["wellScopedIssueIds"],
        "poorlyScopedIssueIds": scoping_result["poorlyScopedIssueIds"],
        "model": settings.openai_model,
        "issueCount": len(issues),
    }


def _build_repo_identification_messages(
    *,
    issue: Dict[str, Any],
    repositories: List[Dict[str, Any]],
    docs_context: str,
) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for identifying the repo that fits an issue.

    The model is instructed to return a strict JSON object containing the chosen
    repository name, a confidence score, and a short rationale so the backend
    can parse it deterministically.
    """

    # Build a compact, LLM-friendly description of each candidate repository.
    repo_lines: List[str] = []
    for repository in repositories:
        repo_name = str(repository.get("name") or "").strip()
        full_name = str(repository.get("fullName") or repository.get("full_name") or "").strip()
        default_branch = str(repository.get("defaultBranch") or repository.get("default_branch") or "").strip()
        provider = str(repository.get("provider") or "").strip()
        url = str(repository.get("url") or "").strip()

        # Collapse each candidate into a single line the model can reason over.
        repo_lines.append(
            f"- name: {repo_name} | fullName: {full_name or '(n/a)'} | "
            f"defaultBranch: {default_branch or '(n/a)'} | provider: {provider or '(n/a)'} | url: {url or '(n/a)'}"
        )

    # Gather the descriptive fields from the issue to ground the match.
    issue_ticket = str(issue.get("ticket") or "").strip()
    issue_title = str(issue.get("title") or "").strip()
    issue_description = str(issue.get("description") or "").strip()
    issue_status = str(issue.get("status") or "").strip()
    issue_priority = str(issue.get("priority") or "").strip()

    system_content = (
        "You are the repository router for the AI Engineering Control Pane. "
        "Given a work issue and the catalog of integrated repositories, pick the single "
        "repository that best fits the work described in the issue. "
        "Only choose from the provided repositories. Do not invent repositories. "
        "Respond with a JSON object only, no prose, no markdown fences. "
        "The JSON object must have exactly these keys: "
        '"repoName" (string, must match one of the candidate names exactly), '
        '"confidence" (number between 0 and 1), '
        '"reasoning" (short string explaining the choice).'
    )

    docs_section = docs_context.strip() or "(no repo docs were available)"

    user_content = (
        "Issue to route:\n"
        f"- Ticket: {issue_ticket or '(n/a)'}\n"
        f"- Title: {issue_title or '(n/a)'}\n"
        f"- Status: {issue_status or '(n/a)'}\n"
        f"- Priority: {issue_priority or '(n/a)'}\n"
        f"- Description: {issue_description or '(n/a)'}\n\n"
        "Candidate repositories (choose exactly one 'name' value from this list):\n"
        + ("\n".join(repo_lines) if repo_lines else "(no repositories available)")
        + "\n\nRepo docs (use these to disambiguate which repo owns the work):\n"
        f"{docs_section}\n\n"
        "Return only a JSON object shaped like: "
        '{"repoName": "<exact name from list>", "confidence": 0.0-1.0, "reasoning": "<short explanation>"}'
    )

    # Return the chat-completion message list used by the repo identification call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_repo_identification_response(
    response_text: str,
    repositories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Parses the OpenAI response text into a validated repo identification result.

    Rejects responses that cannot be parsed as JSON or that do not reference
    a repository that exists in the provided catalog.
    """

    # Strip common markdown code fences the model sometimes adds despite instructions.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence (optionally followed by a language tag).
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[: -3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each field.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON repository identification payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for repository identification."
        )

    suggested_repo_name = str(parsed_payload.get("repoName") or "").strip()
    if not suggested_repo_name:
        # Reject responses missing the required repository name field.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include a repoName value."
        )

    # Match the suggested name against the provided catalog (case-insensitive fallback).
    matched_repository: Optional[Dict[str, Any]] = None
    for repository in repositories:
        candidate_name = str(repository.get("name") or "").strip()
        if candidate_name == suggested_repo_name:
            matched_repository = repository
            break
    if matched_repository is None:
        # Retry with case-insensitive matching so capitalization quirks do not fail the match.
        lowered_suggestion = suggested_repo_name.lower()
        for repository in repositories:
            candidate_name = str(repository.get("name") or "").strip().lower()
            if candidate_name == lowered_suggestion:
                matched_repository = repository
                break

    if matched_repository is None:
        # Reject suggestions that do not correspond to a known repository.
        raise OpenAIEnrichmentError(
            f"OpenAI suggested '{suggested_repo_name}' which is not in the integrated repository catalog."
        )

    raw_confidence = parsed_payload.get("confidence")
    confidence_value: Optional[float] = None
    if isinstance(raw_confidence, (int, float)):
        # Clamp the confidence value to the [0, 1] range expected by the UI.
        confidence_value = max(0.0, min(1.0, float(raw_confidence)))

    reasoning_text = str(parsed_payload.get("reasoning") or "").strip()

    # Return the validated identification result for the route handler.
    return {
        "repoName": str(matched_repository.get("name") or "").strip(),
        "repoFullName": str(matched_repository.get("fullName") or matched_repository.get("full_name") or "").strip(),
        "confidence": confidence_value,
        "reasoning": reasoning_text,
    }


def identify_repository_for_issue(
    settings: Settings,
    *,
    issue: Dict[str, Any],
    repositories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to pick the repository that best fits a work intake issue.

    Uses the integrated repository catalog and the repo docs context as grounding
    so the model can only select from known repositories. Returns a structured
    payload with the chosen repo name, confidence, reasoning, and model metadata.
    """

    if not repositories:
        # Reject calls when no repositories exist to choose from.
        raise OpenAIEnrichmentError(
            "No integrated repositories are available to identify against."
        )

    if not issue:
        # Reject calls made without an issue to match.
        raise OpenAIEnrichmentError(
            "An issue must be selected before identifying a repository."
        )

    if not settings.openai_api_key:
        # Reject identification requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable repository identification."
        )

    docs_context = _collect_doc_context(settings)
    messages = _build_repo_identification_messages(
        issue=issue,
        repositories=repositories,
        docs_context=docs_context,
    )

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can pick the best-fit repository for the issue.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the repository identification request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable identification error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for repository identification: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    identification_result = _parse_repo_identification_response(raw_response_text, repositories)

    # Return the chosen repository plus the model metadata the UI may surface.
    return {
        "repoName": identification_result["repoName"],
        "repoFullName": identification_result["repoFullName"],
        "confidence": identification_result["confidence"],
        "reasoning": identification_result["reasoning"],
        "model": settings.openai_model,
        "docsConsidered": bool(docs_context),
    }


def _summarize_run_for_suggestions(run: Dict[str, Any]) -> str:
    """Builds a compact single-run summary line for the suggestions prompt."""

    # Extract the descriptive fields the LLM needs to reason about the run.
    ticket = str(run.get("ticket") or run.get("id") or "").strip()
    title = str(run.get("title") or "").strip()
    status = str(run.get("status") or "").strip()
    risk = str(run.get("risk") or "").strip()
    repo = str(run.get("repo") or "").strip()
    owner = str(run.get("owner") or "").strip()
    agent = str(run.get("agent") or "").strip()
    runtime = str(run.get("runtime") or "").strip()
    current_step = str(run.get("currentStep") or "").strip()

    # Flatten the blocker list so the LLM sees each reason verbatim.
    blockers_raw = run.get("blockers") or []
    blocker_texts: List[str] = []
    for blocker in blockers_raw:
        blocker_text = str(blocker or "").strip()
        if blocker_text:
            blocker_texts.append(blocker_text)

    blockers_text = "; ".join(blocker_texts) if blocker_texts else "none"

    # Pull the PR status and approval context so suggestions can reference merge state.
    pull_request = run.get("pullRequest") or {}
    pr_state = str(pull_request.get("state") or pull_request.get("status") or "").strip()
    pr_merged = bool(pull_request.get("merged", False))
    pr_approved = bool(pull_request.get("approved", False))

    # Compose a single line that keeps the prompt compact but informative.
    return (
        f"- {ticket or '(no ticket)'} | title: {title or '(untitled)'} | status: {status or '(unknown)'} | "
        f"risk: {risk or '(unknown)'} | repo: {repo or '(unknown)'} | owner: {owner or '(unknown)'} | "
        f"agent: {agent or '(unknown)'} | runtime: {runtime or '00:00'} | step: {current_step or '(none)'} | "
        f"blockers: {blockers_text} | pr_state: {pr_state or '(none)'} | pr_approved: {pr_approved} | pr_merged: {pr_merged}"
    )


def _build_suggested_actions_messages(runs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages that request the suggested next actions list."""

    # Convert each visible run into a compact line for the prompt.
    run_lines: List[str] = []
    for run in runs:
        run_lines.append(_summarize_run_for_suggestions(run))

    runs_section = "\n".join(run_lines) if run_lines else "(no runs are currently visible on the dashboard)"

    system_content = (
        "You are the operations copilot for the AI Engineering Control Pane dashboard. "
        "Given a snapshot of the runs currently displayed in the 'Active and recent runs' panel, "
        "produce a short, prioritized list of suggested next actions for the operator. "
        "Only reason about the runs provided; do not invent integrations, repositories, or policies. "
        "Prefer actions that unblock stalled runs, clear the review queue, or confirm merges. "
        "Respond with a JSON object only, no prose, no markdown fences. "
        "The JSON object must have exactly one key: \"suggestedActions\" whose value is a JSON array of "
        "1 to 5 short sentences (each sentence ends with a period). "
        "Each sentence must be actionable, under 140 characters, and clearly tied to the visible runs."
    )

    user_content = (
        "Visible runs in the dashboard 'Active and recent runs' container:\n"
        f"{runs_section}\n\n"
        "Return JSON shaped like: {\"suggestedActions\": [\"Sentence 1.\", \"Sentence 2.\"]}."
    )

    # Return the chat-completion message list used by the suggestions call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_suggested_actions_response(response_text: str) -> List[str]:
    """Parses the OpenAI response text into a validated suggestions list."""

    # Strip common markdown code fences the model sometimes adds despite instructions.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence (optionally followed by a language tag).
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[: -3].rstrip()

    try:
        # Parse the cleaned response body as JSON so we can validate each field.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON suggestions payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for suggested actions."
        )

    raw_actions = parsed_payload.get("suggestedActions")

    if not isinstance(raw_actions, list):
        # Reject responses that do not include the expected array field.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include a suggestedActions array."
        )

    suggested_actions: List[str] = []

    # Normalize each entry into a clean sentence, dropping empties and non-strings.
    for raw_action in raw_actions:
        if not isinstance(raw_action, str):
            continue

        action_text = raw_action.strip()

        if not action_text:
            continue

        # Clamp each suggestion to a sensible length for the dashboard rail.
        if len(action_text) > 240:
            action_text = action_text[:237].rstrip() + "..."

        suggested_actions.append(action_text)

    # Clamp the overall list so the dashboard rail stays scannable.
    return suggested_actions[:5]


def _build_review_effort_label(effort_minutes: int) -> str:
    """Builds a stable review-effort bucket label from an OpenAI minute guess."""

    if effort_minutes <= 10:
        # Keep tiny PRs visibly distinct from normal review work.
        return "Quick review"

    if effort_minutes <= 30:
        # Treat most straightforward PRs as standard review work.
        return "Moderate review"

    if effort_minutes <= 60:
        # Call out PRs that likely need a deeper pass.
        return "Deep review"

    # Mark very large or risky PRs as extended review work.
    return "Extended review"


def _summarize_run_for_review_effort(run: Dict[str, Any]) -> str:
    """Builds a compact PR-summary line for OpenAI review-effort estimation."""

    # Pull run identity fields so the model can return estimates by stable run ID.
    run_id = str(run.get("id") or "").strip()
    ticket = str(run.get("ticket") or run_id).strip()
    title = str(run.get("title") or "").strip()
    status = str(run.get("status") or "").strip()

    # Use the PR title and body because the requested signal is the PR summary.
    pull_request = run.get("pullRequest") or {}
    pr_title = str(pull_request.get("title") or "").strip()
    pr_body = str(pull_request.get("body") or run.get("summary") or "").strip()

    if len(pr_body) > 1600:
        # Cap very large descriptions so one PR cannot dominate the prompt budget.
        pr_body = pr_body[:1597].rstrip() + "..."

    # Compose one machine-readable line while preserving the PR body text for judgment.
    return (
        f"- runId: {run_id or '(missing)'} | ticket: {ticket or '(n/a)'} | "
        f"title: {title or '(untitled)'} | status: {status or '(unknown)'} | "
        f"prTitle: {pr_title or '(n/a)'} | prSummary: {pr_body or '(no PR summary available)'}"
    )


def _build_review_effort_messages(runs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Builds the OpenAI chat messages for PR-summary review-effort guesses."""

    # Flatten each run into one prompt line so the model can score the batch consistently.
    run_lines: List[str] = []
    for run in runs:
        run_lines.append(_summarize_run_for_review_effort(run))

    runs_section = "\n".join(run_lines) if run_lines else "(no runs are currently visible in the lobby)"
    system_content = (
        "You estimate human pull-request review effort for the AI Engineering Control Pane. "
        "Base each estimate only on the provided PR title and PR summary/body. "
        "Return a JSON object only, no prose, no markdown fences. "
        "The JSON object must have exactly one key: \"reviewEfforts\" whose value is an array. "
        "Each array item must have exactly these keys: "
        '"runId" (string matching one provided runId), '
        '"effortMinutes" (integer from 1 to 180), '
        '"confidence" (number between 0 and 1), '
        '"rationale" (short sentence under 120 characters). '
        "Use lower estimates for narrow, well-described changes and higher estimates for broad, risky, "
        "ambiguous, cross-cutting, migration, auth, data, or infrastructure changes."
    )
    user_content = (
        "Visible lobby runs to estimate from their PR summaries:\n"
        f"{runs_section}\n\n"
        'Return JSON shaped like: {"reviewEfforts":[{"runId":"run-1","effortMinutes":20,"confidence":0.7,"rationale":"Small UI PR with clear scope."}]}'
    )

    # Return the chat-completion message list used by the review-effort call.
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_review_effort_response(response_text: str, runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parses OpenAI review-effort guesses into normalized run-scoped estimates."""

    # Strip common markdown fences so the JSON parser survives minor formatting drift.
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```"):
        # Drop the opening fence before parsing the remaining JSON body.
        cleaned_text = cleaned_text.split("\n", 1)[1] if "\n" in cleaned_text else cleaned_text[3:]
    if cleaned_text.endswith("```"):
        # Drop the closing fence so the remaining body is valid JSON.
        cleaned_text = cleaned_text[: -3].rstrip()

    try:
        # Parse the cleaned response body as JSON so each estimate can be validated.
        parsed_payload = json.loads(cleaned_text)
    except json.JSONDecodeError as decode_error:
        # Reject non-JSON responses with a readable error for the UI.
        raise OpenAIEnrichmentError(
            "OpenAI did not return a JSON review-effort payload."
        ) from decode_error

    if not isinstance(parsed_payload, dict):
        # Reject JSON arrays or scalars so only well-formed objects proceed.
        raise OpenAIEnrichmentError(
            "OpenAI returned an unexpected shape for review effort."
        )

    raw_estimates = parsed_payload.get("reviewEfforts")
    if not isinstance(raw_estimates, list):
        # Require the expected array so callers can rely on a stable response shape.
        raise OpenAIEnrichmentError(
            "OpenAI response did not include a reviewEfforts array."
        )

    valid_run_ids: List[str] = []
    for run in runs:
        run_id = str(run.get("id") or "").strip()
        if run_id:
            # Preserve the incoming run order for the normalized response.
            valid_run_ids.append(run_id)

    valid_run_id_set = set(valid_run_ids)
    estimates_by_run_id: Dict[str, Dict[str, Any]] = {}

    # Normalize each model estimate while ignoring duplicates and unknown run IDs.
    for raw_estimate in raw_estimates:
        if not isinstance(raw_estimate, dict):
            continue

        run_id = str(raw_estimate.get("runId") or "").strip()
        if run_id not in valid_run_id_set or run_id in estimates_by_run_id:
            # Skip estimates that do not belong to the requested lobby runs.
            continue

        raw_minutes = raw_estimate.get("effortMinutes")
        if not isinstance(raw_minutes, (int, float)):
            # Skip entries that do not include the required numeric effort guess.
            continue

        effort_minutes = max(1, min(180, int(round(float(raw_minutes)))))
        raw_confidence = raw_estimate.get("confidence")
        confidence: Optional[float] = None
        if isinstance(raw_confidence, (int, float)):
            # Clamp confidence to the frontend's expected [0, 1] display range.
            confidence = max(0.0, min(1.0, float(raw_confidence)))

        rationale = str(raw_estimate.get("rationale") or "").strip()
        if len(rationale) > 160:
            # Keep rationale copy short enough for channel hover text.
            rationale = rationale[:157].rstrip() + "..."

        estimates_by_run_id[run_id] = {
            "runId": run_id,
            "effortMinutes": effort_minutes,
            "label": _build_review_effort_label(effort_minutes),
            "confidence": confidence,
            "rationale": rationale or "Estimated from the PR summary.",
            "source": "openai",
        }

    # Return estimates in the same order as the requested lobby runs.
    return [estimates_by_run_id[run_id] for run_id in valid_run_ids if run_id in estimates_by_run_id]


def estimate_review_effort_for_runs(
    settings: Settings,
    *,
    runs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to estimate human review effort for visible lobby runs."""

    if not runs:
        # Return an empty successful payload when the selected lobby has no runs.
        return {"reviewEfforts": [], "model": settings.openai_model, "runCount": 0}

    if not settings.openai_api_key:
        # Reject review-effort requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable review-effort estimates."
        )

    messages = _build_review_effort_messages(runs)
    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can estimate review effort from PR summaries.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the review-effort request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable review-effort error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for review effort: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    review_efforts = _parse_review_effort_response(raw_response_text, runs)

    # Return the normalized estimates plus model metadata the UI may surface.
    return {
        "reviewEfforts": review_efforts,
        "model": settings.openai_model,
        "runCount": len(runs),
    }


def suggest_next_actions_for_runs(
    settings: Settings,
    *,
    runs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Asks OpenAI to produce suggested next actions for the visible dashboard runs.

    The caller should pass the runs currently shown in the dashboard's
    'Active and recent runs' container so the suggestions stay consistent with
    what the operator is looking at.
    """

    if not settings.openai_api_key:
        # Reject suggestion requests when the OpenAI key is not configured.
        raise OpenAIEnrichmentError(
            "OpenAI is not configured for this environment. Set OPENAI_API_KEY to enable suggested actions."
        )

    messages = _build_suggested_actions_messages(runs)

    request_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    request_payload: Dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.openai_base_url}/chat/completions"

    try:
        # Call OpenAI so the assistant can propose next actions for the visible runs.
        response_payload = _request_json(
            url,
            method="POST",
            headers=request_headers,
            payload=request_payload,
        )
    except HTTPError as http_error:
        # Surface upstream rejections with the HTTP status so the UI can display them.
        try:
            error_body = http_error.read().decode("utf-8", errors="ignore")
        except Exception:
            error_body = ""

        raise OpenAIEnrichmentError(
            f"OpenAI rejected the suggested actions request (status {http_error.code}): "
            f"{error_body.strip() or http_error.reason}"
        ) from http_error
    except URLError as url_error:
        # Translate transport-level failures into a readable suggestions error.
        raise OpenAIEnrichmentError(
            f"Could not reach OpenAI for suggested actions: {url_error.reason}"
        ) from url_error
    except json.JSONDecodeError as decode_error:
        # Reject malformed OpenAI responses with a clear error message.
        raise OpenAIEnrichmentError(
            "OpenAI returned a response that could not be parsed as JSON."
        ) from decode_error

    raw_response_text = _extract_openai_message(response_payload)
    suggested_actions = _parse_suggested_actions_response(raw_response_text)

    # Return the suggestions plus the model metadata the UI may surface.
    return {
        "suggestedActions": suggested_actions,
        "model": settings.openai_model,
        "runCount": len(runs),
    }
