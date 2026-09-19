"""Offline tests for the strict workout/lifestyle/food coverage audit."""

import unittest

import coverage_audit as ca
import supplement_audit as food_audit


def row(*, grade="A", doi="10.1000/example", text="", source_pdf="x.pdf"):
    return {"grade": grade, "doi": doi, "text": text, "source_pdf": source_pdf}


class SourceCountingTests(unittest.TestCase):
    def test_food_audit_applies_candidate_topic_gate_to_family_rows(self):
        candidate = food_audit.Candidate(
            "parsley", "Parsley", food_audit.QUEUE_WHOLE_FOOD,
            ("01_food_inflammation/food_families/herb_spice_cocoa",),
            (), ("parsley", "herb", "culinary herb"),
        )
        rows = [
            {
                "folder": "01_food_inflammation/food_families/herb_spice_cocoa",
                "grade": "A", "doi": "10.1000/cocoa",
                "text": "Participants consumed cocoa products in a dietary intervention.",
            },
            {
                "folder": "01_food_inflammation/food_families/herb_spice_cocoa",
                "grade": "A", "doi": "10.1000/parsley",
                "text": "Participants consumed parsley as a culinary herb in a dietary intervention.",
            },
        ]
        result = ca.audit_food_rows([candidate], rows)
        self.assertEqual(result["items"]["parsley"]["source_count"], 1)
        self.assertEqual(result["items"]["parsley"]["status"], "WEAK")

    def test_food_requires_distinct_ab_human_dietary_sources(self):
        rows = [
            row(text="A randomized trial in adults consumed whole apples daily; dietary intake was measured."),
            row(doi="10.1000/example", source_pdf="duplicate.pdf",
                text="The same trial reported food consumption in participants."),
            row(grade="C", doi="10.1000/c", text="A review of apple nutrition and dietary intake."),
            row(grade="B", doi="10.1000/animal",
                text="An animal feeding study used apple extract."),
            row(grade="A", doi="10.1000/review",
                text="A systematic review of human dietary apple consumption in adults."),
        ]
        result = ca.count_strong_sources(rows, "food")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["status"], "STRONG")

    def test_workout_requires_exercise_relevance_and_deduplicates_by_path(self):
        rows = [
            row(doi="", source_pdf="a.pdf",
                text="Participants were randomized to resistance training and measured for strength."),
            row(doi="", source_pdf="a.pdf",
                text="The same resistance training trial continued in another indexed chunk."),
            row(grade="B", doi="10.1000/b",
                text="Adults completed an aerobic exercise intervention with a running outcome."),
            row(grade="A", doi="10.1000/off-topic",
                text="Participants received a dietary intervention; body mass was measured."),
        ]
        result = ca.count_strong_sources(rows, "workout")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["status"], "STRONG")

    def test_lifestyle_requires_human_lifestyle_exposure(self):
        rows = [
            row(doi="10.1000/sleep",
                text="Adults were randomized to a sleep regularity intervention and sleep quality was measured."),
            row(doi="10.1000/stress",
                text="A systematic review of workplace stress and burnout interventions in employees."),
            row(grade="A", doi="10.1000/off-topic",
                text="A review of laboratory biomarkers in cell culture."),
        ]
        result = ca.count_strong_sources(rows, "lifestyle")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["status"], "STRONG")

    def test_one_or_zero_sources_is_not_strong(self):
        self.assertEqual(ca.count_strong_sources([], "food")["status"], "NONE")
        self.assertEqual(
            ca.count_strong_sources([
                row(text="A randomized human dietary intervention measured food intake."),
            ], "food")["status"],
            "WEAK",
        )


class StrictGateTests(unittest.TestCase):
    def test_strict_exit_code_is_nonzero_when_any_target_is_below_strong(self):
        report = {"domains": {"food": {"status": "WEAK"}, "workout": {"status": "STRONG"}}}
        self.assertEqual(ca.strict_exit_code(report), 1)

    def test_strict_exit_code_is_zero_when_all_targets_are_strong(self):
        report = {"domains": {"food": {"status": "STRONG"}, "workout": {"status": "STRONG"}}}
        self.assertEqual(ca.strict_exit_code(report), 0)


if __name__ == "__main__":
    unittest.main()
