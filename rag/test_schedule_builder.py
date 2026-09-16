"""Offline tests for schedule_builder.py: day/time parsing, the block data
model, .ics export (RFC 5545), and the interactive Q&A loop (input/print
injected, no real stdin/stdout). No model, no database, no network."""

import datetime as dt
import os
import tempfile
import unittest

import schedule_builder as SB


class LooksLikeUpdateRequestTests(unittest.TestCase):
    def test_recognizes_the_exact_phrasing_that_prompted_this_feature(self):
        self.assertTrue(SB.looks_like_schedule_update_request("i'd like to make updates to my schedule"))

    def test_a_research_question_about_scheduling_is_not_an_update_request(self):
        self.assertFalse(SB.looks_like_schedule_update_request(
            "What should my daily schedule look like with gym involved?"))

    def test_unrelated_question_is_not_an_update_request(self):
        self.assertFalse(SB.looks_like_schedule_update_request("Does creatine cause hair loss?"))


class ParseDaysTests(unittest.TestCase):
    def test_comma_separated_abbreviations(self):
        self.assertEqual(SB.parse_days("mon,wed,fri"), ["Mon", "Wed", "Fri"])

    def test_full_names_with_and(self):
        self.assertEqual(SB.parse_days("Tuesday and Thursday"), ["Tue", "Thu"])

    def test_weekdays_keyword(self):
        self.assertEqual(SB.parse_days("weekdays"), ["Mon", "Tue", "Wed", "Thu", "Fri"])

    def test_weekend_keyword(self):
        self.assertEqual(SB.parse_days("weekend"), ["Sat", "Sun"])

    def test_every_day_keyword(self):
        self.assertEqual(SB.parse_days("every day"), SB.DAYS)

    def test_result_is_always_in_week_order_regardless_of_input_order(self):
        self.assertEqual(SB.parse_days("friday, monday"), ["Mon", "Fri"])

    def test_duplicate_days_collapse_once(self):
        self.assertEqual(SB.parse_days("mon, monday, m"), ["Mon"])

    def test_unrecognized_text_returns_empty(self):
        self.assertEqual(SB.parse_days("whenever I feel like it"), [])


class ParseTimeTests(unittest.TestCase):
    def test_12_hour_with_am_pm(self):
        self.assertEqual(SB.parse_time("7am"), "07:00")
        self.assertEqual(SB.parse_time("7:30 PM"), "19:30")

    def test_noon_and_midnight_edge_cases(self):
        self.assertEqual(SB.parse_time("12pm"), "12:00")
        self.assertEqual(SB.parse_time("12am"), "00:00")

    def test_24_hour_format(self):
        self.assertEqual(SB.parse_time("19:00"), "19:00")
        self.assertEqual(SB.parse_time("04:30"), "04:30")

    def test_bare_hour_with_no_minutes_or_meridiem(self):
        self.assertEqual(SB.parse_time("7"), "07:00")

    def test_unparseable_text_raises(self):
        with self.assertRaises(ValueError):
            SB.parse_time("sometime in the morning")

    def test_out_of_range_hour_raises(self):
        with self.assertRaises(ValueError):
            SB.parse_time("25:00")

    def test_out_of_range_minute_raises(self):
        with self.assertRaises(ValueError):
            SB.parse_time("7:75")


class AddBlockTests(unittest.TestCase):
    def test_valid_block_is_added(self):
        schedule = SB.empty_schedule()
        block = SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15",
                              days=["Mon", "Wed"])
        self.assertEqual(schedule["blocks"], [block])
        self.assertEqual(block["label"], "Lift A")

    def test_blank_label_defaults_to_the_category_name(self):
        schedule = SB.empty_schedule()
        block = SB.add_block(schedule, category="morning_light", label="  ", start="06:30", end="06:45",
                              days=["Mon"])
        self.assertEqual(block["label"], "Morning Light")

    def test_unknown_category_rejected(self):
        with self.assertRaises(ValueError):
            SB.add_block(SB.empty_schedule(), category="nonsense", label="x", start="07:00",
                         end="08:00", days=["Mon"])

    def test_no_days_rejected(self):
        with self.assertRaises(ValueError):
            SB.add_block(SB.empty_schedule(), category="work", label="x", start="07:00",
                         end="08:00", days=[])

    def test_end_not_after_start_rejected(self):
        with self.assertRaises(ValueError):
            SB.add_block(SB.empty_schedule(), category="work", label="x", start="17:00",
                         end="09:00", days=["Mon"])

    def test_equal_start_and_end_rejected(self):
        with self.assertRaises(ValueError):
            SB.add_block(SB.empty_schedule(), category="work", label="x", start="09:00",
                         end="09:00", days=["Mon"])


