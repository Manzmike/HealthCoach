"""Regression tests for the redesigned first-open and home surfaces."""

import unittest
from unittest.mock import patch

from webapp import setup_state as Setup
from webapp.app import app


class LandingSurfaceTests(unittest.TestCase):
    def test_first_open_has_a_clear_setup_hero_and_generic_model(self):
        with patch.object(Setup, "load", return_value=Setup.empty()):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Begin setup", response.data)
        self.assertIn(b'id="bodyModel"', response.data)
        self.assertIn(b"Generic model", response.data)
        self.assertIn(b"/static/body_model.js", response.data)
        self.assertIn(b"reviewed before it is saved", response.data)

    def test_completed_home_keeps_the_model_but_orients_to_current_data(self):
        with patch.object(Setup, "load", return_value={"complete": True, "steps": {"diet": True, "goals": True}}), \
             patch("webapp.app.T.load_today", return_value={
                 "report_available": False, "profile_saved": False,
             }), \
             patch("webapp.app._load_schedule", return_value={"blocks": []}), \
             patch("webapp.app.L.load_labs", return_value={"entries": {}}):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your current data", response.data)
        self.assertIn(b'id="bodyModel"', response.data)
        self.assertIn(b"Ask a question", response.data)

    def test_model_asset_is_local_and_served_by_the_app(self):
        response = app.test_client().get("/static/body_model.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"webgl", response.data.lower())
        self.assertNotIn(b"https://", response.data)


if __name__ == "__main__":
    unittest.main()
