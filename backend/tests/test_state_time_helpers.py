"""Unit coverage for timestamp, runtime, and evidence helpers in state.py."""

import unittest
from datetime import datetime
from datetime import timezone
from unittest.mock import patch

from app import state


class StateTimeHelperTests(unittest.TestCase):
    """Verifies the small timestamp and runtime helpers in state.py."""

    def test_timestamp_and_runtime_helpers_cover_normal_and_fallback_paths(self) -> None:
        """Covers UTC time helpers plus runtime parsing and formatting logic."""

        fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        with patch("app.state.datetime") as mock_datetime:
            # Keep other datetime behaviors intact while fixing now() to a known instant.
            mock_datetime.now.return_value = fixed_now
            mock_datetime.fromisoformat.side_effect = datetime.fromisoformat

            # Confirm the UTC clock helper returns the timezone-aware current instant.
            self.assertEqual(state._utc_now(), fixed_now)

            # Confirm the timestamp helper serializes the current UTC instant.
            self.assertEqual(state._utc_timestamp(), fixed_now.isoformat())

            # Confirm timestamp parsing handles missing, malformed, and naive timestamps.
            self.assertEqual(state._parse_timestamp(None), fixed_now)
            self.assertEqual(state._parse_timestamp("not-a-timestamp"), fixed_now)
            self.assertEqual(
                state._parse_timestamp("2026-04-24T12:30:00").tzinfo,
                timezone.utc,
            )
            self.assertEqual(
                state._parse_timestamp("2026-04-24T12:30:00Z"),
                datetime(2026, 4, 24, 12, 30, tzinfo=timezone.utc),
            )

        # Confirm runtime parsing handles valid and invalid runtime strings.
        self.assertEqual(state._parse_runtime_seconds("02:30"), 150)
        self.assertEqual(state._parse_runtime_seconds("bad"), 0)

        # Confirm runtime formatting clamps negative values and zero pads mm:ss output.
        self.assertEqual(state._format_runtime(-5), "00:00")
        self.assertEqual(state._format_runtime(150), "02:30")

    def test_static_timestamp_and_evidence_helpers_build_expected_sequences(self) -> None:
        """Covers static timestamp spacing, step timestamps, and evidence entry generation."""

        fixed_now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        with patch("app.state._utc_now", return_value=fixed_now):
            # Confirm step timestamps offset the base start time by the requested seconds.
            self.assertEqual(
                state._build_step_timestamp(fixed_now, 30),
                "2026-04-24T12:00:30+00:00",
            )

            # Confirm static timepoints spread evenly across the requested runtime.
            timepoints = state._build_static_timepoints("02:00", 3)
            self.assertEqual(len(timepoints), 3)
            self.assertEqual(timepoints[0], "2026-04-24T11:58:00+00:00")
            self.assertEqual(timepoints[-1], "2026-04-24T12:00:00+00:00")

        # Confirm evidence entries wrap raw strings with ids, timestamps, and status metadata.
        with patch(
            "app.state._build_static_timepoints",
            return_value=[
                "2026-04-24T11:58:00+00:00",
                "2026-04-24T11:59:00+00:00",
            ],
        ):
            evidence_entries = state._build_evidence_entries(
                ["First proof", "Second proof"],
                tab_name="tests",
                runtime_value="02:00",
                status="captured",
            )
        self.assertEqual(evidence_entries[0]["id"], "tests-0")
        self.assertEqual(evidence_entries[1]["detail"], "Second proof")
        self.assertEqual(evidence_entries[1]["status"], "captured")

    def test_format_cursor_agent_runtime_formats_elapsed_time(self) -> None:
        """Covers state_time._format_cursor_agent_runtime via the state wrapper."""

        fixed_now = datetime(2026, 4, 24, 12, 2, tzinfo=timezone.utc)

        with patch("app.state._utc_now", return_value=fixed_now), patch(
            "app.state._parse_timestamp",
            return_value=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        ):
            # Confirm finished Cursor runs never display a zero-second runtime.
            self.assertEqual(
                state._format_cursor_agent_runtime({"createdAt": "2026-04-24T12:00:00+00:00"}, require_nonzero=True),
                "02:00",
            )

            # Confirm in-progress Cursor runs can display zero seconds when elapsed time is tiny.
            with patch("app.state._utc_now", return_value=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)):
                self.assertEqual(
                    state._format_cursor_agent_runtime({"createdAt": "2026-04-24T12:00:00+00:00"}, require_nonzero=False),
                    "00:00",
                )


if __name__ == "__main__":
    # Allow the module to be executed directly during focused local checks.
    unittest.main()
