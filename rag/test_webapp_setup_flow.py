"""Regression tests for the setup-first web GUI pathway.

These tests intentionally use Flask's test client only. They verify that the
first-run walkthrough and Settings hub are the doors to data-entry forms,
while the normal result pages stay readable without immediately displaying
every input control.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import candidate_ledger as CL
import schedule_builder as SB
from webapp import food_preferences as FoodP
from webapp import setup_state as Setup
from webapp import schedule_analysis as SA
from webapp.app import app


class SetupFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.setup_path = Path(self.tmp.name) / "web_setup.json"
        self.food_path = Path(self.tmp.name) / "food_preferences.json"
        self.schedule_path = Path(self.tmp.name) / "schedule.json"
        self.analysis_path = Path(self.tmp.name) / "schedule_analysis.json"
        self.labs_path = Path(self.tmp.name) / "labs.json"
        self.patchers = [
            patch.object(Setup, "DEFAULT_PATH", self.setup_path),
            patch.object(FoodP, "DEFAULT_PATH", self.food_path),
            patch.object(SB, "DEFAULT_PATH", str(self.schedule_path)),
            patch.object(SA, "DEFAULT_PATH", self.analysis_path),
            patch("webapp.app.L.LABS_PATH", self.labs_path),
            patch.object(CL, "load_ledger", return_value={
                "intake": {"goals": [], "weight_direction": "unknown"},
                "candidates": [],
            }),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def test_first_home_view_is_the_setup_walkthrough(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Set up HealthCoach", response.data)
        self.assertIn(b"Start with your diet", response.data)
        self.assertIn(b"/settings", response.data)

    def test_settings_is_the_hub_for_all_input_forms(self):
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        for href in ("/food/diet?from=settings", "/food/goals?from=settings",
                     "/symptoms?edit=1", "/schedule?edit=1", "/labs?edit=1"):
            with self.subTest(href=href):
                self.assertIn(href.encode(), response.data)

    def test_setup_step_links_open_the_diet_and_goals_forms(self):
        response = self.client.get("/setup")
        self.assertIn(b"/food/diet?from=setup", response.data)
        self.assertIn(b"/food/goals?from=setup", response.data)

    def test_normal_schedule_page_hides_add_form_until_edit_is_requested(self):
        normal = self.client.get("/schedule")
        editing = self.client.get("/schedule?edit=1")
        self.assertNotIn(b"Add a block", normal.data)
        self.assertIn(b"Add a block", editing.data)
        self.assertIn(b"Edit schedule", normal.data)

    def test_normal_labs_page_hides_input_forms_until_edit_is_requested(self):
        normal = self.client.get("/labs")
        editing = self.client.get("/labs?edit=1")
        self.assertNotIn(b"Add a value manually", normal.data)
        self.assertIn(b"Add a value manually", editing.data)
        self.assertIn(b"Edit labs", normal.data)

    def test_normal_symptom_page_hides_checklist_until_edit_is_requested(self):
        normal = self.client.get("/symptoms")
        editing = self.client.get("/symptoms?edit=1")
        self.assertNotIn(b"Get flags for selected symptoms", normal.data)
        self.assertIn(b"Get flags for selected symptoms", editing.data)
        self.assertIn(b"Start a symptom check-in", normal.data)

    def test_finish_setup_marks_setup_complete_and_returns_home(self):
        Setup.mark_step("diet", path=self.setup_path)
        Setup.mark_step("goals", path=self.setup_path)
        response = self.client.post("/setup/complete")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Setup.load(self.setup_path)["complete"])
        self.assertTrue(response.headers["Location"].endswith("/"))

    def test_finish_setup_refuses_until_required_steps_are_done(self):
        response = self.client.post("/setup/complete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/setup", response.headers["Location"])
        self.assertFalse(Setup.load(self.setup_path)["complete"])


if __name__ == "__main__":
    unittest.main()
