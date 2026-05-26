"""Prompt builders for launching cloud agents from task context."""

from typing import Any, Dict, List


def _build_cursor_issue_block(issue: Dict[str, Any]) -> str:
    """Builds the issue-context section used inside the Cursor Cloud Agent prompt."""

    issue_lines: List[str] = [
        f"Ticket: {issue.get('ticket', 'Unknown ticket')}",
        f"Title: {issue.get('title', 'Untitled task')}",
        f"Status: {issue.get('status', 'Unknown')}",
        f"Priority: {issue.get('priority', 'Unknown')}",
        f"Provider: {issue.get('provider', 'unknown')}",
    ]
    description = str(issue.get("description", "")).strip()
    assignee = issue.get("assignee", {}) or {}
    assignee_name = str(assignee.get("name", "")).strip()

    if assignee_name:
        # Add the assignee when the originating issue included one.
        issue_lines.append(f"Assignee: {assignee_name}")

    if description:
        # Add the issue description when the originating issue included one.
        issue_lines.append(f"Description: {description}")

    # Return the issue block as a newline-delimited prompt section.
    return "\n".join(issue_lines)


def _build_cursor_docs_block(documents: List[Dict[str, Any]]) -> str:
    """Builds the attached-documents section used inside the Cursor Cloud Agent prompt."""

    if not documents:
        # Return a neutral docs section when the task was launched without attached docs.
        return "Attached docs:\n- No repo markdown documents were attached."

    document_lines = ["Attached docs:"]

    # Add each attached document path so the launched agent knows the intended grounding set.
    for document in documents:
        document_lines.append(f"- {document.get('path', document.get('title', 'Unknown document'))}")

    # Return the docs block as a newline-delimited prompt section.
    return "\n".join(document_lines)


def _build_cursor_prompt(
    run: Dict[str, Any],
    *,
    issue: Dict[str, Any],
    documents: List[Dict[str, Any]],
    repository: Dict[str, Any],
) -> str:
    """Builds the Cursor Cloud Agent prompt from the task, issue, and docs context."""

    task_prompt = str(run.get("_taskPrompt", run.get("summary", ""))).strip()
    acceptance_criteria = str(run.get("_acceptanceCriteria", "")).strip()
    repo_full_name = str(repository.get("fullName", repository.get("name", run.get("repo", "repository"))))
    issue_block = _build_cursor_issue_block(issue)
    docs_block = _build_cursor_docs_block(documents)
    prompt_sections = [
        f"You are launching work for the GitHub repository {repo_full_name}.",
        "Use the issue context below to scope the implementation and keep the work traceable to the originating issue-tracker ticket.",
        issue_block,
        f"Task summary:\n{task_prompt or run.get('summary', 'No task summary was provided.')}",
        f"Acceptance criteria:\n{acceptance_criteria or 'Use the issue details and repository context to determine completion.'}",
        docs_block,
        "Implementation instructions:",
        "- Make the requested code changes in the target repository.",
        "- Keep the branch and pull request aligned with the issue ticket.",
        "- Run the most relevant validation before handing off the work.",
        "- Summarize the changes and any follow-up reviewer notes in the final response.",
        "Include a raw git diff in the final message using:\n"
        "git diff origin/main...HEAD",
    ]

    # Return the composed task prompt that will be sent to the Cursor Cloud Agents API.
    return "\n\n".join(prompt_sections)
