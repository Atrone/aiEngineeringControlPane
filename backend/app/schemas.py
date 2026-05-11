"""Request models for task, run, and approval operations."""

from typing import List, Optional

from pydantic import BaseModel, Field


class UploadedDocumentRequest(BaseModel):
    """Defines a user-uploaded repo document sent from the intake form."""

    id: str
    title: str
    path: str
    source: str = "uploaded_repo_document"
    updated_at: str = Field(default="", alias="updatedAt")
    content: str = ""

    model_config = {"populate_by_name": True}


class TaskCreateRequest(BaseModel):
    """Defines the payload used to create a new AI work item."""

    issue_id: Optional[str] = Field(default=None, alias="issueId")
    repo_name: str = Field(alias="repoName")
    title: str
    prompt: str
    acceptance_criteria: str = Field(alias="acceptanceCriteria")
    document_ids: List[str] = Field(default_factory=list, alias="documentIds")
    uploaded_documents: List[UploadedDocumentRequest] = Field(
        default_factory=list,
        alias="uploadedDocuments",
    )
    execution_mode: str = Field(default="implement", alias="executionMode")

    model_config = {"populate_by_name": True}


class RunCreateRequest(BaseModel):
    """Defines the payload used to create or restart an agent run."""

    task_id: str = Field(alias="taskId")
    agent_name: str = Field(default="impl-agent", alias="agentName")
    execution_mode: str = Field(default="implement", alias="executionMode")


class ApprovalDecisionRequest(BaseModel):
    """Defines the payload used to record an approval decision."""

    run_id: str = Field(alias="runId")
    decision: str
    notes: str = ""


class SignInRequest(BaseModel):
    """Defines the payload used to create a guided sign-in session."""

    name: str
    email: str
    role: str
    team_id: str = Field(default="", alias="teamId")

    model_config = {"populate_by_name": True}


class GoogleAuthExchangeRequest(BaseModel):
    """Defines the payload used to exchange a Google callback code for a session."""

    code: str
    team_id: str = Field(default="", alias="teamId")

    model_config = {"populate_by_name": True}


class GitHubConnectRequest(BaseModel):
    """Defines the payload used to connect GitHub during guided setup."""

    owner: str
    repositories: str
    token: str = ""


class LinearConnectRequest(BaseModel):
    """Defines the payload used to connect Linear during guided setup."""

    api_key: str = Field(alias="apiKey")
    team_id: str = Field(default="", alias="teamId")


class JiraConnectRequest(BaseModel):
    """Defines the payload used to connect Jira Cloud during guided setup."""

    site_url: str = Field(alias="siteUrl")
    email: str
    api_token: str = Field(alias="apiToken")
    project_key: str = Field(default="", alias="projectKey")


class CursorConnectRequest(BaseModel):
    """Defines the payload used to connect Cursor Cloud Agents during guided setup."""

    api_key: str = Field(alias="apiKey")
    model: str = "default"


class GitHubCopilotConnectRequest(BaseModel):
    """Defines the payload used to connect GitHub Copilot cloud agent setup."""

    token: str
    model: str = ""
    custom_agent: str = Field(default="", alias="customAgent")

    model_config = {"populate_by_name": True}


class DocsConnectRequest(BaseModel):
    """Defines the payload used to connect a docs directory during guided setup."""

    docs_directory: str = Field(alias="docsDirectory")


class IntakeEnrichRequest(BaseModel):
    """Defines the payload used to refine a work intake field using repo docs."""

    field: str
    value: str = ""
    title: str = ""
    prompt: str = ""
    acceptance_criteria: str = Field(default="", alias="acceptanceCriteria")
    repo_name: str = Field(default="", alias="repoName")
    execution_mode: str = Field(default="implement", alias="executionMode")
    issue_id: Optional[str] = Field(default=None, alias="issueId")
    uploaded_documents: List[UploadedDocumentRequest] = Field(
        default_factory=list,
        alias="uploadedDocuments",
    )

    model_config = {"populate_by_name": True}


class IntakeIdentifyRepositoryRequest(BaseModel):
    """Defines the payload used to ask OpenAI which repository best fits an issue."""

    issue_id: str = Field(alias="issueId")

    model_config = {"populate_by_name": True}


class IntakeIssueScopingRequest(BaseModel):
    """Defines the payload used to ask OpenAI which issues are well scoped."""

    issue_ids: List[str] = Field(default_factory=list, alias="issueIds")

    model_config = {"populate_by_name": True}


class DashboardSuggestedActionsRequest(BaseModel):
    """Defines the payload used to ask OpenAI for dashboard suggested next actions.

    The caller passes the run IDs currently shown in the dashboard's
    'Active and recent runs' container so the suggestions stay consistent with
    what the operator is looking at.
    """

    run_ids: List[str] = Field(default_factory=list, alias="runIds")

    model_config = {"populate_by_name": True}


class DashboardReviewEffortsRequest(BaseModel):
    """Defines the payload used to ask OpenAI for lobby review-effort guesses.

    The caller passes the run IDs currently visible in the selected lobby so
    OpenAI can estimate human review effort from each run's PR summary.
    """

    run_ids: List[str] = Field(default_factory=list, alias="runIds")

    model_config = {"populate_by_name": True}
