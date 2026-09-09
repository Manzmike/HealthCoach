"""Offline regression test: the xlsx lifestyle ingester must never silently
replace the paper corpus table. No network, no real xlsx file, no database."""

import argparse
import unittest
from unittest.mock import MagicMock, patch

import ingest_foods_lifestyle as IFL


class DefaultBehaviorIsSafeTests(unittest.TestCase):
    def test_no_flags_does_not_drop_existing_table(self):
        """Plain `python3 ingest_foods_lifestyle.py` (no flags) must append,
        never drop_table — that is the exact incident this fixes."""
        args = argparse.Namespace(limit=0, incremental=False, staging=False,
                                   confirm=False, force_rebuild=False)
        fake_table = MagicMock()
        fake_table.search.return_value.select.return_value.limit.return_value.to_list.return_value = []
        fake_db = MagicMock()
        fake_db.list_tables.return_value = ["chunks"]
        fake_db.open_table.return_value = fake_table

        with patch.object(IFL, "build_chunks_from_xlsx", return_value=[
            {"text": "x" * 150, "grade": "A", "year": 2024, "folder": "f",
             "cohort": "general", "doi": "", "source_pdf": "row_1.xlsx",
             "allow_c": False, "chunk_ordinal": 0, "char_start": 0,
             "char_end": 150, "page_hint": 1, "content_hash": "h"},
        ]):
            with patch("lancedb.connect", return_value=fake_db), \
                 patch("sentence_transformers.SentenceTransformer") as fake_st:
                fake_st.return_value.encode.return_value = [[0.0] * 768]
                IFL.run(args)

        fake_db.drop_table.assert_not_called()
        fake_table.add.assert_called_once()

    def test_force_rebuild_flag_still_drops(self):
        """The old destructive behavior must remain available, explicitly."""
        args = argparse.Namespace(limit=0, incremental=False, staging=False,
                                   confirm=False, force_rebuild=True)
        fake_db = MagicMock()
        fake_db.list_tables.return_value = ["chunks"]

        with patch.object(IFL, "build_chunks_from_xlsx", return_value=[
            {"text": "x" * 150, "grade": "A", "year": 2024, "folder": "f",
             "cohort": "general", "doi": "", "source_pdf": "row_1.xlsx",
             "allow_c": False, "chunk_ordinal": 0, "char_start": 0,
             "char_end": 150, "page_hint": 1, "content_hash": "h"},
        ]):
            with patch("lancedb.connect", return_value=fake_db), \
                 patch("sentence_transformers.SentenceTransformer") as fake_st:
                fake_st.return_value.encode.return_value = [[0.0] * 768]
                IFL.run(args)

        fake_db.drop_table.assert_called_once_with("chunks")
        fake_db.create_table.assert_called_once()


if __name__ == "__main__":
    unittest.main()
