"""Unit coverage for auth token, session, and role helpers."""

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi import HTTPException

from app import auth
from app.auth import SessionRecord
from app.config import get_settings


class AuthTokenHelpersTests(unittest.TestCase):
    """Verifies token, session, and role helpers in the auth module."""

    def setUp(self) -> None:
        """Snapshots shared auth state before each test runs."""

        # Preserve the mutable in-memory auth stores so tests cannot leak state.
        self.original_session_store = dict(auth.SESSION_STORE)
        self.original_state_store = dict(auth.GOOGLE_STATE_STORE)
        self.original_exchange_store = dict(auth.GOOGLE_EXCHANGE_CODE_STORE)

    def tearDown(self) -> None:
        """Restores shared auth state after each test finishes."""

        # Restore the in-memory session store for the next isolated test.
        auth.SESSION_STORE.clear()
        auth.SESSION_STORE.update(self.original_session_store)

        # Restore the in-memory Google OAuth state cache.
        auth.GOOGLE_STATE_STORE.clear()
        auth.GOOGLE_STATE_STORE.update(self.original_state_store)

        # Restore the in-memory Google exchange-code cache.
        auth.GOOGLE_EXCHANGE_CODE_STORE.clear()
        auth.GOOGLE_EXCHANGE_CODE_STORE.update(self.original_exchange_store)

    def test_role_repository_and_header_helpers_normalize_inputs(self) -> None:
        """Covers role, repository, token, email, and header normalization helpers."""

        # Confirm every requested role collapses into the supported admin role.
        self.assertEqual(auth._normalize_role("ADMIN"), "admin")
        self.assertEqual(auth._normalize_role("viewer"), "admin")

        # Confirm repository parsing trims whitespace and removes empty values.
        self.assertEqual(
            auth._parse_repositories(" repo-one , ,repo-two, repo-three "),
            ["repo-one", "repo-two", "repo-three"],
        )

        # Confirm bearer-token extraction only succeeds for bearer headers.
        self.assertEqual(
            auth._extract_bearer_token({"authorization": "Bearer session-token"}),
            "session-token",
        )
        self.assertIsNone(auth._extract_bearer_token({"authorization": "Basic abc"}))

        # Confirm email and domain helpers normalize casing and malformed inputs.
        self.assertEqual(auth._normalize_email(" USER@Example.COM "), "user@example.com")
        self.assertEqual(auth._extract_email_domain("USER@Example.COM"), "example.com")
        self.assertEqual(auth._extract_email_domain("not-an-email"), "")

        # Confirm configured rule values are trimmed and lowercased.
        self.assertEqual(auth._normalize_rule_values([" A ", "", "B "]), ["a", "b"])

        # Confirm rule matching works for both exact emails and domains.
        self.assertTrue(
            auth._email_matches_rule(
                "user@example.com",
                ["user@example.com"],
                ["other.com"],
            )
        )
        self.assertTrue(
            auth._email_matches_rule(
                "user@example.com",
                ["admin@example.org"],
                ["example.com"],
            )
        )
        self.assertFalse(auth._email_matches_rule("user@example.com", [], []))

    def test_session_signing_helpers_round_trip_and_reject_invalid_tokens(self) -> None:
        """Covers session signing, token parsing, and reconstruction helpers."""

        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000):
            # Build a deterministic stateless session token.
            token = auth._build_signed_session_token(
                "Test User",
                "test@example.com",
                "admin",
                "platform",
                "guided_sign_in",
            )

            # Confirm the encoded payload can be read back while still unexpired.
            payload = auth._read_signed_session_token(token)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["email"], "test@example.com")

            # Confirm a verified payload reconstructs a session record.
            reconstructed = auth._build_session_record_from_token(token, payload)
            self.assertIsNotNone(reconstructed)
            self.assertEqual(reconstructed.email, "test@example.com")
            self.assertEqual(reconstructed.provider, "guided_sign_in")

            # Confirm base64 helpers round-trip arbitrary bytes.
            encoded = auth._encode_token_segment(b"hello")
            self.assertEqual(auth._decode_token_segment(encoded), b"hello")

        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000):
            # Confirm malformed tokens are rejected.
            self.assertIsNone(auth._read_signed_session_token("missing-signature"))

            # Confirm tampered tokens are rejected.
            self.assertIsNone(auth._read_signed_session_token(f"{token}.tampered"))

        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000 + auth.SESSION_EXPIRATION_SECONDS + 1):
            # Confirm expired tokens are rejected after the expiration window.
            self.assertIsNone(auth._read_signed_session_token(token))

        # Confirm incomplete verified payloads do not reconstruct into sessions.
        self.assertIsNone(
            auth._build_session_record_from_token(
                "token",
                {"name": "", "email": "test@example.com", "role": "admin"},
            )
        )

    def test_session_helpers_create_lookup_and_remove_sessions(self) -> None:
        """Covers session creation, lookup, role checks, and sign-out behavior."""

        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000):
            # Create a new session using the public session helper.
            session_payload = auth.create_session("Test User", "TEST@example.com", "admin")

        session_token = session_payload["sessionToken"]
        session = auth.SESSION_STORE[session_token]

        # Confirm the public current-user payload mirrors the stored session.
        self.assertEqual(
            auth.build_current_user(session),
            {
                "name": "Test User",
                "email": "test@example.com",
                "role": "admin",
                "teamId": "default",
                "provider": "guided_sign_in",
            },
        )

        # Confirm request headers are normalized and enriched with demo identity keys.
        normalized_headers = auth.build_request_headers({"X-Test": "value"}, session)
        self.assertEqual(normalized_headers["x-test"], "value")
        self.assertEqual(normalized_headers["x-demo-user-email"], "test@example.com")

        # Confirm the session can be loaded directly from the in-memory session store.
        loaded_session = auth.get_session({"authorization": f"Bearer {session_token}"})
        self.assertIsNotNone(loaded_session)
        self.assertEqual(loaded_session.email, "test@example.com")

        # Confirm a signed token can be reconstructed even after memory storage is cleared.
        auth.SESSION_STORE.clear()
        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000 + 60):
            # Confirm signed tokens still reconstruct while the test clock is within the TTL window.
            reconstructed = auth.get_session({"authorization": f"Bearer {session_token}"})
        self.assertIsNotNone(reconstructed)
        self.assertEqual(reconstructed.name, "Test User")

        # Confirm require_session returns the session for authenticated requests.
        with patch.dict(
            os.environ,
            {"CONTROL_PANE_SESSION_SECRET": "test-secret"},
            clear=False,
        ), patch("app.auth.time.time", return_value=1000 + 60):
            # Confirm the auth guard accepts the still-valid signed token.
            required_session = auth.require_session({"authorization": f"Bearer {session_token}"})
        self.assertEqual(required_session.email, "test@example.com")

        # Confirm role checks accept admins and reject unsupported roles.
        auth.require_role(required_session, ("admin",))
        with self.assertRaises(HTTPException) as denied_error:
            auth.require_role(SessionRecord(token="t", name="N", email="e", role="viewer"), ("admin",))
        self.assertEqual(denied_error.exception.status_code, 403)

        # Confirm build_effective_settings overlays session-scoped integration values.
        effective_settings = auth.build_effective_settings(
            get_settings(),
            replace(
                required_session,
                github_owner="acme",
                github_repositories=["repo-one"],
                github_token="gh-token",
                linear_api_key="lin",
                linear_team_id="team-1",
                jira_site_url="https://acme.atlassian.net",
                jira_email="owner@example.com",
                jira_api_token="jira-token",
                jira_project_key="ACP",
                cursor_api_key="cursor-token",
                cursor_model="gpt",
                github_copilot_token="copilot-token",
                github_copilot_model="copilot-gpt",
                github_copilot_custom_agent="reviewer",
                docs_directory="docs",
            ),
        )
        self.assertEqual(effective_settings.github_owner, "acme")
        self.assertEqual(effective_settings.github_repositories, ["repo-one"])
        self.assertEqual(effective_settings.cursor_model, "gpt")
        self.assertEqual(effective_settings.github_copilot_custom_agent, "reviewer")

        # Confirm sign-out removes the session token from the in-memory store.
        auth.SESSION_STORE[session_token] = required_session
        auth.sign_out_session({"authorization": f"Bearer {session_token}"})
        self.assertNotIn(session_token, auth.SESSION_STORE)

        # Confirm unauthenticated access raises the expected HTTP error.
        with self.assertRaises(HTTPException) as missing_session_error:
            auth.require_session({})
        self.assertEqual(missing_session_error.exception.status_code, 401)

        # Confirm missing name or email is rejected during session creation.
        with self.assertRaises(HTTPException) as invalid_session_error:
            auth.create_session("", "", "admin")
        self.assertEqual(invalid_session_error.exception.status_code, 400)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
