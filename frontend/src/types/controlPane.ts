export type RunStatus = 'Running' | 'Review' | 'Blocked' | 'Retry' | 'Merged';
export type RiskLevel = 'Low' | 'Medium' | 'High';

export type CurrentUser = {
  name: string;
  email: string;
  role: string;
  provider: string;
};

export type RepositoryRecord = {
  id: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  private: boolean;
  provider: string;
  url: string;
};

export type IssueRecord = {
  id: string;
  ticket: string;
  title: string;
  description: string;
  priority: string;
  status: string;
  url: string;
  assignee: {
    name?: string;
    email?: string;
  };
  provider: string;
};

export type DocumentRecord = {
  id: string;
  title: string;
  path: string;
  source: string;
  updatedAt: string;
};

export type IntegrationStatus = {
  id: string;
  name: string;
  mode: 'live' | 'mock';
  connected: boolean;
  capabilities: string[];
  configured: boolean;
  details: string;
  checkedAt: string;
};

export type RunEvidence = {
  diff: string[];
  tests: string[];
  commands: string[];
  rationale: string[];
};

export type ApprovalHistoryEntry = {
  decision: string;
  notes: string;
  actor: CurrentUser;
  timestamp: string;
};

export type RunSummary = {
  id: string;
  ticket: string;
  title: string;
  repo: string;
  branch: string;
  owner: string;
  agent: string;
  runtime: string;
  cost: string;
  status: RunStatus;
  risk: RiskLevel;
  currentStep: string;
  summary: string;
  evidence: RunEvidence;
  blockers: string[];
  issue?: IssueRecord;
  pullRequest?: {
    number: string;
    status: string;
    url: string;
  };
  ci?: {
    workflow: string;
    status: string;
    summary: string;
  };
  documents?: DocumentRecord[];
  requestedBy?: CurrentUser;
  approvalHistory?: ApprovalHistoryEntry[];
};

export type ApprovalItem = {
  runId: string;
  waitingTime: string;
  outcomeNeeded: string;
};

export type PolicyRule = {
  name: string;
  value: string;
};

export type DashboardMetric = {
  label: string;
  value: string;
  hint: string;
};

export type DashboardPayload = {
  metrics: DashboardMetric[];
  runs: RunSummary[];
  blockedReasons: string[];
  suggestedActions: string[];
  integrationStatuses: IntegrationStatus[];
  currentUser: CurrentUser;
};

export type ApprovalPayload = {
  summary: {
    queueSize: number;
    highRisk: number;
    slaRisk: number;
    reviewReady: number;
  };
  queue: ApprovalItem[];
  runs: RunSummary[];
  currentUser: CurrentUser;
};

export type PolicyPayload = {
  scope: string;
  version: string;
  rules: PolicyRule[];
};

export type IntakePayload = {
  repositories: RepositoryRecord[];
  issues: IssueRecord[];
  documents: DocumentRecord[];
  currentUser: CurrentUser;
  integrationStatuses: IntegrationStatus[];
};

export type IntegrationsPayload = {
  statuses: IntegrationStatus[];
  currentUser: CurrentUser;
};

export type TaskCreateRequest = {
  issueId?: string;
  repoName: string;
  title: string;
  prompt: string;
  acceptanceCriteria: string;
  documentIds: string[];
  executionMode: string;
};

export type RunCreateRequest = {
  taskId: string;
  agentName: string;
  executionMode: string;
};

export type ApprovalDecisionRequest = {
  runId: string;
  decision: string;
  notes: string;
};
