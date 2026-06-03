import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useIntegrationForms } from './useIntegrationForms';
import { integrationStatus } from '../test/fixtures';

vi.mock('../lib/api', () => ({
  fetchIntegrations: vi.fn(),
}));

vi.mock('./useApiQuery', () => ({
  useApiQuery: vi.fn(),
}));

import { useApiQuery } from './useApiQuery';

describe('useIntegrationForms', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useIntegrationForms hydrates setup forms from integration statuses', async () => {
    vi.mocked(useApiQuery).mockReturnValue({
      data: {
        statuses: [integrationStatus],
      },
      error: null,
      isLoading: false,
    });

    const { result } = renderHook(() => useIntegrationForms());

    await waitFor(() => {
      expect(result.current.githubForm.owner).toBe('octo-org');
    });
    expect(result.current.githubForm.repositories).toBe('repo');
  });

  it('useIntegrationForms exposes refresh state for connect handlers', () => {
    vi.mocked(useApiQuery).mockReturnValue({ data: { statuses: [integrationStatus] }, error: null, isLoading: false });

    const { result } = renderHook(() => useIntegrationForms());

    result.current.setRefreshKey(2);
    expect(result.current.setMutationSuccess).toBeTypeOf('function');
  });
});
