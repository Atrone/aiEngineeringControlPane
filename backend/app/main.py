"""FastAPI entrypoint for the AI Control Pane demo backend."""

import base64
import json
from typing import Any, Dict, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.auth import SessionRecord
from app.auth import build_current_user
from app.auth import build_effective_settings
from app.auth import build_request_headers
from app.auth import consume_google_exchange_code
from app.auth import consume_google_oauth_state
from app.auth import connect_cursor
from app.auth import connect_docs
from app.auth import connect_github
from app.auth import connect_jira
from app.auth import connect_linear
from app.auth import create_google_oauth_state
from app.auth import create_session
from app.auth import is_google_sso_enabled
from app.auth import require_role
from app.auth import require_session
from app.auth import store_google_exchange_code
from app.auth import validate_google_identity
from app.auth import sign_out_session
from app.config import get_settings
from app.schemas import ApprovalDecisionRequest
from app.schemas import CursorConnectRequest
from app.schemas import DashboardSuggestedActionsRequest
from app.schemas import DocsConnectRequest
from app.schemas import GitHubConnectRequest
from app.schemas import GoogleAuthExchangeRequest
from app.schemas import IntakeEnrichRequest
from app.schemas import IntakeIdentifyRepositoryRequest
from app.schemas import IntakeIssueScopingRequest
from app.schemas import JiraConnectRequest
from app.schemas import LinearConnectRequest
from app.schemas import RunCreateRequest
from app.schemas import SignInRequest
from app.schemas import TaskCreateRequest
from app.providers import classify_intake_issues_by_scope
from app.providers import CursorAgentError
from app.providers import download_cursor_artifact
from app.providers import OpenAIEnrichmentError
from app.providers import enrich_intake_field
from app.providers import identify_repository_for_issue
from app.providers import list_cursor_artifacts
from app.providers import read_cursor_artifact_content
from app.providers import suggest_next_actions_for_runs
from app.state import create_run
from app.state import create_task
from app.state import get_approval_payload
from app.state import get_dashboard_payload
from app.state import get_integrations_payload
from app.state import get_intake_payload
from app.state import get_policy_payload
from app.state import get_run_detail
from app.state import get_runs_by_ids
from app.state import record_approval


app = FastAPI(
    title="AI Control Pane API",
    description="Backend foundation for the AI Control Pane demo application.",
    version="0.1.0",
)
settings = get_settings()


