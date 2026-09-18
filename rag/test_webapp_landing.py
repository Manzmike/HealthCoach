"""Regression tests for the redesigned first-open and home surfaces."""

import unittest
import os
from unittest.mock import patch

from webapp import setup_state as Setup
from webapp.app import app


class LandingSurfaceTests(unittest.TestCase):
    def test_first_open_has_a_clear_setup_hero_and_generic_model(self):
        with patch.object(Setup, "load", return_value=Setup.empty()):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Begin setup", response.data)
        self.assertIn(b"/setup/intake", response.data)
        self.assertIn(b'id="bodyModel"', response.data)
        self.assertIn(b'data-personalized="false"', response.data)
        self.assertIn(b"Add your data to see your metrics", response.data)
        self.assertIn(b"illustrative range matrix", response.data)
        self.assertIn(b"Generic model", response.data)
        self.assertIn(b"/static/body_model.js", response.data)
        self.assertIn(b"reviewed before it is saved", response.data)

    def test_completed_home_keeps_the_model_but_orients_to_current_data(self):
        with patch.object(Setup, "load", return_value={"complete": True, "steps": {"diet": True, "goals": True}}), \
             patch("webapp.app.T.load_today", return_value={
                 "report_available": False, "profile_saved": False,
             }), \
             patch("webapp.app._load_schedule", return_value={"blocks": []}), \
             patch("webapp.app.L.load_labs", return_value={"entries": {}}), \
             patch("webapp.app.Intake.load", return_value={"updated_at": ""}):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your current data", response.data)
        self.assertIn(b'id="bodyModel"', response.data)
        self.assertIn(b"Ask a question", response.data)

    def test_confirmed_data_marks_the_model_as_a_non_carousel_approximation(self):
        with patch.object(Setup, "load", return_value={"complete": True, "steps": {"diet": True, "goals": True}}), \
             patch("webapp.app.T.load_today", return_value={"report_available": False, "profile_saved": False}), \
             patch("webapp.app._load_schedule", return_value={"blocks": []}), \
             patch("webapp.app.L.load_labs", return_value={"entries": {}}), \
             patch("webapp.app.Intake.load", return_value={
                 "updated_at": "2026-09-18T00:00:00+00:00", "bodyweight_kg": "88",
                 "height_cm": "183", "sex": "male", "dexa": {"body_fat_pct": "18.4", "lean_mass_kg": "70"},
             }):
            response = app.test_client().get("/")
        self.assertIn(b'data-personalized="true"', response.data)
        self.assertIn(b"Your confirmed approximation", response.data)
        self.assertIn(b"18.4% body fat", response.data)

    def test_model_asset_is_local_and_served_by_the_app(self):
        response = app.test_client().get("/static/body_model.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"webgl", response.data.lower())
        self.assertIn(b"requestAnimationFrame", response.data)
        self.assertIn(b"PRESETS", response.data)
        self.assertIn(b"MATRIX_DIMENSIONS", response.data)
        self.assertIn(b"buildMatrix", response.data)
        self.assertIn(b"shuffledOrder", response.data)
        self.assertIn(b"crypto.getRandomValues", response.data)
        self.assertIn(b"orderCursor", response.data)
        self.assertIn(b"waist", response.data)
        self.assertIn(b"armScale", response.data)
        self.assertIn(b"legScale", response.data)
        self.assertIn(b"weightKg", response.data)
        self.assertIn(b"body_model_mesh.bin", response.data)
        self.assertIn(b"fetch(", response.data)
        self.assertIn(b"measurementBases", response.data)
        self.assertIn(b"rotateX(-Math.PI / 2)", response.data)
        self.assertIn(b"upright", response.data)
        self.assertIn(b"MODEL_SCALE", response.data)
        self.assertIn(b"VIEW_DISTANCE", response.data)
        self.assertNotIn(b"https://", response.data)

    def test_reference_mesh_asset_and_notice_are_present(self):
        root = os.path.join(os.path.dirname(__file__), "webapp", "static")
        asset = os.path.join(root, "body_model_mesh.bin")
        notice = os.path.join(root, "THIRD_PARTY_NOTICES.md")
        self.assertTrue(os.path.exists(asset))
        self.assertGreater(os.path.getsize(asset), 100_000)
        with open(notice, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("3D-Human-Body-Shape", text)
        self.assertIn("MIT", text)


if __name__ == "__main__":
    unittest.main()
