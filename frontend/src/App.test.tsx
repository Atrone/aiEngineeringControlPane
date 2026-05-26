import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import {
  App,
  DashboardPage,
  IntegrationsPage,
  TaskDetailPage,
  WorkIntakePage,
} from './App';
import {
  AccessDeniedState,
  DetailList,
  DocumentList,
  ErrorState,
  EvidenceTabPanel,
  IntegrationStatusCard,
  LoadingState,
  LogStream,
  MetricCard,
  Panel,
  StandaloneStatePanel,
  StatusBadge,
  TimelineList,
} from './components/ui';
import {
  ApprovalHistoryList,
  PullRequestPanelBody,
  RunTraceabilityGraphPanelBody,
  TaskDecisionPanelBody,
  TaskImplementationPackagePanelBody,
} from './components/run/TaskPanels';
import {
  GoogleAuthCallbackPage,
  GoogleOAuthReturnPage,
  LandingPage,
  RoleGate,
  RootLayout,
  SignInPage,
} from './pages/AuthPages';
import { mergeDashboardBlockedReasonLists } from './lib/dashboardHelpers';
import * as api from './lib/api';
import { useApiQuery } from './hooks/useApiQuery';
import type { DashboardPayload } from './types/controlPane';
import { createRunFixture, currentUser, documentRecord, integrationStatus, issue, liveView } from './test/fixtures';


