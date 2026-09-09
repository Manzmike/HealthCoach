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

    def test_retry_note_is_incorporated_into_the_system_message_not_appended_raw(self):
        captured_calls = []

        def fake_apply_chat_template(messages, **kwargs):
            captured_calls.append(messages)
            return "PROMPT"

        fake_tok = type("FakeTok", (), {
            "chat_template": "x",
            "apply_chat_template": staticmethod(fake_apply_chat_template),
        })()

        # side_effect forces the FIRST draft to be reject-listed content ("Start TRT
        # now." -- caught by critic.json's reject_if_mentions: "TRT") so critique()
        # actually rejects it and triggers a second _generate_and_render() call with
        # the retry note; the SECOND draft is clean so the retry succeeds. This
        # exercises the real path (critique() rejecting a draft), which is what
        # actually drives a second apply_chat_template call in production -- a bare
        # validate_claims exception is caught by _generate_and_render()'s except
        # clause and returns a withheld-message string that passes critique() with
        # no flags, so it would never reach the retry branch at all.
        with patch("coach.SP.urgent_message", return_value=None), \
             patch("coach.EC.validate_claims",
                   side_effect=[self._claim_record("Start TRT now."), self._claim_record("Move dinner earlier.")]), \
             patch("mlx_lm.generate", return_value="output"):
            coach.answer_from_hits(
                model=object(), tok=fake_tok, question="q", hits=self._hits(),
                matched_intents=[], action_count=1, primary_count=1, drowsy=False,
            )

        self.assertEqual(len(captured_calls), 2)
        first_system = captured_calls[0][0]["content"]
        second_system = captured_calls[1][0]["content"]
        self.assertNotIn("rejected for", first_system)
        self.assertIn("rejected for", second_system)


if __name__ == "__main__":
    unittest.main()
