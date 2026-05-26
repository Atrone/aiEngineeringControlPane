import type { FormEvent, MouseEvent, ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { AccessDeniedState, StandaloneStatePanel } from '../components/ui';
import {
  beginGoogleSignIn,
  fetchAuthConfig,
  signIn,
} from '../lib/api';
import {
  buildRoleCapabilityItems,
  buildShellPageTitle,
  buildUserHeadline,
  buildUserSubtitle,
  canAccessRole,
  exchangeGoogleAuthCodeOnce,
  getNavLinkClassName,
  reviewerRoles,
} from '../lib/appHelpers';
import type { AuthConfig, CurrentUser, SignInRequest, UserRole } from '../types/controlPane';

/**
 * Renders the public product landing page before visitors reach sign-in.
 */
function LandingPage() {
  const [selectedWorkflowScreenshotSrc, setSelectedWorkflowScreenshotSrc] = useState<string | null>(null);
  const highlights = [
    'Route intake from GitHub, Linear, Jira, and docs into one Discord-style review channel.',
    'Watch agent runs move through channel updates, evidence, blockers, approval, and merge decisions.',
    'Give reviewers a connected workspace for every automation handoff.',
  ];
  const workflowScreenshots = [
    {
      alt: 'Run Channels lobby showing servers, run metrics, and suggested next actions.',
      caption: 'Run lobby',
      src: '/landing-run-channels.png',
    },
    {
      alt: 'New Work intake page with issue, repository, mode, documents, and task setup steps.',
      caption: 'Integrated intake',
      src: '/landing-new-work.png',
    },
    {
      alt: 'Issue selection step separating well scoped and poorly scoped work items.',
      caption: 'Issue triage',
      src: '/landing-issue-selection.png',
    },
    {
      alt: 'Repository and execution mode selection for a linked engineering issue.',
      caption: 'Repository and mode',
      src: '/landing-repository-mode.png',
    },
    {
      alt: 'Document upload and generated task brief review before launching agent work.',
      caption: 'Grounded task brief',
      src: '/landing-docs-task-brief.png',
    },
    {
      alt: 'Run lobby showing an active agent run for a selected server.',
      caption: 'Live run tracking',
      src: '/landing-run-lobby-active.png',
    },
    {
      alt: 'Run room showing a creating Cursor Cloud Agent state and live run stream.',
      caption: 'Agent launch',
      src: '/landing-run-room-creating.png',
    },
    {
      alt: 'Cursor Cloud Agent handoff page summarizing implementation, validation, and changed files.',
      caption: 'Agent handoff',
      src: '/landing-agent-handoff.png',
    },
    {
      alt: 'Run room with pull request status, evidence tabs, and reference links.',
      caption: 'Evidence room',
      src: '/landing-run-room-links.png',
    },
    {
      alt: 'Run room showing a finished Cursor Cloud Agent and approval controls.',
      caption: 'Reviewer controls',
      src: '/landing-run-room-finished.png',
    },
    {
      alt: 'GitHub pull request with summary, validation, and issue traceability details.',
      caption: 'Linked pull request',
      src: '/landing-github-pr.png',
    },
  ];
  let selectedWorkflowScreenshot: (typeof workflowScreenshots)[number] | null = null;

  for (const screenshot of workflowScreenshots) {
    if (screenshot.src === selectedWorkflowScreenshotSrc) {
      // Store the matched screenshot so the modal renders the same caption and alt copy.
      selectedWorkflowScreenshot = screenshot;
      break;
    }
  }

  /**
   * Opens the clicked workflow screenshot in the enlarged preview overlay.
   */
  function handleWorkflowScreenshotOpen(event: MouseEvent<HTMLButtonElement>): void {
    // Read the selected screenshot path from the button value to avoid allocating per-card handlers.
    setSelectedWorkflowScreenshotSrc(event.currentTarget.value);
  }

  /**
   * Closes the enlarged workflow screenshot preview.
   */
  function handleWorkflowScreenshotClose(): void {
    // Clear the selected screenshot so the modal is removed from the DOM.
    setSelectedWorkflowScreenshotSrc(null);
  }

  // Keep the landing page static so it stays available before any auth config loads.
  return (
    <main className="landing-shell">
      <nav aria-label="Landing page" className="landing-nav">
        <Link className="landing-brand" to="/">
          <span>
            <strong>Engineering Command Center</strong>
          </span>
        </Link>
        <Link className="ghost-button" to="/sign-in">
          Sign in
        </Link>
      </nav>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="eyebrow">engineering operations</p>
          <h1 id="landing-title">Coordinate AI work across team servers.</h1>
          <p className="muted-copy">
            Engineering Command Center gives product teams one server-like hub to request work, monitor agent execution,
            inspect evidence, and approve the next step.
          </p>
          <div className="landing-actions">
            <Link className="primary-button" to="/sign-in">
              Enter command center
            </Link>
            <a className="ghost-button" href="#landing-workflow">
              See how it works
            </a>
          </div>
        </div>

        <div className="landing-preview-card" aria-label="Run room preview">
          <div className="landing-preview-header">
            <span className="status-badge status-running">Live run</span>
            <span className="subtle-copy">checkout-flow</span>
          </div>
          <div className="landing-preview-room">
            <p className="eyebrow">run room</p>
            <h2>Ship mobility payment retry copy</h2>
            <p className="muted-copy">Evidence is ready, CI passed, and one reviewer decision is waiting.</p>
            <div className="landing-preview-grid">
              <span>Diff captured</span>
              <span>Tests passed</span>
              <span>PR linked</span>
              <span>Approval queued</span>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-capability-grid" id="landing-capabilities" aria-label="Product capabilities">
        {highlights.map((highlight, index) => (
          <article className="landing-capability-card" key={highlight}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <p>{highlight}</p>
          </article>
        ))}
      </section>

      <section className="landing-workflow-panel" id="landing-workflow" aria-labelledby="landing-workflow-title">
        <div className="landing-workflow-copy">
          <p className="eyebrow">How it works</p>
          <h2 id="landing-workflow-title">From request to reviewed pull request in one command center.</h2>
        </div>
        <ol className="landing-workflow-list">
          <li>
            <strong>Capture the work</strong>
            <span>Start from an issue, repository, and attached docs so the agent has the right context.</span>
          </li>
          <li>
            <strong>Track the run</strong>
            <span>Follow status, evidence, blockers, tests, and linked pull request activity as the task moves.</span>
          </li>
          <li>
            <strong>Approve with confidence</strong>
            <span>Review the implementation package, approve the PR, or request a retry from the run room.</span>
          </li>
        </ol>
        <div className="landing-workflow-showcase" aria-label="Product workflow screenshots">
          {workflowScreenshots.map((screenshot) => (
            <figure className="landing-workflow-shot" key={screenshot.src}>
              <button
                aria-label={`Enlarge ${screenshot.caption} screenshot`}
                className="landing-workflow-shot-button"
                onClick={handleWorkflowScreenshotOpen}
                type="button"
                value={screenshot.src}
              >
                <img alt={screenshot.alt} loading="lazy" src={screenshot.src} />
              </button>
              <figcaption>{screenshot.caption}</figcaption>
            </figure>
          ))}
        </div>
      </section>
      {selectedWorkflowScreenshot ? (
        <div className="landing-image-modal" role="dialog" aria-label={`${selectedWorkflowScreenshot.caption} screenshot preview`} aria-modal="true">
          <button className="landing-image-modal-backdrop" onClick={handleWorkflowScreenshotClose} type="button">
            <span className="sr-only">Close screenshot preview</span>
          </button>
          <figure className="landing-image-modal-content">
            <button className="ghost-button landing-image-modal-close" onClick={handleWorkflowScreenshotClose} type="button">
              Close
            </button>
            <img alt={`Expanded ${selectedWorkflowScreenshot.alt}`} src={selectedWorkflowScreenshot.src} />
            <figcaption>{selectedWorkflowScreenshot.caption}</figcaption>
          </figure>
        </div>
      ) : null}
    </main>
  );
}

/**
 * Builds the shared frame around each primary page.
 */
function RootLayout(props: { currentUser: CurrentUser; onSignedOut: () => Promise<void> }) {
  const location = useLocation();
  const [isSigningOut, setIsSigningOut] = useState<boolean>(false);
  const canReview = canAccessRole(props.currentUser.role, reviewerRoles);
  const pageTitle = buildShellPageTitle(location.pathname);

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

  // Keep the shell visible so the app feels like a Discord-inspired team workspace.
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <aside aria-label="Workspace navigation" className="sidebar">
        <div className="brand-card discord-brand-card">
          <h1>Engineering</h1>
          <p className="muted-copy">
            Servers, channels, runs, and reviews stay connected in one Engineering Command Center.
          </p>
        </div>

        <nav aria-label="Primary" className="nav-list">
          <Link className={getNavLinkClassName(location.pathname, '/dashboard')} to="/dashboard">
            # run-lobby
          </Link>
          <Link className={getNavLinkClassName(location.pathname, '/intake')} to="/intake">
            # delegate-agent
          </Link>
          {canReview ? (
            <Link className={getNavLinkClassName(location.pathname, '/settings')} to="/settings">
              # settings
            </Link>
          ) : null}
        </nav>

        <div className="sidebar-card discord-user-card">
          <p className="sidebar-label">Current user</p>
          <p className="sidebar-stat">{buildUserHeadline(props.currentUser)}</p>
          <p className="muted-copy">{buildUserSubtitle(props.currentUser)}</p>
        </div>
      </aside>

      <div className="app-main">
        <main className="page-shell" id="main-content" tabIndex={-1}>
          <header className="topbar">
            <div className="topbar-leading">
              <div>
                <p className="eyebrow">Product Eng</p>
                <h2>{pageTitle}</h2>
              </div>
            </div>
            <div className="topbar-actions">
              <button className="ghost-button" disabled={isSigningOut} onClick={() => { void handleSignOutClick(); }} type="button">
                {isSigningOut ? 'Signing out...' : 'Sign out'}
              </button>
            </div>
          </header>

          <Outlet />
        </main>
      </div>
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
  const [teamId, setTeamId] = useState<string>('platform');
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const roleCapabilityItems = buildRoleCapabilityItems();
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
      role: 'admin',
      teamId,
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
    beginGoogleSignIn(teamId);
  }

  // Present the signed-out auth shell and role guidance together.
  return (
    <div className="auth-shell">
      <section className="auth-panel auth-panel-hero">
        <p className="eyebrow">{googleSsoEnabled ? 'Google SSO' : 'Guided sign-in'}</p>
        <h1>{googleSsoEnabled ? 'Sign in with Google to enter the command center.' : 'Sign in to enter the command center.'}</h1>
        <p className="muted-copy">
          {googleSsoEnabled
            ? 'Your Google account will be validated by the backend before the session is created, and every successful sign-in is treated as an admin session.'
            : 'This demo signs users in as admins and unlocks guided connection flows for GitHub, Linear, Jira, and docs.'}
        </p>

        {googleSsoEnabled ? (
          <div className="stacked-copy">
            <p className="muted-copy">Google sign-in still enforces the configured backend domain and access checks.</p>
            <p className="muted-copy">Every successful Google login is stored as an `admin` session.</p>
          </div>
        ) : (
          <div className="stacked-copy">
            <p className="muted-copy">Role selection has been removed from guided sign-in.</p>
            <p className="muted-copy">Every successful guided login is stored as an `admin` session.</p>
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
              <p className="muted-copy">Continue with Google to create the same app session used by the rest of the control plane.</p>
            </div>

            <label className="field-group">
              <span>Team ID</span>
              <input onChange={(event) => { setTeamId(event.target.value); }} placeholder="platform" type="text" value={teamId} />
            </label>

            {authConfigError ? <p className="error-copy">{authConfigError}</p> : null}
            {submitError ? <p className="error-copy">{submitError}</p> : null}

            <div className="form-actions">
              <button className="primary-button" disabled={!teamId} onClick={handleGoogleSignInClick} type="button">
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
              <span>Team ID</span>
              <input onChange={(event) => { setTeamId(event.target.value); }} placeholder="platform" type="text" value={teamId} />
            </label>

            <div className="field-group field-group-wide">
              <span>What admin access unlocks</span>
              <ul className="detail-list compact-list">{roleCapabilityItems}</ul>
            </div>

            {authConfigError ? <p className="error-copy">{authConfigError}</p> : null}
            {submitError ? <p className="error-copy">{submitError}</p> : null}

            <div className="form-actions">
              <button className="primary-button" disabled={isSubmitting || !name || !email || !teamId} type="submit">
                {isSubmitting ? 'Signing in...' : 'Enter command center'}
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
        const session = await exchangeGoogleAuthCodeOnce(exchangeCode);

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

export {
  GoogleAuthCallbackPage,
  GoogleOAuthReturnPage,
  LandingPage,
  RoleGate,
  RootLayout,
  SignInPage,
};
