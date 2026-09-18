"""Offline tests for webapp/schedule_analysis.py: the persisted gate that
decides whether /schedule/export.ics is allowed. No Flask, real tmp files."""

import tempfile
import unittest
from pathlib import Path

from webapp import schedule_analysis as SA


class LoadSaveTests(unittest.TestCase):
    def test_missing_file_loads_as_empty(self):
        path = Path(tempfile.mkdtemp()) / "nope.json"
        self.assertEqual(SA.load(path), {})

    def test_malformed_json_loads_as_empty_rather_than_raising(self):
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text("{not json")
        self.assertEqual(SA.load(path), {})

    def test_round_trips_snapshot_and_results(self):
        path = Path(tempfile.mkdtemp()) / "analysis.json"
        snapshot = [{"category": "gym", "label": "Lift", "start": "17:00", "end": "18:00", "days": ["Mon"]}]
        results = [{"category": "gym", "answer_html": "<p>evidence</p>"}]
        SA.save(snapshot, results, analyzed_at="2026-09-18T00:00:00", path=path)
        loaded = SA.load(path)
        self.assertEqual(loaded["snapshot"], snapshot)
        self.assertEqual(loaded["results"], results)
        self.assertEqual(loaded["analyzed_at"], "2026-09-18T00:00:00")


class IsCurrentTests(unittest.TestCase):
    def _schedule(self, blocks):
        return {"blocks": blocks}

    def test_no_analysis_on_file_is_never_current(self):
        self.assertFalse(SA.is_current(self._schedule([{"a": 1}]), {}))

    def test_empty_schedule_is_never_current_even_with_a_matching_empty_snapshot(self):
        self.assertFalse(SA.is_current(self._schedule([]), {"snapshot": []}))

    def test_identical_blocks_are_current(self):
        blocks = [{"category": "gym", "label": "Lift", "start": "17:00", "end": "18:00", "days": ["Mon"]}]
        self.assertTrue(SA.is_current(self._schedule(blocks), {"snapshot": blocks}))

    def test_any_change_since_the_snapshot_is_not_current(self):
        old = [{"category": "gym", "label": "Lift", "start": "17:00", "end": "18:00", "days": ["Mon"]}]
        new = old + [{"category": "meal", "label": "Dinner", "start": "19:00", "end": "19:30", "days": ["Mon"]}]
        self.assertFalse(SA.is_current(self._schedule(new), {"snapshot": old}))


if __name__ == "__main__":
    unittest.main()
