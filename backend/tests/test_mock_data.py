"""Unit coverage for demo mock-data payload helpers."""

import unittest

from app import mock_data


class MockDataHelpersTests(unittest.TestCase):
    """Verifies the mock data module returns safe copied payloads."""

    def test_dashboard_approval_and_policy_payloads_return_copied_data(self) -> None:
        """Covers the dashboard, approval, and policy mock payload builders."""

        # Confirm the dashboard payload returns copied nested structures.
        dashboard_payload = mock_data.get_dashboard_payload()
        self.assertIn("metrics", dashboard_payload)
        self.assertIn("runs", dashboard_payload)
        dashboard_payload["runs"][0]["title"] = "Mutated title"
        self.assertNotEqual(mock_data.RUN_SUMMARIES[0]["title"], "Mutated title")

        # Confirm the approval payload includes a summary, queue, and copied runs.
        approval_payload = mock_data.get_approval_payload()
        self.assertEqual(approval_payload["summary"]["queueSize"], 7)
        approval_payload["queue"][0]["runId"] = "mutated"
        self.assertNotEqual(mock_data.APPROVAL_QUEUE[0]["runId"], "mutated")

        # Confirm the policy payload exposes the expected scope, version, and copied rules.
        policy_payload = mock_data.get_policy_payload()
        self.assertEqual(policy_payload["scope"], "web-app")
        self.assertEqual(policy_payload["version"], "3.1")
        policy_payload["rules"][0]["name"] = "Mutated"
        self.assertNotEqual(mock_data.POLICY_RULES[0]["name"], "Mutated")

    def test_get_run_by_id_returns_a_copy_and_raises_for_missing_runs(self) -> None:
        """Covers the run lookup helper for both hit and miss paths."""

        # Confirm the run lookup returns a copied record for a known run ID.
        run_payload = mock_data.get_run_by_id("acp-142")
        self.assertEqual(run_payload["ticket"], "ACP-142")
        run_payload["title"] = "Changed"
        self.assertNotEqual(mock_data.RUN_SUMMARIES[0]["title"], "Changed")

        # Confirm unknown run IDs raise a key error for the API layer to translate.
        with self.assertRaises(KeyError):
            mock_data.get_run_by_id("missing-run")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
