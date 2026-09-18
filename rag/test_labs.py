"""Offline tests for labs.py's pure/argparse-free core: marker resolution,
status flags, and the extracted save_lab_value/extract_pdf_candidates/
save_confirmed_value functions the web GUI's /labs route calls directly
(no argparse.Namespace, no rich console, no interactive prompts)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import labs as L


class _IsolatedLabsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "labs.json"
        patcher = patch.object(L, "LABS_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)


class ResolveMarkerTests(unittest.TestCase):
    def test_exact_key_resolves(self):
        self.assertEqual(L.resolve_marker("tsh"), "tsh")

    def test_display_name_resolves(self):
        self.assertEqual(L.resolve_marker("Free T4"), "free_t4")

    def test_alias_resolves(self):
        self.assertEqual(L.resolve_marker("ft3"), "free_t3")

    def test_unknown_marker_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            L.resolve_marker("not_a_real_marker")


class MarkerStatusTests(unittest.TestCase):
    def test_low_normal_high(self):
        self.assertEqual(L.marker_status("tsh", 0.1), "LOW")
        self.assertEqual(L.marker_status("tsh", 2.0), "NORMAL")
        self.assertEqual(L.marker_status("tsh", 6.2), "HIGH")

    def test_unknown_key_is_unknown_range(self):
        self.assertEqual(L.marker_status("not_a_marker", 1.0), "UNKNOWN RANGE")


class SaveLabValueTests(_IsolatedLabsFile):
    def test_saves_with_default_unit_and_date(self):
        result = L.save_lab_value("tsh", 2.0)
        self.assertEqual(result["status"], "NORMAL")
        self.assertEqual(result["unit"], "mIU/L")
        entries = L.load_labs()["entries"]
        self.assertEqual(entries["tsh"]["value"], 2.0)
        self.assertEqual(entries["tsh"]["source"], "manual")

    def test_unconfirmed_unit_mismatch_raises_and_does_not_save(self):
        with self.assertRaises(ValueError):
            L.save_lab_value("tsh", 2.0, unit="ng/mL")
        self.assertNotIn("tsh", L.load_labs()["entries"])

    def test_confirmed_unit_mismatch_saves_with_override(self):
        result = L.save_lab_value("tsh", 2.0, unit="ng/mL", confirm_unit=True)
        self.assertEqual(result["unit"], "ng/mL")

    def test_explicit_date_is_kept(self):
        result = L.save_lab_value("ferritin", 45, date="2026-01-15")
        self.assertEqual(result["date"], "2026-01-15")

    def test_overwrites_previous_value_for_same_marker(self):
        L.save_lab_value("tsh", 2.0)
        L.save_lab_value("tsh", 6.2)
        self.assertEqual(L.load_labs()["entries"]["tsh"]["value"], 6.2)


class ExtractPdfCandidatesTests(unittest.TestCase):
    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            L.extract_pdf_candidates("/no/such/file.pdf")

    def test_finds_known_markers_in_extracted_text(self):
        fake_reader = type("R", (), {"pages": []})()
        with patch("pypdf.PdfReader", return_value=fake_reader), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(L, "_find_candidates_in_text", return_value=[
                 {"key": "tsh", "value": 6.2, "snippet": "TSH 6.2 mIU/L"}]):
            # Empty pages -> empty extracted text -> short-circuits before
            # _find_candidates_in_text is reached, so give it real text via
            # extract_text instead of relying on the empty-pages path.
            fake_page = type("P", (), {"extract_text": lambda self: "TSH 6.2 mIU/L"})()
            fake_reader.pages = [fake_page]
            candidates, filename = L.extract_pdf_candidates("report.pdf")
        self.assertEqual(filename, "report.pdf")
        self.assertEqual(candidates[0]["key"], "tsh")

    def test_no_extractable_text_returns_empty_candidates(self):
        fake_reader = type("R", (), {"pages": [type("P", (), {"extract_text": lambda self: ""})()]})()
        with patch("pypdf.PdfReader", return_value=fake_reader), \
             patch.object(Path, "exists", return_value=True):
            candidates, filename = L.extract_pdf_candidates("scanned.pdf")
        self.assertEqual(candidates, [])
        self.assertEqual(filename, "scanned.pdf")


class SaveConfirmedValueTests(_IsolatedLabsFile):
    def test_saves_with_markers_own_unit_and_given_source(self):
        result = L.save_confirmed_value("ferritin", 45.0, "2026-02-01", "pdf:quest.pdf")
        self.assertEqual(result["unit"], "ng/mL")
        entry = L.load_labs()["entries"]["ferritin"]
        self.assertEqual(entry["source"], "pdf:quest.pdf")
        self.assertEqual(entry["date"], "2026-02-01")


if __name__ == "__main__":
    unittest.main()
