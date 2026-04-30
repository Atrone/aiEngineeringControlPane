import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import {
  AccessDeniedState,
  App,
  ApprovalHistoryList,
  ArtifactResultsPanelBody,
  DashboardPage,
  DetailList,
  DocumentList,
  ErrorState,
  EvidenceTabPanel,
  GoogleAuthCallbackPage,
  GoogleOAuthReturnPage,
  IntegrationStatusCard,
  IntegrationsPage,
  LoadingState,
  LogStream,
  MetricCard,
  Panel,
  PullRequestPanelBody,
  RoleGate,
  RootLayout,
  SignInPage,
  StandaloneStatePanel,
  StatusBadge,
  TaskDecisionPanelBody,
  TaskDetailPage,
  TaskImplementationPackagePanelBody,
  TimelineList,
  WorkIntakePage,
  buildApprovalDecisionLabel,
  buildApprovalSourceLabel,
  buildEnrichmentSourceLabel,
  buildEvidenceStatusClassName,
  buildEvidenceTabLabel,
  buildIssueTrackerRunLabel,
  buildLogEntryClassName,
  buildPullRequestStateLabel,
  buildReviewEffortLabel,
  buildRoleCapabilityItems,
  buildRoleLabel,
  buildRunTeamGroups,
  buildRunTeamKey,
  buildShellPageTitle,
  buildTeamHoverLabel,
  buildTeamInitials,
  buildTimelineEntryClassName,
  buildUploadedDocumentRecord,
  buildUserHeadline,
  buildUserSubtitle,
  canAccessRole,
  collectBlockerReasons,
  collectTaskDetailReferenceLinks,
  deriveDashboardMetrics,
  exchangeGoogleAuthCodeOnce,
  extractUrlsFromText,
  extractCursorAgentIdFromRun,
  findIntegrationStatus,
  findIssueById,
  formatArtifactSize,
  formatEventTime,
  formatReviewEffortValue,
  getConnectionValue,
  getNavLinkClassName,
  getRunChannelTone,
  isActionableBlocker,
  isIssueTrackerProvider,
  isIssueTrackerRun,
  parseRuntimeSeconds,
  resolveCurrentPullRequestUrl,
} from './App';
import * as api from './lib/api';
import { useApiQuery } from './hooks/useApiQuery';
import type {
  CurrentUser,
  DashboardPayload,
  DocumentRecord,
  IntegrationStatus,
  IssueRecord,
  RunLiveView,
  RunSummary,
  UploadedDocumentRecord,
} from './types/controlPane';

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
  fetchDashboardSuggestedActions: vi.fn(),
  fetchCursorAgentArtifactResults: vi.fn(),
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

const currentUser: CurrentUser = {
  name: 'Maya Chen',
  email: 'maya@example.com',
  role: 'admin',
  teamId: 'platform',
  provider: 'guided',
};

const issue: IssueRecord = {
  id: 'issue-1',
  ticket: 'ACP-1',
  title: 'Build dashboard',
  description: 'Create the dashboard view.',
  priority: 'High',
  status: 'Open',
  url: 'https://linear.example.com/issue/ACP-1',
  assignee: { name: 'Maya Chen', email: 'maya@example.com' },
  provider: 'linear',
};

const documentRecord: DocumentRecord = {
  id: 'doc-1',
  title: 'Runbook',
  path: 'docs/runbook.md',
  source: 'repo',
  updatedAt: '2026-04-28T10:00:00.000Z',
};

const integrationStatus: IntegrationStatus = {
  id: 'github',
  name: 'GitHub',
  mode: 'live',
  connected: true,
  capabilities: ['Pull requests'],
  configured: true,
  details: 'GitHub is connected.',
  requiredRole: 'admin',
  recommendedAction: 'Keep the token fresh.',
  connection: { label: 'octo-org', values: { owner: 'octo-org', repositories: 'repo' } },
  checkedAt: '2026-04-28T10:00:00.000Z',
};

const liveView: RunLiveView = {
  isLive: true,
  statusLabel: 'Streaming',
  lastUpdatedAt: '2026-04-28T10:05:00.000Z',
  timeline: [{ id: 'step-1', title: 'Started', detail: 'Agent started.', timestamp: '2026-04-28T10:00:00.000Z', status: 'active' }],
  logs: [{ id: 'log-1', timestamp: '2026-04-28T10:01:00.000Z', level: 'success', source: 'agent', message: 'Tests passed.' }],
  evidenceTabs: {
    diff: [{ id: 'diff-1', timestamp: '2026-04-28T10:02:00.000Z', summary: 'Changed App', detail: 'Updated UI.', status: 'captured' }],
    tests: [{ id: 'test-1', timestamp: '2026-04-28T10:03:00.000Z', summary: 'Unit tests', detail: 'Vitest passed.', status: 'running' }],
    rationale: [{ id: 'why-1', timestamp: '2026-04-28T10:04:00.000Z', summary: 'Reasoning', detail: 'Safer flow.', status: 'blocked' }],
  },
};

