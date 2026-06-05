import type { ChangeEvent, FormEvent, MouseEvent, ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import {
  DetailList,
  ErrorState,
  EvidenceTabPanel,
  IntegrationStatusCard,
  LoadingState,
  LogStream,
  MetricCard,
  Panel,
  StandaloneStatePanel,
  StatusBadge,
  TimelineList,
} from './components/ui';
import {
  ApprovalHistoryList,
  PullRequestPanelBody,
  RunLobbyPullRequestPreview,
  RunTraceabilityGraphPanelBody,
  TaskAgentDelegationBriefPanelBody,
  TaskDecisionPanelBody,
  TaskImplementationPackagePanelBody,
} from './components/run/TaskPanels';
import {
  GoogleAuthCallbackPage,
  GoogleOAuthReturnPage,
  LandingPage,
  RoleGate,
  RootLayout,
  SignInPage,
} from './pages/AuthPages';
import { useIntegrationForms } from './hooks/useIntegrationForms';
import { useApiQuery } from './hooks/useApiQuery';
import { useIntakeForm } from './hooks/useIntakeForm';
import { useMissionControlDashboard } from './hooks/useMissionControlDashboard';
import {
  type EvidenceTabId,
  buildEnrichmentSourceLabel,
  buildIssueTrackerRunLabel,
  buildReviewEffortLabel,
  buildRoleLabel,
  buildRunTeamKey,
  buildTeamHoverLabel,
  buildUploadedDocumentRecord,
  deriveDashboardMetrics,
  findIssueById,
  formatEventTime,
  getDocumentsForRepository,
  getRunChannelTone,
  mergeDashboardBlockedReasonLists,
  missionControlDashboardRisks,
  missionControlDashboardStatuses,
  reviewerRoles,
} from './lib/appHelpers';
import {
  connectCursor,
  clearSessionToken,
  connectGitHub,
  connectGitHubCopilot,
  connectJira,
  connectLinear,
  createTask,
  enrichIntakeField,
  identifyRepositoryForIssue,
  fetchCurrentUser,
  fetchRunDetail,
  hasSessionToken,
  signOut,
} from './lib/api';
import type {
  CurrentUser,
  IntakeEnrichField,
  IntakeEnrichRequest,
  RiskLevel,
  RunSummary,
  RunStatus,
  TaskCreateRequest,
  UploadedDocumentRecord,
} from './types/controlPane';


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
 * Shows the live mission control dashboard.
 */
function DashboardPage() {
  const {
    filteredTeamRuns,
    isReviewEffortsLoading,
    isSuggestionsLoading,
    lobbyRuns,
    missionFilterFormId,
    missionOwnerOptions,
    missionOwnerToken,
    missionRepo,
    missionRepoOptions,
    missionRisk,
    missionSearch,
    missionStatus,
    query,
    reviewEffortsByRunId,
    reviewEffortsError,
    selectedTeam,
    selectedTeamRuns,
    setMissionOwnerToken,
    setMissionRepo,
    setMissionRisk,
    setMissionSearch,
    setMissionStatus,
    setSelectedTeamKey,
    suggestedActions,
    suggestionsError,
    teamGroups,
  } = useMissionControlDashboard();
  if (query.isLoading) {
    // Render a lightweight loading state while dashboard data is fetched.
    return <LoadingState message="Loading ShipControl data..." />;
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

  // Build the server rail from owner-backed team groups.
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
    ? 'No runs match the current channel filters. Clear or adjust filters to see channels again.'
    : 'No run channels are available for this team.';

  // Surface the operational view as a delivery cockpit with team lanes and a selected run room.
  return (
    <div className="page-grid">
      <section className="hero-panel discord-hero-panel">
        <div>
          <p className="eyebrow">Live shipping operations</p>
          <h3>Pick a team lane, filter active runs, then open the run room for evidence and review.</h3>
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
            lane filters
          </p>
          <div className="mission-control-filter-bar-actions">
            <Link className="primary-button link-button" to="/intake">
              Launch shipment
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

      <section className="discord-workspace" aria-label="ShipControl run workspace">
        <div className="server-rail" aria-label="team lanes">
          {teamServerButtons.length > 0 ? teamServerButtons : <span className="server-empty-state">SC</span>}
        </div>

        <div className="channel-panel" aria-label="Run channels">
          <div className="channel-panel-header">
            <p className="eyebrow">team lane</p>
            <h3>{selectedTeam?.label ?? 'No team selected'}</h3>
            <p className="subtle-copy" role="status">
              Showing {filteredTeamRuns.length} of {selectedTeamRuns.length} active runs
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
              <h3>No runs match the current channel filters.</h3>
              <p className="muted-copy">Clear filters or pick another team lane to restore the preview card.</p>
              {hasActiveMissionFilters ? (
                <button className="primary-button" onClick={handleClearMissionFilters} type="button">
                  Clear filters
                </button>
              ) : null}
            </div>
          ) : (
            <div className="run-room-card">
              <p className="eyebrow">No runs</p>
              <h3>No run channels are available yet.</h3>
              <p className="muted-copy">New delegated runs will appear here as active shipping lanes.</p>
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
  const navigate = useNavigate();
  const {
    acceptanceCriteria,
    enrichError,
    enrichingField,
    enrichNotice,
    executionMode,
    identifyError,
    identifyNotice,
    isIdentifyingRepo,
    isSubmitting,
    issueScopingQuery,
    prompt,
    query,
    selectedIssueId,
    selectedRepoName,
    setAcceptanceCriteria,
    setEnrichError,
    setEnrichingField,
    setEnrichNotice,
    setExecutionMode,
    setIdentifyError,
    setIdentifyNotice,
    setIsIdentifyingRepo,
    setIsSubmitting,
    setPrompt,
    setSelectedIssueId,
    setSelectedRepoName,
    setSubmitError,
    setTitle,
    setUploadError,
    setUploadedDocuments,
    submitError,
    title,
    uploadError,
    uploadedDocuments,
  } = useIntakeForm();
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
 * Renders the tech-lead delegation brief: repo context, issue narrative, criteria, and agent instructions.
 */
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
 * Renders the reviewer decision controls for a task and persists outcomes through the backend.
 */
/**
 * Shows the integration management view.
 */
function IntegrationsPage(props: { currentUser: CurrentUser }) {
  const {
    activeSetupId,
    cursorForm,
    githubCopilotForm,
    githubForm,
    jiraForm,
    linearForm,
    mutationError,
    mutationSuccess,
    query,
    setActiveSetupId,
    setCursorForm,
    setGithubCopilotForm,
    setGithubForm,
    setJiraForm,
    setLinearForm,
    setMutationError,
    setMutationSuccess,
    setRefreshKey,
  } = useIntegrationForms();
  const integrationCards: ReactNode[] = [];
  const settingsSectionLinks: Array<{ id: string; label: string }> = [
    { id: 'provider-status', label: 'Provider status' },
    { id: 'github-settings', label: 'GitHub setup' },
    { id: 'linear-settings', label: 'Linear setup' },
    { id: 'jira-settings', label: 'Jira setup' },
    { id: 'cursor-settings', label: 'Cursor setup' },
    { id: 'github-copilot-settings', label: 'Copilot setup' },
  ];

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


export {
  App,
  DashboardPage,
  IntegrationsPage,
  TaskDetailPage,
  WorkIntakePage,
};

export default App;
