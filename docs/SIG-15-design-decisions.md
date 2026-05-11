# SIG-15: Issue traceability from In Progress — design decisions

**Linear:** SIG-15 (like basically the best ticket out there)  
**Status:** In Progress (ticket meta; implementation closes the engineering loop)  
**Scope:** `backend/app/state.py`, `backend/app/mock_data.py`, reviewer-facing task detail and intake catalogs

## Goals

- Give reviewers a first-class **SIG-15** path in task intake without requiring a Linear API key, while matching the ticket’s **In Progress** status so task-detail **traceability** can show `preservedFromInProgress: true`.
- Keep **issue traceability** consistent between intake and the task-detail **traceability snapshot** when runs preserve an `_issueSnapshot`.
- Normalize common tracker spellings (`In Progress`, `in_progress`, `In-Progress`) so the `preservedFromInProgress` flag stays reliable across providers.

## References (product)

- `docs/integrations.md` — issue tracker integration: link tasks and PRs back to the originating issue; sync state at key moments.
- `docs/mvp-definition.md` — evidence-backed review before merge; auditable trail from ticket to code.
- `docs/wireframes.md` — task detail surfaces evidence and decisions on one page.

## Implementation summary

| Area | Change | Rationale |
| --- | --- | --- |
| SIG-15 intake row | `_sig_15_linear_demo_issue` plus ordering in `_fallback_issues` | Surfaces the ticket when the run store alone would not list SIG-15 |
| Fallback issues | Prefer `_issueSnapshot` fields (including stable snapshot `id`) for each seeded run | Operators see launch-time tracker metadata instead of only the run lifecycle state |
| Status normalization | `_issue_launch_status_indicates_in_progress` | Avoids brittle equality when APIs emit underscores or hyphens |
| Traceability snapshot | `preservedFromInProgress` uses the helper | Review panels stay aligned with acceptance language |
| Demo runs | Seeded `sig-15` and `acp-142` runs carry Linear-style `_issueSnapshot` rows | Supplies concrete lobby and regression targets without depending on live Linear |

## Automated validation performed

- `python3 -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt && python3 -m pip install httpx` (local environment bootstrap for this agent run)
- `python3 -m pytest backend/tests/test_sig15_traceability.py -q`
- `python3 -m pytest backend/tests/ -q` (full backend suite before handoff)
- `npm ci && npm test -- --run` in `frontend/` (guards against accidental API contract drift)

## Manual reviewer checks (optional)

- Intake (no Linear key): **SIG-15** appears first with **In Progress** and **0 priority**; selecting it fills acceptance criteria aligned with the ticket.
- Task detail for run `sig-15`: **Traceability snapshot** shows **Preserved from In Progress: Yes** while the run can remain in **Review**.
- Task detail for run `acp-142`: same traceability snapshot behavior for an additional seeded snapshot row.

## Traceability

All commits for this work reference **SIG-15** in the message subject for Linear ticket traceability.
