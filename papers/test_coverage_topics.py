"""Offline contract tests for workout/lifestyle and whole-food topic coverage."""

import unittest

import fetch_papers as fp


class TopicCoverageContractsTests(unittest.TestCase):
    def test_each_food_family_has_focused_human_queries(self):
        expected = {
            "01_food_inflammation/food_families/fruit",
            "01_food_inflammation/food_families/vegetable",
            "01_food_inflammation/food_families/grain",
            "01_food_inflammation/food_families/legume",
            "01_food_inflammation/food_families/nut_seed",
            "01_food_inflammation/food_families/animal_protein",
            "01_food_inflammation/food_families/seafood",
            "01_food_inflammation/food_families/sea_vegetable",
            "01_food_inflammation/food_families/dairy_fermented_fat",
            "01_food_inflammation/food_families/herb_spice_cocoa",
            "01_food_inflammation/food_families/honey",
        }
        actual = {topic["folder"] for topic in fp.WHOLE_FOOD_FAMILY_TOPICS}
        self.assertEqual(actual, expected)
        for topic in fp.WHOLE_FOOD_FAMILY_TOPICS:
            self.assertGreaterEqual(len(topic["queries"]), 3)
            self.assertTrue(all("human" in q.lower() or "adult" in q.lower() for q in topic["queries"]))

    def test_every_training_topic_has_multiple_focused_queries(self):
        topics = [t for t in fp.TOPICS if t["folder"].startswith("02_training_desk/")]
        self.assertGreaterEqual(len(topics), 16)
        self.assertTrue(all(len(topic["queries"]) >= 2 for topic in topics))

    def test_lifestyle_topics_cover_sleep_and_work_life(self):
        folders = {t["folder"] for t in fp.TOPICS if t["folder"].startswith("03_sleep_stress/")}
        self.assertIn("03_sleep_stress/sleep_best_practices", folders)
        self.assertIn("03_sleep_stress/burnout", folders)
        self.assertIn("03_sleep_stress/sedentary_behavior", folders)

    def test_no_new_coverage_topic_uses_refusal_or_gray_folder(self):
        for topic in fp.WHOLE_FOOD_FAMILY_TOPICS:
            self.assertFalse(topic["folder"].startswith("08_peptides_gray/"))
            self.assertFalse(topic["folder"].startswith("05_fat_loss_drugs/"))

    def test_each_food_family_has_anchor_terms_for_oa_screening(self):
        for topic in fp.WHOLE_FOOD_FAMILY_TOPICS:
            family = topic["folder"].rsplit("/", 1)[-1]
            self.assertIn(family, fp.ANCHORS)
            self.assertGreaterEqual(len(fp.ANCHORS[family]), 2)

    def test_thin_topics_include_known_open_access_human_seeds(self):
        by_folder = {topic["folder"]: topic for topic in fp.TOPICS}
        self.assertIn(("PMC", "PMC6543994"), by_folder["02_training_desk/heat_acclimatization"]["seeds"])
        self.assertIn(("PMC", "PMC12732512"), by_folder["03_sleep_stress/sedentary_behavior"]["seeds"])
        self.assertIn(("MED", "37545570"), by_folder["01_food_inflammation/food_families/sea_vegetable"]["seeds"])
        self.assertIn(("PMC", "PMC4620724"), by_folder["01_food_inflammation/garlic_food"]["seeds"])
        self.assertIn(("MED", "33552217"), by_folder["01_food_inflammation/food_families/honey"]["seeds"])


if __name__ == "__main__":
    unittest.main()
