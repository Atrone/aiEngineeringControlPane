import type {
  CurrentUser,
  DocumentRecord,
  IntegrationStatus,
  IssueRecord,
  RunLiveView,
  RunSummary,
} from '../types/controlPane';
export const currentUser: CurrentUser = {
  name: 'Maya Chen',
  email: 'maya@example.com',
  role: 'admin',
  teamId: 'platform',
  provider: 'guided',
};

export const issue: IssueRecord = {
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

export const documentRecord: DocumentRecord = {
  id: 'doc-1',
  title: 'Runbook',
  path: 'docs/runbook.md',
  source: 'repo',
  updatedAt: '2026-04-28T10:00:00.000Z',
};

export const integrationStatus: IntegrationStatus = {
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

export const liveView: RunLiveView = {
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
export function createRunFixture(overrides: Partial<RunSummary> = {}): RunSummary {
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
      title: 'Build dashboard PR',
      body: '## Summary\nAdds the dashboard implementation for reviewer handoff.',
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
    acceptanceCriteria: '- [ ] Delivers scoped work with review evidence',
    taskPrompt: 'Implement the linked issue with tests and reviewer-ready notes.',
    executionMode: 'implement',
    repositoryContext: {
      id: 'control-pane',
      name: 'control-pane',
      fullName: 'acme/control-pane',
      defaultBranch: 'main',
      url: 'https://github.com/acme/control-pane',
      provider: 'github',
      private: false,
    },
    ...overrides,
  };
}