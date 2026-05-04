"""Unit coverage for Google OAuth and Google identity auth helpers."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import auth
from app.config import Settings


class AuthGoogleHelpersTests(unittest.TestCase):
    """Verifies Google OAuth state, identity, and exchange helpers."""

    def setUp(self) -> None:
        """Snapshots shared auth state before each test runs."""

        # Preserve the mutable in-memory auth stores so tests cannot leak state.
        self.original_session_store = dict(auth.SESSION_STORE)
        self.original_state_store = dict(auth.GOOGLE_STATE_STORE)
        self.original_consumed_state_store = dict(auth.GOOGLE_CONSUMED_STATE_STORE)
        self.original_exchange_store = dict(auth.GOOGLE_EXCHANGE_CODE_STORE)

    def tearDown(self) -> None:
        """Restores shared auth state after each test finishes."""

        # Restore the in-memory session store for the next isolated test.
        auth.SESSION_STORE.clear()
        auth.SESSION_STORE.update(self.original_session_store)

        # Restore the in-memory Google OAuth state cache.
        auth.GOOGLE_STATE_STORE.clear()
        auth.GOOGLE_STATE_STORE.update(self.original_state_store)

        # Restore the local consumed-state replay cache.
        auth.GOOGLE_CONSUMED_STATE_STORE.clear()
        auth.GOOGLE_CONSUMED_STATE_STORE.update(self.original_consumed_state_store)

        # Restore the in-memory Google exchange-code cache.
        auth.GOOGLE_EXCHANGE_CODE_STORE.clear()
        auth.GOOGLE_EXCHANGE_CODE_STORE.update(self.original_exchange_store)

    def _build_settings(self) -> Settings:
        """Builds a minimal Google-enabled settings fixture."""

        # Return a settings object with Google fields populated for auth checks.
        return Settings(
            github_token="",
            github_owner="",
            github_repositories=[],
            linear_api_key="",
            linear_team_id="",
            jira_site_url="",
            jira_email="",
            jira_api_token="",
            jira_project_key="",
            cursor_api_key="",
            cursor_model="default",
            docs_directory="docs",
            default_user_name="Default User",
            default_user_email="default@example.com",
            default_user_role="admin",
            frontend_base_url="http://localhost:5173",
            google_client_id="google-client-id",
            google_client_secret="google-client-secret",
            google_redirect_uri="http://localhost:5173/callback",
            google_hosted_domain="example.com",
            google_allowed_domains=["example.com"],
            google_authorized_emails=["admin@example.com"],
            google_authorized_domains=["example.com"],
            openai_api_key="",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        )

    def test_google_state_and_exchange_helpers_enforce_ttl_and_single_use(self) -> None:
        """Covers Google OAuth state creation, pruning, and exchange-code consumption."""

        with patch("app.auth.token_urlsafe", side_effect=["state-nonce", "exchange-token"]), patch(
            "app.auth.time.time",
            side_effect=[1000, 1000, 1000, 1000, 1001, 1001, 1001],
        ):
            # Confirm state creation persists a one-time state token.
            state_token = auth.create_google_oauth_state()
            self.assertNotEqual(state_token, "state-nonce")
            self.assertIn(state_token, auth.GOOGLE_STATE_STORE)

            # Confirm a fresh state token can be consumed exactly once.
            auth.consume_google_oauth_state(state_token)
            self.assertNotIn(state_token, auth.GOOGLE_STATE_STORE)
            self.assertIn(state_token, auth.GOOGLE_CONSUMED_STATE_STORE)

            # Confirm a short-lived exchange code can be stored with normalized identity data.
            exchange_code = auth.store_google_exchange_code(" Test User ", "USER@example.com", "viewer")
            self.assertEqual(exchange_code, "exchange-token")
            record = auth.GOOGLE_EXCHANGE_CODE_STORE[exchange_code]
            self.assertEqual(record.name, "Test User")
            self.assertEqual(record.email, "user@example.com")
            self.assertEqual(record.role, "admin")

        with patch("app.auth.time.time", return_value=1002):
            # Confirm exchange codes create a normal app session payload when consumed.
            payload = auth.consume_google_exchange_code(exchange_code, team_id="platform-team")
            self.assertEqual(payload["currentUser"]["provider"], "google_sso")
            self.assertEqual(payload["currentUser"]["teamId"], "platform-team")

        with patch("app.auth.time.time", return_value=1003):
            # Confirm reused state tokens are rejected.
            with self.assertRaises(HTTPException) as state_error:
                auth.consume_google_oauth_state(state_token)
            self.assertEqual(state_error.exception.status_code, 400)

            # Confirm reused exchange codes are rejected.
            with self.assertRaises(HTTPException) as exchange_error:
                auth.consume_google_exchange_code(exchange_code)
            self.assertEqual(exchange_error.exception.status_code, 400)

        with patch("app.auth.time.time", return_value=2000):
            # Seed expired Google records so the prune helper has work to do.
            auth.GOOGLE_STATE_STORE["expired-state"] = 1000
            auth.GOOGLE_EXCHANGE_CODE_STORE["expired-code"] = auth.GoogleExchangeRecord(
                name="Test User",
                email="test@example.com",
                role="admin",
                expires_at=1000,
            )

            # Confirm pruning removes both expired OAuth states and expired exchange codes.
            auth._prune_expired_google_records()
            self.assertNotIn("expired-state", auth.GOOGLE_STATE_STORE)
            self.assertNotIn("expired-code", auth.GOOGLE_EXCHANGE_CODE_STORE)

    def test_signed_google_state_survives_missing_memory_store(self) -> None:
        """Covers Google OAuth state validation when callbacks hit a different function instance."""

        with patch("app.auth.token_urlsafe", return_value="state-nonce"), patch("app.auth.time.time", side_effect=[1000, 1000]):
            # Create a signed state token in the start request handler.
            state_token = auth.create_google_oauth_state()

        # Simulate the callback landing on another serverless instance with no warm memory state.
        auth.GOOGLE_STATE_STORE.clear()

        with patch("app.auth.time.time", return_value=1001):
            # Confirm the signed token can still validate without the original in-memory record.
            auth.consume_google_oauth_state(state_token)
            self.assertIn(state_token, auth.GOOGLE_CONSUMED_STATE_STORE)

            # Confirm the current instance still blocks a replay after fallback validation.
            with self.assertRaises(HTTPException) as state_error:
                auth.consume_google_oauth_state(state_token)
            self.assertEqual(state_error.exception.status_code, 400)

    def test_google_identity_validation_and_role_resolution_cover_success_and_failures(self) -> None:
        """Covers Google SSO enablement, role resolution, and identity validation paths."""

        settings = self._build_settings()

        # Confirm the SSO enablement helper reflects configured Google credentials.
        self.assertTrue(auth.is_google_sso_enabled(settings))
        self.assertFalse(auth.is_google_sso_enabled(self._build_settings().__class__(**{**settings.__dict__, "google_client_secret": ""})))

        # Confirm authorized emails and domains map to the supported admin role.
        self.assertEqual(auth.resolve_google_role(settings, "admin@example.com"), "admin")
        self.assertEqual(auth.resolve_google_role(settings, "user@example.com"), "admin")

        # Confirm a valid Google identity payload is normalized into the app session shape.
        identity_payload = auth.validate_google_identity(
            settings,
            {
                "aud": "google-client-id",
                "email_verified": "true",
                "email": "ADMIN@example.com",
                "hd": "example.com",
                "name": "Admin User",
            },
        )
        self.assertEqual(identity_payload["email"], "admin@example.com")
        self.assertEqual(identity_payload["role"], "admin")

        # Confirm access is denied when the Google account is not authorized.
        restricted_settings = self._build_settings().__class__(
            **{
                **settings.__dict__,
                "google_authorized_emails": ["owner@example.com"],
                "google_authorized_domains": [],
                "google_allowed_domains": [],
                "google_hosted_domain": "",
            }
        )
        with self.assertRaises(HTTPException) as role_error:
            auth.resolve_google_role(restricted_settings, "user@example.com")
        self.assertEqual(role_error.exception.status_code, 403)

        # Confirm mismatched client IDs are rejected.
        with self.assertRaises(HTTPException) as audience_error:
            auth.validate_google_identity(
                settings,
                {
                    "aud": "other-client",
                    "email_verified": "true",
                    "email": "admin@example.com",
                    "hd": "example.com",
                },
            )
        self.assertEqual(audience_error.exception.status_code, 401)

        # Confirm unverified emails are rejected.
        with self.assertRaises(HTTPException) as verified_error:
            auth.validate_google_identity(
                settings,
                {
                    "aud": "google-client-id",
                    "email_verified": "false",
                    "email": "admin@example.com",
                    "hd": "example.com",
                },
            )
        self.assertEqual(verified_error.exception.status_code, 401)

        # Confirm disallowed hosted domains are rejected.
        with self.assertRaises(HTTPException) as hosted_domain_error:
            auth.validate_google_identity(
                settings,
                {
                    "aud": "google-client-id",
                    "email_verified": "true",
                    "email": "admin@example.com",
                    "hd": "other.com",
                },
            )
        self.assertEqual(hosted_domain_error.exception.status_code, 403)

        # Confirm allowed-domain enforcement rejects non-matching email domains.
        with self.assertRaises(HTTPException) as allowed_domain_error:
            auth.validate_google_identity(
                self._build_settings().__class__(**{**settings.__dict__, "google_allowed_domains": ["company.com"]}),
                {
                    "aud": "google-client-id",
                    "email_verified": "true",
                    "email": "admin@example.com",
                    "hd": "example.com",
                },
            )
        self.assertEqual(allowed_domain_error.exception.status_code, 403)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
