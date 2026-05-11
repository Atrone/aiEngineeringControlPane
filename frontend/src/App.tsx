import type { ChangeEvent, FormEvent, KeyboardEvent, MouseEvent, ReactNode } from 'react';
import { useEffect, useId, useMemo, useState } from 'react';
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useApiQuery } from './hooks/useApiQuery';
import {
  buildMissionControlOwnerOptions,
  buildMissionControlRepoOptions,
  filterMissionControlRuns,
} from './lib/dashboardMissionControlFilters';
import type { MissionControlFilterCriteria } from './lib/dashboardMissionControlFilters';
import {
  beginGoogleSignIn,
  classifyIntakeIssuesByScope,
  connectCursor,
  clearSessionToken,
  connectGitHub,
  connectGitHubCopilot,
  connectJira,
  connectLinear,
  createApprovalDecision,
  createTask,
  enrichIntakeField,
  identifyRepositoryForIssue,
  exchangeGoogleAuthCode,
  fetchAuthConfig,
  fetchCurrentUser,
  fetchDashboard,
  fetchDashboardReviewEfforts,
  fetchDashboardSuggestedActions,
  fetchIntegrations,
  fetchIntakeOptions,
  fetchRunDetail,
  hasSessionToken,
  signIn,
  signOut,
} from './lib/api';
import type {
  AuthSession,
  AuthConfig,
  CurrentUser,
  CursorConnectRequest,
  DashboardMetric,
  DocumentRecord,
  GitHubConnectRequest,
  GitHubCopilotConnectRequest,
  IntakeEnrichField,
  IntakeEnrichRequest,
  IntakeIssueScopingResponse,
  IntegrationStatus,
  IssueRecord,
  JiraConnectRequest,
  LinearConnectRequest,
  RunEvidenceEntry,
  RunEvidenceTabs,
  RunLiveView,
  RunLogEntry,
  RiskLevel,
  ReviewEffortEstimate,
  RunSummary,
  RunStatus,
  RunTimelineEntry,
  SignInRequest,
  TaskCreateRequest,
  UploadedDocumentRecord,
  UserRole,
} from './types/controlPane';

const reviewerRoles: UserRole[] = ['admin'];
type EvidenceTabId = keyof RunEvidenceTabs;
type RunChannelTone = 'active' | 'blocked' | 'merged';
type RunTeamGroup = {
  key: string;
  label: string;
  initials: string;
  runs: RunSummary[];
  activeCount: number;
  blockedCount: number;
  mergedCount: number;
};
type TraceabilityNodeStatus = 'complete' | 'active' | 'pending' | 'blocked';
type RunTraceabilityNode = {
  id: string;
  eyebrow: string;
  title: string;
  detail: string;
  status: TraceabilityNodeStatus;
  href?: string;
  hrefLabel?: string;
};
const googleAuthCallbackExchanges = new Map<string, Promise<AuthSession>>();
/** Status values surfaced by the mission control dashboard filter dropdown. */
const missionControlDashboardStatuses: RunStatus[] = ['Running', 'Review', 'Approved', 'Blocked', 'Retry', 'Merged'];

/** Risk values surfaced by the mission control dashboard filter dropdown. */
const missionControlDashboardRisks: RiskLevel[] = ['Low', 'Medium', 'High'];

const ignoredBlockerReasons: Set<string> = new Set([
  'none',
  'no active blockers',
  'awaiting run start',
  'streaming execution in progress',
  'reviewer controls will unlock after the run completes',
  'waiting for reviewer decision',
  'cursor cloud agent is still running',
  'reviewer controls unlock after the live agent finishes',
  'awaiting pull-request merge on github',
]);

/**
 * Exchanges a Google callback code once during the current browser page load.
 */
function exchangeGoogleAuthCodeOnce(code: string): Promise<AuthSession> {
  const cachedExchange = googleAuthCallbackExchanges.get(code);

  if (cachedExchange) {
    // Reuse the first request when React remounts the callback route in development.
    return cachedExchange;
  }

  // Start the backend exchange and keep the promise available for duplicate effects.
  const exchangePromise = exchangeGoogleAuthCode(code).catch((caughtError: unknown) => {
    // Allow a real failed exchange to be retried without reloading the app.
    googleAuthCallbackExchanges.delete(code);
    throw caughtError;
  });

  // Cache the in-flight exchange before returning it to callback route effects.
  googleAuthCallbackExchanges.set(code, exchangePromise);
  return exchangePromise;
}

/**
 * Converts a browser file into the uploaded-document payload shape used by intake APIs.
 */
async function buildUploadedDocumentRecord(file: File): Promise<UploadedDocumentRecord> {
  // Read the raw file contents so enrichment can use the exact uploaded repo context.
  const content = await file.text();
  const normalizedName = file.name.trim() || 'uploaded-document.txt';
  const title = normalizedName.replace(/\.[^.]+$/, '') || normalizedName;
  const updatedAt = file.lastModified > 0
    ? new Date(file.lastModified).toISOString()
    : new Date().toISOString();

  return {
    id: `upload-${normalizedName}-${file.lastModified}-${file.size}`,
    title,
    path: `uploads/${normalizedName}`,
    source: 'uploaded_repo_document',
    updatedAt,
    content,
  };
}

/**
 * Returns the label the intake form should use for enrichment grounding.
 */
function buildEnrichmentSourceLabel(uploadedDocuments: UploadedDocumentRecord[]): string {
  if (uploadedDocuments.length > 0) {
    // Call out uploaded docs when the operator has overridden the default repo source.
    return 'uploaded docs';
  }

  // Fall back to the repository docs label when no uploads are present.
  return 'repo docs';
}

/**
 * Normalizes repository and docs-folder names for client-side matching.
 */
function normalizeRepoDocKey(value: string): string {
  // Collapse punctuation differences so repo names and docs folder names compare cleanly.
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

/**
 * Reports whether a document belongs to the shared top-level docs folder.
 */
function isSharedTopLevelDocsDocument(document: DocumentRecord): boolean {
  const normalizedPath = document.path.replace(/\\/g, '/').toLowerCase();
  const pathParts = normalizedPath.split('/');

  if (document.repoName) {
    // Repo-tagged docs are handled by the selected-repository match below.
    return false;
  }

  // Treat direct docs-folder markdown as shared context for every selected repo.
  return pathParts.length === 2 && pathParts[0] === 'docs' && (normalizedPath.endsWith('.md') || normalizedPath.endsWith('.markdown'));
}

/**
 * Returns the repo document records that belong to the selected repository.
 */
function getDocumentsForRepository(documents: DocumentRecord[], repoName: string): DocumentRecord[] {
  const selectedRepoKey = normalizeRepoDocKey(repoName);

  if (!selectedRepoKey) {
    // Return no repo-specific docs when the intake form has no selected repository.
    return [];
  }

  // Keep repo-tagged documents and shared top-level docs folder files for the selection.
  return documents.filter((document) => normalizeRepoDocKey(document.repoName ?? '') === selectedRepoKey || isSharedTopLevelDocsDocument(document));
}

/**
 * Reports whether a blocker string should contribute to the dashboard summaries.
 */
function isActionableBlocker(blocker: string): boolean {
  // Normalize the blocker text so the ignore list can use lower-case keys.
  const normalized = blocker.trim().toLowerCase();

  if (!normalized) {
    // Ignore empty blocker text so summary counts stay meaningful.
    return false;
  }

  // Return true only when the blocker adds real operator context.
  return !ignoredBlockerReasons.has(normalized);
}

/**
 * Converts an mm:ss runtime string into total seconds for metric math.
 */
function parseRuntimeSeconds(runtime: string): number {
  // Split on the first colon to extract minute and second fragments.
  const [minuteText, secondText] = runtime.split(':');

  if (secondText === undefined) {
    // Fall back to zero seconds when the runtime does not follow the expected format.
    return 0;
  }

  const minutes = Number.parseInt(minuteText, 10);
  const seconds = Number.parseInt(secondText, 10);

  if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) {
    // Fall back to zero seconds when the runtime fragments are not numeric.
    return 0;
  }

  // Clamp to a non-negative total so metric math stays sane.
  return Math.max(0, minutes * 60 + seconds);
}

/**
 * Collects unique actionable blocker reasons across Blocked and Retry runs.
 */
function collectBlockerReasons(runs: RunSummary[]): Set<string> {
  const reasons = new Set<string>();

  // Scan the visible runs for blocker reasons that deserve dashboard visibility.
  for (const run of runs) {
    if (run.status !== 'Blocked' && run.status !== 'Retry') {
      // Skip runs that are not currently stalled.
      continue;
    }

    let hasExplicitBlocker = false;

    // Record each actionable blocker captured on the run record.
    for (const blocker of run.blockers) {
      const text = String(blocker);

      if (isActionableBlocker(text)) {
        reasons.add(text.trim());
        hasExplicitBlocker = true;
      }
    }

    if (hasExplicitBlocker) {
      // Skip the current-step fallback when explicit blockers already exist.
      continue;
    }

    const currentStep = run.currentStep.trim();

    if (isActionableBlocker(currentStep)) {
      // Record the current step when the run has no better blocker data.
      reasons.add(currentStep);
    }
  }

  // Return the distinct blocker reasons surfaced by the visible runs.
  return reasons;
}

/**
 * Merges backend-blocked reason strings with actionable reasons collected from runs.
 */
function mergeDashboardBlockedReasonLists(backendReasons: string[], runs: RunSummary[]): string[] {
  const ordered: string[] = [];
  const seenLower = new Set<string>();

  // Prefer backend ordering first so the API payload stays primary for operators.
  for (const raw of backendReasons) {
    const text = raw.trim();

    if (!text) {
      // Skip blank backend rows so the rail stays compact.
      continue;
    }

    const key = text.toLowerCase();

    if (seenLower.has(key)) {
      // Skip duplicates that already appeared earlier in the merged list.
      continue;
    }

    seenLower.add(key);
    ordered.push(text);
  }

  // Append run-derived reasons without duplicating backend lines.
  for (const text of collectBlockerReasons(runs)) {
    const trimmed = text.trim();
    const key = trimmed.toLowerCase();

    if (!trimmed || seenLower.has(key)) {
      // Skip empty strings and duplicates when folding in run-level reasons.
      continue;
    }

    seenLower.add(key);
    ordered.push(trimmed);
  }

  // Return the ordered, de-duplicated list for the blocked-reasons rail.
  return ordered;
}

/**
 * Formats the review-effort metric value from OpenAI's total minute guesses.
 */
function formatReviewEffortValue(runCount: number, totalEffortMinutes: number): string {
  if (runCount === 0) {
    // Return a stable zero state while no OpenAI estimates are available.
    return '0 min';
  }

  // Return the summed OpenAI effort guesses in minutes for the dashboard metric value.
  return `${Math.max(0, Math.round(totalEffortMinutes))} min`;
}

/**
 * Derives the four dashboard metric cards from the runs shown in the selected lobby.
 */
function deriveDashboardMetrics(
  runs: RunSummary[],
  reviewEffortsByRunId: Record<string, ReviewEffortEstimate> = {},
): DashboardMetric[] {
  let activeRuns = 0;
  let runningRuns = 0;
  let reviewReadyRuns = 0;
  let approvedRuns = 0;
  let blockedRuns = 0;
  let mergedRuns = 0;
  let reviewEffortRunCount = 0;
  let totalReviewEffortMinutes = 0;

  // Aggregate the run counts needed by the dashboard cards.
  for (const run of runs) {
    const { status } = run;

    if (status === 'Running' || status === 'Review' || status === 'Approved' || status === 'Blocked' || status === 'Retry') {
      // Count non-terminal runs as active.
      activeRuns += 1;
    }

    if (status === 'Running') {
      // Count live runs that are still actively executing.
      runningRuns += 1;
    }

    if (status === 'Review') {
      // Count review-ready runs for reviewer load visibility.
      reviewReadyRuns += 1;
    }

    if (status === 'Approved') {
      // Count runs that are approved but still waiting for the PR to merge.
      approvedRuns += 1;
    }

    if (status === 'Blocked') {
      // Count blocked runs for the operational dashboard.
      blockedRuns += 1;
    }

    if (status === 'Merged') {
      // Count merged runs for the daily summary card.
      mergedRuns += 1;
    }

    const reviewEffort = reviewEffortsByRunId[run.id];

    if (reviewEffort) {
      // Sum the per-run OpenAI review-effort guesses shown in the lobby.
      reviewEffortRunCount += 1;
      totalReviewEffortMinutes += reviewEffort.effortMinutes;
    }
  }

  const blockerReasons = collectBlockerReasons(runs);
  const activeRunsHintParts: string[] = [];

  // Call out live runs first since they directly reflect current agent activity.
  activeRunsHintParts.push(`${runningRuns} running`);

  if (reviewReadyRuns > 0) {
    // Highlight review-ready runs so reviewers know where their inbox stands.
    activeRunsHintParts.push(`${reviewReadyRuns} waiting for review`);
  }

  if (approvedRuns > 0) {
    // Surface approved-but-not-merged runs so operators can watch PR merge state.
    activeRunsHintParts.push(`${approvedRuns} approved awaiting merge`);
  }

  const activeRunsHint = activeRunsHintParts.length > 0
    ? activeRunsHintParts.join(', ')
    : 'No active runs are currently in flight';

  const blockedReasonCount = blockerReasons.size;
  const blockedRunsHint = blockedRuns > 0 || blockedReasonCount > 0
    ? `${blockedReasonCount} unique blocker reason${blockedReasonCount === 1 ? '' : 's'} need follow-up`
    : 'No blocked runs currently need follow-up';

  const mergedRunsHint = mergedRuns > 0
    ? `${mergedRuns} run${mergedRuns === 1 ? '' : 's'} reached the merged state in the current session`
    : 'No merged runs are recorded in the current session';

  const reviewEffortHint = reviewEffortRunCount > 0
    ? `OpenAI PR-summary guesses across ${reviewEffortRunCount} run${reviewEffortRunCount === 1 ? '' : 's'} in this lobby`
    : 'Waiting for OpenAI review-effort guesses from PR summaries';

  // Return the derived dashboard metrics in the same order as the backend payload.
  return [
    { label: 'Active runs', value: String(activeRuns), hint: activeRunsHint },
    { label: 'Blocked tasks', value: String(blockedRuns), hint: blockedRunsHint },
    { label: 'Merged today', value: String(mergedRuns), hint: mergedRunsHint },
    { label: 'Review effort', value: formatReviewEffortValue(reviewEffortRunCount, totalReviewEffortMinutes), hint: reviewEffortHint },
  ];
}

/**
 * Reports whether a provider name belongs to a live issue tracker integration.
 */
function isIssueTrackerProvider(provider: string | undefined): boolean {
  const normalizedProvider = (provider ?? '').trim().toLowerCase();

  // Return true only for live issue tracker providers supported by the app.
  return normalizedProvider === 'linear' || normalizedProvider === 'jira';
}

/**
 * Reports whether a run is linked to a live issue-tracker record.
 */
function isIssueTrackerRun(run: RunSummary): boolean {
  // Reuse the provider helper so dashboard filters stay consistent across issue trackers.
  return isIssueTrackerProvider(run.issue?.provider);
}

/**
 * Builds the provider-specific dashboard label for an issue-linked run.
 */
function buildIssueTrackerRunLabel(run: RunSummary): string {
  const normalizedProvider = (run.issue?.provider ?? '').trim().toLowerCase();

  if (normalizedProvider === 'jira') {
    // Surface the Jira label when the run originated from Jira Cloud.
    return 'Jira-linked issue';
  }

  if (normalizedProvider === 'linear') {
    // Surface the Linear label when the run originated from Linear.
    return 'Linear-linked issue';
  }

  // Fall back to generic task context so non-tracker delegated work still reads accurately in the lobby.
  return 'Delegated task context';
}

