import type { FormEvent, ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useApiQuery } from './hooks/useApiQuery';
import {
  createApprovalDecision,
  createRun,
  createTask,
  fetchApprovals,
  fetchCurrentUser,
  fetchDashboard,
  fetchIntegrations,
  fetchIntakeOptions,
  fetchPolicies,
  fetchRunDetail,
} from './lib/api';
import type {
  ApprovalDecisionRequest,
  ApprovalItem,
  CurrentUser,
  DashboardMetric,
  DocumentRecord,
  IntegrationStatus,
  IssueRecord,
  RiskLevel,
  RunSummary,
  RunStatus,
  TaskCreateRequest,
} from './types/controlPane';

/**
 * Renders the top-level routed application.
 */
function App() {
  // Route the user into the product shell and default dashboard view.
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route element={<Navigate replace to="/dashboard" />} index />
        <Route element={<DashboardPage />} path="/dashboard" />
        <Route element={<WorkIntakePage />} path="/intake" />
        <Route element={<TaskDetailPage />} path="/tasks/:runId" />
        <Route element={<ApprovalInboxPage />} path="/approvals" />
        <Route element={<PoliciesPage />} path="/policies" />
        <Route element={<IntegrationsPage />} path="/integrations" />
      </Route>
    </Routes>
  );
}

/**
 * Builds the shared frame around each primary page.
 */
function RootLayout() {
  const location = useLocation();
  const userQuery = useApiQuery(fetchCurrentUser, []);

  // Keep the shell visible so the app feels like a real control center.
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <p className="eyebrow">AI Control Pane</p>
          <h1>Mission Control</h1>
          <p className="muted-copy">
            Coordinate AI coding agents across issue intake, repo context, approval, and delivery workflows.
          </p>
        </div>

        <nav aria-label="Primary" className="nav-list">
          <Link className={getNavLinkClassName(location.pathname, '/dashboard')} to="/dashboard">
            Dashboard
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/intake')} to="/intake">
            Work Intake
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/approvals')} to="/approvals">
            Approval Inbox
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/policies')} to="/policies">
            Policy Center
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/integrations')} to="/integrations">
            Integrations
          </Link>
          {location.pathname.startsWith('/tasks/') ? (
            <Link className="nav-link active" to={location.pathname}>
              Task Detail
            </Link>
          ) : null}
        </nav>

        <div className="sidebar-card">
          <p className="sidebar-label">Current user</p>
          <p className="sidebar-stat">{buildUserHeadline(userQuery.data)}</p>
          <p className="muted-copy">{buildUserSubtitle(userQuery.data, userQuery.isLoading, userQuery.error)}</p>
        </div>
      </aside>

      <main className="page-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">Product Eng</p>
            <h2>Team operations view</h2>
          </div>
          <div className="topbar-actions">
            <Link className="ghost-button link-button" to="/integrations">
              View integrations
            </Link>
            <Link className="primary-button link-button" to="/intake">
              New task
            </Link>
          </div>
        </header>

        <Outlet />
      </main>
    </div>
  );
}

/**
 * Shows the live mission control dashboard.
 */
