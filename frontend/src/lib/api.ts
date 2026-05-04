import type {
  ApprovalDecisionRequest,
  ApprovalPayload,
  AuthConfig,
  AuthSession,
  CurrentUser,
  CursorConnectRequest,
  DashboardPayload,
  DashboardSuggestedActionsRequest,
  DashboardSuggestedActionsResponse,
  GoogleAuthExchangeRequest,
  GitHubConnectRequest,
  IntakeEnrichRequest,
  IntakeEnrichResponse,
  IntakeIdentifyRepositoryRequest,
  IntakeIdentifyRepositoryResponse,
  IntakeIssueScopingRequest,
  IntakeIssueScopingResponse,
  IntegrationsPayload,
  IntakePayload,
  JiraConnectRequest,
  LinearConnectRequest,
  RunCreateRequest,
  RunSummary,
  SignInRequest,
  TaskCreateRequest,
} from '../types/controlPane';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '');
const sessionStorageKey = 'ai-control-pane.session-token';
const googleTeamStorageKey = 'ai-control-pane.google-team-id';

/**
 * Reads the persisted session token from browser storage.
 */
export function getSessionToken(): string {
  // Return the current auth token or an empty string when signed out.
  return window.localStorage.getItem(sessionStorageKey) ?? '';
}

/**
 * Stores the active session token in browser storage.
 */
export function setSessionToken(sessionToken: string): void {
  // Persist the session token so page refreshes keep the user signed in.
  window.localStorage.setItem(sessionStorageKey, sessionToken);
}

/**
 * Clears the persisted session token from browser storage.
 */
export function clearSessionToken(): void {
  // Remove the saved auth token when the user signs out.
  window.localStorage.removeItem(sessionStorageKey);
}

/**
 * Reports whether the browser currently has a saved session token.
 */
export function hasSessionToken(): boolean {
  // Return true only when the saved auth token is non-empty.
  return Boolean(getSessionToken());
}

/**
 * Stores the team selected before the Google redirect leaves the app.
 */
function setPendingGoogleTeamId(teamId: string): void {
  // Keep the selected team in tab-scoped storage until the callback exchange finishes.
  window.sessionStorage.setItem(googleTeamStorageKey, teamId.trim());
}

/**
 * Reads the team selected before the Google redirect flow began.
 */
function getPendingGoogleTeamId(): string {
  // Return the pending team id or an empty string when the callback has no saved choice.
  return window.sessionStorage.getItem(googleTeamStorageKey) ?? '';
}

/**
 * Clears the saved Google team selection after a successful session exchange.
 */
function clearPendingGoogleTeamId(): void {
  // Remove the one-time team selection so a later login starts from the visible form value.
  window.sessionStorage.removeItem(googleTeamStorageKey);
}

/**
 * Builds the shared request headers for authenticated API calls.
 */
export function buildRequestHeaders(additionalHeaders?: HeadersInit): HeadersInit {
  const requestHeaders = new Headers(additionalHeaders);
  const sessionToken = getSessionToken();

  if (sessionToken) {
    // Attach the bearer token so protected backend routes can resolve the session.
    requestHeaders.set('Authorization', `Bearer ${sessionToken}`);
  }

  // Return the shared header bag for the outgoing request.
  return requestHeaders;
}

/**
 * Extracts a readable error message from a failed fetch response.
 */
export async function buildErrorMessage(path: string, response: Response): Promise<string> {
  try {
    // Attempt to read the JSON error payload returned by the backend.
    const errorPayload = (await response.json()) as { detail?: string };

    if (errorPayload.detail) {
      // Prefer the backend detail string when it is available.
      return errorPayload.detail;
    }
  } catch {
    // Ignore JSON parsing errors and fall back to the generic status message.
  }

  // Fall back to a predictable message when the backend detail is unavailable.
  return `Request failed for ${path} with status ${response.status}.`;
}

/**
 * Fetches and parses a JSON response from the backend API.
 */
export async function getJson<T>(path: string): Promise<T> {
  // Build the full request URL from the configured API base.
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: buildRequestHeaders(),
  });

  if (!response.ok) {
    // Throw a readable error so the UI can surface a useful failure state.
    throw new Error(await buildErrorMessage(path, response));
  }

  // Return the parsed JSON body using the requested generic type.
  return (await response.json()) as T;
}