/**
 * Builds a stable team key from the ownership fields available on each run.
 */
function buildRunTeamKey(run: RunSummary): string {
  const teamId = run.requestedBy?.teamId?.trim();

  if (teamId) {
    // Prefer the backend team identity to keep run lobbies isolated by signed-in team.
    return teamId;
  }

  const ownerKey = run.owner.trim();

  if (ownerKey) {
    // Prefer owner because it maps most closely to the Discord-style team/server metaphor.
    return ownerKey;
  }

  // Fall back to repo identity so unowned runs still land in a visible team.
  return run.repo.trim() || 'Unassigned team';
}

/**
 * Builds a compact initials label for a team server icon.
 */
function buildTeamInitials(label: string): string {
  const words = label
    .split(/[\s/_-]+/)
    .map((word) => word.trim())
    .filter((word) => word.length > 0);

  if (words.length === 0) {
    // Keep the avatar populated even when the source label is empty.
    return 'AI';
  }

  // Use up to two leading characters so the server rail stays compact.
  return words.slice(0, 2).map((word) => word[0]?.toUpperCase() ?? '').join('');
}

/**
 * Maps a run status to the channel tone used by the Discord-style run list.
 */
function getRunChannelTone(run: RunSummary): RunChannelTone {
  if (run.status === 'Blocked' || run.status === 'Retry') {
    // Treat retries as blocked because they need reviewer or agent follow-up.
    return 'blocked';
  }

  if (run.status === 'Merged' || run.pullRequest?.merged) {
    // Treat backend status and live PR metadata as terminal merged signals.
    return 'merged';
  }

  // Everything else is still active from an operator perspective.
  return 'active';
}

/**
 * Builds the hover text that explains the review effort behind a run channel.
 */
function buildReviewEffortLabel(run: RunSummary, reviewEffort?: ReviewEffortEstimate): string {
  if (reviewEffort) {
    const confidenceCopy = reviewEffort.confidence === null
      ? ''
      : ` · ${Math.round(reviewEffort.confidence * 100)}% confidence`;

    // Show the OpenAI estimate as the primary review-effort signal for lobby runs.
    return `Review effort: ${reviewEffort.label} · ${reviewEffort.effortMinutes} min OpenAI guess${confidenceCopy} · ${reviewEffort.rationale}`;
  }

  if (run.pullRequest?.body?.trim()) {
    // Surface the pending AI state when the PR summary is available but the estimate has not arrived.
    return 'Review effort: estimating from PR summary with OpenAI';
  }

  // Fall back to an explicit missing-summary state so the lobby does not imply runtime-based scoring.
  return `Review effort: awaiting PR summary · ${run.status}`;
}

/**
 * Reports whether the run lobby should show open pull-request content.
 */
function shouldShowRunLobbyPullRequest(run: RunSummary): boolean {
  const pullRequest = run.pullRequest;

  if (run.status !== 'Review' || !pullRequest) {
    // Keep the lobby preview focused on review-ready runs with attached PR metadata.
    return false;
  }

  const normalizedState = (pullRequest.state ?? pullRequest.status ?? '').toLowerCase();

  // Show only open review handoffs so approved, merged, closed, or draft PRs do not linger.
  return !pullRequest.merged && (normalizedState === 'open' || normalizedState === 'ready_for_review');
}

/**
 * Groups runs into Discord-style teams and counts channel state by team.
 */
function buildRunTeamGroups(runs: RunSummary[]): RunTeamGroup[] {
  const groupsByKey = new Map<string, RunTeamGroup>();

  // Preserve the backend run order while collecting team buckets.
  for (const run of runs) {
    const key = buildRunTeamKey(run);
    const existingGroup = groupsByKey.get(key);
    const group = existingGroup ?? {
      key,
      label: key,
      initials: buildTeamInitials(key),
      runs: [],
      activeCount: 0,
      blockedCount: 0,
      mergedCount: 0,
    };
    const tone = getRunChannelTone(run);

    // Keep every run inside the team so the channel list mirrors the dashboard feed.
    group.runs.push(run);

    if (tone === 'blocked') {
      // Count blocked channels separately for the team server hover.
      group.blockedCount += 1;
    } else if (tone === 'merged') {
      // Count merged channels separately so terminal runs stay visually distinct.
      group.mergedCount += 1;
    } else {
      // Count the remaining channels as active work.
      group.activeCount += 1;
    }

    // Write the group back when this is the first run for the team.
    groupsByKey.set(key, group);
  }

  // Return groups in the insertion order established by the run feed.
  return Array.from(groupsByKey.values());
}

/**
 * Builds the team server hover summary shown in the Discord rail.
 */
function buildTeamHoverLabel(group: RunTeamGroup): string {
  const runCount = group.runs.length;

  // Summarize the channel state mix so the server hover carries operational signal.
  return `${group.label}: ${runCount} run${runCount === 1 ? '' : 's'} · ${group.activeCount} active · ${group.blockedCount} blocked · ${group.mergedCount} merged`;
}

/**
 * Renders open pull-request content inside the run lobby preview card.
 */
function RunLobbyPullRequestPreview(props: { run: RunSummary }) {
  const pullRequest = props.run.pullRequest;

  if (!shouldShowRunLobbyPullRequest(props.run) || !pullRequest) {
    // Render nothing unless the selected run is waiting for review on an open PR.
    return null;
  }

  const pullRequestTitle = (pullRequest.title ?? '').trim() || `PR #${pullRequest.number}`;
  const pullRequestBody = (pullRequest.body ?? '').trim() || 'No pull request description was provided.';

  // Return a compact PR content card that sits directly above the run-room action.
  return (
    <section className="run-lobby-pr-content" aria-label="Open pull request content">
      <div className="run-lobby-pr-header">
        <p className="eyebrow">Open PR content</p>
        {pullRequest.url ? (
          <a className="external-link" href={pullRequest.url} rel="noreferrer" target="_blank">
            #{pullRequest.number}
          </a>
        ) : null}
      </div>
      <strong>{pullRequestTitle}</strong>
      <p className="run-lobby-pr-body">{pullRequestBody}</p>
    </section>
  );
}

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

  // Route the user into the public landing page, auth screen, or signed-in product shell.
  return (
    <Routes>
      <Route
        element={currentUser ? <Navigate replace to="/dashboard" /> : <LandingPage />}
        path="/"
      />
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
          <Route element={<TaskDetailPage />} path="/tasks/:runId" />
          <Route
            element={
              <RoleGate allowedRoles={reviewerRoles} currentUser={currentUser} title="Settings">
                <IntegrationsPage currentUser={currentUser} />
              </RoleGate>
            }
            path="/integrations"
          />
          <Route
            element={
              <RoleGate allowedRoles={reviewerRoles} currentUser={currentUser} title="Settings">
                <IntegrationsPage currentUser={currentUser} />
              </RoleGate>
            }
            path="/settings"
          />
          <Route element={<Navigate replace to="/dashboard" />} path="*" />
        </Route>
      ) : (
        <Route element={<Navigate replace to="/" />} path="*" />
      )}
    </Routes>
  );
}

/**
 * Renders the public product landing page before visitors reach sign-in.
 */