function DashboardPage() {
  const query = useApiQuery(fetchDashboard, []);

  if (query.isLoading) {
    // Render a lightweight loading state while dashboard data is fetched.
    return <LoadingState message="Loading mission control data..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the dashboard request fails.
    return <ErrorState message={query.error ?? 'Dashboard data was unavailable.'} />;
  }

  const metricCards: ReactNode[] = [];
  const runCards: ReactNode[] = [];
  const blockedItems: ReactNode[] = [];
  const suggestedItems: ReactNode[] = [];
  const integrationCards: ReactNode[] = [];

  // Build cards explicitly so the UI stays easy to reshape later.
  for (const metric of query.data.metrics) {
    metricCards.push(<MetricCard hint={metric.hint} key={metric.label} label={metric.label} value={metric.value} />);
  }

  // Build the active run list from the fetched execution feed.
  for (const run of query.data.runs) {
    runCards.push(
      <Link className="run-row" key={run.id} to={`/tasks/${run.id}`}>
        <div className="run-row-main">
          <div className="run-ticket">
            <p className="ticket-code">{run.ticket}</p>
            <h3>{run.title}</h3>
          </div>
          <p className="muted-copy">{run.summary}</p>
          <p className="subtle-copy">
            {run.issue?.provider === 'linear' ? 'Linear-linked issue' : 'Fallback issue'} · {run.repo} · {run.agent}
          </p>
        </div>

        <div className="run-row-meta">
          <StatusBadge risk={run.risk} status={run.status} />
          <span>{run.repo}</span>
          <span>{run.owner}</span>
          <span>{run.runtime}</span>
        </div>
      </Link>,
    );
  }

  // Render the blocked reasons in the right rail from API data.
  for (const reason of query.data.blockedReasons) {
    blockedItems.push(
      <p className="rail-item" key={reason}>
        {reason}
      </p>,
    );
  }

  // Render the suggested next actions in the right rail from API data.
  for (const action of query.data.suggestedActions) {
    suggestedItems.push(
      <p className="rail-item" key={action}>
        {action}
      </p>,
    );
  }

  // Render provider integration cards so the operator can see live vs fallback modes.
  for (const status of query.data.integrationStatuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  // Surface the operational view, queue summary, and blocked context together.
  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Live operations</p>
          <h3>Track AI work across planning, implementation, testing, review, and integration status.</h3>
          <p className="muted-copy">
            The dashboard now mixes real provider integrations when configured and safe fallbacks when credentials are absent.
          </p>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.currentUser.role}</span>
          <span className="pill">{query.data.integrationStatuses.length} provider categories</span>
        </div>
      </section>

      <section className="metric-grid">{metricCards}</section>

      <section className="content-grid">
        <Panel body={<div className="run-list">{runCards}</div>} title="Active and recent runs" />

        <div className="rail-stack">
          <Panel body={<div className="rail-list">{blockedItems}</div>} title="Blocked reasons" />
          <Panel body={<div className="rail-list">{suggestedItems}</div>} title="Suggested next actions" />
        </div>
      </section>

      <Panel body={<div className="integration-grid">{integrationCards}</div>} title="Integration status" />
    </div>
  );
}

/**
 * Shows the integrated task intake flow.
 */
