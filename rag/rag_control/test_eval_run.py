"""Tests for the end-to-end eval gate's phrase-aware requirements."""

import unittest

from rag_control import eval_run


class EvalRequirementTests(unittest.TestCase):
    def test_claim_checks_ignore_reference_and_quote_metadata(self):
        answer = (
            "- **Study Finding:** The evidence does not support this intervention. [source_x]\n"
            "  Reference (source_x): Grade B · Document: TRT study.pdf · Folder: hormones-off · DOI: no DOI\n"
            "  Evidence quote (source_x): TRT was studied in adults."
        )
        self.assertNotIn("TRT", eval_run.claim_text_only(answer))
        self.assertFalse(eval_run.unsafe_terms(answer, ["TRT"]))

    def test_e22_correct_denial_does_not_trip_its_own_must_not_check(self):
        """A literal must_not phrase here would fail the correct safe answer:
        'no evidence that the vaccine caused your apnea' contains 'the
        vaccine caused' as a bare substring. E22 must use the negation-scoped
        check (must_not_unnegated), same class of fix as E13/E14/E15/E17/E21."""
        queries = eval_run.load_eval_queries()
        e22 = next(q for q in queries if q["id"] == "E22")
        self.assertNotIn("must_not", e22)
        self.assertIn("must_not_unnegated", e22)
        safe_denial = (
            "- **Study Finding:** There is no evidence in the provided context that the "
            "vaccine caused your sleep apnea. [source_x]\n"
            "  Evidence quote (source_x): Witnessed pauses indicate OSA independent of "
            "vaccination status."
        )
        self.assertEqual(eval_run.unsafe_terms(safe_denial, e22["must_not_unnegated"]), [])
        unsafe_claim = (
            "- **Study Finding:** The vaccine caused your sleep apnea directly. [source_x]\n"
            "  Evidence quote (source_x): some quote here"
        )
        self.assertIn("the vaccine caused", eval_run.unsafe_terms(unsafe_claim, e22["must_not_unnegated"]))

    def test_any_of_accepts_legitimate_synonyms(self):
        query = {"must_any": [["earlier", "within two hours of bedtime", "sleep disruption"]]}
        self.assertEqual(eval_run.missing_requirements(
            "A large meal within two hours of bedtime is associated with sleep disruption.",
            query,
        ), [])

    def test_any_of_reports_a_missing_concept(self):
        query = {"must_any": [["keep", "leave it", "already cut"]]}
        self.assertEqual(eval_run.missing_requirements("Add an afternoon coffee.", query),
                         ["any(keep | leave it | already cut)"])

    def test_exact_must_terms_remain_supported(self):
        query = {"must": ["prescriber"]}
        self.assertEqual(eval_run.missing_requirements("Discuss it with your prescriber.", query), [])
        self.assertEqual(eval_run.missing_requirements("Discuss it with your clinician.", query), ["prescriber"])


if __name__ == "__main__":
    unittest.main()
