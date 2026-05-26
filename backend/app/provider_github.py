"""GitHub repository and pull-request provider adapter."""

import json
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError

from app.config import Settings
from app.provider_common import _request_json

# Pattern matching GitHub pull-request URLs so we can extract owner/repo/number.
_GITHUB_PR_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


def list_github_repositories(settings: Settings) -> List[Dict[str, Any]]:
    """Lists GitHub repositories from live configuration or returns an empty list."""

    repositories: List[Dict[str, Any]] = []

    if not settings.github_owner or not settings.github_repositories:
        # Return no live repository records when the GitHub config is incomplete.
        return repositories

    headers = {"User-Agent": "ai-control-pane"}

    if settings.github_token:
        # Attach the GitHub token when available for higher rate limits and private repo access.
        headers["Authorization"] = f"Bearer {settings.github_token}"

    for repository_name in settings.github_repositories:
        url = f"https://api.github.com/repos/{settings.github_owner}/{repository_name}"

        try:
            response = _request_json(url, headers=headers)
        except (HTTPError, URLError, json.JSONDecodeError):
            # Skip repositories that cannot be fetched from GitHub.
            continue

        # Normalize the GitHub repository payload into the app's shared shape.
        repositories.append(
            {
                "id": str(response.get("id", repository_name)),
                "name": response.get("name", repository_name),
                "fullName": response.get("full_name", f"{settings.github_owner}/{repository_name}"),
                "defaultBranch": response.get("default_branch", "main"),
                "private": bool(response.get("private", False)),
                "provider": "github",
                "url": response.get("html_url", ""),
            }
        )

    # Return the normalized GitHub repository list.
    return repositories


def parse_github_pull_request_url(pull_request_url: str) -> Optional[Dict[str, str]]:
    """Parses a GitHub pull-request URL into owner/repo/number fragments.

    Returns None when the URL does not match a real GitHub PR URL so callers can
    safely fall back to the simulated detection path used in the demo app.
    """

    # Guard against empty or non-string inputs before running the regex.
    if not pull_request_url or not isinstance(pull_request_url, str):
        # Reject empty or invalid PR URLs before attempting to match the pattern.
        return None

    match_result = _GITHUB_PR_URL_PATTERN.match(pull_request_url.strip())

    if not match_result:
        # Return None when the URL is not a real github.com pull-request link.
        return None

    # Return the parsed components for a later GitHub REST API lookup.
    return {
        "owner": match_result.group("owner"),
        "repo": match_result.group("repo"),
        "number": match_result.group("number"),
    }


def _build_github_request_headers(settings: Settings) -> Dict[str, str]:
    """Builds the shared headers used for GitHub REST API calls."""

    request_headers: Dict[str, str] = {
        "User-Agent": "ai-control-pane",
        "Accept": "application/vnd.github+json",
    }

    if settings.github_token:
        # Attach the GitHub token so private-repo and rate-limit-safe calls can succeed.
        request_headers["Authorization"] = f"Bearer {settings.github_token}"

    # Return the shared GitHub REST headers used across PR status lookups.
    return request_headers


def _fetch_github_pull_request_payload(
    settings: Settings,
    owner: str,
    repo: str,
    number: str,
) -> Optional[Dict[str, Any]]:
    """Fetches the raw GitHub pull-request payload for the requested PR."""

    pull_request_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"

    try:
        # Read the GitHub PR record so we can detect state, reviews, and merges.
        return _request_json(pull_request_url, headers=_build_github_request_headers(settings))
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return None when the PR metadata cannot be read from GitHub.
        return None


def _fetch_github_pull_request_reviews(
    settings: Settings,
    owner: str,
    repo: str,
    number: str,
) -> List[Dict[str, Any]]:
    """Fetches the GitHub review list for the requested PR."""

    reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews"

    try:
        response_payload = _request_json(reviews_url, headers=_build_github_request_headers(settings))
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return no reviews when the GitHub review list cannot be fetched.
        return []

    if isinstance(response_payload, list):
        # Return the review list directly when GitHub replied with a JSON array.
        return [review for review in response_payload if isinstance(review, dict)]

    # Return no reviews when the response shape is not the expected array.
    return []


def _fetch_github_pull_request_comments(
    settings: Settings,
    owner: str,
    repo: str,
    number: str,
) -> List[Dict[str, Any]]:
    """Fetches issue comments left on the requested GitHub pull request."""

    # GitHub exposes top-level PR conversation comments through the issues API.
    comments_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"

    try:
        response_payload = _request_json(comments_url, headers=_build_github_request_headers(settings))
    except (HTTPError, URLError, json.JSONDecodeError):
        # Return no comments when GitHub cannot provide the PR conversation.
        return []

    if isinstance(response_payload, list):
        # Keep only structured comment records so downstream extraction is predictable.
        return [comment for comment in response_payload if isinstance(comment, dict)]

    # Return no comments when the response shape is not the expected array.
    return []


