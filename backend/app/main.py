"""FastAPI entrypoint for the AI Control Pane demo backend."""

from typing import Any, Dict, Sequence, Tuple

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth import SessionRecord
from app.auth import build_current_user
from app.auth import build_effective_settings
from app.auth import build_request_headers
from app.auth import connect_docs
from app.auth import connect_github
from app.auth import connect_linear
from app.auth import create_session
from app.auth import require_role
from app.auth import require_session
from app.auth import sign_out_session
from app.config import get_settings
from app.schemas import ApprovalDecisionRequest
from app.schemas import DocsConnectRequest
from app.schemas import GitHubConnectRequest
from app.schemas import LinearConnectRequest
from app.schemas import RunCreateRequest
from app.schemas import SignInRequest
from app.schemas import TaskCreateRequest
from app.state import create_run
from app.state import create_task
from app.state import get_approval_payload
from app.state import get_dashboard_payload
from app.state import get_integrations_payload
from app.state import get_intake_payload
from app.state import get_policy_payload
from app.state import get_run_detail
from app.state import record_approval


app = FastAPI(
    title="AI Control Pane API",
    description="Backend foundation for the AI Control Pane demo application.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings = get_settings()


def _authorized_request(request: Request) -> Tuple[Any, Dict[str, str], SessionRecord]:
    """Resolves the signed-in session and builds the effective request context."""

    session = require_session(request.headers)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the settings, normalized headers, and session for downstream handlers.
    return effective_settings, request_headers, session


def _authorized_request_with_roles(
    request: Request,
    allowed_roles: Sequence[str],
) -> Tuple[Any, Dict[str, str], SessionRecord]:
    """Resolves the signed-in session and enforces a role gate."""

    effective_settings, request_headers, session = _authorized_request(request)
    require_role(session, allowed_roles)

    # Return the authorized request context after the role check passes.
    return effective_settings, request_headers, session


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Creates a lightweight health response for local development checks."""

    # Return a predictable status payload for local verification and future frontend wiring.
    return {"status": "ok", "service": "ai-control-pane-api"}


@app.post("/auth/sign-in")
@app.post("/api/auth/sign-in")
def post_sign_in(payload: SignInRequest) -> Dict[str, Any]:
    """Creates a guided sign-in session for the demo application."""

    # Create the in-memory session used by the frontend auth shell.
    return create_session(payload.name, payload.email, payload.role)


@app.post("/auth/sign-out")
@app.post("/api/auth/sign-out")
def post_sign_out(request: Request) -> Dict[str, str]:
    """Deletes the current guided sign-in session."""

    # Remove the in-memory session token when the caller signs out.
    sign_out_session(request.headers)

    # Return a small confirmation payload for the frontend.
    return {"status": "signed_out"}


@app.get("/dashboard")
@app.get("/api/dashboard")
def get_dashboard(request: Request) -> Dict[str, Any]:
    """Returns the dashboard payload for the mission control view."""

    effective_settings, request_headers, _ = _authorized_request(request)

    # Return the high-level metrics and active run feed for the dashboard.
    return get_dashboard_payload(effective_settings, request_headers)


@app.get("/runs/{run_id}")
@app.get("/api/runs/{run_id}")
def read_run_detail(
    run_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Returns the task detail payload for a specific run."""

    effective_settings, request_headers, _ = _authorized_request(request)

    try:
        # Look up the requested mock run and return the full evidence pack.
        return get_run_detail(run_id, effective_settings, request_headers)
    except KeyError as error:
        # Translate a missing run into an HTTP-friendly not found response.
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found.") from error


@app.get("/approvals")
@app.get("/api/approvals")
def get_approvals(request: Request) -> Dict[str, Any]:
    """Returns the approval inbox payload for review-ready runs."""

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin", "tech_lead"))

    # Return the queue summary and pending approval items for the inbox.
    return get_approval_payload(effective_settings, request_headers)


@app.get("/policies")
@app.get("/api/policies")
@app.get("/policies/{scope}")
@app.get("/api/policies/{scope}")
def get_policies(request: Request, scope: str = "web-app") -> Dict[str, Any]:
    """Returns the active policy pack for the UI demo."""

    _authorized_request_with_roles(request, ("admin", "tech_lead"))

    # Return the readable policy rules that drive the control pane UI.
    return get_policy_payload(scope)


@app.get("/me")
@app.get("/api/me")
def get_current_user(request: Request) -> Dict[str, Any]:
    """Returns the resolved current user identity for approvals and audit trails."""

    _, _, session = _authorized_request(request)

    # Return the signed-in user identity for the frontend auth shell.
    return build_current_user(session)


@app.get("/integrations")
@app.get("/api/integrations")
def get_integrations(request: Request) -> Dict[str, Any]:
    """Returns the provider integration status payload."""

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin", "tech_lead"))

    # Return the current integration status summary for the management view.
    return get_integrations_payload(effective_settings, request_headers)


@app.get("/intake")
@app.get("/api/intake")
def get_intake(request: Request) -> Dict[str, Any]:
    """Returns the integrated intake payload for task creation."""

    effective_settings, request_headers, _ = _authorized_request(request)

    # Return the repositories, issues, docs, and user context for task intake.
    return get_intake_payload(effective_settings, request_headers)


@app.post("/tasks")
@app.post("/api/tasks")
def post_task(
    payload: TaskCreateRequest,
    request: Request,
) -> Dict[str, Any]:
    """Creates a new AI work item from the integrated intake flow."""

    effective_settings, request_headers, _ = _authorized_request(request)

    # Create a new task record that ties issue, repo, docs, and user identity together.
    return create_task(effective_settings, request_headers, payload.model_dump(by_alias=True))


@app.post("/runs")
@app.post("/api/runs")
def post_run(payload: RunCreateRequest, request: Request) -> Dict[str, Any]:
    """Creates or restarts an agent run for an existing task."""

    _authorized_request(request)

    try:
        # Start or restart the selected run using the simplified in-memory workflow.
        return create_run(payload.model_dump(by_alias=True))
    except KeyError as error:
        # Translate missing task IDs into a clear client-facing error response.
        raise HTTPException(status_code=404, detail=f"Task '{payload.task_id}' was not found.") from error


@app.post("/approvals")
@app.post("/api/approvals")
def post_approval(
    payload: ApprovalDecisionRequest,
    request: Request,
) -> Dict[str, Any]:
    """Records an approval decision and attributes it to the current user."""

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin", "tech_lead"))

    try:
        # Record the approval decision and update the run state in the in-memory store.
        return record_approval(effective_settings, request_headers, payload.model_dump(by_alias=True))
    except KeyError as error:
        # Translate missing run IDs into a clear client-facing error response.
        raise HTTPException(status_code=404, detail=f"Run '{payload.run_id}' was not found.") from error


@app.post("/integrations/github/connect")
@app.post("/api/integrations/github/connect")
def post_github_connect(payload: GitHubConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the GitHub connection selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin", "tech_lead"))
    connect_github(session, payload.owner, payload.repositories, payload.token)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the GitHub setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/linear/connect")
@app.post("/api/integrations/linear/connect")
def post_linear_connect(payload: LinearConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the Linear connection selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin", "tech_lead"))
    connect_linear(session, payload.api_key, payload.team_id)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the Linear setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/docs/connect")
@app.post("/api/integrations/docs/connect")
def post_docs_connect(payload: DocsConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the docs directory selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin", "tech_lead"))
    connect_docs(session, payload.docs_directory)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the docs setup.
    return get_integrations_payload(effective_settings, request_headers)