class SaveLoadTests(unittest.TestCase):
    def test_missing_file_loads_empty_schedule(self):
        self.assertEqual(SB.load(os.path.join(tempfile.mkdtemp(), "nope.json")), SB.empty_schedule())

    def test_round_trips_through_save_and_load(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="church", label="Sunday service", start="09:00",
                     end="10:30", days=["Sun"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sched.json")
            SB.save(schedule, path)
            self.assertEqual(SB.load(path), schedule)


class SummaryLinesTests(unittest.TestCase):
    def test_empty_schedule_says_so(self):
        self.assertEqual(SB.summary_lines(SB.empty_schedule()), ["(no blocks yet)"])

    def test_blocks_grouped_by_day_and_sorted_by_start_time(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.add_block(schedule, category="work", label="Job", start="06:00", end="16:00", days=["Mon"])
        lines = SB.summary_lines(schedule)
        self.assertEqual(lines[0], "Mon:")
        # Job (06:00) must be listed before Lift (17:00).
        self.assertLess(lines.index("  06:00-16:00  Job (work)"), lines.index("  17:00-18:00  Lift (gym)"))
        self.assertNotIn("Tue:", lines)  # a day with no blocks is skipped


class ToIcsTests(unittest.TestCase):
    FIXED_NOW = dt.datetime(2026, 9, 16, 12, 0, 0, tzinfo=dt.timezone.utc)  # a Wednesday
    FIXED_TODAY = dt.date(2026, 9, 16)

    def test_basic_structure_is_a_valid_vcalendar(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.rstrip("\r\n").endswith("END:VCALENDAR"))
        self.assertIn("BEGIN:VEVENT\r\n", text)
        self.assertIn("END:VEVENT\r\n", text)
        self.assertIn("VERSION:2.0", text)

    def test_recurring_weekly_rrule_uses_the_right_day_code(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO", text)

    def test_dtstart_lands_on_the_next_occurrence_of_that_weekday(self):
        # FIXED_TODAY is Wednesday 2026-09-16; the next Monday is 2026-09-21.
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertIn("DTSTART:20260921T170000", text)
        self.assertIn("DTEND:20260921T181500", text)

    def test_todays_own_weekday_counts_as_the_next_occurrence(self):
        # FIXED_TODAY is itself a Wednesday.
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="work", label="Job", start="06:00", end="16:00", days=["Wed"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertIn("DTSTART:20260916T060000", text)

    def test_no_timezone_marker_floating_local_time_by_design(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertNotIn("TZID", text)
        self.assertNotIn("DTSTART:20260921T170000Z", text)  # no trailing Z (that would be UTC, not floating)

    def test_a_block_spanning_several_days_produces_one_vevent_per_day(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="work", label="Job", start="06:00", end="16:00",
                     days=["Mon", "Tue", "Wed", "Thu"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertEqual(text.count("BEGIN:VEVENT"), 4)

    def test_special_characters_in_the_label_are_escaped(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="other", label="Church; small-group, notes\nhere", start="18:00",
                     end="19:00", days=["Wed"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        self.assertIn("SUMMARY:Church\\; small-group\\, notes\\nhere", text)
        self.assertNotIn("\nhere", text)  # the raw newline must not have leaked into the file structure

    def test_long_label_is_folded_per_rfc5545(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="other", label="X" * 200, start="18:00", end="19:00", days=["Wed"])
        text = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertIn("\r\n X" * 1, text)  # a continuation line starts with exactly one space

    def test_each_event_has_a_stable_deterministic_uid(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        text1 = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        text2 = SB.to_ics(schedule, now=self.FIXED_NOW, today=self.FIXED_TODAY)
        uid1 = next(l for l in text1.split("\r\n") if l.startswith("UID:"))
        uid2 = next(l for l in text2.split("\r\n") if l.startswith("UID:"))
        self.assertEqual(uid1, uid2)


class ExportIcsTests(unittest.TestCase):
    def test_empty_schedule_refuses_to_export(self):
        with self.assertRaises(ValueError):
            SB.export_ics(SB.empty_schedule())

    def test_writes_a_real_file(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="gym", label="Lift A", start="17:00", end="18:15", days=["Mon"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.ics")
            SB.export_ics(schedule, path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
        self.assertIn("BEGIN:VCALENDAR", content)


class RunBuilderTests(unittest.TestCase):
    """input_fn/print_fn are injected -- these never touch real stdin/stdout."""

    def test_adding_one_block_then_done(self):
        responses = iter(["add", "gym", "Lift A", "mon,wed,fri", "5pm", "6:15pm", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["label"], "Lift A")
        self.assertEqual(schedule["blocks"][0]["start"], "17:00")

    def test_blank_input_immediately_finishes_with_an_empty_schedule(self):
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: "", print_fn=lambda *_: None)
        self.assertEqual(schedule["blocks"], [])

    def test_removing_a_block(self):
        responses = iter([
            "add", "work", "Job", "weekdays", "6am", "4pm",
            "remove", "0",
            "done",
        ])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(schedule["blocks"], [])

    def test_an_invalid_category_skips_the_block_and_continues(self):
        responses = iter(["add", "nonsense", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(schedule["blocks"], [])

    def test_unrecognized_top_level_action_does_not_crash_and_reprompts(self):
        responses = iter(["blah", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(schedule["blocks"], [])

    def test_pre_existing_schedule_is_preserved_and_added_to(self):
        existing = SB.empty_schedule()
        SB.add_block(existing, category="sleep", label="Sleep", start="22:00", end="23:59", days=["Sun"])
        responses = iter(["done"])
        schedule = SB.run_builder(existing, input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["label"], "Sleep")


if __name__ == "__main__":
    unittest.main()
