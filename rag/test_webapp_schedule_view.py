"""Offline test for webapp/schedule_view.py's grouped_by_day() -- pure
dict/list logic, no Flask, no file I/O."""

import unittest

import schedule_builder as SB
from webapp import schedule_view as SV


class GroupedByDayTests(unittest.TestCase):
    def test_all_seven_days_present_even_when_empty(self):
        rows = SV.grouped_by_day(SB.empty_schedule())
        self.assertEqual([day for day, _blocks in rows], SB.DAYS)
        self.assertTrue(all(blocks == [] for _day, blocks in rows))

    def test_a_block_appears_under_every_day_it_covers(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00",
                     days=["Mon", "Wed"])
        rows = dict(SV.grouped_by_day(schedule))
        self.assertEqual(len(rows["Mon"]), 1)
        self.assertEqual(len(rows["Wed"]), 1)
        self.assertEqual(rows["Tue"], [])

    def test_blocks_within_a_day_are_sorted_by_start_time(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="meal", label="Dinner", start="19:00", end="19:30", days=["Mon"])
        SB.add_block(schedule, category="work", label="Job", start="09:00", end="17:00", days=["Mon"])
        rows = dict(SV.grouped_by_day(schedule))
        self.assertEqual([b["label"] for b in rows["Mon"]], ["Job", "Dinner"])

    def test_each_block_carries_its_index_in_the_flat_blocks_list(self):
        """/schedule/remove pops from schedule["blocks"] by position -- a
        day's own sorted sublist reorders blocks, so the index has to be
        carried explicitly rather than reconstructed from sublist order."""
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="meal", label="Dinner", start="19:00", end="19:30", days=["Mon"])
        SB.add_block(schedule, category="work", label="Job", start="09:00", end="17:00", days=["Mon"])
        rows = dict(SV.grouped_by_day(schedule))
        by_label = {b["label"]: b["index"] for b in rows["Mon"]}
        self.assertEqual(by_label, {"Dinner": 0, "Job": 1})

    def test_each_block_carries_its_grid_position(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="06:00", end="07:00", days=["Mon"])
        rows = dict(SV.grouped_by_day(schedule))
        block = rows["Mon"][0]
        self.assertIn("top_pct", block)
        self.assertIn("height_pct", block)


class BlockPositionTests(unittest.TestCase):
    def test_midnight_start_is_zero_percent_from_the_top(self):
        pos = SV.block_position({"start": "00:00", "end": "01:00"})
        self.assertEqual(pos["top_pct"], 0.0)

    def test_a_one_hour_block_is_one_twenty_fourth_of_the_day(self):
        pos = SV.block_position({"start": "06:00", "end": "07:00"})
        self.assertAlmostEqual(pos["height_pct"], 100 / 24, places=3)
        self.assertAlmostEqual(pos["top_pct"], 6 * 100 / 24, places=3)

    def test_noon_to_one_pm_is_centered_at_the_halfway_point(self):
        pos = SV.block_position({"start": "12:00", "end": "13:00"})
        self.assertEqual(pos["top_pct"], 50.0)

    def test_the_last_minute_of_the_day_stays_within_bounds(self):
        pos = SV.block_position({"start": "23:00", "end": "23:59"})
        self.assertLess(pos["top_pct"] + pos["height_pct"], 100.0)


class AnalysisTargetsTests(unittest.TestCase):
    def test_only_research_relevant_categories_are_included(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.add_block(schedule, category="work", label="Job", start="09:00", end="17:00", days=["Mon"])
        targets = SV.analysis_targets(schedule)
        self.assertEqual(targets, [("gym", "Lift")])

    def test_same_category_multiple_blocks_combine_into_one_target(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.add_block(schedule, category="gym", label="Cardio", start="07:00", end="07:30", days=["Wed"])
        targets = SV.analysis_targets(schedule)
        self.assertEqual(targets, [("gym", "Lift, Cardio")])

    def test_duplicate_labels_in_the_same_category_are_not_repeated(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Wed"])
        targets = SV.analysis_targets(schedule)
        self.assertEqual(targets, [("gym", "Lift")])

    def test_no_research_relevant_blocks_returns_empty(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="work", label="Job", start="09:00", end="17:00", days=["Mon"])
        self.assertEqual(SV.analysis_targets(schedule), [])

    def test_results_are_sorted_by_category_for_a_stable_report_order(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="sleep", label="Bed", start="22:00", end="23:59", days=["Mon"])
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        targets = SV.analysis_targets(schedule)
        self.assertEqual([t[0] for t in targets], ["gym", "sleep"])


class HourLabelsTests(unittest.TestCase):
    def test_twenty_four_labels_starting_and_ending_correctly(self):
        self.assertEqual(len(SV.HOUR_LABELS), 24)
        self.assertEqual(SV.HOUR_LABELS[0], "12 AM")
        self.assertEqual(SV.HOUR_LABELS[12], "12 PM")
        self.assertEqual(SV.HOUR_LABELS[13], "1 PM")
        self.assertEqual(SV.HOUR_LABELS[23], "11 PM")


if __name__ == "__main__":
    unittest.main()
