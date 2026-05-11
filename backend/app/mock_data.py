"""Mock API payloads for the AI Control Pane demo backend."""

from copy import deepcopy
from typing import Any, Dict, List


RUN_SUMMARIES: List[Dict[str, Any]] = [
    {
        "id": "acp-142",
        "ticket": "ACP-142",
        "title": "Settings UI for model routing",
        "repo": "web-app",
        "branch": "ai/acp-142-settings-ui",
        "owner": "Maya",
        "agent": "impl-agent",
        "runtime": "08:14",
        "cost": "$3.42",
        "status": "Review",
        "risk": "Medium",
        "currentStep": "Review package ready",
        "summary": "Build a settings experience for model routing, budget caps, and provider validation.",
        "evidence": {
            "diff": [
                "Added a provider settings route with navigation from the control pane shell.",
                "Created a budget threshold form with validation-aware helper messaging.",
                "Replaced placeholder controls with policy and evidence-focused panels.",
            ],
            "tests": [
                "15 unit checks passed",
                "3 integration checks passed",
                "No accessibility blockers reported",
            ],
            "commands": [
                "npm run build",
                "npm run lint",
                "npm run test -- --runInBand",
            ],
            "rationale": [
                "Grouped cost controls and model routing together because both require approval context.",
                "Kept policy warnings visible in the settings flow to reduce risky saves.",
            ],
        },
        "blockers": [
            "No active blockers",
            "Uses existing auth middleware for protected settings routes",
        ],
        "_issueSnapshot": {
            "id": "linear-acp-142",
            "ticket": "ACP-142",
            "title": "Settings UI for model routing",
            "description": "Build a settings experience for model routing, budget caps, and provider validation.",
            "priority": "2",
            "status": "In Progress",
            "url": "https://linear.app/example/issue/ACP-142",
            "assignee": {"name": "Maya", "email": "maya@example.com"},
            "provider": "linear",
        },
    },
    {
        "id": "acp-155",
        "ticket": "ACP-155",
        "title": "API validation hardening",
        "repo": "api-service",
        "branch": "ai/acp-155-api-validation",
        "owner": "Jordan",
        "agent": "impl-agent",
        "runtime": "14:02",
        "cost": "$2.67",
        "status": "Review",
        "risk": "Low",
        "currentStep": "Awaiting human approval",
        "summary": "Tighten request validation and improve callback failure messaging for external providers.",
        "evidence": {
            "diff": [
                "Added stricter request parsing to reject incomplete callback payloads.",
                "Updated callback error rendering to explain retry-safe actions.",
            ],
            "tests": [
                "18 tests passed",
                "No failed jobs",
                "OpenAPI contract snapshot updated",
            ],
            "commands": ["pytest", "ruff check", "python -m mypy ."],
            "rationale": [
                "Focused on low-risk schema protections that reduce noisy retries from agents."
            ],
        },
        "blockers": ["None"],
    },
    {
        "id": "acp-161",
        "ticket": "ACP-161",
        "title": "OAuth callback recovery",
        "repo": "auth-service",
        "branch": "ai/acp-161-oauth-callback",
        "owner": "Priya",
        "agent": "test-agent",
        "runtime": "05:50",
        "cost": "$1.88",
        "status": "Blocked",
        "risk": "High",
        "currentStep": "Waiting on test environment secret",
        "summary": "Stabilize callback retries and remove confusing redirect states during failed sign-in attempts.",
        "evidence": {
            "diff": [
                "Prepared a retry-safe callback branch with staging-only config hooks."
            ],
            "tests": [
                "Unit tests passed",
                "Integration tests blocked by missing secret",
            ],
            "commands": ["pytest tests/unit", "pytest tests/integration"],
            "rationale": [
                "The agent stopped instead of guessing around missing secret access, which matches policy."
            ],
        },
        "blockers": [
            "Missing test environment secret",
            "High-risk auth flow requires approval before merge",
        ],
    },
    {
        "id": "acp-149",
        "ticket": "ACP-149",
        "title": "CI failure repair",
        "repo": "shared-ui",
        "branch": "ai/acp-149-ci-fix",
        "owner": "Sam",
        "agent": "ci-agent",
        "runtime": "19:31",
        "cost": "$1.12",
        "status": "Retry",
        "risk": "Medium",
        "currentStep": "Preparing retry strategy",
        "summary": "Resolve a flaky visual test and suggest a policy-safe retry path.",
        "evidence": {
            "diff": [
                "Reduced test timing assumptions and isolated brittle snapshot setup."
            ],
            "tests": ["Visual test flaky in CI", "Local build passed"],
            "commands": ["npm run test:visual", "npm run build"],
            "rationale": [
                "The next retry should reuse cached fixtures and avoid layout race conditions."
            ],
        },
        "blockers": ["Flaky CI environment"],
    },
    {
        "id": "acp-138",
        "ticket": "ACP-138",
        "title": "Docs search improvements",
        "repo": "web-app",
        "branch": "ai/acp-138-docs-search",
        "owner": "Lin",
        "agent": "impl-agent",
        "runtime": "11:04",
        "cost": "$2.11",
        "status": "Merged",
        "risk": "Low",
        "currentStep": "Pull request merged",
        "summary": "Improve docs search ranking and highlight matched sections for faster scanning.",
        "evidence": {
            "diff": [
                "Upgraded docs search ranker to prefer heading matches before body matches.",
                "Added inline highlighting for matched query fragments in the docs viewer.",
            ],
            "tests": [
                "12 unit tests passed",
                "4 integration tests passed",
                "Search benchmark improved by 18%",
            ],
            "commands": ["npm run build", "npm run test", "npm run bench:docs-search"],
            "rationale": [
                "Heading-weighted ranking aligns with how reviewers scan docs during approvals.",
                "Inline highlighting keeps the reviewer focused without opening every doc in full.",
            ],
        },
        "blockers": ["No active blockers"],
        "approvalHistory": [
            {
                "decision": "approve",
                "source": "reviewer",
                "notes": "Evidence covered ranker and UI updates; merge when CI is green.",
                "actor": {
                    "name": "Priya Singh",
                    "email": "priya@example.com",
                    "role": "admin",
                    "provider": "configured_default",
                },
                "timestamp": "2026-04-17T09:31:00+00:00",
            },
            {
                "decision": "pr_review_approved",
                "source": "github",
                "notes": "GitHub review approved by priya-reviewer",
                "actor": {
                    "name": "GitHub",
                    "email": "noreply@github.com",
                    "role": "admin",
                    "provider": "github",
                },
                "timestamp": "2026-04-17T09:32:12+00:00",
            },
            {
                "decision": "pr_merged",
                "source": "github",
                "notes": "Pull request merged on GitHub",
                "actor": {
                    "name": "GitHub",
                    "email": "noreply@github.com",
                    "role": "admin",
                    "provider": "github",
                },
                "timestamp": "2026-04-17T09:34:48+00:00",
            },
        ],
        "_approvedAt": "2026-04-17T09:31:00+00:00",
        "_approvedBy": "Priya Singh",
        "_mergedAt": "2026-04-17T09:34:48+00:00",
    },
    {
        "id": "sig-15",
        "ticket": "SIG-15",
        "title": "like basically the best ticket out there",
        "repo": "web-app",
        "branch": "ai/sig-15-like-basically-the-best-ticket-out-there",
        "owner": "Jordan",
        "agent": "impl-agent",
        "runtime": "00:00",
        "cost": "$0.00",
        "status": "Review",
        "risk": "Medium",
        "currentStep": "Review package ready for SIG-15 handoff",
        "summary": "Demo run for SIG-15: reviewer handoff with issue traceability preserved from In Progress.",
        "evidence": {
            "diff": [
                "Seeded SIG-15 with a frozen Linear snapshot aligned to the SIG-15 feature branch.",
                "Pinned fallback intake ordering so SIG-15 stays first for Linear traceability walkthroughs.",
            ],
            "tests": ["pytest backend/tests/test_sig15_traceability.py", "npm run test -- --runInBand"],
            "commands": ["git status", "git diff origin/main...HEAD"],
            "rationale": [
                "Keeps Linear SIG-15 visible in the mission-control lobby while the run awaits approval.",
            ],
        },
        "blockers": ["No active blockers", "Waiting for reviewer decision"],
        "_issueSnapshot": {
            "id": "sig-15",
            "ticket": "SIG-15",
            "title": "like basically the best ticket out there",
            "description": "Linear ticket SIG-15 scopes the implementation with issue traceability and reviewer evidence handoff.",
            "priority": "0",
            "status": "In Progress",
            "url": "https://linear.app/example/issue/SIG-15",
            "assignee": {"name": "Jordan", "email": "jordan@example.com"},
            "provider": "linear",
        },
    },
]

