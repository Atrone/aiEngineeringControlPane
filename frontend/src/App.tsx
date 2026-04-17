import type { FormEvent, ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useApiQuery } from './hooks/useApiQuery';
import {
  beginGoogleSignIn,
  connectCursor,
  clearSessionToken,
  connectDocs,
  connectGitHub,
  connectLinear,
  createApprovalDecision,
  createRun,
  createTask,
  enrichIntakeField,
  exchangeGoogleAuthCode,
  fetchAuthConfig,
  fetchApprovals,
  fetchCurrentUser,
  fetchDashboard,
  fetchIntegrations,
  fetchIntakeOptions,
  fetchPolicies,
  fetchRunDetail,
  hasSessionToken,
  signIn,
  signOut,
} from './lib/api';
import type {
  ApprovalDecisionRequest,
  ApprovalItem,
  AuthConfig,
  CurrentUser,
  CursorConnectRequest,
  DashboardMetric,
  DocsConnectRequest,
  DocumentRecord,
  GitHubConnectRequest,
  IntakeEnrichField,
  IntakeEnrichRequest,
  IntegrationStatus,
  IssueRecord,
  LinearConnectRequest,
  RunEvidenceEntry,
  RunEvidenceTabs,
  RunLiveView,
  RunLogEntry,
  RiskLevel,
  RunSummary,
  RunStatus,
  RunTimelineEntry,
  SignInRequest,
  TaskCreateRequest,
  UserRole,
} from './types/controlPane';

const reviewerRoles: UserRole[] = ['admin', 'tech_lead'];
type EvidenceTabId = keyof RunEvidenceTabs;
const roleOptions: Array<{ role: UserRole; title: string; description: string }> = [
  {
    role: 'admin',
    title: 'Admin',
    description: 'Manage sign-in, policies, integrations, and reviewer workflows.',
  },
  {
    role: 'tech_lead',
    title: 'Tech Lead',
    description: 'Launch work, review runs, and guide GitHub, Linear, and docs setup.',
  },
  {
    role: 'engineer',
    title: 'Engineer',
    description: 'Launch and inspect work without reviewer or integration-admin access.',
  },
];

/**
 * Renders the top-level routed application.
 */
function App() {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [isRestoringSession, setIsRestoringSession] = useState<boolean>(true);

  useEffect(() => {
    let isActive = true;

    /**
     * Restores a saved session token into a current-user payload.
     */
    async function restoreSession(): Promise<void> {
      if (!hasSessionToken()) {
        // Skip the session restore call when the browser has no saved token.
        setCurrentUser(null);
        setIsRestoringSession(false);
        return;
      }

      try {
        // Fetch the current user so the app can rebuild the signed-in shell.
        const restoredUser = await fetchCurrentUser();

        if (isActive) {
          // Save the restored user once the backend validates the token.
          setCurrentUser(restoredUser);
        }
      } catch {
        if (isActive) {
          // Clear invalid tokens so the app falls back to the sign-in route.
          clearSessionToken();
          setCurrentUser(null);
        }
      } finally {
        if (isActive) {
          // Mark the restore attempt as complete after the request settles.
          setIsRestoringSession(false);
        }
      }
    }

    // Start the session restore flow once on initial page load.
    void restoreSession();

    return () => {
      // Ignore late async work after the top-level app unmounts.
      isActive = false;
    };
  }, []);

  /**
   * Saves the newly signed-in user inside the routed app shell.
   */
  function handleSignedIn(user: CurrentUser): void {
    // Update the top-level auth state once sign-in succeeds.
    setCurrentUser(user);
  }

  /**
   * Signs the current user out and clears the app-shell auth state.
   */
  async function handleSignedOut(): Promise<void> {
    // Delete the current backend session and local token.
    await signOut();

    // Reset the routed shell back to the signed-out state.
    setCurrentUser(null);
  }

  if (isRestoringSession && hasSessionToken()) {
    // Show a full-page loading state while the saved session is being restored.
    return <StandaloneStatePanel eyebrow="Restoring session" title="Checking your sign-in..." body="Loading your role and workspace access." />;
  }

  // Route the user into the auth screen or the signed-in product shell.
  return (
    <Routes>
      <Route
        element={currentUser ? <Navigate replace to="/dashboard" /> : <SignInPage onSignedIn={handleSignedIn} />}
        path="/sign-in"
      />
      <Route
        element={currentUser ? <Navigate replace to="/dashboard" /> : <GoogleAuthCallbackPage onSignedIn={handleSignedIn} />}
        path="/auth/callback"
      />
      <Route
        element={currentUser ? <Navigate replace to="/dashboard" /> : <GoogleOAuthReturnPage />}
        path="/auth/google/callback"
      />
      {currentUser ? (
        <Route element={<RootLayout currentUser={currentUser} onSignedOut={handleSignedOut} />}>
          <Route element={<Navigate replace to="/dashboard" />} index />
          <Route element={<DashboardPage />} path="/dashboard" />
          <Route element={<WorkIntakePage />} path="/intake" />
          <Route element={<TaskDetailPage currentUser={currentUser} />} path="/tasks/:runId" />
          <Route
            element={
              <RoleGate allowedRoles={reviewerRoles} currentUser={currentUser} title="Approval inbox">
                <ApprovalInboxPage />
              </RoleGate>
            }
            path="/approvals"
          />
          <Route
            element={
              <RoleGate allowedRoles={reviewerRoles} currentUser={currentUser} title="Policy center">
                <PoliciesPage />
              </RoleGate>
            }
            path="/policies"
          />
          <Route
            element={
              <RoleGate allowedRoles={reviewerRoles} currentUser={currentUser} title="Integrations">
                <IntegrationsPage currentUser={currentUser} />
              </RoleGate>
            }
            path="/integrations"
          />
          <Route element={<Navigate replace to="/dashboard" />} path="*" />
        </Route>
      ) : (
        <Route element={<Navigate replace to="/sign-in" />} path="*" />
      )}
    </Routes>
  );
}

/**
 * Builds the shared frame around each primary page.
 */
function RootLayout(props: { currentUser: CurrentUser; onSignedOut: () => Promise<void> }) {
  const location = useLocation();
  const [isSigningOut, setIsSigningOut] = useState<boolean>(false);
  const canReview = canAccessRole(props.currentUser.role, reviewerRoles);

  /**
   * Signs the user out from the shell header action.
   */
  async function handleSignOutClick(): Promise<void> {
    setIsSigningOut(true);

    try {
      // Forward the sign-out request to the top-level auth handler.
      await props.onSignedOut();
    } finally {
      // Restore the button state after the sign-out flow completes.
      setIsSigningOut(false);
    }
  }

  // Keep the shell visible so the app feels like a real control center.
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <p className="eyebrow">AI Control Pane</p>
          <h1>Mission Control</h1>
          <p className="muted-copy">
            Coordinate AI coding agents across issue intake, repo context, approval, and delivery workflows.
          </p>
        </div>

        <nav aria-label="Primary" className="nav-list">
          <Link className={getNavLinkClassName(location.pathname, '/dashboard')} to="/dashboard">
            Dashboard
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/intake')} to="/intake">
            Work Intake
          </Link>
          {canReview ? (
            <Link className={getNavLinkClassName(location.pathname, '/approvals')} to="/approvals">
              Approval Inbox
            </Link>
          ) : null}
          {canReview ? (
            <Link className={getNavLinkClassName(location.pathname, '/policies')} to="/policies">
              Policy Center
            </Link>
          ) : null}
          {canReview ? (
            <Link className={getNavLinkClassName(location.pathname, '/integrations')} to="/integrations">
              Integrations
            </Link>
          ) : null}
          {location.pathname.startsWith('/tasks/') ? (
            <Link className="nav-link active" to={location.pathname}>
              Task Detail
            </Link>
          ) : null}
        </nav>

        <div className="sidebar-card">
          <p className="sidebar-label">Current user</p>
          <p className="sidebar-stat">{buildUserHeadline(props.currentUser)}</p>
          <p className="muted-copy">{buildUserSubtitle(props.currentUser)}</p>
        </div>
      </aside>

      <main className="page-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">Product Eng</p>
            <h2>Team operations view</h2>
          </div>
          <div className="topbar-actions">
            <span className="pill">{buildRoleLabel(props.currentUser.role)}</span>
            {canReview ? (
              <Link className="ghost-button link-button" to="/integrations">
                View integrations
              </Link>
            ) : null}
            <Link className="primary-button link-button" to="/intake">
              New task
            </Link>
            <button className="ghost-button" disabled={isSigningOut} onClick={() => { void handleSignOutClick(); }} type="button">
              {isSigningOut ? 'Signing out...' : 'Sign out'}
            </button>
          </div>
        </header>

        <Outlet />
      </main>
    </div>
  );
}

/**
 * Renders the guided sign-in screen before a session exists.
 */
