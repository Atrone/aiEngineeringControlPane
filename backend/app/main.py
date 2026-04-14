"""FastAPI entrypoint for the AI Control Pane demo backend."""

from typing import Any, Dict

from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.schemas import ApprovalDecisionRequest
from app.schemas import RunCreateRequest
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


def _request_headers(x_demo_user_email: str = "", x_demo_user_name: str = "", x_demo_user_role: str = "") -> Dict[str, str]:
    """Builds the header map passed into the integration and identity layer."""

    headers: Dict[str, str] = {}

    if x_demo_user_email:
        # Forward the optional demo user email into the auth resolver.
        headers["x-demo-user-email"] = x_demo_user_email

    if x_demo_user_name:
        # Forward the optional demo user name into the auth resolver.
        headers["x-demo-user-name"] = x_demo_user_name

    if x_demo_user_role:
        # Forward the optional demo user role into the auth resolver.
        headers["x-demo-user-role"] = x_demo_user_role

    # Return the normalized header map for downstream identity resolution.
    return headers


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Creates a lightweight health response for local development checks."""

    # Return a predictable status payload for local verification and future frontend wiring.
    return {"status": "ok", "service": "ai-control-pane-api"}


@app.get("/dashboard")
@app.get("/api/dashboard")
def get_dashboard(
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the dashboard payload for the mission control view."""

    # Return the high-level metrics and active run feed for the dashboard.
    return get_dashboard_payload(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
    )


@app.get("/runs/{run_id}")
@app.get("/api/runs/{run_id}")
def read_run_detail(
    run_id: str,
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the task detail payload for a specific run."""

    try:
        # Look up the requested mock run and return the full evidence pack.
        return get_run_detail(
            run_id,
            settings,
            _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
        )
    except KeyError as error:
        # Translate a missing run into an HTTP-friendly not found response.
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found.") from error


@app.get("/approvals")
@app.get("/api/approvals")
def get_approvals(
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the approval inbox payload for review-ready runs."""

    # Return the queue summary and pending approval items for the inbox.
    return get_approval_payload(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
    )


@app.get("/policies")
@app.get("/api/policies")
@app.get("/policies/{scope}")
@app.get("/api/policies/{scope}")
def get_policies(scope: str = "web-app") -> Dict[str, Any]:
    """Returns the active policy pack for the UI demo."""

    # Return the readable policy rules that drive the control pane UI.
    return get_policy_payload(scope)


@app.get("/me")
@app.get("/api/me")
def get_current_user(
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the resolved current user identity for approvals and audit trails."""

    # Return the user identity resolved from headers or configured defaults.
    return get_intake_payload(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
    )["currentUser"]


@app.get("/integrations")
@app.get("/api/integrations")
def get_integrations(
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the provider integration status payload."""

    # Return the current integration status summary for the management view.
    return get_integrations_payload(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
    )


@app.get("/intake")
@app.get("/api/intake")
def get_intake(
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Returns the integrated intake payload for task creation."""

    # Return the repositories, issues, docs, and user context for task intake.
    return get_intake_payload(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
    )


@app.post("/tasks")
@app.post("/api/tasks")
def post_task(
    payload: TaskCreateRequest,
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Creates a new AI work item from the integrated intake flow."""

    # Create a new task record that ties issue, repo, docs, and user identity together.
    return create_task(
        settings,
        _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
        payload.model_dump(by_alias=True),
    )


@app.post("/runs")
@app.post("/api/runs")
def post_run(payload: RunCreateRequest) -> Dict[str, Any]:
    """Creates or restarts an agent run for an existing task."""

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
    x_demo_user_email: str = Header(default=""),
    x_demo_user_name: str = Header(default=""),
    x_demo_user_role: str = Header(default=""),
) -> Dict[str, Any]:
    """Records an approval decision and attributes it to the current user."""

    try:
        # Record the approval decision and update the run state in the in-memory store.
        return record_approval(
            settings,
            _request_headers(x_demo_user_email, x_demo_user_name, x_demo_user_role),
            payload.model_dump(by_alias=True),
        )
    except KeyError as error:
        # Translate missing run IDs into a clear client-facing error response.
        raise HTTPException(status_code=404, detail=f"Run '{payload.run_id}' was not found.") from error
