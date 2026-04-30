"""Route and helper coverage for auth-related callables in main.py."""

import json
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.schemas import GoogleAuthExchangeRequest
from app.schemas import SignInRequest


class MainAuthRouteTests(unittest.TestCase):
    """Verifies auth helpers and auth-facing route wrappers in main.py."""

    def test_origin_authorization_and_frontend_url_helpers(self) -> None:
        """Covers origin building, auth-context helpers, and redirect URL builders."""

        with patch.object(main, "settings", SimpleNamespace(frontend_base_url="http://frontend.example.com/")):
            # Confirm the configured frontend origin is appended to the default dev origin.
            self.assertEqual(
                main._build_allowed_origins(),
                ["http://localhost:5173", "http://frontend.example.com"],
            )

            # Confirm frontend URLs include query strings only when parameters are present.
            self.assertEqual(
                main._build_frontend_url("/auth/callback", {"code": "abc"}),
                "http://frontend.example.com/auth/callback?code=abc",
            )
            self.assertEqual(
                main._build_frontend_url("/dashboard", {}),
                "http://frontend.example.com/dashboard",
            )

        request = SimpleNamespace(headers={"authorization": "Bearer token"})
        session = SimpleNamespace(role="admin")

        with patch("app.main.require_session", return_value=session), patch(
            "app.main.build_effective_settings",
            return_value="effective-settings",
        ), patch("app.main.build_request_headers", return_value={"x-demo-user-email": "user@example.com"}):
            # Confirm authorized_request assembles the settings, headers, and session tuple.
            effective_settings, request_headers, returned_session = main._authorized_request(request)
            self.assertEqual(effective_settings, "effective-settings")
            self.assertEqual(request_headers["x-demo-user-email"], "user@example.com")
            self.assertIs(returned_session, session)

        with patch("app.main._authorized_request", return_value=("effective", {"x": "y"}, session)), patch(
            "app.main.require_role"
        ) as mock_require_role:
            # Confirm the role-gated helper delegates to the role checker and returns the same tuple.
            authorized = main._authorized_request_with_roles(request, ("admin",))
            self.assertEqual(authorized, ("effective", {"x": "y"}, session))
            mock_require_role.assert_called_once_with(session, ("admin",))

    def test_request_and_google_http_helpers_cover_success_and_error_paths(self) -> None:
        """Covers low-level JSON requests plus Google exchange and identity helpers."""

        class FakeHttpResponse:
            """Provides a simple context-manager HTTP response stub."""

            def __init__(self, payload):
                """Stores the JSON payload that should be returned to the caller."""

                # Preserve the response payload for the fake read call.
                self.payload = payload

            def __enter__(self):
                """Returns the fake response itself for the context manager."""

                # Yield this fake response object to the caller.
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                """Implements the context-manager exit hook."""

                # Report that exceptions should still propagate normally.
                return False

            def read(self):
                """Returns the encoded JSON response body."""

                # Serialize the stored payload into the byte body main.py expects.
                return json.dumps(self.payload).encode("utf-8")

        with patch("app.main.urlopen", return_value=FakeHttpResponse({"ok": True})):
            # Confirm the generic request helper decodes a JSON body.
            self.assertEqual(main._request_json("https://example.test"), {"ok": True})

        with patch.object(
            main,
            "settings",
            SimpleNamespace(
                google_client_id="client-id",
                google_client_secret="secret",
                google_redirect_uri="http://localhost/callback",
                google_hosted_domain="example.com",
            ),
        ), patch("app.main._request_json", return_value={"id_token": "token"}):
            # Confirm the Google code exchange helper returns the upstream payload.
            self.assertEqual(main._exchange_google_authorization_code("auth-code"), {"id_token": "token"})

            # Confirm the Google identity reader returns the upstream identity payload.
            self.assertEqual(main._read_google_identity("token"), {"id_token": "token"})

            # Confirm the Google authorize URL includes the generated state token and hosted domain.
            with patch("app.main.create_google_oauth_state", return_value="state-token"):
                authorize_url = main._build_google_authorize_url()
            self.assertIn("state=state-token", authorize_url)
            self.assertIn("hd=example.com", authorize_url)

        http_error = HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )

        with patch("app.main._request_json", side_effect=http_error):
            # Confirm provider-side HTTP failures are translated into route-facing HTTP exceptions.
            with self.assertRaises(HTTPException):
                main._exchange_google_authorization_code("bad-code")

            with self.assertRaises(HTTPException):
                main._read_google_identity("bad-token")

        with patch("app.main._request_json", side_effect=URLError("offline")):
            # Confirm unreadable provider responses are translated into 502-style auth errors.
            with self.assertRaises(HTTPException):
                main._exchange_google_authorization_code("offline-code")

            with self.assertRaises(HTTPException):
                main._read_google_identity("offline-token")

    def test_auth_routes_cover_guided_and_google_sign_in_flows(self) -> None:
        """Covers auth config, sign-in, Google redirect, callback, exchange, and sign-out routes."""

        with patch("app.main.is_google_sso_enabled", return_value=True):
            # Confirm the public auth config payload flips guided sign-in off when Google is enabled.
            self.assertEqual(
                main._build_auth_config_payload(),
                {"googleSsoEnabled": True, "guidedSignInEnabled": False},
            )

        with patch("app.main.is_google_sso_enabled", return_value=True):
            # Confirm get_auth_config delegates to the helper payload.
            self.assertEqual(main.get_auth_config()["googleSsoEnabled"], True)

        # Confirm the health check route returns the expected static payload.
        self.assertEqual(main.health_check()["status"], "ok")

        with patch("app.main.create_session", return_value={"sessionToken": "token"}) as mock_create_session:
            # Confirm guided sign-in delegates to create_session.
            sign_in_payload = main.post_sign_in(
                SignInRequest(name="User", email="user@example.com", role="admin", team_id="platform")
            )
            self.assertEqual(sign_in_payload["sessionToken"], "token")
            mock_create_session.assert_called_once_with("User", "user@example.com", "admin", team_id="platform")

        with patch("app.main.is_google_sso_enabled", return_value=False):
            # Confirm the Google enablement guard raises when OAuth is not configured.
            with self.assertRaises(HTTPException):
                main._ensure_google_sso_enabled()

        with patch("app.main._ensure_google_sso_enabled"), patch(
            "app.main._build_google_authorize_url",
            return_value="https://accounts.google.com/o/oauth2/v2/auth?state=abc",
        ):
            # Confirm the start route returns a redirect into Google's auth flow.
            response = main.start_google_sign_in()
            self.assertEqual(response.headers["location"], "https://accounts.google.com/o/oauth2/v2/auth?state=abc")

        with patch("app.main._build_frontend_url", side_effect=lambda path, params: f"{path}:{params}"):
            # Confirm explicit provider errors redirect back to the frontend callback route.
            response = main.finish_google_sign_in(error="access_denied")
            self.assertIn("access_denied", response.headers["location"])

        with patch("app.main._ensure_google_sso_enabled"), patch(
            "app.main.consume_google_oauth_state"
        ), patch("app.main._exchange_google_authorization_code", return_value={"id_token": "token"}), patch(
            "app.main._read_google_identity",
            return_value={"aud": "client", "email": "user@example.com"},
        ), patch(
            "app.main.validate_google_identity",
            return_value={"name": "User", "email": "user@example.com", "role": "admin"},
        ), patch(
            "app.main.store_google_exchange_code",
            return_value="exchange-code",
        ), patch(
            "app.main._build_frontend_url",
            side_effect=lambda path, params: f"{path}:{params}",
        ):
            # Confirm a successful Google callback redirects the frontend with an exchange code.
            response = main.finish_google_sign_in(code="auth-code", state="state-token")
            self.assertIn("exchange-code", response.headers["location"])

        with patch("app.main._ensure_google_sso_enabled", side_effect=HTTPException(status_code=400, detail="bad")):
            # Confirm Google callback failures redirect back with the app error string.
            response = main.finish_google_sign_in(code="auth-code", state="state-token")
            self.assertIn("bad", response.headers["location"])

        with patch("app.main._ensure_google_sso_enabled"), patch(
            "app.main.consume_google_exchange_code",
            return_value={"sessionToken": "google-session"},
        ) as mock_consume_google_exchange_code:
            # Confirm the exchange route delegates to the shared exchange-code helper.
            response = main.post_google_exchange(GoogleAuthExchangeRequest(code="exchange-code", team_id="platform"))
            self.assertEqual(response["sessionToken"], "google-session")
            mock_consume_google_exchange_code.assert_called_once_with("exchange-code", team_id="platform")

        request = SimpleNamespace(headers={"authorization": "Bearer session"})
        with patch("app.main.sign_out_session") as mock_sign_out_session:
            # Confirm sign-out delegates to the auth-layer session remover.
            response = main.post_sign_out(request)
            self.assertEqual(response["status"], "signed_out")
            mock_sign_out_session.assert_called_once_with(request.headers)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
