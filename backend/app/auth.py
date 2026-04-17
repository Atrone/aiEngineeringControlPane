"""Session-backed sign-in, role checks, and guided integration setup state."""

import base64
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import hashlib
import hmac
import json
import os
import time
from secrets import token_urlsafe
from secrets import compare_digest
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import HTTPException
from fastapi import status

from app.config import Settings
from app.providers import normalize_cursor_api_key
from app.providers import normalize_linear_api_key


ALLOWED_ROLES: Sequence[str] = ("admin", "tech_lead", "engineer")
SESSION_STORE: Dict[str, "SessionRecord"] = {}
SESSION_EXPIRATION_SECONDS = 60 * 60 * 12
GOOGLE_STATE_STORE: Dict[str, float] = {}
GOOGLE_EXCHANGE_CODE_STORE: Dict[str, "GoogleExchangeRecord"] = {}
GOOGLE_STATE_TTL_SECONDS = 600
GOOGLE_EXCHANGE_CODE_TTL_SECONDS = 300


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
    cursor_api_key: str = ""
    cursor_model: str = "default"
    docs_directory: str = ""


@dataclass
class GoogleExchangeRecord:
    """Stores a short-lived post-OAuth exchange code before a session is minted."""

    name: str
    email: str
    role: str
    expires_at: float


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


def _get_session_signing_secret() -> str:
    """Resolves the secret used to sign stateless session tokens."""

    configured_secret = os.getenv("CONTROL_PANE_SESSION_SECRET", "").strip()

    if configured_secret:
        # Prefer an explicit session secret when one has been configured.
        return configured_secret

    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    if google_client_secret:
        # Fall back to the Google client secret so SSO sessions stay stable across requests.
        return google_client_secret

    # Use a development-only fallback when no secret has been configured yet.
    return "ai-control-pane-development-session-secret"


def _encode_token_segment(raw_value: bytes) -> str:
    """Encodes a token segment using URL-safe base64 without padding."""

    # Return the URL-safe base64 token segment without trailing padding.
    return base64.urlsafe_b64encode(raw_value).decode("utf-8").rstrip("=")


def _decode_token_segment(encoded_value: str) -> bytes:
    """Decodes a URL-safe base64 token segment back into raw bytes."""

    padding_length = (-len(encoded_value)) % 4
    padded_value = encoded_value + ("=" * padding_length)

    # Return the decoded raw token bytes using the restored base64 padding.
    return base64.urlsafe_b64decode(padded_value.encode("utf-8"))