def _build_allowed_origins() -> Sequence[str]:
    """Builds the allowed browser origins for the frontend application."""

    allowed_origins = ["http://localhost:5173"]
    configured_origin = settings.frontend_base_url.rstrip("/")

    if configured_origin and configured_origin not in allowed_origins:
        # Add the configured frontend origin so production sign-in flows can complete.
        allowed_origins.append(configured_origin)

    # Return the normalized origin list for CORS middleware setup.
    return allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_build_allowed_origins()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _ensure_google_sso_enabled() -> None:
    """Requires the backend Google OAuth configuration before continuing."""

    if is_google_sso_enabled(settings):
        # Allow the request to continue when Google OAuth configuration is complete.
        return

    # Reject Google auth requests when the required environment variables are missing.
    raise HTTPException(status_code=503, detail="Google SSO is not configured for this environment.")


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Executes an HTTP request and parses the JSON response body."""

    request_headers = headers or {}
    request = UrlRequest(url, data=payload, headers=request_headers, method=method)

    with urlopen(request, timeout=12) as response:
        # Decode the remote JSON body into a Python dictionary.
        return json.loads(response.read().decode("utf-8"))


def _exchange_google_authorization_code(authorization_code: str) -> Dict[str, Any]:
    """Exchanges the Google authorization code for the upstream token payload."""

    encoded_payload = urlencode(
        {
            "code": authorization_code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")

    try:
        # Exchange the one-time Google authorization code for the token response.
        return _request_json(
            "https://oauth2.googleapis.com/token",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            payload=encoded_payload,
        )
    except HTTPError as error:
        # Reject the callback when Google refuses the code exchange request.
        raise HTTPException(status_code=400, detail=f"Google sign-in failed during token exchange: {error.reason}") from error
    except (URLError, json.JSONDecodeError) as error:
        # Reject the callback when the Google token response cannot be read safely.
        raise HTTPException(status_code=502, detail="Google sign-in could not be completed because the token response was unreadable.") from error


def _read_google_identity(id_token: str) -> Dict[str, Any]:
    """Reads the Google identity payload for the returned ID token."""

    query_string = urlencode({"id_token": id_token})

    try:
        # Validate and read the Google ID token using Google's tokeninfo endpoint.
        return _request_json(f"https://oauth2.googleapis.com/tokeninfo?{query_string}")
    except HTTPError as error:
        # Reject invalid or expired Google ID tokens before creating an app session.
        raise HTTPException(status_code=401, detail=f"The Google identity token was rejected: {error.reason}") from error
    except (URLError, json.JSONDecodeError) as error:
        # Reject the login when the Google identity payload cannot be read safely.
        raise HTTPException(status_code=502, detail="Google sign-in could not be completed because the identity response was unreadable.") from error


def _build_frontend_url(path: str, query_params: Dict[str, str]) -> str:
    """Builds a frontend redirect URL for the browser-based sign-in flow."""

    normalized_base_url = settings.frontend_base_url.rstrip("/")
    encoded_query = urlencode(query_params)

    if encoded_query:
        # Return the frontend URL together with the encoded query string.
        return f"{normalized_base_url}{path}?{encoded_query}"

    # Return the frontend URL without a query string when there are no parameters.
    return f"{normalized_base_url}{path}"


def _build_google_authorize_url() -> str:
    """Builds the Google authorization URL used to start the redirect flow."""

    state_token = create_google_oauth_state()
    query_string = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state_token,
            "access_type": "offline",
            "prompt": "select_account",
            **({"hd": settings.google_hosted_domain} if settings.google_hosted_domain else {}),
        }
    )

    # Return the completed Google authorization URL for the browser redirect.
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"


def _build_auth_config_payload() -> Dict[str, bool]:
    """Builds the public auth configuration payload used by the sign-in screen."""

    google_sso_enabled = is_google_sso_enabled(settings)

    # Return the available sign-in methods so the frontend can render the correct flow.
    return {
        "googleSsoEnabled": google_sso_enabled,
        "guidedSignInEnabled": not google_sso_enabled,
    }


def _encode_artifact_content(content: bytes) -> Tuple[str, str]:
    """Encodes artifact bytes into a display-safe string payload."""

    try:
        # Prefer readable UTF-8 text so artifact files can be reviewed inline.
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # Fall back to base64 for binary artifacts such as screenshots.
        return base64.b64encode(content).decode("ascii"), "base64"


def _build_cursor_artifact_results(effective_settings: Any, agent_id: str) -> Dict[str, Any]:
    """Builds run-room artifact results from Cursor's artifact APIs."""

    artifact_listing = list_cursor_artifacts(effective_settings, agent_id)
    listed_items = artifact_listing.get("artifacts", artifact_listing.get("items", []))
    artifact_results = []

    if not isinstance(listed_items, list):
        # Treat malformed provider payloads as empty instead of breaking the run room.
        listed_items = []

    for listed_item in listed_items:
        if not isinstance(listed_item, dict):
            # Skip malformed artifact rows without affecting the remaining results.
            continue

        artifact_path = str(listed_item.get("absolutePath", listed_item.get("path", ""))).strip()

        if not artifact_path:
            # Skip rows without the artifact path required by Cursor's download endpoint.
            continue

        download_payload = download_cursor_artifact(effective_settings, agent_id, artifact_path)
        download_url = str(download_payload.get("url", "")).strip()
        artifact_bytes, content_type = read_cursor_artifact_content(download_url)
        encoded_content, encoding = _encode_artifact_content(artifact_bytes)

        # Preserve Cursor metadata and attach the downloaded artifact body for the UI.
        artifact_results.append(
            {
                "path": artifact_path,
                "sizeBytes": listed_item.get("sizeBytes"),
                "updatedAt": listed_item.get("updatedAt", ""),
                "downloadUrl": download_url,
                "expiresAt": download_payload.get("expiresAt", ""),
                "contentType": content_type,
                "encoding": encoding,
                "content": encoded_content,
            }
        )

    # Return a stable panel payload even when the agent has not produced artifacts yet.
    return {"agentId": agent_id, "items": artifact_results}


