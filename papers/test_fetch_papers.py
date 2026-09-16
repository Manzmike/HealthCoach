"""Offline regression tests for fetch_papers.py's ad-hoc single-question
fetch path. No network -- epmc_search/extra_search/acquire are mocked."""

import glob
import os
import tempfile
import unittest
from unittest.mock import patch

import fetch_papers as FP


class FetchForQuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Isolate every module global fetch_for_question touches so this
        # test never reads or writes the real papers/ tree or its logs.
        patchers = [
            patch.object(FP, "ROOT", self.tmp.name),
            patch.object(FP, "MANIFEST", os.path.join(self.tmp.name, "MANIFEST.md")),
            patch.object(FP, "FAILED", os.path.join(self.tmp.name, "SOURCES_FAILED.md")),
            patch.object(FP, "COUNTS", {}),
            patch.object(FP, "SEEN_DOI", {}),
            patch.object(FP, "SEEN_PMC", set()),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _fake_acquire(self, rec, folder_rel, slug, **kwargs):
        """A minimal stand-in for acquire() that does the one thing
        fetch_for_question() actually depends on: writing a new PDF into
        the target folder and bumping COUNTS, without any network call,
        grading, or dedup logic (those are acquire()'s own tested concerns,
        not fetch_for_question()'s orchestration)."""
        folder_abs = os.path.join(self.tmp.name, folder_rel)
        os.makedirs(folder_abs, exist_ok=True)
        safe_name = rec["doi"].replace("/", "_")
        path = os.path.join(folder_abs, f"{safe_name}.pdf")
        with open(path, "w") as f:
            f.write("fake pdf")
        FP.COUNTS[folder_rel] = FP.COUNTS.get(folder_rel, 0) + 1
        return True

    def test_stops_once_target_reached_from_epmc_alone(self):
        recs = [{"doi": f"10.1/{i}"} for i in range(10)]
        with patch.object(FP, "epmc_search", return_value=recs) as mock_epmc, \
             patch.object(FP, "extra_search") as mock_extra, \
             patch.object(FP, "acquire", side_effect=self._fake_acquire):
            added = FP.fetch_for_question("does creatine cause hair loss", max_results=3)
        self.assertEqual(added, 3)
        mock_epmc.assert_called_once_with("does creatine cause hair loss")
        mock_extra.assert_not_called()  # EPMC alone already reached the target

    def test_falls_back_to_extra_search_when_epmc_is_short(self):
        epmc_recs = [{"doi": "10.1/a"}]
        extra_recs = [{"doi": "10.1/b"}, {"doi": "10.1/c"}]
        with patch.object(FP, "epmc_search", return_value=epmc_recs), \
             patch.object(FP, "extra_search", return_value=extra_recs) as mock_extra, \
             patch.object(FP, "acquire", side_effect=self._fake_acquire):
            added = FP.fetch_for_question("a very obscure compound", max_results=3)
        self.assertEqual(added, 3)
        mock_extra.assert_called_once_with("a very obscure compound")

    def test_epmc_failure_does_not_crash_the_fetch(self):
        with patch.object(FP, "epmc_search", side_effect=RuntimeError("network down")), \
             patch.object(FP, "extra_search", return_value=[{"doi": "10.1/x"}]), \
             patch.object(FP, "acquire", side_effect=self._fake_acquire):
            added = FP.fetch_for_question("anything", max_results=1)
        self.assertEqual(added, 1)

    def test_no_results_from_either_source_adds_nothing(self):
        with patch.object(FP, "epmc_search", return_value=[]), \
             patch.object(FP, "extra_search", return_value=[]):
            added = FP.fetch_for_question("nothing findable", max_results=3)
        self.assertEqual(added, 0)

    def test_writes_into_the_named_folder_not_the_curated_taxonomy(self):
        with patch.object(FP, "epmc_search", return_value=[{"doi": "10.1/z"}]), \
             patch.object(FP, "extra_search", return_value=[]), \
             patch.object(FP, "acquire", side_effect=self._fake_acquire):
            FP.fetch_for_question("x", max_results=1, folder="custom_folder")
        pdfs = glob.glob(os.path.join(self.tmp.name, "custom_folder", "*.pdf"))
        self.assertEqual(len(pdfs), 1)


if __name__ == "__main__":
    unittest.main()
