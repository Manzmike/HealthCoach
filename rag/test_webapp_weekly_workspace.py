import datetime as dt
import tempfile
import unittest
from pathlib import Path

from webapp import weekly_workspace as WW


class WeeklyWindowTests(unittest.TestCase):
    def test_selected_date_is_editable_for_exactly_seven_calendar_days(self):
        start = "2026-09-18"
        self.assertEqual(WW.week_dates(start), ("2026-09-18", "2026-09-24"))
        self.assertTrue(WW.is_editable(start, dt.date(2026, 9, 18)))
        self.assertTrue(WW.is_editable(start, dt.date(2026, 9, 24)))
        self.assertFalse(WW.is_editable(start, dt.date(2026, 9, 25)))

    def test_invalid_week_date_is_rejected(self):
        with self.assertRaises(ValueError):
            WW.week_dates("not-a-date")


class WeeklyStateTests(unittest.TestCase):
    def test_normalize_limits_meals_to_one_through_seven(self):
        week = WW.normalize_week({"meals": [{"name": str(i)} for i in range(9)]}, "2026-09-18")
        self.assertEqual(len(week["meals"]), 7)

        with self.assertRaises(ValueError):
            WW.normalize_week({"meal_count": 0}, "2026-09-18")

    def test_save_and_load_round_trip_is_keyed_by_week_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weekly.json"
            week = WW.empty_week("2026-09-18")
            week["symptoms"]["selected"] = ["Bloating"]
            WW.save_week(week, path)
            loaded = WW.get_week("2026-09-18", path)
            self.assertEqual(loaded["symptoms"]["selected"], ["Bloating"])

    def test_analysis_is_current_only_when_the_saved_snapshot_matches_inputs(self):
        week = WW.empty_week("2026-09-18")
        self.assertFalse(WW.analysis_is_current(week, "lifestyle"))
        week["lifestyle"]["current"] = ["desk_work"]
        week["analysis"]["lifestyle"] = {
            "snapshot": WW.analysis_snapshot(week, "lifestyle"),
            "sections": [{"text": "Take walking breaks."}],
            "analyzed_at": "2026-09-18T10:00:00",
        }
        self.assertTrue(WW.analysis_is_current(week, "lifestyle"))
        week["lifestyle"]["target"] = ["sleep_consistency"]
        self.assertFalse(WW.analysis_is_current(week, "lifestyle"))


class WorkoutGeneratorTests(unittest.TestCase):
    def test_generator_returns_one_session_for_each_selected_day(self):
        sessions = WW.generate_workouts(
            "beginner", "build_strength", ["Mon", "Wed", "Sat"], "full_body", "old knee pain"
        )
        self.assertEqual([session["day"] for session in sessions], ["Mon", "Wed", "Sat"])
        self.assertTrue(all("old knee pain" in session["notes"] for session in sessions))
        self.assertTrue(all(session["title"] for session in sessions))


if __name__ == "__main__":
    unittest.main()
