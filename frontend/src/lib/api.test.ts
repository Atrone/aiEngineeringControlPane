import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  beginGoogleSignIn,
  buildErrorMessage,
  buildRequestHeaders,
  classifyIntakeIssuesByScope,
  clearSessionToken,
  connectCursor,
  connectGitHub,
  connectJira,
  connectLinear,
  createApprovalDecision,
  createRun,
  createTask,
  enrichIntakeField,
  exchangeGoogleAuthCode,
  fetchApprovals,
  fetchAuthConfig,
  fetchCurrentUser,
  fetchDashboard,
  fetchDashboardSuggestedActions,
  fetchCursorAgentArtifactResults,
  fetchIntakeOptions,
  fetchIntegrations,
  fetchRunDetail,
  getJson,
  getSessionToken,
  hasSessionToken,
  identifyRepositoryForIssue,
  sendJson,
  setSessionToken,
  signIn,
  signOut,
} from './api';
import type {
  ApprovalDecisionRequest,
  CursorConnectRequest,
  DashboardSuggestedActionsRequest,
  GitHubConnectRequest,
  IntakeEnrichRequest,
  IntakeIdentifyRepositoryRequest,
  IntakeIssueScopingRequest,
  JiraConnectRequest,
  LinearConnectRequest,
  RunCreateRequest,
  SignInRequest,
  TaskCreateRequest,
} from '../types/controlPane';

type FetchCall = {
  url: string;
  init: RequestInit | undefined;
};

const sessionStorageKey = 'ai-control-pane.session-token';

/**
 * Creates a fetch-compatible JSON response for API helper tests.
 */
function createJsonResponse(payload: unknown, ok = true, status = ok ? 200 : 500): Response {
  // Return a browser Response so the production helpers parse the same interface.
  return new Response(JSON.stringify(payload), { status });
}

/**
 * Reads the latest mocked fetch call as a typed URL/init pair.
 */
function getLatestFetchCall(fetchMock: ReturnType<typeof vi.fn>): FetchCall {
  // Pull the most recent call so each assertion stays tied to the helper under test.
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined];

  // Normalize the call tuple into a descriptive object for assertions.
  return { url, init };
}

describe('session token helpers', () => {
  beforeEach(() => {
    // Start each token test from a signed-out browser state.
    window.localStorage.clear();
  });

  it('gets, sets, clears, and detects the session token', () => {
    expect(getSessionToken()).toBe('');
    expect(hasSessionToken()).toBe(false);

    setSessionToken('session-123');

    expect(window.localStorage.getItem(sessionStorageKey)).toBe('session-123');
    expect(getSessionToken()).toBe('session-123');
    expect(hasSessionToken()).toBe(true);

    clearSessionToken();

    expect(getSessionToken()).toBe('');
    expect(hasSessionToken()).toBe(false);
  });
});

describe('request primitives', () => {
  beforeEach(() => {
    // Reset browser state and fetch stubs between request helper cases.
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('builds headers with additional values and an auth token', () => {
    setSessionToken('token-abc');

    const headers = buildRequestHeaders({ 'Content-Type': 'application/json' }) as Headers;

    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('Authorization')).toBe('Bearer token-abc');
  });

  it('builds a detailed error message when the response includes detail', async () => {
    const message = await buildErrorMessage('/api/example', createJsonResponse({ detail: 'Nope' }, false, 400));

    expect(message).toBe('Nope');
  });

  it('builds a fallback error message when the response body is not readable JSON', async () => {
    const response = new Response('not-json', { status: 503 });

    const message = await buildErrorMessage('/api/example', response);

    expect(message).toBe('Request failed for /api/example with status 503.');
  });

  it('fetches JSON with the current auth headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    setSessionToken('token-abc');

    await expect(getJson<{ ok: boolean }>('/api/example')).resolves.toEqual({ ok: true });

    const call = getLatestFetchCall(fetchMock);
    expect(call.url).toContain('/api/example');
    expect((call.init?.headers as Headers).get('Authorization')).toBe('Bearer token-abc');
  });

  it('throws readable GET errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ detail: 'Broken' }, false, 422));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getJson('/api/example')).rejects.toThrow('Broken');
  });

  it('sends JSON with POST, content type, and body payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ id: 'result' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(sendJson<{ id: string }, { name: string }>('/api/example', 'POST', { name: 'Maya' })).resolves.toEqual({
      id: 'result',
    });

    const call = getLatestFetchCall(fetchMock);
    expect(call.url).toContain('/api/example');
    expect(call.init?.method).toBe('POST');
    expect((call.init?.headers as Headers).get('Content-Type')).toBe('application/json');
    expect(call.init?.body).toBe(JSON.stringify({ name: 'Maya' }));
  });

  it('throws readable POST errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ detail: 'Rejected' }, false, 409));
    vi.stubGlobal('fetch', fetchMock);

    await expect(sendJson('/api/example', 'POST', {})).rejects.toThrow('Rejected');
  });
});