function WorkIntakePage() {
  const query = useApiQuery(fetchIntakeOptions, []);
  const navigate = useNavigate();
  const [selectedIssueId, setSelectedIssueId] = useState<string>('');
  const [selectedRepoName, setSelectedRepoName] = useState<string>('');
  const [title, setTitle] = useState<string>('');
  const [prompt, setPrompt] = useState<string>('');
  const [acceptanceCriteria, setAcceptanceCriteria] = useState<string>('');
  const [executionMode, setExecutionMode] = useState<string>('implement');
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  useEffect(() => {
    if (!query.data) {
      // Skip form bootstrapping until the intake payload is available.
      return;
    }

    if (!selectedRepoName && query.data.repositories.length > 0) {
      // Default the repo selection to the first available repository option.
      setSelectedRepoName(query.data.repositories[0].name);
    }

    if (selectedDocumentIds.length === 0 && query.data.documents.length > 0) {
      // Preselect the first two knowledge sources for a sensible intake default.
      setSelectedDocumentIds(query.data.documents.slice(0, 2).map((document) => document.id));
    }
  }, [query.data, selectedDocumentIds.length, selectedRepoName]);

  useEffect(() => {
    if (!query.data || !selectedIssueId) {
      // Skip issue-driven form updates when no issue is selected.
      return;
    }

    const issue = findIssueById(query.data.issues, selectedIssueId);

    if (!issue) {
      // Skip updates when the selected issue cannot be found.
      return;
    }

    if (!title) {
      // Seed the task title from the selected issue.
      setTitle(issue.title);
    }

    if (!prompt) {
      // Seed the implementation prompt from the selected issue description.
      setPrompt(issue.description || `Implement ${issue.ticket}: ${issue.title}`);
    }

    if (!acceptanceCriteria) {
      // Seed the acceptance criteria from the selected issue title and status.
      setAcceptanceCriteria(`Deliver ${issue.ticket} with clear review evidence and preserve issue traceability from ${issue.status}.`);
    }
  }, [acceptanceCriteria, prompt, query.data, selectedIssueId, title]);

  if (query.isLoading) {
    // Render a lightweight loading state while intake options are fetched.
    return <LoadingState message="Loading integrated task intake..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the intake request fails.
    return <ErrorState message={query.error ?? 'Task intake options were unavailable.'} />;
  }

  const issueOptions: ReactNode[] = [];
  const repositoryOptions: ReactNode[] = [];
  const documentRows: ReactNode[] = [];
  const integrationCards: ReactNode[] = [];

  // Build the issue selector options from the integrated issue catalog.
  for (const issue of query.data.issues) {
    issueOptions.push(
      <option key={issue.id} value={issue.id}>
        {issue.ticket} - {issue.title}
      </option>,
    );
  }

  // Build the repository selector options from the integrated repo catalog.
  for (const repository of query.data.repositories) {
    repositoryOptions.push(
      <option key={repository.id} value={repository.name}>
        {repository.fullName || repository.name}
      </option>,
    );
  }

  // Render the selected document checkboxes used for task grounding.
  for (const document of query.data.documents) {
    documentRows.push(
      <label className="selection-row" key={document.id}>
        <input
          checked={selectedDocumentIds.includes(document.id)}
          onChange={() => {
            setSelectedDocumentIds(toggleSelection(selectedDocumentIds, document.id));
          }}
          type="checkbox"
        />
        <span>
          <strong>{document.title}</strong>
          <span className="selection-subtitle">{document.path}</span>
        </span>
      </label>,
    );
  }

  // Render the provider integration cards alongside the task form.
  for (const status of query.data.integrationStatuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  /**
   * Submits the intake form and creates a new run-backed task.
   */
  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setSubmitError('');
    setIsSubmitting(true);

    const payload: TaskCreateRequest = {
      issueId: selectedIssueId || undefined,
      repoName: selectedRepoName,
      title,
      prompt,
      acceptanceCriteria,
      documentIds: selectedDocumentIds,
      executionMode,
    };

    try {
      // Create the new AI work item from the integrated intake form.
      const createdRun = await createTask(payload);

      // Navigate directly into the created task detail view.
      navigate(`/tasks/${createdRun.id}`);
    } catch (caughtError) {
      // Surface any backend mutation errors to the intake UI.
      setSubmitError(caughtError instanceof Error ? caughtError.message : 'Unable to create the task.');
    } finally {
      // Mark the form submission as complete after the request settles.
      setIsSubmitting(false);
    }
  }

  // Render the integrated task intake experience.
  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Integrated intake</p>
          <h3>Create a new AI work item from GitHub repo context, Linear issues, and repo markdown knowledge.</h3>
          <p className="muted-copy">This view uses the hybrid integration layer and falls back safely when provider credentials are missing.</p>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.repositories.length} repos</span>
          <span className="pill">{query.data.issues.length} issues</span>
        </div>
      </section>

      <section className="content-grid intake-grid">
        <Panel
          title="Create task"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleSubmit(event); }}>
              <label className="field-group">
                <span>Issue</span>
                <select onChange={(event) => { setSelectedIssueId(event.target.value); }} value={selectedIssueId}>
                  <option value="">No linked issue</option>
                  {issueOptions}
                </select>
              </label>

              <label className="field-group">
                <span>Repository</span>
                <select onChange={(event) => { setSelectedRepoName(event.target.value); }} value={selectedRepoName}>
                  {repositoryOptions}
                </select>
              </label>

              <label className="field-group">
                <span>Execution mode</span>
                <select onChange={(event) => { setExecutionMode(event.target.value); }} value={executionMode}>
                  <option value="implement">Implement</option>
                  <option value="research">Research</option>
                  <option value="review">Review</option>
                  <option value="test">Test</option>
                </select>
              </label>

              <label className="field-group field-group-wide">
                <span>Task title</span>
                <input onChange={(event) => { setTitle(event.target.value); }} placeholder="Build settings workflow" type="text" value={title} />
              </label>

              <label className="field-group field-group-wide">
                <span>Prompt</span>
                <textarea onChange={(event) => { setPrompt(event.target.value); }} rows={5} value={prompt} />
              </label>

              <label className="field-group field-group-wide">
                <span>Acceptance criteria</span>
                <textarea onChange={(event) => { setAcceptanceCriteria(event.target.value); }} rows={4} value={acceptanceCriteria} />
              </label>

              <div className="field-group field-group-wide">
                <span>Knowledge sources</span>
                <div className="selection-list">{documentRows}</div>
              </div>

              {submitError ? <p className="error-copy">{submitError}</p> : null}

              <div className="form-actions">
                <button className="primary-button" disabled={isSubmitting || !selectedRepoName || !title || !prompt} type="submit">
                  {isSubmitting ? 'Creating task...' : 'Create task'}
                </button>
              </div>
            </form>
          }
        />

        <Panel title="Provider readiness" body={<div className="integration-grid">{integrationCards}</div>} />
      </section>
    </div>
  );
}