def _extract_cursor_agent_id(cloud_agent: Dict[str, Any]) -> str:
    """Extracts the Cursor agent id from the stored Cloud Agent URL."""

    target_payload = cloud_agent.get("target", {})
    cloud_agent_url = ""

    if isinstance(target_payload, dict):
        # Cursor Cloud Agent URLs expose the real provider id as the id query parameter.
        cloud_agent_url = str(target_payload.get("url", "") or "").strip()

    if cloud_agent_url:
        parsed_query = parse_qs(urlparse(cloud_agent_url).query)
        url_agent_id = str((parsed_query.get("id") or [""])[0]).strip()

        if url_agent_id:
            # Prefer the provider id from the URL over any control-pane task or PR slug.
            return url_agent_id

    # Fall back to the provider payload id for older stored runs that lack a URL.
    return str(cloud_agent.get("id", "") or "").strip()


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


@app.get("/auth/config")
@app.get("/api/auth/config")
def get_auth_config() -> Dict[str, bool]:
    """Returns the public auth configuration used by the sign-in screen."""

    # Return the available sign-in methods without exposing any secrets.
    return _build_auth_config_payload()


@app.get("/auth/google/start")
@app.get("/api/auth/google/start")
def start_google_sign_in() -> RedirectResponse:
    """Redirects the browser to Google to begin the OAuth sign-in flow."""

    _ensure_google_sso_enabled()

    # Redirect the browser into the Google OAuth consent flow.
    return RedirectResponse(url=_build_google_authorize_url(), status_code=302)


