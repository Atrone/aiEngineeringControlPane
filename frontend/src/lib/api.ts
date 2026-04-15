import type {
  ApprovalDecisionRequest,
  ApprovalPayload,
  AuthSession,
  CurrentUser,
  DashboardPayload,
  DocsConnectRequest,
  GitHubConnectRequest,
  IntegrationsPayload,
  IntakePayload,
  LinearConnectRequest,
  PolicyPayload,
  RunCreateRequest,
  RunSummary,
  SignInRequest,
  TaskCreateRequest,
} from '../types/controlPane';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '');
const sessionStorageKey = 'ai-control-pane.session-token';

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
 * Builds the shared request headers for authenticated API calls.
 */
function buildRequestHeaders(additionalHeaders?: HeadersInit): HeadersInit {
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
async function buildErrorMessage(path: string, response: Response): Promise<string> {
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
async function getJson<T>(path: string): Promise<T> {
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
async function sendJson<TResponse, TRequest>(path: string, method: 'POST', payload: TRequest): Promise<TResponse> {
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
 * Fetches the active policy payload.
 */
export async function fetchPolicies(): Promise<PolicyPayload> {
  // Load the currently active mock policy pack for the UI.
  return getJson<PolicyPayload>('/api/policies/web-app');
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
 * Fetches the integration status overview payload.
 */
export async function fetchIntegrations(): Promise<IntegrationsPayload> {
  // Load the provider status summary for the integrations view.
  return getJson<IntegrationsPayload>('/api/integrations');
}

/**
 * Creates a new integrated AI work item.
 */
export async function createTask(payload: TaskCreateRequest): Promise<RunSummary> {
  // Submit the intake form payload to create a new task and initial run.
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
 * Stores the docs setup chosen in the guided integrations flow.
 */
export async function connectDocs(payload: DocsConnectRequest): Promise<IntegrationsPayload> {
  // Save the docs connection and fetch the refreshed integrations payload.
  return sendJson<IntegrationsPayload, DocsConnectRequest>('/api/integrations/docs/connect', 'POST', payload);
}