/**
 * Shows the full evidence package for a single task.
 */
function TaskDetailPage() {
  const params = useParams();
  const runId = params.runId ?? '';
  const query = useApiQuery(() => fetchRunDetail(runId), [runId]);
  const [runOverride, setRunOverride] = useState<RunSummary | null>(null);
  const [decisionNotes, setDecisionNotes] = useState<string>('');
  const [mutationError, setMutationError] = useState<string>('');
  const [isMutating, setIsMutating] = useState<boolean>(false);
  const selectedRun = runOverride ?? query.data;

  if (query.isLoading && !selectedRun) {
    // Render a focused loading state while the selected run is being fetched.
    return <LoadingState message="Loading task detail..." />;
  }

  if ((query.error || !query.data) && !selectedRun) {
    // Render a recoverable error state when the requested run cannot be loaded.
    return <ErrorState message={query.error ?? 'Task detail was unavailable.'} />;
  }

  if (!selectedRun) {
    // Guard against an impossible state where no run payload is available.
    return <ErrorState message="No run data was available for this task." />;
  }

  const activeRun = selectedRun;

  /**
   * Posts an approval decision and stores the updated run payload locally.
   */
  async function handleDecision(decision: ApprovalDecisionRequest['decision']): Promise<void> {
    setMutationError('');
    setIsMutating(true);

    try {
      // Send the approval decision to the backend so the audit history updates.
      const updatedRun = await createApprovalDecision({
        runId: activeRun.id,
        decision,
        notes: decisionNotes,
      });

      // Update the local run state with the server-confirmed result.
      setRunOverride(updatedRun);
    } catch (caughtError) {
      // Surface mutation errors directly in the task detail view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to record the decision.');
    } finally {
      // Mark the mutation as complete after the request settles.
      setIsMutating(false);
    }
  }

  /**
   * Starts or restarts the selected run from the task detail page.
   */
  async function handleRunStart(): Promise<void> {
    setMutationError('');
    setIsMutating(true);

    try {
      // Start or restart the run against the integrated backend workflow surface.
      const updatedRun = await createRun({
        taskId: activeRun.id,
        agentName: 'impl-agent',
        executionMode: 'implement',
      });

      // Keep the local task detail view in sync with the backend response.
      setRunOverride({
        ...activeRun,
        ...updatedRun,
        issue: activeRun.issue,
        pullRequest: activeRun.pullRequest,
        ci: activeRun.ci,
        documents: activeRun.documents,
        requestedBy: activeRun.requestedBy,
        approvalHistory: activeRun.approvalHistory,
      });
    } catch (caughtError) {
      // Surface run start errors directly in the task detail UI.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to start the run.');
    } finally {
      // Mark the mutation as complete after the request settles.
      setIsMutating(false);
    }
  }

  // Present everything the reviewer needs on one page.
  return (
    <div className="page-grid">
      <section className="task-header panel">
        <div>
          <p className="eyebrow">{activeRun.ticket}</p>
          <h3>{activeRun.title}</h3>
          <p className="muted-copy">{activeRun.summary}</p>
          <p className="subtle-copy">
            {activeRun.issue?.ticket ?? activeRun.ticket} · {activeRun.issue?.provider ?? 'fallback'} issue context
          </p>
        </div>

        <div className="task-header-meta">
          <StatusBadge risk={activeRun.risk} status={activeRun.status} />
          <div className="inline-meta">
            <span>{activeRun.repo}</span>
            <span>{activeRun.branch}</span>
            <span>{activeRun.owner}</span>
            <span>{activeRun.cost}</span>
          </div>
        </div>
      </section>

      <section className="task-grid">
        <Panel
          body={
            <div className="stacked-copy">
              <p>Linked issue: {activeRun.issue?.title ?? 'No linked issue'}</p>
              <p>Requested by: {activeRun.requestedBy?.name ?? activeRun.owner}</p>
              <p>Current step: {activeRun.currentStep}</p>
              <p>Runtime: {activeRun.runtime}</p>
            </div>
          }
          title="Context"
        />

        <Panel
          body={
            <div className="stacked-copy">
              <p>Pull request: {activeRun.pullRequest?.status ?? 'Not linked'}</p>
              <p>CI workflow: {activeRun.ci?.workflow ?? 'Unavailable'}</p>
              <p>CI status: {activeRun.ci?.status ?? 'Unavailable'}</p>
              <p>{activeRun.ci?.summary ?? 'No CI summary available.'}</p>
            </div>
          }
          title="Repository and CI"
        />

        <Panel
          body={
            <div className="action-stack">
              <button className="primary-button" disabled={isMutating} onClick={() => { void handleDecision('approve'); }} type="button">
                Approve
              </button>
              <button className="ghost-button" disabled={isMutating} onClick={() => { void handleDecision('retry'); }} type="button">
                Request retry
              </button>
              <button className="ghost-button" disabled={isMutating} onClick={() => { void handleDecision('re-scope'); }} type="button">
                Re-scope task
              </button>
              <button className="ghost-button" disabled={isMutating} onClick={() => { void handleDecision('escalate'); }} type="button">
                Escalate to human
              </button>
              <button className="ghost-button" disabled={isMutating} onClick={() => { void handleRunStart(); }} type="button">
                Start run
              </button>
              <textarea
                className="notes-input"
                onChange={(event) => { setDecisionNotes(event.target.value); }}
                placeholder="Optional approval or retry notes"
                rows={3}
                value={decisionNotes}
              />
              {mutationError ? <p className="error-copy">{mutationError}</p> : null}
            </div>
          }
          title="Decision panel"
        />
      </section>

      <section className="evidence-grid">
        <Panel body={<DetailList items={activeRun.evidence.diff} />} title="Diff highlights" />
        <Panel body={<DetailList items={activeRun.evidence.tests} />} title="Tests" />
        <Panel body={<DetailList items={activeRun.evidence.commands} />} title="Commands" />
        <Panel body={<DetailList items={activeRun.evidence.rationale} />} title="Rationale" />
      </section>

      <section className="task-grid task-grid-wide">
        <Panel
          body={
            <div className="stacked-copy">
              <DetailList items={activeRun.blockers} />
              <p className="subtle-copy">
                PR URL: {activeRun.pullRequest?.url ?? 'Not available'}
              </p>
            </div>
          }
          title="Blockers and risks"
        />
        <Panel
          body={
            <div className="stacked-copy">
              <p>Attached docs</p>
              <DocumentList documents={activeRun.documents ?? []} />
              <p>Approval history</p>
              <ApprovalHistoryList entries={activeRun.approvalHistory ?? []} />
            </div>
          }
          title="Knowledge and audit"
        />
      </section>
    </div>
  );
}

