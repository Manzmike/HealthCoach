from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import candidate_ledger as CL
import candidate_manager as manager
import supplement_audit as audit


def no_evidence(*, fallback: bool = False) -> audit.Evidence:
    return audit.Evidence(
        "NONE", "—", 0, 0, "not established", [],
        hybrid_fallback=fallback,
        retrieval_notes=("candidate folders: hybrid failed; used vector-only",) if fallback else (),
    )


def one_source() -> audit.Evidence:
    return audit.Evidence(
        "WEAK", "B", 1, 1, "direct/general",
        [{
            "grade": "B",
            "folder": "test/folder",
            "doi": "10.0000/test",
            "source_pdf": "B_test.pdf",
            "text": "Participants were randomized. No significant difference was found. Safety was monitored.",
        }],
    )


def two_sources(text: str = "Participants significantly improved strength and performance.") -> audit.Evidence:
    return audit.Evidence(
        "STRONG", "A", 2, 2, "direct/general",
        [
            {
                "grade": "A", "folder": "test/folder", "doi": "10.0000/a",
                "source_pdf": "A_test.pdf", "text": text,
            },
            {
                "grade": "B", "folder": "test/folder", "doi": "10.0000/b",
                "source_pdf": "B_test.pdf", "text": text,
            },
        ],
    )


def intake(*, goals=("strength",), appetite="balanced"):
    value = CL.default_intake()
    value["goals"] = list(goals)
    value["preferences"]["evidence_appetite"] = appetite
    return value


