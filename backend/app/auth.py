"""Session-backed sign-in, role checks, and guided integration setup state."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from secrets import token_urlsafe
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import HTTPException
from fastapi import status

from app.config import Settings


ALLOWED_ROLES: Sequence[str] = ("admin", "tech_lead", "engineer")
SESSION_STORE: Dict[str, "SessionRecord"] = {}


@dataclass
class SessionRecord:
    """Stores the in-memory session and provider setup state for a signed-in user."""

    token: str
    name: str
    email: str
    role: str
    provider: str = "guided_sign_in"
    github_owner: str = ""
    github_repositories: List[str] = field(default_factory=list)
    github_token: str = ""
    linear_api_key: str = ""
    linear_team_id: str = ""
    docs_directory: str = ""


def _normalize_role(role: str) -> str:
    """Normalizes a requested role and rejects unsupported values."""

    normalized_role = role.strip().lower()

    if normalized_role in ALLOWED_ROLES:
        # Return the allowed role once it has been normalized.
        return normalized_role

    # Reject unsupported roles so permission checks stay predictable.
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose admin, tech_lead, or engineer.")


def _parse_repositories(raw_value: str) -> List[str]:
    """Parses a comma-separated repository list into normalized repository names."""

    repositories: List[str] = []

    # Split the caller-provided CSV value into individual repository names.
    for item in raw_value.split(","):
        normalized_item = item.strip()

        if normalized_item:
            # Keep each non-empty repository name in its trimmed form.
            repositories.append(normalized_item)

    # Return the normalized repository name list.
    return repositories


def _extract_bearer_token(headers: Mapping[str, str]) -> Optional[str]:
    """Extracts the bearer token from the incoming Authorization header."""

    authorization_header = headers.get("authorization", "").strip()

    if authorization_header.lower().startswith("bearer "):
        # Return only the token portion when a bearer token is present.
        return authorization_header[7:].strip()

    # Return no token when the request is missing a bearer session.
    return None


def create_session(name: str, email: str, role: str) -> Dict[str, Any]:
    """Creates a new in-memory session for the guided sign-in flow."""

    normalized_name = name.strip()
    normalized_email = email.strip().lower()
    normalized_role = _normalize_role(role)

    if not normalized_name or not normalized_email:
        # Reject incomplete sign-in requests so audit identity remains usable.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name and email are required.")

    token = token_urlsafe(24)
    session = SessionRecord(
        token=token,
        name=normalized_name,
        email=normalized_email,
        role=normalized_role,
    )

    # Persist the newly created session in the in-memory store.
    SESSION_STORE[token] = session

    # Return the API payload needed by the frontend auth shell.
    return {
        "sessionToken": token,
        "currentUser": build_current_user(session),
    }


def get_session(headers: Mapping[str, str]) -> Optional[SessionRecord]:
    """Looks up the signed-in session from the incoming request headers."""

    token = _extract_bearer_token(headers)

    if not token:
        # Return no session when the request does not include a bearer token.
        return None

    # Return the matching session when the token exists in memory.
    return SESSION_STORE.get(token)


def require_session(headers: Mapping[str, str]) -> SessionRecord:
    """Requires a valid signed-in session before an API route can proceed."""

    session = get_session(headers)

    if session:
        # Return the resolved session when the request is authenticated.
        return session

    # Reject unauthenticated requests so protected routes stay private.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")


def require_role(session: SessionRecord, allowed_roles: Sequence[str]) -> None:
    """Requires that the signed-in user has one of the allowed roles."""

    if session.role in allowed_roles:
        # Allow the request to continue when the user has an accepted role.
        return

    # Reject the request when the signed-in user lacks the required role.
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this action.")


def build_current_user(session: SessionRecord) -> Dict[str, str]:
    """Builds the shared current-user payload from a session record."""

    # Return the user identity shape consumed across the frontend screens.
    return {
        "name": session.name,
        "email": session.email,
        "role": session.role,
        "provider": session.provider,
    }


def build_effective_settings(settings: Settings, session: SessionRecord) -> Settings:
    """Builds an effective settings object that includes session-level connections."""

    # Overlay session-scoped provider inputs on top of the environment defaults.
    return replace(
        settings,
        github_token=session.github_token or settings.github_token,
        github_owner=session.github_owner or settings.github_owner,
        github_repositories=session.github_repositories or settings.github_repositories,
        linear_api_key=session.linear_api_key or settings.linear_api_key,
        linear_team_id=session.linear_team_id or settings.linear_team_id,
        docs_directory=session.docs_directory or settings.docs_directory,
    )


def build_request_headers(headers: Mapping[str, str], session: SessionRecord) -> Dict[str, str]:
    """Builds the normalized request headers used by the existing identity layer."""

    normalized_headers: Dict[str, str] = {}

    # Lowercase incoming header names so downstream lookups stay consistent.
    for key, value in headers.items():
        normalized_headers[key.lower()] = value

    # Attach the signed-in user identity in the same shape the app already understands.
    normalized_headers["x-demo-user-email"] = session.email
    normalized_headers["x-demo-user-name"] = session.name
    normalized_headers["x-demo-user-role"] = session.role

    # Return the normalized headers for the state and provider helpers.
    return normalized_headers


def sign_out_session(headers: Mapping[str, str]) -> None:
    """Deletes the signed-in session represented by the incoming request."""

    token = _extract_bearer_token(headers)

    if token and token in SESSION_STORE:
        # Remove the in-memory session when the caller signs out.
        SESSION_STORE.pop(token, None)


def connect_github(session: SessionRecord, owner: str, repositories: str, token: str) -> None:
    """Stores the GitHub connection details selected during guided setup."""

    normalized_owner = owner.strip()
    normalized_repositories = _parse_repositories(repositories)

    if not normalized_owner or not normalized_repositories:
        # Reject incomplete GitHub setup requests before mutating the session.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub owner and at least one repository are required.",
        )

    # Save the GitHub inputs to the signed-in session.
    session.github_owner = normalized_owner
    session.github_repositories = normalized_repositories
    session.github_token = token.strip()


def connect_linear(session: SessionRecord, api_key: str, team_id: str) -> None:
    """Stores the Linear connection details selected during guided setup."""

    normalized_api_key = api_key.strip()

    if not normalized_api_key:
        # Reject incomplete Linear setup requests before mutating the session.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Linear API key is required.")

    # Save the Linear inputs to the signed-in session.
    session.linear_api_key = normalized_api_key
    session.linear_team_id = team_id.strip()


def connect_docs(session: SessionRecord, docs_directory: str) -> None:
    """Stores the docs directory selected during guided setup."""

    normalized_docs_directory = docs_directory.strip()

    if not normalized_docs_directory:
        # Reject empty docs paths before mutating the session.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Docs directory is required.")

    # Save the selected docs directory to the signed-in session.
    session.docs_directory = normalized_docs_directory
