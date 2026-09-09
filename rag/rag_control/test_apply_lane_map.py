import shutil
import tempfile
import unittest

import lancedb

from rag_control import apply_lane_map as ALM
from rag_control import schema_migration as SM


class ApplyLaneMapTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        db = lancedb.connect(self.tmpdir)
        self.tbl = db.create_table("chunks", data=[
            {"text": "a", "folder": "14_hormones_thyroid_heart/lipids_apob_ldl", "source_pdf": "a.pdf"},
            {"text": "b", "folder": "14_hormones_thyroid_heart/lipids_apob_ldl", "source_pdf": "b.pdf"},
            {"text": "c", "folder": "08_peptides_gray/semaglutide", "source_pdf": "c.pdf"},
        ])
        SM.add_control_columns(self.tbl)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mapped_folder_gets_its_lane_unmapped_stays_null(self):
        updated = ALM.apply(self.tbl, {"14_hormones_thyroid_heart/lipids_apob_ldl": "lipids"})
        self.assertEqual(updated, 2)
        rows = {r["source_pdf"]: r["lane"] for r in self.tbl.search().select(["source_pdf", "lane"]).limit(10).to_list()}
        self.assertEqual(rows["a.pdf"], "lipids")
        self.assertEqual(rows["b.pdf"], "lipids")
        self.assertIsNone(rows["c.pdf"])

    def test_is_idempotent(self):
        ALM.apply(self.tbl, {"14_hormones_thyroid_heart/lipids_apob_ldl": "lipids"})
        second_pass_updated = ALM.apply(self.tbl, {"14_hormones_thyroid_heart/lipids_apob_ldl": "lipids"})
        self.assertEqual(second_pass_updated, 2)  # re-running re-asserts the same value, doesn't error


if __name__ == "__main__":
    unittest.main()