describe('auth API functions', () => {
  beforeEach(() => {
    // Clear persisted auth and restore global browser mocks before each auth case.
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it('loads auth config from the config endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ googleSsoEnabled: true, guidedSignInEnabled: true }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchAuthConfig()).resolves.toEqual({ googleSsoEnabled: true, guidedSignInEnabled: true });

    expect(getLatestFetchCall(fetchMock).url).toContain('/api/auth/config');
  });

  it('signs in and persists the returned session token', async () => {
    const payload: SignInRequest = { name: 'Maya Chen', email: 'maya@example.com', role: 'admin', teamId: 'platform-team' };
    const session = {
      sessionToken: 'signed-in',
      currentUser: { name: 'Maya Chen', email: 'maya@example.com', role: 'admin', teamId: 'platform-team', provider: 'guided' },
    };
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse(session));
    vi.stubGlobal('fetch', fetchMock);

    await expect(signIn(payload)).resolves.toEqual(session);

    expect(getLatestFetchCall(fetchMock).url).toContain('/api/auth/sign-in');
    expect(getSessionToken()).toBe('signed-in');
  });

  it('starts Google sign-in by assigning the backend redirect URL', () => {
    const originalLocation = window.location;
    const assignMock = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignMock },
    });

    beginGoogleSignIn('platform-team');

    expect(assignMock).toHaveBeenCalledWith(expect.stringContaining('/api/auth/google/start'));
    expect(window.sessionStorage.getItem('ai-control-pane.google-team-id')).toBe('platform-team');
    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
  });

  it('exchanges Google auth code and persists the session token', async () => {
    const session = { sessionToken: 'google-token', currentUser: { name: 'Maya Chen', email: 'maya@example.com', role: 'admin', teamId: 'platform-team', provider: 'google' } };
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse(session));
    vi.stubGlobal('fetch', fetchMock);
    window.sessionStorage.setItem('ai-control-pane.google-team-id', 'platform-team');

    await expect(exchangeGoogleAuthCode('oauth-code')).resolves.toEqual(session);

    const call = getLatestFetchCall(fetchMock);
    expect(call.url).toContain('/api/auth/google/exchange');
    expect(call.init?.body).toBe(JSON.stringify({ code: 'oauth-code', teamId: 'platform-team' }));
    expect(getSessionToken()).toBe('google-token');
  });

  it('clears the session token after sign out succeeds', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);
    setSessionToken('token-to-clear');

    await signOut();

    expect(getLatestFetchCall(fetchMock).url).toContain('/api/auth/sign-out');
    expect(getSessionToken()).toBe('');
  });

  it('clears the session token even when sign out fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ detail: 'Already gone' }, false, 500));
    vi.stubGlobal('fetch', fetchMock);
    setSessionToken('token-to-clear');

    await expect(signOut()).rejects.toThrow('Already gone');

    expect(getSessionToken()).toBe('');
  });
});