@app.get("/auth/google/callback")
@app.get("/api/auth/google/callback")
def finish_google_sign_in(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    """Handles the Google OAuth callback and redirects back to the frontend."""

    if error:
        # Return the browser to the frontend with the provider-supplied failure reason.
        return RedirectResponse(url=_build_frontend_url("/auth/callback", {"error": error}), status_code=302)

    try:
        _ensure_google_sso_enabled()
        consume_google_oauth_state(state)

        if not code.strip():
            # Reject callbacks that do not include a usable authorization code.
            raise HTTPException(status_code=400, detail="Google did not return an authorization code.")

        token_payload = _exchange_google_authorization_code(code.strip())
        id_token = str(token_payload.get("id_token", "")).strip()

        if not id_token:
            # Reject token responses that omit the required Google ID token.
            raise HTTPException(status_code=401, detail="Google did not return a usable identity token.")

        identity_payload = _read_google_identity(id_token)
        validated_identity = validate_google_identity(settings, identity_payload)
        exchange_code = store_google_exchange_code(
            validated_identity["name"],
            validated_identity["email"],
            validated_identity["role"],
        )
    except HTTPException as error_response:
        # Return the browser to the frontend with a stable app-specific auth error.
        return RedirectResponse(
            url=_build_frontend_url("/auth/callback", {"error": error_response.detail}),
            status_code=302,
        )

    # Return the browser to the frontend with the short-lived app exchange code.
    return RedirectResponse(url=_build_frontend_url("/auth/callback", {"code": exchange_code}), status_code=302)


@app.post("/auth/google/exchange")
@app.post("/api/auth/google/exchange")
def post_google_exchange(payload: GoogleAuthExchangeRequest) -> Dict[str, Any]:
    """Exchanges the frontend callback code for the normal app session payload."""

    _ensure_google_sso_enabled()

    # Convert the short-lived Google exchange code into the shared auth session shape.
    return consume_google_exchange_code(payload.code)


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


@app.post("/dashboard/suggested-actions")
@app.post("/api/dashboard/suggested-actions")
def post_dashboard_suggested_actions(
    payload: DashboardSuggestedActionsRequest,
    request: Request,
) -> Dict[str, Any]:
    """Returns OpenAI-generated suggested next actions for the visible dashboard runs.

    The caller passes the run IDs currently shown in the dashboard's
    'Active and recent runs' container so the suggestions stay consistent with
    what the operator is looking at.
    """

    effective_settings, request_headers, _ = _authorized_request(request)

    # Resolve the requested run IDs into enriched run payloads before prompting.
    visible_runs = get_runs_by_ids(payload.run_ids, effective_settings, request_headers)

    try:
        # Call OpenAI to produce suggested next actions grounded in the visible runs.
        return suggest_next_actions_for_runs(effective_settings, runs=visible_runs)
    except OpenAIEnrichmentError as suggestion_error:
        # Translate OpenAI-side rejections into a readable upstream error response.
        raise HTTPException(status_code=502, detail=str(suggestion_error)) from suggestion_error


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


@app.get("/runs/{run_id}/artifacts")
@app.get("/api/runs/{run_id}/artifacts")
def read_run_artifacts(
    run_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Returns downloaded Cursor artifact contents for a specific run."""

    effective_settings, request_headers, _ = _authorized_request(request)

    try:
        # Reuse the run detail resolver so Cursor-backed runs are synced before artifacts load.
        run_detail = get_run_detail(run_id, effective_settings, request_headers)
    except KeyError as error:
        # Translate a missing run into an HTTP-friendly not found response.
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' was not found.") from error

    cloud_agent = run_detail.get("cloudAgent")

    if not isinstance(cloud_agent, dict):
        # Return an empty artifact payload for simulated runs without a Cursor agent.
        return {"agentId": "", "items": []}

    agent_id = _extract_cursor_agent_id(cloud_agent)

    if not agent_id:
        # Return an empty artifact payload when the Cursor payload is missing its id.
        return {"agentId": "", "items": []}

    try:
        # List, download, and read each artifact produced for the Cursor agent.
        return _build_cursor_artifact_results(effective_settings, agent_id)
    except CursorAgentError as cursor_error:
        # Translate Cursor-side failures into a readable upstream error response.
        raise HTTPException(status_code=502, detail=str(cursor_error)) from cursor_error


@app.get("/cursor/agents/{agent_id}/artifacts")
@app.get("/api/cursor/agents/{agent_id}/artifacts")
def read_cursor_agent_artifacts(
    agent_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Returns downloaded Cursor artifact contents for a Cursor Cloud Agent."""

    effective_settings, _, _ = _authorized_request(request)
    normalized_agent_id = agent_id.strip()

    if not normalized_agent_id:
        # Reject empty provider ids before trying to call Cursor.
        raise HTTPException(status_code=400, detail="Cursor Cloud Agent id is required.")

    try:
        # List, download, and read each artifact produced for the Cursor agent id.
        return _build_cursor_artifact_results(effective_settings, normalized_agent_id)
    except CursorAgentError as cursor_error:
        # Translate Cursor-side failures into a readable upstream error response.
        raise HTTPException(status_code=502, detail=str(cursor_error)) from cursor_error


@app.get("/approvals")
@app.get("/api/approvals")
def get_approvals(request: Request) -> Dict[str, Any]:
    """Returns the approval inbox payload for review-ready runs."""

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin",))

    # Return the queue summary and pending approval items for the inbox.
    return get_approval_payload(effective_settings, request_headers)


@app.get("/policies")
@app.get("/api/policies")
@app.get("/policies/{scope}")
@app.get("/api/policies/{scope}")
def get_policies(request: Request, scope: str = "web-app") -> Dict[str, Any]:
    """Returns the active policy pack for the UI demo."""

    _authorized_request_with_roles(request, ("admin",))

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

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin",))

    # Return the current integration status summary for the management view.
    return get_integrations_payload(effective_settings, request_headers)


@app.get("/intake")
@app.get("/api/intake")
def get_intake(request: Request) -> Dict[str, Any]:
    """Returns the integrated intake payload for task creation."""

    effective_settings, request_headers, _ = _authorized_request(request)

    # Return the repositories, issues, docs, and user context for task intake.
    return get_intake_payload(effective_settings, request_headers)


@app.post("/intake/issue-scoping")
@app.post("/api/intake/issue-scoping")
def post_intake_issue_scoping(
    payload: IntakeIssueScopingRequest,
    request: Request,
) -> Dict[str, Any]:
    """Separates the intake issue list into well-scoped and poorly-scoped buckets."""

    effective_settings, request_headers, _ = _authorized_request(request)
    intake_catalog = get_intake_payload(effective_settings, request_headers)
    issue_catalog = list(intake_catalog.get("issues", []))
    requested_issue_ids = [issue_id for issue_id in payload.issue_ids if str(issue_id or "").strip()]

    if requested_issue_ids:
        available_issues_by_id = {
            str(issue.get("id") or "").strip(): issue
            for issue in issue_catalog
            if str(issue.get("id") or "").strip()
        }
        issues_to_classify = []

        # Preserve the frontend issue order while ensuring each requested id exists.
        for requested_issue_id in requested_issue_ids:
            normalized_issue_id = str(requested_issue_id).strip()
            matched_issue = available_issues_by_id.get(normalized_issue_id)

            if matched_issue is None:
                # Reject scoping requests that reference an unknown intake issue.
                raise HTTPException(
                    status_code=404,
                    detail=f"Issue '{normalized_issue_id}' was not found in the intake catalog.",
                )

            issues_to_classify.append(matched_issue)
    else:
        # Default to the entire intake issue catalog when no explicit subset is provided.
        issues_to_classify = issue_catalog

    try:
        # Call OpenAI to separate the visible intake issues into the two scope groups.
        return classify_intake_issues_by_scope(effective_settings, issues=issues_to_classify)
    except OpenAIEnrichmentError as scoping_error:
        # Translate OpenAI-side rejections into a readable upstream error response.
        raise HTTPException(status_code=502, detail=str(scoping_error)) from scoping_error


@app.post("/intake/enrich")
@app.post("/api/intake/enrich")
def post_intake_enrich(payload: IntakeEnrichRequest, request: Request) -> Dict[str, Any]:
    """Refines a work intake field using OpenAI and the repo docs context."""

    effective_settings, _, _ = _authorized_request(request)

    try:
        # Call OpenAI to refine the requested intake field against the repo docs.
        return enrich_intake_field(
            effective_settings,
            field=payload.field,
            value=payload.value,
            title=payload.title,
            prompt=payload.prompt,
            acceptance_criteria=payload.acceptance_criteria,
            repo_name=payload.repo_name,
            execution_mode=payload.execution_mode,
            uploaded_documents=payload.uploaded_documents,
        )
    except OpenAIEnrichmentError as enrichment_error:
        # Translate enrichment failures into a clear 4xx/5xx client response.
        raise HTTPException(status_code=502, detail=str(enrichment_error)) from enrichment_error


@app.post("/intake/identify-repository")
@app.post("/api/intake/identify-repository")
def post_intake_identify_repository(
    payload: IntakeIdentifyRepositoryRequest,
    request: Request,
) -> Dict[str, Any]:
    """Identifies the repository best matching the selected work intake issue.

    Uses the integrated intake catalog (issues + repositories + repo docs) and
    delegates the final selection to OpenAI so the button in the work intake UI
    can automatically set the repository dropdown to the best match.
    """

    effective_settings, request_headers, _ = _authorized_request(request)

    # Load the current intake catalog so we can resolve the issue and build the candidate list.
    intake_catalog = get_intake_payload(effective_settings, request_headers)
    repository_catalog = list(intake_catalog.get("repositories", []))
    issue_catalog = list(intake_catalog.get("issues", []))

    # Locate the issue record whose ID matches the payload so the model can read its context.
    selected_issue: Optional[Dict[str, Any]] = None
    for candidate_issue in issue_catalog:
        if str(candidate_issue.get("id") or "") == payload.issue_id:
            selected_issue = candidate_issue
            break

    if selected_issue is None:
        # Reject identification requests that reference an unknown issue.
        raise HTTPException(
            status_code=404,
            detail=f"Issue '{payload.issue_id}' was not found in the intake catalog.",
        )

    try:
        # Call OpenAI to pick the repository that best fits the selected issue.
        return identify_repository_for_issue(
            effective_settings,
            issue=selected_issue,
            repositories=repository_catalog,
        )
    except OpenAIEnrichmentError as identification_error:
        # Translate OpenAI-side rejections into a readable upstream error response.
        raise HTTPException(status_code=502, detail=str(identification_error)) from identification_error


@app.post("/tasks")
@app.post("/api/tasks")
def post_task(
    payload: TaskCreateRequest,
    request: Request,
) -> Dict[str, Any]:
    """Creates a new AI work item from intake and immediately starts its run."""

    effective_settings, request_headers, _ = _authorized_request(request)

    # Create the task record and auto-start the run before returning the detail payload.
    return create_task(effective_settings, request_headers, payload.model_dump(by_alias=True))


@app.post("/runs")
@app.post("/api/runs")
def post_run(payload: RunCreateRequest, request: Request) -> Dict[str, Any]:
    """Creates or restarts an agent run for an existing task."""

    effective_settings, request_headers, _ = _authorized_request(request)

    try:
        # Start or restart the selected run using the simplified in-memory workflow.
        return create_run(effective_settings, request_headers, payload.model_dump(by_alias=True))
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

    effective_settings, request_headers, _ = _authorized_request_with_roles(request, ("admin",))

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

    _, _, session = _authorized_request_with_roles(request, ("admin",))
    connect_github(session, payload.owner, payload.repositories, payload.token)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the GitHub setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/linear/connect")
@app.post("/api/integrations/linear/connect")
def post_linear_connect(payload: LinearConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the Linear connection selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin",))
    connect_linear(session, payload.api_key, payload.team_id)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the Linear setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/jira/connect")
@app.post("/api/integrations/jira/connect")
def post_jira_connect(payload: JiraConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the Jira Cloud connection selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin",))
    connect_jira(session, payload.site_url, payload.email, payload.api_token, payload.project_key)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the Jira setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/docs/connect")
@app.post("/api/integrations/docs/connect")
def post_docs_connect(payload: DocsConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the docs directory selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin",))
    connect_docs(session, payload.docs_directory)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the docs setup.
    return get_integrations_payload(effective_settings, request_headers)


@app.post("/integrations/cursor/connect")
@app.post("/api/integrations/cursor/connect")
def post_cursor_connect(payload: CursorConnectRequest, request: Request) -> Dict[str, Any]:
    """Stores the Cursor Cloud Agents setup selected in the guided integrations flow."""

    _, _, session = _authorized_request_with_roles(request, ("admin",))
    connect_cursor(session, payload.api_key, payload.model)
    effective_settings = build_effective_settings(settings, session)
    request_headers = build_request_headers(request.headers, session)

    # Return the refreshed integrations payload after saving the Cursor setup.
    return get_integrations_payload(effective_settings, request_headers)
