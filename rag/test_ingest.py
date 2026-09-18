"""Offline regression test for ingest.py's incremental-append schema fix.

Real bug: a live table already migrated by rag_control.schema_migration has
5 control columns (lane, personal, quarantined, quarantine_reason,
geography) that ingest.py's own freshly-built rows never had -- appending
to it failed outright with "Append with different schema", confirmed live
when incrementally ingesting new PDFs after the safety-layer migration.
No model, no database, no network -- pure dict mutation."""

import unittest

import ingest as I


class BackfillControlColumnsTests(unittest.TestCase):
    def test_adds_defaults_only_for_columns_the_live_table_actually_has(self):
        rows = [{"text": "a"}, {"text": "b"}]
        I.backfill_control_columns(rows, {"text", "lane", "personal"})
        for row in rows:
            self.assertEqual(row["lane"], None)
            self.assertEqual(row["personal"], False)
            self.assertNotIn("quarantined", row)
            self.assertNotIn("quarantine_reason", row)
            self.assertNotIn("geography", row)

    def test_unmigrated_table_schema_leaves_rows_untouched(self):
        rows = [{"text": "a"}]
        I.backfill_control_columns(rows, {"text", "grade", "year"})
        self.assertEqual(rows, [{"text": "a"}])

    def test_fully_migrated_table_backfills_all_five_columns(self):
        rows = [{"text": "a"}]
        I.backfill_control_columns(rows, set(I.CONTROL_COLUMN_DEFAULTS) | {"text"})
        for name, default in I.CONTROL_COLUMN_DEFAULTS.items():
            self.assertEqual(rows[0][name], default)

    def test_empty_rows_list_does_not_raise(self):
        rows = []
        I.backfill_control_columns(rows, set(I.CONTROL_COLUMN_DEFAULTS))
        self.assertEqual(rows, [])

    def test_a_rows_own_existing_field_is_not_overwritten_by_a_default(self):
        # Not a real scenario today (ingest.py never sets these itself),
        # but backfill must never clobber a value a row already carries.
        rows = [{"text": "a", "personal": True}]
        I.backfill_control_columns(rows, {"personal"})
        self.assertEqual(rows[0]["personal"], True)


if __name__ == "__main__":
    unittest.main()
