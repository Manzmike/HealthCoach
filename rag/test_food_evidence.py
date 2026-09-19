"""Offline regression tests for explicit food evidence routing and refreshes."""

import unittest

import food_evidence as fe
import supplement_audit as audit


class FoodRoutingTests(unittest.TestCase):
    def test_legacy_saffron_and_tamarind_rows_use_explicit_parent_families(self):
        saffron = next(c for c in audit.WHOLE_FOOD_CATALOG if c.key == "saffron_food")
        tamarind = next(c for c in audit.WHOLE_FOOD_CATALOG if c.key == "tamarind")
        self.assertIn("01_food_inflammation/food_families/herb_spice_cocoa", saffron.folders)
        self.assertIn("01_food_inflammation/food_families/fruit", tamarind.folders)
        self.assertIn("spice", saffron.aliases)
        self.assertIn("fruit", tamarind.aliases)

    def test_variant_keeps_item_route_and_declared_family_route(self):
        folders = audit.food_evidence_folders(
            "gala_apples", "01_food_inflammation/whole_food_library_v2/fruit"
        )
        self.assertIn("01_food_inflammation/whole_food_library/gala_apples", folders)
        self.assertIn("01_food_inflammation/whole_food_library_v2/fruit", folders)
        self.assertIn("01_food_inflammation/food_families/fruit", folders)

    def test_variant_has_explicit_parent_alias_for_parent_food_evidence(self):
        aliases = audit.food_evidence_aliases("gala_apples", "Gala apples")
        self.assertIn("gala apples", aliases)
        self.assertIn("apple", aliases)
        self.assertIn("apples", aliases)

    def test_word_boundary_keeps_pineapple_from_matching_plain_apple(self):
        candidate = audit.Candidate(
            "apples", "Apples", audit.QUEUE_WHOLE_FOOD, ("food",), (), ("apple", "apples")
        )
        self.assertFalse(audit.hit_is_on_topic(candidate, {"text": "Pineapple was served."}))
        self.assertTrue(audit.hit_is_on_topic(candidate, {"text": "Apple consumption was measured."}))


class RefreshTests(unittest.TestCase):
    def test_route_signature_marks_old_record_stale(self):
        old = {"schema_version": "old", "route_signature": "old-route"}
        self.assertTrue(fe.needs_refresh(old, "new-route"))

    def test_current_record_is_reused(self):
        current = {"schema_version": fe.FOOD_EVIDENCE_SCHEMA_VERSION, "route_signature": "route-1"}
        self.assertFalse(fe.needs_refresh(current, "route-1"))


class DirectFamilyEvidenceTests(unittest.TestCase):
    def test_explicit_family_rows_can_restore_sources_missed_by_ranked_search(self):
        candidate = next(c for c in audit.WHOLE_FOOD_CATALOG if c.key == "gala_apples")
        rows = [
            {
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "A",
                "doi": "10.1000/fruit-one",
                "text": "Participants in a whole fruit consumption dietary intervention were measured.",
            },
            {
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "B",
                "doi": "10.1000/fruit-two",
                "text": "Participants increased fruit intake and recorded food frequency outcomes.",
            },
            {
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "A",
                "doi": "10.1000/not-food",
                "text": "Participants completed a medication trial with no dietary exposure.",
            },
        ]
        hits = fe.direct_food_hits(candidate, rows)
        self.assertEqual({hit["doi"] for hit in hits}, {"10.1000/fruit-one", "10.1000/fruit-two"})

    def test_direct_family_rows_make_cached_evidence_strong(self):
        candidate = next(c for c in audit.WHOLE_FOOD_CATALOG if c.key == "gala_apples")
        base = audit.Evidence("NONE", "—", 0, 0, "not established", [])
        rows = [
            {
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "A",
                "doi": "10.1000/fruit-one",
                "text": "Participants in a whole fruit consumption dietary intervention were measured.",
            },
            {
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "B",
                "doi": "10.1000/fruit-two",
                "text": "Participants increased fruit intake and recorded food frequency outcomes.",
            },
        ]
        result = fe.augment_food_evidence(base, candidate, rows)
        self.assertEqual(result.coverage, "STRONG")
        self.assertEqual(result.unique_papers, 2)

    def test_qualifying_direct_chunk_wins_over_same_doi_ranked_chunk(self):
        candidate = next(c for c in audit.WHOLE_FOOD_CATALOG if c.key == "gala_apples")
        ranked = audit.Evidence(
            "WEAK", "A", 1, 1, "not established", [{
                "folder": "01_food_inflammation/food_families/fruit",
                "grade": "A",
                "doi": "10.1000/fruit-one",
                "text": "The paper discusses a secondary outcome without a dietary exposure signal.",
            }]
        )
        rows = [{
            "folder": "01_food_inflammation/food_families/fruit",
            "grade": "A",
            "doi": "10.1000/fruit-one",
            "text": "Participants in a whole fruit consumption dietary intervention were measured.",
        }, {
            "folder": "01_food_inflammation/food_families/fruit",
            "grade": "B",
            "doi": "10.1000/fruit-two",
            "text": "Participants increased fruit intake and recorded food frequency outcomes.",
        }]
        result = fe.augment_food_evidence(ranked, candidate, rows)
        self.assertEqual(result.coverage, "STRONG")
