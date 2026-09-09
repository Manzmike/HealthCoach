"""Offline test using a real temporary LanceDB table (no papers, no network,
no embedding model -- just schema/data assertions)."""

import shutil
import tempfile
import unittest

import lancedb

from rag_control import schema_migration as SM


class AddControlColumnsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = lancedb.connect(self.tmpdir)
        self.tbl = self.db.create_table("chunks", data=[
            {"text": "a", "grade": "A", "folder": "01_x", "doi": "", "source_pdf": "a.pdf"},
            {"text": "b", "grade": "C", "folder": "08_peptides_gray/x", "doi": "", "source_pdf": "b.pdf"},
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_adds_five_columns_with_expected_defaults(self):
        SM.add_control_columns(self.tbl)
        names = {f.name for f in self.tbl.schema}
        self.assertTrue({"lane", "personal", "quarantined", "quarantine_reason", "geography"} <= names)
        rows = self.tbl.search().select(
            ["lane", "personal", "quarantined", "quarantine_reason", "geography"]
        ).limit(10).to_list()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row["lane"])
            self.assertEqual(row["personal"], False)
            self.assertEqual(row["quarantined"], False)
            self.assertIsNone(row["quarantine_reason"])
            self.assertIsNone(row["geography"])

    def test_is_idempotent_on_a_table_that_already_has_the_columns(self):
        SM.add_control_columns(self.tbl)
        SM.add_control_columns(self.tbl)  # must not raise or duplicate columns
        names = [f.name for f in self.tbl.schema]
        self.assertEqual(names.count("lane"), 1)


if __name__ == "__main__":
    unittest.main()
