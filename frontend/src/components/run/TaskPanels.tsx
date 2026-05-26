import type { ChangeEvent, FormEvent, ReactNode } from 'react';
import { useState } from 'react';
import { createApprovalDecision } from '../../lib/api';
import {
  buildApprovalDecisionLabel,
  buildApprovalSourceLabel,
  buildPullRequestStateLabel,
  buildRunTraceabilityGraph,
  buildTraceabilityNodeClassName,
  buildTraceabilityStatusLabel,
  collectTaskDetailReferenceLinks,
  formatEventTime,
  formatExecutionModeLabel,
  resolveCurrentPullRequestUrl,
  resolveRunRepositoryUrl,
  shouldShowRunLobbyPullRequest,
} from '../../lib/appHelpers';
import type { RunSummary } from '../../types/controlPane';
import { DetailList } from '../ui';

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
 * Renders task-specific delegation inputs sourced from intake and integration payloads.
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
                -
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
        stay within allowed commands and paths described in Settings - matching the control pane agent interaction
        guidelines.
      </p>
    </div>
  );
}

export {
  ApprovalHistoryList,
  PullRequestPanelBody,
  RunLobbyPullRequestPreview,
  RunTraceabilityGraphPanelBody,
  TaskAgentDelegationBriefPanelBody,
  TaskDecisionPanelBody,
  TaskImplementationPackagePanelBody,
};