def _extract_latest_approved_review(reviews: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Finds the most recent GitHub review that left an APPROVED decision."""

    latest_approved_review: Optional[Dict[str, Any]] = None
    latest_submitted_at: Optional[str] = None

    # Scan the review list for the most recent "APPROVED" submission.
    for review in reviews:
        if str(review.get("state", "")).upper() != "APPROVED":
            # Skip reviews that did not leave an approval decision.
            continue

        submitted_at = str(review.get("submitted_at", "")).strip()

        if latest_submitted_at is None or submitted_at > latest_submitted_at:
            # Keep the latest approved review based on submission timestamp.
            latest_submitted_at = submitted_at
            latest_approved_review = review

    # Return the latest approved GitHub review if one was found.
    return latest_approved_review


def _extract_latest_review_activity(
    reviews: List[Dict[str, Any]],
    comments: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Finds the latest review or comment activity left on a pull request."""

    latest_activity: Optional[Dict[str, Any]] = None
    latest_timestamp: Optional[str] = None

    # Fold submitted PR reviews into the shared review-activity timeline.
    for review in reviews:
        submitted_at = str(review.get("submitted_at", "") or "").strip()

        if not submitted_at:
            # Skip review records that do not have a usable activity timestamp.
            continue

        if latest_timestamp is None or submitted_at > latest_timestamp:
            # Keep the most recent review activity based on GitHub's submitted time.
            latest_timestamp = submitted_at
            latest_activity = {
                "state": str(review.get("state", "") or "").strip().lower(),
                "timestamp": submitted_at,
                "actor": str(review.get("user", {}).get("login", "") or "").strip() or None,
            }

    # Fold top-level PR conversation comments into the same activity timeline.
    for comment in comments:
        created_at = str(comment.get("created_at", "") or "").strip()

        if not created_at:
            # Skip comment records that do not have a usable activity timestamp.
            continue

        if latest_timestamp is None or created_at > latest_timestamp:
            # Treat a PR conversation comment as in-progress review activity.
            latest_timestamp = created_at
            latest_activity = {
                "state": "commented",
                "timestamp": created_at,
                "actor": str(comment.get("user", {}).get("login", "") or "").strip() or None,
            }

    # Return the latest review activity if GitHub exposed one.
    return latest_activity


def fetch_github_pull_request_status(
    settings: Settings,
    pull_request_url: str,
) -> Optional[Dict[str, Any]]:
    """Fetches the normalized PR state payload from GitHub for an existing PR URL.

    Returns None when the caller should fall back to the simulated detection flow
    (for example when the URL is not a real GitHub PR link or GitHub is offline).
    """

    pr_components = parse_github_pull_request_url(pull_request_url)

    if not pr_components:
        # Return None when the URL does not resolve to a real GitHub PR.
        return None

    if not settings.github_owner or not settings.github_repositories:
        # Return None when GitHub is not configured so simulation can take over.
        return None

    pull_request_payload = _fetch_github_pull_request_payload(
        settings,
        pr_components["owner"],
        pr_components["repo"],
        pr_components["number"],
    )

    if not pull_request_payload:
        # Return None so the simulated detection path can still drive the demo UI.
        return None

    state_value = str(pull_request_payload.get("state", "open")).lower()
    merged_flag = bool(pull_request_payload.get("merged", False))
    merged_at_value = str(pull_request_payload.get("merged_at", "") or "").strip() or None
    reviews = _fetch_github_pull_request_reviews(
        settings,
        pr_components["owner"],
        pr_components["repo"],
        pr_components["number"],
    )
    comments = _fetch_github_pull_request_comments(
        settings,
        pr_components["owner"],
        pr_components["repo"],
        pr_components["number"],
    )
    latest_approved_review = _extract_latest_approved_review(reviews)
    latest_review_activity = _extract_latest_review_activity(reviews, comments)
    approved_flag = latest_approved_review is not None
    approved_at_value = (
        str(latest_approved_review.get("submitted_at", "") or "").strip() or None
        if latest_approved_review
        else None
    )
    review_activity_at_value = (
        str(latest_review_activity.get("timestamp", "") or "").strip() or None
        if latest_review_activity
        else None
    )
    review_activity_by_login = (
        str(latest_review_activity.get("actor", "") or "").strip() or None
        if latest_review_activity
        else None
    )
    review_activity_state = (
        str(latest_review_activity.get("state", "") or "").strip() or None
        if latest_review_activity
        else None
    )
    approved_by_login = (
        str(latest_approved_review.get("user", {}).get("login", "")).strip() or None
        if latest_approved_review
        else None
    )

    if merged_flag:
        # Treat merged PRs as the terminal state for the downstream state machine.
        resolved_state = "merged"
    elif state_value == "closed":
        # Treat closed-but-not-merged PRs as a terminal closed state.
        resolved_state = "closed"
    elif approved_flag:
        # Treat at-least-one APPROVED review as the approved-but-open PR state.
        resolved_state = "approved"
    else:
        # Treat every remaining case as the open-awaiting-review state.
        resolved_state = "open"

    # Return the normalized GitHub PR state payload for the state machine.
    return {
        "source": "github",
        "state": resolved_state,
        "title": str(pull_request_payload.get("title", "") or "").strip(),
        "body": str(pull_request_payload.get("body", "") or "").strip(),
        "merged": merged_flag,
        "mergedAt": merged_at_value,
        "approved": approved_flag,
        "approvedAt": approved_at_value,
        "approvedBy": approved_by_login,
        "reviewInProgress": bool(latest_review_activity and not approved_flag and not merged_flag),
        "reviewActivityAt": review_activity_at_value,
        "reviewActivityBy": review_activity_by_login,
        "reviewActivityState": review_activity_state,
        "number": pr_components["number"],
        "owner": pr_components["owner"],
        "repo": pr_components["repo"],
        "htmlUrl": pull_request_payload.get("html_url", pull_request_url),
    }


def summarize_repository_names(records: Iterable[Dict[str, Any]]) -> List[str]:
    """Builds a repository name list from normalized repository records."""

    names: List[str] = []

    # Extract the repository display name from each normalized record.
    for record in records:
        name = record.get("name", "")

        if name:
            # Keep only non-empty repository names.
            names.append(str(name))

    # Return the normalized repository name list.
    return names