/**
 * Builds a complete run payload with optional targeted overrides.
 */
function createRunFixture(overrides: Partial<RunSummary> = {}): RunSummary {
  // Return a full RunSummary so components can render without defensive test shims.
  return {
    id: 'run-1',
    ticket: 'ACP-1',
    title: 'Build dashboard',
    repo: 'control-pane',
    branch: 'feature/dashboard',
    owner: 'Platform Team',
    agent: 'Cursor',
    runtime: '02:30',
    cost: '$1.25',
    status: 'Review',
    risk: 'Medium',
    currentStep: 'Waiting for reviewer decision',
    summary: 'Dashboard implementation is ready for review.',
    evidence: {
      diff: ['Preview at https://preview.example.com.'],
      tests: ['CI at https://ci.example.com/build/1'],
      commands: ['npm test'],
      rationale: ['Docs at https://docs.example.com/runbook'],
    },
    blockers: ['Needs approval'],
    issue,
    pullRequest: {
      number: '42',
      status: 'open',
      state: 'open',
      url: 'https://github.com/octo/repo/pull/42',
      approved: true,
      approvedAt: '2026-04-28T10:06:00.000Z',
      approvedBy: 'Reviewer',
      merged: false,
      mergedAt: null,
      source: 'github',
    },
    ci: {
      workflow: 'CI',
      status: 'passed',
      summary: 'Build passed at https://ci.example.com/build/1.',
    },
    documents: [documentRecord],
    requestedBy: currentUser,
    approvalHistory: [{
      decision: 'approve',
      source: 'reviewer',
      notes: 'Looks good.',
      actor: currentUser,
      timestamp: '2026-04-28T10:07:00.000Z',
    }],
    cloudAgent: {
      id: 'agent-1',
      status: 'completed',
      target: {
        url: 'https://cursor.example.com/agents/1',
        prUrl: 'https://github.com/octo/repo/pull/42',
      },
    },
    liveView,
    ...overrides,
  };
}

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