/**
 * Sends a JSON request body to the backend API and parses the response.
 */
export async function sendJson<TResponse, TRequest>(path: string, method: 'POST', payload: TRequest): Promise<TResponse> {
  // Send the JSON request body to the configured backend API.
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    headers: buildRequestHeaders({
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    // Throw a readable error so route-level UI can surface the failed mutation.
    throw new Error(await buildErrorMessage(path, response));
  }

  // Return the parsed JSON response body from the mutation request.
  return (await response.json()) as TResponse;
}

/**
 * Loads the public auth configuration for the sign-in screen.
 */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  // Read the available sign-in methods without requiring an existing session.
  return getJson<AuthConfig>('/api/auth/config');
}

/**
 * Creates a guided sign-in session and persists the returned token.
 */
export async function signIn(payload: SignInRequest): Promise<AuthSession> {
  // Create the signed-in session through the backend auth route.
  const session = await sendJson<AuthSession, SignInRequest>('/api/auth/sign-in', 'POST', payload);

  // Save the new session token so protected routes can authenticate future requests.
  setSessionToken(session.sessionToken);

  // Return the full auth session payload to the caller.
  return session;
}

/**
 * Starts the browser-based Google sign-in redirect flow.
 */
export function beginGoogleSignIn(teamId: string): void {
  // Save the chosen team before navigating away for the OAuth redirect.
  setPendingGoogleTeamId(teamId);

  // Send the browser to the backend route that begins the Google OAuth flow.
  window.location.assign(`${apiBaseUrl}/api/auth/google/start`);
}

/**
 * Exchanges the Google callback code for the standard app session payload.
 */
export async function exchangeGoogleAuthCode(code: string): Promise<AuthSession> {
  const teamId = getPendingGoogleTeamId();

  // Exchange the short-lived callback code for the app's normal signed-in session.
  const session = await sendJson<AuthSession, GoogleAuthExchangeRequest>('/api/auth/google/exchange', 'POST', { code, teamId });

  // Persist the returned session token so refreshes can restore the signed-in user.
  setSessionToken(session.sessionToken);

  // Drop the pending team once the backend has minted a session for it.
  clearPendingGoogleTeamId();

  // Return the standard auth session payload to the caller.
  return session;
}

/**
 * Signs the current user out and clears the persisted session token.
 */
export async function signOut(): Promise<void> {
  try {
    // Ask the backend to delete the in-memory session for the current token.
    await sendJson<{ status: string }, Record<string, never>>('/api/auth/sign-out', 'POST', {});
  } finally {
    // Always clear the local auth token even when the backend request fails.
    clearSessionToken();
  }
}

/**
 * Fetches the dashboard payload for the mission control view.
 */
export async function fetchDashboard(): Promise<DashboardPayload> {
  // Load the top-level mission control data from the backend.
  return getJson<DashboardPayload>('/api/dashboard');
}

/**
 * Requests OpenAI-generated suggested next actions for the visible dashboard runs.
 */
export async function fetchDashboardSuggestedActions(
  payload: DashboardSuggestedActionsRequest,
): Promise<DashboardSuggestedActionsResponse> {
  // Send the visible run IDs so the backend can prompt OpenAI with matching context.
  return sendJson<DashboardSuggestedActionsResponse, DashboardSuggestedActionsRequest>(
    '/api/dashboard/suggested-actions',
    'POST',
    payload,
  );
}

/**
 * Fetches the full detail payload for a specific run.
 */
export async function fetchRunDetail(runId: string): Promise<RunSummary> {
  // Load the selected run by ID so the detail page can render evidence.
  return getJson<RunSummary>(`/api/runs/${runId}`);
}

/**
 * Fetches the approval inbox payload.
 */
export async function fetchApprovals(): Promise<ApprovalPayload> {
  // Load the queue summary and review-ready approval items.
  return getJson<ApprovalPayload>('/api/approvals');
}

/**
 * Fetches the current user identity used for approvals and audit history.
 */
export async function fetchCurrentUser(): Promise<CurrentUser> {
  // Load the resolved current user from the backend identity layer.
  return getJson<CurrentUser>('/api/me');
}

/**
 * Fetches the integrated task intake payload.
 */
