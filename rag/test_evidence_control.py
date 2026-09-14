"""Offline regression tests. No local papers, private state, models, or network required."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import coach
import evidence_control as EC
import supplement_audit as audit


def hit(text="Creatine improved strength in the studied adults.", **changes):
    return {"text": text, "source_pdf": "study.pdf", "doi": "10.1/study", "grade": "B",
            "cohort": "general", "folder": "07_supplements/creatine",
            "retrieval": {"accepted": True, "topic_passed": True, "reranker_score": 2.0, "minimum_score": 0.0}, **changes}


class Reranker:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = []

    def predict(self, pairs, *, activation_fn):
        self.pairs = pairs
        return activation_fn(self.scores)


class Table:
    def __init__(self, rows, fallback=None, personal=None):
        self.rows = rows
        self.fallback = fallback if fallback is not None else rows
        self.personal = personal
        self.mode = "rows"

    def search(self, *args, **kwargs):
        self.mode = "rows"
        return self

    def vector(self, *args):
        return self

    def text(self, *args):
        return self

    def where(self, where, **kwargs):
        if where.startswith("1=1"):
            self.mode = "fallback"
        elif self.personal is not None and "personal = true" in where:
            self.mode = "personal"
        else:
            self.mode = "rows"
        return self

    def limit(self, *args):
        return self

    def to_list(self):
        source = {"rows": self.rows, "fallback": self.fallback, "personal": self.personal}[self.mode]
        return copy.deepcopy(source)


class EvidenceControlTests(unittest.TestCase):
    def test_relevance_and_topic_gate_are_both_required(self):
        rows = [hit(), hit("Creatine has no relevant outcome here.", doi="10.1/low"),
                hit("Unrelated paper about road surfaces.", doi="10.1/offtopic")]
        before = copy.deepcopy(rows)
        diagnostics = []
        selected = EC.select_evidence(rows, "creatine strength", Reranker([2, -1]), audit=diagnostics)
        self.assertEqual(len(selected), 1)
        self.assertEqual([d["retrieval"]["reason"] for d in diagnostics],
                         ["topic_and_relevance_passed", "below_relevance_threshold", "topic_gate_failed"])
        self.assertEqual(rows, before)
        self.assertEqual(selected[0]["retrieval"]["minimum_score"], 0)
        self.assertIsNone(selected[0]["retrieval"]["keyword_score"])

    def test_fails_closed_on_missing_failed_nonfinite_or_mismatched_scores(self):
        broken = Mock()
        broken.predict.side_effect = RuntimeError("model unavailable")
        for reranker in (None, broken, Reranker([]), Reranker([float("nan")]), Reranker([float("inf")])):
            with self.subTest(reranker=reranker):
                self.assertEqual(EC.select_evidence([hit()], "creatine", reranker), [])

    def test_threshold_boundary_and_invalid_configuration(self):
        self.assertEqual(len(EC.select_evidence([hit()], "creatine", Reranker([0]))), 1)
        with patch.dict(os.environ, {"HC_MIN_RERANK_SCORE": "3"}):
            self.assertEqual(EC.select_evidence([hit()], "creatine", Reranker([2])), [])
        for value in ("nan", "infinity", "wrong"):
            with patch.dict(os.environ, {"HC_MIN_RERANK_SCORE": value}), self.assertRaises(ValueError):
                EC.select_evidence([hit()], "creatine", Reranker([2]))

    def test_doi_urls_case_and_duplicate_passages_do_not_inflate_context(self):
        rows = [hit(f"Creatine strength study finding number {i}.", doi=doi, source_pdf=f"copy{i}.pdf")
                for i, doi in enumerate(("10.1/Study", "https://doi.org/10.1/study", "DOI:10.1/STUDY", "10.1/independent"))]
        chosen = EC.select_evidence(rows, "creatine strength", Reranker([4, 3, 2, 1]))
        self.assertEqual(len(chosen), 3)
        self.assertEqual(chosen[-1]["doi"], "10.1/independent")
        duplicates = [hit(), hit(source_pdf="copy.pdf", doi="10.1/alias")]
        self.assertEqual(len(EC.select_evidence(duplicates, "creatine", Reranker([2, 2]))), 1)

    def test_hardlinks_without_doi_share_the_same_paper_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.pdf"
            first.touch()
            second = Path(directory) / "b.pdf"
            os.link(first, second)
            rows = [hit(f"Creatine finding {i} in the same underlying paper.", doi="", source_pdf=str(first if i < 2 else second)) for i in range(3)]
            self.assertEqual(len(EC.select_evidence(rows, "creatine", Reranker([3, 2, 1]))), 2)

    def test_boost_fn_changes_final_ranking_order(self):
        low_raw_but_boosted = hit(text="Personal note about sleep.", source_pdf="gold.pdf",
                                   doi="", grade="A", **{"personal": True})
        high_raw_not_boosted = hit(text="Unrelated high-scoring passage.", source_pdf="other.pdf",
                                    doi="10.1/other", grade="C", **{"personal": False})
        reranker = Reranker([1.0, 5.0])  # high_raw_not_boosted would win on raw score alone
        accepted = EC.select_evidence(
            [low_raw_but_boosted, high_raw_not_boosted], "sleep", reranker, k=2,
            topic_gate=lambda h: True,
            boost_fn=lambda h: 10.0 if h.get("personal") else 1.0,
        )
        self.assertEqual(accepted[0]["source_pdf"], "gold.pdf")

    def test_boost_fn_defaults_to_no_op(self):
        a = hit(text="passage one here", source_pdf="a.pdf", doi="10.1/a")
        b = hit(text="passage two here", source_pdf="b.pdf", doi="10.1/b")
        reranker = Reranker([1.0, 2.0])
        accepted = EC.select_evidence([a, b], "x", reranker, k=2, topic_gate=lambda h: True)
        self.assertEqual(accepted[0]["source_pdf"], "b.pdf")  # unchanged behavior: raw score order

    def test_max_per_subfolder_caps_even_across_different_papers(self):
        rows = [
            hit(text=f"passage {i}", source_pdf=f"p{i}.pdf", doi=f"10.1/{i}", folder="01_x/y")
            for i in range(5)
        ]
        reranker = Reranker([5.0, 4.0, 3.0, 2.0, 1.0])
        accepted = EC.select_evidence(rows, "x", reranker, k=10, topic_gate=lambda h: True)
        self.assertLessEqual(len(accepted), EC.MAX_PER_SUBFOLDER)

    def test_identifiers_and_scored_passage_match_the_generation_context(self):
        self.assertFalse(EC.topic_matches("PP405 hair research", hit("JXL069 hair research only.")))
        self.assertFalse(EC.topic_matches("uridine monophosphate cognition attention", hit("Cognition and attention improved with another intervention.")))
        self.assertFalse(EC.topic_matches("how does zinc affect testosterone", hit("Testosterone changed in a fenugreek trial.")))
        row = hit("Creatine " + "x" * 2500)
        rr = Reranker([2])
        EC.select_evidence([row], "creatine", rr)
        self.assertEqual(rr.pairs[0][1], EC.passage(row))
        self.assertIn(rr.pairs[0][1], EC.claim_context([row]))

    def claims(self, row=None):
        row = row or hit()
        return {"claims": [{"claim": "Strength improved in the study.", "claim_type": "study_finding",
                            "sources": [{"source_id": EC.source_id(row), "quote": row["text"]}]}]}

    def test_claim_records_require_real_ids_and_verbatim_quotes(self):
        records = EC.validate_claims(json.dumps(self.claims()), [hit()])
        self.assertEqual(records[0]["source_ids"], [EC.source_id(hit())])
        self.assertEqual(records[0]["certainty"], "not_assessed")
        self.assertEqual(records[0]["entailment"], "not_verified")
        self.assertIn("not a personal plan", EC.render_claims(records))
        for source in ({"source_id": "invented", "quote": hit()["text"]},
                       {"source_id": EC.source_id(hit()), "quote": "A fabricated quote not found in the actual passage."},
                       {"source_id": EC.source_id(hit()), "quote": "Creatine"}):
            data = self.claims()
            data["claims"][0]["sources"] = [source]
            with self.assertRaises(ValueError):
                EC.validate_claims(json.dumps(data), [hit()])

    def test_unsourced_personal_actions_and_partial_json_are_withheld(self):
        for change in ({"sources": []}, {"claim_type": "practical_action"}, {"claim": ""}, {"claim_type": []},
                       {"claim": "You should inject the compound every day."}, {"claim": "Stop your medication."}):
            data = self.claims()
            data["claims"][0].update(change)
            with self.assertRaises(ValueError):
                EC.validate_claims(json.dumps(data), [hit()])
        for text in ("Here is my answer", '{"claims": [', '[]', '{"claims": {}, "extra": 1}'):
            with self.assertRaises(ValueError):
                EC.validate_claims(text, [hit()])
        self.assertEqual(EC.render_claims(EC.validate_claims('{"claims": []}', [hit()])), EC.NO_EVIDENCE)

    def test_spliced_quote_skipping_real_content_is_rejected(self):
        row = hit("Title clinical line one.\nSource: Some Reference.\nMiddle clinical detail line here.\n"
                   "Body sentence with enough length to finish the point.")
        data = self.claims(row)
        data["claims"][0]["sources"][0]["quote"] = ("Title clinical line one. "
                                                      "Body sentence with enough length to finish the point.")
        with self.assertRaises(ValueError):
            EC.validate_claims(json.dumps(data), [row])

    def test_body_only_quote_passes_once_the_source_locator_line_is_stripped(self):
        row = hit("Title clinical line one.\nSource: Some Reference.\n"
                   "Body sentence with enough length to finish the point of the finding.")
        data = self.claims(row)
        data["claims"][0]["sources"][0]["quote"] = "Body sentence with enough length to finish the point of the finding."
        records = EC.validate_claims(json.dumps(data), [row])
        self.assertEqual(len(records), 1)

    def test_batch_drops_only_the_illegal_spliced_claim(self):
        row = hit("Title clinical line one.\nSource: Some Reference.\nMiddle clinical detail line here.\n"
                   "Body sentence with enough length to finish the point.")

        def good(i):
            return {"claim": f"Finding number {i} restates the body detail.", "claim_type": "study_finding",
                     "sources": [{"source_id": EC.source_id(row),
                                  "quote": "Body sentence with enough length to finish the point."}]}

        bad = {"claim": "An illegally spliced finding that should be dropped.", "claim_type": "study_finding",
               "sources": [{"source_id": EC.source_id(row),
                            "quote": "Title clinical line one. Body sentence with enough length to finish the point."}]}
        data = {"claims": [good(i) for i in range(5)] + [bad]}
        records = EC.validate_claims(json.dumps(data), [row])
        self.assertEqual(len(records), 5)
        self.assertTrue(all("illegally spliced" not in r["claim"] for r in records))

    def test_normalize_source_id_recovers_a_bare_hex_id_missing_its_prefix(self):
        row = hit()
        real_id = EC.source_id(row)
        bare_hex = real_id.removeprefix("source_")
        self.assertEqual(EC.normalize_source_id(bare_hex, {real_id: row}), real_id)

    def test_normalize_source_id_returns_none_for_unknown_hex(self):
        row = hit()
        self.assertIsNone(EC.normalize_source_id("0000000000000000", {EC.source_id(row): row}))

    def test_bare_hex_source_id_is_normalized_in_a_full_claim(self):
        row = hit()
        real_id = EC.source_id(row)
        data = self.claims(row)
        data["claims"][0]["sources"][0]["source_id"] = real_id.removeprefix("source_")
        records = EC.validate_claims(json.dumps(data), [row])
        self.assertEqual(records[0]["source_ids"], [real_id])

    def test_bracketed_header_source_id_is_normalized_to_the_bare_id(self):
        row = hit()
        data = self.claims(row)
        data["claims"][0]["sources"][0]["source_id"] = f"[{EC.source_id(row)} | grade=B | doi=no-doi]"
        records = EC.validate_claims(json.dumps(data), [row])
        self.assertEqual(records[0]["source_ids"], [EC.source_id(row)])

    def test_ambiguous_bracketed_source_id_naming_two_real_ids_is_rejected(self):
        row_a = hit()
        row_b = hit("Creatine also improved endurance in the same cohort.", doi="10.1/other")
        data = self.claims(row_a)
        data["claims"][0]["sources"][0]["source_id"] = f"[{EC.source_id(row_a)} | {EC.source_id(row_b)}]"
        with self.assertRaises(ValueError):
            EC.validate_claims(json.dumps(data), [row_a, row_b])

    def test_drowsy_drive_line_is_appended_for_sleep_eds_even_without_the_word_drive(self):
        row = hit()
        payload = {"claims": [{"claim": "Witnessed pauses point to OSA.", "claim_type": "study_finding",
                                "sources": [{"source_id": EC.source_id(row), "quote": row["text"]}]}]}
        generate = Mock(return_value=json.dumps(payload))
        with patch.dict(sys.modules, {"mlx_lm": SimpleNamespace(generate=generate)}):
            answer = coach.answer_from_hits(None, None, "Fix my apnea with the RAG only.", [row],
                                             matched_intents=["sleep_eds"])
        self.assertIn("do not drive", answer.lower())

    def test_prescriber_line_is_appended_when_lead_intent_is_incretin(self):
        row = hit()
        payload = {"claims": [{"claim": "Stopping tirzepatide may cause rebound hunger.", "claim_type": "study_use",
                                "sources": [{"source_id": EC.source_id(row), "quote": row["text"]}]}]}
        generate = Mock(return_value=json.dumps(payload))
        with patch.dict(sys.modules, {"mlx_lm": SimpleNamespace(generate=generate)}):
            answer = coach.answer_from_hits(None, None, "Tirzepatide makes me nauseous.", [row],
                                             matched_intents=["incretin"])
        self.assertIn("prescriber", answer.lower())

    def test_no_vocabulary_backstop_line_is_appended_for_an_unrelated_intent(self):
        """Only the two standing safety requirements (drowsy-drive,
        prescriber) may ever be appended. An answer whose intent triggers
        neither must come back exactly as render_claims() produced it -- no
        mechanically-appended sentence supplying a word the model itself did
        not write."""
        row = hit()
        claim = "Adding afternoon caffeine is not recommended; your current cutoff is already fine."
        payload = {"claims": [{"claim": claim, "claim_type": "study_use",
                                "sources": [{"source_id": EC.source_id(row), "quote": row["text"]}]}]}
        generate = Mock(return_value=json.dumps(payload))
        with patch.dict(sys.modules, {"mlx_lm": SimpleNamespace(generate=generate)}):
            answer = coach.answer_from_hits(None, None, "Should I add an afternoon coffee.", [row],
                                             matched_intents=["lifestyle_night"])
        self.assertTrue(answer.endswith(claim + f" [{EC.source_id(row)}]\n"
                                        f"  Evidence quote ({EC.source_id(row)}): {row['text']}"))

    def test_required_lines_are_not_appended_to_a_withheld_or_no_evidence_answer(self):
        row = hit()
        generate = Mock(return_value="not json")
        with patch.dict(sys.modules, {"mlx_lm": SimpleNamespace(generate=generate)}):
            withheld = coach.answer_from_hits(None, None, "Even off tirzepatide I still wake at 2.", [row],
                                               matched_intents=["sleep_eds", "incretin"])
        self.assertIn("withheld", withheld)
        self.assertNotIn("do not drive", withheld.lower())
        self.assertNotIn("prescriber", withheld.lower())

    def test_source_ids_are_stable_and_changed_excerpts_cannot_reuse_citations(self):
        self.assertEqual(EC.source_id(hit()), EC.source_id(copy.deepcopy(hit())))
        with self.assertRaises(ValueError):
            EC.validate_claims(json.dumps(self.claims()), [hit("Creatine had a different result in this excerpt.")])

    def test_search_pulls_in_a_personal_row_crowded_out_of_the_general_hybrid_pool(self):
        """A hand-curated personal gold card can rank below a wall of
        near-duplicate master-corpus chunks in the raw hybrid search and
        never reach the reranker at all -- boost_for() can't rescue a row
        that was never a candidate. search() must query personal rows
        separately and merge them in."""
        emb = Mock()
        emb.encode.return_value.tolist.return_value = [0.1]
        crowding_row = hit("Coding sessions at a desk show reduced circulation in one study.",
                            source_pdf="crowd.pdf", doi="10.1/crowd")
        gold_row = hit("Coding late means dim the lights after deep work.", source_pdf="gold.pdf",
                        doi="", grade="A", **{"personal": True})
        table = Table([crowding_row], personal=[gold_row])
        found, weak = coach.search(table, emb, "should I stop coding", reranker=Reranker([1, 5]))
        self.assertEqual({h["source_pdf"] for h in found}, {"crowd.pdf", "gold.pdf"})

    def test_search_falls_back_only_to_evidence_that_passes(self):
        emb = Mock()
        emb.encode.return_value.tolist.return_value = [0.1]
        fallback = hit(grade="C", cohort="older")
        found, weak = coach.search(Table([hit("No shared query vocabulary.")], [fallback]), emb, "creatine", reranker=Reranker([2]))
        self.assertEqual(len(found), 1)
        self.assertTrue(weak)
        self.assertEqual(coach.search(Table([hit()]), emb, "creatine", reranker=None)[0], [])

    def test_urgent_question_needs_no_model_or_database(self):
        with patch.object(sys, "argv", ["coach.py", "I have chest pain now"]), \
             patch.dict(sys.modules, {"lancedb": None, "mlx_lm": None}), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            coach.main()
        self.assertIn("URGENT SAFETY WARNING", output.getvalue())

    def test_answer_withholds_invalid_output_and_does_not_generate_on_a_gap(self):
        generate = Mock(return_value="Uncited medical advice")
        with patch.dict(sys.modules, {"mlx_lm": SimpleNamespace(generate=generate)}):
            answer = coach.answer_from_hits(None, None, "creatine", [], 500)
            self.assertEqual(answer, EC.NO_EVIDENCE)
            generate.assert_not_called()
            self.assertEqual(coach.answer_from_hits(None, None, "creatine", [hit(retrieval={})]), EC.NO_EVIDENCE)
            generate.assert_not_called()
            self.assertIn("withheld", coach.answer_from_hits(None, None, "creatine", [hit()]))
            generate.return_value = json.dumps(self.claims())
            self.assertIn(EC.source_id(hit()), coach.answer_from_hits(None, None, "creatine", [hit()]))

    def test_candidate_retrieval_uses_threshold_and_normalized_paper_count(self):
        candidate = next(c for c in audit.CATALOG if c.key == "creatine_monohydrate")
        emb = Mock()
        emb.encode.return_value.tolist.return_value = [0.1]
        rows = [hit("Creatine improved strength in human trial one.", doi="10.1/same"),
                hit("Creatine improved strength in human trial two.", doi="https://doi.org/10.1/SAME", source_pdf="copy.pdf")]
        rr = Mock()
        rr.predict.side_effect = lambda pairs, **kwargs: [2] * len(pairs)
        ev = audit.retrieve_candidate(Table(rows), emb, rr, candidate, ["strength"])
        self.assertEqual(ev.unique_papers, 1)
        self.assertEqual(ev.coverage, "WEAK")
        self.assertFalse(ev.hybrid_fallback)
        self.assertEqual(audit.retrieve_candidate(Table(rows), emb, None, candidate, ["strength"]).coverage, "NONE")

    def test_gray_card_keeps_mechanistic_research_with_no_human_coverage(self):
        candidate = next(c for c in audit.PEPTIDE_CATALOG if c.key == "bpc_157")
        ev = audit.Evidence("NONE", "C", 0, 0, "not established", [hit("BPC-157 was examined in an animal model.", grade="C")])
        with patch.object(coach, "answer_from_hits", return_value="Labelled mechanistic findings") as answer:
            card = audit.deep_card(None, None, candidate, ev, "RESEARCH ONLY", {}, 900)
        answer.assert_called_once()
        self.assertIn("Labelled mechanistic findings", card)
        self.assertIn("NONE", card)
        self.assertIn("No initiation", card)

    def test_saved_calendar_snapshot_records_existing_template_not_new_defaults(self):
        profile = {"calendar_modes": {"Tuesday": "unavailable", "Wednesday": "morning"}}
        before = copy.deepcopy(profile)
        text = audit.saved_profile_markdown(profile)
        self.assertIn('"origin": "AUTHORED_TEMPLATE"', text)
        self.assertIn("No main session", text)
        self.assertIn("CONFLICT", text)
        self.assertNotIn('"Monday"', text)
        self.assertEqual(profile, before)


if __name__ == "__main__":
    unittest.main()