APPROVAL_QUEUE: List[Dict[str, str]] = [
    {"runId": "acp-155", "waitingTime": "18 min", "outcomeNeeded": "Approve or retry"},
    {"runId": "acp-142", "waitingTime": "12 min", "outcomeNeeded": "Approve or re-scope"},
    {"runId": "acp-161", "waitingTime": "11 min", "outcomeNeeded": "Escalate or unblock"},
]

POLICY_RULES: List[Dict[str, str]] = [
    {
        "name": "File access",
        "value": "Allow src/**, tests/**, docs/**. Deny .env*, secrets/**, infra/prod/**.",
    },
    {
        "name": "Command policy",
        "value": "Allow safe build and test commands. Require approval for git push and dependency changes.",
    },
    {
        "name": "Approval gates",
        "value": "High-risk auth changes, new dependencies, blocked tests, and deploy-like commands.",
    },
    {
        "name": "Runtime budget",
        "value": "45 minute max run time, $10 spend cap, 2 retries before escalation.",
    },
]

DASHBOARD_METRICS: List[Dict[str, str]] = [
    {"label": "Active runs", "value": "12", "hint": "4 review-ready right now"},
    {"label": "Blocked tasks", "value": "3", "hint": "2 need credentials or policy changes"},
    {"label": "Merged today", "value": "9", "hint": "Average cycle time down 18%"},
    {"label": "Review effort", "value": "18 min", "hint": "Average review time per accepted run"},
]

