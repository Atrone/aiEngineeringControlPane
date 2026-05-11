# SIG-15: Linear traceability demo — design decisions

**Linear:** SIG-15 (like basically the best ticket out there)  
**Scope:** `backend/app/state.py` — fallback intake issue catalog when Linear/Jira are not connected

## Goals

- Give reviewers a first-class **SIG-15** row in task intake without requiring a Linear API key.
- Match the ticket’s **In Progress** status so the task-detail **traceability** snapshot can show `preservedFromInProgress: true` after a run is created from intake.
- Keep acceptance wording aligned with the issue so auto-filled acceptance criteria in the UI matches the tracker.

## References (product)

- `docs/mvp-definition.md` — human approval and evidence before merge.
- `docs/integrations.md` — issue tracker sync and linking tasks back to the originating issue.

## Implementation summary

| Area | Change | Rationale |
| --- | --- | --- |
| Fallback issues | Append a synthetic Linear issue `SIG-15` with status `In Progress` | Exercises `_build_traceability_snapshot` and the intake form’s status-driven acceptance line |
| Provider | `provider: linear` | Matches `buildIssueTrackerRunLabel` / “Linear-linked issue” in the UI |
| Priority | `0` | Matches the Linear priority field from the originating ticket |

## Manual review checks performed

- Intake (no Linear key): **SIG-15** appears in the issue list with **In Progress** and **0 priority**.
- Selecting SIG-15 fills acceptance criteria: *Deliver SIG-15 with clear review evidence and preserve issue traceability from In Progress.*
- After creating a run from SIG-15, task detail **Traceability** shows **Preserved from In Progress: Yes**.

## Traceability

Commits for this work reference **SIG-15** in the message subject for Linear ticket traceability.