vi.mock('./lib/api', () => ({
  beginGoogleSignIn: vi.fn(),
  classifyIntakeIssuesByScope: vi.fn(),
  clearSessionToken: vi.fn(),
  connectCursor: vi.fn(),
  connectGitHub: vi.fn(),
  connectJira: vi.fn(),
  connectLinear: vi.fn(),
  createApprovalDecision: vi.fn(),
  createTask: vi.fn(),
  enrichIntakeField: vi.fn(),
  exchangeGoogleAuthCode: vi.fn(),
  fetchApprovals: vi.fn(),
  fetchAuthConfig: vi.fn(),
  fetchCurrentUser: vi.fn(),
  fetchDashboard: vi.fn(),
  fetchDashboardReviewEfforts: vi.fn(),
  fetchDashboardSuggestedActions: vi.fn(),
  fetchIntegrations: vi.fn(),
  fetchIntakeOptions: vi.fn(),
  fetchRunDetail: vi.fn(),
  hasSessionToken: vi.fn(),
  identifyRepositoryForIssue: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('./hooks/useApiQuery', () => ({
  useApiQuery: vi.fn(),
}));


/**
 * Renders a component inside a MemoryRouter for route-aware component tests.
 */
function renderWithRouter(element: ReactElement, initialPath = '/dashboard'): void {
  // Render through MemoryRouter so links, navigation, and route hooks have context.
  render(<MemoryRouter initialEntries={[initialPath]}>{element}</MemoryRouter>);
}

/**
 * Returns the mocked hook function with a precise Vitest mock type.
 */
function mockedUseApiQuery(): Mock {
  // Cast once so tests can set return values without repeating type assertions.
  return useApiQuery as unknown as Mock;
}


describe('App presentational component functions', () => {
  it('renders badge, cards, state panels, lists, and panels', () => {
    render(
      <div>
        <StatusBadge risk="High" status="Blocked" />
        <MetricCard hint="2 running" label="Active runs" value="2" />
        <IntegrationStatusCard status={integrationStatus} />
        <LoadingState message="Loading mission control data..." />
        <ErrorState message="Broken request" />
        <StandaloneStatePanel body="Body copy" eyebrow="Eyebrow" title="Standalone title" />
        <AccessDeniedState currentUser={currentUser} title="Settings" />
        <DetailList items={['One', 'Two']} />
        <DocumentList documents={[documentRecord]} />
        <Panel body={<p>Panel body</p>} title="Panel title" />
      </div>,
    );

    expect(screen.getByText('Blocked · High')).toBeInTheDocument();
    expect(screen.getByText('Active runs')).toBeInTheDocument();
    expect(screen.getByText('GitHub')).toBeInTheDocument();
    expect(screen.getByText('Loading mission control data...')).toBeInTheDocument();
    expect(screen.getByText('Broken request')).toBeInTheDocument();
    expect(screen.getByText('Standalone title')).toBeInTheDocument();
    expect(screen.getByText('Settings is limited to reviewers.')).toBeInTheDocument();
    expect(screen.getByText('Runbook')).toBeInTheDocument();
    expect(screen.getByText('Panel body')).toBeInTheDocument();
  });

  it('renders timeline, logs, evidence tabs, approval history, PR body, and reference links', () => {
    const onTabChange = vi.fn();
    const run = createRunFixture();

    render(
      <div>
        <TimelineList entries={liveView.timeline} liveLabel="Streaming" />
        <LogStream entries={liveView.logs} />
        <EvidenceTabPanel activeTab="diff" liveView={liveView} onTabChange={onTabChange} />
        <ApprovalHistoryList entries={run.approvalHistory} />
        <PullRequestPanelBody run={run} />
        <TaskImplementationPackagePanelBody run={run} />
        <RunTraceabilityGraphPanelBody run={run} />
      </div>,
    );

    expect(screen.getByText('Started')).toBeInTheDocument();
    expect(screen.getByText('Tests passed.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Tests (1)' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Tests (1)' }));
    expect(onTabChange).toHaveBeenCalledWith('tests');
    expect(screen.getByText('Reviewer approved')).toBeInTheDocument();
    expect(screen.getByText('Pull request:')).toBeInTheDocument();
    expect(screen.getByText('Issue traceability')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Run traceability graph' })).toBeInTheDocument();
    expect(screen.getByText('Merge/deploy status')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open repository' })).toHaveAttribute('href', 'https://github.com/octo/repo');
    expect(screen.getByRole('link', { name: 'Open branch' })).toHaveAttribute('href', 'https://github.com/octo/repo/tree/feature%2Fdashboard');
    expect(screen.getByRole('link', { name: 'Open Cursor agent run' })).toHaveAttribute('href', 'https://cursor.example.com/agents/1');
    expect(screen.getByRole('link', { name: 'Open PR commits' })).toHaveAttribute('href', 'https://github.com/octo/repo/pull/42/commits');
    expect(screen.getByRole('link', { name: 'Open test evidence' })).toHaveAttribute('href', 'https://ci.example.com/build/1');
  });

  it('renders empty states for list-oriented components', () => {
    render(
      <div>
        <TimelineList entries={[]} liveLabel="Idle" />
        <LogStream entries={[]} />
        <DocumentList documents={[]} />
        <ApprovalHistoryList entries={[]} />
        <TaskImplementationPackagePanelBody run={createRunFixture({ issue: undefined, pullRequest: undefined, ci: undefined, cloudAgent: undefined, evidence: { diff: [], tests: [], commands: [], rationale: [] } })} />
      </div>,
    );

    expect(screen.getByText('No timeline data is available for this run yet.')).toBeInTheDocument();
    expect(screen.getByText('No streamed logs have been captured for this run yet.')).toBeInTheDocument();
    expect(screen.getByText('No documents were attached to this task.')).toBeInTheDocument();
    expect(screen.getByText('No approval actions have been recorded yet.')).toBeInTheDocument();
    expect(screen.getByText('No task-specific reference links are available for this run yet.')).toBeInTheDocument();
  });
});

describe('App route and page component functions', () => {
  beforeEach(() => {
    // Reset API and hook mocks before rendering stateful routed components.
    vi.clearAllMocks();
    vi.mocked(api.hasSessionToken).mockReturnValue(false);
    vi.mocked(api.fetchAuthConfig).mockResolvedValue({ googleSsoEnabled: false, guidedSignInEnabled: true });
    vi.mocked(api.signIn).mockResolvedValue({ sessionToken: 'token', currentUser });
    vi.mocked(api.signOut).mockResolvedValue();
    vi.mocked(api.fetchDashboardReviewEfforts).mockResolvedValue({
      reviewEfforts: [{ runId: 'run-1', effortMinutes: 18, label: 'Moderate review', confidence: 0.8, rationale: 'Clear UI PR summary.', source: 'openai' }],
      model: 'test-model',
      runCount: 1,
    });
    vi.mocked(api.fetchDashboardSuggestedActions).mockResolvedValue({ suggestedActions: ['Review blocked runs'], model: 'test-model', runCount: 1 });
    mockedUseApiQuery().mockReturnValue({ data: null, error: null, isLoading: true });
  });

  it('renders the public landing page before sign-in', () => {
    renderWithRouter(<LandingPage />, '/');

    expect(screen.getByText('Coordinate AI work across team servers.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Enter command center' })).toHaveAttribute('href', '/sign-in');
    expect(screen.getByRole('link', { name: 'See how it works' })).toHaveAttribute('href', '#landing-workflow');
    expect(screen.getByRole('heading', { name: 'From request to reviewed pull request in one command center.' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Run Channels lobby showing servers, run metrics, and suggested next actions.' })).toHaveAttribute('src', '/landing-run-channels.png');

    fireEvent.click(screen.getByRole('button', { name: 'Enlarge Run lobby screenshot' }));
    expect(screen.getByRole('dialog', { name: 'Run lobby screenshot preview' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Expanded Run Channels lobby showing servers, run metrics, and suggested next actions.' })).toHaveAttribute('src', '/landing-run-channels.png');

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog', { name: 'Run lobby screenshot preview' })).not.toBeInTheDocument();
  });

  it('renders App signed-out flow and SignInPage submit behavior', async () => {
    renderWithRouter(<App />, '/');

    expect(screen.getByText('Coordinate AI work across team servers.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Enter command center' }));

    await waitFor(() => {
      expect(screen.getByText('Sign in to enter the command center.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Enter command center' }));

    await waitFor(() => {
      expect(api.signIn).toHaveBeenCalledWith({ name: 'Maya Chen', email: 'maya.chen@example.com', role: 'admin', teamId: 'platform' });
    });
  });

  it('renders SignInPage Google flow when SSO is enabled', async () => {
    vi.mocked(api.fetchAuthConfig).mockResolvedValue({ googleSsoEnabled: true, guidedSignInEnabled: false });

    renderWithRouter(<SignInPage onSignedIn={vi.fn()} />, '/sign-in');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
    expect(api.beginGoogleSignIn).toHaveBeenCalledWith('platform');
  });

  it('renders RootLayout, handles sign out, and gates roles', async () => {
    const onSignedOut = vi.fn().mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Routes>
          <Route element={<RootLayout currentUser={currentUser} onSignedOut={onSignedOut} />}>
            <Route element={<p>Nested settings</p>} path="/settings" />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Nested settings')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(onSignedOut).toHaveBeenCalled();
    });

    render(<RoleGate allowedRoles={['admin']} currentUser={currentUser} title="Settings"><p>Allowed</p></RoleGate>);
    expect(screen.getByText('Allowed')).toBeInTheDocument();
  });

  it('renders Google callback error state without exchanging a code', async () => {
    render(
      <MemoryRouter initialEntries={['/auth/callback?error=access_denied']}>
        <Routes>
          <Route element={<GoogleAuthCallbackPage onSignedIn={vi.fn()} />} path="/auth/callback" />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('access_denied')).toBeInTheDocument();
    });
    expect(api.exchangeGoogleAuthCode).not.toHaveBeenCalled();
  });

  it('forwards Google OAuth return parameters to the backend callback route', async () => {
    const originalLocation = window.location;
    const replaceMock = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, replace: replaceMock },
    });

    renderWithRouter(<GoogleOAuthReturnPage />, '/auth/google/callback?code=oauth-code&state=state-1');

    expect(screen.getByText('Redirecting your callback...')).toBeInTheDocument();
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith('/api/auth/google/callback?code=oauth-code&state=state-1');
    });

    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
  });

  it('renders dashboard data and requests suggested actions', async () => {
    const run = createRunFixture();
    const dashboard: DashboardPayload = {
      metrics: [],
      runs: [run],
      blockedReasons: ['Failing integration test'],
      suggestedActions: [],
      integrationStatuses: [integrationStatus],
      currentUser,
    };
    mockedUseApiQuery().mockReturnValue({ data: dashboard, error: null, isLoading: false });

    renderWithRouter(<DashboardPage />, '/dashboard');

    expect(screen.getByText('Pick a server, use channel filters to narrow runs, then open the run room for evidence and review.')).toBeInTheDocument();
    expect(screen.getByLabelText('Search tasks')).toBeInTheDocument();
    expect(screen.getByText('Failing integration test')).toBeInTheDocument();
    await waitFor(() => {
      expect(api.fetchDashboardSuggestedActions).toHaveBeenCalledWith({ runIds: ['run-1'] });
    });
    await waitFor(() => {
      expect(api.fetchDashboardReviewEfforts).toHaveBeenCalledWith({ runIds: ['run-1'] });
    });

    const suggestionsTitle = await screen.findByText('Suggested next actions');
    const teamWorkspace = screen.getByRole('region', { name: 'server run workspace' });
    const openRunRoomLink = screen.getByRole('link', { name: 'Open run room' });
    const pullRequestContent = screen.getByRole('region', { name: 'Open pull request content' });

    expect(screen.queryByText(/Model:/i)).not.toBeInTheDocument();
    expect(suggestionsTitle.compareDocumentPosition(teamWorkspace) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Artifact results')).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Run traceability graph for ACP-1' })).toBeInTheDocument();
    expect(screen.getByText(/Moderate review/)).toBeInTheDocument();
    expect(screen.getByText('Build dashboard PR')).toBeInTheDocument();
    expect(screen.getByText(/Adds the dashboard implementation/)).toBeInTheDocument();
    expect(pullRequestContent.compareDocumentPosition(openRunRoomLink) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(openRunRoomLink).toBeInTheDocument();
  });

  it('totals OpenAI review effort from runs in the selected lobby only', async () => {
    const platformReviewRun = createRunFixture({ runtime: '02:30' });
    const platformBlockedRun = createRunFixture({
      id: 'run-2',
      ticket: 'ACP-2',
      status: 'Blocked',
      blockers: ['Missing API key'],
      issue: { ...issue, id: 'issue-2', ticket: 'ACP-2', url: 'https://linear.example.com/issue/ACP-2' },
      runtime: '03:00',
    });
    const opsRun = createRunFixture({
      id: 'run-3',
      ticket: 'OPS-1',
      issue: { ...issue, id: 'issue-3', ticket: 'OPS-1', url: 'https://linear.example.com/issue/OPS-1' },
      runtime: '10:00',
      requestedBy: { ...currentUser, teamId: 'ops' },
    });
    const dashboard: DashboardPayload = {
      metrics: [],
      runs: [platformReviewRun, platformBlockedRun, opsRun],
      blockedReasons: [],
      suggestedActions: [],
      integrationStatuses: [integrationStatus],
      currentUser,
    };
    mockedUseApiQuery().mockReturnValue({ data: dashboard, error: null, isLoading: false });
    vi.mocked(api.fetchDashboardReviewEfforts).mockResolvedValue({
      reviewEfforts: [
        { runId: 'run-1', effortMinutes: 12, label: 'Moderate review', confidence: 0.7, rationale: 'Small scoped PR.', source: 'openai' },
        { runId: 'run-2', effortMinutes: 25, label: 'Moderate review', confidence: 0.6, rationale: 'Needs blocker follow-up.', source: 'openai' },
      ],
      model: 'test-model',
      runCount: 2,
    });

    renderWithRouter(<DashboardPage />, '/dashboard');

    expect(await screen.findByText('37 min')).toBeInTheDocument();
    expect(screen.getByText('OpenAI PR-summary guesses across 2 runs in this lobby')).toBeInTheDocument();
    await waitFor(() => {
      expect(api.fetchDashboardReviewEfforts).toHaveBeenCalledWith({ runIds: ['run-1', 'run-2'] });
    });
    expect(screen.getByRole('list', { name: 'Run traceability graph for ACP-1' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Run traceability graph for ACP-2' })).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Run traceability graph for OPS-1' })).not.toBeInTheDocument();
    expect(api.fetchDashboardReviewEfforts).not.toHaveBeenCalledWith({ runIds: ['run-1', 'run-2', 'run-3'] });
  });

  it('narrows mission control channels when the operator types in the search field', async () => {
    const platformReviewRun = createRunFixture({ runtime: '02:30' });
    const platformBlockedRun = createRunFixture({
      id: 'run-2',
      ticket: 'ACP-2',
      title: 'OAuth callback',
      status: 'Blocked',
      blockers: ['Missing API key'],
      issue: { ...issue, id: 'issue-2', ticket: 'ACP-2', url: 'https://linear.example.com/issue/ACP-2' },
      runtime: '03:00',
    });
    const dashboard: DashboardPayload = {
      metrics: [],
      runs: [platformReviewRun, platformBlockedRun],
      blockedReasons: [],
      suggestedActions: [],
      integrationStatuses: [integrationStatus],
      currentUser,
    };
    mockedUseApiQuery().mockReturnValue({ data: dashboard, error: null, isLoading: false });
    vi.mocked(api.fetchDashboardReviewEfforts).mockResolvedValue({
      reviewEfforts: [
        { runId: 'run-1', effortMinutes: 12, label: 'Moderate review', confidence: 0.7, rationale: 'Small scoped PR.', source: 'openai' },
        { runId: 'run-2', effortMinutes: 25, label: 'Moderate review', confidence: 0.6, rationale: 'Needs blocker follow-up.', source: 'openai' },
      ],
      model: 'test-model',
      runCount: 2,
    });

    renderWithRouter(<DashboardPage />, '/dashboard');

    await waitFor(() => {
      expect(api.fetchDashboardReviewEfforts).toHaveBeenCalledWith({ runIds: ['run-1', 'run-2'] });
    });

    fireEvent.change(screen.getByLabelText('Search tasks'), { target: { value: 'ACP-2' } });

    await waitFor(() => {
      expect(api.fetchDashboardReviewEfforts).toHaveBeenCalledWith({ runIds: ['run-2'] });
    });

    expect(screen.queryByRole('link', { name: /ACP-1:/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /ACP-2:/ })).toBeInTheDocument();
  });

  it('merges dashboard blocked reason lists without duplicates', () => {
    const runs = [
      createRunFixture({
        id: 'blocked-run',
        status: 'Blocked',
        blockers: ['Missing API key', 'none'],
        currentStep: 'Waiting for reviewer decision',
      }),
    ];

    // Prefer backend ordering while folding in actionable run-derived reasons once.
    expect(
      mergeDashboardBlockedReasonLists(['Failing integration test', 'failing integration test'], runs),
    ).toEqual(['Failing integration test', 'Missing API key']);
  });

  it('renders loading states for data-backed page components', () => {
    mockedUseApiQuery().mockReturnValue({ data: null, error: null, isLoading: true });

    renderWithRouter(
      <div>
        <WorkIntakePage />
        <IntegrationsPage currentUser={currentUser} />
      </div>,
      '/intake',
    );

    expect(screen.getByText('Loading integrated task intake...')).toBeInTheDocument();
    expect(screen.getByText('Loading provider integrations...')).toBeInTheDocument();

    render(
      <MemoryRouter initialEntries={['/tasks/run-1']}>
        <Routes>
          <Route element={<TaskDetailPage />} path="/tasks/:runId" />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Loading task detail...')).toBeInTheDocument();
  });

  it('renders the agent delegation brief with intake fields on task detail', async () => {
    const run = createRunFixture({
      acceptanceCriteria: '- [ ] Custom criterion',
      taskPrompt: 'Custom prompt body.',
      executionMode: 'test',
    });
    mockedUseApiQuery().mockReturnValue({ data: run, error: null, isLoading: false });

    render(
      <MemoryRouter initialEntries={['/tasks/run-1']}>
        <Routes>
          <Route element={<TaskDetailPage />} path="/tasks/:runId" />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'Agent delegation brief' })).toBeInTheDocument();
    expect(screen.getByText('- [ ] Custom criterion')).toBeInTheDocument();
    expect(screen.getByText('Custom prompt body.')).toBeInTheDocument();
    expect(screen.getByText(/Test — focus on validation/i)).toBeInTheDocument();
    expect(screen.getByText('acme/control-pane')).toBeInTheDocument();
  });

  it('submits selected repository docs from the intake page by default', async () => {
    mockedUseApiQuery().mockImplementation((queryFn) => {
      if (queryFn === api.fetchIntakeOptions) {
        // Return the intake payload with one selected-repo doc and one unrelated repo doc.
        return {
          data: {
            repositories: [{ id: 'platform-web', name: 'platform-web', fullName: 'acme/platform-web', defaultBranch: 'main', private: false, provider: 'github', url: '' }],
            issues: [],
            documents: [
              { ...documentRecord, id: 'doc-platform', repoName: 'platform-web' },
              { ...documentRecord, id: 'doc-api', repoName: 'api-service' },
            ],
            currentUser,
            integrationStatuses: [integrationStatus],
          },
          error: null,
          isLoading: false,
        };
      }

      // Return empty scope results for the issue-scoping query.
      return { data: { wellScopedIssueIds: [], poorlyScopedIssueIds: [] }, error: null, isLoading: false };
    });
    vi.mocked(api.createTask).mockResolvedValue(createRunFixture({ id: 'created-run' }));

    renderWithRouter(<WorkIntakePage />, '/intake');
    await screen.findByText('1 docs from acme/platform-web\'s docs folder will be attached before uploads are added.');

    fireEvent.change(screen.getByLabelText('Task title'), { target: { value: 'Create task' } });
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Implement with selected docs.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create task and start run' }));

    await waitFor(() => {
      expect(api.createTask).toHaveBeenCalledWith(expect.objectContaining({ documentIds: ['doc-platform'] }));
    });
  });

  it('submits reviewer decisions through TaskDecisionPanelBody', async () => {
    const run = createRunFixture({ cloudAgent: undefined, pullRequest: undefined });
    const updatedRun = createRunFixture({ status: 'Approved' });
    const onRunUpdated = vi.fn();
    vi.mocked(api.createApprovalDecision).mockResolvedValue(updatedRun);

    render(<TaskDecisionPanelBody onRunUpdated={onRunUpdated} run={run} />);
    fireEvent.change(screen.getByLabelText('Reviewer notes'), { target: { value: 'Ship it.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(api.createApprovalDecision).toHaveBeenCalledWith({ runId: 'run-1', decision: 'approve', notes: 'Ship it.' });
    });
    expect(onRunUpdated).toHaveBeenCalledWith(updatedRun);
    expect(screen.getByText('Task approved. The dashboard will show it as approved when you return.')).toBeInTheDocument();
  });

  it('links approval control to the current pull request when available', () => {
    const run = createRunFixture();

    render(<TaskDecisionPanelBody onRunUpdated={vi.fn()} run={run} />);

    expect(screen.getByText('Open the current pull request to approve the work in GitHub; the run room will sync the PR review state.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Approve' })).toHaveAttribute('href', 'https://github.com/octo/repo/pull/42');
  });
});