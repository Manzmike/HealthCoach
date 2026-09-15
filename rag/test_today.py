"""Synthetic Today/navigation/daily-log tests; never load live user state or models."""

from __future__ import annotations

import contextlib
import curses
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import daily_log
import healthcoach_dashboard as dashboard
import today


class TodayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report = self.root / "report.md"
        self.ledger = self.root / "ledger.json"
        self.log = self.root / "private" / "daily_log.json"
        self.day = dt.date(2026, 9, 7)
        self.policy = types.ModuleType("safety_policy")
        self.policy.candidate_gate = Mock(return_value={
            "active_plan_allowed": True, "reasons": [], "research_allowed": True,
        })
        self.policy.urgent_message = Mock(return_value=None)
        self.policy_patch = patch.dict(sys.modules, {"safety_policy": self.policy})
        self.policy_patch.start()
        self.addCleanup(self.policy_patch.stop)

    def snapshot(self, day=None):
        return today.load_today(self.report, self.ledger, self.log, day or self.day, week_path=self.root / "week.json")

    def profile(self, value):
        self.report.write_text(
            "Personal prose must not appear in Today.\n"
            "<!-- HC_PROFILE_STATE_START -->\n<details>\n```json\n"
            + json.dumps(value) + "\n```\n</details>\n<!-- HC_PROFILE_STATE_END -->\n"
            "<!-- HC_BEVEL_WEEK_START 2026-08-31 -->\n"
            "Research-only instructions must not appear in Today.\n"
            "<!-- HC_BEVEL_WEEK_END 2026-08-31 -->\n",
            encoding="utf-8",
        )

    def candidates(self, *rows):
        self.ledger.write_text(json.dumps({"schema_version": 2, "candidates": rows}), encoding="utf-8")

    def row(self, name="Example", **changes):
        return {
            "id": name.lower(), "display_name": name, "class": "supplement",
            "consideration_scope": "personal_candidate", "user_decision": "adopt",
            "use_status": "in_use", "user_dose": None, **changes,
        }

    def test_missing_state_adds_no_defaults_and_writes_nothing(self):
        state = self.snapshot()
        self.assertTrue(state["first_run"])
        self.assertIsNone(state["placement"])
        self.assertEqual(state["active"], [])
        self.assertIsNone(state["daily"])
        self.assertEqual(list(self.root.iterdir()), [])
        text = "\n".join(today.summary_lines(state))
        self.assertIn("Not configured", text)
        self.assertNotIn("17:00", text)
        self.assertNotIn("5 g", text)

    def test_saved_placement_is_not_a_generated_session(self):
        self.profile({"calendar_modes": {"Monday": "morning"}, "calendar_validation": "PASS with unresolved conflict"})
        before = self.report.read_bytes()
        state = self.snapshot()
        self.assertEqual(state["placement"], "morning")
        self.assertEqual(state["weeks"], ["2026-08-31"])
        text = "\n".join(today.summary_lines(state))
        self.assertIn("unresolved conflict", text)
        self.assertIn("no exact session/time", text)
        self.assertNotIn("Personal prose", text)
        self.assertNotIn("Research-only instructions", text)
        self.assertEqual(before, self.report.read_bytes())

    def test_missing_weekday_is_not_seeded_from_generic_timing(self):
        self.profile({"cardio_timing": "evening", "workout_timing": "morning", "calendar_modes": {"Tuesday": "both"}})
        self.assertIsNone(self.snapshot()["placement"])
        self.profile({"calendar_modes": {"Monday": "plan"}})
        self.assertIn("Authored template", "\n".join(today.summary_lines(self.snapshot())))

    def test_saved_session_snapshot_and_conflict_are_shown_verbatim(self):
        snapshot = {"mode": "morning", "placement": "User-reviewed Monday session", "status": "CONFLICT: keep visible", "origin": "AUTHORED_TEMPLATE"}
        self.profile({"calendar_modes": {"Monday": "morning"}, "calendar_snapshot": {"Monday": snapshot}})
        text = "\n".join(today.summary_lines(self.snapshot()))
        self.assertIn("SAVED SESSION: User-reviewed Monday session", text)
        self.assertIn("CONFLICT: keep visible", text)
        snapshot["mode"] = "evening"
        self.profile({"calendar_modes": {"Monday": "morning"}, "calendar_snapshot": {"Monday": snapshot}})
        self.assertIsNone(self.snapshot()["calendar_snapshot"])

    def test_stale_and_malformed_intake_are_visible_without_writes(self):
        for intake in ({"updated_at": "2025-01-01T00:00:00+00:00"}, {"updated_at": "bad-date"}, []):
            self.ledger.write_text(json.dumps({"schema_version": 2, "candidates": [], "intake": intake}))
            before = self.ledger.read_bytes()
            self.assertTrue(self.snapshot()["warnings"])
            self.assertEqual(before, self.ledger.read_bytes())

    def test_active_requires_all_three_explicit_fields_and_shared_gate(self):
        active = self.row("Active", user_dose="USER 7 g on selected days")
        research = self.row("Research", consideration_scope="research_only_topic", use_status="not_in_use")
        restricted = self.row("Restricted", **{"class": "gray_market"})
        reported = self.row("Reported", consideration_scope="research_only_topic")
        rejected = self.row("Rejected", user_decision="reject")
        unscheduled = self.row("NotStarted", use_status="not_in_use")
        implicit = self.row("MissingScope")
        implicit.pop("consideration_scope")
        self.candidates(active, research, restricted, reported, rejected, unscheduled, implicit)
        self.policy.candidate_gate.side_effect = lambda row: {
            "active_plan_allowed": row["id"] != "restricted",
            "reasons": ["Restricted category"] if row["id"] == "restricted" else [],
            "research_allowed": True,
        }
        before = self.ledger.read_bytes()
        state = self.snapshot()
        self.assertEqual([r["id"] for r in state["active"]], ["active"])
        self.assertEqual({r["id"] for r in state["review"]}, {"restricted", "reported", "rejected", "missingscope"})
        self.assertEqual(state["active"][0]["dose"], "USER 7 g on selected days")
        collapsed = "\n".join(today.summary_lines(state))
        self.assertNotIn("Restricted (", collapsed)
        expanded = "\n".join(today.summary_lines(state, show_review=True))
        self.assertIn("Restricted (gray_market)", expanded)
        self.assertIn("not an automatic stop", expanded.lower())
        self.assertNotIn("Research (", expanded)
        self.assertEqual(self.ledger.read_bytes(), before)
        for call in self.policy.candidate_gate.call_args_list:
            self.assertEqual(len(call.args), 1)
            self.assertEqual(call.kwargs, {})

    def test_no_class_blacklist_outside_shared_policy(self):
        self.candidates(self.row("Custom", **{"class": "gray_market"}))
        self.assertEqual(self.snapshot()["active"][0]["id"], "custom")

    def test_missing_failed_or_malformed_policy_is_review_only(self):
        self.candidates(self.row())
        for value in (None, {"active_plan_allowed": "yes", "reasons": []}):
            with self.subTest(value=value):
                self.policy.candidate_gate.return_value = value
                state = self.snapshot()
                self.assertEqual(state["active"], [])
                self.assertEqual(len(state["review"]), 1)
        self.policy.candidate_gate.side_effect = RuntimeError("unavailable")
        self.assertEqual(self.snapshot()["active"], [])
        with patch.dict(sys.modules, {"safety_policy": None}):
            state = self.snapshot()
            self.assertEqual(state["active"], [])
            self.assertTrue(state["warnings"])

    def test_malformed_state_is_visible_and_never_rewritten(self):
        for content in ("{", "[]", '{"schema_version": 9, "candidates": []}',
                        '{"schema_version": 2, "candidates": [null]}'):
            with self.subTest(content=content):
                self.ledger.write_text(content)
                self.assertTrue(self.snapshot()["warnings"])
                self.assertEqual(self.ledger.read_text(), content)
        for value in ({"calendar_modes": []}, {"calendar_modes": {"Monday": ["plan"]}}):
            self.profile(value)
            state = self.snapshot()
            self.assertIsNone(state["placement"])
            self.assertTrue(state["warnings"])
        self.report.write_text("<!-- HC_PROFILE_STATE_START -->\n```json\n{}\n```\n")
        self.assertFalse(self.snapshot()["profile_saved"])

    def test_duplicate_candidates_and_profile_blocks_are_not_accepted(self):
        self.candidates(self.row(), self.row())
        self.assertEqual(self.snapshot()["active"], [])
        self.profile({"calendar_modes": {"Monday": "evening"}})
        self.report.write_text(self.report.read_text() * 2)
        self.assertIsNone(self.snapshot()["placement"])

    def test_exact_date_and_weekly_reassessment(self):
        daily_log.save_entry(self.day, {**daily_log.empty_entry(), "status": "completed"}, self.log)
        self.assertEqual(self.snapshot()["daily"]["status"], "completed")
        following = self.snapshot(self.day + dt.timedelta(days=7))
        self.assertIsNone(following["daily"])
        self.assertEqual(following["reassessment"], "2026-09-14")
        self.assertEqual(self.snapshot(self.day - dt.timedelta(days=1))["reassessment"], "2026-09-07")

    def test_read_projection_preserves_all_bytes_and_mtimes(self):
        self.profile({"calendar_modes": {"Monday": "unavailable"}})
        self.candidates(self.row())
        daily_log.save_entry(self.day, daily_log.empty_entry(), self.log)
        paths = (self.report, self.ledger, self.log)
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        self.snapshot()
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])

    def test_daily_save_keeps_unknowns_and_other_days_not_weekly_packages(self):
        self.profile({})
        before = self.report.read_bytes()
        daily_log.save_entry(self.day, {**daily_log.empty_entry(), "status": "skipped", "duration_min": 0}, self.log)
        daily_log.save_entry(self.day + dt.timedelta(days=1), daily_log.empty_entry(), self.log)
        data = daily_log.load_log(self.log)
        self.assertEqual(data["days"]["2026-09-07"]["duration_min"], 0)
        self.assertIsNone(data["days"]["2026-09-08"]["duration_min"])
        self.assertEqual(data["days"]["2026-09-08"]["status"], "unknown")
        self.assertEqual(before, self.report.read_bytes())
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_urgent_note_checked_before_write_and_preserved(self):
        note = "Synthetic urgent symptom report"
        self.policy.urgent_message.side_effect = lambda text: (
            self.assertFalse(self.log.exists()) or "Seek urgent help"
        )
        message = daily_log.save_entry(self.day, {**daily_log.empty_entry(), "note": note}, self.log)
        self.policy.urgent_message.assert_called_once_with(note)
        self.assertEqual(message, "Seek urgent help")
        self.assertEqual(daily_log.load_log(self.log)["days"][self.day.isoformat()]["note"], note)

    def test_bad_log_and_invalid_values_cannot_be_overwritten(self):
        for duration in (-1, 1441, float("nan"), float("inf"), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                daily_log.save_entry(self.day, {**daily_log.empty_entry(), "duration_min": duration}, self.log)
        self.log.parent.mkdir()
        self.log.write_text("corrupt private state")
        with self.assertRaises(ValueError):
            daily_log.save_entry(self.day, daily_log.empty_entry(), self.log)
        self.assertEqual(self.log.read_text(), "corrupt private state")
        self.assertIn("UNAVAILABLE", "\n".join(today.summary_lines(self.snapshot())))

    def test_atomic_replace_failure_keeps_prior_log_and_cleans_temp(self):
        daily_log.save_entry(self.day, daily_log.empty_entry(), self.log)
        before = self.log.read_bytes()
        with patch.object(daily_log.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                daily_log.save_entry(self.day, {**daily_log.empty_entry(), "status": "completed"}, self.log)
        self.assertEqual(self.log.read_bytes(), before)
        self.assertEqual(list(self.log.parent.iterdir()), [self.log])

    def test_cli_cancel_and_blank_keep_explicit_unknown(self):
        args = ["--date", self.day.isoformat(), "--log", str(self.log)]
        with patch("builtins.input", side_effect=["", "", "", "", "", "q"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daily_log.main(args), 0)
        self.assertFalse(self.log.exists())
        daily_log.save_entry(self.day, {**daily_log.empty_entry(), "duration_min": 42, "note": "retain"}, self.log)
        with patch("builtins.input", side_effect=["", "?", "", "", "", "s"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daily_log.main(args), 0)
        saved = daily_log.load_log(self.log)["days"][self.day.isoformat()]
        self.assertEqual(saved["note"], "retain")
        self.assertIsNone(saved["duration_min"])

    def test_display_strips_terminal_control_characters(self):
        self.candidates(self.row("Unsafe\x1b[2J\nName"))
        text = "\n".join(today.summary_lines(self.snapshot()))
        self.assertNotIn("\x1b", text)

    def run_screen(self, keys, size=(24, 80)):
        state = self.snapshot(dt.datetime.now().astimezone().date())
        state["first_run"] = False
        screen = FakeScreen(keys, size)
        with patch.object(dashboard.T, "load_today", return_value=state), \
             patch.object(dashboard.curses, "wrapper", side_effect=lambda run: run(screen)), \
             patch.object(dashboard.curses, "curs_set"), patch.object(dashboard, "REPORT", self.report):
            action = dashboard.choose_action()
        return action, screen

    def test_today_default_selects_week_and_every_group_is_keyboard_reachable(self):
        action, screen = self.run_screen([10])
        self.assertEqual(action.key, "week")
        first_frame = "\n".join(screen.frames[0].values())
        self.assertIn("STEPS:", first_frame)
        self.assertIn("Peptides/Gray", first_frame)
        for index, group in enumerate(dashboard.GROUPS, 1):
            action, _ = self.run_screen([ord(str(index)), 10])
            self.assertEqual(action.key, dashboard.GROUPS[group][0])

    def test_compact_layout_scroll_review_refresh_and_back(self):
        for size in ((24, 80), (16, 40), (40, 140), (8, 20)):
            with self.subTest(size=size):
                action, screen = self.run_screen([
                    curses.KEY_NPAGE, ord("v"), ord("r"), ord("4"), 27, ord("q"),
                ], size)
                self.assertIsNone(action)
                self.assertTrue(screen.frames)

    def test_global_search_and_no_match_do_not_launch_another_action(self):
        with patch.object(dashboard, "text_input", return_value="experimental"):
            action, _ = self.run_screen([ord("/"), 10])
            self.assertEqual(action.key, "experimental")
        with patch.object(dashboard, "text_input", return_value="does-not-exist"):
            action, _ = self.run_screen([ord("/"), 10, ord("q")])
            self.assertIsNone(action)

    def test_reset_requires_confirmation_from_both_entry_points(self):
        for answer in ("", "no", "RESET"):
            with self.subTest(answer=answer), patch("builtins.input", return_value=answer), \
                 patch.object(dashboard, "run_action", return_value=0) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dashboard.main(["--action", "reset"]), 0)
                self.assertEqual(run.call_count, int(answer == "RESET"))
        with patch.object(dashboard, "text_input", return_value="no"):
            action, _ = self.run_screen([ord("5"), curses.KEY_DOWN, 10, ord("q")])
            self.assertIsNone(action)


class FakeScreen:
    """Bounds-check drawing and drive the real curses loop without a terminal."""

    def __init__(self, keys, size):
        self.keys = iter(keys)
        self.size = size
        self.frames = []
        self.lines = {}

    def getmaxyx(self):
        return self.size

    def keypad(self, enabled):
        pass

    def erase(self):
        self.lines = {}

    def addnstr(self, y, x, text, count, attr=0):
        assert 0 <= y < self.size[0] and 0 <= x < self.size[1]
        assert count <= self.size[1] - x - 1
        self.lines[y] = text[:count]

    def refresh(self):
        self.frames.append(dict(self.lines))

    def getch(self):
        return next(self.keys)


class ActionTests(unittest.TestCase):
    def test_shared_policy_integration_with_only_synthetic_state(self):
        import safety_policy

        row = {
            "id": "synthetic_peptide", "display_name": "Synthetic peptide",
            "class": "peptide", "consideration_scope": "personal_candidate",
            "user_decision": "adopt", "use_status": "in_use", "user_dose": None,
        }
        self.assertFalse(safety_policy.candidate_gate(row)["active_plan_allowed"])
        note = "Chest pain and shortness of breath"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            log = root / "daily.json"
            ledger.write_text(json.dumps({"schema_version": 2, "candidates": [row]}))
            day = dt.date(2026, 9, 7)
            state = today.load_today(root / "missing-report.md", ledger, log, day, week_path=root / "week.json")
            self.assertEqual(state["active"], [])
            self.assertEqual(state["review"][0]["id"], row["id"])
            alert = daily_log.save_entry(day, {**daily_log.empty_entry(), "note": note}, log)
            self.assertEqual(alert, safety_policy.urgent_message(note))
            self.assertIsNotNone(alert)
            self.assertEqual(daily_log.load_log(log)["days"][day.isoformat()]["note"], note)

    def test_existing_actions_and_commands_remain_reachable(self):
        commands = {
            "assessment": ("./hc-supplements",),
            "candidates": (sys.executable, "candidate_manager.py"),
            "weekly": (sys.executable, "weekly_checkin.py"), "bevel": ("./hc-bevel",),
            "report": ("./hc-report",), "question": (sys.executable, "coach.py"),
            "foods": ("./hc-refresh-whole-foods",),
            "food-review": (sys.executable, "week_planner.py", "--view", "food"),
            "food-plan": (sys.executable, "week_planner.py", "--view", "meals"),
            "lifestyle": (sys.executable, "lifestyle_plan.py", "--print"),
            "symptoms": (sys.executable, "symptom_checkin.py"),
            "nootropics": ("./hc-refresh-nootropics",), "experimental": ("./hc-refresh-experimental",),
            "test": (sys.executable, "test_retrieval.py"), "reset": ("./hc-supplements", "--start-over"),
        }
        actions = {action.key: action for action in dashboard.ACTIONS}
        self.assertEqual(len(actions), len(dashboard.ACTIONS))
        self.assertEqual(set(actions), {key for keys in dashboard.GROUPS.values() for key in keys})
        for key, command in commands.items():
            self.assertEqual(actions[key].command, command)
        self.assertIn("GRAY-MARKET", actions["experimental"].title)
        self.assertEqual(dashboard.group_actions("Today", "no-match"), [])

    def test_imports_do_not_load_research_or_models(self):
        result = subprocess.run([
            sys.executable, "-B", "-c",
            "import sys; import today, healthcoach_dashboard; "
            "assert not {'coach', 'supplement_audit', 'candidate_manager', 'mlx_lm', 'sentence_transformers', 'lancedb'} & set(sys.modules)",
        ], cwd=Path(__file__).resolve().parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
