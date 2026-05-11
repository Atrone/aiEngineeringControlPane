# Integration Map

This document lists the initial systems the AI Control Pane should integrate with in order to support the MVP workflow: a tech lead delegates a scoped engineering ticket to an AI agent, reviews the evidence, and decides whether to merge or retry.

## Integration Principles
- Start with systems that provide the minimum loop of intake, execution, verification, and approval.
- Prefer one strong integration per category in the first release instead of many shallow adapters.
- Capture enough metadata to make agent work observable and auditable.

## Recommended Day-One Integration Set

| Category | Primary Recommendation | Why It Matters In MVP |
| --- | --- | --- |
| Repositories | GitHub | Pull requests, diffs, branches, checks, reviewers, and audit history are central to the approval loop. |
| CI | GitHub Actions | Keeps repo state and CI state in the same platform for a simpler first implementation. |
| Issue Tracker | Linear or Jira | Gives the pane a source of scoped tasks, acceptance criteria, owners, and status. |
| Docs / Knowledge | Notion, Confluence, or repo markdown | Provides architecture guidance, coding standards, and implementation context for agent memory. |
| Authentication | SSO via Google Workspace, Okta, or Microsoft Entra ID | Needed for team access, role-aware permissions, and approval accountability. |

## Category Details

### 1. Repository Integration

#### MVP Requirements
- Read repository metadata, default branches, and branch protections.
- Create agent branches.
- Read and write pull requests or draft pull requests.
- Fetch diffs, changed files, review comments, and merge status.
- Associate every agent run with a repo, branch, and resulting PR.

#### Core Data Needed
- Repository name and identifier
- Branches and branch protection rules
- Pull request status
- Changed files and diff hunks
- Reviewer assignments
- Mergeability state

#### MVP Features Enabled
- Launch task against a specific repo
- Show code changes in the task detail page
- Route approved work into a standard merge flow
- Preserve auditability between agent runs and pull requests

### 2. CI Integration

#### MVP Requirements
- Read build, test, and lint status for a branch or pull request.
- Surface failed jobs and logs inside the task detail page.
- Link CI outcomes into the approval decision.

#### Core Data Needed
- Workflow run status
- Job names and durations
- Failing step names
- Log URLs or log excerpts
- Re-run eligibility

#### MVP Features Enabled
- Evidence-backed review
- Blocked-state explanations
- Retry guidance when the agent needs another pass

### 3. Issue Tracker Integration

#### MVP Requirements
- Import ticket title, description, acceptance criteria, priority, and assignee.
- Sync ticket state with task state at key moments.
- Link a task and its resulting PR back to the originating issue.

#### Core Data Needed
- Ticket ID and title
- Description and acceptance criteria
- Labels, priority, and owner
- Current workflow state
- Related links

#### MVP Features Enabled
- Fast task intake
- Better agent grounding
- Clear traceability from request to code change

### 4. Docs and Knowledge Integration

#### MVP Requirements
- Attach specific docs to a task or auto-attach docs based on repo or service.
- Support both centralized docs and repo-local markdown.
- Record which knowledge sources influenced a run.

#### Core Data Needed
- Document title and URL
- Page or section identifiers
- Last updated timestamp
- Repo or service association
- Access permissions

#### MVP Features Enabled
- Shared memory injection
- Reviewable evidence for why the agent made certain choices
- Lower prompt-writing overhead for tech leads

### 5. Authentication and Identity Integration

#### MVP Requirements
- Support team login via SSO.
- Map users to roles such as tech lead, engineer, and admin.
- Store who launched, reviewed, approved, retried, or escalated each task.

#### Core Data Needed
- User identity
- Team and organization membership
- Roles and groups
- Session metadata
- Approval action history

#### MVP Features Enabled
- Human approval gates
- Role-based policy access
- Org-level audit trail

### Single-Stack Simplicity
- `GitHub`
- `GitHub Actions`
- `Linear`
- `Repo markdown and one shared docs source`
- `Google Workspace SSO` or equivalent

This gives the fastest path to an end-to-end demo with the fewest cross-platform edges.

## Risks and Design Notes
- Repository and CI integrations should be designed together because reviewers need code and checks in one place.
- Issue tracker sync should be event-driven but tolerant of stale data so the pane stays responsive.
- Knowledge integrations must surface provenance, or reviewers will not trust agent rationale.
- Identity must be first-class because approvals are part of the product, not an afterthought.

## Suggested API Surface For The Product Team
- `POST /tasks`: create a new AI work item from a ticket or prompt.
- `POST /runs`: launch a specific agent attempt with repo, policy, and context.
- `GET /runs/:id`: fetch status, evidence, and linked external metadata.
- `POST /approvals`: record a human decision with reason and next action.
- `GET /policies/:scope`: fetch the active policy pack for a repo or team.

## Definition Of Done For Integration Readiness
- A tech lead can pick a ticket and launch a task without manual copy-paste.
- A reviewer can see the code diff, CI state, and task evidence from one screen.
- The final approval action is tied to a real user identity.
- Every approved task can be traced back to its issue, repo branch, and review decision.
