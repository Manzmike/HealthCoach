# rag/test_coach_control_layer.py
"""Router/critic/person_state wiring in coach.py. No model, no database --
pure function tests against build_where_clause and the critique-wrapping
in answer_from_hits (mocked generation)."""

import unittest
from unittest.mock import patch

import coach


class WhereClauseTests(unittest.TestCase):
    def test_zero_match_has_no_lane_restriction(self):
        clause = coach.build_where_clause([])
        self.assertNotIn("lane IN (", clause)

    def test_matched_intent_adds_lane_condition(self):
        clause = coach.build_where_clause(["lipids"])
        self.assertIn("lane IS NULL", clause)
        self.assertIn("'lipids'", clause)

    def test_deny_lanes_always_excluded(self):
        clause = coach.build_where_clause(["sleep_eds"])
        self.assertIn("deny", clause)
        self.assertIn("deny-detox", clause)

    def test_quarantine_always_excluded_matched_or_not(self):
        self.assertIn("quarantined = false", coach.build_where_clause([]))
        self.assertIn("quarantined = false", coach.build_where_clause(["sleep_eds"]))


class AnswerFromHitsCritiqueTests(unittest.TestCase):
    def _hits(self):
        return [{
            "text": "Do not drive while fighting sleep. Move dinner earlier.",
            "doi": "10.1/x", "grade": "A", "source_pdf": "x.pdf",
            "retrieval": {"accepted": True, "topic_passed": True},
        }]

    def _claim_record(self, claim_text: str) -> list[dict]:
        # Matches what EC.validate_claims actually returns (see evidence_control.py:197-199):
        # the original item's `claim`/`claim_type`/`sources` plus derived `source_ids`.
        return [{
            "claim": claim_text, "claim_type": "study_use",
            "sources": [{"source_id": "source_x", "quote": "a long enough quoted passage here"}],
            "source_ids": ["source_x"], "study_design_metadata": ["A"],
            "certainty": "not_assessed", "entailment": "not_verified",
        }]

    def test_failing_draft_returns_fallback_text_not_the_draft(self):
        """The *rendered claim text* is what critique() inspects, not the raw
        model output -- so the mock must make render_claims() actually
        produce reject-listed content, or critique() has nothing to catch."""
        with patch("coach.SP.urgent_message", return_value=None), \
             patch("coach.EC.validate_claims", return_value=self._claim_record("Start TRT now.")), \
             patch("mlx_lm.generate", return_value='{"claims": []}'):
            result = coach.answer_from_hits(
                model=object(), tok=object(), question="q", hits=self._hits(),
                matched_intents=[], action_count=1, primary_count=1, drowsy=False,
            )
        self.assertIn("prescriber", result.lower())  # the fallback_plan mentions the prescriber
        self.assertNotIn("start trt now", result.lower())

    def test_passing_draft_is_returned_unchanged(self):
        with patch("coach.SP.urgent_message", return_value=None), \
             patch("coach.EC.validate_claims", return_value=self._claim_record("Move dinner earlier.")), \
             patch("mlx_lm.generate", return_value='{"claims": []}'):
            result = coach.answer_from_hits(
                model=object(), tok=object(), question="q", hits=self._hits(),
                matched_intents=[], action_count=1, primary_count=1, drowsy=False,
            )
        self.assertIn("move dinner earlier", result.lower())


if __name__ == "__main__":
    unittest.main()