function LandingPage() {
  const [selectedWorkflowScreenshotSrc, setSelectedWorkflowScreenshotSrc] = useState<string | null>(null);
  const highlights = [
    'Route intake from GitHub, Linear, Jira, and docs into one review lane.',
    'Watch agent runs move through evidence, blockers, approval, and merge.',
    'Give reviewers a Discord-inspired workspace for every automation handoff.',
  ];
  const workflowScreenshots = [
    {
      alt: 'Run Channels lobby showing team servers, run metrics, and suggested next actions.',
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
      alt: 'Run lobby showing an active agent run for a selected team server.',
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
          <span className="discord-home-mark landing-brand-mark" aria-hidden="true">
            AI
          </span>
          <span>
            <span className="eyebrow">AI Control Plane</span>
            <strong>Engineering Mission Control</strong>
          </span>
        </Link>
        <Link className="ghost-button" to="/sign-in">
          Sign in
        </Link>
      </nav>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="eyebrow">Agentic engineering operations</p>
          <h1 id="landing-title">Coordinate AI work from intake to approval.</h1>
          <p className="muted-copy">
            AI Control Plane gives product engineering teams one place to request work, monitor agent execution, inspect evidence, and approve the next step.
          </p>
          <div className="landing-actions">
            <Link className="primary-button" to="/sign-in">
              Enter mission control
            </Link>
            <a className="ghost-button" href="#landing-workflow">
              See how it works
            </a>
          </div>
        </div>

        <div className="landing-preview-card" aria-label="Run room preview">
          <div className="landing-preview-header">
            <span className="status-badge status-running">Live run</span>
            <span className="subtle-copy">platform / checkout-flow</span>
          </div>
          <div className="landing-preview-room">
            <p className="eyebrow">Run room</p>
            <h2>Ship payment retry copy</h2>
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
          <h2 id="landing-workflow-title">From request to reviewed pull request in one control plane.</h2>
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

  // Keep the shell visible so the app feels like a real Discord-inspired team workspace.
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <aside aria-label="Workspace navigation" className="sidebar">
        <div className="brand-card discord-brand-card">
          <div className="discord-home-mark" aria-hidden="true">
            AI
          </div>
          <p className="eyebrow">AI Control Plane</p>
          <h1>Engineering</h1>
          <p className="muted-copy">
            Teams are servers, runs are channels, and every run opens into a focused review room.
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
        <h1>{googleSsoEnabled ? 'Sign in with Google to enter mission control.' : 'Sign in to enter mission control.'}</h1>
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

/**
 * Shows the live mission control dashboard.
 */
function DashboardPage() {
  const query = useApiQuery(fetchDashboard, []);
  const [suggestedActions, setSuggestedActions] = useState<string[]>([]);
  const [suggestionsError, setSuggestionsError] = useState<string>('');
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState<boolean>(false);
  const [reviewEffortsByRunId, setReviewEffortsByRunId] = useState<Record<string, ReviewEffortEstimate>>({});
  const [reviewEffortsError, setReviewEffortsError] = useState<string>('');
  const [isReviewEffortsLoading, setIsReviewEffortsLoading] = useState<boolean>(false);
  const [selectedTeamKey, setSelectedTeamKey] = useState<string>('');
  const [missionSearch, setMissionSearch] = useState<string>('');
  const [missionStatus, setMissionStatus] = useState<'' | RunStatus>('');
  const [missionRepo, setMissionRepo] = useState<string>('');
  const [missionOwnerToken, setMissionOwnerToken] = useState<string>('');
  const [missionRisk, setMissionRisk] = useState<'' | RiskLevel>('');
  const missionFilterFormId = useId();
  const lobbyRuns = query.data
    ? query.data.runs
    : [];
  const teamGroups = buildRunTeamGroups(lobbyRuns);
  const selectedTeam = teamGroups.find((group) => group.key === selectedTeamKey) ?? teamGroups[0] ?? null;
  const selectedTeamRuns = selectedTeam?.runs ?? [];

  const missionControlFilterCriteria = useMemo<MissionControlFilterCriteria>(
    () => ({
      searchText: missionSearch,
      status: missionStatus,
      repo: missionRepo,
      ownerToken: missionOwnerToken,
      risk: missionRisk,
    }),
    [missionSearch, missionStatus, missionRepo, missionOwnerToken, missionRisk],
  );

  const filteredTeamRuns = useMemo(
    () => filterMissionControlRuns(selectedTeamRuns, missionControlFilterCriteria),
    [missionControlFilterCriteria, selectedTeamRuns],
  );

  // Build a stable, comma-joined key so the effect reruns only when the filtered run IDs change.
  const visibleRunIdsKey = filteredTeamRuns.map((run) => run.id).join(',');

  useEffect(() => {
    if (!visibleRunIdsKey) {
      // Skip OpenAI calls when there are no visible issue-tracker-linked runs.
      setSuggestedActions([]);
      setSuggestionsError('');
      setIsSuggestionsLoading(false);
      setReviewEffortsByRunId({});
      setReviewEffortsError('');
      setIsReviewEffortsLoading(false);
      return;
    }

    let isActive = true;
    const runIds = visibleRunIdsKey.split(',').filter((id) => id.length > 0);

    setIsSuggestionsLoading(true);
    setSuggestionsError('');
    setIsReviewEffortsLoading(true);
    setReviewEffortsError('');

    /**
     * Requests OpenAI-generated suggestions for the currently visible runs.
     */
    async function loadSuggestions(): Promise<void> {
      try {
        // Send the visible run IDs so the backend can prompt OpenAI with matching context.
        const response = await fetchDashboardSuggestedActions({ runIds });

        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        setSuggestedActions(response.suggestedActions);
      } catch (error) {
        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const readableMessage = error instanceof Error ? error.message : 'Suggested actions were unavailable.';
        setSuggestedActions([]);
        setSuggestionsError(readableMessage);
      } finally {
        if (isActive) {
          // Always clear the loading flag once the request settles.
          setIsSuggestionsLoading(false);
        }
      }
    }

    /**
     * Requests OpenAI-generated review-effort guesses for the selected lobby runs.
     */
    async function loadReviewEfforts(): Promise<void> {
      try {
        // Send the selected lobby run IDs so OpenAI can estimate effort from their PR summaries.
        const response = await fetchDashboardReviewEfforts({ runIds });

        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const nextReviewEffortsByRunId: Record<string, ReviewEffortEstimate> = {};

        // Index the estimates by run ID for cheap lookups during lobby rendering.
        for (const reviewEffort of response.reviewEfforts) {
          nextReviewEffortsByRunId[reviewEffort.runId] = reviewEffort;
        }

        setReviewEffortsByRunId(nextReviewEffortsByRunId);
      } catch (error) {
        if (!isActive) {
          // Skip state updates when the effect has already been cleaned up.
          return;
        }

        const readableMessage = error instanceof Error ? error.message : 'Review-effort estimates were unavailable.';
        setReviewEffortsByRunId({});
        setReviewEffortsError(readableMessage);
      } finally {
        if (isActive) {
          // Always clear the loading flag once the request settles.
          setIsReviewEffortsLoading(false);
        }
      }
    }

    void loadSuggestions();
    void loadReviewEfforts();

    return () => {
      // Mark the effect as inactive so stale responses do not overwrite fresh state.
      isActive = false;
    };
  }, [visibleRunIdsKey]);

  if (query.isLoading) {
    // Render a lightweight loading state while dashboard data is fetched.
    return <LoadingState message="Loading mission control data..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the dashboard request fails.
    return <ErrorState message={query.error ?? 'Dashboard data was unavailable.'} />;
  }

  /**
   * Switches the active Discord-style server in the dashboard run browser.
   */
  function handleTeamSelect(event: MouseEvent<HTMLButtonElement>): void {
    const teamKey = event.currentTarget.dataset.teamKey ?? '';

    // Store only the selected team key because the groups are derived fresh from query data.
    setSelectedTeamKey(teamKey);
  }

  /**
   * Updates the mission control keyword filter as the operator types in the search field.
   */
  function handleMissionSearchChange(event: ChangeEvent<HTMLInputElement>): void {
    // Keep the controlled search field aligned with the latest input value.
    setMissionSearch(event.currentTarget.value);
  }

  /**
   * Updates the mission control status filter when the operator changes the dropdown.
   */
  function handleMissionStatusFilterChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextValue = event.currentTarget.value as '' | RunStatus;

    // Persist the selected status token, including the empty all-statuses option.
    setMissionStatus(nextValue);
  }

  /**
   * Updates the mission control repository filter when the operator changes the dropdown.
   */
  function handleMissionRepoFilterChange(event: ChangeEvent<HTMLSelectElement>): void {
    // Persist the selected repository name, including the empty all-repositories option.
    setMissionRepo(event.currentTarget.value);
  }

  /**
   * Updates the mission control owner filter when the operator changes the dropdown.
   */
  function handleMissionOwnerFilterChange(event: ChangeEvent<HTMLSelectElement>): void {
    // Persist the owner token, including the dedicated unassigned sentinel when chosen.
    setMissionOwnerToken(event.currentTarget.value);
  }

  /**
   * Updates the mission control risk filter when the operator changes the dropdown.
   */
  function handleMissionRiskFilterChange(event: ChangeEvent<HTMLSelectElement>): void {
    const nextValue = event.currentTarget.value as '' | RiskLevel;

    // Persist the selected risk token, including the empty all-risk-levels option.
    setMissionRisk(nextValue);
  }

  /**
   * Clears every mission control filter so the full team lobby is visible again.
   */
  function handleClearMissionFilters(): void {
    // Reset the full filter stack to restore the default unfiltered lobby view.
    setMissionSearch('');
    setMissionStatus('');
    setMissionRepo('');
    setMissionOwnerToken('');
    setMissionRisk('');
  }

  const derivedMetrics = deriveDashboardMetrics(filteredTeamRuns, reviewEffortsByRunId);
  const selectedPreviewRun = filteredTeamRuns[0] ?? null;
  const metricCards: ReactNode[] = [];
  const teamServerButtons: ReactNode[] = [];
  const runChannels: ReactNode[] = [];
  const suggestedItems: ReactNode[] = [];

  // Build cards explicitly so the UI stays easy to reshape later.
  for (const metric of derivedMetrics) {
    metricCards.push(<MetricCard hint={metric.hint} key={metric.label} label={metric.label} value={metric.value} />);
  }

  // Build the Discord server rail from owner-backed team groups.
  for (const group of teamGroups) {
    const isActiveTeam = selectedTeam?.key === group.key;

    teamServerButtons.push(
      <button
        aria-label={buildTeamHoverLabel(group)}
        className={`server-button${isActiveTeam ? ' server-button-active' : ''}`}
        data-team-key={group.key}
        key={group.key}
        onClick={handleTeamSelect}
        title={buildTeamHoverLabel(group)}
        type="button"
      >
        <span>{group.initials}</span>
      </button>,
    );
  }

  // Build the run channel list for the selected team after mission control filters apply.
  for (const run of filteredTeamRuns) {
    const channelTone = getRunChannelTone(run);
    const reviewEffort = buildReviewEffortLabel(run, reviewEffortsByRunId[run.id]);

    runChannels.push(
      <Link
        aria-label={`${run.ticket}: ${run.title}. ${reviewEffort}`}
        className={`run-channel run-channel-${channelTone}`}
        key={run.id}
        title={reviewEffort}
        to={`/tasks/${run.id}`}
      >
        <span className="run-channel-hash" aria-hidden="true">#</span>
        <span className="run-channel-copy">
          <span className="run-channel-title">{run.ticket} {run.title}</span>
          <span className="run-channel-meta">{run.repo} · {run.runtime}</span>
        </span>
        <span className="run-channel-status">{run.status}</span>
        <RunTraceabilityGraphPanelBody
          ariaLabel={`Run traceability graph for ${run.ticket}`}
          run={run}
          showArtifactLinks={false}
          variant="compact"
        />
      </Link>,
    );
  }

  // Render the OpenAI-generated suggested next actions in the right rail.
  for (const action of suggestedActions) {
    suggestedItems.push(
      <p className="rail-item" key={action}>
        {action}
      </p>,
    );
  }

  // Choose the suggestions rail body so loading, error, and empty states all read clearly.
  let suggestionsBody: ReactNode;

  if (lobbyRuns.length === 0) {
    // Tell the operator that AI suggestions need visible runs first.
    suggestionsBody = <p className="muted-copy">No run channels are available to generate suggestions from.</p>;
  } else if (isSuggestionsLoading) {
    // Surface the OpenAI call in flight so the panel does not look empty while we wait.
    suggestionsBody = <p className="muted-copy">Generating suggestions from the runs above...</p>;
  } else if (suggestionsError) {
    // Surface a readable failure state without replacing the rest of the dashboard.
    suggestionsBody = <p className="muted-copy">Suggestions were unavailable: {suggestionsError}</p>;
  } else if (suggestedItems.length === 0) {
    // Stay resilient to empty OpenAI responses so the panel still renders cleanly.
    suggestionsBody = <p className="muted-copy">No suggested next actions are available right now.</p>;
  } else {
    // Render the list of OpenAI-generated suggestions when everything succeeded.
    suggestionsBody = (
      <div>
        <div className="rail-list">{suggestedItems}</div>
      </div>
    );
  }

  const reviewEffortStatusCopy = reviewEffortsError
    ? `OpenAI review effort unavailable: ${reviewEffortsError}`
    : isReviewEffortsLoading
      ? 'Estimating review effort from PR summaries with OpenAI...'
      : 'Hover a run channel to see OpenAI-estimated review effort.';

  const missionRepoOptions = buildMissionControlRepoOptions(selectedTeamRuns);
  const missionOwnerOptions = buildMissionControlOwnerOptions(selectedTeamRuns);
  const mergedBlockedReasons = mergeDashboardBlockedReasonLists(query.data.blockedReasons, filteredTeamRuns);
  const hasActiveMissionFilters = Boolean(
    missionSearch.trim() || missionStatus || missionRepo.trim() || missionOwnerToken.trim() || missionRisk,
  );
  const missionStatusFilterOptions: ReactNode[] = [
    <option key="mission-status-all" value="">All statuses</option>,
  ];

  for (const status of missionControlDashboardStatuses) {
    missionStatusFilterOptions.push(
      <option key={`mission-status-${status}`} value={status}>
        {status}
      </option>,
    );
  }

  const missionRepoFilterOptions: ReactNode[] = [
    <option key="mission-repo-all" value="">All repositories</option>,
  ];

  for (const repo of missionRepoOptions) {
    missionRepoFilterOptions.push(
      <option key={`mission-repo-${repo}`} value={repo}>
        {repo}
      </option>,
    );
  }

  const missionOwnerFilterOptions: ReactNode[] = [
    <option key="mission-owner-all" value="">All owners</option>,
  ];

  for (const option of missionOwnerOptions) {
    missionOwnerFilterOptions.push(
      <option key={`mission-owner-${option.value}`} value={option.value}>
        {option.label}
      </option>,
    );
  }

  const missionRiskFilterOptions: ReactNode[] = [
    <option key="mission-risk-all" value="">All risk levels</option>,
  ];

  for (const risk of missionControlDashboardRisks) {
    missionRiskFilterOptions.push(
      <option key={`mission-risk-${risk}`} value={risk}>
        {risk}
      </option>,
    );
  }

  const blockedReasonListItems: ReactNode[] = [];

  for (const reason of mergedBlockedReasons) {
    blockedReasonListItems.push(
      <li className="rail-item" key={reason}>
        {reason}
      </li>,
    );
  }


  const channelListEmptyCopy = selectedTeamRuns.length > 0 && filteredTeamRuns.length === 0
    ? 'No runs match the current mission control filters. Clear or adjust filters to see channels again.'
    : 'No run channels are available for this team.';

  // Surface the operational view as a Discord-style server, channel, and run room.
  return (
    <div className="page-grid">
      <section className="hero-panel discord-hero-panel">
        <div>
          <p className="eyebrow">Live operations</p>
          <h3>Pick a team server, use mission control filters to narrow channels, then open the run room for evidence and review.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{teamGroups.length} teams</span>
          <span className="pill">{query.data.integrationStatuses.length} provider categories</span>
          {hasActiveMissionFilters ? <span className="pill">Filters active</span> : null}
        </div>
      </section>

      <section aria-labelledby={`${missionFilterFormId}-legend`} className="mission-control-filter-bar">
        <div className="mission-control-filter-bar-header">
          <p className="eyebrow" id={`${missionFilterFormId}-legend`}>
            Mission control filters
          </p>
          <div className="mission-control-filter-bar-actions">
            <Link className="primary-button link-button" to="/intake">
              Delegate to agent
            </Link>
            {hasActiveMissionFilters ? (
              <button className="ghost-button" onClick={handleClearMissionFilters} type="button">
                Clear filters
              </button>
            ) : null}
          </div>
        </div>
        <form className="mission-control-filter-toolbar" role="search" onSubmit={(event) => { event.preventDefault(); }}>
          <div className="field-group field-group-wide mission-control-search-field">
            <label htmlFor={`${missionFilterFormId}-search`}>Search tasks</label>
            <input
              autoComplete="off"
              id={`${missionFilterFormId}-search`}
              onChange={handleMissionSearchChange}
              placeholder="Ticket, title, repo, agent, or owner"
              type="search"
              value={missionSearch}
            />
          </div>
          <div className="field-group">
            <label htmlFor={`${missionFilterFormId}-status`}>Status</label>
            <select id={`${missionFilterFormId}-status`} onChange={handleMissionStatusFilterChange} value={missionStatus}>
              {missionStatusFilterOptions}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor={`${missionFilterFormId}-repo`}>Repository</label>
            <select id={`${missionFilterFormId}-repo`} onChange={handleMissionRepoFilterChange} value={missionRepo}>
              {missionRepoFilterOptions}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor={`${missionFilterFormId}-owner`}>Owner</label>
            <select id={`${missionFilterFormId}-owner`} onChange={handleMissionOwnerFilterChange} value={missionOwnerToken}>
              {missionOwnerFilterOptions}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor={`${missionFilterFormId}-risk`}>Risk</label>
            <select id={`${missionFilterFormId}-risk`} onChange={handleMissionRiskFilterChange} value={missionRisk}>
              {missionRiskFilterOptions}
            </select>
          </div>
        </form>
      </section>

      <section className="metric-grid">{metricCards}</section>

      <section className="content-grid discord-support-grid">
        <div className="rail-stack">
          <Panel body={suggestionsBody} title="Suggested next actions" />
        </div>
      </section>

      <section className="discord-workspace" aria-label="Team run workspace">
        <div className="server-rail" aria-label="Team servers">
          {teamServerButtons.length > 0 ? teamServerButtons : <span className="server-empty-state">AI</span>}
        </div>

        <div className="channel-panel" aria-label="Run channels">
          <div className="channel-panel-header">
            <p className="eyebrow">Team server</p>
            <h3>{selectedTeam?.label ?? 'No team selected'}</h3>
            <p className="subtle-copy" role="status">
              Showing {filteredTeamRuns.length} of {selectedTeamRuns.length} run channels
              {hasActiveMissionFilters ? ' with filters applied' : ''}.
            </p>
            <p className="subtle-copy">{reviewEffortStatusCopy}</p>
          </div>
          <div className="run-channel-list">
            {runChannels.length > 0 ? runChannels : <p className="muted-copy">{channelListEmptyCopy}</p>}
          </div>
        </div>

        <div className="run-room-preview" aria-label="Selected run preview">
          {selectedPreviewRun ? (
            <div className="run-room-card">
              <div className="run-room-card-header">
                <div>
                  <p className="eyebrow">#{selectedPreviewRun.ticket}</p>
                  <h3>{selectedPreviewRun.title}</h3>
                  <p className="muted-copy">{selectedPreviewRun.summary}</p>
                </div>
                <StatusBadge risk={selectedPreviewRun.risk} status={selectedPreviewRun.status} />
              </div>

              <div className="run-room-facts">
                <span>{buildIssueTrackerRunLabel(selectedPreviewRun)}</span>
                <span>{selectedPreviewRun.repo}</span>
                <span>{selectedPreviewRun.agent}</span>
                <span>{selectedPreviewRun.runtime}</span>
              </div>

              <p className="subtle-copy">{buildReviewEffortLabel(selectedPreviewRun, reviewEffortsByRunId[selectedPreviewRun.id])}</p>

              <RunLobbyPullRequestPreview run={selectedPreviewRun} />

              <Link className="primary-button link-button" to={`/tasks/${selectedPreviewRun.id}`}>
                Open run room
              </Link>
            </div>
          ) : selectedTeamRuns.length > 0 ? (
            <div className="run-room-card">
              <p className="eyebrow">No match</p>
              <h3>No runs match the current mission control filters.</h3>
              <p className="muted-copy">Clear filters or pick another team server to restore the preview card.</p>
              {hasActiveMissionFilters ? (
                <button className="primary-button" onClick={handleClearMissionFilters} type="button">
                  Clear filters
                </button>
              ) : null}
            </div>
          ) : (
            <div className="run-room-card">
              <p className="eyebrow">No channels</p>
              <h3>No run channels are available yet.</h3>
              <p className="muted-copy">New delegated runs will appear here as channels.</p>
            </div>
          )}
        </div>
      </section>
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
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [enrichingField, setEnrichingField] = useState<IntakeEnrichField | ''>('');
  const [enrichError, setEnrichError] = useState<string>('');
  const [enrichNotice, setEnrichNotice] = useState<string>('');
  const [isIdentifyingRepo, setIsIdentifyingRepo] = useState<boolean>(false);
  const [identifyError, setIdentifyError] = useState<string>('');
  const [identifyNotice, setIdentifyNotice] = useState<string>('');
  const [uploadedDocuments, setUploadedDocuments] = useState<UploadedDocumentRecord[]>([]);
  const [uploadError, setUploadError] = useState<string>('');

  /**
   * Loads the OpenAI-scored issue scoping groups for the visible intake issues.
   */
  async function loadIssueScoping(): Promise<IntakeIssueScopingResponse | null> {
    if (!query.data || query.data.issues.length === 0) {
      // Skip scoping requests until the intake issue catalog has loaded.
      return null;
    }

    const issueIds: string[] = [];

    // Preserve the rendered issue order when asking the backend to classify the list.
    for (const issue of query.data.issues) {
      issueIds.push(issue.id);
    }

    // Ask the OpenAI-backed backend route to separate the issues into the two scope buckets.
    return classifyIntakeIssuesByScope({ issueIds });
  }

  const issueScopingQuery = useApiQuery(loadIssueScoping, [query.data]);

  useEffect(() => {
    if (!query.data) {
      // Skip form bootstrapping until the intake payload is available.
      return;
    }

    if (!selectedRepoName && query.data.repositories.length > 0) {
      // Default the repo selection to the first available repository option.
      setSelectedRepoName(query.data.repositories[0].name);
    }
  }, [query.data, selectedRepoName]);

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

    // Refresh the intake title so it always matches the currently selected issue.
    setTitle(issue.title);

    // Refresh the implementation prompt from the selected issue details.
    setPrompt(issue.description || `Implement ${issue.ticket}: ${issue.title}`);

    // Refresh the acceptance criteria so it stays aligned with the selected issue.
    setAcceptanceCriteria(`Deliver ${issue.ticket} with clear review evidence and preserve issue traceability from ${issue.status}.`);
  }, [query.data, selectedIssueId]);

  if (query.isLoading) {
    // Render a lightweight loading state while intake options are fetched.
    return <LoadingState message="Loading integrated task intake..." />;
  }

  if (query.error || !query.data) {
    // Render a recoverable error panel if the intake request fails.
    return <ErrorState message={query.error ?? 'Task intake options were unavailable.'} />;
  }

  const unscopedIssueCards: ReactNode[] = [];
  const wellScopedIssueOptions: ReactNode[] = [];
  const poorlyScopedIssueOptions: ReactNode[] = [];
  const wellScopedIssueCards: ReactNode[] = [];
  const poorlyScopedIssueCards: ReactNode[] = [];
  const repositoryOptions: ReactNode[] = [];
  const integrationCards: ReactNode[] = [];
  const issueScopeById: Map<string, 'well_scoped' | 'poorly_scoped'> = new Map();

  if (issueScopingQuery.data) {
    // Index the OpenAI scoping result so each issue can be placed into the matching optgroup.
    for (const issueId of issueScopingQuery.data.wellScopedIssueIds) {
      issueScopeById.set(issueId, 'well_scoped');
    }

    // Fill in the poorly scoped group after the well-scoped assignments are applied.
    for (const issueId of issueScopingQuery.data.poorlyScopedIssueIds) {
      issueScopeById.set(issueId, 'poorly_scoped');
    }
  }

  // Build the issue selector controls from the integrated issue catalog.
  for (const issue of query.data.issues) {
    const issueOption = (
      <option key={issue.id} value={issue.id}>
        {issue.ticket} - {issue.title}
      </option>
    );
    const scopedGroup = issueScopeById.get(issue.id);
    const issueCard = (
      <label className={`intake-card-option${selectedIssueId === issue.id ? ' intake-card-option-selected' : ''}`} key={issue.id}>
        <input
          checked={selectedIssueId === issue.id}
          name="issue"
          onChange={() => { setSelectedIssueId(issue.id); }}
          type="radio"
          value={issue.id}
        />
        <span className="intake-card-option-body">
          <strong>{issue.ticket}</strong>
          <span>{issue.title}</span>
          <small>{issue.priority} priority · {issue.status}</small>
        </span>
      </label>
    );

    if (scopedGroup === 'well_scoped') {
      // Place highly executable issues into the well-scoped optgroup.
      wellScopedIssueOptions.push(issueOption);
      wellScopedIssueCards.push(issueCard);
    } else if (scopedGroup === 'poorly_scoped') {
      // Place ambiguous or discovery-heavy issues into the poorly-scoped optgroup.
      poorlyScopedIssueOptions.push(issueOption);
      poorlyScopedIssueCards.push(issueCard);
    } else {
      // Fall back to an unscoped card list until OpenAI scoping data is available.
      unscopedIssueCards.push(issueCard);
    }
  }

  // Keep the repository identification action reserved for well-scoped issues only.
  const isSelectedIssueWellScoped = selectedIssueId !== ''
    && issueScopeById.get(selectedIssueId) === 'well_scoped';
  const selectedIssue = selectedIssueId ? findIssueById(query.data.issues, selectedIssueId) : null;
  const selectedRepository = query.data.repositories.find((repository) => repository.name === selectedRepoName) ?? null;
  const selectedRepositoryDocuments = getDocumentsForRepository(query.data.documents, selectedRepoName);
  const executionModeCards: ReactNode[] = [];

  // Build execution mode cards so this step can stand on its own visually.
  for (const mode of [
    { id: 'implement', title: 'Implement', detail: 'Ask the agent to change code and prepare review evidence.' },
    { id: 'research', title: 'Research', detail: 'Investigate the issue and return a grounded implementation plan.' },
    { id: 'review', title: 'Review', detail: 'Evaluate existing changes, risks, and missing tests.' },
    { id: 'test', title: 'Test', detail: 'Focus the run on validation, reproduction, and regression coverage.' },
  ]) {
    executionModeCards.push(
      <label className={`intake-card-option${executionMode === mode.id ? ' intake-card-option-selected' : ''}`} key={mode.id}>
        <input
          checked={executionMode === mode.id}
          name="executionMode"
          onChange={() => { setExecutionMode(mode.id); }}
          type="radio"
          value={mode.id}
        />
        <span className="intake-card-option-body">
          <strong>{mode.title}</strong>
          <span>{mode.detail}</span>
        </span>
      </label>,
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

  // Render the provider integration cards alongside the task form.
  for (const status of query.data.integrationStatuses) {
    integrationCards.push(<IntegrationStatusCard key={status.id} status={status} />);
  }

  /**
   * Submits the intake form and creates a task that auto-starts its run.
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
      documentIds: uploadedDocuments.length > 0 ? [] : selectedRepositoryDocuments.map((document) => document.id),
      uploadedDocuments,
      executionMode,
    };

    try {
      // Create the task and let the backend immediately start its run.
      const createdRun = await createTask(payload);

      // Navigate directly into the started run detail view.
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
      uploadedDocuments,
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
          ? `Refined using ${buildEnrichmentSourceLabel(uploadedDocuments)} context.`
          : `Refined without ${buildEnrichmentSourceLabel(uploadedDocuments)} available to ground the response.`,
      );
    } catch (caughtError) {
      // Surface enrichment failures so the user can retry or adjust configuration.
      setEnrichError(caughtError instanceof Error ? caughtError.message : 'Unable to enrich this field.');
    } finally {
      // Mark the inline enrichment request as complete.
      setEnrichingField('');
    }
  }

  /**
   * Calls the backend OpenAI route to pick the repo that best fits the selected issue
   * and then updates the repository dropdown with the returned match.
   */
  async function handleIdentifyRepository(): Promise<void> {
    // Reset the inline identification status before starting a new request.
    setIdentifyError('');
    setIdentifyNotice('');

    if (!selectedIssueId) {
      // Require a selected issue so OpenAI has something concrete to route against.
      setIdentifyError('Select an issue before identifying the matching repository.');
      return;
    }

    if (!isSelectedIssueWellScoped) {
      // Limit repository identification to issues the scoping step marked as executable.
      setIdentifyError('Select a Well Scoped issue before identifying the matching repository.');
      return;
    }

    setIsIdentifyingRepo(true);

    try {
      // Ask the backend to select the repository that best fits the selected issue.
      const identificationResult = await identifyRepositoryForIssue({ issueId: selectedIssueId });

      // Update the repository dropdown to reflect the AI-suggested match.
      setSelectedRepoName(identificationResult.repoName);

      // Build a human-readable notice that summarizes the repository match for the UI.
      const confidenceSuffix =
        typeof identificationResult.confidence === 'number'
          ? ` (confidence ${(identificationResult.confidence * 100).toFixed(0)}%)`
          : '';
      const reasoningSuffix = identificationResult.reasoning ? ` ${identificationResult.reasoning}` : '';
      const docsSuffix = identificationResult.docsConsidered
        ? ` Grounded in repo docs.`
        : ` No repo docs were available for grounding.`;

      setIdentifyNotice(
        `Linked to ${identificationResult.repoFullName || identificationResult.repoName}${confidenceSuffix}.${reasoningSuffix}${docsSuffix}`,
      );
    } catch (caughtError) {
      // Surface identification failures so the user can retry or adjust configuration.
      setIdentifyError(
        caughtError instanceof Error ? caughtError.message : 'Unable to identify the matching repository.',
      );
    } finally {
      // Mark the inline identification request as complete regardless of outcome.
      setIsIdentifyingRepo(false);
    }
  }

  /**
   * Reads the selected repo documents into local state for enrichment and task creation.
   */
  async function handleUploadedDocumentsChange(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    // Clear any prior upload error before processing the newly selected files.
    setUploadError('');

    const selectedFiles = Array.from(event.target.files ?? []);

    if (selectedFiles.length === 0) {
      // Reset the file input value when the chooser closes without new files.
      event.target.value = '';
      return;
    }

    try {
      // Convert each browser file into the shared uploaded-document payload shape.
      const nextUploadedDocuments = await Promise.all(
        selectedFiles.map((file) => buildUploadedDocumentRecord(file)),
      );

      setUploadedDocuments((currentDocuments) => {
        const mergedDocuments = new Map<string, UploadedDocumentRecord>();

        // Keep existing uploads unless the user re-selected the same file.
        for (const currentDocument of currentDocuments) {
          mergedDocuments.set(currentDocument.id, currentDocument);
        }

        // Overwrite duplicates with the latest uploaded file snapshot.
        for (const nextDocument of nextUploadedDocuments) {
          mergedDocuments.set(nextDocument.id, nextDocument);
        }

        return Array.from(mergedDocuments.values());
      });
    } catch (caughtError) {
      // Surface file-reading failures so the operator knows the upload was ignored.
      setUploadError(caughtError instanceof Error ? caughtError.message : 'Unable to read the selected documents.');
    } finally {
      // Reset the native input so the same file can be selected again after removal.
      event.target.value = '';
    }
  }

  /**
   * Removes a single uploaded repo document from the intake form.
   */
  function handleRemoveUploadedDocument(documentId: string): void {
    // Drop the selected upload so later enrich requests stop grounding on it.
    setUploadedDocuments((currentDocuments) => currentDocuments.filter((document) => document.id !== documentId));
  }

  // Render the integrated task intake experience.
  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Delegate to an AI agent</p>
          <h3>
            Tech leads: hand a scoped ticket to an implementation agent with repository context, acceptance criteria,
            and linked docs — then monitor the run from the lobby and run room.
          </h3>
        </div>
        <div className="hero-pills">
          <span className="pill">{query.data.currentUser.name}</span>
          <span className="pill">{query.data.repositories.length} repos</span>
          <span className="pill">{query.data.issues.length} issues</span>
        </div>
      </section>

      <section className="content-grid intake-grid">
        <aside className="rail-stack intake-summary-rail">
          <Panel
            title="Intake summary"
            body={(
              <div className="mini-list">
                <div className="mini-row">
                  <strong>Issue</strong>
                  <span className="subtle-copy">{selectedIssue ? `${selectedIssue.ticket} · ${selectedIssue.title}` : 'No linked issue'}</span>
                </div>
                <div className="mini-row">
                  <strong>Repository</strong>
                  <span className="subtle-copy">{selectedRepository?.fullName || selectedRepoName || 'Select a repository'}</span>
                </div>
                <div className="mini-row">
                  <strong>Mode</strong>
                  <span className="subtle-copy">{executionMode}</span>
                </div>
                <div className="mini-row">
                  <strong>Documents</strong>
                  <span className="subtle-copy">{uploadedDocuments.length > 0 ? `${uploadedDocuments.length} uploaded` : `${selectedRepositoryDocuments.length} selected repo docs`}</span>
                </div>
              </div>
            )}
          />
        </aside>

        <form className="intake-flow" onSubmit={(event) => { void handleSubmit(event); }}>
          <nav className="intake-step-nav" aria-label="Agent delegation setup pages">
            <a href="#intake-issues">1. Issues</a>
            <a href="#intake-repository">2. Repository</a>
            <a href="#intake-execution">3. Mode</a>
            <a href="#intake-documents">4. Documents</a>
            <a href="#intake-task">5. Task</a>
          </nav>

          <section className="panel intake-step-panel" id="intake-issues">
            <div className="intake-step-header">
              <div>
                <p className="eyebrow">Page 1</p>
                <h3>Separate and select an issue</h3>
              </div>
              <span className="pill">{selectedIssue ? selectedIssue.ticket : 'No issue selected'}</span>
            </div>
            <p className="subtle-copy">
              Pick a well-scoped issue when you want repository identification to run. Selecting an issue still auto-fills the task title, prompt, and acceptance criteria.
            </p>
            {query.data.issues.length > 0 && issueScopingQuery.isLoading && !issueScopingQuery.data && !issueScopingQuery.error ? (
              <p className="muted-copy">Separating issues with OpenAI...</p>
            ) : null}
            {issueScopingQuery.error ? (
              <p className="muted-copy">Issue scoping is unavailable right now, so the full list is shown without categories.</p>
            ) : null}
            <div className="issue-scope-grid">
              <div className="issue-scope-column">
                <div className="issue-scope-heading">
                  <strong>Well scoped</strong>
                  <span>{wellScopedIssueOptions.length}</span>
                </div>
                {issueScopingQuery.data
                  ? (wellScopedIssueCards.length > 0 ? wellScopedIssueCards : <p className="muted-copy">No well-scoped issues found yet.</p>)
                  : (unscopedIssueCards.length > 0 ? unscopedIssueCards : <p className="muted-copy">No issue-tracker issues are available.</p>)}
              </div>
              <div className="issue-scope-column">
                <div className="issue-scope-heading">
                  <strong>Poorly scoped</strong>
                  <span>{poorlyScopedIssueOptions.length}</span>
                </div>
                {issueScopingQuery.data
                  ? (poorlyScopedIssueCards.length > 0 ? poorlyScopedIssueCards : <p className="muted-copy">No poorly scoped issues found.</p>)
                  : <p className="muted-copy">Poorly scoped issues will appear after separation completes.</p>}
              </div>
            </div>
            <label className="intake-card-option intake-card-option-muted">
              <input
                checked={selectedIssueId === ''}
                name="issue"
                onChange={() => { setSelectedIssueId(''); }}
                type="radio"
                value=""
              />
              <span className="intake-card-option-body">
                <strong>No linked issue</strong>
                <span>Create a task without issue tracker traceability.</span>
              </span>
            </label>
          </section>

          <section className="panel intake-step-panel" id="intake-repository">
            <div className="intake-step-header">
              <div>
                <p className="eyebrow">Page 2</p>
                <h3>Identify and select a repository</h3>
              </div>
              <span className="pill">{selectedRepository?.fullName || selectedRepoName || 'No repo selected'}</span>
            </div>
            <div className="intake-two-column">
              <label className="field-group">
                <span>Repository</span>
                <select onChange={(event) => { setSelectedRepoName(event.target.value); }} value={selectedRepoName}>
                  {repositoryOptions}
                </select>
              </label>
              <div className="intake-action-card">
                <strong>AI repository match</strong>
                <p className="subtle-copy">Use the selected well-scoped issue to identify the best matching GitHub repository.</p>
                <button
                  className="ghost-button enrich-button"
                  disabled={isIdentifyingRepo || enrichingField !== '' || isSubmitting || !isSelectedIssueWellScoped}
                  onClick={() => { void handleIdentifyRepository(); }}
                  type="button"
                >
                  {isIdentifyingRepo ? 'Identifying repository...' : 'Identify repository'}
                </button>
              </div>
            </div>
            {identifyError ? <p className="error-copy" role="alert">{identifyError}</p> : null}
            {identifyNotice && !identifyError ? <p className="muted-copy enrich-notice">{identifyNotice}</p> : null}
            {!isSelectedIssueWellScoped && selectedIssueId ? (
              <p className="muted-copy">Repository identification unlocks after selecting an issue from the well-scoped group.</p>
            ) : null}
          </section>

          <section className="panel intake-step-panel" id="intake-execution">
            <div className="intake-step-header">
              <div>
                <p className="eyebrow">Page 3</p>
                <h3>Choose the execution mode</h3>
              </div>
              <span className="pill">{executionMode}</span>
            </div>
            <div className="intake-card-grid">{executionModeCards}</div>
          </section>

          <section className="panel intake-step-panel" id="intake-documents">
            <div className="intake-step-header">
              <div>
                <p className="eyebrow">Page 4</p>
                <h3>Add repo documents</h3>
              </div>
              <span className="pill">{uploadedDocuments.length} uploaded</span>
            </div>
            <div className="intake-two-column">
              <label className="field-group">
                <span>Repo documents</span>
                <input
                  accept=".md,.markdown,.txt,text/markdown,text/plain"
                  multiple
                  onChange={(event) => { void handleUploadedDocumentsChange(event); }}
                  type="file"
                />
              </label>
              <div className="intake-action-card">
                <strong>Available repository docs</strong>
                <p className="subtle-copy">
                  {selectedRepositoryDocuments.length > 0
                    ? `${selectedRepositoryDocuments.length} docs from ${selectedRepository?.fullName || selectedRepoName}'s docs folder will be attached before uploads are added.`
                    : 'No docs folder documents are available for the selected repository yet.'}
                </p>
              </div>
            </div>
            <p className="subtle-copy">
              Add markdown files to the selected repository's top-level docs/ folder to auto-attach them, or upload markdown or text files here for this task.
            </p>
            {uploadError ? <p className="error-copy">{uploadError}</p> : null}
            {uploadedDocuments.length > 0 ? (
              <div className="mini-list">
                {uploadedDocuments.map((document) => (
                  <div className="document-upload-row" key={document.id}>
                    <div className="mini-row">
                      <strong>{document.title}</strong>
                      <span className="subtle-copy">{document.path}</span>
                    </div>
                    <button
                      className="ghost-button document-upload-remove-button"
                      onClick={() => { handleRemoveUploadedDocument(document.id); }}
                      type="button"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ) : selectedRepositoryDocuments.length > 0 ? (
              <div className="mini-list">
                {selectedRepositoryDocuments.map((document) => (
                  <div className="document-upload-row" key={document.id}>
                    <div className="mini-row">
                      <strong>{document.title}</strong>
                      <span className="subtle-copy">{document.path}</span>
                    </div>
                    <span className="pill">Selected repo doc</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted-copy">No uploaded repo documents yet. Repo docs are picked up from the selected repository's top-level docs/ folder, for example docs/guide.md or docs/runbook.md.</p>
            )}
          </section>

          <section className="panel intake-step-panel" id="intake-task">
            <div className="intake-step-header">
              <div>
                <p className="eyebrow">Page 5</p>
                <h3>Review the generated task brief</h3>
              </div>
              <span className="pill">Auto-fill retained</span>
            </div>
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
                  {enrichingField === 'title' ? 'Enriching title...' : `Enrich title with ${buildEnrichmentSourceLabel(uploadedDocuments)}`}
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
                  {enrichingField === 'prompt' ? 'Enriching prompt...' : `Enrich prompt with ${buildEnrichmentSourceLabel(uploadedDocuments)}`}
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
                  {enrichingField === 'acceptanceCriteria' ? 'Enriching acceptance criteria...' : `Enrich acceptance criteria with ${buildEnrichmentSourceLabel(uploadedDocuments)}`}
                </button>
              </div>
            </div>

            {enrichError ? <p className="error-copy">{enrichError}</p> : null}
            {enrichNotice ? <p className="muted-copy enrich-notice">{enrichNotice}</p> : null}
            {submitError ? <p className="error-copy">{submitError}</p> : null}

            <div className="form-actions">
              <button className="primary-button" disabled={isSubmitting || !selectedRepoName || !title || !prompt} type="submit">
                {isSubmitting ? 'Creating task and starting run...' : 'Create task and start run'}
              </button>
            </div>
          </section>
        </form>

        <aside className="rail-stack">
          <Panel title="Provider readiness" body={<div className="integration-grid">{integrationCards}</div>} />
        </aside>
      </section>
    </div>
  );
}

/**
 * Converts a stored execution mode token into a human-readable intake label.
 */
function formatExecutionModeLabel(executionMode: string): string {
  // Normalize the stored token so unknown future modes still render safely.
  const normalizedMode = executionMode.trim().toLowerCase();

  if (normalizedMode === 'implement') {
    // Match the intake card copy for the default engineering implementation path.
    return 'Implement — change code and prepare review evidence';
  }

  if (normalizedMode === 'research') {
    // Match the intake card copy for investigation-heavy work.
    return 'Research — investigate and return a grounded plan';
  }

  if (normalizedMode === 'review') {
    // Match the intake card copy for reviewer-style analysis runs.
    return 'Review — evaluate existing changes, risks, and tests';
  }

  if (normalizedMode === 'test') {
    // Match the intake card copy for validation-focused runs.
    return 'Test — focus on validation, reproduction, and regression coverage';
  }

  // Fall back to the raw token when the backend introduces a new execution mode.
  return executionMode.trim() || 'Implement — change code and prepare review evidence';
}

/**
 * Renders the tech-lead delegation brief: repo context, issue narrative, criteria, and agent instructions.
 */
function TaskAgentDelegationBriefPanelBody(props: { run: RunSummary }) {
  // Read optional repository metadata resolved by the backend integration catalog.
  const repositoryContext = props.run.repositoryContext;
  // Read the linked issue so description and ticket metadata can sit beside criteria.
  const issue = props.run.issue;
  // Read the human-authored acceptance checklist captured during intake.
  const acceptanceCriteria = props.run.acceptanceCriteria?.trim() ?? '';
  // Read the full delegation prompt separate from the short summary line.
  const taskPrompt = props.run.taskPrompt?.trim() ?? '';
  // Read the execution mode label for policy-aligned agent routing context.
  const executionModeLabel = formatExecutionModeLabel(props.run.executionMode ?? 'implement');
  // Prefer the repository URL from integration data before falling back to PR-derived links.
  const repositoryBrowseUrl = repositoryContext?.url?.trim()
    ? repositoryContext.url.trim()
    : resolveRunRepositoryUrl(props.run);
  // Prefer the catalog full name when present so reviewers see owner/repo formatting.
  const repositoryDisplayName = repositoryContext?.fullName?.trim()
    || repositoryContext?.name?.trim()
    || props.run.repo;
  // Read the default branch hint when the backend supplied repository context.
  const defaultBranchLabel = repositoryContext?.defaultBranch?.trim() || '—';
  // Build the attached document list for provenance consistent with integrations.md.
  const documentItems: ReactNode[] = [];

  // Render each attached document as a compact list row when snapshots exist.
  for (const document of props.run.documents ?? []) {
    documentItems.push(
      <li className="delegation-doc-row" key={document.id}>
        <strong>{document.title}</strong>
        <span className="subtle-copy">{document.path}</span>
      </li>,
    );
  }

  // Return the structured delegation brief expected by tech leads reviewing agent work.
  return (
    <div className="delegation-brief">
      <p className="subtle-copy" id="sig16-delegation-traceability">
        Product delivery ticket SIG-16: this panel keeps delegation inputs visible for reviewers and ties runs back to
        issue-tracker context per the MVP workflow (see docs/mvp-definition.md and docs/integrations.md).
      </p>

      <div className="delegation-brief-grid">
        <div className="delegation-brief-block">
          <p className="eyebrow">Repository context</p>
          <dl className="delegation-dl">
            <div>
              <dt>Repository</dt>
              <dd>{repositoryDisplayName}</dd>
            </div>
            <div>
              <dt>Agent branch</dt>
              <dd>{props.run.branch}</dd>
            </div>
            <div>
              <dt>Default branch</dt>
              <dd>{defaultBranchLabel}</dd>
            </div>
            <div>
              <dt>Remote</dt>
              <dd>
                {repositoryBrowseUrl ? (
                  <a className="external-link" href={repositoryBrowseUrl} rel="noreferrer" target="_blank">
                    Open repository
                  </a>
                ) : (
                  <span className="muted-copy">Connect GitHub to show a live repository link.</span>
                )}
              </dd>
            </div>
          </dl>
        </div>

        <div className="delegation-brief-block">
          <p className="eyebrow">Linked issue</p>
          {issue ? (
            <div className="stacked-copy">
              <p>
                <strong>{issue.ticket}</strong>
                {' '}
                —
                {issue.url ? (
                  <a className="external-link" href={issue.url} rel="noreferrer" target="_blank">
                    {' '}
                    Open in
                    {issue.provider ? ` ${issue.provider}` : ' issue tracker'}
                  </a>
                ) : null}
              </p>
              <p className="muted-copy">{issue.title}</p>
              {issue.description?.trim() ? (
                <pre className="delegation-issue-body">{issue.description.trim()}</pre>
              ) : (
                <p className="muted-copy">No issue description was synced for this task.</p>
              )}
            </div>
          ) : (
            <p className="muted-copy">This run was created without a linked issue-tracker ticket.</p>
          )}
        </div>

        <div className="delegation-brief-block delegation-brief-block-wide" id="delegation-acceptance-criteria">
          <p className="eyebrow">Acceptance criteria</p>
          {acceptanceCriteria ? (
            <pre className="delegation-criteria">
              {acceptanceCriteria}
            </pre>
          ) : (
            <p className="muted-copy">
              No explicit acceptance criteria were stored for this run. Use the linked issue and repository context, or
              re-scope the task from intake.
            </p>
          )}
        </div>

        <div className="delegation-brief-block delegation-brief-block-wide">
          <p className="eyebrow">Agent instructions</p>
          <p className="subtle-copy">{executionModeLabel}</p>
          {taskPrompt ? (
            <pre className="delegation-prompt">{taskPrompt}</pre>
          ) : (
            <pre className="delegation-prompt">{props.run.summary}</pre>
          )}
        </div>

        <div className="delegation-brief-block delegation-brief-block-wide">
          <p className="eyebrow">Attached knowledge</p>
          {documentItems.length > 0 ? <ul className="delegation-doc-list">{documentItems}</ul> : (
            <p className="muted-copy">No document snapshots were attached to this delegation.</p>
          )}
        </div>
      </div>

      <p className="subtle-copy" id="delegation-agent-policy-note">
        Agents execute under the active policy pack for this repository, require human approval before merge, and must
        stay within allowed commands and paths described in Settings — matching the control pane agent interaction
        guidelines.
      </p>
    </div>
  );
}

/**
 * Shows the full evidence package for a single task.
 */
function TaskDetailPage() {
  const params = useParams();
  const runId = params.runId ?? '';
  const query = useApiQuery(() => fetchRunDetail(runId), [runId], { pollIntervalMs: 2000 });
  const [runOverride, setRunOverride] = useState<RunSummary | null>(null);
  const [activeEvidenceTab, setActiveEvidenceTab] = useState<EvidenceTabId>('diff');

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
  const liveView = activeRun.liveView ?? null;
  const hasLiveTimeline = Boolean(liveView && liveView.timeline.length > 0);
  const hasLiveLogs = Boolean(liveView && liveView.logs.length > 0);
  const hasLiveEvidence = Boolean(
    liveView
    && (
      liveView.evidenceTabs.diff.length > 0
      || liveView.evidenceTabs.tests.length > 0
      || liveView.evidenceTabs.rationale.length > 0
    ),
  );

  // Present the run as a Discord-style channel room instead of a message thread.
  return (
    <div className="page-grid run-room-page">
      <section className="task-header panel run-room-header">
        <div>
          <p className="eyebrow">#{activeRun.ticket}</p>
          <h3>{activeRun.title}</h3>
          <p className="muted-copy">{activeRun.summary}</p>
          <p className="subtle-copy">
            {buildRunTeamKey(activeRun)} server · {activeRun.issue?.provider ?? 'fallback'} issue context · {buildReviewEffortLabel(activeRun)}
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

      <Panel
        body={<TaskAgentDelegationBriefPanelBody run={activeRun} />}
        title="Agent delegation brief"
      />

      <section className="task-grid run-room-status-grid">
        <Panel
          body={
            <div className="stacked-copy">
              <p>Linked issue: {activeRun.issue?.title ?? 'No linked issue'}</p>
              <p>Requested by: {activeRun.requestedBy?.name ?? activeRun.owner}</p>
              <p>Current step: {activeRun.currentStep}</p>
              <p>Runtime: {activeRun.runtime}</p>
              <p>Cloud agent: {activeRun.cloudAgent?.id ?? 'Not launched'}</p>
              <p>Last updated: {liveView ? formatEventTime(liveView.lastUpdatedAt) : 'Not available'}</p>
            </div>
          }
          title="Channel context"
        />

        <Panel
          body={hasLiveTimeline && liveView
            ? <TimelineList entries={liveView.timeline} liveLabel={liveView.statusLabel} />
            : <p className="muted-copy">No live run timeline is available for this task yet.</p>}
          title="Live activity"
        />

        <Panel
          body={<TaskDecisionPanelBody onRunUpdated={setRunOverride} run={activeRun} />}
          title="Review controls"
        />
      </section>

      <section className="content-grid task-detail-live-grid run-room-stream-grid">
        <Panel
          body={<PullRequestPanelBody run={activeRun} />}
          title="Pull request status"
        />

        <Panel
          body={hasLiveLogs && liveView
            ? <LogStream entries={liveView.logs} />
            : <p className="muted-copy">No live log stream is available for this task yet.</p>}
          title="Run stream"
        />
      </section>

      <Panel
        body={<RunTraceabilityGraphPanelBody run={activeRun} />}
        title="End-to-end traceability"
      />

      <Panel
        body={hasLiveEvidence && liveView
          ? <EvidenceTabPanel activeTab={activeEvidenceTab} liveView={liveView} onTabChange={setActiveEvidenceTab} />
          : <p className="muted-copy">No live evidence has been captured for this task yet.</p>}
        title="Evidence tabs"
      />

      <Panel
        body={<TaskImplementationPackagePanelBody run={activeRun} />}
        title="Reference links"
      />

      <section className="task-grid task-grid-wide">
        <Panel
          body={
            <div className="stacked-copy">
              <DetailList items={activeRun.blockers} />
              {activeRun.pullRequest?.source === 'github' && activeRun.pullRequest.url ? (
                <p className="subtle-copy">
                  Pull request link:{' '}
                  <a className="external-link" href={activeRun.pullRequest.url} rel="noreferrer" target="_blank">
                    {activeRun.pullRequest.url}
                  </a>
                </p>
              ) : (
                <p className="subtle-copy">No live pull request link is available for this task yet.</p>
              )}
            </div>
          }
          title="Blockers and risks"
        />
        <Panel
          body={
            <div className="stacked-copy">
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
 * Resolves the best current pull-request URL available for a run room.
 */
function resolveCurrentPullRequestUrl(run: RunSummary): string {
  const canonicalPullRequestUrl = run.pullRequest?.source === 'github'
    ? run.pullRequest.url.trim()
    : '';

  if (canonicalPullRequestUrl) {
    // Prefer the backend-normalized PR payload because it carries current review state.
    return canonicalPullRequestUrl;
  }

  // Fall back to the Cursor target PR URL while the canonical run payload catches up.
  return run.cloudAgent?.target?.prUrl?.trim() ?? '';
}

/**
 * Resolves the GitHub repository URL tied to a run artifact.
 */
function resolveRunRepositoryUrl(run: RunSummary): string {
  const pullRequestUrl = resolveCurrentPullRequestUrl(run);
  const pullRequestMatch = pullRequestUrl.match(/^(https:\/\/github\.com\/[^/]+\/[^/#?]+)\/pull\/[^/#?]+/iu);

  if (pullRequestMatch) {
    // Use the canonical PR URL so repo links stay aligned with the active artifact.
    return pullRequestMatch[1];
  }

  const sourceRepository = run.cloudAgent?.source?.repository?.trim() ?? '';
  const sourceRepositoryMatch = sourceRepository.match(/^(?:https:\/\/github\.com\/)?([^/\s]+\/[^/\s]+?)(?:\.git)?$/iu);

  if (sourceRepositoryMatch) {
    // Normalize Cursor source repository metadata into a browsable GitHub repo URL.
    return `https://github.com/${sourceRepositoryMatch[1]}`;
  }

  // Return no URL when the run payload does not identify a concrete remote repository.
  return '';
}

/**
 * Resolves the GitHub branch URL tied to a run artifact.
 */
function resolveRunBranchUrl(run: RunSummary): string {
  const repositoryUrl = resolveRunRepositoryUrl(run);
  const branchName = run.cloudAgent?.target?.branchName?.trim() || run.branch.trim();

  if (!repositoryUrl || !branchName) {
    // Avoid emitting a misleading branch link when either side of the URL is unknown.
    return '';
  }

  // Encode branch slashes so GitHub opens the branch name rather than a nested path.
  return `${repositoryUrl}/tree/${encodeURIComponent(branchName)}`;
}

/**
 * Appends a GitHub pull-request subpage to the run's active PR URL.
 */
function resolvePullRequestArtifactUrl(run: RunSummary, subpage: string): string {
  const pullRequestUrl = resolveCurrentPullRequestUrl(run).replace(/\/+$/u, '');

  if (!pullRequestUrl) {
    // Return no URL when there is no PR artifact to extend.
    return '';
  }

  // Keep artifact-specific graph links on the same PR that reviewers already use.
  return `${pullRequestUrl}/${subpage}`;
}

/**
 * Resolves the most relevant CI or validation URL recorded for a run.
 */
function resolveRunValidationUrl(run: RunSummary): string {
  const validationUrls = [
    ...extractUrlsFromText(run.ci?.summary ?? ''),
    ...extractUrlsFromText(run.evidence.tests.join('\n')),
    ...extractUrlsFromText(run.evidence.commands.join('\n')),
  ];

  if (validationUrls.length > 0) {
    // Prefer the first concrete CI URL captured in the backend evidence payload.
    return validationUrls[0];
  }

  // Fall back to the PR checks tab when CI evidence exists but no standalone URL was captured.
  return resolvePullRequestArtifactUrl(run, 'checks');
}

/**
 * Builds a status class name for one traceability graph node.
 */
function buildTraceabilityNodeClassName(status: TraceabilityNodeStatus): string {
  // Join the base graph-card class with a state modifier for visual scanning.
  return `traceability-node traceability-node-${status}`;
}

/**
 * Converts a traceability status into a concise chip label.
 */
function buildTraceabilityStatusLabel(status: TraceabilityNodeStatus): string {
  if (status === 'complete') {
    // Use past-tense wording for steps with captured evidence.
    return 'Captured';
  }

  if (status === 'active') {
    // Use active wording for the currently moving part of the run.
    return 'Active';
  }

  if (status === 'blocked') {
    // Use blocked wording when the run status says this step needs attention.
    return 'Blocked';
  }

  // Return the default pending label for future or unavailable evidence.
  return 'Pending';
}

/**
 * Summarizes the latest human or provider review notes for traceability.
 */
function buildReviewNoteTraceSummary(run: RunSummary): string {
  const visibleHistory = (run.approvalHistory ?? []).filter((entry) => entry.source !== 'simulated');

  if (visibleHistory.length === 0) {
    const pullRequestReviewActivityAt = run.pullRequest?.reviewActivityAt;
    const pullRequestReviewActivityBy = run.pullRequest?.reviewActivityBy;

    if (run.pullRequest?.reviewInProgress) {
      // Summarize GitHub comment activity before a final review decision exists.
      return pullRequestReviewActivityAt
        ? `GitHub review activity${pullRequestReviewActivityBy ? ` by ${pullRequestReviewActivityBy}` : ''} at ${formatEventTime(pullRequestReviewActivityAt)}.`
        : 'GitHub review activity has started.';
    }

    // Tell reviewers that the review step has not produced notes yet.
    return 'No review notes recorded yet.';
  }

  const latestEntry = visibleHistory[visibleHistory.length - 1];
  const decisionLabel = buildApprovalDecisionLabel(latestEntry.decision);
  const actorName = latestEntry.actor?.name ?? 'Reviewer';
  const noteText = latestEntry.notes ? ` - ${latestEntry.notes}` : '';

  // Combine decision, actor, time, and notes into one graph-friendly sentence.
  return `${decisionLabel} by ${actorName} at ${formatEventTime(latestEntry.timestamp)}${noteText}`;
}

/**
 * Derives the end-to-end traceability chain from the run payload.
 */
function buildRunTraceabilityGraph(run: RunSummary): RunTraceabilityNode[] {
  const pullRequestUrl = resolveCurrentPullRequestUrl(run);
  const hasPullRequest = Boolean(pullRequestUrl);
  const visibleHistory = (run.approvalHistory ?? []).filter((entry) => entry.source !== 'simulated');
  const hasReviewNotes = visibleHistory.length > 0;
  const hasReviewInProgress = Boolean(run.pullRequest?.reviewInProgress && !hasReviewNotes);
  const isMerged = Boolean(run.pullRequest?.merged || run.status === 'Merged');
  const isBlocked = run.status === 'Blocked' || run.status === 'Retry';
  const hasTestEvidence = run.evidence.tests.length > 0 || run.evidence.commands.length > 0 || Boolean(run.ci);
  const hasCommitEvidence = run.evidence.diff.length > 0 || hasPullRequest;
  const agentSessionLink = run.cloudAgent?.target?.url?.trim() ?? '';
  const repositoryUrl = resolveRunRepositoryUrl(run);
  const branchUrl = resolveRunBranchUrl(run);
  const commitUrl = resolvePullRequestArtifactUrl(run, 'commits') || branchUrl;
  const pullRequestChecksUrl = resolvePullRequestArtifactUrl(run, 'checks');
  const validationUrl = resolveRunValidationUrl(run);
  const cloudAgentName = run.cloudAgent?.provider === 'github-copilot-cloud-agent' ? 'GitHub Copilot' : 'Cursor';
  const cloudAgentRunLabel = run.cloudAgent?.provider === 'github-copilot-cloud-agent' ? 'Open GitHub Copilot issue' : 'Open Cursor agent run';
  const issueLabel = run.issue?.provider
    ? `${run.issue.provider.toUpperCase()} ticket`
    : 'Issue ticket';

  // Return the complete ordered graph from task intake through merge/deploy readiness.
  return [
    {
      id: 'issue',
      eyebrow: issueLabel,
      title: run.ticket,
      detail: run.issue?.title ?? run.title,
      status: 'complete',
      href: run.issue?.url || undefined,
      hrefLabel: run.issue?.provider ? `Open ${run.issue.provider} task` : 'Open issue artifact',
    },
    {
      id: 'repo',
      eyebrow: 'Selected repo',
      title: run.repo,
      detail: `Owner: ${run.owner}`,
      status: 'complete',
      href: repositoryUrl || undefined,
      hrefLabel: 'Open repository',
    },
    {
      id: 'branch',
      eyebrow: 'Branch',
      title: run.branch,
      detail: 'Workspace branch selected for the agent run.',
      status: 'complete',
      href: branchUrl || undefined,
      hrefLabel: 'Open branch',
    },
    {
      id: 'agent',
      eyebrow: 'Agent session',
      title: run.cloudAgent?.id ?? run.agent,
      detail: run.cloudAgent?.status
        ? `${cloudAgentName} status: ${run.cloudAgent.status}`
        : `Assigned agent: ${run.agent}`,
      status: run.status === 'Running' ? 'active' : 'complete',
      href: agentSessionLink || undefined,
      hrefLabel: cloudAgentRunLabel,
    },
    {
      id: 'commits',
      eyebrow: 'Commits',
      title: hasCommitEvidence ? `${run.evidence.diff.length || 1} change set${run.evidence.diff.length === 1 ? '' : 's'}` : 'No commits captured',
      detail: hasCommitEvidence
        ? run.evidence.diff[0] ?? 'Commit evidence is linked through the pull request.'
        : 'Commit metadata has not been reported for this run yet.',
      status: hasCommitEvidence ? 'complete' : isBlocked ? 'blocked' : 'pending',
      href: commitUrl || undefined,
      hrefLabel: hasPullRequest ? 'Open PR commits' : 'Open branch changes',
    },
    {
      id: 'tests',
      eyebrow: 'Tests',
      title: run.ci?.workflow ?? 'Test evidence',
      detail: run.ci?.summary ?? run.evidence.tests[0] ?? 'No test results captured yet.',
      status: hasTestEvidence ? (isBlocked ? 'blocked' : 'complete') : 'pending',
      href: validationUrl || undefined,
      hrefLabel: validationUrl === pullRequestChecksUrl ? 'Open PR checks' : 'Open test evidence',
    },
    {
      id: 'pull-request',
      eyebrow: 'Pull request',
      title: hasPullRequest ? buildPullRequestStateLabel(run) : 'Not linked',
      detail: hasPullRequest
        ? run.pullRequest?.title ?? `PR ${run.pullRequest?.number ? `#${run.pullRequest.number}` : 'link'} is available.`
        : 'No pull request has been attached to this run yet.',
      status: isMerged ? 'complete' : hasPullRequest ? 'active' : 'pending',
      href: pullRequestUrl || undefined,
      hrefLabel: 'Open pull request',
    },
    {
      id: 'review',
      eyebrow: 'Review notes',
      title: hasReviewNotes ? `${visibleHistory.length} review event${visibleHistory.length === 1 ? '' : 's'}` : hasReviewInProgress ? 'Review in progress' : 'Awaiting review',
      detail: buildReviewNoteTraceSummary(run),
      status: hasReviewNotes ? 'complete' : run.status === 'Review' ? 'active' : 'pending',
      href: pullRequestUrl || undefined,
      hrefLabel: 'Open review artifact',
    },
    {
      id: 'merge-deploy',
      eyebrow: 'Merge/deploy status',
      title: isMerged ? 'Merged' : run.pullRequest?.approved ? 'Approved, awaiting merge' : 'Not merged',
      detail: isMerged
        ? `Merged${run.pullRequest?.mergedAt ? ` at ${formatEventTime(run.pullRequest.mergedAt)}` : ''}; deploy status ready for release tracking.`
        : run.currentStep,
      status: isMerged ? 'complete' : isBlocked ? 'blocked' : 'pending',
      href: pullRequestUrl || undefined,
      hrefLabel: isMerged ? 'Open merged pull request' : 'Open release artifact',
    },
  ];
}

/**
 * Renders an ordered graph of every major artifact connected to the run.
 */
function RunTraceabilityGraphPanelBody(props: { ariaLabel?: string; run: RunSummary; showArtifactLinks?: boolean; variant?: 'default' | 'compact' }) {
  const nodes = buildRunTraceabilityGraph(props.run);
  const graphNodes: ReactNode[] = [];
  // Track the compact lobby variant once so render branches stay readable.
  const isCompactGraph = props.variant === 'compact';
  // Switch to the compact graph class when the graph is embedded in a lobby run channel.
  const graphClassName = isCompactGraph
    ? 'traceability-graph traceability-graph-compact'
    : 'traceability-graph';
  // Keep artifact links enabled by default for full run-room graphs.
  const shouldShowArtifactLinks = props.showArtifactLinks ?? true;

  // Render each traceability node as a connected card with optional deep links.
  for (const [index, node] of nodes.entries()) {
    graphNodes.push(
      <li className="traceability-step" key={node.id}>
        <article className={buildTraceabilityNodeClassName(node.status)}>
          <div className="traceability-node-header">
            <span className="eyebrow">{node.eyebrow}</span>
            <span className="traceability-status">{buildTraceabilityStatusLabel(node.status)}</span>
          </div>
          <strong>{node.title}</strong>
          {isCompactGraph ? null : <p className="muted-copy">{node.detail}</p>}
          {shouldShowArtifactLinks && node.href ? (
            <a className="external-link traceability-link" href={node.href} rel="noreferrer" target="_blank">
              {node.hrefLabel ?? 'Open artifact'}
            </a>
          ) : null}
        </article>
        {index < nodes.length - 1 ? <span aria-hidden="true" className="traceability-connector" /> : null}
      </li>,
    );
  }

  // Return an accessible ordered list so screen readers preserve the graph sequence.
  return (
    <ol aria-label={props.ariaLabel ?? 'Run traceability graph'} className={graphClassName}>
      {graphNodes}
    </ol>
  );
}

/**
 * Renders the reviewer decision controls for a task and persists outcomes through the backend.
 */
function TaskDecisionPanelBody(props: { run: RunSummary; onRunUpdated: (run: RunSummary) => void }) {
  const [notes, setNotes] = useState<string>('');
  const [activeDecision, setActiveDecision] = useState<string>('');
  const [mutationError, setMutationError] = useState<string>('');
  const [mutationSuccess, setMutationSuccess] = useState<string>('');
  const isDecisionLocked = props.run.status === 'Running' || props.run.status === 'Merged';
  const isSubmittingDecision = activeDecision !== '';
  const approvalPullRequestUrl = resolveCurrentPullRequestUrl(props.run);
  const shouldLinkApprovalToPullRequest = Boolean(approvalPullRequestUrl && !isDecisionLocked && !isSubmittingDecision);

  /**
   * Keeps the notes textarea synchronized with the current reviewer input.
   */
  function handleNotesChange(event: ChangeEvent<HTMLTextAreaElement>): void {
    // Mirror the latest textarea value so the next decision includes the reviewer note.
    setNotes(event.target.value);
  }

  /**
   * Sends the selected decision to the backend and applies the returned run state locally.
   */
  async function handleDecisionSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from leaving the task detail page during the mutation.
    event.preventDefault();

    const nativeSubmitEvent = event.nativeEvent as SubmitEvent;
    const submitter = nativeSubmitEvent.submitter;

    if (!(submitter instanceof HTMLButtonElement)) {
      // Surface a readable error when the browser does not expose the clicked decision button.
      setMutationError('Unable to determine which review action was selected.');
      setMutationSuccess('');
      return;
    }

    const decision = submitter.value.trim().toLowerCase();

    if (!decision) {
      // Guard against empty decision payloads before calling the backend.
      setMutationError('Choose a review action before submitting.');
      setMutationSuccess('');
      return;
    }

    setActiveDecision(decision);
    setMutationError('');
    setMutationSuccess('');

    try {
      // Persist the reviewer action so task detail and dashboard read the same backend-backed run state.
      const updatedRun = await createApprovalDecision({
        runId: props.run.id,
        decision,
        notes,
      });

      // Replace the visible task snapshot with the backend response immediately after the mutation succeeds.
      props.onRunUpdated(updatedRun);

      if (decision === 'approve') {
        // Confirm that the task moved into the approved state that the dashboard also summarizes.
        setMutationSuccess('Task approved. The dashboard will show it as approved when you return.');
      } else if (decision === 'retry') {
        // Confirm that the task moved into the retry state for another agent attempt.
        setMutationSuccess('Retry requested. The dashboard will now treat this task as a retry.');
      } else if (decision === 're-scope') {
        // Confirm that the task moved into the blocked state pending updated scope.
        setMutationSuccess('Re-scope requested. The dashboard will now show this task as blocked.');
      } else {
        // Confirm that fallback reviewer actions land in the blocked escalation path.
        setMutationSuccess('Escalation recorded. The dashboard will now show this task as blocked.');
      }

      // Clear the notes field once the reviewer decision has been saved successfully.
      setNotes('');
    } catch (caughtError) {
      // Surface backend approval failures directly in the decision panel.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to save the reviewer decision.');
      setMutationSuccess('');
    } finally {
      // Restore the decision buttons after the mutation settles.
      setActiveDecision('');
    }
  }

  // Explain when the reviewer controls are intentionally unavailable for the current run state.
  const helperCopy = isDecisionLocked
    ? (props.run.status === 'Merged'
        ? 'This run has already merged, so no further reviewer decision is needed.'
        : 'Reviewer controls unlock after the run finishes and reaches a reviewable state.')
    : (approvalPullRequestUrl
        ? 'Open the current pull request to approve the work in GitHub; the run room will sync the PR review state.'
        : 'Save a reviewer decision here to update the run state the dashboard summarizes.');

  return (
    <form className="form-grid" onSubmit={handleDecisionSubmit}>
      <p className="muted-copy">{helperCopy}</p>

      <label className="field-group field-group-wide">
        <span>Reviewer notes</span>
        <textarea
          className="notes-input"
          disabled={isSubmittingDecision}
          onChange={handleNotesChange}
          placeholder="Summarize why this task should be approved, retried, re-scoped, or escalated."
          rows={4}
          value={notes}
        />
      </label>

      <div aria-live="polite" className="status-message-region" role="status">
        {mutationSuccess ? <p className="success-copy">{mutationSuccess}</p> : null}
        {mutationError ? <p className="error-copy">{mutationError}</p> : null}
      </div>

      <div className="action-stack">
        {shouldLinkApprovalToPullRequest ? (
          <a className="primary-button" href={approvalPullRequestUrl} rel="noreferrer" target="_blank">
            Approve
          </a>
        ) : (
          <button className="primary-button" disabled={isDecisionLocked || isSubmittingDecision} type="submit" value="approve">
            {activeDecision === 'approve' ? 'Saving approval...' : 'Approve'}
          </button>
        )}
        <button className="ghost-button" disabled={isDecisionLocked || isSubmittingDecision} type="submit" value="retry">
          {activeDecision === 'retry' ? 'Saving retry...' : 'Retry'}
        </button>
        <button className="ghost-button" disabled={isDecisionLocked || isSubmittingDecision} type="submit" value="re-scope">
          {activeDecision === 're-scope' ? 'Saving re-scope...' : 'Re-scope'}
        </button>
        <button className="ghost-button" disabled={isDecisionLocked || isSubmittingDecision} type="submit" value="escalate">
          {activeDecision === 'escalate' ? 'Saving escalation...' : 'Escalate'}
        </button>
      </div>
    </form>
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
  const [jiraForm, setJiraForm] = useState<JiraConnectRequest>({
    siteUrl: '',
    email: '',
    apiToken: '',
    projectKey: '',
  });
  const [cursorForm, setCursorForm] = useState<CursorConnectRequest>({
    apiKey: '',
    model: 'default',
  });
  const [githubCopilotForm, setGithubCopilotForm] = useState<GitHubCopilotConnectRequest>({
    token: '',
    model: '',
    customAgent: '',
  });
  const [mutationError, setMutationError] = useState<string>('');
  const [mutationSuccess, setMutationSuccess] = useState<string>('');
  const [activeSetupId, setActiveSetupId] = useState<string>('');
  const query = useApiQuery(fetchIntegrations, [refreshKey]);
  const integrationCards: ReactNode[] = [];
  const settingsSectionLinks: Array<{ id: string; label: string }> = [
    { id: 'provider-status', label: 'Provider status' },
    { id: 'github-settings', label: 'GitHub setup' },
    { id: 'linear-settings', label: 'Linear setup' },
    { id: 'jira-settings', label: 'Jira setup' },
    { id: 'cursor-settings', label: 'Cursor setup' },
    { id: 'github-copilot-settings', label: 'Copilot setup' },
  ];

  useEffect(() => {
    const githubStatus = findIntegrationStatus(query.data?.statuses ?? [], 'github');
    const linearStatus = findIntegrationStatus(query.data?.statuses ?? [], 'linear');
    const jiraStatus = findIntegrationStatus(query.data?.statuses ?? [], 'jira');
    const cursorStatus = findIntegrationStatus(query.data?.statuses ?? [], 'cursor_cloud_agents');
    const githubCopilotStatus = findIntegrationStatus(query.data?.statuses ?? [], 'github_copilot_cloud_agent');

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

    // Mirror the saved Jira connection into the setup form defaults.
    setJiraForm({
      siteUrl: getConnectionValue(jiraStatus, 'siteUrl'),
      email: getConnectionValue(jiraStatus, 'email'),
      apiToken: '',
      projectKey: getConnectionValue(jiraStatus, 'projectKey'),
    });

    // Mirror the saved Cursor connection into the setup form defaults.
    setCursorForm({
      apiKey: '',
      model: getConnectionValue(cursorStatus, 'model') || 'default',
    });

    // Mirror the saved GitHub Copilot connection into the setup form defaults.
    setGithubCopilotForm({
      token: '',
      model: getConnectionValue(githubCopilotStatus, 'model'),
      customAgent: getConnectionValue(githubCopilotStatus, 'customAgent'),
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
   * Saves the Jira Cloud setup selected by the user.
   */
  async function handleJiraConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('jira');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the Jira Cloud setup for the current signed-in session.
      await connectJira(jiraForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('Jira connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface Jira setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect Jira.');
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
   * Saves the GitHub Copilot cloud agent setup selected by the user.
   */
  async function handleGitHubCopilotConnect(event: FormEvent<HTMLFormElement>): Promise<void> {
    // Prevent the browser from performing a full page form submission.
    event.preventDefault();
    setActiveSetupId('github_copilot_cloud_agent');
    setMutationError('');
    setMutationSuccess('');

    try {
      // Save the Copilot setup for the current signed-in session.
      await connectGitHubCopilot(githubCopilotForm);

      // Show a success message and refresh the status view.
      setMutationSuccess('GitHub Copilot cloud agent connection saved for this session.');
      setRefreshKey((currentValue) => currentValue + 1);
    } catch (caughtError) {
      // Surface Copilot setup failures directly inside the integrations view.
      setMutationError(caughtError instanceof Error ? caughtError.message : 'Unable to connect GitHub Copilot cloud agent.');
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
          <p className="eyebrow">Settings</p>
          <h3>Manage integrations with a guided, accessible setup flow for GitHub, Linear, Jira, Cursor Cloud Agents, and GitHub Copilot cloud agent.</h3>
        </div>
        <div className="hero-pills">
          <span className="pill">{props.currentUser.name}</span>
          <span className="pill">{buildRoleLabel(props.currentUser.role)}</span>
          <span className="pill">{query.data.statuses.length} providers</span>
        </div>
      </section>

      <section aria-label="Settings sections" className="settings-nav-panel panel">
        <div className="panel-header">
          <h3>Settings navigation</h3>
        </div>
        <div className="panel-body">
          <p className="muted-copy">Jump directly to a setup section and verify each provider configuration quickly.</p>
          <nav className="settings-anchor-nav">
            {settingsSectionLinks.map((link) => (
              <a className="ghost-button link-button settings-anchor-link" href={`#${link.id}`} key={link.id}>
                {link.label}
              </a>
            ))}
          </nav>
        </div>
      </section>

      <div aria-live="polite" className="status-message-region" role="status">
        {mutationSuccess ? <p className="success-copy">{mutationSuccess}</p> : null}
        {mutationError ? <p className="error-copy">{mutationError}</p> : null}
      </div>

      <section id="provider-status">
        <Panel body={<div className="integration-grid">{integrationCards}</div>} title="Provider status" />
      </section>

      <section className="content-grid approvals-grid">
        <Panel
          title="Connect GitHub"
          body={
            <form aria-describedby="github-setup-help github-settings-a11y github-settings-traceability" className="form-grid" id="github-settings" onSubmit={(event) => { void handleGitHubConnect(event); }}>
              <p className="muted-copy" id="github-setup-help">Step 1: choose an org or owner. Step 2: list the repos agents may target. Step 3: add an optional token for private repos and higher rate limits.</p>
              <p className="subtle-copy" id="github-settings-a11y">Accessibility note: keep owner and repo names human-readable so reviewer context is clear across dashboard, task detail, and approvals.</p>
              <p className="subtle-copy" id="github-settings-traceability">Traceability note: GitHub repo metadata links issue context to pull-request and agent-run audit trails.</p>
              <label className="field-group">
                <span>Owner or org</span>
                <input
                  aria-label="GitHub owner or organization"
                  onChange={(event) => { setGithubForm({ ...githubForm, owner: event.target.value }); }}
                  placeholder="your-org"
                  type="text"
                  value={githubForm.owner}
                />
              </label>
              <label className="field-group">
                <span>Repositories</span>
                <input
                  aria-label="GitHub repositories"
                  onChange={(event) => { setGithubForm({ ...githubForm, repositories: event.target.value }); }}
                  placeholder="web-app, api-service"
                  type="text"
                  value={githubForm.repositories}
                />
              </label>
              <label className="field-group">
                <span>Token</span>
                <input
                  aria-label="GitHub personal access token"
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
            <form aria-describedby="linear-setup-help linear-settings-a11y linear-settings-traceability" className="form-grid" id="linear-settings" onSubmit={(event) => { void handleLinearConnect(event); }}>
              <p className="muted-copy" id="linear-setup-help">Step 1: create a Linear API key. Step 2: add an optional team ID, key, or exact name if you want intake scoped to one team.</p>
              <p className="subtle-copy" id="linear-settings-a11y">Accessibility note: use a specific team identifier when possible so the intake queue remains concise and easier to scan.</p>
              <p className="subtle-copy" id="linear-settings-traceability">Traceability note: Linear ticket IDs anchor work from intake through implementation and review evidence.</p>
              <label className="field-group">
                <span>API key</span>
                <input
                  aria-label="Linear API key"
                  onChange={(event) => { setLinearForm({ ...linearForm, apiKey: event.target.value }); }}
                  placeholder="lin_api_..."
                  type="password"
                  value={linearForm.apiKey}
                />
              </label>
              <label className="field-group">
                <span>Team ID or key</span>
                <input
                  aria-label="Linear team ID or team key"
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

        <Panel
          title="Connect Jira"
          body={
            <form aria-describedby="jira-setup-help jira-settings-a11y jira-settings-traceability" className="form-grid" id="jira-settings" onSubmit={(event) => { void handleJiraConnect(event); }}>
              <p className="muted-copy" id="jira-setup-help">Step 1: add your Jira Cloud site URL. Step 2: add the Atlassian account email and API token. Step 3: add an optional project key if you want intake scoped to one project.</p>
              <p className="subtle-copy" id="jira-settings-a11y">Accessibility note: use a specific Jira project key when possible so the intake queue remains concise and easier to scan.</p>
              <p className="subtle-copy" id="jira-settings-traceability">Traceability note: Jira issue keys anchor work from intake through implementation and review evidence.</p>
              <label className="field-group">
                <span>Site URL</span>
                <input
                  aria-label="Jira Cloud site URL"
                  onChange={(event) => { setJiraForm({ ...jiraForm, siteUrl: event.target.value }); }}
                  placeholder="https://your-team.atlassian.net"
                  type="text"
                  value={jiraForm.siteUrl}
                />
              </label>
              <label className="field-group">
                <span>Email</span>
                <input
                  aria-label="Jira account email"
                  onChange={(event) => { setJiraForm({ ...jiraForm, email: event.target.value }); }}
                  placeholder="you@example.com"
                  type="email"
                  value={jiraForm.email}
                />
              </label>
              <label className="field-group">
                <span>API token</span>
                <input
                  aria-label="Jira API token"
                  onChange={(event) => { setJiraForm({ ...jiraForm, apiToken: event.target.value }); }}
                  placeholder="Atlassian API token"
                  type="password"
                  value={jiraForm.apiToken}
                />
              </label>
              <label className="field-group">
                <span>Project key</span>
                <input
                  aria-label="Jira project key"
                  onChange={(event) => { setJiraForm({ ...jiraForm, projectKey: event.target.value }); }}
                  placeholder="Optional project key"
                  type="text"
                  value={jiraForm.projectKey}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'jira'} type="submit">
                  {activeSetupId === 'jira' ? 'Saving Jira...' : 'Connect Jira'}
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
            <form aria-describedby="cursor-setup-help cursor-settings-a11y cursor-settings-traceability" className="form-grid" id="cursor-settings" onSubmit={(event) => { void handleCursorConnect(event); }}>
              <p className="muted-copy" id="cursor-setup-help">Step 1: add a Cursor API key. Step 2: choose a model. Step 3: use Start run on a task to launch a real agent against the connected GitHub repository with the selected issue context.</p>
              <p className="subtle-copy" id="cursor-settings-a11y">Accessibility note: keep model naming consistent so operators can compare run behavior and evidence with less cognitive load.</p>
              <p className="subtle-copy" id="cursor-settings-traceability">Traceability note: connected agent metadata is surfaced on task detail pages for run-level auditability.</p>
              <label className="field-group">
                <span>API key</span>
                <input
                  aria-label="Cursor API key"
                  onChange={(event) => { setCursorForm({ ...cursorForm, apiKey: event.target.value }); }}
                  placeholder="cur_..."
                  type="password"
                  value={cursorForm.apiKey}
                />
              </label>
              <label className="field-group">
                <span>Model</span>
                <input
                  aria-label="Cursor model"
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
          title="Connect GitHub Copilot cloud agent"
          body={
            <form aria-describedby="github-copilot-setup-help github-copilot-settings-a11y github-copilot-settings-traceability" className="form-grid" id="github-copilot-settings" onSubmit={(event) => { void handleGitHubCopilotConnect(event); }}>
              <p className="muted-copy" id="github-copilot-setup-help">Step 1: add a GitHub token with Copilot issue-assignment permissions. Step 2: optionally choose a model or custom agent. Step 3: use Start run to create a GitHub issue assigned to Copilot for the selected repository.</p>
              <p className="subtle-copy" id="github-copilot-settings-a11y">Accessibility note: keep model and custom-agent labels readable so operators can distinguish Copilot runs from Cursor runs.</p>
              <p className="subtle-copy" id="github-copilot-settings-traceability">Traceability note: the generated GitHub issue is surfaced as the cloud-agent session link on task detail pages.</p>
              <label className="field-group">
                <span>GitHub token</span>
                <input
                  aria-label="GitHub token for Copilot cloud agent"
                  onChange={(event) => { setGithubCopilotForm({ ...githubCopilotForm, token: event.target.value }); }}
                  placeholder="ghp_..."
                  type="password"
                  value={githubCopilotForm.token}
                />
              </label>
              <label className="field-group">
                <span>Model</span>
                <input
                  aria-label="GitHub Copilot cloud agent model"
                  onChange={(event) => { setGithubCopilotForm({ ...githubCopilotForm, model: event.target.value }); }}
                  placeholder="Optional model"
                  type="text"
                  value={githubCopilotForm.model}
                />
              </label>
              <label className="field-group">
                <span>Custom agent</span>
                <input
                  aria-label="GitHub Copilot custom agent"
                  onChange={(event) => { setGithubCopilotForm({ ...githubCopilotForm, customAgent: event.target.value }); }}
                  placeholder="Optional custom agent"
                  type="text"
                  value={githubCopilotForm.customAgent}
                />
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={activeSetupId === 'github_copilot_cloud_agent'} type="submit">
                  {activeSetupId === 'github_copilot_cloud_agent' ? 'Saving Copilot...' : 'Connect Copilot'}
                </button>
              </div>
            </form>
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
  if (targetPath === '/settings' && pathname === '/integrations') {
    // Keep the settings nav state active for the legacy integrations route alias.
    return 'nav-link active';
  }

  // Highlight the current section so navigation stays oriented.
  return pathname === targetPath ? 'nav-link active' : 'nav-link';
}

/**
 * Builds the shared shell title for the current page route.
 */
function buildShellPageTitle(pathname: string): string {
  if (pathname.startsWith('/tasks/')) {
    // Label individual run detail pages as focused run rooms.
    return 'Run Room';
  }

  if (pathname === '/intake') {
    // Match the intake route to the sidebar channel label for agent delegation (SIG-16).
    return 'Delegate to agent';
  }

  if (pathname === '/settings' || pathname === '/integrations') {
    // Treat the legacy integrations alias as the settings page.
    return 'Settings';
  }

  // Keep the dashboard title as the default shell landing state.
  return 'Run Channels';
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
  void role;

  // Return the only supported role label.
  return 'Admin';
}

/**
 * Builds the sign-in capability list for the admin session.
 */
function buildRoleCapabilityItems(): ReactNode[] {
  const capabilities: string[] = [
    'Access every route in the control plane.',
    'Launch work, review approval-ready runs, and resolve decisions.',
    'Manage integrations, sign-in flows, and control-pane governance.',
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
    <section aria-busy="true" aria-live="polite" className="panel state-panel" role="status">
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
    <section className="panel state-panel" role="alert">
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
        {buildRoleLabel(props.currentUser.role)} sessions can still inspect dashboards and task detail, but only admin sessions can manage approvals and integrations.
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
  const evidencePanelId = useId();
  const availableTabs: EvidenceTabId[] = ['diff', 'tests', 'rationale'];
  const activeEntries = props.liveView.evidenceTabs[props.activeTab];
  const tabButtons: ReactNode[] = [];
  const evidenceRows: ReactNode[] = [];

  /**
   * Builds a stable DOM id for each evidence tab control.
   */
  function buildEvidenceTabId(tab: EvidenceTabId): string {
    // Join the React id prefix with the tab key so each control stays unique in the DOM.
    return `${evidencePanelId}-${tab}-tab`;
  }

  /**
   * Builds a stable DOM id for each evidence tab panel region.
   */
  function buildEvidencePanelId(tab: EvidenceTabId): string {
    // Join the React id prefix with the tab key so each panel stays unique in the DOM.
    return `${evidencePanelId}-${tab}-panel`;
  }

  /**
   * Moves focus across evidence tabs using arrow keys for keyboard parity with mouse users.
   */
  function handleEvidenceTabKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    // Ignore keys that are not part of the roving tablist interaction model.
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'Home' && event.key !== 'End') {
      return;
    }

    // Prevent the browser from scrolling the page horizontally while changing tabs.
    event.preventDefault();

    const activeIndex = availableTabs.indexOf(props.activeTab);

    if (activeIndex < 0) {
      // Bail out when the active tab is not part of the supported tab list.
      return;
    }

    let nextIndex = activeIndex;

    if (event.key === 'ArrowRight') {
      // Advance to the next tab and wrap from the end back to the start.
      nextIndex = (activeIndex + 1) % availableTabs.length;
    } else if (event.key === 'ArrowLeft') {
      // Move to the previous tab and wrap from the start back to the end.
      nextIndex = (activeIndex - 1 + availableTabs.length) % availableTabs.length;
    } else if (event.key === 'Home') {
      // Jump directly to the first tab for faster scanning from the keyboard.
      nextIndex = 0;
    } else {
      // Jump directly to the last tab when End is pressed.
      nextIndex = availableTabs.length - 1;
    }

    const nextTab = availableTabs[nextIndex];

    // Update the selected tab so the panel content stays synchronized with focus intent.
    props.onTabChange(nextTab);

    // Move keyboard focus to the newly selected tab button after React re-renders.
    window.requestAnimationFrame(() => {
      document.getElementById(buildEvidenceTabId(nextTab))?.focus();
    });
  }

  // Render the evidence tab buttons with counts from the current live-view snapshot.
  for (const tab of availableTabs) {
    const isSelected = tab === props.activeTab;

    tabButtons.push(
      <button
        aria-controls={buildEvidencePanelId(tab)}
        aria-selected={isSelected}
        className={isSelected ? 'evidence-tab evidence-tab-active' : 'evidence-tab'}
        id={buildEvidenceTabId(tab)}
        key={tab}
        onClick={() => { props.onTabChange(tab); }}
        role="tab"
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
      <div aria-label="Evidence categories" className="evidence-tab-list" onKeyDown={handleEvidenceTabKeyDown} role="tablist">
        {tabButtons}
      </div>
      <div
        aria-labelledby={buildEvidenceTabId(props.activeTab)}
        className="evidence-tab-panel"
        id={buildEvidencePanelId(props.activeTab)}
        role="tabpanel"
        tabIndex={0}
      >
        {evidenceRows.length > 0 ? <div className="evidence-row-list">{evidenceRows}</div> : <p className="muted-copy">No evidence has streamed into this tab yet.</p>}
      </div>
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

  // Default every remaining event to the in-app reviewer source.
  return 'Reviewer';
}

/**
 * Renders the approval history list for a task including reviewer and GitHub events.
 */
function ApprovalHistoryList(props: { entries: RunSummary['approvalHistory'] }) {
  const visibleEntries = (props.entries ?? []).filter((entry) => entry.source !== 'simulated');

  if (visibleEntries.length === 0) {
    // Return a neutral placeholder when there is no approval history yet.
    return <p className="muted-copy">No approval actions have been recorded yet.</p>;
  }

  const historyItems: ReactNode[] = [];

  // Render each approval record with its acting user, source, and timestamp.
  for (const entry of visibleEntries) {
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
    if (pullRequest.reviewInProgress) {
      // Show PR comment activity as an active review instead of an untouched queue item.
      return 'Open - review in progress';
    }

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
  const currentPullRequestUrl = resolveCurrentPullRequestUrl(props.run);
  const hasLivePullRequest = Boolean(prInfo && prInfo.source === 'github' && prInfo.url);
  const stateLabel = hasLivePullRequest ? buildPullRequestStateLabel(props.run) : null;
  const approvedAt = hasLivePullRequest && prInfo?.approvedAt ? formatEventTime(prInfo.approvedAt) : null;
  const mergedAt = hasLivePullRequest && prInfo?.mergedAt ? formatEventTime(prInfo.mergedAt) : null;
  const cloudAgentUrl = props.run.cloudAgent?.target?.url ?? '';
  const cloudAgentName = props.run.cloudAgent?.provider === 'github-copilot-cloud-agent' ? 'GitHub Copilot' : 'Cursor';

  // Return the combined PR + CI summary used on the task detail page.
  return (
    <div className="stacked-copy">
      {hasLivePullRequest && stateLabel ? (
        <p>
          Pull request: <strong>{stateLabel}</strong>
        </p>
      ) : (
        <p className="muted-copy">No live pull request metadata is available for this task yet.</p>
      )}
      {hasLivePullRequest && prInfo?.number ? <p className="subtle-copy">PR number: #{prInfo.number}</p> : null}
      {currentPullRequestUrl ? (
        <p className="subtle-copy">
          PR link:{' '}
          <a className="external-link" href={currentPullRequestUrl} rel="noreferrer" target="_blank">
            {currentPullRequestUrl}
          </a>
        </p>
      ) : null}
      {hasLivePullRequest && prInfo?.approved ? (
        <p className="subtle-copy">
          Approved{prInfo.approvedBy ? ` by ${prInfo.approvedBy}` : ''}
          {approvedAt ? ` at ${approvedAt}` : ''}
        </p>
      ) : null}
      {hasLivePullRequest && prInfo?.merged ? (
        <p className="subtle-copy">Merged{mergedAt ? ` at ${mergedAt}` : ''}</p>
      ) : null}
      {props.run.cloudAgent?.status ? <p>{cloudAgentName} status: {props.run.cloudAgent.status}</p> : null}
      {cloudAgentUrl ? (
        <p className="subtle-copy">
          Cloud agent link:{' '}
          <a className="external-link" href={cloudAgentUrl} rel="noreferrer" target="_blank">
            {cloudAgentUrl}
          </a>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Extracts distinct HTTP(S) URLs from a free-form text block.
 */
function extractUrlsFromText(text: string): string[] {
  // Match URLs conservatively so CI and evidence links can be rendered as anchors.
  const urlMatches = text.match(/https?:\/\/[^\s)]+/gi) ?? [];
  const normalizedUrls: string[] = [];
  const seenUrls = new Set<string>();

  // Deduplicate while preserving order for predictable UI rendering.
  for (const rawUrl of urlMatches) {
    const sanitizedUrl = rawUrl.replace(/[.,;!?]+$/u, '');

    if (!seenUrls.has(sanitizedUrl)) {
      // Store each unique URL once so repeated references do not clutter the panel.
      seenUrls.add(sanitizedUrl);
      normalizedUrls.push(sanitizedUrl);
    }
  }

  // Return the ordered list of unique URLs extracted from the input text.
  return normalizedUrls;
}

/**
 * Builds a grouped link package for task detail traceability and evidence review.
 */
function collectTaskDetailReferenceLinks(run: RunSummary): {
  issueLinks: string[];
  interfaceLinks: string[];
  ciLinks: string[];
  evidenceLinks: string[];
} {
  const issueLinks: string[] = [];
  const interfaceLinks: string[] = [];
  const ciLinks: string[] = [];
  const evidenceLinks: string[] = [];

  if (run.issue?.url) {
    // Preserve issue-provider traceability by linking directly back to the originating ticket.
    issueLinks.push(run.issue.url);
  }

  if (run.pullRequest?.source === 'github' && run.pullRequest.url) {
    // Include the PR URL because updated UI screenshots and previews are commonly attached there.
    interfaceLinks.push(run.pullRequest.url);
  }

  if (run.cloudAgent?.target?.url) {
    // Include the cloud-agent session URL so reviewers can inspect generated preview output.
    interfaceLinks.push(run.cloudAgent.target.url);
  }

  if (run.cloudAgent?.target?.prUrl) {
    // Include the cloud-agent PR URL when it differs from the canonical pull-request field.
    interfaceLinks.push(run.cloudAgent.target.prUrl);
  }

  if (run.ci?.summary) {
    // Extract CI URLs from the backend summary text so status checks are directly clickable.
    ciLinks.push(...extractUrlsFromText(run.ci.summary));
  }

  const evidenceUrls = [
    ...extractUrlsFromText(run.evidence.diff.join('\n')),
    ...extractUrlsFromText(run.evidence.tests.join('\n')),
    ...extractUrlsFromText(run.evidence.commands.join('\n')),
    ...extractUrlsFromText(run.evidence.rationale.join('\n')),
  ];

  // Include proof links captured in run evidence (screenshots, recordings, logs, or docs).
  evidenceLinks.push(...evidenceUrls);

  const dedupe = (items: string[]): string[] => Array.from(new Set(items));

  // Return deduplicated grouped links for predictable task-detail rendering.
  return {
    issueLinks: dedupe(issueLinks),
    interfaceLinks: dedupe(interfaceLinks),
    ciLinks: dedupe(ciLinks),
    evidenceLinks: dedupe(evidenceLinks),
  };
}

/**
 * Renders task-specific traceability links sourced from the run payload.
 */
function TaskImplementationPackagePanelBody(props: { run: RunSummary }) {
  const links = collectTaskDetailReferenceLinks(props.run);
  const traceability = props.run.traceability;
  const hasReferenceLinks = (
    links.issueLinks.length > 0
    || links.interfaceLinks.length > 0
    || links.ciLinks.length > 0
    || links.evidenceLinks.length > 0
  );
  const hasTraceabilitySnapshot = Boolean(traceability);

  /**
   * Builds reviewer-facing traceability summary lines from the run snapshot.
   */
  function buildTraceabilitySnapshotItems(): string[] {
    if (!traceability) {
      // Return no lines when the backend did not include a traceability snapshot.
      return [];
    }

    const summaryItems: string[] = [
      `Ticket: ${traceability.ticket || props.run.ticket}`,
      `Issue provider: ${traceability.issueProvider || 'fallback'}`,
      `Issue launch status: ${traceability.issueStatusAtLaunch || 'Unknown'}`,
      `Run status: ${traceability.runStatus || props.run.status}`,
      `Pull request status: ${traceability.pullRequestStatus || 'draft'} (${traceability.pullRequestSource || 'simulated'})`,
      `Evidence entries captured: ${traceability.capturedEvidenceCount}`,
      `Preserved from In Progress: ${traceability.preservedFromInProgress ? 'Yes' : 'No'}`,
    ];

    if (traceability.latestDecision) {
      // Append the latest decision only when reviewer or provider history exists.
      summaryItems.push(`Latest decision: ${traceability.latestDecision}`);
    }

    // Return the assembled summary lines for the traceability section.
    return summaryItems;
  }

  const traceabilitySnapshotItems = buildTraceabilitySnapshotItems();

  /**
   * Renders a titled list of external links used as review evidence.
   */
  function renderLinkGroup(title: string, urls: string[], emptyMessage: string): ReactNode {
    if (urls.length === 0) {
      // Return a neutral hint when the backend did not provide links for this section yet.
      return (
        <div className="stacked-copy">
          <strong>{title}</strong>
          <p className="muted-copy">{emptyMessage}</p>
        </div>
      );
    }

    const linkItems: ReactNode[] = [];

    // Render each URL as an accessible external anchor for quick reviewer access.
    for (const [index, url] of urls.entries()) {
      linkItems.push(
        <li key={`${title}-${url}`}>
          <a className="external-link" href={url} rel="noreferrer" target="_blank">
            {title} link {index + 1}
          </a>
        </li>,
      );
    }

    // Return the titled list of links for this evidence section.
    return (
      <div className="stacked-copy">
        <strong>{title}</strong>
        <ul className="external-link-list">{linkItems}</ul>
      </div>
    );
  }

  if (!hasReferenceLinks && !hasTraceabilitySnapshot) {
    // Return a neutral placeholder when the run does not expose any concrete task links yet.
    return <p className="muted-copy">No task-specific reference links are available for this run yet.</p>;
  }

  // Render only concrete links sourced from the run payload.
  return (
    <div className="stacked-copy">
      {traceabilitySnapshotItems.length > 0 ? (
        <div className="stacked-copy">
          <strong>Traceability snapshot</strong>
          <DetailList items={traceabilitySnapshotItems} />
        </div>
      ) : null}
      {links.issueLinks.length > 0 ? renderLinkGroup('Issue traceability', links.issueLinks, '') : null}
      {links.interfaceLinks.length > 0 ? renderLinkGroup('Updated interface', links.interfaceLinks, '') : null}
      {links.ciLinks.length > 0 ? renderLinkGroup('CI results', links.ciLinks, '') : null}
      {links.evidenceLinks.length > 0 ? renderLinkGroup('Evidence links', links.evidenceLinks, '') : null}
    </div>
  );
}

/**
 * Wraps page sections in a consistent panel treatment.
 */
function Panel(props: { title: string; body: ReactNode }) {
  // Keep content framing consistent across dashboard and review views.
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>{props.title}</h3>
      </div>
      <div className="panel-body">{props.body}</div>
    </section>
  );
}

export {
  AccessDeniedState,
  App,
  ApprovalHistoryList,
  DashboardPage,
  DetailList,
  DocumentList,
  ErrorState,
  EvidenceTabPanel,
  GoogleAuthCallbackPage,
  GoogleOAuthReturnPage,
  IntegrationStatusCard,
  IntegrationsPage,
  LandingPage,
  LoadingState,
  LogStream,
  MetricCard,
  Panel,
  PullRequestPanelBody,
  RoleGate,
  RootLayout,
  SignInPage,
  StandaloneStatePanel,
  StatusBadge,
  TaskAgentDelegationBriefPanelBody,
  TaskDecisionPanelBody,
  TaskDetailPage,
  TaskImplementationPackagePanelBody,
  RunTraceabilityGraphPanelBody,
  TimelineList,
  WorkIntakePage,
  buildApprovalDecisionLabel,
  buildApprovalSourceLabel,
  buildEnrichmentSourceLabel,
  buildEvidenceStatusClassName,
  buildEvidenceTabLabel,
  buildIssueTrackerRunLabel,
  buildLogEntryClassName,
  buildPullRequestStateLabel,
  buildReviewEffortLabel,
  buildRoleCapabilityItems,
  buildRoleLabel,
  buildRunTraceabilityGraph,
  buildRunTeamGroups,
  buildRunTeamKey,
  buildShellPageTitle,
  buildTeamHoverLabel,
  buildTeamInitials,
  buildTraceabilityNodeClassName,
  buildTraceabilityStatusLabel,
  buildTimelineEntryClassName,
  buildUploadedDocumentRecord,
  buildUserHeadline,
  buildUserSubtitle,
  canAccessRole,
  collectBlockerReasons,
  collectTaskDetailReferenceLinks,
  mergeDashboardBlockedReasonLists,
  deriveDashboardMetrics,
  exchangeGoogleAuthCodeOnce,
  extractUrlsFromText,
  findIntegrationStatus,
  findIssueById,
  formatEventTime,
  formatExecutionModeLabel,
  formatReviewEffortValue,
  getConnectionValue,
  getDocumentsForRepository,
  getNavLinkClassName,
  getRunChannelTone,
  isActionableBlocker,
  isIssueTrackerProvider,
  isIssueTrackerRun,
  parseRuntimeSeconds,
  resolveCurrentPullRequestUrl,
  shouldShowRunLobbyPullRequest,
};

export default App;
