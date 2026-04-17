"""Regression coverage for Linear-linked Cursor agent prompts and review traceability."""

import unittest

from app import state


class CursorPromptLinearTraceabilityTests(unittest.TestCase):
    """Verifies Linear issue metadata flows into Cursor prompts for SIG-style review handoffs."""

    def _minimal_repository(self) -> dict:
        """Returns a stub GitHub repository record for prompt composition."""

        # Mirror the fields _build_cursor_prompt reads from the repository catalog.
        return {
            "fullName": "acme/platform-web",
            "name": "platform-web",
            "url": "https://github.com/acme/platform-web",
            "defaultBranch": "main",
        }

    def _minimal_run(self) -> dict:
        """Returns a stub run record with task fields used by the Cursor prompt builder."""

        # Keep only the keys the prompt builder touches for this focused assertion.
        return {
            "repo": "platform-web",
            "summary": "Stub summary",
            "_taskPrompt": "Implement the requested change set.",
            "_acceptanceCriteria": "Deliver with review evidence and traceability.",
        }

    def test_build_cursor_prompt_includes_issue_url_and_intake_status_for_linear(self) -> None:
        """Surfaces Linear URLs and intake status so agents can anchor review evidence."""

        issue = {
            "id": "issue-sig-5",
            "ticket": "SIG-5",
            "title": "Issue",
            "description": "Issue",
            "priority": "3",
            "status": "Todo",
            "url": "https://linear.app/acme/issue/SIG-5",
            "assignee": {"name": "Anthony T"},
            "provider": "linear",
        }
        prompt_text = state._build_cursor_prompt(
            self._minimal_run(),
            issue=issue,
            documents=[],
            repository=self._minimal_repository(),
        )

        # Confirm the deeplink is visible for reviewers and downstream automation.
        self.assertIn("Issue URL: https://linear.app/acme/issue/SIG-5", prompt_text)
        # Confirm the intake-time workflow label is preserved for traceability from Todo.
        self.assertIn("Issue status at intake: Todo.", prompt_text)
        # Confirm the default handoff path references branch and pull request alignment.
        self.assertIn("Git branch name", prompt_text)
        self.assertIn("Linear review traceability", prompt_text)

    def test_build_cursor_prompt_warns_when_linear_issue_already_terminal(self) -> None:
        """Steers agents toward evidence-first review when the ticket already looks shipped."""

        issue = {
            "id": "issue-done",
            "ticket": "SIG-99",
            "title": "Already shipped",
            "description": "Cleanup",
            "priority": "2",
            "status": "Done",
            "url": "https://linear.app/acme/issue/SIG-99",
            "assignee": {},
            "provider": "linear",
        }
        prompt_text = state._build_cursor_prompt(
            self._minimal_run(),
            issue=issue,
            documents=[],
            repository=self._minimal_repository(),
        )

        # Confirm the terminal-state guidance replaces the default open-workflow handoff.
        self.assertIn("Issue status at intake: Done.", prompt_text)
        self.assertIn("already in an intake state that typically means", prompt_text)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