/**
 * Displays the queue of runs waiting for a human decision.
 */
function ApprovalInboxPage() {
  const query = useApiQuery(fetchApprovals, []);

  if (query.isLoading) {
    // Render an inbox loading state while the queue payload is being fetched.
    return <LoadingState message="Loading approval inbox..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the inbox request fails.
    return <ErrorState message={query.error ?? 'Approval queue was unavailable.'} />;
  }

  const queueCards: ReactNode[] = [];

  // Join queue metadata with fetched run summaries for a reviewer-friendly inbox.
  for (const item of query.data.queue) {
    const matchedRun = findRunById(query.data.runs, item);

    if (!matchedRun) {
      // Skip queue records that do not have a matching run payload.
      continue;
    }

    queueCards.push(
      <div className="queue-row" key={item.runId}>
        <div>
          <p className="ticket-code">{matchedRun.ticket}</p>
          <h3>{matchedRun.title}</h3>
          <p className="muted-copy">
            {matchedRun.repo} · Waiting {item.waitingTime} · {item.outcomeNeeded}
          </p>
          <p className="subtle-copy">
            {matchedRun.issue?.provider ?? 'fallback'} issue · {matchedRun.ci?.status ?? 'unknown'} CI
          </p>
        </div>

        <div className="queue-actions">
          <StatusBadge risk={matchedRun.risk} status={matchedRun.status} />
          <Link className="ghost-button link-button" to={`/tasks/${matchedRun.id}`}>
            Open task
          </Link>
        </div>
      </div>,
    );
  }

  // Give reviewers both queue speed and evidence context.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Approval center</p>
          <h3>Review queued runs quickly without losing issue, repo, and CI context.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">Queue: {query.data.summary.queueSize}</span>
          <span className="pill">High risk: {query.data.summary.highRisk}</span>
          <span className="pill">SLA risk: {query.data.summary.slaRisk}</span>
          <span className="pill">Review ready: {query.data.summary.reviewReady}</span>
        </div>
      </section>

      <section className="content-grid approvals-grid">
        <Panel body={<div className="queue-list">{queueCards}</div>} title="Queue" />

        <Panel
          body={
            <div className="stacked-copy">
              <p>Reviewer identity: {query.data.currentUser.name}</p>
              <p>Low-risk approvals can stay in the inbox for fast triage.</p>
              <p>High-risk runs should push reviewers into the full task detail page before approval.</p>
              <p>Rejected runs should capture notes that become future retry guidance.</p>
            </div>
          }
          title="Reviewer guidance"
        />
      </section>
    </div>
  );
}

