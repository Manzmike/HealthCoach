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
    def __init__(self, rows, fallback=None):
        self.rows = rows
        self.fallback = fallback if fallback is not None else rows
        self.broad = False

    def search(self, *args, **kwargs):
        self.broad = False
        return self

    def vector(self, *args):
        return self

    def text(self, *args):
        return self

    def where(self, where, **kwargs):
        self.broad = where.startswith("1=1")
        return self

    def limit(self, *args):
        return self

    def to_list(self):
        return copy.deepcopy(self.fallback if self.broad else self.rows)


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

    def test_source_ids_are_stable_and_changed_excerpts_cannot_reuse_citations(self):
        self.assertEqual(EC.source_id(hit()), EC.source_id(copy.deepcopy(hit())))
        with self.assertRaises(ValueError):
            EC.validate_claims(json.dumps(self.claims()), [hit("Creatine had a different result in this excerpt.")])

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