function SignInPage(props: { onSignedIn: (user: CurrentUser) => void }) {
  const navigate = useNavigate();
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [isLoadingAuthConfig, setIsLoadingAuthConfig] = useState<boolean>(true);
  const [authConfigError, setAuthConfigError] = useState<string>('');
  const [name, setName] = useState<string>('Maya Chen');
  const [email, setEmail] = useState<string>('maya.chen@example.com');
  const [role, setRole] = useState<UserRole>('tech_lead');
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const roleCapabilityItems = buildRoleCapabilityItems(role);
  const googleSsoEnabled = authConfig?.googleSsoEnabled ?? false;
  const guidedSignInEnabled = authConfig?.guidedSignInEnabled ?? true;

  useEffect(() => {
    let isActive = true;

    /**
     * Loads the available sign-in methods for the current backend environment.
     */
    async function loadAuthConfig(): Promise<void> {
      try {
        // Read the public auth configuration so the sign-in screen can render the right flow.
        const loadedAuthConfig = await fetchAuthConfig();

        if (isActive) {
          // Save the backend auth configuration once it has been loaded successfully.
          setAuthConfig(loadedAuthConfig);
          setAuthConfigError('');
        }
      } catch (caughtError) {
        if (isActive) {
          // Fall back to guided sign-in when the public auth config cannot be loaded.
          setAuthConfig({
            googleSsoEnabled: false,
            guidedSignInEnabled: true,
          });
          setAuthConfigError(caughtError instanceof Error ? caughtError.message : 'Unable to load the available sign-in methods.');
        }
      } finally {
        if (isActive) {
          // Mark the auth-config lookup as complete after the request settles.
          setIsLoadingAuthConfig(false);
        }
      }
    }

    // Load the available sign-in methods once when the sign-in screen mounts.
    void loadAuthConfig();

    return () => {
      // Ignore late auth-config responses after the sign-in screen unmounts.
      isActive = false;
    };
  }, []);

  /**
   * Creates the guided sign-in session from the submitted identity form.
   */
  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setSubmitError('');
    setIsSubmitting(true);

    const payload: SignInRequest = {
      name,
      email,
      role,
    };

    try {
      // Create the signed-in session and receive the current-user payload.
      const session = await signIn(payload);

      // Save the current user in the top-level app shell.
      props.onSignedIn(session.currentUser);

      // Route directly into the dashboard once sign-in succeeds.
      navigate('/dashboard');
    } catch (caughtError) {
      // Surface sign-in failures directly inside the auth screen.
      setSubmitError(caughtError instanceof Error ? caughtError.message : 'Unable to sign in.');
    } finally {
      // Restore the submit button state after the auth request settles.
      setIsSubmitting(false);
    }
  }

  /**
   * Starts the browser redirect flow for Google SSO.
   */
  function handleGoogleSignInClick(): void {
    setSubmitError('');

    // Redirect the browser to the backend route that begins Google OAuth.
    beginGoogleSignIn();
  }

  // Present the signed-out auth shell and role guidance together.
  return (
    <div className="auth-shell">
      <section className="auth-panel auth-panel-hero">
        <p className="eyebrow">{googleSsoEnabled ? 'Google SSO' : 'Guided sign-in'}</p>
        <h1>{googleSsoEnabled ? 'Sign in with Google to enter mission control.' : 'Choose your role before you enter mission control.'}</h1>
        <p className="muted-copy">
          {googleSsoEnabled
            ? 'Your Google account will be mapped to an app role from the backend email and domain rules before the session is created.'
            : 'This demo now signs users in, maps them to roles, and unlocks guided connection flows for GitHub, Linear, and docs.'}
        </p>

        {googleSsoEnabled ? (
          <div className="stacked-copy">
            <p className="muted-copy">Reviewer and operator access now comes from configured Google role-mapping rules instead of a client-selected role.</p>
            <p className="muted-copy">Use a Google account that has already been mapped to `admin`, `tech_lead`, or `engineer` on the backend.</p>
          </div>
        ) : (
          <div className="auth-role-grid">
            {roleOptions.map((roleOption) => (
              <button
                className={roleOption.role === role ? 'role-card role-card-active' : 'role-card'}
                key={roleOption.role}
                onClick={() => { setRole(roleOption.role); }}
                type="button"
              >
                <strong>{roleOption.title}</strong>
                <span className="muted-copy">{roleOption.description}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="auth-panel">
        {isLoadingAuthConfig ? (
          <div className="stacked-copy">
            <p className="eyebrow">Checking auth</p>
            <h2>Loading sign-in methods...</h2>
            <p className="muted-copy">The app is checking whether Google SSO or the local fallback is available.</p>
          </div>
        ) : googleSsoEnabled ? (
          <div className="form-grid">
            <div className="field-group field-group-wide">
              <span>Google sign-in</span>
              <p className="muted-copy">Continue with Google to create the same app session used by the rest of the control pane.</p>
            </div>

            {authConfigError ? <p className="error-copy">{authConfigError}</p> : null}
            {submitError ? <p className="error-copy">{submitError}</p> : null}

            <div className="form-actions">
              <button className="primary-button" onClick={handleGoogleSignInClick} type="button">
                Continue with Google
              </button>
            </div>
          </div>
        ) : guidedSignInEnabled ? (
          <form className="form-grid" onSubmit={(event) => { void handleSubmit(event); }}>
            <label className="field-group">
              <span>Name</span>
              <input onChange={(event) => { setName(event.target.value); }} placeholder="Maya Chen" type="text" value={name} />
            </label>

            <label className="field-group">
              <span>Email</span>
              <input onChange={(event) => { setEmail(event.target.value); }} placeholder="maya.chen@example.com" type="email" value={email} />
            </label>

            <label className="field-group">
              <span>Role</span>
              <select onChange={(event) => { setRole(event.target.value as UserRole); }} value={role}>
                {roleOptions.map((roleOption) => (
                  <option key={roleOption.role} value={roleOption.role}>
                    {roleOption.title}
                  </option>
                ))}
              </select>
            </label>

            <div className="field-group field-group-wide">
              <span>What this role unlocks</span>
              <ul className="detail-list compact-list">{roleCapabilityItems}</ul>
            </div>

            {authConfigError ? <p className="error-copy">{authConfigError}</p> : null}
            {submitError ? <p className="error-copy">{submitError}</p> : null}

            <div className="form-actions">
              <button className="primary-button" disabled={isSubmitting || !name || !email} type="submit">
                {isSubmitting ? 'Signing in...' : 'Enter mission control'}
              </button>
            </div>
          </form>
        ) : (
          <div className="stacked-copy">
            <p className="eyebrow">Auth unavailable</p>
            <h2>No sign-in method is available.</h2>
            <p className="muted-copy">Configure Google SSO or re-enable the local fallback before trying again.</p>
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * Handles the browser redirect back from Google OAuth and restores the app session.
 */
function GoogleAuthCallbackPage(props: { onSignedIn: (user: CurrentUser) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { onSignedIn } = props;
  const [error, setError] = useState<string>('');
  const [isCompletingSignIn, setIsCompletingSignIn] = useState<boolean>(true);

  useEffect(() => {
    let isActive = true;

    /**
     * Finishes the frontend side of the Google sign-in callback flow.
     */
    async function completeGoogleSignIn(): Promise<void> {
      const queryParams = new URLSearchParams(location.search);
      const authError = queryParams.get('error') ?? '';
      const exchangeCode = queryParams.get('code') ?? '';

      if (authError) {
        // Surface the backend or provider failure directly in the callback screen.
        setError(authError);
        setIsCompletingSignIn(false);
        return;
      }

      if (!exchangeCode) {
        // Reject callback URLs that do not include the one-time exchange code.
        setError('Google sign-in did not return a usable exchange code.');
        setIsCompletingSignIn(false);
        return;
      }

      try {
        // Exchange the callback code for the same app session used by guided sign-in.
        const session = await exchangeGoogleAuthCode(exchangeCode);

        if (isActive) {
          // Save the signed-in user in the top-level app shell before navigating away.
          onSignedIn(session.currentUser);

          // Force a full app reload so the restored session drives the authenticated route tree.
          window.location.replace('/dashboard');
        }
      } catch (caughtError) {
        if (isActive) {
          // Surface exchange failures directly in the callback screen for recovery.
          setError(caughtError instanceof Error ? caughtError.message : 'Unable to complete Google sign-in.');
          setIsCompletingSignIn(false);
        }
      }
    }

    // Complete the Google callback flow once after the route receives the redirect.
    void completeGoogleSignIn();

    return () => {
      // Ignore late exchange responses after the callback screen unmounts.
      isActive = false;
    };
  }, [location.search, navigate, onSignedIn]);

  if (isCompletingSignIn) {
    // Keep the user on a focused loading screen while the session exchange completes.
    return <StandaloneStatePanel body="Finishing the redirect and restoring your access." eyebrow="Google sign-in" title="Completing your sign-in..." />;
  }

  // Surface callback failures in a readable standalone auth panel.
  return (
    <div className="auth-shell">
      <section className="auth-panel auth-panel-centered">
        <p className="eyebrow">Google sign-in failed</p>
        <h1>Unable to complete sign-in.</h1>
        <p className="muted-copy">{error}</p>
        <div className="form-actions">
          <Link className="ghost-button link-button" to="/sign-in">
            Back to sign-in
          </Link>
        </div>
      </section>
    </div>
  );
}

/**
 * Forwards a Google OAuth browser return on the frontend origin to the backend callback handler.
 */
function GoogleOAuthReturnPage() {
  const location = useLocation();

  useEffect(() => {
    const callbackBaseUrl = import.meta.env.VITE_API_BASE_URL ?? '';
    const callbackUrl = `${callbackBaseUrl}/api/auth/google/callback${location.search}`;

    // Hand the raw Google callback parameters to the backend so it can validate state and exchange the code.
    window.location.replace(callbackUrl);
  }, [location.search]);

  // Keep the user on a focused loading screen while the browser is forwarded to the backend callback route.
  return <StandaloneStatePanel body="Handing the Google callback back to the backend sign-in handler." eyebrow="Google sign-in" title="Redirecting your callback..." />;
}

/**
 * Blocks a route when the signed-in user lacks the required role.
 */
function RoleGate(props: { currentUser: CurrentUser; allowedRoles: UserRole[]; title: string; children: ReactNode }) {
  if (canAccessRole(props.currentUser.role, props.allowedRoles)) {
    // Render the protected route when the user role has access.
    return <>{props.children}</>;
  }

  // Render a friendly access-denied state for unauthorized routes.
  return <AccessDeniedState currentUser={props.currentUser} title={props.title} />;
}

/**
 * Shows the live mission control dashboard.
 */
function DashboardPage() {
  const query = useApiQuery(fetchDashboard, []);

  if (query.isLoading) {
    // Render a lightweight loading state while dashboard data is fetched.
    return <LoadingState message="Loading mission control data..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the dashboard request fails.
    return <ErrorState message={query.error ?? 'Dashboard data was unavailable.'} />;
  }

  // Limit the dashboard run feed to runs backed by real Linear issues.
  const linearLinkedRuns = query.data.runs.filter((run) => run.issue?.provider === 'linear');
  const metricCards: ReactNode[] = [];
  const runCards: ReactNode[] = [];
  const blockedItems: ReactNode[] = [];
  const suggestedItems: ReactNode[] = [];
  const integrationCards: ReactNode[] = [];

  // Build cards explicitly so the UI stays easy to reshape later.
  for (const metric of query.data.metrics) {
    metricCards.push(<MetricCard hint={metric.hint} key={metric.label} label={metric.label} value={metric.value} />);
  }

  // Build the active run list from the fetched execution feed.
  for (const run of linearLinkedRuns) {
    runCards.push(
      <Link className="run-row" key={run.id} to={`/tasks/${run.id}`}>
        <div className="run-row-main">
          <div className="run-ticket">
            <p className="ticket-code">{run.ticket}</p>
            <h3>{run.title}</h3>
          </div>
          <p className="muted-copy">{run.summary}</p>
          <p className="subtle-copy">
            Linear-linked issue · {run.repo} · {run.agent}
          </p>
        </div>

        <div className="run-row-meta">
          <StatusBadge risk={run.risk} status={run.status} />
          <span>{run.repo}</span>
          <span>{run.owner}</span>
          <span>{run.runtime}</span>
        </div>
      </Link>,
    );
  }

  // Render the blocked reasons in the right rail from API data.
  for (const reason of query.data.blockedReasons) {
    blockedItems.push(
      <p className="rail-item" key={reason}>
        {reason}
      </p>,
    );
  }

  // Render the suggested next actions in the right rail from API data.
  for (const action of query.data.suggestedActions) {
    suggestedItems.push(
      <p className="rail-item" key={action}>
        {action}
      </p>,
    );
  }

  // Render provider integration cards so the operator can see live vs fallback modes.
  for (const status of query.data.integrationStatuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  // Surface the operational view, queue summary, and blocked context together.
  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Live operations</p>
          <h3>Track AI work across planning, implementation, testing, review, and integration status.</h3>
          <p className="muted-copy">
            The dashboard now mixes real provider integrations when configured and safe fallbacks when credentials are absent.
          </p>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.currentUser.role}</span>
          <span className="pill">{query.data.integrationStatuses.length} provider categories</span>
        </div>
      </section>

      <section className="metric-grid">{metricCards}</section>

      <section className="content-grid">
        <Panel
          body={
            runCards.length > 0
              ? <div className="run-list">{runCards}</div>
              : <p className="muted-copy">No live Linear-linked runs are available yet.</p>
          }
          title="Active and recent runs"
        />

        <div className="rail-stack">
          <Panel body={<div className="rail-list">{blockedItems}</div>} title="Blocked reasons" />
          <Panel body={<div className="rail-list">{suggestedItems}</div>} title="Suggested next actions" />
        </div>
      </section>

      <Panel body={<div className="integration-grid">{integrationCards}</div>} title="Integration status" />
    </div>
  );
}

/**
 * Shows the integrated task intake flow.
 */
function WorkIntakePage() {
  const query = useApiQuery(fetchIntakeOptions, []);
  const navigate = useNavigate();
  const [selectedIssueId, setSelectedIssueId] = useState<string>('');
  const [selectedRepoName, setSelectedRepoName] = useState<string>('');
  const [title, setTitle] = useState<string>('');
  const [prompt, setPrompt] = useState<string>('');
  const [acceptanceCriteria, setAcceptanceCriteria] = useState<string>('');
  const [executionMode, setExecutionMode] = useState<string>('implement');
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [enrichingField, setEnrichingField] = useState<IntakeEnrichField | ''>('');
  const [enrichError, setEnrichError] = useState<string>('');
  const [enrichNotice, setEnrichNotice] = useState<string>('');

  useEffect(() => {
    if (!query.data) {
      // Skip form bootstrapping until the intake payload is available.
      return;
    }

    if (!selectedRepoName && query.data.repositories.length > 0) {
      // Default the repo selection to the first available repository option.
      setSelectedRepoName(query.data.repositories[0].name);
    }

    if (selectedDocumentIds.length === 0 && query.data.documents.length > 0) {
      // Preselect the first two knowledge sources for a sensible intake default.
      setSelectedDocumentIds(query.data.documents.slice(0, 2).map((document) => document.id));
    }
  }, [query.data, selectedDocumentIds.length, selectedRepoName]);

  useEffect(() => {
    if (!query.data || !selectedIssueId) {
      // Skip issue-driven form updates when no issue is selected.
      return;
    }

    const issue = findIssueById(query.data.issues, selectedIssueId);

    if (!issue) {
      // Skip updates when the selected issue cannot be found.
      return;
    }

    if (!title) {
      // Seed the task title from the selected issue.
      setTitle(issue.title);
    }

    if (!prompt) {
      // Seed the implementation prompt from the selected issue description.
      setPrompt(issue.description || `Implement ${issue.ticket}: ${issue.title}`);
    }

    if (!acceptanceCriteria) {
      // Seed the acceptance criteria from the selected issue title and status.
      setAcceptanceCriteria(`Deliver ${issue.ticket} with clear review evidence and preserve issue traceability from ${issue.status}.`);
    }
  }, [acceptanceCriteria, prompt, query.data, selectedIssueId, title]);

  if (query.isLoading) {
    // Render a lightweight loading state while intake options are fetched.
    return <LoadingState message="Loading integrated task intake..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the intake request fails.
    return <ErrorState message={query.error ?? 'Task intake options were unavailable.'} />;
  }

  const issueOptions: ReactNode[] = [];
  const repositoryOptions: ReactNode[] = [];
  const documentRows: ReactNode[] = [];
  const integrationCards: ReactNode[] = [];

  // Build the issue selector options from the integrated issue catalog.
  for (const issue of query.data.issues) {
    issueOptions.push(
      <option key={issue.id} value={issue.id}>
        {issue.ticket} - {issue.title}
      </option>,
    );
  }

  // Build the repository selector options from the integrated repo catalog.
  for (const repository of query.data.repositories) {
    repositoryOptions.push(
      <option key={repository.id} value={repository.name}>
        {repository.fullName || repository.name}
      </option>,
    );
  }

  // Render the selected document checkboxes used for task grounding.
  for (const document of query.data.documents) {
    documentRows.push(
      <label className="selection-row" key={document.id}>
        <input
          checked={selectedDocumentIds.includes(document.id)}
          onChange={() => {
            setSelectedDocumentIds(toggleSelection(selectedDocumentIds, document.id));
          }}
          type="checkbox"
        />
        <span>
          <strong>{document.title}</strong>
          <span className="selection-subtitle">{document.path}</span>
        </span>
      </label>,
    );
  }

  // Render the provider integration cards alongside the task form.
  for (const status of query.data.integrationStatuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  /**
   * Submits the intake form and creates a new run-backed task.
   */
  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setSubmitError('');
    setIsSubmitting(true);

    const payload: TaskCreateRequest = {
      issueId: selectedIssueId || undefined,
      repoName: selectedRepoName,
      title,
      prompt,
      acceptanceCriteria,
      documentIds: selectedDocumentIds,
      executionMode,
    };

    try {
      // Create the new AI work item from the integrated intake form.
      const createdRun = await createTask(payload);

      // Navigate directly into the created task detail view.
      navigate(`/tasks/${createdRun.id}`);
    } catch (caughtError) {
      // Surface any backend mutation errors to the intake UI.
      setSubmitError(caughtError instanceof Error ? caughtError.message : 'Unable to create the task.');
    } finally {
      // Mark the form submission as complete after the request settles.
      setIsSubmitting(false);
    }
  }

  /**
   * Requests an OpenAI-backed refinement of a single intake field using repo docs.
   */
  async function handleEnrichField(field: IntakeEnrichField): Promise<void> {
    // Reset the inline enrichment status before each new request.
    setEnrichError('');
    setEnrichNotice('');
    setEnrichingField(field);

    const currentValueByField: Record<IntakeEnrichField, string> = {
      title,
      prompt,
      acceptanceCriteria,
    };

    const enrichPayload: IntakeEnrichRequest = {
      field,
      value: currentValueByField[field],
      title,
      prompt,
      acceptanceCriteria,
      repoName: selectedRepoName,
      executionMode,
      issueId: selectedIssueId || undefined,
    };

    try {
      // Call the backend enrichment route so OpenAI can rewrite the field with repo context.
      const enrichedResult = await enrichIntakeField(enrichPayload);
      const refinedValue = enrichedResult.value;

      if (field === 'title') {
        // Apply the refined value to the task title textbox.
        setTitle(refinedValue);
      } else if (field === 'prompt') {
        // Apply the refined value to the prompt textbox.
        setPrompt(refinedValue);
      } else {
        // Apply the refined value to the acceptance criteria textbox.
        setAcceptanceCriteria(refinedValue);
      }

      setEnrichNotice(
        enrichedResult.docsConsidered
          ? `Refined with ${enrichedResult.model} using repo docs context.`
          : `Refined with ${enrichedResult.model} (no repo docs were available to ground the response).`,
      );
    } catch (caughtError) {
      // Surface enrichment failures so the user can retry or adjust configuration.
      setEnrichError(caughtError instanceof Error ? caughtError.message : 'Unable to enrich this field.');
    } finally {
      // Mark the inline enrichment request as complete.
      setEnrichingField('');
    }
  }

  // Render the integrated task intake experience.
  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Integrated intake</p>
          <h3>Create a new AI work item from GitHub repo context, Linear issues, and repo markdown knowledge.</h3>
          <p className="muted-copy">This view uses the hybrid integration layer and falls back safely when provider credentials are missing.</p>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.repositories.length} repos</span>
          <span className="pill">{query.data.issues.length} issues</span>
        </div>
      </section>

      <section className="content-grid intake-grid">
        <Panel
          title="Create task"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleSubmit(event); }}>
              <label className="field-group">
                <span>Issue</span>
                <select onChange={(event) => { setSelectedIssueId(event.target.value); }} value={selectedIssueId}>
                  <option value="">No linked issue</option>
                  {issueOptions}
                </select>
              </label>

              <label className="field-group">
                <span>Repository</span>
                <select onChange={(event) => { setSelectedRepoName(event.target.value); }} value={selectedRepoName}>
                  {repositoryOptions}
                </select>
              </label>

              <label className="field-group">
                <span>Execution mode</span>
                <select onChange={(event) => { setExecutionMode(event.target.value); }} value={executionMode}>
                  <option value="implement">Implement</option>
                  <option value="research">Research</option>
                  <option value="review">Review</option>
                  <option value="test">Test</option>
                </select>
              </label>

              <div className="field-group field-group-wide">
                <label className="field-group">
                  <span>Task title</span>
                  <input onChange={(event) => { setTitle(event.target.value); }} placeholder="Build settings workflow" type="text" value={title} />
                </label>
                <div className="enrich-row">
                  <button
                    className="ghost-button enrich-button"
                    disabled={enrichingField !== '' || isSubmitting}
                    onClick={() => { void handleEnrichField('title'); }}
                    type="button"
                  >
                    {enrichingField === 'title' ? 'Enriching title...' : 'Enrich title with repo docs'}
                  </button>
                </div>
              </div>

              <div className="field-group field-group-wide">
                <label className="field-group">
                  <span>Prompt</span>
                  <textarea onChange={(event) => { setPrompt(event.target.value); }} rows={5} value={prompt} />
                </label>
                <div className="enrich-row">
                  <button
                    className="ghost-button enrich-button"
                    disabled={enrichingField !== '' || isSubmitting}
                    onClick={() => { void handleEnrichField('prompt'); }}
                    type="button"
                  >
                    {enrichingField === 'prompt' ? 'Enriching prompt...' : 'Enrich prompt with repo docs'}
                  </button>
                </div>
              </div>

              <div className="field-group field-group-wide">
                <label className="field-group">
                  <span>Acceptance criteria</span>
                  <textarea onChange={(event) => { setAcceptanceCriteria(event.target.value); }} rows={4} value={acceptanceCriteria} />
                </label>
                <div className="enrich-row">
                  <button
                    className="ghost-button enrich-button"
                    disabled={enrichingField !== '' || isSubmitting}
                    onClick={() => { void handleEnrichField('acceptanceCriteria'); }}
                    type="button"
                  >
                    {enrichingField === 'acceptanceCriteria' ? 'Enriching acceptance criteria...' : 'Enrich acceptance criteria with repo docs'}
                  </button>
                </div>
              </div>

              {enrichError ? <p className="error-copy">{enrichError}</p> : null}
              {enrichNotice ? <p className="muted-copy enrich-notice">{enrichNotice}</p> : null}

              <div className="field-group field-group-wide">
                <span>Knowledge sources</span>
                <div className="selection-list">{documentRows}</div>
              </div>

              {submitError ? <p className="error-copy">{submitError}</p> : null}

              <div className="form-actions">
                <button className="primary-button" disabled={isSubmitting || !selectedRepoName || !title || !prompt} type="submit">
                  {isSubmitting ? 'Creating task...' : 'Create task'}
                </button>
              </div>
            </form>
          }
        />

        <Panel title="Provider readiness" body={<div className="integration-grid">{integrationCards}</div>} />
      </section>
    </div>
  );
}

/**
 * Shows the full evidence package for a single task.
 */
function TaskDetailPage(props: { currentUser: CurrentUser }) {
  const params = useParams();
  const runId = params.runId ?? '';
  const query = useApiQuery(() => fetchRunDetail(runId), [runId], { pollIntervalMs: 2000 });
  const [runOverride, setRunOverride] = useState<RunSummary | null>(null);
  const [decisionNotes, setDecisionNotes] = useState<string>('');
  const [mutationError, setMutationError] = useState<string>('');
  const [isMutating, setIsMutating] = useState<boolean>(false);
  const [activeEvidenceTab, setActiveEvidenceTab] = useState<EvidenceTabId>('diff');
  const canReview = canAccessRole(props.currentUser.role, reviewerRoles);

  useEffect(() => {
    if (query.data) {
      // Keep the local run snapshot synchronized with the latest polled backend payload.
      setRunOverride(query.data);
    }
  }, [query.data]);

  useEffect(() => {
    // Reset the visible evidence tab whenever the user navigates to a different run.
    setActiveEvidenceTab('diff');
    setRunOverride(null);
  }, [runId]);

  const selectedRun = runOverride ?? query.data;

  if (query.isLoading && !selectedRun) {
    // Render a focused loading state while the selected run is being fetched.
    return <LoadingState message="Loading task detail..." />;
  }

  if ((query.error || !query.data) && !selectedRun) {
    // Render a recoverable error state when the requested run cannot be loaded.
    return <ErrorState message={query.error ?? 'Task detail was unavailable.'} />;
  }

  if (!selectedRun) {
    // Guard against an impossible state where no run payload is available.
    return <ErrorState message="No run data was available for this task." />;
  }

  const activeRun = selectedRun;
  const liveView = activeRun.liveView ?? buildFallbackRunLiveView(activeRun);

  /**
   * Posts an approval decision and stores the updated run payload locally.
   */
  async function handleDecision(decision: ApprovalDecisionRequest['decision']): Promise<void> {
    setMutationError('');
    setIsMutating(true);

    try {
      // Send the approval decision to the backend so the audit history updates.
      const updatedRun = await createApprovalDecision({
        runId: activeRun.id,
        decision,
        notes: decisionNotes,
      });

      // Update the local run state with the server-confirmed result.
      setRunOverride(updatedRun);
    } catch (caughtError) {
      // Surface mutation errors directly in the task detail view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to record the decision.');
    } finally {
      // Mark the mutation as complete after the request settles.
      setIsMutating(false);
    }
  }

  /**
   * Starts or restarts the selected run from the task detail page.
   */
  async function handleRunStart(): Promise<void> {
    setMutationError('');
    setIsMutating(true);

    try {
      // Start or restart the run against the integrated backend workflow surface.
      const updatedRun = await createRun({
        taskId: activeRun.id,
        agentName: 'impl-agent',
        executionMode: 'implement',
      });

      // Keep the local task detail view in sync with the backend response.
      setRunOverride({
        ...activeRun,
        ...updatedRun,
        issue: activeRun.issue,
        pullRequest: activeRun.pullRequest,
        ci: activeRun.ci,
        documents: activeRun.documents,
        requestedBy: activeRun.requestedBy,
        approvalHistory: activeRun.approvalHistory,
      });
    } catch (caughtError) {
      // Surface run start errors directly in the task detail UI.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to start the run.');
    } finally {
      // Mark the mutation as complete after the request settles.
      setIsMutating(false);
    }
  }

  // Present everything the reviewer needs on one page.
  return (
    <div className="page-grid">
      <section className="task-header panel">
        <div>
          <p className="eyebrow">{activeRun.ticket}</p>
          <h3>{activeRun.title}</h3>
          <p className="muted-copy">{activeRun.summary}</p>
          <p className="subtle-copy">
            {activeRun.issue?.ticket ?? activeRun.ticket} · {activeRun.issue?.provider ?? 'fallback'} issue context
          </p>
        </div>

        <div className="task-header-meta">
          <StatusBadge risk={activeRun.risk} status={activeRun.status} />
          <div className="inline-meta">
            <span>{activeRun.repo}</span>
            <span>{activeRun.branch}</span>
            <span>{activeRun.owner}</span>
            <span>{activeRun.cost}</span>
          </div>
        </div>
      </section>

      <section className="task-grid">
        <Panel
          body={
            <div className="stacked-copy">
              <p>Linked issue: {activeRun.issue?.title ?? 'No linked issue'}</p>
              <p>Requested by: {activeRun.requestedBy?.name ?? activeRun.owner}</p>
              <p>Current step: {activeRun.currentStep}</p>
              <p>Runtime: {activeRun.runtime}</p>
              <p>Cloud agent: {activeRun.cloudAgent?.id ?? 'Not launched'}</p>
              <p>Last updated: {formatEventTime(liveView.lastUpdatedAt)}</p>
            </div>
          }
          title="Context"
        />

        <Panel
          body={<TimelineList entries={liveView.timeline} liveLabel={liveView.statusLabel} />}
          title="Run timeline"
        />

        <Panel
          body={
            <div className="action-stack">
              {canReview ? (
                <button
                  className="primary-button"
                  disabled={isMutating || activeRun.status === 'Approved' || activeRun.status === 'Merged'}
                  onClick={() => { void handleDecision('approve'); }}
                  type="button"
                >
                  {activeRun.status === 'Merged'
                    ? 'Pull request merged'
                    : activeRun.status === 'Approved'
                      ? 'Awaiting PR merge'
                      : 'Approve'}
                </button>
              ) : null}
              {canReview ? (
                <button
                  className="ghost-button"
                  disabled={isMutating || activeRun.status === 'Merged'}
                  onClick={() => { void handleDecision('retry'); }}
                  type="button"
                >
                  Request retry
                </button>
              ) : null}
              {canReview ? (
                <button
                  className="ghost-button"
                  disabled={isMutating || activeRun.status === 'Merged'}
                  onClick={() => { void handleDecision('re-scope'); }}
                  type="button"
                >
                  Re-scope task
                </button>
              ) : null}
              {canReview ? (
                <button
                  className="ghost-button"
                  disabled={isMutating || activeRun.status === 'Merged'}
                  onClick={() => { void handleDecision('escalate'); }}
                  type="button"
                >
                  Escalate to human
                </button>
              ) : null}
              <button className="ghost-button" disabled={isMutating} onClick={() => { void handleRunStart(); }} type="button">
                Start run
              </button>
              {canReview ? (
                <textarea
                  className="notes-input"
                  onChange={(event) => { setDecisionNotes(event.target.value); }}
                  placeholder="Optional approval or retry notes"
                  rows={3}
                  value={decisionNotes}
                />
              ) : null}
              {!canReview ? <p className="muted-copy">Your role can inspect runs and start work, but reviewer decisions stay limited to tech leads and admins.</p> : null}
              {mutationError ? <p className="error-copy">{mutationError}</p> : null}
            </div>
          }
          title="Decision panel"
        />
      </section>

      <section className="content-grid task-detail-live-grid">
        <Panel
          body={<PullRequestPanelBody run={activeRun} />}
          title="Pull request"
        />

        <Panel body={<LogStream entries={liveView.logs} />} title="Streamed logs" />
      </section>

      <Panel
        body={<EvidenceTabPanel activeTab={activeEvidenceTab} liveView={liveView} onTabChange={setActiveEvidenceTab} />}
        title="Evidence"
      />

      <section className="task-grid task-grid-wide">
        <Panel
          body={
            <div className="stacked-copy">
              <DetailList items={activeRun.blockers} />
              <p className="subtle-copy">
                PR URL: {activeRun.pullRequest?.url ?? 'Not available'}
              </p>
            </div>
          }
          title="Blockers and risks"
        />
        <Panel
          body={
            <div className="stacked-copy">
              <p>Attached docs</p>
              <DocumentList documents={activeRun.documents ?? []} />
              <p>Approval history</p>
              <ApprovalHistoryList entries={activeRun.approvalHistory ?? []} />
            </div>
          }
          title="Knowledge and audit"
        />
      </section>
    </div>
  );
}

/**
 * Displays the queue of runs waiting for a human decision.
 */
function ApprovalInboxPage() {
  const query = useApiQuery(fetchApprovals, []);

  if (query.isLoading) {
    // Render an inbox loading state while the queue payload is being fetched.
    return <LoadingState message="Loading approval inbox..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the inbox request fails.
    return <ErrorState message={query.error ?? 'Approval queue was unavailable.'} />;
  }

  const queueCards: ReactNode[] = [];

  // Join queue metadata with fetched run summaries for a reviewer-friendly inbox.
  for (const item of query.data.queue) {
    const matchedRun = findRunById(query.data.runs, item);

    if (!matchedRun) {
      // Skip queue records that do not have a matching run payload.
      continue;
    }

    queueCards.push(
      <div className="queue-row" key={item.runId}>
        <div>
          <p className="ticket-code">{matchedRun.ticket}</p>
          <h3>{matchedRun.title}</h3>
          <p className="muted-copy">
            {matchedRun.repo} · Waiting {item.waitingTime} · {item.outcomeNeeded}
          </p>
          <p className="subtle-copy">
            {matchedRun.issue?.provider ?? 'fallback'} issue · {matchedRun.ci?.status ?? 'unknown'} CI
          </p>
        </div>

        <div className="queue-actions">
          <StatusBadge risk={matchedRun.risk} status={matchedRun.status} />
          <Link className="ghost-button link-button" to={`/tasks/${matchedRun.id}`}>
            Open task
          </Link>
        </div>
      </div>,
    );
  }

  // Give reviewers both queue speed and evidence context.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Approval center</p>
          <h3>Review queued runs quickly without losing issue, repo, and CI context.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">Queue: {query.data.summary.queueSize}</span>
          <span className="pill">High risk: {query.data.summary.highRisk}</span>
          <span className="pill">SLA risk: {query.data.summary.slaRisk}</span>
          <span className="pill">Review ready: {query.data.summary.reviewReady}</span>
        </div>
      </section>

      <section className="content-grid approvals-grid">
        <Panel body={<div className="queue-list">{queueCards}</div>} title="Queue" />

        <Panel
          body={
            <div className="stacked-copy">
              <p>Reviewer identity: {query.data.currentUser.name}</p>
              <p>Low-risk approvals can stay in the inbox for fast triage.</p>
              <p>High-risk runs should push reviewers into the full task detail page before approval.</p>
              <p>Rejected runs should capture notes that become future retry guidance.</p>
            </div>
          }
          title="Reviewer guidance"
        />
      </section>
    </div>
  );
}

/**
 * Shows the org and repo policy controls for AI runs.
 */
function PoliciesPage() {
  const query = useApiQuery(fetchPolicies, []);

  if (query.isLoading) {
    // Render a loading panel while the current policy pack is fetched.
    return <LoadingState message="Loading policy pack..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the policy request fails.
    return <ErrorState message={query.error ?? 'Policy data was unavailable.'} />;
  }

  const ruleCards: ReactNode[] = [];

  // Render the policy pack as readable rules instead of dense admin forms.
  for (const rule of query.data.rules) {
    ruleCards.push(
      <div className="policy-row" key={rule.name}>
        <h3>{rule.name}</h3>
        <p className="muted-copy">{rule.value}</p>
      </div>,
    );
  }

  // Emphasize that governance and visibility are core to the product.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Policy center</p>
          <h3>Define what agents can touch, what requires approval, and when runs must stop.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">Scope: {query.data.scope}</span>
          <span className="pill">Policy v{query.data.version}</span>
          <span className="pill">{query.data.rules.length} core rule groups</span>
        </div>
      </section>

      <section className="content-grid approvals-grid">
        <Panel body={<div className="policy-list">{ruleCards}</div>} title="Current rules" />

        <Panel
          body={
            <div className="action-stack">
              <button className="primary-button" type="button">
                Publish policy
              </button>
              <button className="ghost-button" type="button">
                Save draft
              </button>
              <button className="ghost-button" type="button">
                View audit history
              </button>
            </div>
          }
          title="Policy actions"
        />
      </section>
    </div>
  );
}

/**
 * Shows the integration management view.
 */
function IntegrationsPage(props: { currentUser: CurrentUser }) {
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [githubForm, setGithubForm] = useState<GitHubConnectRequest>({
    owner: '',
    repositories: '',
    token: '',
  });
  const [linearForm, setLinearForm] = useState<LinearConnectRequest>({
    apiKey: '',
    teamId: '',
  });
  const [cursorForm, setCursorForm] = useState<CursorConnectRequest>({
    apiKey: '',
    model: 'default',
  });
  const [docsForm, setDocsForm] = useState<DocsConnectRequest>({
    docsDirectory: '',
  });
  const [mutationError, setMutationError] = useState<string>('');
  const [mutationSuccess, setMutationSuccess] = useState<string>('');
  const [activeSetupId, setActiveSetupId] = useState<string>('');
  const query = useApiQuery(fetchIntegrations, [refreshKey]);
  const integrationCards: ReactNode[] = [];

  useEffect(() => {
    const githubStatus = findIntegrationStatus(query.data?.statuses ?? [], 'github');
    const linearStatus = findIntegrationStatus(query.data?.statuses ?? [], 'linear');
    const cursorStatus = findIntegrationStatus(query.data?.statuses ?? [], 'cursor_cloud_agents');
    const docsStatus = findIntegrationStatus(query.data?.statuses ?? [], 'repo_docs');

    // Mirror the saved GitHub connection into the setup form defaults.
    setGithubForm({
      owner: getConnectionValue(githubStatus, 'owner'),
      repositories: getConnectionValue(githubStatus, 'repositories'),
      token: '',
    });

    // Mirror the saved Linear connection into the setup form defaults.
    setLinearForm({
      apiKey: '',
      teamId: getConnectionValue(linearStatus, 'teamId'),
    });

    // Mirror the saved Cursor connection into the setup form defaults.
    setCursorForm({
      apiKey: '',
      model: getConnectionValue(cursorStatus, 'model') || 'default',
    });

    // Mirror the saved docs path into the setup form defaults.
    setDocsForm({
      docsDirectory: getConnectionValue(docsStatus, 'docsDirectory'),
    });
  }, [query.data]);

  if (query.isLoading) {
    // Render a loading state while the provider status payload is fetched.
    return <LoadingState message="Loading provider integrations..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the integrations request fails.
    return <ErrorState message={query.error ?? 'Integration status was unavailable.'} />;
  }

  // Render provider integration cards for all configured categories.
  for (const status of query.data.statuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  /**
   * Saves the GitHub setup selected by the user.
   */
  async function handleGitHubConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('github');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the GitHub setup for the current signed-in session.
      await connectGitHub(githubForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('GitHub connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface GitHub setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect GitHub.');
    } finally {
      // Clear the active submit state when the request settles.
      setActiveSetupId('');
    }
  }

  /**
   * Saves the Linear setup selected by the user.
   */
  async function handleLinearConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('linear');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the Linear setup for the current signed-in session.
      await connectLinear(linearForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('Linear connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface Linear setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect Linear.');
    } finally {
      // Clear the active submit state when the request settles.
      setActiveSetupId('');
    }
  }

  /**
   * Saves the Cursor Cloud Agents setup selected by the user.
   */
  async function handleCursorConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('cursor_cloud_agents');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the Cursor setup for the current signed-in session.
      await connectCursor(cursorForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('Cursor Cloud Agents connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface Cursor setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect Cursor Cloud Agents.');
    } finally {
      // Clear the active submit state when the request settles.
      setActiveSetupId('');
    }
  }

  /**
   * Saves the docs path selected by the user.
   */
  async function handleDocsConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('repo_docs');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the docs path for the current signed-in session.
      await connectDocs(docsForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('Docs connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface docs setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect docs.');
    } finally {
      // Clear the active submit state when the request settles.
      setActiveSetupId('');
    }
  }

  // Render the integrations management view.
  return (
    <div className="page-grid">
      <section className="hero-panel compact-panel">
        <div>
          <p className="eyebrow">Integrations</p>
          <h3>See which providers are live, which are using fallbacks, and walk through guided setup for GitHub, Linear, and docs.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">{props.currentUser.name}</span>
          <span className="pill">{buildRoleLabel(props.currentUser.role)}</span>
          <span className="pill">{query.data.statuses.length} providers</span>
        </div>
      </section>

      <Panel body={<div className="integration-grid">{integrationCards}</div>} title="Provider status" />

      <section className="content-grid approvals-grid">
        <Panel
          title="Connect GitHub"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleGitHubConnect(event); }}>
              <p className="muted-copy">Step 1: choose an org or owner. Step 2: list the repos agents may target. Step 3: add an optional token for private repos and higher rate limits.</p>
              <label className="field-group">
                <span>Owner or org</span>
                <input
                  onChange={(event) => { setGithubForm({ ...githubForm, owner: event.target.value }); }}
                  placeholder="your-org"
                  type="text"
                  value={githubForm.owner}
                />
              </label>
              <label className="field-group">
                <span>Repositories</span>
                <input
                  onChange={(event) => { setGithubForm({ ...githubForm, repositories: event.target.value }); }}
                  placeholder="web-app, api-service"
                  type="text"
                  value={githubForm.repositories}
                />
              </label>
              <label className="field-group">
                <span>Token</span>
                <input
                  onChange={(event) => { setGithubForm({ ...githubForm, token: event.target.value }); }}
                  placeholder="Optional for public repos"
                  type="password"
                  value={githubForm.token}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'github'} type="submit">
                  {activeSetupId === 'github' ? 'Saving GitHub...' : 'Connect GitHub'}
                </button>
              </div>
            </form>
          }
        />

        <Panel
          title="Connect Linear"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleLinearConnect(event); }}>
              <p className="muted-copy">Step 1: create a Linear API key. Step 2: add an optional team ID, key, or exact name if you want intake scoped to one team.</p>
              <label className="field-group">
                <span>API key</span>
                <input
                  onChange={(event) => { setLinearForm({ ...linearForm, apiKey: event.target.value }); }}
                  placeholder="lin_api_..."
                  type="password"
                  value={linearForm.apiKey}
                />
              </label>
              <label className="field-group">
                <span>Team ID or key</span>
                <input
                  onChange={(event) => { setLinearForm({ ...linearForm, teamId: event.target.value }); }}
                  placeholder="Optional team ID, key, or name"
                  type="text"
                  value={linearForm.teamId}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'linear'} type="submit">
                  {activeSetupId === 'linear' ? 'Saving Linear...' : 'Connect Linear'}
                </button>
              </div>
            </form>
          }
        />
      </section>

      <section className="content-grid approvals-grid">
        <Panel
          title="Connect Cursor Cloud Agents"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleCursorConnect(event); }}>
              <p className="muted-copy">Step 1: add a Cursor API key. Step 2: choose a model. Step 3: use Start run on a task to launch a real agent against the connected GitHub repository with the selected Linear issue context.</p>
              <label className="field-group">
                <span>API key</span>
                <input
                  onChange={(event) => { setCursorForm({ ...cursorForm, apiKey: event.target.value }); }}
                  placeholder="cur_..."
                  type="password"
                  value={cursorForm.apiKey}
                />
              </label>
              <label className="field-group">
                <span>Model</span>
                <input
                  onChange={(event) => { setCursorForm({ ...cursorForm, model: event.target.value }); }}
                  placeholder="default"
                  type="text"
                  value={cursorForm.model}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'cursor_cloud_agents'} type="submit">
                  {activeSetupId === 'cursor_cloud_agents' ? 'Saving Cursor...' : 'Connect Cursor'}
                </button>
              </div>
            </form>
          }
        />

        <Panel
          title="Connect docs"
          body={
            <form className="form-grid" onSubmit={(event) => { void handleDocsConnect(event); }}>
              <p className="muted-copy">Step 1: point the control pane at the docs folder you want indexed. Step 2: save it so intake and review screens ground agent work in the right markdown sources.</p>
              <label className="field-group">
                <span>Docs directory</span>
                <input
                  onChange={(event) => { setDocsForm({ docsDirectory: event.target.value }); }}
                  placeholder="C:\repo\docs"
                  type="text"
                  value={docsForm.docsDirectory}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'repo_docs'} type="submit">
                  {activeSetupId === 'repo_docs' ? 'Saving docs...' : 'Connect docs'}
                </button>
              </div>
            </form>
          }
        />

        <Panel
          title="Guided setup notes"
          body={
            <div className="stacked-copy">
              <p>Roles: only admins and tech leads can manage provider connections.</p>
              <p>GitHub Actions piggybacks on the GitHub repo connection so CI status activates automatically.</p>
              <p>When GitHub plus Cursor are connected, the task detail Start run action launches a real Cursor Cloud Agent instead of the local simulator.</p>
              <p>Sessions are stored in memory for this demo, so reconnect after a backend restart.</p>
              {mutationSuccess ? <p className="success-copy">{mutationSuccess}</p> : null}
              {mutationError ? <p className="error-copy">{mutationError}</p> : null}
            </div>
          }
        />
      </section>
    </div>
  );
}