def _build_signed_session_token(name: str, email: str, role: str, provider: str) -> str:
    """Builds a signed stateless session token for cross-request auth restoration."""

    issued_at = int(time.time())
    payload = {
        "version": 1,
        "name": name,
        "email": email,
        "role": role,
        "provider": provider,
        "iat": issued_at,
        "exp": issued_at + SESSION_EXPIRATION_SECONDS,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_segment = _encode_token_segment(payload_json)
    signature = hmac.new(
        _get_session_signing_secret().encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_segment = _encode_token_segment(signature)

    # Return the stateless token formed from the payload and its signature.
    return f"{payload_segment}.{signature_segment}"


def _read_signed_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Validates and parses a signed stateless session token."""

    token_parts = token.split(".", 1)

    if len(token_parts) != 2:
        # Return no payload when the token does not have the expected two-part shape.
        return None

    payload_segment, signature_segment = token_parts
    expected_signature = hmac.new(
        _get_session_signing_secret().encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_signature_segment = _encode_token_segment(expected_signature)

    if not compare_digest(signature_segment, expected_signature_segment):
        # Return no payload when the token signature does not verify.
        return None

    try:
        payload = json.loads(_decode_token_segment(payload_segment).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        # Return no payload when the signed token body cannot be decoded safely.
        return None

    if not isinstance(payload, dict):
        # Return no payload when the token body is not a JSON object.
        return None

    expires_at = int(payload.get("exp", 0))

    if expires_at <= int(time.time()):
        # Return no payload when the signed session token has already expired.
        return None

    # Return the verified payload for session reconstruction.
    return payload


def _build_session_record_from_token(token: str, payload: Mapping[str, Any]) -> Optional["SessionRecord"]:
    """Reconstructs a session record from a verified stateless token payload."""

    name = str(payload.get("name", "")).strip()
    email = _normalize_email(str(payload.get("email", "")))
    role = str(payload.get("role", "")).strip()
    provider = str(payload.get("provider", "guided_sign_in")).strip() or "guided_sign_in"

    if not name or not email or role not in ALLOWED_ROLES:
        # Return no session when the verified token payload is incomplete or invalid.
        return None

    # Return the minimal session reconstructed from the stateless signed token.
    return SessionRecord(
        token=token,
        name=name,
        email=email,
        role=role,
        provider=provider,
    )


def _normalize_email(email: str) -> str:
    """Normalizes an email address for auth checks and role resolution."""

    # Return the lowercased email string so comparisons stay stable.
    return email.strip().lower()


def _extract_email_domain(email: str) -> str:
    """Extracts the email domain used by Google access and role rules."""

    normalized_email = _normalize_email(email)

    if "@" not in normalized_email:
        # Return an empty domain when the caller passed an invalid email.
        return ""

    # Return the domain portion after the at-sign for rule matching.
    return normalized_email.split("@", 1)[1]


def _normalize_rule_values(values: Sequence[str]) -> List[str]:
    """Normalizes configured rule values into a case-insensitive list."""

    normalized_values: List[str] = []

    # Normalize every configured value so matching stays case-insensitive.
    for value in values:
        normalized_value = value.strip().lower()

        if normalized_value:
            # Keep only non-empty normalized rule values.
            normalized_values.append(normalized_value)

    # Return the filtered and normalized rule values.
    return normalized_values


def _prune_expired_google_records() -> None:
    """Deletes expired Google OAuth state and exchange records from memory."""

    current_time = time.time()

    # Remove expired state tokens so replay windows stay short.
    for state_token, expires_at in list(GOOGLE_STATE_STORE.items()):
        if expires_at <= current_time:
            # Drop the expired state token from the in-memory store.
            GOOGLE_STATE_STORE.pop(state_token, None)

    # Remove expired exchange codes before they can be reused.
    for exchange_code, record in list(GOOGLE_EXCHANGE_CODE_STORE.items()):
        if record.expires_at <= current_time:
            # Drop the expired exchange code from the in-memory store.
            GOOGLE_EXCHANGE_CODE_STORE.pop(exchange_code, None)


def is_google_sso_enabled(settings: Settings) -> bool:
    """Reports whether the backend has enough configuration to run Google SSO."""

    # Return true only when the required Google OAuth settings are all present.
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri)


def create_google_oauth_state() -> str:
    """Creates a short-lived OAuth state token for the Google redirect flow."""

    _prune_expired_google_records()
    state_token = token_urlsafe(24)

    # Persist the state token with a short expiration to block CSRF replay.
    GOOGLE_STATE_STORE[state_token] = time.time() + GOOGLE_STATE_TTL_SECONDS
    return state_token


def consume_google_oauth_state(state_token: str) -> None:
    """Consumes a Google OAuth state token and rejects invalid or expired values."""

    _prune_expired_google_records()
    normalized_state_token = state_token.strip()
    expires_at = GOOGLE_STATE_STORE.pop(normalized_state_token, None)

    if expires_at and expires_at > time.time():
        # Accept the state token once and only once when it is still valid.
        return

    # Reject missing, reused, or expired state tokens to protect the callback flow.
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The Google sign-in request is no longer valid.")


def _email_matches_rule(email: str, emails: Sequence[str], domains: Sequence[str]) -> bool:
    """Reports whether an email matches configured exact-email or domain rules."""

    normalized_email = _normalize_email(email)
    normalized_domain = _extract_email_domain(normalized_email)
    allowed_emails = _normalize_rule_values(emails)
    allowed_domains = _normalize_rule_values(domains)

    if normalized_email in allowed_emails:
        # Match exact email rules before considering broader domain rules.
        return True

    if normalized_domain in allowed_domains:
        # Match a configured domain rule when the email domain is allowed.
        return True

    # Report no match when neither the email nor its domain are configured.
    return False


def resolve_google_role(settings: Settings, email: str) -> str:
    """Maps a Google account to an application role using configured rules."""

    normalized_email = _normalize_email(email)

    if _email_matches_rule(normalized_email, settings.google_admin_emails, settings.google_admin_domains):
        # Prefer the admin role when an account matches multiple configured rules.
        return "admin"

    if _email_matches_rule(normalized_email, settings.google_tech_lead_emails, settings.google_tech_lead_domains):
        # Map the next-highest reviewer role when the account is a tech lead.
        return "tech_lead"

    if _email_matches_rule(normalized_email, settings.google_engineer_emails, settings.google_engineer_domains):
        # Fall back to the engineer role when that is the first matching rule.
        return "engineer"

    # Reject accounts that are authenticated with Google but not authorized in the app.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Your Google account is not authorized for this control pane.",
    )


def validate_google_identity(settings: Settings, identity_payload: Mapping[str, Any]) -> Dict[str, str]:
    """Validates the Google identity payload and resolves the app-specific role."""

    audience = str(identity_payload.get("aud", "")).strip()
    verified_email = str(identity_payload.get("email_verified", "")).strip().lower()
    email = _normalize_email(str(identity_payload.get("email", "")))
    hosted_domain = str(identity_payload.get("hd", "")).strip().lower()
    name = str(identity_payload.get("name", "")).strip()
    email_domain = _extract_email_domain(email)

    if audience != settings.google_client_id:
        # Reject tokens minted for a different Google OAuth client.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The Google identity token was not issued for this app.")

    if verified_email not in {"true", "1"}:
        # Reject identities whose Google email address has not been verified.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your Google email address must be verified before signing in.")

    if not email:
        # Reject malformed Google identity payloads that omit the user's email.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google did not return a usable email address.")

    if settings.google_hosted_domain and hosted_domain != settings.google_hosted_domain.strip().lower():
        # Reject accounts outside the configured Google Workspace hosted domain.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sign-in is limited to the configured Google Workspace domain.")

    if settings.google_allowed_domains:
        allowed_domains = _normalize_rule_values(settings.google_allowed_domains)

        if email_domain not in allowed_domains:
            # Reject accounts whose email domain is not on the allowed-domain list.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your Google account domain is not allowed for this control pane.")

    resolved_role = resolve_google_role(settings, email)
    resolved_name = name or email.split("@", 1)[0]

    # Return the normalized Google identity the app uses to create a session.
    return {
        "name": resolved_name,
        "email": email,
        "role": resolved_role,
    }


def store_google_exchange_code(name: str, email: str, role: str) -> str:
    """Stores a short-lived code that the frontend can exchange for an app session."""

    _prune_expired_google_records()
    exchange_code = token_urlsafe(24)

    # Persist the resolved Google identity until the frontend completes the exchange step.
    GOOGLE_EXCHANGE_CODE_STORE[exchange_code] = GoogleExchangeRecord(
        name=name.strip(),
        email=_normalize_email(email),
        role=_normalize_role(role),
        expires_at=time.time() + GOOGLE_EXCHANGE_CODE_TTL_SECONDS,
    )
    return exchange_code


def consume_google_exchange_code(exchange_code: str) -> Dict[str, Any]:
    """Consumes a short-lived Google exchange code and creates an app session."""

    _prune_expired_google_records()
    normalized_exchange_code = exchange_code.strip()
    record = GOOGLE_EXCHANGE_CODE_STORE.pop(normalized_exchange_code, None)

    if record and record.expires_at > time.time():
        # Convert the one-time exchange code into the standard app session payload.
        return create_session(record.name, record.email, record.role, provider="google_sso")

    # Reject missing, reused, or expired exchange codes before creating a session.
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The Google sign-in response is no longer valid.")


def create_session(name: str, email: str, role: str, provider: str = "guided_sign_in") -> Dict[str, Any]:
    """Creates a new in-memory session for either guided sign-in or Google SSO."""

    normalized_name = name.strip()
    normalized_email = _normalize_email(email)
    normalized_role = _normalize_role(role)

    if not normalized_name or not normalized_email:
        # Reject incomplete sign-in requests so audit identity remains usable.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name and email are required.")

    token = _build_signed_session_token(normalized_name, normalized_email, normalized_role, provider.strip() or "guided_sign_in")
    session = SessionRecord(
        token=token,
        name=normalized_name,
        email=normalized_email,
        role=normalized_role,
        provider=provider.strip() or "guided_sign_in",
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

    memory_session = SESSION_STORE.get(token)

    if memory_session:
        # Return the in-memory session when the token exists in the local process store.
        return memory_session

    signed_payload = _read_signed_session_token(token)

    if not signed_payload:
        # Return no session when the signed token is missing, invalid, or expired.
        return None

    reconstructed_session = _build_session_record_from_token(token, signed_payload)

    if not reconstructed_session:
        # Return no session when the signed payload cannot be converted into a session.
        return None

    # Return the reconstructed session so auth survives across backend invocations.
    return reconstructed_session


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
        cursor_api_key=session.cursor_api_key or settings.cursor_api_key,
        cursor_model=session.cursor_model or settings.cursor_model,
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

    normalized_api_key = normalize_linear_api_key(api_key)

    if not normalized_api_key:
        # Reject incomplete Linear setup requests before mutating the session.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Linear API key is required.")

    # Save the Linear inputs to the signed-in session.
    session.linear_api_key = normalized_api_key
    session.linear_team_id = team_id.strip()


def connect_cursor(session: SessionRecord, api_key: str, model: str) -> None:
    """Stores the Cursor Cloud Agents connection details selected during guided setup."""

    normalized_api_key = normalize_cursor_api_key(api_key)
    normalized_model = model.strip() or "default"

    if not normalized_api_key:
        # Reject incomplete Cursor setup requests before mutating the session.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor API key is required.")

    # Save the Cursor Cloud Agents inputs to the signed-in session.
    session.cursor_api_key = normalized_api_key
    session.cursor_model = normalized_model


def connect_docs(session: SessionRecord, docs_directory: str) -> None:
    """Stores the docs directory selected during guided setup."""

    normalized_docs_directory = docs_directory.strip()

    if not normalized_docs_directory:
        # Reject empty docs paths before mutating the session.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Docs directory is required.")

    # Save the selected docs directory to the signed-in session.
    session.docs_directory = normalized_docs_directory
