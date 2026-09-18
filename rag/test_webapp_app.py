"""Route-level tests for webapp/app.py using Flask's test client -- no real
browser, no server process. The business logic under every route is already
covered by test_coach_*.py/test_schedule_builder.py/test_symptom_checkin.py/
test_labs.py; these tests check wiring: right template, right status code,
form-validation errors surfaced, file state isolated per test."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import labs as L
import schedule_builder as SB
from webapp import schedule_analysis as SA
from webapp.app import app


class _IsolatedState(unittest.TestCase):
    """Every test gets its own schedule_calendar.json, schedule_export.ics,
    schedule_analysis.json, and labs.json so real personal data on this
    machine is never touched or read. webapp/app.py's routes read
    SB.DEFAULT_PATH/SB.DEFAULT_ICS_PATH/SA.DEFAULT_PATH at call time (see
    app._load_schedule()'s docstring for why that matters: a `path=`
    default bound at function-definition time does NOT pick up a later
    patch.object() on the attribute -- confirmed live the hard way, when an
    earlier version of these tests silently wrote real Job/Breakfast/Lift
    blocks into this machine's actual rag/schedule_calendar.json and
    schedule_export.ics)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sched_path = str(Path(self.tmp.name) / "schedule_calendar.json")
        self.ics_path = str(Path(self.tmp.name) / "schedule_export.ics")
        self.analysis_path = Path(self.tmp.name) / "schedule_analysis.json"
        self.labs_path = Path(self.tmp.name) / "labs.json"
        for patcher in (patch.object(SB, "DEFAULT_PATH", self.sched_path),
                        patch.object(SB, "DEFAULT_ICS_PATH", self.ics_path),
                        patch.object(SA, "DEFAULT_PATH", self.analysis_path),
                        patch.object(L, "LABS_PATH", self.labs_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()


class GetRoutesRenderTests(unittest.TestCase):
    def test_every_get_page_renders_ok(self):
        client = app.test_client()
        for path in ("/", "/ask", "/symptoms", "/schedule", "/labs", "/more"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)


class ScheduleRoutesTests(_IsolatedState):
    def test_adding_a_non_research_block_redirects_to_the_grid_and_shows_it(self):
        r = self.client.post("/schedule/add", data={
            "category": "church", "label": "Sunday service", "days": "sun",
            "start": "9am", "end": "10:30am",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Sunday service", r.data)

    def test_a_research_relevant_category_redirects_to_research_guidance(self):
        with patch("coach.answer_question", return_value=[
            {"topic": "general", "text": "q", "no_evidence": True, "answer": "",
             "related": "", "schedule_block": "", "weak": False},
        ]):
            r = self.client.post("/schedule/add", data={
                "category": "gym", "label": "Lift", "days": "mon", "start": "7am", "end": "8am",
            })
        self.assertEqual(r.status_code, 302)
        self.assertIn("/schedule/research", r.headers["Location"])

    def test_unresolvable_category_shows_an_inline_error_and_does_not_save(self):
        r = self.client.post("/schedule/add", data={
            "category": "workoutt", "label": "x", "days": "mon", "start": "7am", "end": "8am",
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Unknown category", r.data)
        self.assertEqual(SB.load(self.sched_path)["blocks"], [])

    def test_unparseable_time_shows_an_inline_error(self):
        r = self.client.post("/schedule/add", data={
            "category": "church", "label": "x", "days": "mon", "start": "not a time", "end": "8am",
        })
        self.assertIn(b"Could not parse a time", r.data)

    def test_remove_pops_the_right_block_by_index(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="meal", label="Breakfast", start="07:00", end="07:30", days=["Mon"])
        SB.add_block(sched, category="work", label="Job", start="09:00", end="17:00", days=["Mon"])
        SB.save(sched, self.sched_path)
        r = self.client.post("/schedule/remove", data={"index": "0"}, follow_redirects=True)
        self.assertNotIn(b"Breakfast", r.data)
        self.assertIn(b"Job", r.data)

    def test_export_with_no_blocks_redirects_with_an_error_instead_of_500ing(self):
        r = self.client.get("/schedule/export.ics", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Add at least one block", r.data)

    def test_export_before_analyzing_is_refused_with_an_explanation(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.save(sched, self.sched_path)
        r = self.client.get("/schedule/export.ics", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Analyze the schedule first", r.data)

    def test_export_ics_downloads_a_real_calendar_file_once_analyzed(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.save(sched, self.sched_path)
        with patch("coach.answer_question", return_value=[]):
            self.client.post("/schedule/analyze")
        r = self.client.get("/schedule/export.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"BEGIN:VCALENDAR", r.data)
        self.assertIn(b"Lift", r.data)

    def test_editing_the_schedule_after_analyzing_re_locks_the_download(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.save(sched, self.sched_path)
        with patch("coach.answer_question", return_value=[]):
            self.client.post("/schedule/analyze")
        self.client.post("/schedule/add", data={
            "category": "church", "label": "Service", "days": "sun", "start": "9am", "end": "10am",
        })
        r = self.client.get("/schedule/export.ics", follow_redirects=True)
        self.assertIn(b"Analyze the schedule first", r.data)

    def test_analyze_runs_one_evidence_lookup_per_research_relevant_category(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="gym", label="Lift", start="17:00", end="18:00", days=["Mon"])
        SB.add_block(sched, category="church", label="Service", start="09:00", end="10:00", days=["Sun"])
        SB.save(sched, self.sched_path)
        with patch("coach.answer_question", return_value=[
            {"topic": "general", "text": "q", "no_evidence": False, "answer": "**Evidence:** train earlier.",
             "related": "", "schedule_block": "", "weak": False},
        ]) as mock_answer:
            r = self.client.post("/schedule/analyze", follow_redirects=True)
        mock_answer.assert_called_once()  # only "gym" is research-relevant; "church" is skipped
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"train earlier", r.data)

    def test_analyze_with_no_research_relevant_blocks_still_unlocks_download(self):
        sched = SB.empty_schedule()
        SB.add_block(sched, category="church", label="Service", start="09:00", end="10:00", days=["Sun"])
        SB.save(sched, self.sched_path)
        self.client.post("/schedule/analyze")
        r = self.client.get("/schedule/export.ics")
        self.assertEqual(r.status_code, 200)


class SymptomsRouteTests(_IsolatedState):
    def test_selecting_symptoms_renders_a_report(self):
        r = self.client.post("/symptoms", data={"symptom": ["Bloating", "Excess gas"]})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Bloating", r.data)

    def test_a_thyroid_cluster_selection_shows_the_alert(self):
        r = self.client.post("/symptoms", data={"symptom": [
            "Constipation", "Unexplained weight gain", "Cold intolerance",
        ]})
        self.assertIn("underactive thyroid".encode(), r.data)


class LabsRoutesTests(_IsolatedState):
    def test_adding_a_value_shows_up_in_the_table(self):
        r = self.client.post("/labs/add", data={"marker": "tsh", "value": "2.1"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"TSH", r.data)
        self.assertIn(b"NORMAL", r.data)

    def test_unknown_marker_shows_an_inline_error_and_does_not_save(self):
        r = self.client.post("/labs/add", data={"marker": "not_a_real_marker", "value": "1"})
        self.assertIn(b"Unknown marker", r.data)
        self.assertEqual(L.load_labs()["entries"], {})

    def test_unconfirmed_unit_mismatch_shows_an_inline_error(self):
        r = self.client.post("/labs/add", data={"marker": "tsh", "value": "2", "unit": "ng/mL"})
        self.assertIn(b"Unit mismatch", r.data)

    def test_import_with_no_file_shows_an_inline_error(self):
        r = self.client.post("/labs/import", data={}, content_type="multipart/form-data")
        self.assertIn(b"Choose a PDF file first", r.data)

    def test_import_shows_candidates_for_confirmation(self):
        candidates = [{"key": "tsh", "value": 6.2, "snippet": "TSH 6.2 mIU/L"}]
        with patch.object(L, "extract_pdf_candidates", return_value=(candidates, "quest.pdf")):
            data = {"pdf": (io.BytesIO(b"%PDF-fake"), "quest.pdf")}
            r = self.client.post("/labs/import", data=data, content_type="multipart/form-data")
        self.assertIn(b"TSH", r.data)
        self.assertIn(b"quest.pdf", r.data)
        self.assertEqual(L.load_labs()["entries"], {})  # nothing saved yet, confirmation still pending

    def test_import_with_no_recognized_markers_shows_an_inline_error(self):
        with patch.object(L, "extract_pdf_candidates", return_value=([], "blank.pdf")):
            data = {"pdf": (io.BytesIO(b"%PDF-fake"), "blank.pdf")}
            r = self.client.post("/labs/import", data=data, content_type="multipart/form-data")
        self.assertIn(b"No extractable text", r.data)

    def test_confirming_a_checked_candidate_saves_it(self):
        r = self.client.post("/labs/import/confirm", data={
            "filename": "quest.pdf", "date": "2026-06-01", "save": ["tsh"], "value_tsh": "6.2",
        }, follow_redirects=True)
        self.assertIn(b"TSH", r.data)
        entry = L.load_labs()["entries"]["tsh"]
        self.assertEqual(entry["value"], 6.2)
        self.assertEqual(entry["source"], "pdf:quest.pdf")

    def test_unchecked_candidates_are_not_saved(self):
        self.client.post("/labs/import/confirm", data={
            "filename": "quest.pdf", "date": "2026-06-01", "save": [],
        })
        self.assertEqual(L.load_labs()["entries"], {})


if __name__ == "__main__":
    unittest.main()
