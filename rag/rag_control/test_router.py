# rag/rag_control/test_router.py
import json
import unittest
from pathlib import Path

from rag_control import router as R

HERE = Path(__file__).resolve().parent


class ClassifyTests(unittest.TestCase):
    def test_single_intent_match(self):
        self.assertEqual(R.classify("I dropped after at lunch for an hour."), ["sleep_eds"])

    def test_zero_intent_match_returns_empty_list(self):
        self.assertEqual(R.classify("does creatine affect sleep"), [])

    def test_covid_vax_can_fire(self):
        """Regression test for the pack bug: _INTENT_HINTS had no covid_vax entry."""
        self.assertIn("covid_vax", R.classify("did the covid vaccine cause myocarditis"))

    def test_multi_intent_match(self):
        matched = R.classify("Even off tirzepatide I still wake at 2.")
        self.assertIn("sleep_eds", matched)
        self.assertIn("incretin", matched)

    def test_no_default_if_unknown_anywhere(self):
        self.assertNotIn("default_if_unknown", R.ROUTER)


class AllowedLanesTests(unittest.TestCase):
    def test_zero_match_means_no_restriction(self):
        self.assertIsNone(R.allowed_lanes([]))

    def test_single_intent_returns_its_lanes(self):
        lanes = R.allowed_lanes(["sleep_eds"])
        self.assertIn("sleep-OSA", lanes)
        self.assertNotIn("incretin-context", lanes)

    def test_multi_intent_is_a_union_incretin_context_survives(self):
        """E06: sleep_eds does not list incretin-context, but incretin does --
        the union must keep it, per the approved spec correction."""
        lanes = R.allowed_lanes(["sleep_eds", "incretin"])
        self.assertIn("incretin-context", lanes)
        self.assertIn("sleep-OSA", lanes)


class LeftoverForbidTests(unittest.TestCase):
    def test_single_intent_gets_its_full_forbid_list(self):
        forbids = R.leftover_forbid_lanes(["sleep_eds"])
        self.assertIn("incretin-context", forbids)
        self.assertIn("peptides", forbids)

    def test_multi_intent_removes_lanes_allowed_by_the_other_intent(self):
        """incretin allows incretin-context, so it must NOT appear in the
        leftover forbid set once incretin is also matched."""
        forbids = R.leftover_forbid_lanes(["sleep_eds", "incretin"])
        self.assertNotIn("incretin-context", forbids)
        self.assertIn("peptides", forbids)  # still forbidden, nothing allows it

    def test_zero_intent_has_no_drift_check_at_all(self):
        self.assertEqual(R.leftover_forbid_lanes([]), set())


class LeadIntentTests(unittest.TestCase):
    def test_sleep_eds_leads_over_incretin(self):
        self.assertEqual(R.lead_intent(["incretin", "sleep_eds"]), "sleep_eds")

    def test_single_intent_is_its_own_lead(self):
        self.assertEqual(R.lead_intent(["lipids"]), "lipids")

    def test_empty_has_no_lead(self):
        self.assertIsNone(R.lead_intent([]))


class BoostForTests(unittest.TestCase):
    def test_personal_grade_a_multiplies(self):
        self.assertAlmostEqual(R.boost_for({"personal": True, "grade": "A"}), 3.0 * 1.5)

    def test_grade_c_zeroes_out_even_if_personal(self):
        self.assertEqual(R.boost_for({"personal": True, "grade": "C"}), 0.0)

    def test_non_personal_grade_b_is_baseline(self):
        self.assertAlmostEqual(R.boost_for({"personal": False, "grade": "B"}), 1.0)


class CritiqueTests(unittest.TestCase):
    def test_universal_reject_fires_regardless_of_intent(self):
        result = R.critique("You should start TRT now.", [], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])

    def test_doses_or_orders_drug_action_fires_even_as_secondary_lane(self):
        draft = "Sleep first. Also, take 7.5mg of tirzepatide next week to push through the nausea."
        result = R.critique(draft, ["sleep_eds", "incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])
        self.assertIn("doses_or_orders_drug_action", result["flags"])

    def test_concludes_vaccine_caused_condition_fires(self):
        draft = "The vaccine caused your sleep apnea, so stop worrying about a sleep study."
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])
        self.assertIn("concludes_vaccine_caused_condition", result["flags"])

    def test_vaccine_risk_fact_without_causal_conclusion_passes(self):
        draft = "Myocarditis is a known rare risk in young men after mRNA vaccination. Your witnessed pauses are an airway question for a sleep clinic."
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertTrue(result["ok"])

    def test_negated_dose_instruction_does_not_fire(self):
        draft = "Do not increase your tirzepatide dose without talking to your prescriber."
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("doses_or_orders_drug_action", result["flags"])

    def test_negated_dose_change_instruction_does_not_fire(self):
        draft = "If still on tirzepatide: message the prescriber about fatigue. Do not change the dose yourself."
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("doses_or_orders_drug_action", result["flags"])

    def test_negated_vaccine_causation_denial_does_not_fire(self):
        draft = "The vaccine did not cause your sleep apnea."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("concludes_vaccine_caused_condition", result["flags"])

    def test_unlikely_vaccine_causation_denial_does_not_fire(self):
        draft = "It is unlikely the vaccine caused your sleep apnea; witnessed pauses are an airway question."
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("concludes_vaccine_caused_condition", result["flags"])

    def test_negated_dose_instruction_with_contraction_does_not_fire(self):
        draft = "Don't increase your tirzepatide dose without talking to your prescriber."
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("doses_or_orders_drug_action", result["flags"])

    def test_reinforced_causation_with_unrelated_negation_word_still_fires(self):
        draft = "There's no doubt the vaccine caused your sleep apnea, so file a report."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("concludes_vaccine_caused_condition", result["flags"])

    def test_must_include_if_drowsy(self):
        result = R.critique("Move dinner earlier.", ["sleep_eds"], action_count=1, primary_count=1, drowsy=True)
        self.assertFalse(result["ok"])
        self.assertIn("missing_drowsy_drive_line", result["flags"])

    def test_drowsy_line_present_passes(self):
        draft = "Do not drive while fighting sleep. Move dinner earlier."
        result = R.critique(draft, ["sleep_eds"], action_count=1, primary_count=1, drowsy=True)
        self.assertTrue(result["ok"])

    def test_actions_over_three_fails(self):
        result = R.critique("fine text", [], action_count=4, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])
        self.assertIn("actions_gt_3", result["flags"])

    def test_ok_draft_returns_no_fallback(self):
        result = R.critique("Move dinner earlier and talk to your prescriber.", [], action_count=1, primary_count=1, drowsy=False)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["fallback"])

    def test_failing_draft_returns_the_fallback_plan_verbatim(self):
        result = R.critique("Start TRT.", [], action_count=1, primary_count=1, drowsy=False)
        self.assertEqual(result["fallback"], R.CRITIC["fallback_plan"])


if __name__ == "__main__":
    unittest.main()
