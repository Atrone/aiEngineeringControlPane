import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMissionControlDashboard } from './useMissionControlDashboard';
import * as api from '../lib/api';
import { createRunFixture, currentUser, integrationStatus } from '../test/fixtures';

vi.mock('../lib/api', () => ({
  fetchDashboard: vi.fn(),
  fetchDashboardReviewEfforts: vi.fn(),
  fetchDashboardSuggestedActions: vi.fn(),
}));

vi.mock('./useApiQuery', () => ({
  useApiQuery: vi.fn(),
}));

import { useApiQuery } from './useApiQuery';

describe('useMissionControlDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useMissionControlDashboard loadSuggestions and loadReviewEfforts fetch OpenAI dashboard enrichments', async () => {
    const run = createRunFixture();
    vi.mocked(useApiQuery).mockReturnValue({
      data: {
        metrics: [],
        runs: [run],
        blockedReasons: [],
        suggestedActions: [],
        integrationStatuses: [integrationStatus],
        currentUser,
      },
      error: null,
      isLoading: false,
    });
    vi.mocked(api.fetchDashboardSuggestedActions).mockResolvedValue({
      suggestedActions: ['Review blocked runs'],
      model: 'test-model',
      runCount: 1,
    });
    vi.mocked(api.fetchDashboardReviewEfforts).mockResolvedValue({
      reviewEfforts: [{ runId: run.id, effortMinutes: 18, label: 'Moderate review', confidence: 0.8, rationale: 'Clear scope.', source: 'openai' }],
      model: 'test-model',
      runCount: 1,
    });

    const { result } = renderHook(() => useMissionControlDashboard());

    await waitFor(() => {
      expect(result.current.suggestedActions).toEqual(['Review blocked runs']);
    });
    expect(result.current.reviewEffortsByRunId[run.id]?.effortMinutes).toBe(18);
    expect(api.fetchDashboardSuggestedActions).toHaveBeenCalledWith({ runIds: [run.id] });
    expect(api.fetchDashboardReviewEfforts).toHaveBeenCalledWith({ runIds: [run.id] });
  });

  it('useMissionControlDashboard clears enrichments when no runs are visible', async () => {
    vi.mocked(useApiQuery).mockReturnValue({
      data: {
        metrics: [],
        runs: [],
        blockedReasons: [],
        suggestedActions: [],
        integrationStatuses: [integrationStatus],
        currentUser,
      },
      error: null,
      isLoading: false,
    });

    const { result } = renderHook(() => useMissionControlDashboard());

    await waitFor(() => {
      expect(result.current.suggestedActions).toEqual([]);
    });
    expect(result.current.reviewEffortsByRunId).toEqual({});
    expect(api.fetchDashboardSuggestedActions).not.toHaveBeenCalled();
    expect(api.fetchDashboardReviewEfforts).not.toHaveBeenCalled();
  });
});
