"""Additional coverage for auth.py and main.py guard branches."""

import hashlib
import hmac
import json
import os
import unittest
from types import SimpleNamespace
from urllib.parse import unquote
from unittest.mock import patch

from app import auth
from app import main
from app.config import get_settings


class AuthAndMainGapCoverageTests(unittest.TestCase):
    """Verifies the remaining auth and route edge cases."""

    def test_auth_helpers_cover_secret_and_invalid_signed_session_branches(self) -> None:
        """Covers secret fallback selection and invalid signed-session payload branches."""

        with patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET": "google-secret"}, clear=True):
            # Confirm the Google client secret becomes the signing secret fallback.
            self.assertEqual(auth._get_session_signing_secret(), "google-secret")

        payload_segment = auth._encode_token_segment(b"\xff")
        signature_segment = auth._encode_token_segment(
            hmac.new(
                b"test-secret",
                payload_segment.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
        malformed_token = f"{payload_segment}.{signature_segment}"

        with patch.dict(os.environ, {"CONTROL_PANE_SESSION_SECRET": "test-secret"}, clear=False), patch(
            "app.auth.time.time",
            return_value=1000,
        ):
            # Confirm payloads that cannot decode from UTF-8 are rejected safely.
            self.assertIsNone(auth._read_signed_session_token(malformed_token))

        non_object_segment = auth._encode_token_segment(json.dumps(["not", "an", "object"]).encode("utf-8"))
        non_object_signature = auth._encode_token_segment(
            hmac.new(
                b"test-secret",
                non_object_segment.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
        non_object_token = f"{non_object_segment}.{non_object_signature}"

        with patch.dict(os.environ, {"CONTROL_PANE_SESSION_SECRET": "test-secret"}, clear=False), patch(
            "app.auth.time.time",
            return_value=1000,
        ):
            # Confirm JSON arrays are rejected because session payloads must be objects.
            self.assertIsNone(auth._read_signed_session_token(non_object_token))

        with patch("app.auth._extract_bearer_token", return_value="session-token"), patch(
            "app.auth._read_signed_session_token",
            return_value=None,
        ):
            # Confirm get_session returns no session when the signed token cannot be parsed.
            self.assertIsNone(auth.get_session({"authorization": "Bearer session-token"}))

        with patch("app.auth._extract_bearer_token", return_value="session-token"), patch(
            "app.auth._read_signed_session_token",
            return_value={"email": "user@example.com"},
        ), patch(
            "app.auth._build_session_record_from_token",
            return_value=None,
        ):
            # Confirm get_session returns no session when reconstruction fails after parsing.
            self.assertIsNone(auth.get_session({"authorization": "Bearer session-token"}))

    def test_create_session_and_current_user_include_team_id(self) -> None:
        """Covers team id normalization in session creation and current-user payloads."""

        created_session = auth.create_session(
            "User",
            "user@example.com",
            "admin",
            team_id=" Platform Team ",
        )

        # Confirm guided sign-in normalizes and persists the team identity.
        self.assertEqual(created_session["currentUser"]["teamId"], "platform team")

    def test_google_identity_helpers_cover_open_access_and_missing_email_paths(self) -> None:
        """Covers Google role resolution and validation branches not hit elsewhere."""

        open_access_settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "google_client_id": "client-id",
                "google_authorized_emails": [],
                "google_authorized_domains": [],
            }
        )

        # Confirm open-access Google settings still map validated users to admin.
        self.assertEqual(auth.resolve_google_role(open_access_settings, "user@example.com"), "admin")

        with self.assertRaises(auth.HTTPException) as missing_email_error:
            # Confirm Google identity payloads without an email are rejected explicitly.
            auth.validate_google_identity(
                open_access_settings,
                {
                    "aud": "client-id",
                    "email_verified": "true",
                    "email": "",
                    "hd": "",
                    "name": "User",
                },
            )
        self.assertEqual(missing_email_error.exception.status_code, 401)

    def test_main_google_helpers_cover_enabled_missing_code_and_missing_token_paths(self) -> None:
        """Covers the remaining Google route helper branches in main.py."""

        with patch("app.main.is_google_sso_enabled", return_value=True):
            # Confirm the Google SSO guard returns cleanly when config is present.
            self.assertIsNone(main._ensure_google_sso_enabled())

        with patch("app.main._ensure_google_sso_enabled"), patch("app.main.consume_google_oauth_state"), patch(
            "app.main._build_frontend_url",
            side_effect=lambda path, query_params: f"{path}?error={query_params.get('error', '')}",
        ):
            # Confirm callbacks without an authorization code are redirected with the route error.
            missing_code_response = main.finish_google_sign_in(code=" ", state="state-token")
        self.assertIn("authorization code", unquote(missing_code_response.headers["location"]))

        with patch("app.main._ensure_google_sso_enabled"), patch("app.main.consume_google_oauth_state"), patch(
            "app.main._exchange_google_authorization_code",
            return_value={},
        ), patch(
            "app.main._build_frontend_url",
            side_effect=lambda path, query_params: f"{path}?error={query_params.get('error', '')}",
        ):
            # Confirm token exchanges without an ID token are redirected with the route error.
            missing_token_response = main.finish_google_sign_in(code="auth-code", state="state-token")
        self.assertIn("usable identity token", unquote(missing_token_response.headers["location"]))

    def test_main_openai_route_and_integration_refresh_helpers(self) -> None:
        """Covers main._run_openai_route and main._refresh_integrations_for_session."""

        from fastapi import HTTPException

        from app import providers

        # Confirm OpenAI provider failures are translated into HTTP 502 responses.
        with self.assertRaises(HTTPException) as openai_route_error:
            main._run_openai_route(lambda: (_ for _ in ()).throw(providers.OpenAIEnrichmentError("OpenAI unavailable")))
        self.assertEqual(openai_route_error.exception.status_code, 502)

        # Confirm successful OpenAI route actions return the provider payload unchanged.
        self.assertEqual(main._run_openai_route(lambda: {"ok": True}), {"ok": True})

        session = auth.SessionRecord(
            token="session-token",
            name="User",
            email="user@example.com",
            role="admin",
            team_id="alpha",
        )
        request = SimpleNamespace(headers={"x-demo-team-id": "alpha"})

        with patch("app.main.get_integrations_payload", return_value={"statuses": []}) as integrations_mock:
            # Confirm integration refresh rebuilds settings from the active session.
            refreshed_payload = main._refresh_integrations_for_session(request, session)
            self.assertEqual(refreshed_payload, {"statuses": []})
            integrations_mock.assert_called_once()


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