/**
 * Builds the active nav class based on the current location.
 */
function getNavLinkClassName(pathname: string, targetPath: string): string {
  // Highlight the current section so navigation stays oriented.
  return pathname === targetPath ? 'nav-link active' : 'nav-link';
}

/**
 * Reports whether a given role can access a protected route or action.
 */
function canAccessRole(role: UserRole, allowedRoles: UserRole[]): boolean {
  // Return true when the signed-in role is included in the allowed role list.
  return allowedRoles.includes(role);
}

/**
 * Builds a human-readable label for the current role badge.
 */
function buildRoleLabel(role: UserRole): string {
  if (role === 'tech_lead') {
    // Expand the tech-lead role into a readable badge label.
    return 'Tech Lead';
  }

  if (role === 'engineer') {
    // Expand the engineer role into a readable badge label.
    return 'Engineer';
  }

  // Fall back to the admin label for the remaining supported role.
  return 'Admin';
}

/**
 * Builds the sign-in capability list for the selected role.
 */
function buildRoleCapabilityItems(role: UserRole): ReactNode[] {
  const capabilities: string[] = role === 'engineer'
    ? [
        'Launch new work from the intake flow.',
        'Inspect active tasks, evidence, and attached docs.',
        'Start or restart runs without reviewer privileges.',
      ]
    : role === 'tech_lead'
      ? [
          'Launch work and review approval-ready runs.',
          'Manage guided setup for GitHub, Linear, and docs.',
          'Publish policy decisions and escalation outcomes.',
        ]
      : [
          'Access every route in the control pane.',
          'Manage reviewer workflows, policies, and integrations.',
          'Act as the top-level owner for sign-in and governance.',
        ];
  const capabilityItems: ReactNode[] = [];

  // Convert each capability string into a rendered list item.
  for (const capability of capabilities) {
    capabilityItems.push(<li key={capability}>{capability}</li>);
  }

  // Return the rendered role capability list for the auth screen.
  return capabilityItems;
}

