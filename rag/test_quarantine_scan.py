import unittest

import quarantine_scan as QS


class ManifestParsingTests(unittest.TestCase):
    def test_parses_a_manifest_table_row(self):
        lines = [
            "| GRADE | YEAR | DOI/PMCID | FOLDER | FILENAME | SOURCE |",
            "|-------|------|-----------|--------|----------|--------|",
            "| B | 2025 | 10.7759/cureus.12345 | 08_peptides_gray/semaglutide | "
            "B_2025_semaglutide_case-report.pdf | unpaywall https://www.cureus.com/x.pdf |",
        ]
        rows = QS.parse_manifest_lines(lines)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doi"], "10.7759/cureus.12345")
        self.assertEqual(rows[0]["folder"], "08_peptides_gray/semaglutide")
        self.assertEqual(rows[0]["source_url"], "https://www.cureus.com/x.pdf")
        self.assertEqual(rows[0]["method"], "unpaywall")


class ClassifyPaperTests(unittest.TestCase):
    def _row(self, **over):
        base = {"grade": "A", "doi": "10.1000/example", "folder": "01_food_inflammation/oats",
                "filename": "A_2024_oats_review.pdf", "source_url": "https://link.springer.com/x.pdf",
                "method": "unpaywall", "allow_c": False}
        base.update(over)
        return base

    def test_cureus_case_report_below_grade_a_is_mill(self):
        row = self._row(grade="B", doi="10.7759/cureus.99999", source_url="https://www.cureus.com/y.pdf")
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="ordinary text"), "MILL")

    def test_cureus_systematic_review_grade_a_is_not_mill(self):
        row = self._row(grade="A", doi="10.7759/cureus.99999", source_url="https://www.cureus.com/y.pdf")
        self.assertIsNone(QS.classify_paper(row, chunk_text_sample="ordinary text"))

    def test_biorxiv_prefix_is_unlabeled_preprint(self):
        row = self._row(doi="10.1101/2024.01.01.123456")
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="ordinary text"), "UNLABELED_PREPRINT")

    def test_research_square_prefix_is_unlabeled_preprint(self):
        row = self._row(doi="10.21203/rs.3.rs-999999/v1")
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="ordinary text"), "UNLABELED_PREPRINT")

    def test_grade_c_not_allow_c_is_grade_c_default(self):
        row = self._row(grade="C", allow_c=False)
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="ordinary text"), "GRADE_C_DEFAULT")

    def test_grade_c_with_allow_c_true_is_not_flagged(self):
        row = self._row(grade="C", allow_c=True)
        self.assertIsNone(QS.classify_paper(row, chunk_text_sample="ordinary text"))

    def test_peptide_gray_protocol_language_is_flagged(self):
        row = self._row(folder="08_peptides_gray/bpc157", grade="C")
        text = "Reconstitute with bacteriostatic water and inject subcutaneous injection daily, titrate to 500mcg/day."
        self.assertEqual(QS.classify_paper(row, chunk_text_sample=text), "PEPTIDE_GRAY")

    def test_peptide_gray_mechanism_only_is_not_flagged_for_protocol(self):
        row = self._row(folder="08_peptides_gray/bpc157", grade="A")
        text = "This systematic review examines receptor binding and mechanism of action in animal models."
        self.assertIsNone(QS.classify_paper(row, chunk_text_sample=text))

    def test_nofap_keyword_is_flagged(self):
        row = self._row()
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="A nofap reboot streak protocol for men."), "NOFAP")

    def test_detox_keyword_is_flagged(self):
        row = self._row()
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="Try a coffee enema to detox the liver."), "DETOX")

    def test_lpi_domain_in_source_url_is_flagged(self):
        row = self._row(source_url="https://lpi.oregonstate.edu/nutrient/vitamin-c")
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="ordinary text"), "LPI_AS_ORDER")

    def test_name_only_with_no_doi_and_no_url_is_flagged(self):
        row = self._row(doi="", source_url="")
        self.assertEqual(QS.classify_paper(row, chunk_text_sample="Dr. Smith says this works."), "NAME_ONLY")

    def test_ordinary_paper_is_not_flagged(self):
        row = self._row()
        self.assertIsNone(QS.classify_paper(row, chunk_text_sample="Oats contain beta-glucan fiber."))


class DuplicateDoiTests(unittest.TestCase):
    def test_same_doi_same_folder_is_duplicate_but_first_seen_is_kept(self):
        rows = [
            {"doi": "10.1/x", "folder": "01_a", "filename": "f1.pdf"},
            {"doi": "10.1/x", "folder": "01_a", "filename": "f2.pdf"},
        ]
        flags = QS.find_duplicate_dois(rows)
        self.assertEqual(flags, {("01_a", "f2.pdf"): "DUPLICATE_DOI"})

    def test_same_doi_different_folder_is_hardlink_not_duplicate(self):
        rows = [
            {"doi": "10.1/x", "folder": "01_a", "filename": "f1.pdf"},
            {"doi": "10.1/x", "folder": "12_population_AA", "filename": "f1.pdf"},
        ]
        flags = QS.find_duplicate_dois(rows)
        self.assertEqual(flags, {})


if __name__ == "__main__":
    unittest.main()
