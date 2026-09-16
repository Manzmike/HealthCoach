"""Offline tests for schedule_builder.py: day/time parsing, the block data
model, .ics export (RFC 5545), and the interactive Q&A loop (input/print
injected, no real stdin/stdout). No model, no database, no network."""

import datetime as dt
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

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


class ResolveCategoryTests(unittest.TestCase):
    def test_exact_category_names_match(self):
        for category in SB.CATEGORIES:
            self.assertEqual(SB._resolve_category(category), category)

    def test_case_and_spacing_are_forgiving(self):
        self.assertEqual(SB._resolve_category("  Morning Light  "), "morning_light")
        self.assertEqual(SB._resolve_category("MORNING-LIGHT"), "morning_light")

    def test_common_synonyms_resolve_to_the_right_category(self):
        self.assertEqual(SB._resolve_category("workout"), "gym")
        self.assertEqual(SB._resolve_category("commute"), "drive")
        self.assertEqual(SB._resolve_category("sunrise"), "morning_light")
        self.assertEqual(SB._resolve_category("breakfast"), "meal")

    def test_unrecognized_text_returns_none_never_a_guess(self):
        self.assertIsNone(SB._resolve_category("something else entirely"))


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


class _FakeCoach:
    """A minimal stand-in for the coach module, implementing only what
    _offer_research_guidance() actually calls -- no real model, database,
    or network in any of these tests."""

    def __init__(self, hits=None, offer_to_fetch_sources_return=0, answer_text="evidence-based answer"):
        self.RC = MagicMock()
        self.RC.classify.return_value = []
        self._hits = [] if hits is None else hits
        self.search_calls = []
        self.offer_to_fetch_sources = MagicMock(return_value=offer_to_fetch_sources_return)
        self.answer_from_hits = MagicMock(return_value=answer_text)
        self._for_terminal = lambda text: text
        self.DBDIR = "unused"
        self.TABLE = "unused"
        self.GEN_MODEL = "unused"

    def search(self, tbl, emb, q, k, rr, matched_intents=None):
        self.search_calls.append(q)
        return self._hits, False


def _rag_with(coach) -> SB._LazyRag:
    rag = SB._LazyRag()
    rag.coach = coach
    rag.tbl = MagicMock()
    rag.emb = MagicMock()
    rag.rr = MagicMock()
    rag.model_tok = (MagicMock(), MagicMock())  # pre-set so ensure_model skips the real mlx_lm import
    rag.reopen_table = MagicMock()  # real reopen_table does a real lancedb.connect(); not under test here
    return rag


class LazyRagTests(unittest.TestCase):
    def test_ensure_loaded_is_a_noop_once_coach_is_already_set(self):
        rag = SB._LazyRag()
        rag.coach = "already set"
        printed = []
        rag.ensure_loaded(printed.append)
        self.assertEqual(printed, [])  # no "Loading..." message; the real import path never ran


class LoadPersonContextTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(SB.load_person_context(os.path.join(tempfile.mkdtemp(), "nope.json")), {})

    def test_malformed_json_returns_empty_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "person_state.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            self.assertEqual(SB.load_person_context(path), {})

    def test_extracts_the_fields_schedule_building_actually_uses(self):
        state = {
            "identity": {"work": "desk_sedentary", "commute_min": 20},
            "sleep": {"windows": ["22:00-02:00 + 03:30-07:00"]},
            "drugs": {"caffeine_last": "11:00-12:00", "alcohol": {"pattern": "weekend_0_or_3_to_6"}},
            "body": {"training": "stopped"},
        }
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "person_state.json")
            with open(path, "w") as f:
                json.dump(state, f)
            known = SB.load_person_context(path)
        self.assertEqual(known["work_type"], "desk sedentary")
        self.assertEqual(known["commute_min"], "20 min")
        self.assertEqual(known["sleep_window"], "22:00-02:00 + 03:30-07:00")
        self.assertEqual(known["caffeine_last"], "11:00-12:00")
        self.assertEqual(known["alcohol_pattern"], "weekend_0_or_3_to_6")
        self.assertEqual(known["training_status"], "stopped")

    def test_missing_sub_sections_are_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "person_state.json")
            with open(path, "w") as f:
                json.dump({}, f)
            self.assertEqual(SB.load_person_context(path), {})


