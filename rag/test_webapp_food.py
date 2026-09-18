"""Route-level tests for /food (webapp/app.py) -- Flask test client, no real
browser. catalog_rows()/load_ledger()/load_saved_profile()/
_load_food_evidence() are mocked with small fixed fixtures rather than the
real ~6,000-line supplement catalog; week_plan.py's own grades()/save()/
rationale() etc. are the real functions (already covered by
test_week_plan.py) -- these tests check wiring: the draft/save/discard
lifecycle, and that a required source/reason is actually enforced."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import candidate_ledger as CL
import supplement_audit as audit
import week_plan as WP
import weekly_food_plan as food_plan
import week_planner as WPL
from webapp import food_draft as FDraft
from webapp import food_analysis as FoodA
from webapp import food_preferences as FoodP
from webapp.app import app
import importlib

webapp_module = importlib.import_module("webapp.app")

_LEDGER = {"intake": {"goals": []}, "candidates": []}

# A resource's "id" is a hash of its own kind+text (see week_plan.resource()/
# validate_rationale()) -- a hand-typed id here would fail exactly the
# check real code enforces to prevent inventing a fake source, so real
# catalog_rows() code always builds these through WP.resource() too.
_SALMON = {"id": "salmon", "display_name": "Salmon", "browse_categories": ["food"], "class": "food",
           "resources": [WP.resource("USDA nutrition composition entry.", "nutrition")]}
_KALE_NO_SOURCES = {"id": "kale", "display_name": "Kale", "browse_categories": ["food"], "class": "food"}


class _IsolatedFoodState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.week_plan_path = Path(self.tmp.name) / "week_plan.json"
        self.draft_path = Path(self.tmp.name) / "food_draft.json"
        self.food_preferences_path = Path(self.tmp.name) / "food_preferences.json"
        for patcher in (
            patch.object(WP, "DEFAULT_PATH", self.week_plan_path),
            patch.object(FDraft, "DEFAULT_PATH", self.draft_path),
            patch.object(FoodP, "DEFAULT_PATH", self.food_preferences_path),
            patch.object(CL, "load_ledger", return_value=dict(_LEDGER)),
            patch.object(audit, "load_saved_profile", return_value={}),
            patch.object(food_plan, "_load_food_evidence", return_value={}),
            patch.object(WPL, "catalog_rows", return_value=[dict(_SALMON), dict(_KALE_NO_SOURCES)]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()


class FoodPageTests(_IsolatedFoodState):
    def test_get_lists_catalog_entries_unselected_and_not_dirty(self):
        r = self.client.get("/food")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Salmon", r.data)
        self.assertIn(b"Kale", r.data)
        self.assertIn(b"No unsaved changes", r.data)

    def test_selecting_an_item_with_no_sources_is_refused_with_an_explanation(self):
        r = self.client.get("/food/select/kale", follow_redirects=True)
        self.assertIn(b"no usable source/resource", r.data)

    def test_selecting_an_unknown_item_redirects_with_an_error(self):
        r = self.client.get("/food/select/not_a_real_item", follow_redirects=True)
        self.assertIn(b"Item not found", r.data)

    def test_select_form_lists_the_items_actual_sources(self):
        r = self.client.get("/food/select/salmon")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"USDA nutrition composition entry", r.data)


class FoodSelectTests(_IsolatedFoodState):
    def _select_salmon(self, **overrides):
        data = {
            "source_index": "0",
            "goal": "Support recovery after evening training sessions.",
            "personal_reason": "High protein and omega-3s fit my current cut goal.",
            "review_trigger": "Review if a lipid panel or GI symptoms change.",
        }
        data.update(overrides)
        return self.client.post("/food/select/salmon", data=data, follow_redirects=True)

    def test_a_complete_justification_selects_the_item_as_a_draft(self):
        r = self._select_salmon()
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Unselect", r.data)
        self.assertIn(b"unsaved selection changes", r.data)

    def test_a_short_reason_is_rejected_and_nothing_is_selected(self):
        r = self._select_salmon(goal="too short")
        self.assertIn(b"hard reason needs", r.data.lower().replace(b"a hard", b"hard"))
        r2 = self.client.get("/food")
        self.assertIn(b"No unsaved changes", r2.data)

    def test_missing_source_selection_is_rejected(self):
        r = self._select_salmon(source_index="-1")
        self.assertIn(b"Choose one of the listed", r.data)

    def test_unselecting_clears_the_draft_selection(self):
        self._select_salmon()
        r = self.client.post("/food/unselect/salmon", follow_redirects=True)
        self.assertIn(b"No unsaved changes", r.data)
        self.assertIn(b"Select</button>", r.data)

    def test_selecting_then_unselecting_the_same_item_returns_to_clean(self):
        """A second real bug: "dirty" was defined as "a draft file exists
        on disk", not "the draft differs from baseline" -- select-then-
        unselect left a draft file with content identical to the seeded
        baseline, which the old definition still reported as dirty."""
        self._select_salmon()
        r = self.client.post("/food/unselect/salmon", follow_redirects=True)
        self.assertIn(b"No unsaved changes", r.data)

    def test_unselecting_an_item_that_was_never_selected_creates_no_draft(self):
        """A real bug caught by this test: unselect() unconditionally wrote
        a draft (the freshly-seeded week) even for a no-op pop on an item
        that was never selected, which manufactured "unsaved changes" out
        of nothing."""
        r = self.client.post("/food/unselect/salmon", follow_redirects=True)
        self.assertIn(b"No unsaved changes", r.data)
        start = WP.monday(dt.date.today())
        self.assertIsNone(FDraft.load_draft(start, path=self.draft_path))


class FoodSaveDiscardTests(_IsolatedFoodState):
    def _select_salmon(self):
        return self.client.post("/food/select/salmon", data={
            "source_index": "0",
            "goal": "Support recovery after evening training sessions.",
            "personal_reason": "High protein and omega-3s fit my current cut goal.",
            "review_trigger": "Review if a lipid panel or GI symptoms change.",
        })

    def test_saving_with_no_reason_is_refused(self):
        self._select_salmon()
        r = self.client.post("/food/save", data={"reason": ""}, follow_redirects=True)
        self.assertIn(b"reason is required", r.data.lower())

    def test_saving_with_a_reason_commits_and_clears_the_draft(self):
        self._select_salmon()
        r = self.client.post("/food/save", data={"reason": "Trying salmon this week for recovery."},
                              follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No unsaved changes", r.data)
        self.assertIn(b"Unselect", r.data)  # still selected -- now as the saved baseline, not a draft
        saved = WP.load(self.week_plan_path)
        start = next(iter(saved["weeks"]))
        self.assertIn("salmon", saved["weeks"][start]["selected"])
        self.assertEqual(len(saved["weeks"][start]["history"]), 1)

    def test_discarding_drops_the_draft_without_saving(self):
        self._select_salmon()
        r = self.client.post("/food/discard", follow_redirects=True)
        self.assertIn(b"No unsaved changes", r.data)
        self.assertIn(b"Select</button>", r.data)
        self.assertFalse(self.week_plan_path.exists())


class FoodGoalsTests(_IsolatedFoodState):
    def test_food_page_links_to_goals_and_shows_current_goal(self):
        with patch.object(CL, "load_ledger", return_value={
            "intake": {"goals": ["recovery"], "weight_direction": "maintain"},
            "candidates": [],
        }):
            r = self.client.get("/food")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Edit health goals", r.data)
        self.assertIn(b"Recovery", r.data)

    def test_get_goals_page_renders_saved_values(self):
        with patch.object(CL, "load_ledger", return_value={
            "intake": {"goals": ["recovery", "sleep"], "weight_direction": "lose"},
            "candidates": [],
        }):
            r = self.client.get("/food/goals")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Health goals", r.data)
        self.assertIn(b'value="recovery" selected', r.data)
        self.assertIn(b'value="lose" selected', r.data)

    def test_post_goals_saves_the_same_intake_fields_used_by_food_grading(self):
        saved = {}
        with patch.object(CL, "save_ledger", side_effect=lambda value: saved.setdefault("value", value)):
            r = self.client.post("/food/goals", data={
                "goal": ["recovery", "sleep"],
                "weight_direction": "maintain",
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(saved["value"]["intake"]["goals"], ["recovery", "sleep"])
        self.assertEqual(saved["value"]["intake"]["weight_direction"], "maintain")


class FoodAnalysisTests(_IsolatedFoodState):
    def _selected_state(self):
        return {
            "start": "2026-09-14",
            "week": {"selected": {
                "salmon": {"name": "Salmon", "category": "food"},
                "oats": {"name": "Oats", "category": "food"},
            }},
            "ledger": {"intake": {"goals": ["recovery"]}},
            "food_preferences": {"diet": "keto", "toggles": ["no_dairy"]},
        }

    def test_analyze_queries_selected_foods_and_goals_then_persists_sections(self):
        results = [{"topic": "food", "text": "Salmon and oats", "no_evidence": False,
                    "answer": "**Use:** Evidence summary", "related": ""}]
        sections = [{"topic": "food", "answer_html": "<p>Evidence summary</p>",
                     "no_evidence": False, "related_html": "", "text": "Salmon and oats",
                     "offer_fetch": False}]
        with patch.object(webapp_module, "_food_state", return_value=self._selected_state()), \
             patch.object(webapp_module.coach, "answer_question", return_value=results) as answer, \
             patch.object(webapp_module, "_sections_from_results", return_value=sections), \
             patch.object(FoodA, "save") as save:
            r = self.client.post("/food/analyze")
        self.assertEqual(r.status_code, 302)
        query = answer.call_args.args[0]
        self.assertIn("Salmon, Oats", query)
        self.assertIn("Keto / very low-carb", query)
        self.assertIn("No dairy", query)
        self.assertIn("recovery", query)
        save.assert_called_once()
        self.assertEqual(save.call_args.args[0], ["Oats", "Salmon"])
        self.assertEqual(save.call_args.args[1], sections)

    def test_analyze_without_foods_is_refused_without_querying_the_model(self):
        state = self._selected_state()
        state["week"]["selected"] = {}
        with patch.object(webapp_module, "_food_state", return_value=state), \
             patch.object(webapp_module.coach, "answer_question") as answer:
            r = self.client.post("/food/analyze")
        self.assertEqual(r.status_code, 302)
        self.assertIn("Select+at+least+one+food", r.headers["Location"])
        answer.assert_not_called()

    def test_food_page_renders_only_analysis_for_the_current_selection(self):
        self.client.post("/food/select/salmon", data={
            "source_index": "0",
            "goal": "Support recovery after evening training sessions.",
            "personal_reason": "High protein and omega-3s fit my current cut goal.",
            "review_trigger": "Review if a lipid panel or GI symptoms change.",
        })
        analysis = {"foods": ["Salmon"], "analyzed_at": "2026-09-18T06:00:00",
                    "sections": [{"no_evidence": False, "answer_html": "<p>Use salmon.</p>",
                                   "related_html": "", "text": "Salmon", "topic": "food"}]}
        with patch.object(FoodA, "load", return_value=analysis):
            r = self.client.get("/food")
        self.assertIn(b"Evidence review", r.data)
        self.assertIn(b"Use salmon.", r.data)

    def test_export_contains_selected_food_reason_and_source(self):
        self.client.post("/food/select/salmon", data={
            "source_index": "0",
            "goal": "Support recovery after evening training sessions.",
            "personal_reason": "High protein and omega-3s fit my current cut goal.",
            "review_trigger": "Review if a lipid panel or GI symptoms change.",
        })
        r = self.client.get("/food/export")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "text/plain")
        self.assertIn(b"## Salmon", r.data)
        self.assertIn(b"Why it fits: High protein and omega-3s fit my current cut goal.", r.data)
        self.assertIn(b"[nutrition] USDA nutrition composition entry.", r.data)


class FoodDietTests(_IsolatedFoodState):
    def test_get_diet_page_renders_saved_preset_and_toggles(self):
        with patch.object(FoodP, "load", return_value={"diet": "keto", "toggles": ["no_dairy"]}):
            r = self.client.get("/food/diet")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Diet first", r.data)
        self.assertIn(b'value="keto" selected', r.data)
        self.assertIn(b'value="no_dairy" checked', r.data)

    def test_post_diet_saves_normalized_preferences(self):
        saved = {}
        with patch.object(FoodP, "save", side_effect=lambda value, path: saved.setdefault("value", value)):
            r = self.client.post("/food/diet", data={
                "diet": "vegetarian",
                "toggle": ["no_dairy", "no_dairy"],
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(saved["value"], {"diet": "vegetarian", "toggles": ["no_dairy"]})

    def test_food_page_shows_diet_and_link_to_change_it(self):
        with patch.object(FoodP, "load", return_value={"diet": "vegetarian", "toggles": []}):
            r = self.client.get("/food")
        self.assertIn(b"Vegetarian", r.data)
        self.assertIn(b"Change diet", r.data)

    def test_server_refuses_selecting_food_excluded_by_diet(self):
        yogurt = {"id": "plain_yogurt", "display_name": "Plain yogurt", "browse_categories": ["food"],
                  "class": "food", "resources": [WP.resource("USDA yogurt entry.", "nutrition")]}
        with patch.object(WPL, "catalog_rows", return_value=[dict(_SALMON), yogurt]), \
             patch.object(FoodP, "load", return_value={"diet": "vegan", "toggles": []}):
            r = self.client.get("/food/select/plain_yogurt", follow_redirects=True)
        self.assertIn(b"does not fit the selected diet", r.data)

    def test_food_page_marks_excluded_rows_instead_of_offering_select(self):
        yogurt = {"id": "plain_yogurt", "display_name": "Plain yogurt", "browse_categories": ["food"],
                  "class": "food", "resources": [WP.resource("USDA yogurt entry.", "nutrition")]}
        with patch.object(WPL, "catalog_rows", return_value=[dict(_SALMON), yogurt]), \
             patch.object(FoodP, "load", return_value={"diet": "vegan", "toggles": []}):
            r = self.client.get("/food")
        self.assertIn(b"Not available for this diet", r.data)
        self.assertNotIn(b'href="/food/select/plain_yogurt"', r.data)

    def test_changing_diet_cannot_strand_a_selected_food(self):
        state = {"start": "2026-09-14", "week": {"selected": {
            "salmon": {"name": "Salmon", "category": "food"},
        }}}
        with patch.object(webapp_module, "_food_state", return_value={
            **state, "food_preferences": {"diet": "whole_food", "toggles": []},
        }), patch.object(FoodP, "save") as save:
            r = self.client.post("/food/diet", data={"diet": "vegan"}, follow_redirects=True)
        self.assertIn(b"Remove or replace selected foods first", r.data)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
