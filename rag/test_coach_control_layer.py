# rag/test_coach_control_layer.py
"""Router/critic/person_state wiring in coach.py. No model -- pure function
tests against build_where_clause and the critique-wrapping in
answer_from_hits (mocked generation), plus one semantic WHERE-clause test
that runs the real clause through a real throwaway LanceDB fixture."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

import coach
import evidence_control as EC


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


class WhereClauseSemanticsTests(unittest.TestCase):
    """M4. A substring assertion on the clause TEXT cannot catch a SQL
    three-valued-logic bug: `NULL NOT IN ('deny','deny-detox')` evaluates to
    NULL, which the engine treats as not-true, so a bare `lane NOT IN (...)`
    silently drops every `lane IS NULL` row -- 138,976 of the real corpus's
    147,631. Run the real clause through the real query engine against a
    small fixture instead, and assert on which rows actually survive."""

    ROWS = [
        {"rid": "unmapped", "lane": None, "grade": "A", "quarantined": False, "allow_c": False},
        {"rid": "deny", "lane": "deny", "grade": "A", "quarantined": False, "allow_c": False},
        {"rid": "deny_detox", "lane": "deny-detox", "grade": "A", "quarantined": False, "allow_c": False},
        {"rid": "mapped", "lane": "sleep_eds", "grade": "A", "quarantined": False, "allow_c": False},
        {"rid": "unmapped_quarantined", "lane": None, "grade": "A", "quarantined": True, "allow_c": False},
    ]

    def surviving(self, clause):
        try:
            import lancedb
            import pyarrow as pa
        except ImportError as exc:  # pragma: no cover - environment without the DB stack
            self.skipTest(f"lancedb/pyarrow unavailable: {exc}")
        schema = pa.schema([
            pa.field("rid", pa.string()),
            pa.field("lane", pa.string(), nullable=True),
            pa.field("grade", pa.string()),
            pa.field("quarantined", pa.bool_()),
            pa.field("allow_c", pa.bool_()),
        ])
        with tempfile.TemporaryDirectory() as directory:
            table = lancedb.connect(directory).create_table(
                "chunks", data=pa.Table.from_pylist(self.ROWS, schema=schema))
            rows = table.search().where(clause).limit(len(self.ROWS)).to_list()
        return {row["rid"] for row in rows}

    def test_lane_is_null_rows_survive_the_unrestricted_clause(self):
        survivors = self.surviving(coach.build_where_clause([]))
        self.assertIn("unmapped", survivors)
        self.assertEqual(survivors, {"unmapped", "mapped"})

    def test_lane_is_null_rows_survive_a_lane_restricted_clause(self):
        survivors = self.surviving(coach.build_where_clause(["sleep_eds"]))
        self.assertIn("unmapped", survivors)
        self.assertNotIn("deny", survivors)
        self.assertNotIn("unmapped_quarantined", survivors)

    def test_a_lane_restriction_still_excludes_other_mapped_lanes(self):
        survivors = self.surviving(coach.build_where_clause(["lipids"]))
        self.assertEqual(survivors, {"unmapped"})


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

    def test_contradictory_schedule_reaches_safe_fallback(self):
        record = self._claim_record(
            "You can resume a 5-day lifting schedule this week, starting with 2–3 days."
        )
        record[0]["sources"][0]["quote"] = "Nausea week: breaks not a 5-day program."
        with patch("coach.SP.urgent_message", return_value=None), \
             patch("coach.EC.validate_claims", return_value=record), \
             patch("mlx_lm.generate", return_value="output"):
            result = coach.answer_from_hits(
                model=object(), tok=object(), question="Get me back on 5 days lifting this week.",
                hits=self._hits(), matched_intents=["cut_train"], action_count=1,
                primary_count=1, drowsy=False,
            )
        self.assertNotIn("5-day lifting schedule", result.lower())
        self.assertIn("gut", result.lower())

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


class ForTerminalTests(unittest.TestCase):
    """render_claims() emits **bold** because its output is also embedded
    verbatim into generated Markdown reports, where that syntax is correct.
    _for_terminal() is coach.py CLI's own presentation step, applied only to
    what gets printed to a human's terminal -- report generation never calls
    it, so Markdown files keep the real asterisks they need."""

    def test_interactive_terminal_gets_real_ansi_bold(self):
        with patch("sys.stdout.isatty", return_value=True):
            rendered = coach._for_terminal("- **Uncertainty:** no evidence found.")
        self.assertEqual(rendered, "- \033[1mUncertainty:\033[0m no evidence found.")

    def test_piped_output_gets_plain_text_not_raw_asterisks_or_escape_codes(self):
        with patch("sys.stdout.isatty", return_value=False):
            rendered = coach._for_terminal("- **Uncertainty:** no evidence found.")
        self.assertEqual(rendered, "- Uncertainty: no evidence found.")
        self.assertNotIn("*", rendered)
        self.assertNotIn("\033", rendered)

    def test_text_with_no_bold_markup_is_unchanged(self):
        with patch("sys.stdout.isatty", return_value=True):
            self.assertEqual(coach._for_terminal("plain text"), "plain text")


class AnswerQuestionTests(unittest.TestCase):
    """answer_question() is the CLI-independent core of main()'s retrieve/
    answer loop -- the web GUI's /ask route calls it directly. No real
    model, database, or network: get_stack/load_model are injected fakes,
    and search()/answer_from_hits()/RC.classify() are mocked."""

    def _stack(self):
        return object(), object(), object()

    def test_single_topic_question_with_evidence_returns_one_result(self):
        hit = {"retrieval": {"accepted": True, "topic_passed": True}, "grade": "A"}
        with patch.object(coach, "search", return_value=([hit], False)) as mock_search, \
             patch.object(coach, "answer_from_hits", return_value="**Answer:** do X.") as mock_answer, \
             patch.object(coach.RC, "classify", return_value=["cut_train"]):
            results = coach.answer_question(
                "Does creatine cause hair loss?", get_stack=self._stack,
                load_model=lambda: (object(), object()),
            )
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["no_evidence"])
        self.assertEqual(results[0]["answer"], "**Answer:** do X.")
        mock_search.assert_called_once()
        mock_answer.assert_called_once()

    def test_no_evidence_returns_no_evidence_result_and_never_loads_the_model(self):
        load_model = MagicMock()
        with patch.object(coach, "search", return_value=([], False)), \
             patch.object(coach.RC, "classify", return_value=[]):
            results = coach.answer_question(
                "an unanswerable question", get_stack=self._stack, load_model=load_model,
            )
        self.assertTrue(results[0]["no_evidence"])
        self.assertEqual(results[0]["answer"], EC.NO_EVIDENCE)
        load_model.assert_not_called()

    def test_multi_topic_question_gets_one_result_per_group_and_stack_loaded_once(self):
        hit = {"retrieval": {"accepted": True, "topic_passed": True}, "grade": "A"}
        get_stack = MagicMock(side_effect=self._stack)
        with patch.object(coach, "search", return_value=([hit], False)), \
             patch.object(coach, "answer_from_hits", return_value="answer"), \
             patch.object(coach.RC, "classify", return_value=[]):
            results = coach.answer_question(
                "What should my gym routine look like? What foods should I eat?",
                get_stack=get_stack, load_model=lambda: (object(), object()),
            )
        self.assertEqual(len(results), 2)
        self.assertEqual({r["topic"] for r in results}, {"schedule", "food"})
        get_stack.assert_called_once()

    def test_schedule_shaped_answer_includes_a_schedule_block_when_a_schedule_is_saved(self):
        hit = {"retrieval": {"accepted": True, "topic_passed": True}, "grade": "A"}
        with patch.object(coach, "has_saved_schedule", return_value=True), \
             patch.object(coach, "real_schedule_block", return_value="YOUR SAVED SCHEDULE:\n\nreal table"), \
             patch.object(coach, "search", return_value=([hit], False)), \
             patch.object(coach, "answer_from_hits", return_value="- **X:** y [z]"), \
             patch.object(coach.RC, "classify", return_value=[]):
            results = coach.answer_question(
                "What should my gym routine look like?", get_stack=self._stack,
                load_model=lambda: (object(), object()),
            )
        self.assertIn("real table", results[0]["schedule_block"])


if __name__ == "__main__":
    unittest.main()
