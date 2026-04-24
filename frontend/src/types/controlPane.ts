export type RunStatus = 'Running' | 'Review' | 'Approved' | 'Blocked' | 'Retry' | 'Merged';

export type PullRequestState = 'draft' | 'open' | 'approved' | 'merged' | 'closed' | 'ready_for_review';

export type ApprovalHistorySource = 'reviewer' | 'github' | 'simulated';
export type RiskLevel = 'Low' | 'Medium' | 'High';
export type UserRole = 'admin';

export type CurrentUser = {
  name: string;
  email: string;
  role: UserRole;
  provider: string;
};

export type AuthSession = {
  sessionToken: string;
  currentUser: CurrentUser;
};

export type AuthConfig = {
  googleSsoEnabled: boolean;
  guidedSignInEnabled: boolean;
};

export type SignInRequest = {
  name: string;
  email: string;
  role: UserRole;
};

export type GoogleAuthExchangeRequest = {
  code: string;
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

export type UploadedDocumentRecord = DocumentRecord & {
  content: string;
};

export type IntegrationStatus = {
  id: string;
  name: string;
  mode: 'live' | 'mock';
  connected: boolean;
  capabilities: string[];
  configured: boolean;
  details: string;
  requiredRole: UserRole;
  recommendedAction: string;
  connection?: {
    label: string;
    values: Record<string, string>;
  } | null;
  checkedAt: string;
};

export type CloudAgentRecord = {
  id: string;
  name?: string;
  status: string;
  createdAt?: string;
  summary?: string;
  source?: {
    repository?: string;
    ref?: string;
  };
  target?: {
    branchName?: string;
    url?: string;
    prUrl?: string;
    autoCreatePr?: boolean;
    openAsCursorGithubApp?: boolean;
    skipReviewerRequest?: boolean;
  };
};

export type RunEvidence = {
  diff: string[];
  tests: string[];
  commands: string[];
  rationale: string[];
};

export type RunTimelineStatus = 'complete' | 'active' | 'pending';

export type RunTimelineEntry = {
  id: string;
  title: string;
  detail: string;
  timestamp: string;
  status: RunTimelineStatus;
};

export type RunLogLevel = 'info' | 'success' | 'warning' | 'error';

export type RunLogEntry = {
  id: string;
  timestamp: string;
  level: RunLogLevel;
  source: string;
  message: string;
};

export type RunEvidenceStatus = 'captured' | 'running' | 'blocked';

export type RunEvidenceEntry = {
  id: string;
  timestamp: string;
  summary: string;
  detail: string;
  status: RunEvidenceStatus;
};

export type RunEvidenceTabs = {
  diff: RunEvidenceEntry[];
  tests: RunEvidenceEntry[];
  rationale: RunEvidenceEntry[];
};

export type RunLiveView = {
  isLive: boolean;
  statusLabel: string;
  lastUpdatedAt: string;
  timeline: RunTimelineEntry[];
  logs: RunLogEntry[];
  evidenceTabs: RunEvidenceTabs;
};

export type ApprovalHistoryEntry = {
  decision: string;
  source?: ApprovalHistorySource;
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
    state?: PullRequestState;
    url: string;
    merged?: boolean;
    mergedAt?: string | null;
    approved?: boolean;
    approvedAt?: string | null;
    approvedBy?: string | null;
    source?: 'github' | 'simulated' | 'skipped';
  };
  ci?: {
    workflow: string;
    status: string;
    summary: string;
  };
  documents?: DocumentRecord[];
  requestedBy?: CurrentUser;
  approvalHistory?: ApprovalHistoryEntry[];
  cloudAgent?: CloudAgentRecord;
  liveView?: RunLiveView;
};

export type ApprovalItem = {
  runId: string;
  waitingTime: string;
  outcomeNeeded: string;
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
  uploadedDocuments: UploadedDocumentRecord[];
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

export type GitHubConnectRequest = {
  owner: string;
  repositories: string;
  token: string;
};

export type LinearConnectRequest = {
  apiKey: string;
  teamId: string;
};

export type JiraConnectRequest = {
  siteUrl: string;
  email: string;
  apiToken: string;
  projectKey: string;
};

export type CursorConnectRequest = {
  apiKey: string;
  model: string;
};

export type IntakeEnrichField = 'title' | 'prompt' | 'acceptanceCriteria';

export type IntakeEnrichRequest = {
  field: IntakeEnrichField;
  value: string;
  title: string;
  prompt: string;
  acceptanceCriteria: string;
  repoName: string;
  executionMode: string;
  issueId?: string;
  uploadedDocuments: UploadedDocumentRecord[];
};

export type IntakeEnrichResponse = {
  field: string;
  value: string;
  model: string;
  docsConsidered: boolean;
};

export type IntakeIdentifyRepositoryRequest = {
  issueId: string;
};

export type IntakeIssueScopingRequest = {
  issueIds: string[];
};

export type IntakeIssueScopingResponse = {
  wellScopedIssueIds: string[];
  poorlyScopedIssueIds: string[];
  model: string;
  issueCount: number;
};

export type IntakeIdentifyRepositoryResponse = {
  repoName: string;
  repoFullName: string;
  confidence: number | null;
  reasoning: string;
  model: string;
  docsConsidered: boolean;
};

export type DashboardSuggestedActionsRequest = {
  runIds: string[];
};

export type DashboardSuggestedActionsResponse = {
  suggestedActions: string[];
  model: string;
  runCount: number;
};
