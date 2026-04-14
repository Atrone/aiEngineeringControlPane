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
