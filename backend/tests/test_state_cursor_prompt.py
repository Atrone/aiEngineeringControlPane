"""Unit coverage for state helper functions that build run/task context."""

import unittest

from app import state


class StateCursorPromptTests(unittest.TestCase):
    """Verifies cursor-prompt and catalog-selection helpers in state.py."""

    def test_catalog_selection_and_prompt_helpers_cover_expected_behavior(self) -> None:
        """Covers slugging, issue/repo lookup, doc selection, and Cursor prompt helpers."""

        issues = [
            {"id": "issue-1", "ticket": "ACP-1", "title": "First issue"},
            {"id": "issue-2", "ticket": "ACP-2", "title": "Second issue"},
        ]
        repositories = [
            {"name": "platform-web", "fullName": "acme/platform-web", "url": "https://github.com/acme/platform-web"}
        ]
        documents = [
            {"id": "doc-1", "path": "docs/architecture.md", "title": "Architecture"},
            {"id": "doc-2", "path": "docs/testing.md", "title": "Testing"},
        ]

        # Confirm slugging normalizes punctuation and falls back when no slug is possible.
        self.assertEqual(state._slugify("Ship This Feature!"), "ship-this-feature")
        self.assertEqual(state._slugify("!!!"), "generated-task")

        # Confirm issue, repository, and selected-document helpers return the expected records.
        self.assertEqual(state._find_issue(issues, "issue-2")["ticket"], "ACP-2")
        self.assertIsNone(state._find_issue(issues, None))
        self.assertEqual(state._find_repository(repositories, " platform-web ")["fullName"], "acme/platform-web")
        self.assertEqual(state._select_documents(documents, ["doc-2"]), [documents[1]])

        issue = {
            "ticket": "ACP-2",
            "title": "Second issue",
            "status": "Todo",
            "priority": "1",
            "provider": "linear",
            "url": "https://linear.example.com/issue/ACP-2",
            "assignee": {"name": "Maya"},
            "description": "Build a richer Cursor prompt.",
        }

        # Confirm issue and docs blocks capture the available context in readable text.
        issue_block = state._build_cursor_issue_block(issue)
        docs_block = state._build_cursor_docs_block(documents)
        empty_docs_block = state._build_cursor_docs_block([])
        self.assertIn("Ticket: ACP-2", issue_block)
        self.assertIn("Assignee: Maya", issue_block)
        self.assertIn("Issue URL: https://linear.example.com/issue/ACP-2", issue_block)
        self.assertIn("docs/testing.md", docs_block)
        self.assertIn("No repo markdown documents were attached", empty_docs_block)

        run = {
            "repo": "platform-web",
            "summary": "Fallback summary",
            "_taskPrompt": "Implement the requested feature.",
            "_acceptanceCriteria": "- [ ] Add tests",
        }

        # Confirm the full Cursor prompt weaves together repo, issue, task, and docs context.
        prompt_text = state._build_cursor_prompt(
            run,
            issue=issue,
            documents=documents,
            repository=repositories[0],
        )
        self.assertIn("acme/platform-web", prompt_text)
        self.assertIn("Second issue", prompt_text)
        self.assertIn("docs/testing.md", prompt_text)
        self.assertTrue(prompt_text.endswith("git diff origin/main...HEAD"))
        self.assertNotIn("artifacts/evidence.md", prompt_text)

        run_with_sync_markers = {"_linearSyncedStatusName": "Done", "_jiraSyncedStatusName": "Done"}

        # Confirm sync-marker cleanup removes both tracker-specific cache keys.
        state._clear_issue_tracker_sync_state(run_with_sync_markers)
        self.assertNotIn("_linearSyncedStatusName", run_with_sync_markers)
        self.assertNotIn("_jiraSyncedStatusName", run_with_sync_markers)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
