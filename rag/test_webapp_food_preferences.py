"""Offline tests for the private web food-preference store.

Diet eligibility itself stays in diet_rules.py; this module only persists and
validates the user's selected preset and exclusion toggles.
"""

import tempfile
import unittest
from pathlib import Path

from webapp import food_preferences as FP


class FoodPreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "food_preferences.json"

    def test_missing_file_uses_unrestricted_whole_food_default(self):
        self.assertEqual(FP.load(self.path), {"diet": "whole_food", "toggles": []})

    def test_save_load_round_trip_deduplicates_and_orders_toggles(self):
        FP.save({"diet": "keto", "toggles": ["no_dairy", "no_grains", "no_dairy"]}, self.path)
        self.assertEqual(FP.load(self.path), {"diet": "keto", "toggles": ["no_dairy", "no_grains"]})

    def test_invalid_diet_is_rejected(self):
        with self.assertRaises(ValueError):
            FP.normalize({"diet": "not_a_real_diet", "toggles": []})

    def test_invalid_toggle_is_rejected(self):
        with self.assertRaises(ValueError):
            FP.normalize({"diet": "whole_food", "toggles": ["not_a_real_toggle"]})

    def test_malformed_file_falls_back_to_default(self):
        self.path.write_text("not json")
        self.assertEqual(FP.load(self.path), {"diet": "whole_food", "toggles": []})


if __name__ == "__main__":
    unittest.main()
