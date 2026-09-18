"""Offline tests for webapp/food_draft.py -- the in-progress week-selection
draft /food holds between page loads until "Save this week" commits it
through week_plan.save(). No Flask, real tmp files."""

import tempfile
import unittest
from pathlib import Path

from webapp import food_draft as FD


class LoadSaveDraftTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "food_draft.json"

    def test_missing_file_has_no_draft(self):
        self.assertIsNone(FD.load_draft("2026-09-14", path=self.path))

    def test_malformed_json_has_no_draft_rather_than_raising(self):
        self.path.write_text("{not json")
        self.assertIsNone(FD.load_draft("2026-09-14", path=self.path))

    def test_round_trips_a_draft_for_one_week(self):
        week = {"selected": {"ferritin": {"name": "Ferritin"}}}
        FD.save_draft("2026-09-14", week, path=self.path)
        self.assertEqual(FD.load_draft("2026-09-14", path=self.path), week)

    def test_a_different_weeks_draft_is_unaffected(self):
        FD.save_draft("2026-09-14", {"selected": {"a": 1}}, path=self.path)
        FD.save_draft("2026-09-21", {"selected": {"b": 2}}, path=self.path)
        self.assertEqual(FD.load_draft("2026-09-14", path=self.path), {"selected": {"a": 1}})
        self.assertEqual(FD.load_draft("2026-09-21", path=self.path), {"selected": {"b": 2}})

    def test_saving_again_overwrites_only_that_weeks_draft(self):
        FD.save_draft("2026-09-14", {"selected": {"a": 1}}, path=self.path)
        FD.save_draft("2026-09-14", {"selected": {"a": 1, "b": 2}}, path=self.path)
        self.assertEqual(FD.load_draft("2026-09-14", path=self.path), {"selected": {"a": 1, "b": 2}})


class ClearDraftTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "food_draft.json"

    def test_clearing_a_missing_file_does_not_raise(self):
        FD.clear_draft("2026-09-14", path=self.path)  # no exception

    def test_clearing_removes_only_that_weeks_draft(self):
        FD.save_draft("2026-09-14", {"selected": {"a": 1}}, path=self.path)
        FD.save_draft("2026-09-21", {"selected": {"b": 2}}, path=self.path)
        FD.clear_draft("2026-09-14", path=self.path)
        self.assertIsNone(FD.load_draft("2026-09-14", path=self.path))
        self.assertEqual(FD.load_draft("2026-09-21", path=self.path), {"selected": {"b": 2}})

    def test_clearing_a_week_with_no_draft_is_a_no_op(self):
        FD.save_draft("2026-09-21", {"selected": {"b": 2}}, path=self.path)
        FD.clear_draft("2026-09-14", path=self.path)
        self.assertEqual(FD.load_draft("2026-09-21", path=self.path), {"selected": {"b": 2}})


if __name__ == "__main__":
    unittest.main()