/**
 * Finds the run associated with an approval queue record.
 */
function findRunById(runs: RunSummary[], item: ApprovalItem): RunSummary | null {
  // Search the fetched run list for the queue item's run ID.
  for (const run of runs) {
    if (run.id === item.runId) {
      // Return the first matching run detail for the inbox card.
      return run;
    }
  }

  // Return null when the queue item does not resolve to a run.
  return null;
}

/**
 * Finds an issue by ID from the intake issue catalog.
 */
function findIssueById(issues: IssueRecord[], issueId: string): IssueRecord | null {
  // Search the issue catalog for the selected issue record.
  for (const issue of issues) {
    if (issue.id === issueId) {
      // Return the matching issue record.
      return issue;
    }
  }

  // Return null when the requested issue cannot be found.
  return null;
}

/**
 * Finds an integration status record by provider ID.
 */
function findIntegrationStatus(statuses: IntegrationStatus[], integrationId: string): IntegrationStatus | null {
  // Search the fetched integration status list for the requested provider record.
  for (const status of statuses) {
    if (status.id === integrationId) {
      // Return the first matching provider status record.
      return status;
    }
  }

  // Return null when the requested provider record does not exist.
  return null;
}

/**
 * Reads a single saved connection field from an integration status.
 */
function getConnectionValue(status: IntegrationStatus | null, key: string): string {
  if (!status?.connection) {
    // Return an empty string when the provider has no saved connection payload.
    return '';
  }

  // Return the saved connection value or an empty string when it is missing.
  return status.connection.values[key] ?? '';
}