BLOCKED_REASONS: List[str] = [
    "Missing test environment secret",
    "Policy denied production-impacting command",
    "Flaky integration suite needs retry guidance",
]

SUGGESTED_ACTIONS: List[str] = [
    "4 review-ready runs in the approval inbox",
    "2 high-risk tasks need tech lead attention",
    "Policy pack v3.1 applied to 11 active runs",
]


def get_dashboard_payload() -> Dict[str, Any]:
    """Builds the dashboard payload for the mission control screen."""

    # Copy the mock payload so endpoints cannot accidentally mutate the shared in-memory fixtures.
    return {
        "metrics": deepcopy(DASHBOARD_METRICS),
        "runs": deepcopy(RUN_SUMMARIES),
        "blockedReasons": deepcopy(BLOCKED_REASONS),
        "suggestedActions": deepcopy(SUGGESTED_ACTIONS),
    }


def get_approval_payload() -> Dict[str, Any]:
    """Builds the approval inbox payload with queue summary values."""

    # Return the queue plus a small summary block for the inbox hero state.
    return {
        "summary": {"queueSize": 7, "highRisk": 2, "slaRisk": 2},
        "queue": deepcopy(APPROVAL_QUEUE),
        "runs": deepcopy(RUN_SUMMARIES),
    }


def get_policy_payload() -> Dict[str, Any]:
    """Builds the policy editor payload for the mock control center."""

    # Return the current repo scope and the human-readable rule set.
    return {
        "scope": "web-app",
        "version": "3.1",
        "rules": deepcopy(POLICY_RULES),
    }


def get_run_by_id(run_id: str) -> Dict[str, Any]:
    """Finds a specific mock run detail payload by ID."""

    # Search the mock run list for the matching task record.
    for run in RUN_SUMMARIES:
        if run["id"] == run_id:
            # Copy the selected run so callers can safely reshape the payload.
            return deepcopy(run)

    # Raise a key error so the API layer can translate it into a 404 response.
    raise KeyError(run_id)
