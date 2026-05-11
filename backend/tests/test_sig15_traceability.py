"""Regression coverage for SIG-15 demo seeding and intake traceability behavior."""

import unittest
from unittest.mock import patch

from app import state
from app.config import get_settings


class Sig15TraceabilityTests(unittest.TestCase):
    """Verifies the SIG-15 fixture preserves Linear-style intake status for reviewers."""

    def test_sig15_run_detail_preserves_in_progress_traceability(self) -> None:
        """Confirms the seeded SIG-15 run exposes a traceability snapshot pinned to In Progress."""

        # Load the enriched task detail payload the frontend uses on the run room page.
        detail = state.get_run_detail("sig-15", get_settings(), {})

        # Anchor the demo record to the Linear-style ticket id used in product walkthroughs.
        self.assertEqual(detail["ticket"], "SIG-15")
        # Confirm the public issue view still reflects the frozen Linear snapshot fields.
        self.assertEqual(detail["issue"]["status"], "In Progress")
        self.assertEqual(detail["issue"]["provider"], "linear")

        traceability = detail["traceability"]
        # Prove reviewers can see the intake status independent of the run-room Review state.
        self.assertEqual(traceability["issueStatusAtLaunch"], "In Progress")
        # Validate the snapshot flag expected by dashboard copy and reviewer panels.
        self.assertTrue(traceability["preservedFromInProgress"])

    def test_fallback_issues_surface_sig15_first_with_intake_status(self) -> None:
        """Confirms intake lists SIG-15 first and keeps tracker status from the frozen snapshot."""

        # Force the seeded fallback catalog so CI environments with Linear env vars stay deterministic.
        with patch("app.state._list_connected_issues", return_value=[]):
            # Build the integration catalog the intake page hydrates from.
            catalog = state.get_integration_catalog(get_settings(), {})
            issues = catalog["issues"]

        # Keep the SIG-15 demo ticket above the fold for demo operators.
        self.assertEqual(issues[0]["ticket"], "SIG-15")
        # Prove fallback issue rows prefer snapshot status instead of the run lifecycle state.
        self.assertEqual(issues[0]["status"], "In Progress")
        self.assertEqual(issues[0]["provider"], "linear")


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
