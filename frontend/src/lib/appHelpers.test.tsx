import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
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
  buildRunTraceabilityGraph,
  buildRunTeamGroups,
  buildRunTeamKey,
  buildShellPageTitle,
  buildTeamHoverLabel,
  buildTeamInitials,
  buildTimelineEntryClassName,
  buildTraceabilityNodeClassName,
  buildTraceabilityStatusLabel,
  buildUploadedDocumentRecord,
  buildUserHeadline,
  buildUserSubtitle,
  canAccessRole,
  collectBlockerReasons,
  collectTaskDetailReferenceLinks,
  deriveDashboardMetrics,
  exchangeGoogleAuthCodeOnce,
  extractUrlsFromText,
  findIntegrationStatus,
  findIssueById,
  formatEventTime,
  formatExecutionModeLabel,
  formatReviewEffortValue,
  getConnectionValue,
  getDocumentsForRepository,
  getNavLinkClassName,
  getRunChannelTone,
  isActionableBlocker,
  isIssueTrackerProvider,
  isIssueTrackerRun,
  parseRuntimeSeconds,
  resolveCurrentPullRequestUrl,
  resolvePullRequestArtifactUrl,
  resolveRunBranchUrl,
  resolveRunRepositoryUrl,
  resolveRunValidationUrl,
  shouldShowRunLobbyPullRequest,
} from './appHelpers';
import * as api from './api';
import { createRunFixture, currentUser, documentRecord, integrationStatus, issue } from '../test/fixtures';
import type { UploadedDocumentRecord } from '../types/controlPane';