/**
 * Toggles a selection value inside a string array.
 */
function toggleSelection(currentValues: string[], value: string): string[] {
  if (currentValues.includes(value)) {
    // Remove the selected value when it is already present.
    return currentValues.filter((currentValue) => currentValue !== value);
  }

  // Append the value when it is not already selected.
  return [...currentValues, value];
}

/**
 * Builds the sidebar headline from the resolved current user.
 */
function buildUserHeadline(user: CurrentUser | null): string {
  if (!user) {
    // Fall back to a neutral headline when the current user has not loaded yet.
    return 'Loading user';
  }

  // Return the current user's display name for the sidebar summary.
  return user.name;
}

/**
 * Builds the sidebar subtitle from the resolved current user.
 */
function buildUserSubtitle(user: CurrentUser | null): string {
  if (!user) {
    // Fall back to a neutral subtitle when no user payload is available.
    return 'No identity payload available.';
  }

  // Return the resolved role and provider for the sidebar summary.
  return `${user.email} · ${buildRoleLabel(user.role)} · ${user.provider}`;
}

/**
 * Renders a compact status and risk badge.
 */
function StatusBadge(props: { status: RunStatus; risk: RiskLevel }) {
  const statusClassName = `status-badge status-${props.status.toLowerCase()} risk-${props.risk.toLowerCase()}`;

  // Keep status and risk together because both inform reviewer urgency.
  return <span className={statusClassName}>{props.status} · {props.risk}</span>;
}

