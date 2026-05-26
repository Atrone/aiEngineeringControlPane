"""Live-view builders for run detail execution panels."""

from typing import Any, Dict, List, Mapping

from app.state_time import STREAM_STEP_SECONDS


def _state():
    """Returns the public state facade for compatibility-level helper access."""

    # Import lazily to avoid circular imports while app.state loads these helper modules.
    from app import state

    # Return the facade module that owns the backward-compatible patch points.
    return state

def _build_stream_plan(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Builds the simulated streaming plan for a live run."""

    evidence = run.get("evidence", {})
    diff_items = list(evidence.get("diff", []))
    test_items = list(evidence.get("tests", []))
    rationale_items = list(evidence.get("rationale", []))
    first_diff = diff_items[0] if diff_items else "Prepared the first implementation pass for the requested scope."
    first_test = test_items[0] if test_items else "Queued validation after the code edit step."
    first_rationale = rationale_items[0] if rationale_items else "The run is building a review package with evidence attached."
    execution_mode = str(run.get("_executionMode", "implement"))
    agent_name = str(run.get("agent", "impl-agent"))
    repo_name = str(run.get("repo", "repo"))
    branch_name = str(run.get("branch", "ai/generated"))

    # Return the ordered step plan used to simulate a live agent run.
    return [
        {
            "id": "accepted",
            "offsetSeconds": 0,
            "title": "Task accepted",
            "detail": f"{agent_name} picked up {run['ticket']} in {execution_mode} mode.",
            "currentStep": "Loading task context",
            "logs": [
                {"level": "info", "source": "orchestrator", "message": f"Queued {run['ticket']} for {agent_name}."},
                {"level": "info", "source": "agent", "message": f"Loading repository context for {repo_name} on {branch_name}."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Scoped the live run",
                        "detail": f"Execution mode {execution_mode} was selected for {repo_name}.",
                    },
                ],
            },
        },
        {
            "id": "plan",
            "offsetSeconds": STREAM_STEP_SECONDS,
            "title": "Plan generated",
            "detail": "Agent reviewed the task context and drafted an implementation approach.",
            "currentStep": "Drafting plan and selecting files",
            "logs": [
                {"level": "info", "source": "agent", "message": "Summarized acceptance criteria and matched nearby files."},
                {"level": "info", "source": "planner", "message": "Prepared an execution plan with diff, validation, and review milestones."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Planning rationale captured",
                        "detail": first_rationale,
                    },
                ],
            },
        },
        {
            "id": "edit",
            "offsetSeconds": STREAM_STEP_SECONDS * 2,
            "title": "Files edited",
            "detail": "Implementation changes were written to the working tree.",
            "currentStep": "Editing files and collecting diff evidence",
            "logs": [
                {"level": "info", "source": "agent", "message": "Applied the first code change set to the target branch."},
                {"level": "success", "source": "git", "message": "Working tree updated without policy violations."},
            ],
            "evidence": {
                "diff": [
                    {
                        "summary": "Working diff captured",
                        "detail": first_diff,
                    },
                ],
            },
        },
        {
            "id": "tests",
            "offsetSeconds": STREAM_STEP_SECONDS * 3,
            "title": "Validation running",
            "detail": "The agent started validation and is collecting proof for reviewer handoff.",
            "currentStep": "Running validation and summarizing evidence",
            "logs": [
                {"level": "info", "source": "runner", "message": "Started the validation command group for the current changes."},
                {"level": "success", "source": "runner", "message": first_test},
            ],
            "evidence": {
                "tests": [
                    {
                        "summary": "Validation evidence captured",
                        "detail": first_test,
                    },
                ],
            },
        },
        {
            "id": "handoff",
            "offsetSeconds": STREAM_STEP_SECONDS * 4,
            "title": "Review package ready",
            "detail": "The run finished streaming and is ready for human review.",
            "currentStep": "Review package ready",
            "logs": [
                {"level": "success", "source": "agent", "message": "Review bundle assembled with diff, tests, and rationale tabs."},
                {"level": "info", "source": "orchestrator", "message": "Streaming paused while awaiting a reviewer decision."},
            ],
            "evidence": {
                "rationale": [
                    {
                        "summary": "Reviewer handoff prepared",
                        "detail": "The agent packaged the run timeline, streamed logs, and evidence for approval.",
                    },
                ],
            },
        },
    ]


def _build_evidence_entries(
    items: List[str],
    *,
    tab_name: str,
    runtime_value: str,
    status: str,
) -> List[Dict[str, str]]:
    """Builds timestamped evidence entries for a static run."""

    entries: List[Dict[str, str]] = []
    timepoints = _state()._build_static_timepoints(runtime_value, max(1, len(items)))

    # Convert each plain evidence string into a richer entry used by the tabbed UI.
    for index, item in enumerate(items):
        entries.append(
            {
                "id": f"{tab_name}-{index}",
                "timestamp": timepoints[index],
                "summary": f"{tab_name.title()} evidence {index + 1}",
                "detail": item,
                "status": status,
            }
        )

    # Return the evidence entry list for the requested tab.
    return entries


def _build_static_timeline(run: Dict[str, Any]) -> List[Dict[str, str]]:
    """Builds a completed timeline for a non-streaming run."""

    evidence = run.get("evidence", {})
    rationale_items = list(evidence.get("rationale", []))
    diff_items = list(evidence.get("diff", []))
    test_items = list(evidence.get("tests", []))
    timeline_templates = [
        {
            "id": "created",
            "title": "Task created",
            "detail": "Issue, repository, and policy context were attached to the run.",
        },
        {
            "id": "plan",
            "title": "Plan generated",
            "detail": rationale_items[0] if rationale_items else "The agent planned the requested change.",
        },
        {
            "id": "edit",
            "title": "Files edited",
            "detail": diff_items[0] if diff_items else "Code changes were prepared for review.",
        },
        {
            "id": "validate",
            "title": "Validation completed" if run["status"] in {"Review", "Merged"} else "Validation attempted",
            "detail": test_items[0] if test_items else str(run["currentStep"]),
        },
        {
            "id": "final",
            "title": "Merged"
            if run["status"] == "Merged"
            else "Approved - awaiting merge"
            if run["status"] == "Approved"
            else "Run blocked"
            if run["status"] == "Blocked"
            else "Retry prepared"
            if run["status"] == "Retry"
            else "Review package ready",
            "detail": str(run["currentStep"]),
        },
    ]
    timepoints = _state()._build_static_timepoints(str(run.get("runtime", "00:00")), len(timeline_templates))
    timeline_entries: List[Dict[str, str]] = []

    # Pair each static run step with a timestamp so the execution history still reads chronologically.
    for index, template in enumerate(timeline_templates):
        timeline_entries.append(
            {
                "id": template["id"],
                "title": template["title"],
                "detail": template["detail"],
                "timestamp": timepoints[index],
                "status": "complete",
            }
        )

    # Return the completed timeline for the run.
    return timeline_entries


def _build_static_logs(run: Dict[str, Any]) -> List[Dict[str, str]]:
    """Builds the log stream for a non-streaming run."""

    log_entries: List[Dict[str, str]] = []
    commands = list(run.get("evidence", {}).get("commands", []))
    timepoints = _state()._build_static_timepoints(str(run.get("runtime", "00:00")), max(2, len(commands) + 2))
    status_level = "warning" if run["status"] in {"Blocked", "Retry"} else "success"

    log_entries.append(
        {
            "id": "static-log-start",
            "timestamp": timepoints[0],
            "level": "info",
            "source": "orchestrator",
            "message": f"Loaded run summary for {run['ticket']} in {run['repo']}.",
        }
    )

    # Convert recorded commands into readable log lines for the execution stream panel.
    for index, command in enumerate(commands):
        log_entries.append(
            {
                "id": f"static-log-command-{index}",
                "timestamp": timepoints[min(index + 1, len(timepoints) - 1)],
                "level": "info",
                "source": "runner",
                "message": f"Executed: {command}",
            }
        )

    log_entries.append(
        {
            "id": "static-log-finish",
            "timestamp": timepoints[-1],
            "level": status_level,
            "source": "agent",
            "message": str(run["currentStep"]),
        }
    )

    # Return the static log stream for the task detail view.
    return log_entries


def _build_stream_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the live timeline, log stream, and evidence tabs for a streaming run."""

    started_at = _state()._parse_timestamp(str(run.get("_streamStartedAt", "")))
    step_plan = _build_stream_plan(run)
    elapsed_seconds = max(0, int((_state()._utc_now() - started_at).total_seconds()))
    final_offset = int(step_plan[-1]["offsetSeconds"])
    is_complete = elapsed_seconds >= final_offset
    active_index = 0
    timeline_entries: List[Dict[str, Any]] = []
    log_entries: List[Dict[str, Any]] = []
    evidence_tabs: Dict[str, List[Dict[str, Any]]] = {"diff": [], "tests": [], "rationale": []}

    # Resolve which step should be shown as active for the current elapsed time.
    for index, step in enumerate(step_plan):
        if elapsed_seconds >= int(step["offsetSeconds"]):
            active_index = index

    # Build the timeline, visible logs, and evidence tabs from the revealed stream steps.
    for index, step in enumerate(step_plan):
        if is_complete or index < active_index:
            step_status = "complete"
        elif index == active_index:
            step_status = "complete" if is_complete else "active"
        else:
            step_status = "pending"

        step_timestamp = _state()._build_step_timestamp(started_at, int(step["offsetSeconds"]))
        timeline_entries.append(
            {
                "id": step["id"],
                "title": step["title"],
                "detail": step["detail"],
                "timestamp": step_timestamp,
                "status": step_status,
            }
        )

        if not is_complete and index > active_index:
            # Keep future logs and evidence hidden until the step becomes visible.
            continue

        evidence_status = "captured" if is_complete or index < active_index else "running"

        # Surface every visible step log inside the streamed execution panel.
        for log_index, log in enumerate(step.get("logs", [])):
            log_entries.append(
                {
                    "id": f"{step['id']}-log-{log_index}",
                    "timestamp": step_timestamp,
                    "level": log["level"],
                    "source": log["source"],
                    "message": log["message"],
                }
            )

        # Group visible evidence into the diff, tests, and rationale tabs.
        for tab_name, tab_items in step.get("evidence", {}).items():
            for item_index, item in enumerate(tab_items):
                evidence_tabs[tab_name].append(
                    {
                        "id": f"{step['id']}-{tab_name}-{item_index}",
                        "timestamp": step_timestamp,
                        "summary": item["summary"],
                        "detail": item["detail"],
                        "status": evidence_status,
                    }
                )

    # Return the live execution snapshot consumed by the task detail page.
    return {
        "isLive": not is_complete and run["status"] == "Running",
        "statusLabel": "Streaming live" if not is_complete and run["status"] == "Running" else "Stream complete",
        "lastUpdatedAt": _state()._utc_timestamp(),
        "timeline": timeline_entries,
        "logs": log_entries,
        "evidenceTabs": evidence_tabs,
    }


def _build_cursor_cloud_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the task detail live view for a run backed by Cursor Cloud Agents."""

    cloud_agent = run.get("_cursorAgent", {}) or {}
    target_payload = _state()._extract_cloud_agent_target(cloud_agent if isinstance(cloud_agent, Mapping) else {})
    created_at = str(cloud_agent.get("createdAt", "")).strip() or _state()._utc_timestamp()
    cursor_status = str(cloud_agent.get("status", "CREATING"))
    timeline_status = "complete" if run["status"] != "Running" else "active"
    review_status = "pending" if run["status"] == "Running" else "complete"
    timeline = [
        {
            "id": "cursor-launch",
            "title": "Cursor Cloud Agent launched",
            "detail": f"{cloud_agent.get('id', 'Unknown agent')} was started for {run['repo']}.",
            "timestamp": created_at,
            "status": "complete",
        },
        {
            "id": "cursor-progress",
            "title": f"Cursor status: {cursor_status}",
            "detail": run["currentStep"],
            "timestamp": _state()._utc_timestamp(),
            "status": timeline_status,
        },
        {
            "id": "cursor-review",
            "title": "Review handoff",
            "detail": "The task will move into review once the Cursor Cloud Agent finishes.",
            "timestamp": _state()._utc_timestamp(),
            "status": review_status,
        },
    ]
    logs = [
        {
            "id": "cursor-log-launch",
            "timestamp": created_at,
            "level": "info",
            "source": "cursor-cloud",
            "message": f"Launched agent {cloud_agent.get('id', 'unknown')} for repository {run['repo']}.",
        },
        {
            "id": "cursor-log-status",
            "timestamp": _state()._utc_timestamp(),
            "level": "warning" if run["status"] == "Blocked" else "success" if run["status"] == "Review" else "info",
            "source": "cursor-cloud",
            "message": run["currentStep"],
        },
    ]
    rationale_entries = [
        {
            "id": "cursor-rationale-launch",
            "timestamp": created_at,
            "summary": "Live cloud agent launched",
            "detail": str(run.get("_cursorPromptSummary", "The run was sent to Cursor Cloud Agents using the selected task context.")),
            "status": "captured" if run["status"] != "Running" else "running",
        },
    ]

    if str(target_payload.get("prUrl", "")).strip():
        # Add the generated pull request URL when Cursor already created one.
        rationale_entries.append(
            {
                "id": "cursor-rationale-pr",
                "timestamp": _state()._utc_timestamp(),
                "summary": "Pull request link available",
                "detail": f"Cursor attached PR {target_payload.get('prUrl')}.",
                "status": "captured",
            }
        )

    # Return the live execution snapshot consumed by the task detail page.
    return {
        "isLive": run["status"] == "Running",
        "statusLabel": "Cursor Cloud Agent running" if run["status"] == "Running" else "Cursor Cloud Agent complete",
        "lastUpdatedAt": _state()._utc_timestamp(),
        "timeline": timeline,
        "logs": logs,
        "evidenceTabs": {
            "diff": [],
            "tests": [],
            "rationale": rationale_entries,
        },
    }


def _build_github_copilot_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the task detail live view for a run backed by GitHub Copilot cloud agent."""

    cloud_agent = run.get("_githubCopilotAgent", {}) or {}
    target_payload = _state()._extract_cloud_agent_target(cloud_agent if isinstance(cloud_agent, Mapping) else {})
    created_at = str(cloud_agent.get("createdAt", "")).strip() or _state()._utc_timestamp()
    copilot_status = str(cloud_agent.get("status", "ASSIGNED"))
    timeline_status = "complete" if run["status"] != "Running" else "active"
    review_status = "pending" if run["status"] == "Running" else "complete"
    timeline = [
        {
            "id": "github-copilot-launch",
            "title": "GitHub Copilot cloud agent assigned",
            "detail": f"{cloud_agent.get('id', 'Unknown agent')} was assigned for {run['repo']}.",
            "timestamp": created_at,
            "status": "complete",
        },
        {
            "id": "github-copilot-progress",
            "title": f"GitHub Copilot status: {copilot_status}",
            "detail": run["currentStep"],
            "timestamp": _state()._utc_timestamp(),
            "status": timeline_status,
        },
        {
            "id": "github-copilot-review",
            "title": "Review handoff",
            "detail": "The task will move into review once Copilot opens a pull request.",
            "timestamp": _state()._utc_timestamp(),
            "status": review_status,
        },
    ]
    logs = [
        {
            "id": "github-copilot-log-launch",
            "timestamp": created_at,
            "level": "info",
            "source": "github-copilot-cloud",
            "message": f"Assigned Copilot through GitHub issue {target_payload.get('issueUrl', target_payload.get('url', 'unknown'))}.",
        },
        {
            "id": "github-copilot-log-status",
            "timestamp": _state()._utc_timestamp(),
            "level": "warning" if run["status"] == "Blocked" else "success" if run["status"] == "Review" else "info",
            "source": "github-copilot-cloud",
            "message": run["currentStep"],
        },
    ]
    rationale_entries = [
        {
            "id": "github-copilot-rationale-launch",
            "timestamp": created_at,
            "summary": "Live cloud agent assigned",
            "detail": str(run.get("_githubCopilotPromptSummary", "The run was sent to GitHub Copilot cloud agent using the selected task context.")),
            "status": "captured" if run["status"] != "Running" else "running",
        },
    ]

    if str(target_payload.get("prUrl", "")).strip():
        # Add the generated pull request URL when Copilot already created one.
        rationale_entries.append(
            {
                "id": "github-copilot-rationale-pr",
                "timestamp": _state()._utc_timestamp(),
                "summary": "Pull request link available",
                "detail": f"GitHub Copilot attached PR {target_payload.get('prUrl')}.",
                "status": "captured",
            }
        )

    # Return the live execution snapshot consumed by the task detail page.
    return {
        "isLive": run["status"] == "Running",
        "statusLabel": "GitHub Copilot cloud agent running" if run["status"] == "Running" else "GitHub Copilot cloud agent complete",
        "lastUpdatedAt": _state()._utc_timestamp(),
        "timeline": timeline,
        "logs": logs,
        "evidenceTabs": {
            "diff": [],
            "tests": [],
            "rationale": rationale_entries,
        },
    }


def _build_static_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the timeline, logs, and evidence tabs for a static run."""

    evidence = run.get("evidence", {})
    test_status = "blocked" if run["status"] == "Blocked" else "captured"

    if run["status"] == "Review":
        static_status_label = "Awaiting decision"
    elif run["status"] == "Approved":
        static_status_label = "Approved - awaiting PR merge"
    elif run["status"] == "Merged":
        static_status_label = "Pull request merged"
    else:
        static_status_label = "Execution complete"

    # Return the completed execution view for runs that are no longer actively streaming.
    return {
        "isLive": False,
        "statusLabel": static_status_label,
        "lastUpdatedAt": _state()._utc_timestamp(),
        "timeline": _state()._build_static_timeline(run),
        "logs": _state()._build_static_logs(run),
        "evidenceTabs": {
            "diff": _state()._build_evidence_entries(list(evidence.get("diff", [])), tab_name="diff", runtime_value=str(run.get("runtime", "00:00")), status="captured"),
            "tests": _state()._build_evidence_entries(list(evidence.get("tests", [])), tab_name="tests", runtime_value=str(run.get("runtime", "00:00")), status=test_status),
            "rationale": _state()._build_evidence_entries(list(evidence.get("rationale", [])), tab_name="rationale", runtime_value=str(run.get("runtime", "00:00")), status="captured"),
        },
    }


def _build_live_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the task detail live view for the requested run."""

    if run.get("_cursorAgent"):
        # Prefer the Cursor-specific live view when the run is backed by a cloud agent.
        return _state()._build_cursor_cloud_live_view(run)

    if run.get("_githubCopilotAgent"):
        # Prefer the Copilot-specific live view when the run is backed by a cloud agent.
        return _state()._build_github_copilot_live_view(run)

    if run.get("_streamStartedAt"):
        # Prefer the streaming execution view when the run was started in the live simulator.
        return _state()._build_stream_live_view(run)

    # Fall back to a completed execution view for static seeded runs.
    return _state()._build_static_live_view(run)
