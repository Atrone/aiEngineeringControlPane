import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  RunLobbyPullRequestPreview,
  TaskAgentDelegationBriefPanelBody,
  TaskDecisionPanelBody,
  TaskImplementationPackagePanelBody,
} from './TaskPanels';
import * as api from '../../lib/api';
import { createRunFixture } from '../../test/fixtures';

vi.mock('../../lib/api', () => ({
  createApprovalDecision: vi.fn(),
}));

describe('TaskPanels component functions', () => {
  it('RunLobbyPullRequestPreview renders pull-request content for review-ready runs', () => {
    const run = createRunFixture();

    render(<RunLobbyPullRequestPreview run={run} />);

    expect(screen.getByText('Build dashboard PR')).toBeInTheDocument();
  });

  it('TaskDecisionPanelBody handleNotesChange and handleDecisionSubmit persist reviewer input', async () => {
    const onRunUpdated = vi.fn();
    const run = createRunFixture({ cloudAgent: undefined, pullRequest: undefined });
    vi.mocked(api.createApprovalDecision).mockResolvedValue(createRunFixture({ status: 'Approved' }));

    render(<TaskDecisionPanelBody onRunUpdated={onRunUpdated} run={run} />);

    fireEvent.change(screen.getByLabelText('Reviewer notes'), { target: { value: 'Looks good.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(api.createApprovalDecision).toHaveBeenCalledWith({ runId: 'run-1', decision: 'approve', notes: 'Looks good.' });
    });
  });

  it('TaskImplementationPackagePanelBody buildTraceabilitySnapshotItems and renderLinkGroup show traceability details', () => {
    const run = createRunFixture({
      traceability: {
        ticket: 'ACP-1',
        issueProvider: 'linear',
        issueStatusAtLaunch: 'In Progress',
        runStatus: 'Review',
        pullRequestStatus: 'open',
        pullRequestSource: 'github',
        capturedEvidenceCount: 3,
        latestDecision: 'approve',
        preservedFromInProgress: true,
      },
    });

    render(<TaskImplementationPackagePanelBody run={run} />);

    expect(screen.getByText('Traceability snapshot')).toBeInTheDocument();
    expect(screen.getByText(/Evidence entries captured: 3/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Issue traceability link 1' })).toBeInTheDocument();
  });

  it('TaskAgentDelegationBriefPanelBody renders delegation inputs from the run payload', () => {
    const run = createRunFixture({
      taskPrompt: 'Implement the dashboard card.',
      acceptanceCriteria: '- [ ] Add tests',
    });

    render(<TaskAgentDelegationBriefPanelBody run={run} />);

    expect(screen.getByText('Implement the dashboard card.')).toBeInTheDocument();
    expect(screen.getByText('- [ ] Add tests')).toBeInTheDocument();
  });
});
