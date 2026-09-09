# rag/rag_control/test_lane_map.py
"""Every lane_map.json entry must point at a real folder that actually
exists under papers/, and every value must be a lane router.json knows
about. Prevents the map from silently rotting as folders get renamed."""

import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPERS = HERE.parent.parent.parent / "papers"


class LaneMapTests(unittest.TestCase):
    def setUp(self):
        with (HERE / "lane_map.json").open() as f:
            self.lane_map = json.load(f)
        with (HERE / "router.json").open() as f:
            self.router = json.load(f)

    def test_every_mapped_folder_exists_on_disk(self):
        for folder in self.lane_map:
            self.assertTrue((PAPERS / folder).is_dir(), f"missing folder: {folder}")

    def test_every_mapped_lane_is_allowed_by_at_least_one_intent(self):
        all_allowed_lanes = {
            lane for intent in self.router["intents"].values() for lane in intent["lanes"]
        }
        for folder, lane in self.lane_map.items():
            self.assertIn(lane, all_allowed_lanes, f"{folder} -> {lane!r} is not an allowed lane anywhere")

    def test_expected_lanes_are_covered(self):
        expected = {"lipids", "inflam", "hormones-off", "food-floor",
                    "return-train", "desk-sit", "heat", "covid-infect"}
        covered = set(self.lane_map.values())
        self.assertTrue(expected <= covered, f"missing coverage for: {expected - covered}")


if __name__ == "__main__":
    unittest.main()