/**
 * Shows the org and repo policy controls for AI runs.
 */
function PoliciesPage() {
  const query = useApiQuery(fetchPolicies, []);

  if (query.isLoading) {
    // Render a loading panel while the current policy pack is fetched.
    return <LoadingState message="Loading policy pack..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the policy request fails.
    return <ErrorState message={query.error ?? 'Policy data was unavailable.'} />;
  }

  const ruleCards: ReactNode[] = [];

  // Render the policy pack as readable rules instead of dense admin forms.
  for (const rule of query.data.rules) {
    ruleCards.push(
      <div className="policy-row" key={rule.name}>
        <h3>{rule.name}</h3>
        <p className="muted-copy">{rule.value}</p>
      </div>,
    );
  }

  // Emphasize that governance and visibility are core to the product.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Policy center</p>
          <h3>Define what agents can touch, what requires approval, and when runs must stop.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">Scope: {query.data.scope}</span>
          <span className="pill">Policy v{query.data.version}</span>
          <span className="pill">{query.data.rules.length} core rule groups</span>
        </div>
      </section>

      <section className="content-grid approvals-grid">
        <Panel body={<div className="policy-list">{ruleCards}</div>} title="Current rules" />

        <Panel
          body={
            <div className="action-stack">
              <button className="primary-button" type="button">
                Publish policy
              </button>
              <button className="ghost-button" type="button">
                Save draft
              </button>
              <button className="ghost-button" type="button">
                View audit history
              </button>
            </div>
          }
          title="Policy actions"
        />
      </section>
    </div>
  );
}

