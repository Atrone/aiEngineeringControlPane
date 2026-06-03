import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useIntakeForm } from './useIntakeForm';
import * as api from '../lib/api';
import { currentUser, documentRecord, integrationStatus, issue } from '../test/fixtures';

vi.mock('../lib/api', () => ({
  classifyIntakeIssuesByScope: vi.fn(),
  fetchIntakeOptions: vi.fn(),
}));

vi.mock('./useApiQuery', () => ({
  useApiQuery: vi.fn(),
}));

import { useApiQuery } from './useApiQuery';

describe('useIntakeForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useIntakeForm loadIssueScoping calls classifyIntakeIssuesByScope when issues exist', async () => {
    const intakePayload = {
      repositories: [{ id: 'platform-web', name: 'platform-web', fullName: 'acme/platform-web', defaultBranch: 'main', private: false, provider: 'github', url: '' }],
      issues: [issue],
      documents: [documentRecord],
      currentUser,
      integrationStatuses: [integrationStatus],
    };
    const capturedLoaders: Array<() => Promise<unknown>> = [];

    vi.mocked(useApiQuery).mockImplementation((loader, dependencies) => {
      if (dependencies.length === 0) {
        return { data: intakePayload, error: null, isLoading: false };
      }

      capturedLoaders.push(loader as () => Promise<unknown>);
      return { data: { wellScopedIssueIds: [issue.id], poorlyScopedIssueIds: [] }, error: null, isLoading: false };
    });
    vi.mocked(api.classifyIntakeIssuesByScope).mockResolvedValue({
      wellScopedIssueIds: [issue.id],
      poorlyScopedIssueIds: [],
    });

    renderHook(() => useIntakeForm());

    expect(capturedLoaders.length).toBeGreaterThan(0);
    await expect(capturedLoaders[capturedLoaders.length - 1]()).resolves.toEqual({
      wellScopedIssueIds: [issue.id],
      poorlyScopedIssueIds: [],
    });
    expect(api.classifyIntakeIssuesByScope).toHaveBeenCalledWith({ issueIds: [issue.id] });
  });

  it('useIntakeForm loadIssueScoping skips the API when no issues are available', async () => {
    const capturedLoaders: Array<() => Promise<unknown>> = [];

    vi.mocked(useApiQuery).mockImplementation((loader, dependencies) => {
      if (dependencies.length === 0) {
        return {
          data: {
            repositories: [],
            issues: [],
            documents: [],
            currentUser,
            integrationStatuses: [],
          },
          error: null,
          isLoading: false,
        };
      }

      capturedLoaders.push(loader as () => Promise<unknown>);
      return { data: null, error: null, isLoading: false };
    });

    renderHook(() => useIntakeForm());

    await expect(capturedLoaders[capturedLoaders.length - 1]()).resolves.toBeNull();
    expect(api.classifyIntakeIssuesByScope).not.toHaveBeenCalled();
  });
});
