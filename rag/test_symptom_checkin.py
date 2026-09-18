"""Offline tests for symptom_checkin.py: the symptom catalog itself, the
hormone/organ-function cluster alert (and its labs.py integration), and the
picker's pure display logic (filter + grouped rows) -- no curses screen, no
real terminal. curses itself imports fine without a tty; only actual screen
I/O (curses.wrapper, addnstr, ...) needs one, and none of that is exercised
here."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import symptom_checkin as SC
import supplement_audit as audit


class LooksLikeCheckinRequestTests(unittest.TestCase):
    def test_recognizes_natural_phrasings(self):
        for text in ("I have some symptoms I want to check", "symptom check",
                     "what's wrong with me", "check my symptoms"):
            self.assertTrue(SC.looks_like_symptom_checkin_request(text), text)

    def test_an_unrelated_question_is_not_a_checkin_request(self):
        self.assertFalse(SC.looks_like_symptom_checkin_request("Does creatine cause hair loss?"))


class SymptomCatalogTests(unittest.TestCase):
    """Every tag used in SYMPTOMS must be one of the 11 real supplement_audit
    issue tags -- a symptom mapped to anything else silently matches nothing
    in the catalog, which is exactly the kind of thing that's invisible
    until a real user picks it and gets an empty report."""

    def test_every_symptom_tag_is_a_real_issue_tag(self):
        for label, (_group, tags) in SC.SYMPTOMS.items():
            for tag in tags:
                self.assertIn(tag, audit.ISSUES, f"{label!r} uses unknown tag {tag!r}")

    def test_the_reported_symptoms_are_all_present(self):
        """The exact gaps found while working through a real user's actual
        symptom list (dry hair, puffy face, slow heart rate, weight gain,
        constipation, possible infertility) -- confirms they're now pickable."""
        for label in ("Slow / low resting heart rate (bradycardia)", "Puffy or swollen face",
                      "Possible infertility / trouble conceiving", "Constipation",
                      "Unexplained weight gain", "Thinning hair / hair loss"):
            self.assertIn(label, SC.SYMPTOMS)

    def test_no_duplicate_symptom_labels(self):
        # dict keys can't literally duplicate, but this guards against a
        # copy-paste variant differing only by case/whitespace.
        normalized = [label.strip().lower() for label in SC.SYMPTOMS]
        self.assertEqual(len(normalized), len(set(normalized)))


class ClusterAlertsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_below_threshold_produces_no_alert(self):
        selected = ["Constipation", "Unexplained weight gain"]  # 2 of the 3 minimum
        self.assertEqual(SC.cluster_alerts(selected), [])

    def test_meeting_the_threshold_flags_the_pattern(self):
        selected = ["Constipation", "Unexplained weight gain", "Cold intolerance",
                    "Thinning hair / hair loss"]
        lines = SC.cluster_alerts(selected)
        text = "\n".join(lines)
        self.assertIn("underactive thyroid", text)
        self.assertIn("Constipation", text)
        self.assertIn("TSH, Free T4, and Free T3 lab values", text)
        self.assertIn("diet cannot correct thyroid hormone levels", text)

    def test_the_reported_symptom_combination_actually_triggers_the_alert(self):
        """The exact combination from the real report that prompted this
        feature: dry hair, puffy face, slow heart rate, weight gain,
        constipation, possible infertility."""
        selected = ["Thinning hair / hair loss", "Puffy or swollen face",
                    "Slow / low resting heart rate (bradycardia)", "Unexplained weight gain",
                    "Constipation", "Possible infertility / trouble conceiving"]
        lines = SC.cluster_alerts(selected)
        self.assertTrue(lines)
        self.assertIn("underactive thyroid", "\n".join(lines))

    def test_unrelated_symptoms_never_trigger_the_thyroid_alert(self):
        selected = ["Bloating", "Excess gas", "Anxiety / high stress", "Acne / breakouts"]
        self.assertEqual(SC.cluster_alerts(selected), [])

    def test_no_labs_on_file_says_so_and_points_to_providers(self):
        with patch.object(SC, "_lab_lines_for", return_value=[]):
            lines = SC.cluster_alerts(["Constipation", "Unexplained weight gain", "Cold intolerance"])
        text = "\n".join(lines)
        self.assertIn("No TSH/FREE_T4/FREE_T3 on file yet", text)
        self.assertIn("labs.py providers", text)

    def test_real_lab_values_on_file_are_shown_instead_of_the_generic_prompt(self):
        with patch.object(SC, "_lab_lines_for", return_value=["  - TSH: 6.2 mIU/L (HIGH), recorded 2026-06-01"]):
            lines = SC.cluster_alerts(["Constipation", "Unexplained weight gain", "Cold intolerance"])
        text = "\n".join(lines)
        self.assertIn("What's on file for you:", text)
        self.assertIn("TSH: 6.2 mIU/L (HIGH)", text)
        self.assertNotIn("labs.py providers", text)

    def test_lab_lines_for_reads_real_recorded_values(self):
        # _lab_lines_for() does `import labs as L` internally -- that binds
        # to the real, already-imported labs module, so redirecting its
        # LABS_PATH here is enough; no need to mock the import itself.
        import labs as L
        path = Path(self.tmp.name) / "labs.json"
        with patch.object(L, "LABS_PATH", path):
            L.save_labs({"entries": {"tsh": {"value": 6.2, "unit": "mIU/L", "date": "2026-06-01",
                                              "source": "manual"}}})
            lines = SC._lab_lines_for(("tsh", "free_t4"))
        self.assertEqual(len(lines), 1)
        self.assertIn("TSH: 6.2 mIU/L (HIGH)", lines[0])

    def test_lab_lines_for_returns_empty_when_labs_module_is_unavailable(self):
        def fail_import(name, *a, **k):
            if name == "labs":
                raise ImportError("no labs module")
            return __import__(name, *a, **k)
        with patch("builtins.__import__", side_effect=fail_import):
            self.assertEqual(SC._lab_lines_for(("tsh",)), [])


class FilterLabelsTests(unittest.TestCase):
    def test_empty_query_returns_everything_in_original_order(self):
        self.assertEqual(SC.filter_labels(""), list(SC.SYMPTOMS))
        self.assertEqual(SC.filter_labels("   "), list(SC.SYMPTOMS))

    def test_a_real_word_finds_the_matching_symptoms(self):
        results = SC.filter_labels("hair")
        self.assertIn("Thinning hair / hair loss", results)
        self.assertIn("Hair breakage / brittle hair", results)
        self.assertTrue(all("hair" in label.lower() for label in results))

    def test_case_insensitive(self):
        self.assertEqual(SC.filter_labels("HAIR"), SC.filter_labels("hair"))

    def test_no_match_returns_empty_not_everything(self):
        self.assertEqual(SC.filter_labels("xyznonexistent"), [])


class GroupedRowsTests(unittest.TestCase):
    def test_a_header_row_precedes_the_first_label_of_each_group(self):
        labels = ["Dry / flaky scalp", "Dandruff", "Bloating"]  # 2x Skin & Hair, 1x Digestion
        rows = SC.grouped_rows(labels)
        self.assertEqual(rows[0], ("Skin & Hair", None))
        self.assertEqual(rows[1], (None, "Dry / flaky scalp"))
        self.assertEqual(rows[2], (None, "Dandruff"))
        self.assertEqual(rows[3], ("Digestion", None))
        self.assertEqual(rows[4], (None, "Bloating"))

    def test_every_label_appears_exactly_once_as_a_row(self):
        labels = list(SC.SYMPTOMS)
        rows = SC.grouped_rows(labels)
        row_labels = [label for _header, label in rows if label is not None]
        self.assertEqual(row_labels, labels)

    def test_a_single_group_gets_exactly_one_header(self):
        labels = ["Bloating", "Excess gas", "Constipation"]  # all Digestion
        rows = SC.grouped_rows(labels)
        headers = [h for h, _l in rows if h is not None]
        self.assertEqual(headers, ["Digestion"])

    def test_empty_label_list_produces_no_rows(self):
        self.assertEqual(SC.grouped_rows([]), [])


if __name__ == "__main__":
    unittest.main()
