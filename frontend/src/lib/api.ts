import type {
  ApprovalDecisionRequest,
  ApprovalPayload,
  CurrentUser,
  DashboardPayload,
  IntegrationsPayload,
  IntakePayload,
  PolicyPayload,
  RunCreateRequest,
  RunSummary,
  TaskCreateRequest,
} from '../types/controlPane';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '');

/**
 * Fetches and parses a JSON response from the backend API.
 */
async function getJson<T>(path: string): Promise<T> {
  // Build the full request URL from the configured API base.
  const response = await fetch(`${apiBaseUrl}${path}`);

  if (!response.ok) {
    // Throw a readable error so the UI can surface a useful failure state.
    throw new Error(`Request failed for ${path} with status ${response.status}.`);
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
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    // Throw a readable error so route-level UI can surface the failed mutation.
    throw new Error(`Request failed for ${path} with status ${response.status}.`);
  }

  // Return the parsed JSON response body from the mutation request.
  return (await response.json()) as TResponse;
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
