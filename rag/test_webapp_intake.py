"""Regression tests for the one-time comprehensive setup pathway."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import candidate_ledger as CL
import schedule_builder as SB
from webapp import food_preferences as FoodP
from webapp import intake as Intake
from webapp import setup_state as Setup
from webapp.app import app


class ComprehensiveIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.setup_path = root / "setup.json"
        self.intake_path = root / "intake.json"
        self.ledger_path = root / "ledger.json"
        self.food_path = root / "food.json"
        self.schedule_path = root / "schedule.json"
        self.labs_path = root / "labs.json"
        self.patchers = [
            patch.object(Setup, "DEFAULT_PATH", self.setup_path),
            patch.object(Intake, "DEFAULT_PATH", self.intake_path),
            patch.object(CL, "DEFAULT_LEDGER", self.ledger_path),
            patch.object(FoodP, "DEFAULT_PATH", self.food_path),
            patch.object(SB, "DEFAULT_PATH", str(self.schedule_path)),
            patch("webapp.app.L.LABS_PATH", self.labs_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def _valid_form(self):
        return {
            "diet": "whole_food",
            "toggle": ["no_shellfish"],
            "health_goal": ["fat_loss", "strength"],
            "weight_direction": "lose",
            "body_goals": "Reduce waist measurement while preserving strength.",
            "lifestyle_goals": "Sleep consistently and make weekday meals repeatable.",
            "bodyweight_kg": "88",
            "height_cm": "183",
            "age_years": "34",
            "sex": "male",
            "current_lifestyle": "Desk work with a consistent morning walk.",
            "current_sport": "Strength training three days per week.",
            "schedule_notes": "Work Monday through Friday, gym after work.",
            "symptoms": "No current symptoms to report.",
            "dexa_scan_date": "",
            "dexa_body_fat_pct": "",
            "dexa_lean_mass_kg": "",
            "dexa_fat_mass_kg": "",
            "dexa_visceral_fat": "",
            "dexa_bmc_kg": "",
            "dexa_notes": "",
        }

    def test_begin_setup_opens_the_comprehensive_form(self):
        response = self.client.get("/setup/intake")
        self.assertEqual(response.status_code, 200)
        for label in (b"Current body weight", b"Current lifestyle", b"Current sport",
                      b"DEXA", b"Review answers"):
            with self.subTest(label=label):
                self.assertIn(label, response.data)

    def test_missing_required_context_is_not_silently_accepted(self):
        response = self.client.post("/setup/intake", data={"diet": "whole_food"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Answer every required section", response.data)
        self.assertFalse(self.intake_path.exists())

    def test_valid_intake_goes_to_review_without_committing(self):
        response = self.client.post("/setup/intake", data=self._valid_form())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/setup/review"))
        self.assertTrue(self.intake_path.exists())
        self.assertFalse(self.ledger_path.exists())

        review = self.client.get("/setup/review")
        self.assertEqual(review.status_code, 200)
        self.assertIn(b"Review before saving", review.data)
        self.assertIn(b"Clear DEXA data", review.data)
        self.assertIn(b"Strength training three days per week", review.data)

    def test_review_clear_action_changes_only_the_dexa_draft(self):
        self.client.post("/setup/intake", data={**self._valid_form(), "dexa_body_fat_pct": "18.4"})
        response = self.client.post("/setup/review", data={"action": "clear_dexa"})
        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.intake_path.read_text())
        self.assertEqual(saved["dexa"]["body_fat_pct"], "")
        self.assertIn("Strength training three days per week", saved["current_sport"])
        self.assertFalse(self.ledger_path.exists())

    def test_confirm_commits_legacy_food_and_body_fields_and_completes_setup(self):
        self.client.post("/setup/intake", data=self._valid_form())
        response = self.client.post("/setup/review", data={"action": "confirm"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        ledger = CL.load_ledger(self.ledger_path)
        self.assertEqual(ledger["intake"]["goals"], ["fat_loss", "strength"])
        self.assertEqual(ledger["intake"]["bodyweight_kg"], 88.0)
        self.assertEqual(FoodP.load(self.food_path)["toggles"], ["no_shellfish"])
        self.assertTrue(Setup.load(self.setup_path)["complete"])


if __name__ == "__main__":
    unittest.main()