class CandidateLedgerTests(unittest.TestCase):
    def add_row(self, **overrides):
        values = {
            "item_id": None,
            "display_name": "Typed recovery peptide",
            "item_class": "peptide",
            "aliases": ("TRP",),
            "folder": None,
            "consideration_scope": "undecided",
            "use_status": "not_in_use",
            "intent": "undecided",
            "observed": "unknown",
            "burden": "unknown",
            "blocker": {},
            "reasons": ("recovery",),
            "user_dose": None,
            "notes": None,
        }
        values.update(overrides)
        ledger, row, _created = CL.upsert_candidate(CL.empty_ledger(), **values)
        return ledger, row

    def evaluate(self, row, candidate, evidence, intake_state=None):
        return audit.evaluate_ledger_rows(
            [row], {row["id"]: candidate}, {row["id"]: evidence}, {}, intake_state
        )

    def test_typed_zero_paper_candidate_is_visible_watch_and_not_on_week(self):
        _ledger, row = self.add_row()
        candidate, built_in = audit.candidate_from_ledger_row(row)
        self.assertFalse(built_in)
        evaluations = self.evaluate(row, candidate, no_evidence())
        self.assertEqual(evaluations[row["id"]]["coverage"], "NONE")
        self.assertEqual(evaluations[row["id"]]["system_suggestion"], "WATCH")
        matrix = audit.stack_matrix_markdown([row], evaluations)
        card = audit.candidate_cards_markdown([row], evaluations)
        week = audit.adopted_week_overlay([row], evaluations)
        self.assertIn("Typed recovery peptide", matrix)
        self.assertIn("coverage `NONE` is an emitted result", card)
        self.assertNotIn("Typed recovery peptide", week)

    def test_already_using_user_dose_is_the_only_week_dose(self):
        _ledger, row = self.add_row(
            item_id="creatine_monohydrate",
            display_name="Creatine monohydrate",
            item_class="supplement",
            use_status="in_use",
            consideration_scope="personal_candidate",
            intent="keep",
            reasons=("strength",),
            user_dose="USER 7 g on training days",
        )
        candidate, _ = audit.candidate_from_ledger_row(row)
        evaluations = self.evaluate(row, candidate, one_source())
        week = audit.adopted_week_overlay([row], evaluations)
        self.assertIn("USER 7 g on training days", week)
        self.assertIn("in_use", week)

    def test_adopt_without_dose_emits_week_line_with_unset_dose(self):
        _ledger, row = self.add_row(
            display_name="Adopted candidate",
            item_class="supplement",
            reasons=("strength",),
        )
        row["user_decision"] = "adopt"
        candidate, _ = audit.candidate_from_ledger_row(row)
        evaluations = self.evaluate(row, candidate, one_source())
        week = audit.adopted_week_overlay([row], evaluations)
        self.assertIn("Adopted candidate", week)
        self.assertIn("dose unset", week)

    def test_legacy_skip_policy_cannot_remove_selected_row(self):
        built_in = next(candidate for candidate in audit.PEPTIDE_CATALOG if candidate.key.startswith("semaglutide_"))
        _ledger, row = self.add_row(
            item_id=built_in.key,
            display_name=built_in.name,
            item_class="peptide",
            reasons=("fat_loss",),
        )
        candidate, _ = audit.candidate_from_ledger_row(row)
        evaluations = self.evaluate(row, candidate, no_evidence())
        matrix = audit.stack_matrix_markdown([row], evaluations)
        card = audit.candidate_cards_markdown([row], evaluations)
        self.assertIn(built_in.name.replace("|", "/"), matrix)
        self.assertIn("LEGACY_POLICY=SKIP", matrix)
        self.assertIn(built_in.name, card)

    def test_invariant_and_fallback_provenance(self):
        _ledger, row = self.add_row()
        candidate, _ = audit.candidate_from_ledger_row(row)
        evaluations = self.evaluate(row, candidate, no_evidence(fallback=True))
        diff = CL.regeneration_diff(
            [row], evaluations, {row["id"]}, {row["id"]}
        )
        self.assertEqual(diff["selected_but_missing_from_inventory"], [])
        self.assertIn("VECTOR_ONLY_FALLBACK", evaluations[row["id"]]["flags"])

    def test_ledger_round_trip_is_atomic_and_private_path_can_be_overridden(self):
        ledger, row = self.add_row()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate_ledger.json"
            CL.save_ledger(ledger, path)
            loaded = CL.load_ledger(path)
            self.assertEqual(loaded["candidates"][0]["id"], row["id"])

    def test_schema_v1_research_only_migrates_without_inventing_scope(self):
        legacy = {
            "schema_version": 1,
            "candidates": [{
                "id": "legacy", "display_name": "Legacy row", "class": "supplement",
                "use_status": "research_only", "reasons": ["strength"],
                "user_decision": "undecided",
            }],
        }
        migrated = CL.normalize_ledger(legacy)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["candidates"][0]["use_status"], "not_in_use")
        self.assertEqual(migrated["candidates"][0]["consideration_scope"], "undecided")

    def test_confirmed_private_intake_prevents_old_profile_from_readding_current_use(self):
        args = audit.build_parser().parse_args(["--non-interactive", "--current", "creatine"])
        profile = audit.hard_define_profile(audit.default_profile(args))
        ledger = CL.empty_ledger()
        intake_state = CL.default_intake()
        intake_state["goals"] = ["strength"]
        ledger = CL.update_intake(ledger, intake_state)
        synced = audit.sync_profile_to_ledger(profile, ledger)
        creatine = CL.rows_by_id(synced)["creatine_monohydrate"]
        self.assertEqual(creatine["use_status"], "not_in_use")
        applied = audit.apply_ranking_intake_to_profile(
            profile, synced["intake"], synced["candidates"]
        )
        self.assertEqual(applied["current_supplement_keys"], [])
        self.assertEqual(applied["current_supplements"], "none confirmed in private intake")

    def test_profile_validation_no_longer_forces_old_current_items(self):
        args = audit.build_parser().parse_args([
            "--non-interactive", "--current", "none", "--medications", "none", "--peptides", "none",
        ])
        profile = audit.hard_define_profile(audit.default_profile(args))
        self.assertEqual(profile["current_supplement_keys"], [])
        self.assertEqual(profile["medication_keys"], [])
        self.assertEqual(profile["selected_peptide_keys"], [])

    def test_approved_suggestion_precedence(self):
        candidate = next(item for item in audit.CATALOG if item.key == "creatine_monohydrate")
        _ledger, row = self.add_row(
            item_id=candidate.key,
            display_name=candidate.name,
            item_class="supplement",
            consideration_scope="personal_candidate",
            reasons=("strength",),
            burden="acceptable",
        )
        evaluation = self.evaluate(row, candidate, two_sources(), intake_state=intake(appetite="conservative"))
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "ADOPT_CANDIDATE")

        research_row = dict(row, consideration_scope="research_only_topic")
        evaluation = self.evaluate(research_row, candidate, two_sources(), intake_state=intake())
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "WATCH")

        harm_row = dict(row, observed="harms", intent="want_replace")
        evaluation = self.evaluate(harm_row, candidate, two_sources(), intake_state=intake())
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "UNFAVORABLE")

        current_harm = dict(row, use_status="in_use", observed="harms", intent="keep")
        evaluation = self.evaluate(current_harm, candidate, two_sources(), intake_state=intake())
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "CONDITIONAL")

        current_keep = dict(row, use_status="in_use", observed="helps", intent="keep")
        evaluation = self.evaluate(current_keep, candidate, no_evidence(), intake_state=intake())
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "CONTINUE_CURRENT")

        blocked = dict(
            row,
            blocker={"present": True, "description": "USER_REPORTED prerequisite", "provenance": "USER_REPORTED"},
        )
        evaluation = self.evaluate(blocked, candidate, two_sources(), intake_state=intake())
        self.assertEqual(evaluation[row["id"]]["system_suggestion"], "CONDITIONAL")

        conflict_candidate = next(
            item for item in audit.PEPTIDE_CATALOG
            if item.key.startswith("semaglutide_do_not_stack")
        )
        self.assertEqual(audit.reason_stack_fit(conflict_candidate, []), "unknown")
        _ledger, conflict_row = self.add_row(
            item_id=conflict_candidate.key,
            display_name=conflict_candidate.name,
            item_class="peptide",
            consideration_scope="personal_candidate",
            reasons=("fat_loss",),
            burden="acceptable",
        )
        tirzepatide = next(
            item for item in audit.PEPTIDE_CATALOG
            if item.key == "tirzepatide_current_prescription"
        )
        _ledger, current_tirzepatide = self.add_row(
            item_id=tirzepatide.key,
            display_name=tirzepatide.name,
            item_class="peptide",
            consideration_scope="personal_candidate",
            use_status="in_use",
            intent="keep",
            reasons=("fat_loss",),
        )
        conflict_evaluation = audit.evaluate_ledger_rows(
            [conflict_row, current_tirzepatide],
            {conflict_row["id"]: conflict_candidate, current_tirzepatide["id"]: tirzepatide},
            {
                conflict_row["id"]: two_sources("Participants significantly reduced body weight."),
                current_tirzepatide["id"]: no_evidence(),
            },
            {},
            intake(goals=("fat_loss",)),
        )
        self.assertEqual(
            conflict_evaluation[conflict_row["id"]]["system_suggestion"], "CONDITIONAL"
        )

    def test_conservative_weak_floor_and_retrieved_harm(self):
        candidate = next(item for item in audit.CATALOG if item.key == "creatine_monohydrate")
        _ledger, row = self.add_row(
            item_id=candidate.key,
            display_name=candidate.name,
            item_class="supplement",
            consideration_scope="personal_candidate",
            reasons=("strength",),
            burden="acceptable",
        )
        weak_favor = audit.Evidence(
            "WEAK", "A", 1, 1, "direct/general",
            [{"grade": "A", "folder": "test", "doi": "10.0/weak", "source_pdf": "weak.pdf",
              "text": "Participants significantly improved strength."}],
        )
        conservative = self.evaluate(row, candidate, weak_favor, intake_state=intake(appetite="conservative"))
        balanced = self.evaluate(row, candidate, weak_favor, intake_state=intake(appetite="balanced"))
        self.assertEqual(conservative[row["id"]]["system_suggestion"], "WATCH")
        self.assertEqual(balanced[row["id"]]["system_suggestion"], "ADOPT_CANDIDATE")

        harm = self.evaluate(
            row, candidate, two_sources("Participants had increased risk and serious adverse outcomes."),
            intake_state=intake(),
        )
        self.assertEqual(harm[row["id"]]["system_suggestion"], "UNFAVORABLE")

    def test_full_catalog_rankings_share_visibility_and_exploratory_raises_uncertainty(self):
        strong = audit.Candidate(
            "strong", "Strong candidate", audit.QUEUE_LOW, (), ("strength",), ("strong",)
        )
        weak = audit.Candidate(
            "weak", "Weak candidate", audit.QUEUE_LOW, (), ("strength",), ("weak",)
        )
        evidence = {
            "strong": two_sources(),
            "weak": audit.Evidence(
                "WEAK", "A", 1, 1, "direct/general",
                [{"grade": "A", "folder": "test", "doi": "10.0/weak-rank",
                  "source_pdf": "weak.pdf", "text": "Strength remains uncertain."}],
            ),
        }
        rankings = audit.catalog_rankings(
            [strong, weak], evidence, [], intake(goals=("strength",), appetite="exploratory")
        )
        adopt_ids = [entry["id"] for entry in rankings["adopt_consider"]]
        research_ids = [entry["id"] for entry in rankings["research"]]
        self.assertEqual(set(adopt_ids), {"strong", "weak"})
        self.assertEqual(set(research_ids), {"strong", "weak"})
        self.assertEqual(adopt_ids[0], "strong")
        self.assertEqual(research_ids[0], "weak")

    def test_retrieved_annotation_has_closed_provenance(self):
        candidate = audit.Candidate(
            "test", "Test candidate", audit.QUEUE_LOW, (), ("strength",), ("test",)
        )
        ev = two_sources("The FDA regulatory status remains under review.")
        regulatory, sport, sourcing, _flags = audit.candidate_annotations(candidate, ev)
        self.assertEqual(regulatory["source"], "RETRIEVED")
        self.assertIn(sport["source"], CL.ANNOTATION_SOURCES)
        self.assertIn(sourcing["source"], CL.ANNOTATION_SOURCES)

    def test_inspect_resolver_accepts_id_display_name_and_alias(self):
        ledger, row = self.add_row()
        self.assertEqual(manager.find_ledger_row(ledger, row["id"])["id"], row["id"])
        self.assertEqual(manager.find_ledger_row(ledger, row["display_name"])["id"], row["id"])
        self.assertEqual(manager.find_ledger_row(ledger, "TRP")["id"], row["id"])

    def test_dry_run_renderer_does_not_write_output(self):
        args = audit.build_parser().parse_args(["--non-interactive"])
        profile = audit.hard_define_profile(audit.default_profile(args))
        candidate = audit.CATALOG[0]
        food_candidates = list(audit.WHOLE_FOOD_CATALOG)
        evidence = {candidate.key: no_evidence()}
        food_evidence = {food.key: no_evidence() for food in food_candidates}
        _ledger, row = self.add_row(
            item_id=candidate.key,
            display_name=candidate.name,
            item_class="supplement",
            use_status="in_use",
            reasons=("already_using",),
        )
        evaluations = self.evaluate(row, candidate, evidence[candidate.key])
        diff = CL.regeneration_diff([row], evaluations, {candidate.key}, {candidate.key})
        intake_state = intake(goals=("strength",))
        rankings = audit.catalog_rankings(
            [candidate], evidence, [row], intake_state, evaluations
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must_not_exist.md"
            text = audit.write_report(
                output,
                profile,
                [candidate],
                evidence,
                {candidate.key: "KEEP / REVIEW AGAINST EVIDENCE"},
                [],
                "**RETRIEVED:** timing not evaluated in unit test.",
                no_evidence(),
                food_candidates,
                food_evidence,
                [row],
                evaluations,
                diff,
                rankings,
                intake_state,
                dry_run=True,
            )
            self.assertFalse(output.exists())
            self.assertIn("selected_but_missing_from_inventory:** empty", text)
            self.assertIn("CANDIDATE STACK MATRIX", text)
            self.assertIn("FULL-CATALOG ADOPT-CONSIDER AND RESEARCH ORDERS", text)


if __name__ == "__main__":
    unittest.main()
