import { describe, expect, it } from 'vitest';
import type { RunSummary } from '../types/controlPane';
import {
  buildMissionControlOwnerOptions,
  buildMissionControlRepoOptions,
  filterMissionControlRuns,
} from './dashboardMissionControlFilters';

/**
 * Builds a minimal run row for focused mission control filter unit tests.
 */
function buildRun(overrides: Partial<RunSummary> = {}): RunSummary {
  // Return a small RunSummary slice so filter predicates can run without full task payloads.
  return {
    id: 'run-test',
    ticket: 'SIG-1',
    title: 'Example task',
    repo: 'web-app',
    branch: 'main',
    owner: 'Maya',
    agent: 'cursor-agent',
    runtime: '01:00',
    cost: '$0',
    status: 'Review',
    risk: 'Low',
    currentStep: 'Waiting',
    summary: 'Summary',
    evidence: { diff: [], tests: [], commands: [], rationale: [] },
    blockers: [],
    ...overrides,
  };
}

describe('dashboardMissionControlFilters', () => {
  it('normalizeMissionControlSearchText and runMatchesMissionControlSearch match search tokens across run fields', () => {
    const runs = [
      buildRun({ id: 'a', ticket: 'ACP-1', title: 'Dashboard', repo: 'frontend' }),
      buildRun({ id: 'b', ticket: 'ACP-2', title: 'API work', repo: 'api-service', owner: 'Jordan' }),
    ];
    const criteria = { searchText: 'acp-2 jordan', status: '' as const, repo: '', ownerToken: '', risk: '' as const };

    // Require every whitespace token to match somewhere in the combined searchable text.
    expect(filterMissionControlRuns(runs, criteria).map((run) => run.id)).toEqual(['b']);
  });

  it('runMatchesMissionControlStatus runMatchesMissionControlRepo runMatchesMissionControlOwner and runMatchesMissionControlRisk apply together', () => {
    const runs = [
      buildRun({ id: 'keep', status: 'Blocked', repo: 'web-app', owner: 'Sam', risk: 'High' }),
      buildRun({ id: 'drop', status: 'Review', repo: 'web-app', owner: 'Sam', risk: 'High' }),
    ];
    const criteria = {
      searchText: '',
      status: 'Blocked' as const,
      repo: 'web-app',
      ownerToken: 'Sam',
      risk: 'High' as const,
    };

    // Keep only the row that satisfies every filter dimension at once.
    expect(filterMissionControlRuns(runs, criteria).map((run) => run.id)).toEqual(['keep']);
  });

  it('routes the unassigned owner token to runs with blank owners', () => {
    const runs = [
      buildRun({ id: 'assigned', owner: 'Priya' }),
      buildRun({ id: 'blank', owner: '   ' }),
    ];
    const criteria = { searchText: '', status: '' as const, repo: '', ownerToken: '__unassigned__', risk: '' as const };

    // Surface only runs that lack a usable owner label for triage-style filtering.
    expect(filterMissionControlRuns(runs, criteria).map((run) => run.id)).toEqual(['blank']);
  });

  it('sorts repository and owner option helpers for stable dropdown rendering', () => {
    const runs = [
      buildRun({ id: 'r1', repo: 'zebra' }),
      buildRun({ id: 'r2', repo: 'alpha' }),
      buildRun({ id: 'r3', repo: 'shared', owner: 'Charlie' }),
      buildRun({ id: 'r4', repo: 'shared', owner: 'Alex' }),
    ];

    // Repos sort alphabetically so operators can scan predictable option lists.
    expect(buildMissionControlRepoOptions(runs)).toEqual(['alpha', 'shared', 'zebra']);
    // Owners sort alphabetically while preserving the dedicated unassigned row when needed.
    expect(buildMissionControlOwnerOptions([buildRun({ id: 'r0', owner: '' }), runs[2], runs[3]])).toEqual([
      { label: '(Unassigned)', value: '__unassigned__' },
      { label: 'Alex', value: 'Alex' },
      { label: 'Charlie', value: 'Charlie' },
    ]);
  });
});