/**
 * Renders a small metric summary card.
 */
function MetricCard(props: DashboardMetric) {
  // Make dashboard metrics scannable at a glance.
  return (
    <article className="metric-card">
      <p className="metric-label">{props.label}</p>
      <p className="metric-value">{props.value}</p>
      <p className="muted-copy">{props.hint}</p>
    </article>
  );
}

/**
 * Renders a provider integration status card.
 */
function IntegrationStatusCard(props: { status: IntegrationStatus }) {
  const capabilityItems: ReactNode[] = [];

  // Render each capability as a scan-friendly list item.
  for (const capability of props.status.capabilities) {
    capabilityItems.push(<li key={capability}>{capability}</li>);
  }

  // Return the provider integration status card.
  return (
    <article className="integration-card">
      <div className="integration-card-header">
        <div>
          <p className="ticket-code">{props.status.name}</p>
          <h3>{props.status.connected ? 'Connected' : 'Fallback mode'}</h3>
        </div>
        <span className={`pill integration-pill integration-pill-${props.status.mode}`}>{props.status.mode}</span>
      </div>
      <p className="muted-copy">{props.status.details}</p>
      <p className="subtle-copy">Required role: {buildRoleLabel(props.status.requiredRole)}</p>
      <p className="subtle-copy">{props.status.recommendedAction}</p>
      {props.status.connection ? <p className="subtle-copy">Connected as: {props.status.connection.label}</p> : null}
      <ul className="detail-list compact-list">{capabilityItems}</ul>
      <p className="subtle-copy">Checked: {props.status.checkedAt}</p>
    </article>
  );
}

