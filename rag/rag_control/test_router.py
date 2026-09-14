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


DOSE_FLAG = "doses_or_orders_drug_action"
CAUSE_FLAG = "concludes_vaccine_caused_condition"


class CritiqueTests(unittest.TestCase):
    def flags(self, draft, matched):
        return R.critique(draft, matched, action_count=1, primary_count=1, drowsy=False)["flags"]

    def test_universal_reject_fires_regardless_of_intent(self):
        result = R.critique("You should start TRT now.", [], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])

    def test_doses_or_orders_drug_action_fires_even_as_secondary_lane(self):
        """Acceptance case 6."""
        draft = "Sleep first. Also, take 7.5mg of tirzepatide next week to push through the nausea."
        result = R.critique(draft, ["sleep_eds", "incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])
        self.assertIn("doses_or_orders_drug_action", result["flags"])

    def test_concludes_vaccine_caused_condition_fires(self):
        """Acceptance case 12."""
        draft = "The vaccine caused your sleep apnea, so stop worrying about a sleep study."
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertFalse(result["ok"])
        self.assertIn("concludes_vaccine_caused_condition", result["flags"])

    def test_vaccine_risk_fact_without_causal_conclusion_passes(self):
        draft = "Myocarditis is a known rare risk in young men after mRNA vaccination. Your witnessed pauses are an airway question for a sleep clinic."
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertTrue(result["ok"])

    # ----------------------------------------------------------------
    # Negation awareness. The two universal hard-rejects must fire on a
    # genuine order/conclusion but stay silent on safe text that DENIES
    # the same surface pattern. Cases 1-15 below are the acceptance set;
    # each one is a phrasing an earlier implementation got wrong.
    #
    # Cases 6 and 12 keep the brief's original test names above
    # (test_doses_or_orders_drug_action_fires_even_as_secondary_lane and
    # test_concludes_vaccine_caused_condition_fires) rather than being
    # duplicated here.
    # ----------------------------------------------------------------

    # -- must NOT flag a dose order --

    def test_1_negated_dose_instruction_does_not_fire(self):
        draft = "Do not increase your tirzepatide dose without talking to your prescriber."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_2_negation_in_a_later_sentence_of_a_multi_sentence_draft(self):
        draft = "If still on tirzepatide: message the prescriber about fatigue. Do not change the dose yourself."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_3_negated_dose_instruction_with_contraction_does_not_fire(self):
        """A bare `n't` token can never match real text -- the contraction
        must be recognised as part of the whole word ("Don't")."""
        draft = "Don't increase your tirzepatide dose without talking to your prescriber."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_4_negation_several_words_ahead_of_the_verb_still_suppresses(self):
        """The lookback must be wide enough to span an intervening phrase."""
        draft = "You should not go ahead and increase your tirzepatide dose this week."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_5_no_way_phrasing_suppresses(self):
        """Bare "no" is not a negation cue (see case 13), but "no way" is."""
        draft = "There is no way you should stop your tirzepatide dose right now."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    # -- must flag a dose order --

    def test_7_negated_sentence_does_not_suppress_a_violation_in_the_next(self):
        draft = "Don't skip your metformin dose. Increase your tirzepatide dose to 10mg this week."
        self.assertIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_8_negated_clause_does_not_suppress_a_later_clause_violation(self):
        draft = "Don't skip your metformin dose, but increase your tirzepatide dose to 10mg this week."
        self.assertIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_9_parenthetical_comma_does_not_hide_a_single_instruction(self):
        """One instruction interrupted by an aside is still one instruction:
        the companion-word search must see past ", if you tolerate it well,"."""
        draft = "Increase, if you tolerate it well, your tirzepatide dose to 10mg this week."
        self.assertIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    # -- must NOT flag a vaccine causal conclusion --

    def test_10_vaccine_causation_denial_does_not_fire(self):
        draft = "The vaccine did not cause your sleep apnea."
        self.assertNotIn(CAUSE_FLAG, self.flags(draft, ["covid_vax"]))

    def test_11_unlikely_vaccine_causation_denial_does_not_fire(self):
        draft = "It is unlikely the vaccine caused your sleep apnea; witnessed pauses are an airway question."
        self.assertNotIn(CAUSE_FLAG, self.flags(draft, ["sleep_eds", "covid_vax"]))

    # -- must flag a vaccine causal conclusion --

    def test_13_reinforcing_no_doubt_is_not_a_negation(self):
        """"no doubt" strengthens the claim -- suppressing here would let an
        unsafe assertion pass as safe, which is worse than over-flagging."""
        draft = "There's no doubt the vaccine caused your sleep apnea, so file a report."
        self.assertIn(CAUSE_FLAG, self.flags(draft, ["covid_vax"]))

    def test_14_negation_in_earlier_comma_clause_does_not_suppress_a_later_one(self):
        draft = "There's no evidence the flu shot causes fatigue, but the vaccine caused your sleep apnea, so file a report."
        self.assertIn(CAUSE_FLAG, self.flags(draft, ["covid_vax"]))

    def test_15_parenthetical_comma_does_not_hide_a_causal_conclusion(self):
        draft = "Your sleep apnea, in my opinion, was caused by the vaccine."
        self.assertIn(CAUSE_FLAG, self.flags(draft, ["covid_vax"]))

    # -- design property: an aside is stepped over, a new clause is not --

    def test_negation_reaches_across_a_parenthetical_aside(self):
        """Mirror image of case 8: here the comma opens an aside, not a new
        assertion, so the leading "not" must still reach the verb."""
        draft = "Do not, under any circumstances, increase your tirzepatide dose."
        self.assertNotIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_an_aside_never_hides_a_companion_word_inside_it(self):
        """Stripping asides may only SHORTEN the distance to a companion
        word, never remove one -- here the drug object is itself the
        comma-delimited segment."""
        draft = "Increase, your tirzepatide dose, next week."
        self.assertIn(DOSE_FLAG, self.flags(draft, ["incretin"]))

    def test_an_aside_never_hides_a_causal_companion_word(self):
        draft = "Your sleep apnea, was caused, in my view, by the vaccine."
        self.assertIn(CAUSE_FLAG, self.flags(draft, ["sleep_eds", "covid_vax"]))

    # -- round 5: a trigger sitting right after a bare comma, with nothing
    # (or a coordinator-led clause) between it and the comma, must not pick
    # up an earlier clause's negation; and a newline is a hard boundary too.

    def test_comma_into_unrelated_clause_does_not_suppress_a_later_violation(self):
        draft = "Don't skip your metformin dose, increase your tirzepatide dose to 10mg this week."
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("doses_or_orders_drug_action", result["flags"])

    def test_causal_comma_into_unrelated_clause_does_not_suppress_a_later_violation(self):
        draft = "It is not a coincidence, the vaccine caused your sleep apnea."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("concludes_vaccine_caused_condition", result["flags"])

    def test_coordinator_clauses_negation_does_not_bleed_into_a_later_clause(self):
        draft = "Keep metformin steady, but do not skip meals, take 7.5mg of tirzepatide tonight."
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("doses_or_orders_drug_action", result["flags"])

    def test_bulleted_draft_does_not_leak_negation_across_lines(self):
        draft = "This week:\n- Do not drive while fighting sleep\n- Increase your tirzepatide dose to 10mg"
        result = R.critique(draft, ["incretin"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("doses_or_orders_drug_action", result["flags"])

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


class RecommendationOnlyTermsTests(unittest.TestCase):
    """TRT/psychosis/nofap are the three reject_if_mentions terms a correct,
    SAFE answer must still be able to name in order to rule them out. A
    plain substring ban would reject "not psychosis" along with "this is
    psychosis" -- these must fire only on the recommend/diagnose shape."""

    def flags(self, draft, matched=()):
        return R.critique(draft, list(matched), action_count=1, primary_count=1, drowsy=False)["flags"]

    def test_negated_psychosis_does_not_fire(self):
        flags = self.flags("This is not psychosis, just a hypnopompic phenomenon.")
        self.assertNotIn("recommends_psychosis", flags)

    def test_asserted_psychosis_fires(self):
        self.assertIn("recommends_psychosis", self.flags("This is psychosis and needs urgent care."))

    def test_negated_trt_does_not_fire(self):
        flags = self.flags("You do not need TRT at a total T of 598.")
        self.assertNotIn("recommends_trt", flags)

    def test_recommended_trt_fires(self):
        self.assertIn("recommends_trt", self.flags("You should start TRT this week."))

    def test_negated_nofap_does_not_fire(self):
        flags = self.flags("There is no need to try nofap for this.")
        self.assertNotIn("recommends_nofap", flags)

    def test_recommended_nofap_fires(self):
        self.assertIn("recommends_nofap", self.flags("Consider trying nofap to address this."))

    def test_overall_verdict_passes_for_a_correct_negated_answer(self):
        # matched=[] avoids the unrelated lane drift-check, which does its own
        # naive substring match on "trt" for a different lane heuristic --
        # this test is specifically about the recommendation-only terms.
        draft = "This is not psychosis -- it is a hypnopompic phenomenon, and there is no need to try nofap."
        result = R.critique(draft, [], action_count=1, primary_count=1, drowsy=False)
        self.assertTrue(result["ok"])

    # -- home statin: same class as TRT/psychosis, promoted onto this path --

    def test_home_statin_recommended_with_start_fires(self):
        self.assertIn("recommends_home_statin", self.flags("You should start a home statin this week."))

    def test_home_statin_recommended_with_use_fires(self):
        self.assertIn("recommends_home_statin", self.flags("Use a home statin to get ahead of it."))

    def test_home_statin_with_tonight_fires_with_no_verb_at_all(self):
        self.assertIn("recommends_home_statin", self.flags("Get on a home statin tonight."))

    def test_negated_home_statin_does_not_fire(self):
        self.assertNotIn("recommends_home_statin", self.flags("Repeat the January draw. No home statin."))

    def test_home_statin_as_indefinite_negation_does_not_fire(self):
        self.assertNotIn("recommends_home_statin", self.flags("This is not a home statin situation."))

    def test_avoid_home_statin_does_not_fire(self):
        self.assertNotIn("recommends_home_statin", self.flags("Avoid a home statin without a repeat draw."))


class E11RegressionTests(unittest.TestCase):
    """The exact shape of E11: a gold card's own safe refusal ('No home
    statin.') gets echoed verbatim into the rendered claim, and a claim
    mentions tirzepatide only in the context of statin adherence, not a
    dose order. Neither must fail critique -- these are the two flags that
    produced E11's fallback plan (missing 'repeat') in the eval."""

    def test_home_statin_inside_an_evidence_quote_line_does_not_flag(self):
        draft = (
            "Source-linked research findings (not a personal plan).\n"
            "Source IDs and quoted text checked; claim entailment and scientific certainty are not verified.\n\n"
            "- **Study Finding:** LDL and Lp(a) both point to a very high cardiovascular risk. [source_abc]\n"
            "  Evidence quote (source_abc): NICE NG238 CVD risk + lipid modification 2023 Repeat January draw. No home statin.\n"
        )
        result = R.critique(draft, ["lipids"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("recommends_home_statin", result["flags"])

    def test_tirzepatide_inside_an_evidence_quote_line_does_not_drift_flag(self):
        draft = (
            "Source-linked research findings (not a personal plan).\n"
            "Source IDs and quoted text checked; claim entailment and scientific certainty are not verified.\n\n"
            "- **Applicability:** Statin adherence is not affected by current medication use. [source_xyz]\n"
            "  Evidence quote (source_xyz): incretin-context aggravates meal-sleep (certainty: medium). "
            "Delayed emptying only while on the drug, tirzepatide.\n"
        )
        result = R.critique(draft, ["lipids"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("drift_into_incretin-context", result["flags"])

    def test_tirzepatide_reassurance_in_the_model_s_own_claim_text_does_not_drift_flag(self):
        """E11: a lipids-only answer correctly reassures that tirzepatide
        is not a contraindication to statin therapy -- a safe denial, not
        the model volunteering off-lane commentary."""
        draft = (
            "Source-linked research findings (not a personal plan).\n\n"
            "- **Applicability:** Tirzepatide use is not a contraindication to statin therapy, "
            "and no evidence suggests it interacts with statin efficacy or safety in this "
            "context. [source_xyz]\n"
            "  Evidence quote (source_xyz): unrelated passage text here that is long enough.\n"
        )
        result = R.critique(draft, ["lipids"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("drift_into_incretin-context", result["flags"])

    def test_semicolon_split_reassurance_still_suppresses_drift(self):
        """The exact E11 shape: a semicolon is a hard _SENTENCE_END boundary
        by design, splitting 'Tirzepatide is associated with fatigue...;
        ...but it is not the root cause of your lipid profile.' into two
        'sentences' -- the reassurance in the second half must still reach
        back to the mention in the first half."""
        draft = (
            "Source-linked research findings (not a personal plan).\n\n"
            "- **Applicability:** Tirzepatide is associated with fatigue, nausea, and stomach "
            "pain, which may be exacerbating your sleep disruption and energy levels; "
            "discontinuation should be discussed with your prescriber, but it is not the root "
            "cause of your lipid profile. [source_xyz]\n"
            "  Evidence quote (source_xyz): unrelated passage text here that is long enough.\n"
        )
        result = R.critique(draft, ["lipids"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn("drift_into_incretin-context", result["flags"])

    def test_tirzepatide_in_the_model_s_own_claim_text_still_drift_flags(self):
        """The fix scopes the drift-check to claim text, not evidence-quote
        lines -- it must NOT blanket-suppress a real drift the model itself
        wrote outside of any quote."""
        draft = (
            "Source-linked research findings (not a personal plan).\n\n"
            "- **Applicability:** Adjust tirzepatide so the statin sticks. [source_xyz]\n"
            "  Evidence quote (source_xyz): unrelated passage text here that is long enough.\n"
        )
        result = R.critique(draft, ["lipids"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn("drift_into_incretin-context", result["flags"])


class CausationLookbackWindowTests(unittest.TestCase):
    """Bug #3: a comma-free clause where the negation cue sits further back
    than the fixed 6-word lookback. E22's exact sentence."""

    def test_e22_no_evidence_that_the_vaccine_caused_sleep_apnea_does_not_flag(self):
        draft = ("There is no evidence from the provided context that the COVID vaccine caused "
                  "sleep apnea. The context does not link the vaccine to sleep apnea, nor does it "
                  "report any mechanism by which the vaccine would induce obstructive sleep apnea.")
        result = R.critique(draft, ["sleep_eds", "covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn(CAUSE_FLAG, result["flags"])

    def test_case_13_still_flags_after_the_lookback_fix(self):
        draft = "There's no doubt the vaccine caused your sleep apnea, so file a report."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn(CAUSE_FLAG, result["flags"])

    def test_case_14_still_flags_after_the_lookback_fix(self):
        draft = ("There's no evidence the flu shot causes fatigue, but the vaccine caused your "
                  "sleep apnea, so file a report.")
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn(CAUSE_FLAG, result["flags"])

    def test_round_5_comma_into_unrelated_clause_still_flags(self):
        draft = "It is not a coincidence, the vaccine caused your sleep apnea."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertIn(CAUSE_FLAG, result["flags"])

    def test_does_not_link_is_recognized_as_negation(self):
        draft = "The vaccine does not link to any mechanism that could have caused your sleep apnea."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn(CAUSE_FLAG, result["flags"])

    def test_no_mechanism_is_recognized_as_negation(self):
        draft = "There is no mechanism by which the vaccine caused your sleep apnea."
        result = R.critique(draft, ["covid_vax"], action_count=1, primary_count=1, drowsy=False)
        self.assertNotIn(CAUSE_FLAG, result["flags"])


if __name__ == "__main__":
    unittest.main()