export async function fetchIntakeOptions(): Promise<IntakePayload> {
  // Load the repositories, issues, docs, and provider status data for task creation.
  return getJson<IntakePayload>('/api/intake');
}

/**
 * Refines a work intake field using the OpenAI-backed enrichment route.
 */
export async function enrichIntakeField(payload: IntakeEnrichRequest): Promise<IntakeEnrichResponse> {
  // Send the current intake state and target field to the backend enrichment route.
  return sendJson<IntakeEnrichResponse, IntakeEnrichRequest>('/api/intake/enrich', 'POST', payload);
}

/**
 * Asks the backend OpenAI route to pick the repository that best fits a work issue.
 */
export async function identifyRepositoryForIssue(
  payload: IntakeIdentifyRepositoryRequest,
): Promise<IntakeIdentifyRepositoryResponse> {
  // Send the selected issue ID to the backend so OpenAI can pick the best-fit repository.
  return sendJson<IntakeIdentifyRepositoryResponse, IntakeIdentifyRepositoryRequest>(
    '/api/intake/identify-repository',
    'POST',
    payload,
  );
}

/**
 * Asks the backend OpenAI route to separate intake issues by scope quality.
 */
export async function classifyIntakeIssuesByScope(
  payload: IntakeIssueScopingRequest,
): Promise<IntakeIssueScopingResponse> {
  // Send the visible issue IDs so the backend can classify the current intake list.
  return sendJson<IntakeIssueScopingResponse, IntakeIssueScopingRequest>(
    '/api/intake/issue-scoping',
    'POST',
    payload,
  );
}

/**
 * Fetches the integration status overview payload.
 */
export async function fetchIntegrations(): Promise<IntegrationsPayload> {
  // Load the provider status summary for the integrations view.
  return getJson<IntegrationsPayload>('/api/integrations');
}

/**
 * Creates a new integrated AI work item and starts its run.
 */
export async function createTask(payload: TaskCreateRequest): Promise<RunSummary> {
  // Submit the intake form payload to create the task and immediately start its run.
  return sendJson<RunSummary, TaskCreateRequest>('/api/tasks', 'POST', payload);
}

/**
 * Starts or restarts a run for an existing task.
 */
export async function createRun(payload: RunCreateRequest): Promise<RunSummary> {
  // Send the run creation payload to the backend workflow surface.
  return sendJson<RunSummary, RunCreateRequest>('/api/runs', 'POST', payload);
}

/**
 * Records an approval decision against a run.
 */
export async function createApprovalDecision(payload: ApprovalDecisionRequest): Promise<RunSummary> {
  // Send the approval decision to the backend so audit history is updated.
  return sendJson<RunSummary, ApprovalDecisionRequest>('/api/approvals', 'POST', payload);
}

/**
 * Stores the GitHub setup chosen in the guided integrations flow.
 */
export async function connectGitHub(payload: GitHubConnectRequest): Promise<IntegrationsPayload> {
  // Save the GitHub connection and fetch the refreshed integrations payload.
  return sendJson<IntegrationsPayload, GitHubConnectRequest>('/api/integrations/github/connect', 'POST', payload);
}

/**
 * Stores the Linear setup chosen in the guided integrations flow.
 */
export async function connectLinear(payload: LinearConnectRequest): Promise<IntegrationsPayload> {
  // Save the Linear connection and fetch the refreshed integrations payload.
  return sendJson<IntegrationsPayload, LinearConnectRequest>('/api/integrations/linear/connect', 'POST', payload);
}

/**
 * Stores the Jira Cloud setup chosen in the guided integrations flow.
 */
export async function connectJira(payload: JiraConnectRequest): Promise<IntegrationsPayload> {
  // Save the Jira connection and fetch the refreshed integrations payload.
  return sendJson<IntegrationsPayload, JiraConnectRequest>('/api/integrations/jira/connect', 'POST', payload);
}

/**
 * Stores the Cursor Cloud Agents setup chosen in the guided integrations flow.
 */
export async function connectCursor(payload: CursorConnectRequest): Promise<IntegrationsPayload> {
  // Save the Cursor setup and fetch the refreshed integrations payload.
  return sendJson<IntegrationsPayload, CursorConnectRequest>('/api/integrations/cursor/connect', 'POST', payload);
}