/**
 * Renders a shared loading panel for route-level data fetches.
 */
function LoadingState(props: { message: string }) {
  // Keep loading feedback consistent across screens that fetch backend data.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Loading</p>
      <h3>{props.message}</h3>
      <p className="muted-copy">The UI is waiting for the FastAPI integration layer to respond.</p>
    </section>
  );
}

/**
 * Renders a shared error panel for route-level data fetches.
 */
function ErrorState(props: { message: string }) {
  // Keep failed requests visible without breaking the surrounding shell.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Request failed</p>
      <h3>Unable to load this control-pane view.</h3>
      <p className="muted-copy">{props.message}</p>
    </section>
  );
}

/**
 * Renders a standalone full-page state panel for auth flows.
 */
function StandaloneStatePanel(props: { eyebrow: string; title: string; body: string }) {
  // Keep loading and transition states visually consistent outside the app shell.
  return (
    <div className="auth-shell">
      <section className="auth-panel auth-panel-centered">
        <p className="eyebrow">{props.eyebrow}</p>
        <h1>{props.title}</h1>
        <p className="muted-copy">{props.body}</p>
      </section>
    </div>
  );
}

/**
 * Renders a friendly access-denied state for gated routes.
 */
function AccessDeniedState(props: { currentUser: CurrentUser; title: string }) {
  // Keep gated routes readable instead of dropping the user onto a blank page.
  return (
    <section className="panel state-panel">
      <p className="eyebrow">Access denied</p>
      <h3>{props.title} is limited to reviewers.</h3>
      <p className="muted-copy">
        {buildRoleLabel(props.currentUser.role)} sessions can still inspect dashboards and task detail, but only admins and tech leads can manage approvals, policies, and integrations.
      </p>
    </section>
  );
}

/**
 * Formats an ISO timestamp for task timeline, log, and evidence display.
 */
