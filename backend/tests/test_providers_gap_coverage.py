"""Additional coverage for provider helper guard branches."""

import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.error import URLError
from unittest.mock import patch

from app import providers
from app.config import get_settings


class ProviderGapCoverageTests(unittest.TestCase):
    """Verifies the remaining uncovered provider helper branches."""

    def test_request_and_connection_helpers_cover_remaining_error_paths(self) -> None:
        """Covers low-level request helpers plus connection-check guard branches."""

        class FakeResponse:
            """Provides a minimal context-manager HTTP response stub."""

            def __init__(self, payload):
                """Stores the response payload for later reads."""

                # Preserve the JSON payload so read() can serialize it.
                self.payload = payload

            def __enter__(self):
                """Returns the fake response for the context-manager body."""

                # Yield the response object to the helper under test.
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                """Allows exceptions to propagate out of the context manager."""

                # Report that any exception should still bubble up.
                return False

            def read(self):
                """Returns the encoded JSON response body."""

                # Serialize the stored payload into the byte body providers.py expects.
                return json.dumps(self.payload).encode("utf-8")

        with patch("app.provider_common.urlopen", return_value=FakeResponse({"ok": True})):
            # Confirm JSON requests support both caller headers and JSON body payloads.
            self.assertEqual(
                providers._request_json(
                    "https://example.test/providers",
                    method="POST",
                    headers={"X-Test": "1"},
                    payload={"value": 1},
                ),
                {"ok": True},
            )

        unreadable_error = HTTPError(
            url="https://example.test/providers",
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=io.BytesIO(b"not-json"),
        )

        # Confirm unreadable provider errors fall back to the status text.
        self.assertEqual(providers._extract_provider_error_message(unreadable_error), "502 Bad Gateway")

        nested_error = HTTPError(
            url="https://example.test/providers",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"errors":[{"message":"Nested provider message"}]}'),
        )

        # Confirm nested provider error lists are flattened into the first readable message.
        self.assertEqual(providers._extract_provider_error_message(nested_error), "Nested provider message")

        no_message_error = HTTPError(
            url="https://example.test/providers",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"errors":[{}]}'),
        )

        # Confirm provider payloads without any readable message fall back to the status text.
        self.assertEqual(providers._extract_provider_error_message(no_message_error), "400 Bad Request")

        # Confirm Linear connectivity fails fast when no API key is configured.
        self.assertFalse(providers.is_linear_connected(get_settings()))

        with patch("app.provider_linear._request_json", return_value={"data": []}):
            # Confirm malformed Linear data payloads are rejected.
            self.assertFalse(providers.is_linear_connected(get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin"})))

        with patch("app.provider_linear._request_json", return_value={"data": {"viewer": []}}):
            # Confirm malformed Linear viewer payloads are rejected.
            self.assertFalse(providers.is_linear_connected(get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin"})))

        with patch("app.provider_linear._request_json", side_effect=URLError("offline")):
            # Confirm Linear connectivity fails safely when the provider cannot be reached.
            self.assertFalse(providers.is_linear_connected(get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin"})))

        with patch("app.provider_cursor._request_json", side_effect=URLError("offline")):
            # Confirm Cursor connectivity fails safely when the provider cannot be reached.
            self.assertFalse(providers.is_cursor_connected(get_settings().__class__(**{**get_settings().__dict__, "cursor_api_key": "cursor"})))

        # Confirm Jira JSON requests short-circuit when credentials are incomplete.
        self.assertIsNone(providers._request_jira_json(get_settings(), path="/myself"))

        with patch("app.provider_jira._request_json", side_effect=HTTPError("https://example.test", 500, "Boom", None, io.BytesIO(b"{}"))):
            # Confirm Jira JSON requests return no payload when Jira rejects the call.
            self.assertIsNone(
                providers._request_jira_json(
                    get_settings().__class__(
                        **{
                            **get_settings().__dict__,
                            "jira_site_url": "https://acme.atlassian.net",
                            "jira_email": "owner@example.com",
                            "jira_api_token": "token",
                        }
                    ),
                    path="/myself",
                )
            )

        # Confirm Jira transition requests short-circuit when credentials are incomplete.
        self.assertFalse(providers._request_jira_transition_update(get_settings(), issue_id="100", transition_id="1"))

        with patch("app.provider_jira.urlopen", side_effect=URLError("offline")):
            # Confirm Jira transition updates fail safely when the provider request errors.
            self.assertFalse(
                providers._request_jira_transition_update(
                    get_settings().__class__(
                        **{
                            **get_settings().__dict__,
                            "jira_site_url": "https://acme.atlassian.net",
                            "jira_email": "owner@example.com",
                            "jira_api_token": "token",
                        }
                    ),
                    issue_id="100",
                    transition_id="1",
                )
            )

        # Confirm Linear GraphQL requests short-circuit when no API key is configured.
        self.assertIsNone(providers._request_linear_graphql(get_settings(), query="query Viewer { viewer { id } }"))

        with patch("app.provider_linear._request_json", side_effect=URLError("offline")):
            # Confirm Linear GraphQL requests fail safely when Linear rejects the request.
            self.assertIsNone(
                providers._request_linear_graphql(
                    get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin"}),
                    query="query Viewer { viewer { id } }",
                )
            )

    def test_linear_and_jira_helpers_cover_remaining_extraction_and_update_branches(self) -> None:
        """Covers Linear and Jira extraction helpers plus update guard branches."""

        # Confirm malformed Linear issue envelopes return no nodes.
        self.assertIsNone(providers._extract_linear_issue_nodes({"data": {"issues": []}}))
        self.assertIsNone(providers._extract_linear_issue_nodes({"data": {"issues": {"nodes": "bad"}}}))

        # Confirm malformed Linear team envelopes return no team node.
        self.assertIsNone(providers._extract_linear_team_node({"data": []}))
        self.assertIsNone(providers._extract_linear_team_node({"data": {"teams": []}}))
        self.assertIsNone(providers._extract_linear_team_node({"data": {"teams": {"nodes": ["bad-node"]}}}))

        # Confirm malformed team-scoped issue payloads return no nodes.
        self.assertIsNone(providers._extract_linear_team_issue_nodes({"data": []}))
        self.assertIsNone(providers._extract_linear_team_issue_nodes({"data": {"team": []}}))
        self.assertIsNone(providers._extract_linear_team_issue_nodes({"data": {"team": {"issues": []}}}))
        self.assertIsNone(providers._extract_linear_team_issue_nodes({"data": {"team": {"issues": {"nodes": "bad"}}}}))

        # Confirm malformed Linear issue-state catalogs are rejected at every envelope level.
        self.assertIsNone(providers._extract_linear_issue_state_catalog({"data": []}))
        self.assertIsNone(providers._extract_linear_issue_state_catalog({"data": {"issue": []}}))
        self.assertIsNone(providers._extract_linear_issue_state_catalog({"data": {"issue": {"team": []}}}))
        self.assertIsNone(providers._extract_linear_issue_state_catalog({"data": {"issue": {"team": {"states": []}}}}))
        self.assertIsNone(providers._extract_linear_issue_state_catalog({"data": {"issue": {"team": {"states": {"nodes": "bad"}}}}}))
        self.assertIsNone(
            providers._extract_linear_issue_state_catalog(
                {"data": {"issue": {"state": "bad", "team": {"states": {"nodes": []}}}}}
            )
        )

        # Confirm missing Linear state matches return no node.
        self.assertIsNone(providers._find_linear_state_node([{"id": "1", "name": "Backlog", "type": "backlog"}], "Done"))

        settings = get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin"})

        # Confirm invalid Linear update requests are rejected before any provider calls.
        self.assertFalse(providers.update_linear_issue_status(settings, issue_id=" ", status_name="Done"))

        with patch("app.provider_linear._request_linear_graphql", return_value=None):
            # Confirm Linear updates stop when the state catalog cannot be loaded.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        with patch("app.provider_linear._request_linear_graphql", return_value={"data": {}}), patch(
            "app.provider_linear._extract_linear_issue_state_catalog",
            return_value=None,
        ):
            # Confirm Linear updates stop when the state catalog cannot be normalized.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        with patch("app.provider_linear._request_linear_graphql", return_value={"data": {}}), patch(
            "app.provider_linear._extract_linear_issue_state_catalog",
            return_value={"currentState": {}, "teamStates": []},
        ), patch(
            "app.provider_linear._find_linear_state_node",
            return_value=None,
        ):
            # Confirm Linear updates stop when the team has no matching target state.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        with patch(
            "app.provider_linear._request_linear_graphql",
            side_effect=[
                {"data": {"issue": {"id": "issue-1"}}},
                None,
            ],
        ), patch(
            "app.provider_linear._extract_linear_issue_state_catalog",
            return_value={"currentState": {"id": "current"}, "teamStates": [{"id": "target"}]},
        ), patch(
            "app.provider_linear._find_linear_state_node",
            return_value={"id": "target"},
        ):
            # Confirm Linear updates stop when the mutation response is missing.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        with patch(
            "app.provider_linear._request_linear_graphql",
            side_effect=[
                {"data": {"issue": {"id": "issue-1"}}},
                {"data": []},
            ],
        ), patch(
            "app.provider_linear._extract_linear_issue_state_catalog",
            return_value={"currentState": {"id": "current"}, "teamStates": [{"id": "target"}]},
        ), patch(
            "app.provider_linear._find_linear_state_node",
            return_value={"id": "target"},
        ):
            # Confirm Linear updates stop when the mutation data envelope is malformed.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        with patch(
            "app.provider_linear._request_linear_graphql",
            side_effect=[
                {"data": {"issue": {"id": "issue-1"}}},
                {"data": {"issueUpdate": []}},
            ],
        ), patch(
            "app.provider_linear._extract_linear_issue_state_catalog",
            return_value={"currentState": {"id": "current"}, "teamStates": [{"id": "target"}]},
        ), patch(
            "app.provider_linear._find_linear_state_node",
            return_value={"id": "target"},
        ):
            # Confirm Linear updates stop when the issueUpdate payload is malformed.
            self.assertFalse(providers.update_linear_issue_status(settings, issue_id="issue-1", status_name="Done"))

        # Confirm Jira descriptions flatten list content and unknown shapes safely.
        self.assertEqual(
            providers._extract_jira_description_text(["Hello", {"content": [{"text": "World"}]}]),
            "Hello\nWorld",
        )
        self.assertEqual(providers._extract_jira_description_text(object()), "")

        jira_settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "jira_site_url": "https://acme.atlassian.net",
                "jira_email": "owner@example.com",
                "jira_api_token": "token",
                "jira_project_key": "ACP",
            }
        )

        # Confirm malformed Jira issue payloads return no issues.
        with patch("app.provider_jira._request_jira_json", return_value={"issues": "bad"}):
            self.assertEqual(providers.list_jira_issues(jira_settings), [])

        with patch(
            "app.provider_jira._request_jira_json",
            return_value={
                "issues": [
                    "bad-row",
                    {"id": "jira-1", "key": "ACP-1", "fields": "bad-fields"},
                ]
            },
        ):
            # Confirm malformed Jira rows and fields are skipped instead of breaking the catalog.
            self.assertEqual(providers.list_jira_issues(jira_settings), [])

        # Confirm missing Jira status categories flatten to an empty label.
        self.assertEqual(providers._extract_jira_status_category_name({"statusCategory": "bad"}), "")

        # Confirm unmatched Jira transitions return no transition.
        self.assertIsNone(
            providers._find_jira_transition(
                [{"name": "Move", "to": "bad"}],
                "Done",
            )
        )

        # Confirm invalid Jira update requests are rejected before any provider calls.
        self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id=" ", status_name="Done"))

        with patch("app.provider_jira._request_jira_json", return_value=None):
            # Confirm Jira updates stop when the current issue state cannot be loaded.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch("app.provider_jira._request_jira_json", return_value={"fields": []}):
            # Confirm Jira updates stop when the fields envelope is malformed.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch("app.provider_jira._request_jira_json", return_value={"fields": {"status": []}}):
            # Confirm Jira updates stop when the status payload is malformed.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch(
            "app.provider_jira._request_jira_json",
            side_effect=[
                {"fields": {"status": {"name": "In Progress"}}},
                None,
            ],
        ):
            # Confirm Jira updates stop when transitions cannot be loaded.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch(
            "app.provider_jira._request_jira_json",
            side_effect=[
                {"fields": {"status": {"name": "In Progress"}}},
                {"transitions": "bad"},
            ],
        ):
            # Confirm Jira updates stop when the transitions payload is malformed.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch(
            "app.provider_jira._request_jira_json",
            side_effect=[
                {"fields": {"status": {"name": "In Progress"}}},
                {"transitions": [{"id": "1", "name": "Move"}]},
            ],
        ), patch(
            "app.provider_jira._find_jira_transition",
            return_value=None,
        ):
            # Confirm Jira updates stop when there is no matching transition.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch(
            "app.provider_jira._request_jira_json",
            side_effect=[
                {"fields": {"status": {"name": "In Progress"}}},
                {"transitions": [{"id": "", "name": "Done"}]},
            ],
        ), patch(
            "app.provider_jira._find_jira_transition",
            return_value={"id": ""},
        ):
            # Confirm Jira updates stop when the matched transition lacks an ID.
            self.assertFalse(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        with patch(
            "app.provider_jira._request_jira_json",
            return_value={"fields": {"status": {"name": "Custom Done", "statusCategory": {"name": "Done"}}}},
        ):
            # Confirm Jira updates short-circuit successfully when the status category already matches.
            self.assertTrue(providers.update_jira_issue_status(jira_settings, issue_id="jira-1", status_name="Done"))

        scoped_linear_settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "linear_api_key": "lin",
                "linear_team_id": "ENG",
            }
        )

        with patch(
            "app.provider_linear._request_json",
            side_effect=[URLError("offline"), URLError("offline"), URLError("offline")],
        ):
            # Confirm team lookup failures fall back to an empty Linear issue list.
            self.assertEqual(providers.list_linear_issues(scoped_linear_settings), [])

        with patch(
            "app.provider_linear._request_json",
            side_effect=[
                {"data": {"teams": {"nodes": [{"id": "team-1"}]}}},
                URLError("offline"),
            ],
        ):
            # Confirm team-scoped issue fetch failures fall back to an empty Linear issue list.
            self.assertEqual(providers.list_linear_issues(scoped_linear_settings), [])

        with patch(
            "app.provider_linear._request_json",
            side_effect=[
                {"data": {"teams": {"nodes": [{"id": "team-1"}]}}},
                {"data": {"team": {}}},
            ],
        ), patch(
            "app.provider_linear._extract_linear_team_issue_nodes",
            return_value=None,
        ):
            # Confirm malformed team-scoped issue payloads fall back to an empty Linear issue list.
            self.assertEqual(providers.list_linear_issues(scoped_linear_settings), [])

        with patch("app.provider_linear._request_json", side_effect=URLError("offline")):
            # Confirm unscoped issue fetch failures fall back to an empty Linear issue list.
            self.assertEqual(
                providers.list_linear_issues(
                    get_settings().__class__(**{**get_settings().__dict__, "linear_api_key": "lin", "linear_team_id": ""})
                ),
                [],
            )

    def test_document_and_github_helpers_cover_remaining_edge_cases(self) -> None:
        """Covers repo-doc and GitHub helper branches that were still missing."""

        # Confirm unreadable markdown files fall back to a title derived from the filename.
        self.assertEqual(providers._read_markdown_title(Path("docs/test-file.md")), "Test File")

        # Confirm missing docs directories produce no repo-doc records.
        self.assertEqual(
            providers.list_repo_documents(get_settings().__class__(**{**get_settings().__dict__, "docs_directory": "missing-docs"})),
            [],
        )

        github_settings = get_settings().__class__(
            **{
                **get_settings().__dict__,
                "github_owner": "acme",
                "github_repositories": ["repo-one", "repo-two"],
                "github_token": "gh-token",
            }
        )

        with patch(
            "app.provider_github._request_json",
            side_effect=[
                HTTPError("https://example.test/repo-one", 404, "Not Found", None, io.BytesIO(b"{}")),
                {"id": "2", "name": "repo-two", "full_name": "acme/repo-two", "html_url": "https://github.com/acme/repo-two"},
            ],
        ):
            # Confirm GitHub repository listing skips repos that cannot be fetched.
            repositories = providers.list_github_repositories(github_settings)
        self.assertEqual([repository["name"] for repository in repositories], ["repo-two"])

        # Confirm unreadable repo-doc excerpts are skipped cleanly.
        self.assertEqual(providers._read_doc_excerpt(Path("missing-doc.md"), 50), "")

        # Confirm invalid GitHub contents payloads decode to an empty string.
        self.assertEqual(providers._decode_github_contents_body({"encoding": "plain", "content": "text"}), "")
        with patch("app.provider_openai.base64.b64decode", side_effect=ValueError("bad-base64")):
            # Confirm malformed base64 payloads are swallowed during GitHub content decoding.
            self.assertEqual(providers._decode_github_contents_body({"encoding": "base64", "content": "!!!"}), "")

        # Confirm the recursive GitHub markdown lister short-circuits invalid input and provider failures.
        self.assertEqual(
            providers._list_github_markdown_paths("https://api.github.com/repos/acme/repo", {}, directory_path="", max_files=3),
            [],
        )

        with patch("app.provider_openai._fetch_github_json_body", side_effect=URLError("offline")):
            self.assertEqual(
                providers._list_github_markdown_paths(
                    "https://api.github.com/repos/acme/repo",
                    {},
                    directory_path="docs",
                    max_files=3,
                ),
                [],
            )

        with patch(
            "app.provider_openai._fetch_github_json_body",
            return_value={"path": "docs/README.md", "type": "file"},
        ):
            # Confirm single-file GitHub listings are still treated as markdown candidates.
            self.assertEqual(
                providers._list_github_markdown_paths(
                    "https://api.github.com/repos/acme/repo",
                    {},
                    directory_path="docs",
                    max_files=3,
                ),
                ["docs/README.md"],
            )

        with patch(
            "app.provider_openai._fetch_github_json_body",
            return_value=["bad-entry", {"type": "file", "path": ""}, {"type": "file", "path": "docs/guide.md"}],
        ):
            # Confirm malformed GitHub directory entries are ignored during traversal.
            self.assertEqual(
                providers._list_github_markdown_paths(
                    "https://api.github.com/repos/acme/repo",
                    {},
                    directory_path="docs",
                    max_files=3,
                ),
                ["docs/guide.md"],
            )

        with patch(
            "app.provider_openai._fetch_github_json_body",
            return_value=[
                {"type": "file", "path": "docs/one.md"},
                {"type": "file", "path": "docs/two.md"},
            ],
        ):
            # Confirm the GitHub markdown walker stops once it reaches the requested file budget.
            self.assertEqual(
                providers._list_github_markdown_paths(
                    "https://api.github.com/repos/acme/repo",
                    {},
                    directory_path="docs",
                    max_files=1,
                ),
                ["docs/one.md"],
            )

        # Confirm long remote docs are truncated into bounded prompt sections.
        self.assertIn("...[truncated]...", providers._format_remote_doc_section("docs/guide.md", "a" * 20, 5))

        settings = get_settings().__class__(**{**get_settings().__dict__, "github_owner": "acme"})

        # Confirm remote repo-doc collection short-circuits without a repo name.
        self.assertEqual(providers._fetch_remote_repo_doc_context(settings, repo_name=""), "")

        encoded_readme = base64.b64encode(b"# Repo Readme").decode("utf-8")
        encoded_doc = base64.b64encode(b"Guide text").decode("utf-8")

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                HTTPError("https://example.test/readme", 404, "Not Found", None, io.BytesIO(b"{}")),
                {"encoding": "base64", "content": encoded_doc},
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/guide.md"],
        ):
            # Confirm missing READMEs do not block remote doc context collection.
            remote_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=2)
        self.assertIn("repo/docs/guide.md", remote_context)

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                HTTPError("https://example.test/readme", 404, "Not Found", None, io.BytesIO(b"{}")),
                {"encoding": "base64", "content": encoded_doc},
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/guide.md", "docs/extra.md"],
        ):
            # Confirm remote doc collection stops once the requested max-doc budget has been reached.
            bounded_remote_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=1)
        self.assertEqual(bounded_remote_context.count("### "), 1)

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                {"path": "README.md", "encoding": "base64", "content": encoded_readme},
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/one.md", "docs/two.md"],
        ):
            # Confirm the file loop respects the max-doc budget even if the listing overshoots it.
            budgeted_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=1)
        self.assertEqual(budgeted_context.count("### "), 1)

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                {"path": "README.md", "encoding": "base64", "content": encoded_readme},
                HTTPError("https://example.test/docs/guide.md", 500, "Boom", None, io.BytesIO(b"{}")),
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/guide.md"],
        ):
            # Confirm unreadable remote files are skipped without failing the whole context build.
            skip_error_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=2)
        self.assertIn("repo/README.md", skip_error_context)

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                {"path": "README.md", "encoding": "base64", "content": encoded_readme},
                ["bad-payload"],
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/guide.md"],
        ):
            # Confirm non-dict file payloads are ignored during remote doc collection.
            non_dict_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=2)
        self.assertIn("repo/README.md", non_dict_context)

        with patch(
            "app.provider_openai._fetch_github_json_body",
            side_effect=[
                {"path": "README.md", "encoding": "base64", "content": encoded_readme},
                {"encoding": "base64", "content": base64.b64encode(b"").decode("utf-8")},
            ],
        ), patch(
            "app.provider_openai._list_github_markdown_paths",
            return_value=["docs/empty.md"],
        ):
            # Confirm empty remote file bodies are ignored during context collection.
            empty_body_context = providers._fetch_remote_repo_doc_context(settings, repo_name="repo", max_docs=2)
        self.assertNotIn("repo/docs/empty.md", empty_body_context)

        # Confirm local doc-context collection short-circuits when the docs directory is missing.
        self.assertEqual(
            providers._collect_doc_context(get_settings().__class__(**{**get_settings().__dict__, "docs_directory": "missing-docs"})),
            "",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            docs_root = Path(temp_dir) / "docs"
            docs_root.mkdir()
            readme_path = Path(temp_dir) / "README.md"
            readme_path.write_text("# Readme", encoding="utf-8")
            guide_path = docs_root / "guide.md"
            guide_path.write_text("# Guide", encoding="utf-8")

            with patch(
                "app.provider_openai._read_doc_excerpt",
                side_effect=["", "Guide body"],
            ), patch(
                "app.provider_openai.Path.relative_to",
                side_effect=ValueError("outside docs parent"),
            ):
                # Confirm empty local excerpts are skipped and relative-path fallbacks use the filename.
                local_context = providers._collect_doc_context(
                    get_settings().__class__(**{**get_settings().__dict__, "docs_directory": str(docs_root)}),
                    max_docs=2,
                )
        self.assertIn("### guide.md", local_context)


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
