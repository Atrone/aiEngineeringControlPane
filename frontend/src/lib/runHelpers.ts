import type { RunEvidenceEntry, RunEvidenceTabs, RunLogEntry, RunSummary, RunTimelineEntry } from '../types/controlPane';

type EvidenceTabId = keyof RunEvidenceTabs;
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

export type { EvidenceTabId, RunTraceabilityNode, TraceabilityNodeStatus };

export {
  buildApprovalDecisionLabel,
  buildApprovalSourceLabel,
  buildEvidenceStatusClassName,
  buildEvidenceTabLabel,
  buildLogEntryClassName,
  buildPullRequestStateLabel,
  buildRunTraceabilityGraph,
  buildTimelineEntryClassName,
  buildTraceabilityNodeClassName,
  buildTraceabilityStatusLabel,
  collectTaskDetailReferenceLinks,
  extractUrlsFromText,
  formatEventTime,
  resolveCurrentPullRequestUrl,
  resolvePullRequestArtifactUrl,
  resolveRunBranchUrl,
  resolveRunRepositoryUrl,
  resolveRunValidationUrl,
};
