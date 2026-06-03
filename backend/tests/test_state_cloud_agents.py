"""Unit coverage for cloud-agent payload helpers in state_cloud_agents.py."""

import unittest

from app import state_cloud_agents


class StateCloudAgentTests(unittest.TestCase):
    """Verifies cloud-agent target extraction and merge helpers."""

    def test_extract_cloud_agent_target_normalizes_mapping_payloads(self) -> None:
        """Covers state_cloud_agents._extract_cloud_agent_target."""

        # Confirm structured target payloads are copied into a mutable mapping.
        self.assertEqual(
            state_cloud_agents._extract_cloud_agent_target({"target": {"prUrl": "https://github.com/acme/repo/pull/1"}}),
            {"prUrl": "https://github.com/acme/repo/pull/1"},
        )

        # Confirm malformed target values collapse to an empty mapping.
        self.assertEqual(state_cloud_agents._extract_cloud_agent_target({"target": "bad"}), {})
        self.assertEqual(state_cloud_agents._extract_cloud_agent_target({}), {})

    def test_merge_cloud_agent_update_preserves_pr_target_metadata(self) -> None:
        """Covers state_cloud_agents._merge_cloud_agent_update."""

        previous_agent = {
            "id": "agent-1",
            "status": "RUNNING",
            "target": {"prUrl": "https://github.com/acme/repo/pull/1"},
        }
        latest_without_target = {"id": "agent-1", "status": "FINISHED", "target": None}

        # Confirm later polls without target metadata keep the launch-time PR URL.
        merged_agent = state_cloud_agents._merge_cloud_agent_update(previous_agent, latest_without_target)
        self.assertEqual(merged_agent["status"], "FINISHED")
        self.assertEqual(merged_agent["target"]["prUrl"], "https://github.com/acme/repo/pull/1")

        latest_with_target = {
            "id": "agent-1",
            "status": "FINISHED",
            "target": {"prUrl": "https://github.com/acme/repo/pull/2"},
        }

        # Confirm fresh target metadata replaces the previous PR URL when present.
        self.assertEqual(
            state_cloud_agents._merge_cloud_agent_update(previous_agent, latest_with_target)["target"]["prUrl"],
            "https://github.com/acme/repo/pull/2",
        )


if __name__ == "__main__":
    unittest.main()