describe('resource API functions', () => {
  beforeEach(() => {
    // Replace fetch with a default success response for endpoint mapping tests.
    vi.unstubAllGlobals();
  });

  it.each([
    ['fetchDashboard', () => fetchDashboard(), '/api/dashboard'],
    ['fetchRunDetail', () => fetchRunDetail('run-1'), '/api/runs/run-1'],
    ['fetchCursorAgentArtifactResults', () => fetchCursorAgentArtifactResults('agent 1/slash'), '/api/cursor/agents/agent%201%2Fslash/artifacts'],
    ['fetchApprovals', () => fetchApprovals(), '/api/approvals'],
    ['fetchCurrentUser', () => fetchCurrentUser(), '/api/me'],
    ['fetchIntakeOptions', () => fetchIntakeOptions(), '/api/intake'],
    ['fetchIntegrations', () => fetchIntegrations(), '/api/integrations'],
  ])('%s performs the expected GET request', async (_name, request, endpoint) => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await request();

    expect(getLatestFetchCall(fetchMock).url).toContain(endpoint);
    expect(getLatestFetchCall(fetchMock).init?.method).toBeUndefined();
  });

  it.each([
    ['fetchDashboardSuggestedActions', () => fetchDashboardSuggestedActions({ runIds: ['run-1'] } satisfies DashboardSuggestedActionsRequest), '/api/dashboard/suggested-actions'],
    ['enrichIntakeField', () => enrichIntakeField({
      field: 'title',
      value: 'Title',
      title: 'Title',
      prompt: 'Prompt',
      acceptanceCriteria: 'Done',
      repoName: 'repo',
      executionMode: 'cloud',
      uploadedDocuments: [],
    } satisfies IntakeEnrichRequest), '/api/intake/enrich'],
    ['identifyRepositoryForIssue', () => identifyRepositoryForIssue({ issueId: 'issue-1' } satisfies IntakeIdentifyRepositoryRequest), '/api/intake/identify-repository'],
    ['classifyIntakeIssuesByScope', () => classifyIntakeIssuesByScope({ issueIds: ['issue-1'] } satisfies IntakeIssueScopingRequest), '/api/intake/issue-scoping'],
    ['createTask', () => createTask({
      repoName: 'repo',
      title: 'Task',
      prompt: 'Prompt',
      acceptanceCriteria: 'Done',
      documentIds: [],
      uploadedDocuments: [],
      executionMode: 'cloud',
    } satisfies TaskCreateRequest), '/api/tasks'],
    ['createRun', () => createRun({ taskId: 'task-1', agentName: 'Cursor', executionMode: 'cloud' } satisfies RunCreateRequest), '/api/runs'],
    ['createApprovalDecision', () => createApprovalDecision({ runId: 'run-1', decision: 'approved', notes: 'Ship it' } satisfies ApprovalDecisionRequest), '/api/approvals'],
    ['connectGitHub', () => connectGitHub({ owner: 'owner', repositories: 'repo', token: 'token' } satisfies GitHubConnectRequest), '/api/integrations/github/connect'],
    ['connectLinear', () => connectLinear({ apiKey: 'key', teamId: 'team' } satisfies LinearConnectRequest), '/api/integrations/linear/connect'],
    ['connectJira', () => connectJira({ siteUrl: 'https://jira.example.com', email: 'maya@example.com', apiToken: 'token', projectKey: 'ACP' } satisfies JiraConnectRequest), '/api/integrations/jira/connect'],
    ['connectCursor', () => connectCursor({ apiKey: 'key', model: 'gpt' } satisfies CursorConnectRequest), '/api/integrations/cursor/connect'],
  ])('%s performs the expected POST request', async (_name, request, endpoint) => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await request();

    const call = getLatestFetchCall(fetchMock);
    expect(call.url).toContain(endpoint);
    expect(call.init?.method).toBe('POST');
    expect((call.init?.headers as Headers).get('Content-Type')).toBe('application/json');
  });
});
