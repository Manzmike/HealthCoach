# rag/rag_control/test_ingest_gold_pack.py
import csv
import io
import unittest

from rag_control import ingest_gold_pack as IGP


def csv_rows(header: str, *lines: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(header + "\n" + "\n".join(lines)))
    return list(reader)


class SourceCsvRowsTests(unittest.TestCase):
    def test_seven_column_row_carries_cat_and_geography(self):
        rows = csv_rows(
            "lane,cat,title,origin,locator,grade,why",
            'sleep-OSA,03,NICE NG202 OSAHS,UK,nice.org.uk/guidance/ng202,A,Inconclusive study needs a real referral.',
        )
        chunks = IGP.chunks_from_source_rows(rows, pack_name="lifestyle")
        self.assertEqual(len(chunks), 1)
        c = chunks[0]
        self.assertEqual(c["lane"], "sleep-OSA")
        self.assertEqual(c["grade"], "A")
        self.assertEqual(c["geography"], "UK")
        self.assertTrue(c["personal"])
        self.assertEqual(c["folder"], "gold/lifestyle")
        self.assertIn("NICE NG202 OSAHS", c["text"])
        self.assertIn("nice.org.uk/guidance/ng202", c["text"])

    def test_six_column_row_missing_cat_still_works(self):
        rows = csv_rows(
            "lane,title,origin,locator,grade,why",
            'covid-vax,EMA PRAC myocarditis listing,EU,ema.europa.eu myocarditis,A,Regulator signal for a mid-20s male.',
        )
        chunks = IGP.chunks_from_source_rows(rows, pack_name="covid")
        self.assertEqual(chunks[0]["lane"], "covid-vax")
        self.assertEqual(chunks[0]["folder"], "gold/covid")

    def test_deny_rows_are_still_ingested_not_skipped(self):
        rows = csv_rows(
            "lane,title,origin,locator,grade,why",
            "deny-detox,Lymphatic detox teas / dry brushing / coffee enemas,any,DENY,—,Recreates worst output.",
        )
        chunks = IGP.chunks_from_source_rows(rows, pack_name="lymph")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["lane"], "deny-detox")


class RelationsCsvRowsTests(unittest.TestCase):
    def test_relation_row_uses_from_field_as_lane(self):
        rows = csv_rows(
            "from,to,relation,certainty,note",
            "screens-circadian,sleep-split,may worsen,medium,Bright laptop 18-23 delays melatonin. Does not cause witnessed apneas.",
        )
        chunks = IGP.chunks_from_relations_rows(rows)
        self.assertEqual(len(chunks), 1)
        c = chunks[0]
        self.assertEqual(c["lane"], "screens-circadian")
        self.assertEqual(c["grade"], "A")
        self.assertTrue(c["personal"])
        self.assertIn("may worsen", c["text"])
        self.assertIn("Does not cause witnessed apneas", c["text"])


if __name__ == "__main__":
    unittest.main()