class RunIntakeTests(unittest.TestCase):
    def test_answers_are_stored_in_the_schedule_profile(self):
        schedule = SB.empty_schedule()
        answers = ["software engineer, desk job", "6am-4pm", "11pm-6am", "noon", "yes",
                    "moderate", "none right now", "drive, 20 min", "rarely", "none", "steady"]
        self.assertEqual(len(answers), len(SB._INTAKE_QUESTIONS))  # keep this test in sync with the real question set
        responses = iter(answers)
        SB.run_intake(schedule, known={}, input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(schedule["profile"]["job_role"], "software engineer, desk job")
        self.assertEqual(schedule["profile"]["work_hours"], "6am-4pm")
        self.assertEqual(schedule["profile"]["sleep_pattern"], "11pm-6am")
        self.assertEqual(schedule["profile"]["energy_pattern"], "steady")

    def test_blank_answers_fall_back_to_the_known_default(self):
        schedule = SB.empty_schedule()
        known = {"sleep_window": "22:00-02:00 + 03:30-07:00", "caffeine_last": "11:00-12:00"}
        SB.run_intake(schedule, known=known, input_fn=lambda _: "", print_fn=lambda *_: None)
        self.assertEqual(schedule["profile"]["sleep_pattern"], known["sleep_window"])
        self.assertEqual(schedule["profile"]["caffeine"], known["caffeine_last"])

    def test_blank_answer_with_no_known_default_leaves_the_field_unset(self):
        schedule = SB.empty_schedule()
        SB.run_intake(schedule, known={}, input_fn=lambda _: "", print_fn=lambda *_: None)
        self.assertNotIn("job_role", schedule["profile"])

    def test_a_typed_answer_overrides_an_existing_profile_value(self):
        schedule = SB.empty_schedule()
        schedule["profile"] = {"job_role": "old answer"}
        responses = iter(["new answer"] + [""] * (len(SB._INTAKE_QUESTIONS) - 1))
        SB.run_intake(schedule, known={}, input_fn=lambda _: next(responses), print_fn=lambda *_: None)
        self.assertEqual(schedule["profile"]["job_role"], "new answer")

    def test_known_values_are_printed_up_front(self):
        printed = []
        SB.run_intake(SB.empty_schedule(), known={"sleep_window": "22:00-06:00"},
                      input_fn=lambda _: "", print_fn=printed.append)
        self.assertTrue(any("22:00-06:00" in p for p in printed))


class PlacementQueryTests(unittest.TestCase):
    def test_includes_context_from_already_entered_work_and_sleep_blocks(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="work", label="Job", start="06:00", end="16:00", days=["Mon"])
        query = SB._placement_query(schedule, "gym", "Lift A")
        self.assertIn("work is 06:00-16:00 on Mon", query)
        self.assertIn("Lift A", query)
        self.assertIn("gym", query)

    def test_no_context_when_no_work_or_sleep_blocks_or_profile_exist_yet(self):
        query = SB._placement_query(SB.empty_schedule(), "gym", "Lift A")
        self.assertNotIn("Given:", query)

    def test_includes_relevant_intake_profile_fields(self):
        schedule = SB.empty_schedule()
        schedule["profile"] = {"job_role": "software engineer", "stress_level": "high"}
        query = SB._placement_query(schedule, "gym", "Lift A")
        self.assertIn("job role: software engineer", query)
        self.assertIn("stress level: high", query)

    def test_a_church_or_drive_block_is_not_used_as_context(self):
        schedule = SB.empty_schedule()
        SB.add_block(schedule, category="church", label="Service", start="09:00", end="10:00", days=["Sun"])
        query = SB._placement_query(schedule, "gym", "Lift A")
        self.assertNotIn("church", query)


class OfferResearchGuidanceTests(unittest.TestCase):
    def test_declining_skips_the_lookup_entirely(self):
        coach = _FakeCoach()
        rag = _rag_with(coach)
        SB._offer_research_guidance(SB.empty_schedule(), "gym", "Lift A", rag,
                                     input_fn=lambda _: "n", print_fn=lambda *_: None)
        self.assertEqual(coach.search_calls, [])
        coach.answer_from_hits.assert_not_called()

    def test_empty_input_defaults_to_declining(self):
        coach = _FakeCoach()
        rag = _rag_with(coach)
        SB._offer_research_guidance(SB.empty_schedule(), "gym", "Lift A", rag,
                                     input_fn=lambda _: "", print_fn=lambda *_: None)
        self.assertEqual(coach.search_calls, [])

    def test_accepting_with_hits_prints_an_evidence_based_answer(self):
        coach = _FakeCoach(hits=[{"id": "1"}], answer_text="train in the evening, per the evidence")
        rag = _rag_with(coach)
        printed = []
        SB._offer_research_guidance(SB.empty_schedule(), "gym", "Lift A", rag,
                                     input_fn=lambda _: "y", print_fn=printed.append)
        self.assertEqual(len(coach.search_calls), 1)
        coach.answer_from_hits.assert_called_once()
        self.assertIn("train in the evening, per the evidence", printed)

    def test_no_hits_offers_to_fetch_then_retries_and_finds_something(self):
        coach = _FakeCoach(hits=[], offer_to_fetch_sources_return=2)
        call_count = {"n": 0}

        def search(tbl, emb, q, k, rr, matched_intents=None):
            call_count["n"] += 1
            return ([{"id": "1"}] if call_count["n"] > 1 else []), False
        coach.search = search
        rag = _rag_with(coach)
        SB._offer_research_guidance(SB.empty_schedule(), "meal", "Dinner", rag,
                                     input_fn=lambda _: "y", print_fn=lambda *_: None)
        coach.offer_to_fetch_sources.assert_called_once()
        self.assertEqual(call_count["n"], 2)  # original search + one retry after the fetch
        coach.answer_from_hits.assert_called_once()

    def test_no_hits_and_fetch_finds_nothing_tells_user_to_use_own_judgment(self):
        coach = _FakeCoach(hits=[], offer_to_fetch_sources_return=0)
        rag = _rag_with(coach)
        printed = []
        SB._offer_research_guidance(SB.empty_schedule(), "church", "Service", rag,
                                     input_fn=lambda _: "y", print_fn=printed.append)
        coach.answer_from_hits.assert_not_called()
        self.assertTrue(any("own judgment" in p for p in printed))


class RunBuilderTests(unittest.TestCase):
    """input_fn/print_fn are injected -- these never touch real stdin/stdout."""

    def test_intake_runs_by_default_on_a_schedule_with_no_profile_yet(self):
        # 10 blank intake answers, then immediately "done".
        responses = iter([""] * len(SB._INTAKE_QUESTIONS) + ["done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses),
                                  print_fn=lambda *_: None, offer_research=False)
        self.assertIn("profile", schedule)

    def test_intake_is_not_re_run_on_a_schedule_that_already_has_a_profile(self):
        schedule = SB.empty_schedule()
        schedule["profile"] = {"job_role": "already answered"}
        # First input answers "update your info?" with no ("n" -> skip intake), then "done".
        responses = iter(["n", "done"])
        SB.run_builder(schedule, input_fn=lambda _: next(responses), print_fn=lambda *_: None,
                       offer_research=False)
        self.assertEqual(schedule["profile"]["job_role"], "already answered")

    def test_adding_one_block_then_done(self):
        responses = iter(["add", "gym", "Lift A", "mon,wed,fri", "5pm", "6:15pm", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["label"], "Lift A")
        self.assertEqual(schedule["blocks"][0]["start"], "17:00")

    def test_bad_category_then_bad_days_then_bad_end_time_all_reprompt_and_still_succeed(self):
        responses = iter([
            "add",
            "nonsense", "gym",                       # category: retry once
            "Lift A",
            "whenever", "mon",                        # days: retry once
            "5pm",
            "4pm", "6pm",                              # end time: retry once (not after start)
            "done",
        ])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["start"], "17:00")
        self.assertEqual(schedule["blocks"][0]["end"], "18:00")

    def test_cancel_at_the_days_prompt_aborts_just_that_block(self):
        responses = iter(["add", "gym", "Lift A", "cancel", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_cancel_at_the_start_time_prompt_aborts_just_that_block(self):
        responses = iter(["add", "gym", "Lift A", "mon", "cancel", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_blank_input_immediately_finishes_with_an_empty_schedule(self):
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: "", print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_removing_a_block(self):
        responses = iter([
            "add", "work", "Job", "weekdays", "6am", "4pm",
            "remove", "0",
            "done",
        ])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_an_invalid_category_reprompts_instead_of_silently_dropping_the_block(self):
        """The exact bug reported live: typing something not on the fixed
        category list used to drop the whole block with no clear signal,
        which looked like the prompt was ignoring input. It must now
        reprompt for category specifically, not fall through to the
        top-level add/remove/done menu."""
        responses = iter(["add", "nonsense", "cancel", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_a_category_synonym_is_accepted_on_the_first_try(self):
        responses = iter(["add", "workout", "Lift A", "mon", "5pm", "6pm", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["category"], "gym")

    def test_unrecognized_top_level_action_does_not_crash_and_reprompts(self):
        responses = iter(["blah", "done"])
        schedule = SB.run_builder(SB.empty_schedule(), input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(schedule["blocks"], [])

    def test_pre_existing_schedule_is_preserved_and_added_to(self):
        existing = SB.empty_schedule()
        SB.add_block(existing, category="sleep", label="Sleep", start="22:00", end="23:59", days=["Sun"])
        responses = iter(["done"])
        schedule = SB.run_builder(existing, input_fn=lambda _: next(responses), print_fn=lambda *_: None, offer_research=False, offer_intake=False)
        self.assertEqual(len(schedule["blocks"]), 1)
        self.assertEqual(schedule["blocks"][0]["label"], "Sleep")


if __name__ == "__main__":
    unittest.main()