/**
 * Shows the integration management view.
 */
function IntegrationsPage() {
  const query = useApiQuery(fetchIntegrations, []);
  const integrationCards: ReactNode[] = [];

  if (query.isLoading) {
    // Render a loading state while the provider status payload is fetched.
    return <LoadingState message="Loading provider integrations..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the integrations request fails.
    return <ErrorState message={query.error ?? 'Integration status was unavailable.'} />;
  }

  // Render provider integration cards for all configured categories.
  for (const status of query.data.statuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  // Render the integrations management view.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Integrations</p>
          <h3>See which providers are live, which are using fallbacks, and what capabilities each category unlocks.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.currentUser.provider}</span>
          <span className="pill">{query.data.statuses.length} providers</span>
        </div>
      </section>

      <Panel body={<div className="integration-grid">{integrationCards}</div>} title="Provider status" />
    </div>
  );
}

/**
 * Builds the active nav class based on the current location.
 */
function getNavLinkClassName(pathname: string, targetPath: string): string {
  // Highlight the current section so navigation stays oriented.
  return pathname === targetPath ? 'nav-link active' : 'nav-link';
}

/**
 * Finds the run associated with an approval queue record.
 */
function findRunById(runs: RunSummary[], item: ApprovalItem): RunSummary | null {
  // Search the fetched run list for the queue item's run ID.
  for (const run of runs) {
    if (run.id === item.runId) {
      // Return the first matching run detail for the inbox card.
      return run;
    }
  }

  // Return null when the queue item does not resolve to a run.
  return null;
}

/**
 * Finds an issue by ID from the intake issue catalog.
 */
function findIssueById(issues: IssueRecord[], issueId: string): IssueRecord | null {
  // Search the issue catalog for the selected issue record.
  for (const issue of issues) {
    if (issue.id === issueId) {
      // Return the matching issue record.
      return issue;
    }
  }

  // Return null when the requested issue cannot be found.
  return null;
}

/**
 * Toggles a selection value inside a string array.
 */
function toggleSelection(currentValues: string[], value: string): string[] {
  if (currentValues.includes(value)) {
    // Remove the selected value when it is already present.
    return currentValues.filter((currentValue) => currentValue !== value);
  }

  // Append the value when it is not already selected.
  return [...currentValues, value];
}

/**
 * Builds the sidebar headline from the resolved current user.
 */
function buildUserHeadline(user: CurrentUser | null): string {
  if (!user) {
    // Fall back to a neutral headline when the current user has not loaded yet.
    return 'Loading user';
  }

  // Return the current user's display name for the sidebar summary.
  return user.name;
}

/**
 * Builds the sidebar subtitle from the user query state.
 */
function buildUserSubtitle(user: CurrentUser | null, isLoading: boolean, error: string | null): string {
  if (isLoading) {
    // Explain that the identity layer is still resolving.
    return 'Resolving current identity from the backend integration layer.';
  }

  if (error) {
    // Surface a readable error description when the identity request fails.
    return error;
  }

  if (!user) {
    // Fall back to a neutral subtitle when no user payload is available.
    return 'No identity payload available.';
  }

  // Return the resolved role and provider for the sidebar summary.
  return `${user.email} · ${user.role} · ${user.provider}`;
}

/**
 * Renders a compact status and risk badge.
 */
function StatusBadge(props: { status: RunStatus; risk: RiskLevel }) {
  const statusClassName = `status-badge status-${props.status.toLowerCase()} risk-${props.risk.toLowerCase()}`;

  // Keep status and risk together because both inform reviewer urgency.
  return <span className={statusClassName}>{props.status} · {props.risk}</span>;
}

/**
 * Renders a small metric summary card.
 */
function MetricCard(props: DashboardMetric) {
  // Make dashboard metrics scannable at a glance.
  return (
    <article className="metric-card">
      <p className="metric-label">{props.label}</p>
      <p className="metric-value">{props.value}</p>
      <p className="muted-copy">{props.hint}</p>
    </article>
  );
}

