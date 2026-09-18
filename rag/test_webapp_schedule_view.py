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


if __name__ == "__main__":
    unittest.main()