describe('App pure helper functions', () => {
  beforeEach(() => {
    // Reset mocked API calls before helpers that depend on imported API bindings.
    vi.clearAllMocks();
  });

  it('deduplicates Google auth code exchanges during a page load', async () => {
    vi.mocked(api.exchangeGoogleAuthCode).mockResolvedValue({ sessionToken: 'token', currentUser });

    const first = exchangeGoogleAuthCodeOnce('code-one');
    const second = exchangeGoogleAuthCodeOnce('code-one');

    await expect(Promise.all([first, second])).resolves.toEqual([
      { sessionToken: 'token', currentUser },
      { sessionToken: 'token', currentUser },
    ]);
    expect(api.exchangeGoogleAuthCode).toHaveBeenCalledTimes(1);
  });

  it('builds uploaded document records from browser files', async () => {
    const file = new File(['hello'], 'notes.md', { type: 'text/markdown', lastModified: 1000 });

    const record = await buildUploadedDocumentRecord(file);

    expect(record).toMatchObject({
      id: 'upload-notes.md-1000-5',
      title: 'notes',
      path: 'uploads/notes.md',
      source: 'uploaded_repo_document',
      content: 'hello',
    });
  });

  it('covers dashboard, blocker, runtime, and team helpers', () => {
    const reviewRun = createRunFixture();
    const blockedRun = createRunFixture({ id: 'run-2', status: 'Blocked', blockers: ['Missing API key'], owner: '', repo: 'fallback-repo', runtime: '03:00' });
    const mergedRun = createRunFixture({ id: 'run-3', status: 'Merged', blockers: [], runtime: '01:00' });

    expect(buildEnrichmentSourceLabel([])).toBe('repo docs');
    expect(buildEnrichmentSourceLabel([{} as UploadedDocumentRecord])).toBe('uploaded docs');
    expect(isActionableBlocker('No active blockers')).toBe(false);
    expect(isActionableBlocker('Missing API key')).toBe(true);
    expect(parseRuntimeSeconds('02:30')).toBe(150);
    expect(parseRuntimeSeconds('bad')).toBe(0);
    expect(collectBlockerReasons([blockedRun, reviewRun])).toEqual(new Set(['Missing API key']));
    expect(formatReviewEffortValue(0, 0)).toBe('0 min');
    expect(formatReviewEffortValue(2, 240)).toBe('2 min');
    expect(deriveDashboardMetrics([reviewRun, blockedRun, mergedRun]).map((metric) => metric.value)).toEqual(['2', '1', '1', '2 min']);
    expect(isIssueTrackerProvider(' Jira ')).toBe(true);
    expect(isIssueTrackerProvider('github')).toBe(false);
    expect(isIssueTrackerRun(reviewRun)).toBe(true);
    expect(buildIssueTrackerRunLabel(reviewRun)).toBe('Linear-linked issue');
    expect(buildIssueTrackerRunLabel(createRunFixture({ issue: { ...issue, provider: 'jira' } }))).toBe('Jira-linked issue');
    expect(buildRunTeamKey(blockedRun)).toBe('platform');
    expect(buildTeamInitials('Platform Team')).toBe('PT');
    expect(buildTeamInitials('')).toBe('AI');
    expect(getRunChannelTone(blockedRun)).toBe('blocked');
    expect(getRunChannelTone(mergedRun)).toBe('merged');
    expect(buildReviewEffortLabel(blockedRun)).toContain('1 actionable blocker');
    expect(resolveCurrentPullRequestUrl(reviewRun)).toBe('https://github.com/octo/repo/pull/42');
    expect(resolveCurrentPullRequestUrl(createRunFixture({ pullRequest: undefined }))).toBe('https://github.com/octo/repo/pull/42');
    expect(formatArtifactSize(null)).toBe('Size unavailable');
    expect(formatArtifactSize(512)).toBe('512 B');
    expect(formatArtifactSize(2048)).toBe('2.0 KiB');
    expect(extractCursorAgentIdFromRun(createRunFixture({
      cloudAgent: {
        id: 'fallback-agent',
        status: 'completed',
        target: { url: 'https://cursor.com/agents?id=bc-cloud-agent-1' },
      },
    }))).toBe('bc-cloud-agent-1');

    const groups = buildRunTeamGroups([reviewRun, blockedRun, mergedRun]);
    expect(groups).toHaveLength(2);
    expect(buildTeamHoverLabel(groups[0])).toContain('Platform Team: 2 runs');
  });

  it('covers route, role, lookup, class, and label helpers', () => {
    expect(getNavLinkClassName('/integrations', '/settings')).toBe('nav-link active');
    expect(getNavLinkClassName('/dashboard', '/settings')).toBe('nav-link');
    expect(buildShellPageTitle('/tasks/run-1')).toBe('Run Room');
    expect(buildShellPageTitle('/intake')).toBe('New Work');
    expect(canAccessRole('admin', ['admin'])).toBe(true);
    expect(buildRoleLabel('admin')).toBe('Admin');
    expect(buildRoleCapabilityItems()).toHaveLength(3);
    expect(findIssueById([issue], 'issue-1')).toBe(issue);
    expect(findIssueById([issue], 'missing')).toBeNull();
    expect(findIntegrationStatus([integrationStatus], 'github')).toBe(integrationStatus);
    expect(findIntegrationStatus([integrationStatus], 'missing')).toBeNull();
    expect(getConnectionValue(integrationStatus, 'owner')).toBe('octo-org');
    expect(getConnectionValue(null, 'owner')).toBe('');
    expect(buildUserHeadline(currentUser)).toBe('Maya Chen');
    expect(buildUserHeadline(null)).toBe('Loading user');
    expect(buildUserSubtitle(currentUser)).toContain('maya@example.com');
    expect(buildUserSubtitle(null)).toBe('No identity payload available.');
    expect(formatEventTime('not-a-date')).toBe('not-a-date');
    expect(buildTimelineEntryClassName('active')).toBe('timeline-entry timeline-entry-active');
    expect(buildTimelineEntryClassName('pending')).toBe('timeline-entry timeline-entry-pending');
    expect(buildTimelineEntryClassName('complete')).toBe('timeline-entry timeline-entry-complete');
    expect(buildLogEntryClassName('success')).toBe('log-entry log-entry-success');
    expect(buildLogEntryClassName('warning')).toBe('log-entry log-entry-warning');
    expect(buildLogEntryClassName('error')).toBe('log-entry log-entry-error');
    expect(buildLogEntryClassName('info')).toBe('log-entry log-entry-info');
    expect(buildEvidenceStatusClassName('running')).toBe('evidence-status evidence-status-running');
    expect(buildEvidenceStatusClassName('blocked')).toBe('evidence-status evidence-status-blocked');
    expect(buildEvidenceStatusClassName('captured')).toBe('evidence-status evidence-status-captured');
    expect(buildEvidenceTabLabel('diff')).toBe('Diff');
    expect(buildEvidenceTabLabel('tests')).toBe('Tests');
    expect(buildEvidenceTabLabel('rationale')).toBe('Rationale');
  });

  it('covers approval, pull request, URL, and task reference helpers', () => {
    const run = createRunFixture();

    expect(buildApprovalDecisionLabel('approve')).toBe('Reviewer approved');
    expect(buildApprovalDecisionLabel('retry')).toBe('Reviewer requested retry');
    expect(buildApprovalDecisionLabel('re-scope')).toBe('Reviewer re-scoped');
    expect(buildApprovalDecisionLabel('escalate')).toBe('Reviewer escalated');
    expect(buildApprovalDecisionLabel('pr_review_approved')).toBe('PR review approved on GitHub');
    expect(buildApprovalDecisionLabel('pr_merged')).toBe('Pull request merged');
    expect(buildApprovalDecisionLabel('custom')).toBe('custom');
    expect(buildApprovalSourceLabel('github')).toBe('GitHub');
    expect(buildApprovalSourceLabel(undefined)).toBe('Reviewer');
    expect(buildPullRequestStateLabel(run)).toBe('Open - awaiting review');
    expect(buildPullRequestStateLabel(createRunFixture({ pullRequest: undefined }))).toBe('Not linked');
    expect(buildPullRequestStateLabel(createRunFixture({ pullRequest: { ...run.pullRequest!, state: 'approved' } }))).toBe('Approved, awaiting merge');
    expect(extractUrlsFromText('See https://a.example/test, then https://a.example/test and https://b.example/path.')).toEqual([
      'https://a.example/test',
      'https://b.example/path',
    ]);

    const links = collectTaskDetailReferenceLinks(run);
    expect(links.issueLinks).toEqual(['https://linear.example.com/issue/ACP-1']);
    expect(links.interfaceLinks).toContain('https://github.com/octo/repo/pull/42');
    expect(links.ciLinks).toEqual(['https://ci.example.com/build/1']);
    expect(links.artifactLinks).toContain('https://preview.example.com');
  });
});

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
  });

  it('renders Cursor artifact result contents', () => {
    const run = createRunFixture();
    mockedUseApiQuery().mockReturnValue({
      data: {
        agentId: 'agent-1',
        items: [{
          path: 'artifacts/result.txt',
          sizeBytes: 12,
          updatedAt: '2026-04-28T10:08:00.000Z',
          downloadUrl: 'https://cursor-artifacts.example.com/result.txt',
          expiresAt: '2026-04-28T10:23:00.000Z',
          contentType: 'text/plain',
          encoding: 'utf-8',
          content: 'artifact body',
        }],
      },
      error: null,
      isLoading: false,
    });

    render(<ArtifactResultsPanelBody run={run} />);

    expect(screen.getByText('artifacts/result.txt')).toBeInTheDocument();
    expect(screen.getByText('artifact body')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open temporary download' })).toHaveAttribute('href', 'https://cursor-artifacts.example.com/result.txt');
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
    vi.mocked(api.fetchDashboardSuggestedActions).mockResolvedValue({ suggestedActions: ['Review blocked runs'], model: 'test-model', runCount: 1 });
    mockedUseApiQuery().mockReturnValue({ data: null, error: null, isLoading: true });
  });

  it('renders App signed-out flow and SignInPage submit behavior', async () => {
    renderWithRouter(<App />, '/');

    await waitFor(() => {
      expect(screen.getByText('Sign in to enter mission control.')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Enter mission control' }));

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
    expect(api.beginGoogleSignIn).toHaveBeenCalled();
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
      blockedReasons: [],
      suggestedActions: [],
      integrationStatuses: [integrationStatus],
      currentUser,
    };
    mockedUseApiQuery().mockReturnValue({ data: dashboard, error: null, isLoading: false });

    renderWithRouter(<DashboardPage />, '/dashboard');

    expect(screen.getByText('Pick a team server, scan run channels, then open the run room for evidence and review.')).toBeInTheDocument();
    await waitFor(() => {
      expect(api.fetchDashboardSuggestedActions).toHaveBeenCalledWith({ runIds: ['run-1'] });
    });
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