/**
 * Renders a provider integration status card.
 */
function IntegrationStatusCard(props: { status: IntegrationStatus }) {
  const capabilityItems: ReactNode[] = [];

  // Render each capability as a scan-friendly list item.
  for (const capability of props.status.capabilities) {
    capabilityItems.push(<li key={capability}>{capability}</li>);
  }

  // Return the provider integration status card.
  return (
    <article className="integration-card">
      <div className="integration-card-header">
        <div>
          <p className="ticket-code">{props.status.name}</p>
          <h3>{props.status.connected ? 'Connected' : 'Fallback mode'}</h3>
        </div>
        <span className={`pill integration-pill integration-pill-${props.status.mode}`}>{props.status.mode}</span>
      </div>
      <p className="muted-copy">{props.status.details}</p>
      <ul className="detail-list compact-list">{capabilityItems}</ul>
      <p className="subtle-copy">Checked: {props.status.checkedAt}</p>
    </article>
  );
}

/**
 * Renders a shared loading panel for route-level data fetches.
 */
function LoadingState(props: { message: string }) {
  // Keep loading feedback consistent across screens that fetch backend data.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Loading</p>
      <h3>{props.message}</h3>
      <p className="muted-copy">The UI is waiting for the FastAPI integration layer to respond.</p>
    </section>
  );
}

/**
 * Renders a shared error panel for route-level data fetches.
 */
function ErrorState(props: { message: string }) {
  // Keep failed requests visible without breaking the surrounding shell.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Request failed</p>
      <h3>Unable to load this control-pane view.</h3>
      <p className="muted-copy">{props.message}</p>
    </section>
  );
}

/**
 * Renders a simple unordered list for evidence and blocker sections.
 */
function DetailList(props: { items: string[] }) {
  const listItems: ReactNode[] = [];

  // Convert each string entry into a consistently styled list item.
  for (const item of props.items) {
    listItems.push(<li key={item}>{item}</li>);
  }

  // Return the rendered detail list for the surrounding panel.
  return <ul className="detail-list">{listItems}</ul>;
}

/**
 * Renders the attached document list for a task.
 */
function DocumentList(props: { documents: DocumentRecord[] }) {
  if (props.documents.length === 0) {
    // Return a neutral placeholder when no documents are attached.
    return <p className="muted-copy">No documents were attached to this task.</p>;
  }

  const documentItems: ReactNode[] = [];

  // Render each attached document as a simple scan-friendly row.
  for (const document of props.documents) {
    documentItems.push(
      <div className="mini-row" key={document.id}>
        <strong>{document.title}</strong>
        <span className="subtle-copy">{document.path}</span>
      </div>,
    );
  }

  // Return the rendered document list.
  return <div className="mini-list">{documentItems}</div>;
}

/**
 * Renders the approval history list for a task.
 */
function ApprovalHistoryList(props: { entries: RunSummary['approvalHistory'] }) {
  if (!props.entries || props.entries.length === 0) {
    // Return a neutral placeholder when there is no approval history yet.
    return <p className="muted-copy">No approval actions have been recorded yet.</p>;
  }

  const historyItems: ReactNode[] = [];

  // Render each approval record with its acting user and timestamp.
  for (const entry of props.entries) {
    historyItems.push(
      <div className="mini-row" key={`${entry.timestamp}-${entry.decision}`}>
        <strong>{entry.decision}</strong>
        <span className="subtle-copy">
          {entry.actor.name} · {entry.actor.role} · {entry.timestamp}
        </span>
        {entry.notes ? <span className="muted-copy">{entry.notes}</span> : null}
      </div>,
    );
  }

  // Return the rendered approval history list.
  return <div className="mini-list">{historyItems}</div>;
}

/**
 * Wraps page sections in a consistent panel treatment.
 */
function Panel(props: { title: string; body: ReactNode }) {
  // Keep content framing consistent across dashboard, review, and policy views.
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>{props.title}</h3>
      </div>
      <div className="panel-body">{props.body}</div>
    </section>
  );
}

export default App;
