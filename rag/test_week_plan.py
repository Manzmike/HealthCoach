"""Weekly workspace tests use synthetic state, no live ledger or model calls."""

import copy
import contextlib
import datetime as dt
import io
import json
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import candidate_ledger as CL
import daily_log
import healthcoach_dashboard as dashboard
import safety_policy as SP
import today
import week_plan as W
import week_planner as UI
import plan_export as EX
import weekly_food_plan as F
from test_today import FakeScreen

START = "2026-09-07"
SOURCE = W.resource("Synthetic verified resource for this test item", "nutrition")


def basis():
    return W.rationale("Support my strength goal", "This source supports the food's protein contribution", "Review at my next weekly check-in", SOURCE, [SOURCE])


def row(item_id="chicken", cls="food", **changes):
    return {**CL.normalize_row({"id": item_id, "display_name": item_id.title(), "class": cls,
                               "consideration_scope": "personal_candidate", "reasons": ["strength"], **changes}), "resources": [SOURCE]}


def portion(item_id="chicken", servings=7, **changes):
    return {"id": item_id, "name": item_id.title(), "servings": servings, "kcal_per_serving": 150,
            "protein_g_per_serving": 25, "grams_per_serving": 113, **changes}


class WeekPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "private" / "week.json"

    def test_opening_or_seeding_is_read_only_and_does_not_claim_use(self):
        before = row(user_decision="adopt")
        week = W.seed_week(START, [before], {})
        self.assertIn("chicken", week["selected"])
        self.assertEqual(before["use_status"], "not_in_use")
        self.assertFalse(self.path.exists())
        self.assertEqual(W.load(self.path)["weeks"], {})
        self.assertEqual(week["workouts"][START]["steps_target"], 10000)
        self.assertIsNone(week["workouts"][START]["time"])

    def test_gray_interest_survives_without_adoption_or_a_protocol(self):
        peptide = row("bpc_157", "peptide", consideration_scope="research_only_topic")
        before = copy.deepcopy(peptide)
        week = W.seed_week(START, [peptide], {"selected_peptide_keys": [peptide["id"]]})
        self.assertIn("bpc_157", week["selected"])
        self.assertFalse(SP.candidate_gate(peptide)["active_plan_allowed"])
        self.assertEqual(week["item_routines"], {})
        self.assertEqual(peptide, before)

    def test_overall_grade_does_not_change_with_personal_goals(self):
        candidate = row("noopept", "nootropic")
        evidence = {"overall_grade": "A", "coverage": "STRONG", "direction": "favor", "sources": ["source_1"]}
        strength = W.grades(candidate, {"goals": ["strength"]}, research=evidence)
        sleep = W.grades(candidate, {"goals": ["sleep"]}, research=evidence)
        self.assertEqual(strength["overall"], sleep["overall"])
        self.assertEqual(strength["personal"], "A")
        self.assertEqual(sleep["personal"], "D")
        self.assertIn("not evidence of harm", sleep["personal_why"])
        candidate["observed"] = "harms"
        harm = W.grades(candidate, {"goals": ["strength"]}, research=evidence)
        self.assertEqual(harm["overall"], "A")
        self.assertEqual(harm["personal"], "F")

    def test_missing_evidence_and_personal_context_are_unknown(self):
        result = W.grades(row(), {})
        self.assertEqual((result["overall"], result["personal"]), ("?", "?"))

    def test_full_catalog_browses_gray_nootropics_and_foods_without_writes(self):
        entries = {item["id"]: item for item in UI.catalog_rows(CL.empty_ledger())}
        self.assertIn("bpc_157", entries)
        self.assertIn("gray", entries["noopept_omberacetam"]["browse_categories"])
        self.assertIn("nootropic", entries["noopept_omberacetam"]["browse_categories"])
        self.assertIn("nootropic", entries["citicoline"]["browse_categories"])
        self.assertIn("food", entries["chicken"]["browse_categories"])

    def test_save_requires_reason_preserves_other_weeks_and_records_before_after(self):
        first = W.seed_week(START, [row(user_decision="adopt")], {})
        first["selected"]["chicken"]["rationale"] = basis()
        with self.assertRaises(ValueError):
            W.save(START, first, None, "", self.path)
        self.assertFalse(self.path.exists())
        saved = W.save(START, first, None, "Prepare meals for work", self.path)
        other = W.seed_week("2026-09-14", [], {})
        W.save("2026-09-14", other, None, "Next week's schedule", self.path)
        changed = copy.deepcopy(saved)
        changed["workouts"][START]["steps_target"] = 8000
        changed["justifications"]["workouts"] = basis()
        W.save(START, changed, saved, "Less time on Monday", self.path)
        loaded = W.load(self.path)
        self.assertIn("2026-09-14", loaded["weeks"])
        history = loaded["weeks"][START]["history"][-1]
        self.assertEqual(history["reason"], "Less time on Monday")
        self.assertEqual(history["changes"][0]["before"][START]["steps_target"], 10000)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            W.save(START, first, saved, "Stale client", self.path)

    def test_research_refresh_cannot_change_week_or_erase_concurrent_week(self):
        week = W.seed_week(START, [], {})
        saved = W.save(START, week, None, "Initial week", self.path)
        W.save_research("bpc_157", {"overall_grade": "B"}, self.path)
        W.save(START, saved, saved, "Reviewed schedule", self.path)
        self.assertEqual(W.load(self.path)["research"]["bpc_157"]["overall_grade"], "B")

    def test_corrupt_state_and_failed_replace_do_not_destroy_existing_file(self):
        self.path.parent.mkdir()
        self.path.write_text("broken")
        with self.assertRaises(ValueError):
            W.save(START, W.empty_week(), None, "test", self.path)
        self.assertEqual(self.path.read_text(), "broken")
        self.path.unlink()
        previous = W.save(START, W.empty_week(), None, "initial", self.path)
        before = self.path.read_bytes()
        with patch.object(W.os, "replace", side_effect=OSError("failed")), self.assertRaises(OSError):
            W.save(START, previous, previous, "edit", self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(list(self.path.parent.glob(".week-plan-*")))

    def test_meal_distribution_preserves_all_portions_without_invented_clock_times(self):
        plan = {"foods": [portion(), portion("oats", 10, kcal_per_serving=100, protein_g_per_serving=4)], "skipped": []}
        before = copy.deepcopy(plan)
        meals, notices = W.distribute_meals(plan, START)
        self.assertFalse(notices)
        self.assertEqual(sum(meal["servings"] for meal in meals), 17)
        self.assertEqual(sum(meal["kcal"] for meal in meals), 2050)
        self.assertEqual({meal["food_id"] for meal in meals}, {"chicken", "oats"})
        self.assertEqual(len({meal["date"] for meal in meals if meal["food_id"] == "chicken"}), 7)
        week = W.empty_week()
        week["meals"] = meals
        W.validate_week(START, week)
        self.assertTrue(all(time is None for time in week["meal_times"].values()))
        self.assertEqual(plan, before)

    def test_group_limits_and_unplaceable_choices_are_visible(self):
        plan = {"foods": [portion("lean_beef", 3), portion("lamb", 3), portion("beef_liver", 1), portion("chicken_liver", 1)]}
        meals, notices = W.distribute_meals(plan, START)
        self.assertEqual(sum(m["servings"] for m in meals if m["food_id"] in {"lean_beef", "lamb"}), 3)
        self.assertEqual(sum(m["servings"] for m in meals if "liver" in m["food_id"]), 1)
        self.assertTrue(notices)

    def test_manual_meal_edits_cannot_exceed_limits_or_leave_week(self):
        meals, _ = W.distribute_meals({"foods": [portion()]}, START)
        for change in ({"date": "2026-09-14"}, {"servings": float("nan")}, {"servings": 3}, {"slot": "Anything"}, {"kcal": float("inf")}):
            with self.subTest(change=change):
                week = W.empty_week()
                week["meals"] = [dict(meals[0], **change)]
                with self.assertRaises(ValueError):
                    W.validate_week(START, week)

    def test_building_meals_uses_selection_not_actual_use_and_exposes_missing_data(self):
        food = row()
        week = W.seed_week(START, [], {})
        week["selected"][food["id"]] = W.selection(food)
        week["selected"][food["id"]]["rationale"] = basis()
        before = copy.deepcopy(food)
        fake_plan = {"foods": [portion()], "targets": {"weekly_kcal": 14000, "weekly_protein_g": 900}}
        with patch.object(F, "plan_week", return_value=fake_plan) as allocator:
            built = UI.build_meals(week, [food], {}, self.root / "report.md", START)
        self.assertEqual(len(built["meals"]), 7)
        self.assertEqual(allocator.call_args.args[0][0]["use_status"], "not_in_use")
        self.assertEqual(food, before)
        with patch.object(F, "plan_week", return_value={"foods": [], "targets": {}, "note": "Missing biometrics"}):
            result = UI.build_meals(week, [food], {}, self.root / "report.md", START)
        self.assertEqual(result["meals"], [])
        self.assertIn("Missing biometrics", result["allocation"]["notices"])

    def test_selected_restricted_food_remains_visible_but_gets_no_meals(self):
        food = row(observed="harms")
        week = W.seed_week(START, [], {})
        week["selected"][food["id"]] = W.selection(food)
        week["selected"][food["id"]]["rationale"] = basis()
        with patch.object(F, "plan_week", return_value={"foods": [], "targets": {}}) as allocator:
            built = UI.build_meals(week, [food], {}, self.root / "report.md", START)
        self.assertEqual(allocator.call_args.args[0], [])
        self.assertIn("chicken", built["selected"])
        self.assertTrue(built["allocation"]["notices"])

    def test_new_choices_or_goals_mark_old_meals_stale(self):
        week = W.seed_week(START, [row(user_decision="adopt")], {})
        week["meal_basis"] = W.meal_basis(week, {"goals": ["strength"]})
        week["meals"], _ = W.distribute_meals({"foods": [portion()]}, START)
        text = "\n".join(W.overview(week, START, START, {"goals": ["sleep"]}))
        self.assertIn("MEALS NEED REBUILD", text)
        self.assertNotIn("Chicken x1", text)

    def test_daily_steps_preserve_unknown_zero_and_existing_logs(self):
        path = self.root / "daily.json"
        daily_log.save_entry(dt.date.fromisoformat(START), {**daily_log.empty_entry(), "steps": 0}, path)
        self.assertEqual(daily_log.load_log(path)["days"][START]["steps"], 0)
        for steps in (-1, True, 1.5, 100001):
            with self.assertRaises(ValueError):
                daily_log.validate_entry({**daily_log.empty_entry(), "steps": steps})
        old = daily_log.empty_entry()
        del old["steps"]
        daily_log.validate_entry(old)

    def drive(self, keys, *, answers=(), view="food", items=None, size=(28, 100)):
        items = items or [row()]
        args = SimpleNamespace(state=self.path, ledger=self.root / "ledger.json", report=self.root / "report.md", week=dt.date.fromisoformat(START), view=view)
        screen = FakeScreen(keys, size)
        ledger = {"intake": {"goals": ["strength"]}, "candidates": items}
        with patch.object(UI.curses, "wrapper", side_effect=lambda run: run(screen)), patch.object(UI.curses, "curs_set"), patch.object(dashboard, "text_input", side_effect=answers):
            UI.run_ui(args, items, ledger, {}, {})
        return screen

    def test_keyboard_selection_save_and_cancel(self):
        screen = self.drive([ord(" "), ord("s"), ord("q")], answers=["1", "Support my strength goal", "Protein fits my workday lunch", "Review my next weekly log", "Meal prep for work", "SAVE"])
        self.assertIn("chicken", W.load(self.path)["weeks"][START]["selected"])
        self.assertIn("All", "\n".join(screen.frames[0].values()))
        before = self.path.read_bytes()
        self.drive([ord(" "), ord("q")], answers=["DISCARD"])
        self.assertEqual(before, self.path.read_bytes())

    def test_every_view_is_reachable_and_gray_selection_is_not_blocked(self):
        peptide = row("bpc_157", "peptide")
        self.drive([ord(" "), 10, 27, ord("s"), ord("q")], answers=["1", "Review tendon evidence", "Compare study populations to my injury context", "Review with updated human evidence", "Review tendon evidence", "SAVE"], view="gray", items=[peptide])
        self.assertIn("bpc_157", W.load(self.path)["weeks"][START]["selected"])
        self.assertEqual(peptide["use_status"], "not_in_use")
        for view in UI.VIEWS:
            with self.subTest(view=view):
                self.drive([ord("q")], view=view, size=(20, 60))

    def test_home_shortcuts_open_the_actual_selection_views(self):
        state = today.load_today(self.root / "report.md", self.root / "ledger.json", self.root / "daily.json", week_path=self.path)
        state["first_run"] = False
        for key, action in {"f": "food-review", "g": "gray-review", "n": "nootropic-review", "s": "supplement-review", "m": "food-plan", "t": "workouts", "c": "week-changes", "e": "export"}.items():
            screen = FakeScreen([ord(key)], (24, 80))
            with patch.object(dashboard.T, "load_today", return_value=state), patch.object(dashboard.curses, "wrapper", side_effect=lambda run: run(screen)), patch.object(dashboard.curses, "curs_set"):
                self.assertEqual(dashboard.choose_action().key, action)

    def test_hard_reasons_are_required_at_save_not_only_by_the_ui(self):
        week = W.seed_week(START, [row(user_decision="adopt")], {})
        with self.assertRaisesRegex(ValueError, "justify"):
            W.save(START, week, None, "I want to try this", self.path)
        week["selected"]["chicken"]["rationale"] = basis()
        week["workouts"][START].update(session="A newly chosen workout", origin="USER_PLANNED")
        with self.assertRaises(ValueError):
            W.save(START, week, None, "New training week", self.path)
        week["justifications"]["workouts"] = basis()
        W.save(START, week, None, "New training week", self.path)
        self.assertTrue(self.path.exists())

    def test_fabricated_resource_and_empty_purpose_cannot_justify_a_selection(self):
        with self.assertRaises(ValueError):
            W.rationale("A specific goal", "Specific personal reason", "Review next week", W.resource("Made up source"), [SOURCE])
        for key in ("goal", "personal_reason", "review_trigger"):
            value = basis()
            value[key] = "because"
            with self.assertRaises(ValueError):
                W.validate_rationale(value)

    def test_unsupported_item_cannot_be_checked_into_the_week(self):
        item = row("unsupported", "supplement")
        item["resources"] = []
        screen = self.drive([ord(" "), ord("q")], view="supplement", items=[item])
        self.assertFalse(self.path.exists())
        self.assertIn("No usable source", "\n".join(screen.frames[-1].values()))

    def test_export_sections_include_grades_hard_reasons_and_full_archive(self):
        item = row()
        week = W.seed_week(START, [dict(item, user_decision="adopt")], {})
        week["selected"]["chicken"]["rationale"] = basis()
        week["meals"], _ = W.distribute_meals({"foods": [portion()]}, START)
        week["meal_basis"] = W.meal_basis(week, {})
        week["justifications"]["meals"] = basis()
        for section in EX.SECTIONS:
            text = EX.render(section, START, week, [item], {}, {}, {}, report_text="EXACT ARCHIVE CONTENT")
            self.assertIn("2026-09-07", text)
            if section in {"food", "current-plan", "full-report"}:
                self.assertIn("Personal reason:", text)
                self.assertIn(SOURCE["id"], text)
            if section == "full-report":
                self.assertIn("EXACT ARCHIVE CONTENT", text)
        with self.assertRaises(ValueError):
            EX.render("full-report", START, week, [item], {}, {}, {})

    def test_exports_are_private_unique_and_do_not_change_state(self):
        directory = self.root / "exports"
        first = EX.write_export("first content", START, "overview", directory)
        second = EX.write_export("second content", START, "overview", directory)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(), "first content")
        self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.path.exists())

    def test_export_cancel_does_not_write_private_files(self):
        with patch("builtins.input", return_value="q"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(EX.main(["--state", str(self.path), "--directory", str(self.root / "exports")]), 0)
        self.assertFalse((self.root / "exports").exists())

    def test_keyboard_food_to_meals_times_and_portion_edit_end_to_end(self):
        answers = ["1", "Protein for my strength goal", "This nutrient resource supports protein in my lunch", "Review at the next weekly check-in"]
        answers += ["1", "Build a practical meal week", "Distribute my chosen foods around work and training", "Review adherence after seven days"]
        answers += ["07:00", "12:00", "18:00", "15:00", "1", "Use practical meal windows", "These times fit my recorded workday schedule", "Review if my work hours change"]
        answers += ["2026-09-08", "Lunch", "0.5", "1", "Move and resize this portion", "This fits Tuesday lunch while retaining the same food", "Review hunger at the next weekly check-in"]
        answers += ["Plan around this week's work schedule", "SAVE"]
        plan = {"foods": [portion()], "targets": {"weekly_kcal": 14000, "weekly_protein_g": 900}}
        with patch.object(F, "plan_week", return_value=plan):
            self.drive([ord(" "), ord("b"), ord("c"), ord("e"), ord("s"), ord("q")], answers=answers)
        saved = W.load(self.path)["weeks"][START]
        self.assertEqual(saved["meal_times"]["Lunch"], "12:00")
        self.assertEqual(sum(m["servings"] for m in saved["meals"]), 6.5)
        self.assertTrue(saved["justifications"]["meals"]["source"])
        self.assertIn("chicken", saved["selected"])

    def test_keyboard_training_edit_records_its_specific_basis(self):
        answers = ["Easy bike instead of running", "17:00", "30", "8000", "1", "Reduce training burden this week", "A shorter session fits my available time and recovery", "Review duration and recovery after seven days", "Reduced Monday workload", "SAVE"]
        self.drive([ord("e"), ord("s"), ord("q")], view="training", answers=answers)
        workout = W.load(self.path)["weeks"][START]["workouts"][START]
        self.assertEqual(workout["steps_target"], 8000)
        self.assertEqual(workout["minutes"], 30)
        self.assertIn("recovery", workout["rationale"]["personal_reason"])

    @unittest.skipUnless(sys.platform in {"darwin", "linux"}, "requires a POSIX terminal")
    def test_real_terminal_opens_category_views_without_models_or_state_writes(self):
        import fcntl
        import os
        import pty
        import select
        import struct
        import subprocess
        import termios
        import time

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 100, 0, 0))
        process = subprocess.Popen([sys.executable, str(W.HERE / "week_planner.py"), "--week", START,
                                    "--state", str(self.path), "--ledger", str(self.root / "ledger.json"),
                                    "--report", str(self.root / "report.md"), "--view", "food"],
                                   stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM": "xterm-256color", "HF_HUB_OFFLINE": "1"}, cwd=W.HERE)
        os.close(slave)
        output = b""
        sent = False
        try:
            deadline = time.monotonic() + 20
            while process.poll() is None and time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        output += os.read(master, 65536)
                    except OSError:
                        break
                if b"YOUR WEEK" in output and b"Peptides/Gray" in output and not sent:
                    os.write(master, b"3q")
                    sent = True
            process.wait(timeout=3)
            self.assertTrue(sent, output.decode(errors="replace"))
            self.assertEqual(process.returncode, 0, output.decode(errors="replace"))
            self.assertFalse(self.path.exists())
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