function formatEventTime(timestamp: string): string {
  const parsedDate = new Date(timestamp);

  if (Number.isNaN(parsedDate.getTime())) {
    // Fall back to the raw value when the timestamp cannot be parsed locally.
    return timestamp;
  }

  // Format the timestamp as a compact local time for quick scanning.
  return parsedDate.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * Builds the CSS class used for each timeline step state.
 */
function buildTimelineEntryClassName(status: RunTimelineEntry['status']): string {
  if (status === 'active') {
    // Highlight the currently streaming timeline step.
    return 'timeline-entry timeline-entry-active';
  }

  if (status === 'pending') {
    // Dim timeline steps that have not been reached yet.
    return 'timeline-entry timeline-entry-pending';
  }

  // Treat every remaining step as completed evidence.
  return 'timeline-entry timeline-entry-complete';
}

/**
 * Builds the CSS class used for each streamed log level.
 */
function buildLogEntryClassName(level: RunLogEntry['level']): string {
  if (level === 'success') {
    // Color successful log lines with the success treatment.
    return 'log-entry log-entry-success';
  }

  if (level === 'warning') {
    // Color warning log lines with the warning treatment.
    return 'log-entry log-entry-warning';
  }

  if (level === 'error') {
    // Color error log lines with the danger treatment.
    return 'log-entry log-entry-error';
  }

  // Use the neutral style for informational log lines.
  return 'log-entry log-entry-info';
}

/**
 * Builds the CSS class used for each evidence status pill.
 */
function buildEvidenceStatusClassName(status: RunEvidenceEntry['status']): string {
  if (status === 'running') {
    // Highlight evidence that is still being assembled by the live stream.
    return 'evidence-status evidence-status-running';
  }

  if (status === 'blocked') {
    // Surface blocked evidence with the warning treatment.
    return 'evidence-status evidence-status-blocked';
  }

  // Default the remaining evidence items to the captured treatment.
  return 'evidence-status evidence-status-captured';
}

/**
 * Expands an evidence tab ID into a human-readable label.
 */
function buildEvidenceTabLabel(tab: EvidenceTabId): string {
  if (tab === 'diff') {
    // Expand the diff tab into a reviewer-friendly label.
    return 'Diff';
  }

  if (tab === 'tests') {
    // Expand the tests tab into a reviewer-friendly label.
    return 'Tests';
  }

  // Expand the rationale tab into a reviewer-friendly label.
  return 'Rationale';
}

/**
 * Builds timestamped fallback evidence entries when the backend response has no live view yet.
 */
function buildFallbackEvidenceEntries(items: string[], tab: EvidenceTabId, run: RunSummary): RunEvidenceEntry[] {
  const fallbackTimestamp = new Date().toISOString();
  const fallbackEntries: RunEvidenceEntry[] = [];
  const fallbackStatus: RunEvidenceEntry['status'] = tab === 'tests' && run.status === 'Blocked'
    ? 'blocked'
    : run.status === 'Running'
      ? 'running'
      : 'captured';

  // Convert legacy string evidence into a richer fallback shape for the tabbed UI.
  for (const [index, item] of items.entries()) {
    fallbackEntries.push({
      id: `${tab}-${index}`,
      timestamp: fallbackTimestamp,
      summary: `${buildEvidenceTabLabel(tab)} evidence ${index + 1}`,
      detail: item,
      status: fallbackStatus,
    });
  }

  // Return the generated fallback evidence entries for the selected tab.
  return fallbackEntries;
}

/**
 * Builds a minimal live-view fallback from the legacy run payload shape.
 */
function buildFallbackRunLiveView(run: RunSummary): RunLiveView {
  const fallbackTimestamp = new Date().toISOString();
  const logEntries: RunLogEntry[] = [];

  // Convert legacy command evidence into a simple streamed-log fallback.
  for (const [index, command] of run.evidence.commands.entries()) {
    logEntries.push({
      id: `command-${index}`,
      timestamp: fallbackTimestamp,
      level: 'info',
      source: 'runner',
      message: `Executed: ${command}`,
    });
  }

  logEntries.push({
    id: 'run-state',
    timestamp: fallbackTimestamp,
    level: run.status === 'Blocked' ? 'warning' : 'success',
    source: 'agent',
    message: run.currentStep,
  });

  // Return a safe fallback so the task detail view remains usable between polls.
  return {
    isLive: run.status === 'Running',
    statusLabel: run.status === 'Running' ? 'Streaming live' : 'Snapshot loaded',
    lastUpdatedAt: fallbackTimestamp,
    timeline: [
      {
        id: 'current-step',
        title: run.currentStep,
        detail: run.summary,
        timestamp: fallbackTimestamp,
        status: run.status === 'Running' ? 'active' : 'complete',
      },
    ],
    logs: logEntries,
    evidenceTabs: {
      diff: buildFallbackEvidenceEntries(run.evidence.diff, 'diff', run),
      tests: buildFallbackEvidenceEntries(run.evidence.tests, 'tests', run),
      rationale: buildFallbackEvidenceEntries(run.evidence.rationale, 'rationale', run),
    },
  };
}

/**
 * Renders the run timeline with timestamps and live-state styling.
 */
function TimelineList(props: { entries: RunTimelineEntry[]; liveLabel: string }) {
  if (props.entries.length === 0) {
    // Return a neutral placeholder when no timeline data is available yet.
    return <p className="muted-copy">No timeline data is available for this run yet.</p>;
  }

  const timelineItems: ReactNode[] = [];

  // Render each timeline step with its local timestamp and current execution state.
  for (const entry of props.entries) {
    timelineItems.push(
      <li className={buildTimelineEntryClassName(entry.status)} key={entry.id}>
        <div className="timeline-entry-header">
          <strong>{entry.title}</strong>
          <span className="subtle-copy">{formatEventTime(entry.timestamp)}</span>
        </div>
        <p className="muted-copy">{entry.detail}</p>
      </li>,
    );
  }

  // Return the full run timeline together with the current live-state label.
  return (
    <div className="timeline-shell">
      <div className="timeline-meta">
        <span className="pill">{props.liveLabel}</span>
      </div>
      <ul className="timeline-list">{timelineItems}</ul>
    </div>
  );
}

/**
 * Renders the streamed execution log panel for a run.
 */
function LogStream(props: { entries: RunLogEntry[] }) {
  if (props.entries.length === 0) {
    // Return a neutral placeholder when no log lines have been recorded.
    return <p className="muted-copy">No streamed logs have been captured for this run yet.</p>;
  }

  const logItems: ReactNode[] = [];

  // Render each log line in chronological order with its source and level styling.
  for (const entry of props.entries) {
    logItems.push(
      <div className={buildLogEntryClassName(entry.level)} key={entry.id}>
        <div className="log-entry-header">
          <span>{formatEventTime(entry.timestamp)}</span>
          <span>{entry.source}</span>
        </div>
        <p>{entry.message}</p>
      </div>,
    );
  }

  // Return the live log stream panel for the selected run.
  return <div className="log-stream">{logItems}</div>;
}

/**
 * Renders the tabbed evidence view grouped by diff, tests, and rationale.
 */
function EvidenceTabPanel(props: { liveView: RunLiveView; activeTab: EvidenceTabId; onTabChange: (tab: EvidenceTabId) => void }) {
  const availableTabs: EvidenceTabId[] = ['diff', 'tests', 'rationale'];
  const activeEntries = props.liveView.evidenceTabs[props.activeTab];
  const tabButtons: ReactNode[] = [];
  const evidenceRows: ReactNode[] = [];

  // Render the evidence tab buttons with counts from the current live-view snapshot.
  for (const tab of availableTabs) {
    tabButtons.push(
      <button
        className={tab === props.activeTab ? 'evidence-tab evidence-tab-active' : 'evidence-tab'}
        key={tab}
        onClick={() => { props.onTabChange(tab); }}
        type="button"
      >
        {buildEvidenceTabLabel(tab)} ({props.liveView.evidenceTabs[tab].length})
      </button>,
    );
  }

  // Render the selected evidence tab entries with timestamps and capture state.
  for (const entry of activeEntries) {
    evidenceRows.push(
      <div className="evidence-row" key={entry.id}>
        <div className="evidence-row-header">
          <strong>{entry.summary}</strong>
          <span className={buildEvidenceStatusClassName(entry.status)}>{entry.status}</span>
        </div>
        <p className="muted-copy">{entry.detail}</p>
        <p className="subtle-copy">{formatEventTime(entry.timestamp)}</p>
      </div>,
    );
  }

  // Return the grouped tab controls and the currently selected evidence list.
  return (
    <div className="evidence-shell">
      <div className="evidence-tab-list">{tabButtons}</div>
      {evidenceRows.length > 0 ? <div className="evidence-row-list">{evidenceRows}</div> : <p className="muted-copy">No evidence has streamed into this tab yet.</p>}
    </div>
  );
}

/**
 * Renders a simple unordered list for evidence and blocker sections.
 */
function DetailList(props: { items: string[] }) {
  const listItems: ReactNode[] = [];

  // Convert each string entry into a consistently styled list item.
  for (const item of props.items) {
    listItems.push(<li key={item}>{item}</li>);
  }

  // Return the rendered detail list for the surrounding panel.
  return <ul className="detail-list">{listItems}</ul>;
}

/**
 * Renders the attached document list for a task.
 */
function DocumentList(props: { documents: DocumentRecord[] }) {
  if (props.documents.length === 0) {
    // Return a neutral placeholder when no documents are attached.
    return <p className="muted-copy">No documents were attached to this task.</p>;
  }

  const documentItems: ReactNode[] = [];

  // Render each attached document as a simple scan-friendly row.
  for (const document of props.documents) {
    documentItems.push(
      <div className="mini-row" key={document.id}>
        <strong>{document.title}</strong>
        <span className="subtle-copy">{document.path}</span>
      </div>,
    );
  }

  // Return the rendered document list.
  return <div className="mini-list">{documentItems}</div>;
}

/**
 * Builds a readable label for a reviewer or GitHub-driven approval decision.
 */
function buildApprovalDecisionLabel(decision: string): string {
  const normalizedDecision = (decision ?? '').toLowerCase();

  if (normalizedDecision === 'approve') {
    // Use an operator-friendly label for reviewer approvals recorded in the app.
    return 'Reviewer approved';
  }

  if (normalizedDecision === 'retry') {
    // Use the same friendly label scheme for reviewer retry decisions.
    return 'Reviewer requested retry';
  }

  if (normalizedDecision === 're-scope') {
    // Use the same friendly label scheme for reviewer re-scope decisions.
    return 'Reviewer re-scoped';
  }

  if (normalizedDecision === 'escalate') {
    // Use the same friendly label scheme for reviewer escalations.
    return 'Reviewer escalated';
  }

  if (normalizedDecision === 'pr_review_approved') {
    // Distinguish GitHub review approvals from reviewer-in-app approvals.
    return 'PR review approved on GitHub';
  }

  if (normalizedDecision === 'pr_merged') {
    // Capture GitHub merge events with a clear, scannable label.
    return 'Pull request merged';
  }

  // Fall back to the raw decision string when we do not have a friendly label yet.
  return decision || 'Decision recorded';
}

/**
 * Maps an approval history source into a short display chip label.
 */
function buildApprovalSourceLabel(source: string | undefined): string {
  if (source === 'github') {
    // Tag events synced from GitHub with a clear upstream source.
    return 'GitHub';
  }

  if (source === 'simulated') {
    // Tag demo-time simulated events so operators know they are not live data.
    return 'Simulated';
  }

  // Default every remaining event to the in-app reviewer source.
  return 'Reviewer';
}

/**
 * Renders the approval history list for a task including reviewer and GitHub events.
 */
function ApprovalHistoryList(props: { entries: RunSummary['approvalHistory'] }) {
  if (!props.entries || props.entries.length === 0) {
    // Return a neutral placeholder when there is no approval history yet.
    return <p className="muted-copy">No approval actions have been recorded yet.</p>;
  }

  const historyItems: ReactNode[] = [];

  // Render each approval record with its acting user, source, and timestamp.
  for (const entry of props.entries) {
    const sourceLabel = buildApprovalSourceLabel(entry.source);
    const decisionLabel = buildApprovalDecisionLabel(entry.decision);
    const sourceClassName = `pill approval-source-pill approval-source-${(entry.source ?? 'reviewer').toLowerCase()}`;

    historyItems.push(
      <div className="mini-row approval-history-row" key={`${entry.timestamp}-${entry.decision}-${entry.source ?? 'reviewer'}`}>
        <div className="approval-history-header">
          <strong>{decisionLabel}</strong>
          <span className={sourceClassName}>{sourceLabel}</span>
        </div>
        <span className="subtle-copy">
          {entry.actor.name} · {entry.actor.role} · {formatEventTime(entry.timestamp)}
        </span>
        {entry.notes ? <span className="muted-copy">{entry.notes}</span> : null}
      </div>,
    );
  }

  // Return the rendered approval history list.
  return <div className="mini-list">{historyItems}</div>;
}

/**
 * Builds a human-readable label for a pull-request state or status field.
 */
function buildPullRequestStateLabel(run: RunSummary): string {
  const pullRequest = run.pullRequest;

  if (!pullRequest) {
    // Return a neutral placeholder when the run has no linked PR payload yet.
    return 'Not linked';
  }

  const normalizedState = (pullRequest.state ?? pullRequest.status ?? '').toLowerCase();

  if (normalizedState === 'merged') {
    // Flag merged PRs explicitly so reviewers know the run is terminal.
    return 'Merged';
  }

  if (normalizedState === 'approved') {
    // Flag approved-but-open PRs so reviewers know the app is waiting on merge.
    return 'Approved, awaiting merge';
  }

  if (normalizedState === 'closed') {
    // Flag closed-without-merge PRs so reviewers can decide next steps.
    return 'Closed without merge';
  }

  if (normalizedState === 'draft') {
    // Flag draft PRs so reviewers know the run has not been handed off yet.
    return 'Draft';
  }

  if (normalizedState === 'ready_for_review' || normalizedState === 'open') {
    // Flag review-ready PRs with a clear, scannable label.
    return 'Open - awaiting review';
  }

  // Default every remaining state to the raw display value.
  return pullRequest.state ?? pullRequest.status ?? 'Unknown';
}

/**
 * Renders the combined pull-request and CI summary panel body for a task.
 */
function PullRequestPanelBody(props: { run: RunSummary }) {
  const prInfo = props.run.pullRequest;
  const stateLabel = buildPullRequestStateLabel(props.run);
  const approvedAt = prInfo?.approvedAt ? formatEventTime(prInfo.approvedAt) : null;
  const mergedAt = prInfo?.mergedAt ? formatEventTime(prInfo.mergedAt) : null;
  const sourceLabel = prInfo?.source === 'github'
    ? 'GitHub (live)'
    : prInfo?.source === 'simulated'
      ? 'Simulated'
      : 'Control pane';

  // Return the combined PR + CI summary used on the task detail page.
  return (
    <div className="stacked-copy">
      <p>
        Pull request: <strong>{stateLabel}</strong>
      </p>
      <p className="subtle-copy">PR source: {sourceLabel}</p>
      {prInfo?.number ? <p className="subtle-copy">PR number: #{prInfo.number}</p> : null}
      {prInfo?.approved ? (
        <p className="subtle-copy">
          Approved{prInfo.approvedBy ? ` by ${prInfo.approvedBy}` : ''}
          {approvedAt ? ` at ${approvedAt}` : ''}
        </p>
      ) : null}
      {prInfo?.merged ? (
        <p className="subtle-copy">Merged{mergedAt ? ` at ${mergedAt}` : ''}</p>
      ) : null}
      <p>Cursor status: {props.run.cloudAgent?.status ?? 'Unavailable'}</p>
      <p>CI workflow: {props.run.ci?.workflow ?? 'Unavailable'}</p>
      <p>CI status: {props.run.ci?.status ?? 'Unavailable'}</p>
      <p>Cloud agent URL: {props.run.cloudAgent?.target?.url ?? 'Unavailable'}</p>
      <p className="muted-copy">{props.run.ci?.summary ?? 'No CI summary available.'}</p>
    </div>
  );
}

/**
 * Wraps page sections in a consistent panel treatment.
 */
function Panel(props: { title: string; body: ReactNode }) {
  // Keep content framing consistent across dashboard, review, and policy views.
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>{props.title}</h3>
      </div>
      <div className="panel-body">{props.body}</div>
    </section>
  );
}

export default App;
