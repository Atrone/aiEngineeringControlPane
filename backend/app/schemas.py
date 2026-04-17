"""Request models for task, run, and approval operations."""

from typing import List, Optional

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    """Defines the payload used to create a new AI work item."""

    issue_id: Optional[str] = Field(default=None, alias="issueId")
    repo_name: str = Field(alias="repoName")
    title: str
    prompt: str
    acceptance_criteria: str = Field(alias="acceptanceCriteria")
    document_ids: List[str] = Field(default_factory=list, alias="documentIds")
    execution_mode: str = Field(default="implement", alias="executionMode")


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


class GoogleAuthExchangeRequest(BaseModel):
    """Defines the payload used to exchange a Google callback code for a session."""

    code: str


class GitHubConnectRequest(BaseModel):
    """Defines the payload used to connect GitHub during guided setup."""

    owner: str
    repositories: str
    token: str = ""


class LinearConnectRequest(BaseModel):
    """Defines the payload used to connect Linear during guided setup."""

    api_key: str = Field(alias="apiKey")
    team_id: str = Field(default="", alias="teamId")


class CursorConnectRequest(BaseModel):
    """Defines the payload used to connect Cursor Cloud Agents during guided setup."""

    api_key: str = Field(alias="apiKey")
    model: str = "default"


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

    model_config = {"populate_by_name": True}


class IntakeIdentifyRepositoryRequest(BaseModel):
    """Defines the payload used to ask OpenAI which repository best fits an issue."""

    issue_id: str = Field(alias="issueId")

    model_config = {"populate_by_name": True}
