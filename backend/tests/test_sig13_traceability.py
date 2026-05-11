"""Regression coverage for SIG-13 demo seeding and intake traceability behavior."""

import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class Sig13TraceabilityTests(unittest.TestCase):
    """Verifies the SIG-13 fixture preserves Linear-style intake status for reviewers."""

    def test_sig13_run_detail_preserves_in_progress_traceability(self) -> None:
        """Confirms the seeded SIG-13 run exposes a traceability snapshot pinned to In Progress."""

        # Load the enriched task detail payload the frontend uses on the run room page.
        detail = state.get_run_detail("sig-13", get_settings(), {})

        # Anchor the demo record to the Linear-style ticket id used in product walkthroughs.
        self.assertEqual(detail["ticket"], "SIG-13")
        # Confirm the public issue view still reflects the frozen Linear snapshot fields.
        self.assertEqual(detail["issue"]["status"], "In Progress")
        self.assertEqual(detail["issue"]["provider"], "linear")

        traceability = detail["traceability"]
        # Prove reviewers can see the intake status independent of the run-room Review state.
        self.assertEqual(traceability["issueStatusAtLaunch"], "In Progress")
        # Validate the SIG-12 snapshot flag expected by dashboard copy and reviewer panels.
        self.assertTrue(traceability["preservedFromInProgress"])

    def test_fallback_issues_keep_sig13_intake_status(self) -> None:
        """Confirms intake still exposes SIG-13 with frozen Linear snapshot fields."""

        # Force the seeded fallback catalog so CI environments with Linear env vars stay deterministic.
        with patch("app.state._list_connected_issues", return_value=[]):
            # Build the integration catalog the intake page hydrates from.
            catalog = state.get_integration_catalog(get_settings(), {})
            issues = catalog["issues"]

        # Locate the SIG-13 row even when newer SIG demo tickets sort ahead in the lobby.
        sig13_rows = [item for item in issues if str(item.get("ticket")) == "SIG-13"]
        self.assertEqual(len(sig13_rows), 1)
        # Prove fallback issue rows prefer snapshot status instead of the run lifecycle state.
        self.assertEqual(sig13_rows[0]["status"], "In Progress")
        self.assertEqual(sig13_rows[0]["provider"], "linear")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