vi.mock('./api', () => ({
  exchangeGoogleAuthCode: vi.fn(),
}));
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
    const mergedRun = createRunFixture({
      id: 'run-3',
      status: 'Merged',
      blockers: [],
      runtime: '01:00',
      requestedBy: { ...currentUser, teamId: 'ops' },
    });

    expect(buildEnrichmentSourceLabel([])).toBe('repo docs');
    expect(buildEnrichmentSourceLabel([{} as UploadedDocumentRecord])).toBe('uploaded docs');
    expect(
      getDocumentsForRepository(
        [
          { ...documentRecord, id: 'doc-platform', repoName: 'platform-web' },
          { ...documentRecord, id: 'doc-shared', repoName: undefined },
          { ...documentRecord, id: 'doc-readme', path: 'README.md', repoName: undefined },
          { ...documentRecord, id: 'doc-api', repoName: 'api-service' },
        ],
        'Platform Web',
      ).map((document) => document.id),
    ).toEqual(['doc-platform', 'doc-shared']);
    expect(getDocumentsForRepository(
      [{ ...documentRecord, id: 'shared-top-level', path: 'docs/overview.md', repoName: undefined }],
      'platform-web',
    ).map((document) => document.id)).toEqual(['shared-top-level']);
    expect(isActionableBlocker('No active blockers')).toBe(false);
    expect(isActionableBlocker('Missing API key')).toBe(true);
    expect(parseRuntimeSeconds('02:30')).toBe(150);
    expect(parseRuntimeSeconds('bad')).toBe(0);
    expect(collectBlockerReasons([blockedRun, reviewRun])).toEqual(new Set(['Missing API key']));
    expect(formatReviewEffortValue(0, 0)).toBe('0 min');
    expect(formatReviewEffortValue(2, 24)).toBe('24 min');
    expect(deriveDashboardMetrics([reviewRun, blockedRun, mergedRun]).map((metric) => metric.value)).toEqual(['2', '1', '1', '0 min']);
    expect(deriveDashboardMetrics([reviewRun, blockedRun], {
      'run-1': { runId: 'run-1', effortMinutes: 18, label: 'Moderate review', confidence: 0.8, rationale: 'Clear scope.', source: 'openai' },
      'run-2': { runId: 'run-2', effortMinutes: 30, label: 'Moderate review', confidence: 0.6, rationale: 'Needs care.', source: 'openai' },
    }).find((metric) => metric.label === 'Review effort')?.value).toBe('48 min');
    expect(isIssueTrackerProvider(' Jira ')).toBe(true);
    expect(isIssueTrackerProvider('github')).toBe(false);
    expect(isIssueTrackerRun(reviewRun)).toBe(true);
    expect(buildIssueTrackerRunLabel(reviewRun)).toBe('Linear-linked issue');
    expect(buildIssueTrackerRunLabel(createRunFixture({ issue: { ...issue, provider: 'jira' } }))).toBe('Jira-linked issue');
    expect(buildIssueTrackerRunLabel(createRunFixture({ issue: { ...issue, provider: 'fallback' } }))).toBe('Delegated task context');
    expect(buildRunTeamKey(blockedRun)).toBe('platform');
    expect(buildTeamInitials('Platform Team')).toBe('PT');
    expect(buildTeamInitials('')).toBe('AI');
    expect(getRunChannelTone(blockedRun)).toBe('blocked');
    expect(getRunChannelTone(mergedRun)).toBe('merged');
    expect(buildReviewEffortLabel(blockedRun, { runId: 'run-2', effortMinutes: 30, label: 'Moderate review', confidence: 0.6, rationale: 'Needs care.', source: 'openai' })).toContain('30 min OpenAI guess');
    expect(shouldShowRunLobbyPullRequest(reviewRun)).toBe(true);
    expect(shouldShowRunLobbyPullRequest(blockedRun)).toBe(false);
    expect(resolveCurrentPullRequestUrl(reviewRun)).toBe('https://github.com/octo/repo/pull/42');
    expect(resolveCurrentPullRequestUrl(createRunFixture({ pullRequest: undefined }))).toBe('https://github.com/octo/repo/pull/42');

    const groups = buildRunTeamGroups([reviewRun, blockedRun, mergedRun]);
    expect(groups).toHaveLength(2);
    expect(buildTeamHoverLabel(groups[0])).toContain('platform: 2 runs');

    const fallbackRun = createRunFixture({
      id: 'run-fallback',
      issue: { ...issue, provider: 'fallback' },
      requestedBy: { ...currentUser, teamId: 'platform' },
    });

    expect(isIssueTrackerRun(fallbackRun)).toBe(false);
    expect(buildRunTeamGroups([fallbackRun])[0].runs).toEqual([fallbackRun]);
  });

  it('covers route, role, lookup, class, and label helpers', () => {
    expect(getNavLinkClassName('/integrations', '/settings')).toBe('nav-link active');
    expect(getNavLinkClassName('/dashboard', '/settings')).toBe('nav-link');
    expect(buildShellPageTitle('/tasks/run-1')).toBe('Run Room');
    expect(buildShellPageTitle('/intake')).toBe('Delegate to agent');
    expect(buildShellPageTitle('/settings')).toBe('Settings');
    expect(buildShellPageTitle('/integrations')).toBe('Settings');
    expect(buildShellPageTitle('/dashboard')).toBe('Run Channels');
    expect(formatExecutionModeLabel('implement')).toContain('Implement');
    expect(formatExecutionModeLabel('research')).toContain('Research');
    expect(formatExecutionModeLabel('unknown-mode')).toBe('unknown-mode');
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
    expect(buildPullRequestStateLabel(createRunFixture({ pullRequest: { ...run.pullRequest!, approved: false, reviewInProgress: true } }))).toBe('Open - review in progress');
    expect(buildTraceabilityNodeClassName('active')).toBe('traceability-node traceability-node-active');
    expect(buildTraceabilityStatusLabel('complete')).toBe('Captured');
    expect(buildTraceabilityStatusLabel('active')).toBe('Active');
    expect(buildTraceabilityStatusLabel('blocked')).toBe('Blocked');
    expect(buildTraceabilityStatusLabel('pending')).toBe('Pending');
    const traceabilityGraph = buildRunTraceabilityGraph(run);

    expect(traceabilityGraph.map((node) => node.id)).toEqual([
      'issue',
      'repo',
      'branch',
      'agent',
      'commits',
      'tests',
      'pull-request',
      'review',
      'merge-deploy',
    ]);
    expect(traceabilityGraph.map((node) => [node.id, node.href])).toEqual([
      ['issue', 'https://linear.example.com/issue/ACP-1'],
      ['repo', 'https://github.com/octo/repo'],
      ['branch', 'https://github.com/octo/repo/tree/feature%2Fdashboard'],
      ['agent', 'https://cursor.example.com/agents/1'],
      ['commits', 'https://github.com/octo/repo/pull/42/commits'],
      ['tests', 'https://ci.example.com/build/1'],
      ['pull-request', 'https://github.com/octo/repo/pull/42'],
      ['review', 'https://github.com/octo/repo/pull/42'],
      ['merge-deploy', 'https://github.com/octo/repo/pull/42'],
    ]);

    const commentedRun = createRunFixture({
      approvalHistory: [],
      pullRequest: {
        ...run.pullRequest!,
        approved: false,
        approvedAt: null,
        approvedBy: null,
        reviewInProgress: true,
        reviewActivityAt: '2026-04-28T10:08:00.000Z',
        reviewActivityBy: 'octo-reviewer',
      },
    });
    const reviewNode = buildRunTraceabilityGraph(commentedRun).find((node) => node.id === 'review');
    expect(reviewNode?.title).toBe('Review in progress');
    expect(reviewNode?.detail).toContain('octo-reviewer');
    expect(extractUrlsFromText('See https://a.example/test, then https://a.example/test and https://b.example/path.')).toEqual([
      'https://a.example/test',
      'https://b.example/path',
    ]);

    const links = collectTaskDetailReferenceLinks(run);
    expect(links.issueLinks).toEqual(['https://linear.example.com/issue/ACP-1']);
    expect(links.interfaceLinks).toContain('https://github.com/octo/repo/pull/42');
    expect(links.ciLinks).toEqual(['https://ci.example.com/build/1']);
    expect(links.evidenceLinks).toContain('https://preview.example.com');
  });

  it('resolveRunRepositoryUrl resolveRunBranchUrl resolvePullRequestArtifactUrl and resolveRunValidationUrl build artifact links', () => {
    const run = createRunFixture();

    expect(resolveRunRepositoryUrl(run)).toBe('https://github.com/octo/repo');
    expect(resolveRunBranchUrl(run)).toBe('https://github.com/octo/repo/tree/feature%2Fdashboard');
    expect(resolvePullRequestArtifactUrl(run, 'commits')).toBe('https://github.com/octo/repo/pull/42/commits');
    expect(resolveRunValidationUrl(run)).toBe('https://ci.example.com/build/1');
  });

  it('normalizeRepoDocKey and isSharedTopLevelDocsDocument keep shared docs visible for selected repos', () => {
    expect(getDocumentsForRepository(
      [{ ...documentRecord, id: 'shared-top-level', path: 'docs/overview.md', repoName: undefined }],
      'platform-web',
    ).map((document) => document.id)).toEqual(['shared-top-level']);
  });

  it('buildReviewNoteTraceSummary and collectTaskDetailReferenceLinks dedupe duplicate URLs', () => {
    const run = createRunFixture({
      ci: { workflow: 'CI', status: 'passed', summary: 'See https://ci.example.com/build/1 and https://ci.example.com/build/1 again.' },
    });

    expect(collectTaskDetailReferenceLinks(run).ciLinks).toEqual(['https://ci.example.com/build/1']);
    expect(buildRunTraceabilityGraph(run).find((node) => node.id === 'review')?.title).toBeTruthy();
  });
});