import { describe, expect, it } from 'vitest';
import { buildRunTeamGroups, deriveDashboardMetrics } from './dashboardHelpers';
import { getDocumentsForRepository } from './intakeHelpers';
import { buildRunTraceabilityGraph, collectTaskDetailReferenceLinks } from './runHelpers';
import { createRunFixture, documentRecord } from '../test/fixtures';

describe('domain helper modules', () => {
  it('keeps dashboard helpers focused on run grouping and metrics', () => {
    const reviewRun = createRunFixture();
    const blockedRun = createRunFixture({ id: 'run-2', status: 'Blocked', blockers: ['Missing token'] });

    expect(buildRunTeamGroups([reviewRun, blockedRun])[0].runs).toEqual([reviewRun, blockedRun]);
    expect(deriveDashboardMetrics([reviewRun, blockedRun]).map((metric) => metric.value)).toEqual(['2', '1', '0', '0 min']);
  });

  it('keeps intake document matching independent from the page component', () => {
    const documents = [
      { ...documentRecord, id: 'repo-doc', repoName: 'platform-web' },
      { ...documentRecord, id: 'shared-doc', path: 'docs/overview.md', repoName: undefined },
      { ...documentRecord, id: 'other-doc', repoName: 'api-service' },
    ];

    expect(getDocumentsForRepository(documents, 'Platform Web').map((document) => document.id)).toEqual(['repo-doc', 'shared-doc']);
  });

  it('keeps run traceability helpers reusable outside App routing', () => {
    const run = createRunFixture();

    expect(buildRunTraceabilityGraph(run).map((node) => node.id)).toContain('pull-request');
    expect(collectTaskDetailReferenceLinks(run).interfaceLinks).toContain('https://github.com/octo/repo/pull/42');
  });
});
