from __future__ import annotations

import copy
import sys
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import candidate_ledger as CL
import candidate_manager as manager
import safety_policy as SP
import supplement_audit as audit
import symptom_checkin as symptoms
import weekly_food_plan as food_plan
import test_candidate_ledger as fixtures


def row_for(name="creatine_monohydrate", **changes):
    candidate = next((c for c in (*audit.CATALOG, *audit.PEPTIDE_CATALOG) if c.key == name), None)
    return CL.normalize_row({
        "id": name, "display_name": candidate.name if candidate else name,
        "class": audit.default_ledger_class(candidate) if candidate else "supplement",
        "consideration_scope": "personal_candidate", "reasons": ["strength"],
        "burden": "acceptable", **changes,
    })


def ledger_for(*rows):
    return CL.normalize_ledger({"schema_version": 2, "intake": fixtures.intake(), "candidates": list(rows)})


class SafetyPolicyTests(unittest.TestCase):
    def test_gate_is_pure_and_research_always_remains_available(self):
        row = row_for("bpc_157", user_decision="adopt", use_status="in_use", user_dose="recorded dose")
        before = copy.deepcopy(row)
        gate = SP.candidate_gate(row)
        self.assertFalse(gate["active_plan_allowed"])
        self.assertTrue(gate["research_allowed"])
        self.assertEqual(row, before)
        self.assertTrue(SP.candidate_gate(row_for())["active_plan_allowed"])

    def test_every_experimental_catalog_alias_is_restricted_even_relabelled(self):
        for candidate in audit.PEPTIDE_CATALOG:
            for identity in (candidate.key, candidate.name, *candidate.aliases):
                with self.subTest(identity=identity):
                    row = row_for("renamed", display_name=identity.upper(), **{"class": "food"})
                    self.assertFalse(SP.candidate_gate(row)["active_plan_allowed"])
                    row["display_name"] = "Innocent label"
                    row["aliases"] = [identity]
                    self.assertFalse(SP.candidate_gate(row)["active_plan_allowed"])

    def test_catalog_policy_and_gate_cannot_be_cleared_by_decision(self):
        for policy, gate_text in (("CLINICIAN-ONLY", ""), ("SKIP", ""), ("KEEP-PRESCRIPTION", ""),
                                  ("MEDICATION-REVIEW", ""), ("", "Kidney review required")):
            candidate = audit.Candidate("x", "Unlisted", audit.QUEUE_LOW, (), (), (), gate_text, policy)
            row = row_for("x", user_decision="adopt", use_status="in_use", observed="helps")
            with self.subTest(policy=policy, gate=gate_text):
                self.assertFalse(SP.candidate_gate(row, candidate)["active_plan_allowed"])

    def test_explicit_user_boundaries_and_unknown_experimental(self):
        cases = (
            {"consideration_scope": "research_only_topic"},
            {"blocker": {"present": True}}, {"observed": "harms"}, {"user_decision": "reject"},
            {"class": "gray_market"}, {"class": "peptide"}, {"class": "nootropic"},
            {"folder": "08_peptides_gray/custom"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                gate = SP.candidate_gate(row_for("custom", **changes))
                self.assertFalse(gate["active_plan_allowed"])
                self.assertTrue(gate["research_allowed"])

    def test_current_state_projection_respects_cached_review_without_latching_fresh_evaluation(self):
        row = row_for(last_suggestion="CONDITIONAL")
        self.assertFalse(SP.candidate_gate(row)["active_plan_allowed"])
        self.assertTrue(SP.candidate_gate({**row, "direction": "favor"})["active_plan_allowed"])

    def test_food_allocator_excludes_research_scope_and_reported_harm(self):
        rows = [row_for("test_food", **{"class": "food"}, consideration_scope="research_only_topic"),
                row_for("other_food", **{"class": "food"}, observed="harms")]
        with patch.object(food_plan, "_load_nutrition", return_value={}), \
             patch.object(food_plan, "_load_food_evidence", return_value={}), \
             patch.object(food_plan, "weekly_targets", return_value={"weekly_kcal": None, "weekly_protein_g": None}), \
             patch.object(food_plan, "_food_macros") as macros:
            food_plan.plan_week(rows, {})
        macros.assert_not_called()

    def test_alias_resolution_preserves_row_id_and_user_class(self):
        row = row_for("private_custom_id", display_name="GVS-111", **{"class": "food"})
        before = copy.deepcopy(row)
        candidate, built_in = audit.candidate_from_ledger_row(row)
        self.assertTrue(built_in)
        self.assertEqual(candidate.key, row["id"])
        self.assertIn("NO PERSONAL PROTOCOL", candidate.policy)
        self.assertFalse(audit.candidate_plan_gate(row)["active_plan_allowed"])
        self.assertEqual(row, before)

    def test_strong_gray_research_kept_without_routine_action(self):
        row = row_for("bpc_157", reasons=["joint_pain"])
        candidate, _ = audit.candidate_from_ledger_row(row)
        evidence = fixtures.two_sources("Participants significantly improved joint pain.")
        evaluations = audit.evaluate_ledger_rows([row], {row["id"]: candidate}, {row["id"]: evidence}, {}, fixtures.intake(goals=("joint_pain",)))
        evaluation = evaluations[row["id"]]
        self.assertEqual(evaluation["coverage"], "STRONG")
        self.assertEqual(evaluation["direction"], "favor")
        self.assertNotIn(evaluation["system_suggestion"], {"ADOPT_CANDIDATE", "CONTINUE_CURRENT"})
        self.assertIn(row["display_name"], audit.candidate_cards_markdown([row], evaluations))
        rankings = audit.catalog_rankings([candidate], {candidate.key: evidence}, [row], fixtures.intake(), evaluations)
        self.assertEqual(rankings["research"][0]["id"], row["id"])
        self.assertFalse(rankings["adopt_consider"][0]["safety_gate"]["active_plan_allowed"])
        profile = {"issues": ["joints"], "selected_peptide_keys": [candidate.key]}
        selected = audit.choose_deep_candidates([candidate], {candidate.key: evidence}, profile, {candidate.key: "RESEARCH"}, 1)
        self.assertEqual(selected, [candidate])
        self.assertNotIn("adopt if", manager._triage_recommendation(row, evidence, evaluation, fixtures.intake()))

    def test_restricted_current_exposure_is_not_endorsed_or_erased(self):
        for decision in ("adopt", "reject", "undecided"):
            row = row_for("phenibut", user_decision=decision, use_status="in_use", intent="keep", user_dose="USER RECORDED AMOUNT")
            before = copy.deepcopy(row)
            overlay = audit.adopted_week_overlay([row], {row["id"]: {"system_suggestion": "CONTINUE_CURRENT"}})
            active, exposure = overlay.split("#### Reported exposures", 1)
            self.assertNotIn(row["display_name"], active)
            self.assertIn(row["display_name"], exposure)
            self.assertIn("USER RECORDED AMOUNT", exposure)
            self.assertIn("no automatic", exposure.lower())
            self.assertEqual(row, before)

    def test_research_scope_overrides_current_keep(self):
        row = row_for(use_status="in_use", intent="keep", consideration_scope="research_only_topic")
        candidate, _ = audit.candidate_from_ledger_row(row)
        evaluation = audit.evaluate_ledger_rows([row], {row["id"]: candidate}, {row["id"]: fixtures.two_sources()}, {})[row["id"]]
        self.assertEqual(evaluation["system_suggestion"], "WATCH")
        self.assertFalse(evaluation["safety_gate"]["active_plan_allowed"])

    def test_reported_harm_never_becomes_adopt_or_continue(self):
        for intent in CL.INTENTS:
            for use in CL.USE_STATUSES:
                row = row_for(intent=intent, use_status=use, observed="harms")
                candidate, _ = audit.candidate_from_ledger_row(row)
                evaluation = audit.evaluate_ledger_rows([row], {row["id"]: candidate}, {row["id"]: fixtures.two_sources()}, {})[row["id"]]
                self.assertNotIn(evaluation["system_suggestion"], {"ADOPT_CANDIDATE", "CONTINUE_CURRENT"})

    def test_whole_ledger_context_detects_conflict_without_self_conflict(self):
        row = row_for("semaglutide_do_not_stack_with_tirzepatide", reasons=["fat_loss"])
        current = row_for("tirzepatide_current_prescription", use_status="in_use", user_decision="reject")
        candidate, _ = audit.candidate_from_ledger_row(row)
        self.assertNotEqual(audit.reason_stack_fit(candidate, [dict(row, use_status="in_use")]), "conflicts_lock")
        evaluation = audit.evaluate_ledger_rows(
            [row], {row["id"]: candidate}, {row["id"]: fixtures.two_sources()}, {},
            ledger_rows=[row, current],
        )[row["id"]]
        self.assertEqual(evaluation["per_reason"]["fat_loss"]["stack_fit"], "conflicts_lock")

    def test_legacy_actions_do_not_prescribe_cessation_or_approve_prescription(self):
        for key in ("phenibut", "tirzepatide_current_prescription", "mk_677_ibutamoren"):
            candidate, _ = audit.candidate_from_ledger_row(row_for(key))
            profile = {"issues": ["strength"], "current_supplements": "", "current_supplement_keys": [], "medications": ""}
            decisions = audit.preliminary_decisions([candidate], {key: fixtures.two_sources()}, profile)
            self.assertNotIn("KEEP-PRESCRIPTION", decisions[key])
            action = audit.stack_action(candidate, fixtures.two_sources(), decisions[key], profile, True)
            self.assertIn("REPORTED USE", action)
            self.assertNotIn("REMOVE", action)

    def test_cached_symptom_positive_is_gated_by_current_facts(self):
        for changes in ({}, {"consideration_scope": "research_only_topic"}, {"user_decision": "reject"},
                        {"blocker": {"present": True}}):
            row = row_for("bpc_157", last_suggestion="ADOPT_CANDIDATE", last_coverage="STRONG", **changes)
            ledger = ledger_for(row)
            before = copy.deepcopy(ledger)
            buckets = symptoms.supplements_for_tags(("joints",), ledger)
            self.assertNotIn(row["id"], {e["key"] for e in buckets["positive"]})
            self.assertIn(row["id"], {e["key"] for e in buckets["research_review"]})
            self.assertEqual(ledger, before)
        row = row_for(last_suggestion="ADOPT_CANDIDATE", last_coverage="STRONG", consideration_scope="research_only_topic")
        buckets = symptoms.supplements_for_tags(("strength",), ledger_for(row))
        self.assertNotIn(row["id"], {e["key"] for e in buckets["positive"]})

    def test_unfavorable_goal_fit_is_not_labelled_harm(self):
        row = row_for(last_suggestion="UNFAVORABLE", last_suggestion_reason="goal match is no")
        buckets = symptoms.supplements_for_tags(("strength",), ledger_for(row))
        self.assertNotIn(row["id"], {e["key"] for e in buckets["hard_warning"]})
        self.assertIn(row["id"], {e["key"] for e in buckets["research_review"]})

    def test_symptom_exposure_and_evidence_remain_in_review_detail(self):
        row = row_for("phenibut", use_status="in_use", user_dose="USER ONLY", last_suggestion="CONTINUE_CURRENT", last_coverage="STRONG")
        buckets = symptoms.supplements_for_tags(("sleep",), ledger_for(row))
        report = {"sections": [{"symptom": "Sleep", "tags": ["sleep"], "supplements": buckets,
                                "foods": {"positive": [], "negative": [], "hard_warning": []}, "lifestyle": []}]}
        text = symptoms.render_deep(report)
        self.assertIn("USER ONLY", text)
        self.assertIn("coverage STRONG", text)
        self.assertIn("Research / review only", symptoms.render_short(report))

    def test_urgent_warning_precedes_checkin_data_loading(self):
        with patch.object(CL, "load_ledger", side_effect=AssertionError("must not read private data")):
            report = symptoms.build_report(["I have chest pain now"])
        self.assertIn("URGENT SAFETY WARNING", symptoms.render_short(report))
        self.assertIn("URGENT SAFETY WARNING", symptoms.render_deep(report))

    def test_urgent_current_terms_and_nonurgent_research(self):
        for text in ("I have chest pain now", "I can't breathe", "My tongue is swelling", "face drooping",
                     "I am vomiting blood", "I want to kill myself", "Someone is unresponsive",
                     "No chest pain, but I can't breathe"):
            with self.subTest(text=text):
                self.assertIsNotNone(SP.urgent_message(text))
        for text in ("What causes chest pain?", "No chest pain", "Without chest pain", "history of chest pain",
                     "I have a history of chest pain", "I am reading an article about chest pain", "mild fatigue"):
            with self.subTest(text=text):
                self.assertIsNone(SP.urgent_message(text))


class AdmissionCommandTests(unittest.TestCase):
    def command_context(self, ledger):
        stack = ExitStack()
        stack.enter_context(patch.object(CL, "load_ledger", side_effect=lambda *_: copy.deepcopy(ledger)))
        save = stack.enter_context(patch.object(CL, "save_ledger"))
        stack.enter_context(patch.object(manager, "console", MagicMock()))
        stack.enter_context(patch.object(manager, "_finish_batch"))
        stack.enter_context(patch.object(manager, "_lab_context_lines", return_value=[]))
        stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        stack.enter_context(patch.object(sys.stdout, "isatty", return_value=True))
        return stack, save

    def live_context(self, ledger):
        stack, save = self.command_context(ledger)
        stack.enter_context(patch.dict(sys.modules, {
            "lancedb": SimpleNamespace(connect=lambda *_: Mock()),
            "sentence_transformers": SimpleNamespace(SentenceTransformer=lambda *a, **k: Mock()),
        }))
        stack.enter_context(patch.object(audit.HC, "load_reranker", return_value=None))
        stack.enter_context(patch.object(audit, "retrieve_candidate", return_value=fixtures.two_sources()))
        return stack, save

    def test_decide_adopt_does_not_invent_actual_use(self):
        ledger = ledger_for(row_for())
        context, save = self.command_context(ledger)
        with context:
            self.assertEqual(manager.main(["decide", "creatine_monohydrate", "adopt"]), 0)
        row = save.call_args.args[0]["candidates"][0]
        self.assertEqual(row["user_decision"], "adopt")
        self.assertEqual(row["use_status"], "not_in_use")

    def test_cached_inspection_displays_policy_without_loading_models(self):
        ledger = ledger_for(row_for("bpc_157", use_status="in_use"))
        context, save = self.command_context(ledger)
        with context, patch.object(manager, "folder_pdf_count", return_value=0):
            self.assertEqual(manager.main(["inspect", "bpc_157", "--cached-only"]), 0)
        save.assert_not_called()

    def test_decide_restricted_adopt_leaves_state_unchanged(self):
        ledger = ledger_for(row_for("bpc_157", user_dose="USER ONLY"))
        context, save = self.command_context(ledger)
        with context:
            self.assertEqual(manager.main(["decide", "bpc_157", "adopt"]), 2)
        save.assert_not_called()

    def test_bulk_review_checks_every_selected_adoption(self):
        ledger = ledger_for(row_for(), row_for("bpc_157"))
        context, save = self.command_context(ledger)
        with context, patch.object(manager, "curses_multiselect", return_value={r["id"] for r in ledger["candidates"]}):
            manager.main(["review"])
        rows = {r["id"]: r for r in save.call_args.args[0]["candidates"]}
        self.assertEqual(rows["creatine_monohydrate"]["user_decision"], "adopt")
        self.assertEqual(rows["bpc_157"]["user_decision"], "undecided")
        self.assertTrue(all(r["use_status"] == "not_in_use" for r in rows.values()))

    def test_rank_selection_preserves_actual_use_and_gates_restricted_rows(self):
        ledger = ledger_for(row_for(), row_for("bpc_157"), row_for("caffeine", use_status="in_use", user_decision="adopt", user_dose="USER COFFEE"))
        context, save = self.live_context(ledger)
        with context, patch.object(manager, "curses_grade_select", return_value={"creatine_monohydrate", "bpc_157"}):
            self.assertEqual(manager.main(["rank", "--all-decisions"]), 0)
        rows = {r["id"]: r for r in save.call_args.args[0]["candidates"]}
        self.assertEqual(rows["creatine_monohydrate"]["user_decision"], "adopt")
        self.assertEqual(rows["creatine_monohydrate"]["use_status"], "not_in_use")
        self.assertEqual(rows["bpc_157"]["user_decision"], "undecided")
        self.assertEqual(rows["caffeine"]["use_status"], "in_use")
        self.assertEqual(rows["caffeine"]["user_dose"], "USER COFFEE")

    def test_cancelled_rank_never_saves_inferred_reasons(self):
        ledger = ledger_for(row_for(reasons=[]))
        context, save = self.live_context(ledger)
        with context, patch.object(manager, "curses_grade_select", return_value=None):
            self.assertEqual(manager.main(["rank"]), 0)
        save.assert_not_called()
        self.assertEqual(ledger["candidates"][0]["reasons"], [])

    def test_triage_adoption_is_intent_only(self):
        ledger = ledger_for(row_for())
        context, save = self.live_context(ledger)
        with context, patch.object(manager.Prompt, "ask", return_value="adopt"):
            self.assertEqual(manager.main(["triage"]), 0)
        self.assertEqual(save.call_args.args[0]["candidates"][0]["use_status"], "not_in_use")

    def test_triage_restricted_adoption_does_not_save(self):
        ledger = ledger_for(row_for("bpc_157"))
        context, save = self.live_context(ledger)
        with context, patch.object(manager.Prompt, "ask", return_value="adopt"):
            self.assertEqual(manager.main(["triage"]), 0)
        save.assert_not_called()

    def test_dose_review_does_not_compute_for_restricted_exposure(self):
        row = row_for("magnesium", use_status="in_use", user_dose="USER ONLY")
        with patch.object(manager, "compute_dose") as compute, patch.object(manager, "_print_evidence_review") as review, patch.object(manager, "console", Mock()):
            manager._dose_one(ledger_for(row), row, 80)
        compute.assert_not_called()
        self.assertEqual(review.call_args.args[0]["user_dose"], "USER ONLY")


if __name__ == "__main__":
    unittest.main()
