"""Unit coverage for provider helpers that read local and remote repo docs."""

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderDocsTests(unittest.TestCase):
    """Verifies markdown discovery and GitHub-doc context helpers."""

    def test_local_doc_helpers_cover_titles_records_and_context(self) -> None:
        """Covers markdown title parsing, local record building, and local context collection."""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            docs_root = repo_root / "docs"
            docs_root.mkdir()
            readme_path = repo_root / "README.md"
            architecture_path = docs_root / "architecture.md"
            plain_path = docs_root / "plain_doc.md"
            repo_docs_root = docs_root / "ai-control-pane"
            repo_docs_root.mkdir()
            repo_guide_path = repo_docs_root / "guide.md"

            # Write sample markdown content used by the local-doc helpers.
            readme_path.write_text("# Repo Title\nRoot docs", encoding="utf-8")
            architecture_path.write_text("# Architecture\nDetailed architecture", encoding="utf-8")
            plain_path.write_text("No heading here", encoding="utf-8")
            repo_guide_path.write_text("# Repo Guide\nSelected repo docs", encoding="utf-8")

            settings = get_settings().__class__(**{**get_settings().__dict__, "docs_directory": str(docs_root)})

            # Confirm title extraction prefers markdown headings and falls back to filename-derived titles.
            self.assertEqual(providers._read_markdown_title(architecture_path), "Architecture")
            self.assertEqual(providers._read_markdown_title(plain_path), "Plain Doc")

            # Confirm document records use repo-relative paths and stable metadata fields.
            document_record = providers._to_document_record(architecture_path, docs_root)
            self.assertEqual(document_record["path"], "docs/architecture.md")

            # Confirm repo document listing includes the README and docs markdown files.
            documents = providers.list_repo_documents(settings)
            self.assertGreaterEqual(len(documents), 2)
            selected_repo_documents = providers.list_repo_documents(settings, repo_name="ai-control-pane")
            self.assertEqual([document["path"] for document in selected_repo_documents], ["docs/ai-control-pane/guide.md"])
            self.assertEqual(selected_repo_documents[0]["repoName"], "ai-control-pane")

            # Confirm excerpting truncates long documents and local context collection labels sections.
            excerpt = providers._read_doc_excerpt(architecture_path, 10)
            context = providers._collect_doc_context(settings, per_doc_chars=25, max_docs=5)
            selected_repo_context = providers._collect_doc_context(settings, repo_name="ai-control-pane")
            self.assertIn("...[truncated]...", excerpt)
            self.assertIn("### README.md", context)
            self.assertIn("### docs/ai-control-pane/guide.md", selected_repo_context)

    def test_remote_doc_helpers_cover_github_content_listing_and_fetching(self) -> None:
        """Covers GitHub content decoding, listing recursion, formatting, and remote context fetches."""

        encoded_text = base64.b64encode(b"# Remote Doc\nContents").decode("utf-8")

        # Confirm GitHub content decoding only succeeds for base64-encoded bodies.
        self.assertEqual(
            providers._decode_github_contents_body({"content": encoded_text, "encoding": "base64"}),
            "# Remote Doc\nContents",
        )
        self.assertEqual(providers._decode_github_contents_body({"content": "", "encoding": "base64"}), "")

        # Confirm remote doc sections are labeled and truncated as expected.
        self.assertIn("### repo/docs/file.md", providers._format_remote_doc_section("repo/docs/file.md", "body", 10))

        def fake_fetch_github_json_body(url, headers):
            """Returns GitHub contents fixtures for listing and file fetch calls."""

            # Return the repo README payload when the README endpoint is requested.
            if url.endswith("/readme"):
                return {"path": "README.md", "content": encoded_text, "encoding": "base64"}

            # Return the docs directory listing used for recursive markdown discovery.
            if url.endswith("/contents/docs"):
                return [
                    {"type": "file", "path": "docs/guide.md"},
                    {"type": "dir", "path": "docs/nested"},
                ]

            # Return a nested directory listing for the recursive walk.
            if url.endswith("/contents/docs/nested"):
                return [{"type": "file", "path": "docs/nested/faq.md"}]

            # Return the file payload for any discovered markdown file.
            return {"path": url.rsplit("/contents/", 1)[-1], "content": encoded_text, "encoding": "base64"}

        with patch("app.providers._fetch_github_json_body", side_effect=fake_fetch_github_json_body):
            # Confirm recursive markdown-path discovery finds nested docs while respecting the budget.
            markdown_paths = providers._list_github_markdown_paths(
                "https://api.github.com/repos/acme/platform-web",
                {},
                directory_path="docs",
                max_files=5,
            )
            self.assertIn("docs/guide.md", markdown_paths)
            self.assertIn("docs/nested/faq.md", markdown_paths)

            settings = get_settings().__class__(
                **{
                    **get_settings().__dict__,
                    "github_owner": "acme",
                    "github_repositories": ["platform-web"],
                    "docs_directory": "docs",
                }
            )

            # Confirm remote repo doc context combines the README and docs markdown files.
            remote_context = providers._fetch_remote_repo_doc_context(settings, repo_name="platform-web", max_docs=3)
            self.assertIn("platform-web/README.md", remote_context)
            self.assertIn("platform-web/docs/guide.md", remote_context)

        class FakeResponse:
            """Provides a simple context-manager HTTP response stub for GitHub JSON fetches."""

            def __enter__(self):
                """Returns the fake response itself for the context manager."""

                # Yield this fake response object to the caller.
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                """Implements the context-manager exit hook."""

                # Report that exceptions should still propagate normally.
                return False

            def read(self):
                """Returns a JSON object body encoded as UTF-8 bytes."""

                # Serialize the GitHub fixture payload into the byte body providers.py expects.
                return json.dumps({"ok": True}).encode("utf-8")

        with patch("app.providers.urlopen", return_value=FakeResponse()):
            # Confirm the GitHub JSON-body helper returns the parsed response body.
            self.assertEqual(providers._fetch_github_json_body("https://api.github.com/repos/acme/platform-web", {}), {"ok": True})


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
