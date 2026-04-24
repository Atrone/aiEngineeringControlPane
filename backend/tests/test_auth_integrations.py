"""Unit coverage for auth-driven integration connection helpers."""

import unittest

from fastapi import HTTPException

from app.auth import SessionRecord
from app.auth import connect_cursor
from app.auth import connect_docs
from app.auth import connect_github
from app.auth import connect_jira
from app.auth import connect_linear


class AuthIntegrationConnectionTests(unittest.TestCase):
    """Verifies the session mutation helpers for guided integration setup."""

    def _build_session(self) -> SessionRecord:
        """Builds a fresh session record for guided integration tests."""

        # Return a minimal admin session that can be mutated by connection helpers.
        return SessionRecord(
            token="session-token",
            name="Test User",
            email="test@example.com",
            role="admin",
        )

    def test_connect_github_saves_owner_repositories_and_token(self) -> None:
        """Covers the GitHub guided-setup helper for valid and invalid inputs."""

        session = self._build_session()

        # Confirm valid GitHub inputs are saved onto the session in normalized form.
        connect_github(session, " acme ", " repo-one , repo-two ", " gh-token ")
        self.assertEqual(session.github_owner, "acme")
        self.assertEqual(session.github_repositories, ["repo-one", "repo-two"])
        self.assertEqual(session.github_token, "gh-token")

        # Confirm incomplete GitHub inputs are rejected before mutating the session.
        with self.assertRaises(HTTPException) as github_error:
            connect_github(self._build_session(), "", "", "")
        self.assertEqual(github_error.exception.status_code, 400)

    def test_connect_linear_saves_normalized_credentials(self) -> None:
        """Covers the Linear guided-setup helper for valid and invalid inputs."""

        session = self._build_session()

        # Confirm bearer-prefixed keys are normalized before storage.
        connect_linear(session, " Bearer lin_api_key ", " team-1 ")
        self.assertEqual(session.linear_api_key, "lin_api_key")
        self.assertEqual(session.linear_team_id, "team-1")

        # Confirm missing Linear keys are rejected before mutating the session.
        with self.assertRaises(HTTPException) as linear_error:
            connect_linear(self._build_session(), "   ", "")
        self.assertEqual(linear_error.exception.status_code, 400)

    def test_connect_jira_saves_normalized_credentials(self) -> None:
        """Covers the Jira guided-setup helper for valid and invalid inputs."""

        session = self._build_session()

        # Confirm Jira URL, email, token, and project key are normalized before storage.
        connect_jira(
            session,
            " acme.atlassian.net/ ",
            " USER@example.com ",
            " jira-token ",
            " acp ",
        )
        self.assertEqual(session.jira_site_url, "https://acme.atlassian.net")
        self.assertEqual(session.jira_email, "user@example.com")
        self.assertEqual(session.jira_api_token, "jira-token")
        self.assertEqual(session.jira_project_key, "ACP")

        # Confirm incomplete Jira values are rejected before mutating the session.
        with self.assertRaises(HTTPException) as jira_error:
            connect_jira(self._build_session(), "", "", "", "")
        self.assertEqual(jira_error.exception.status_code, 400)

    def test_connect_cursor_and_docs_save_expected_session_values(self) -> None:
        """Covers the Cursor and docs guided-setup helpers for valid and invalid inputs."""

        session = self._build_session()

        # Confirm the Cursor key and model are normalized before storage.
        connect_cursor(session, " Bearer cursor-key ", "")
        self.assertEqual(session.cursor_api_key, "cursor-key")
        self.assertEqual(session.cursor_model, "default")

        # Confirm the docs directory is stored in trimmed form.
        connect_docs(session, " docs/reference ")
        self.assertEqual(session.docs_directory, "docs/reference")

        # Confirm missing Cursor keys are rejected before mutating the session.
        with self.assertRaises(HTTPException) as cursor_error:
            connect_cursor(self._build_session(), "", "model")
        self.assertEqual(cursor_error.exception.status_code, 400)

        # Confirm missing docs directories are rejected before mutating the session.
        with self.assertRaises(HTTPException) as docs_error:
            connect_docs(self._build_session(), " ")
        self.assertEqual(docs_error.exception.status_code, 400)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
