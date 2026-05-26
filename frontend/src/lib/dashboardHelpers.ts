import type { DashboardMetric, ReviewEffortEstimate, RiskLevel, RunStatus, RunSummary } from '../types/controlPane';

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
 * Builds the team server hover summary shown in the rail.
 */
function buildTeamHoverLabel(group: RunTeamGroup): string {
  const runCount = group.runs.length;

  // Summarize the channel state mix so the server hover carries operational signal.
  return `${group.label}: ${runCount} run${runCount === 1 ? '' : 's'} · ${group.activeCount} active · ${group.blockedCount} blocked · ${group.mergedCount} merged`;
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

export type { RunChannelTone, RunTeamGroup };

export {
  buildIssueTrackerRunLabel,
  buildReviewEffortLabel,
  buildRunTeamGroups,
  buildRunTeamKey,
  buildTeamHoverLabel,
  buildTeamInitials,
  collectBlockerReasons,
  deriveDashboardMetrics,
  formatExecutionModeLabel,
  formatReviewEffortValue,
  getRunChannelTone,
  isActionableBlocker,
  isIssueTrackerProvider,
  isIssueTrackerRun,
  mergeDashboardBlockedReasonLists,
  missionControlDashboardRisks,
  missionControlDashboardStatuses,
  parseRuntimeSeconds,
  shouldShowRunLobbyPullRequest,
};
