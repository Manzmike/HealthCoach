"""Tests for the end-to-end eval gate's phrase-aware requirements."""

import unittest

from rag_control import eval_run


class EvalRequirementTests(unittest.TestCase):
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
