"""Offline regression tests for build_schedule.py's profile/history loading.

Covers the placeholder-history risk documented in docs/PROJECT_AI_HANDOFF.md:
history.md ships with only '- e.g.' example bullets, and reading it wholesale
folds fake data into the prompt as if it were real. No network, no models."""

import os
import tempfile
import unittest

import build_schedule as BS


def write(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class LoadHistoryTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(BS.load_history(os.path.join(tempfile.mkdtemp(), "nope.md")), "")

    def test_shipped_template_is_entirely_placeholder_and_returns_empty(self):
        """The exact regression: history.md with only unfilled '- e.g.' bullets
        must not be folded into the prompt as real history."""
        template = (
            "# MY HISTORY  (optional — delete a section or the whole file if you don't want it used)\n"
            "# If this file exists, build_schedule.py and build_playbook.py fold it into the plan.\n"
            "\n"
            "## CURRENT STACK   (what I already take / do)\n"
            "- e.g. creatine 5g daily, vitamin D, magnesium at night\n"
            "- e.g. lifting 4x/week, running 3x/week\n"
            "\n"
            "## RECENT LABS / METRICS\n"
            "- e.g. total testosterone: 520 ng/dL (2026-06)\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "history.md", template)
            self.assertEqual(BS.load_history(path), "")

    def test_real_content_survives_alongside_untouched_placeholder_sections(self):
        mixed = (
            "# instructional comment\n"
            "\n"
            "## CURRENT STACK\n"
            "- creatine 5g daily, real dose\n"
            "\n"
            "## RECENT LABS / METRICS\n"
            "- e.g. total testosterone: 520 ng/dL (2026-06)\n"
            "\n"
            "## INJURIES / LIMITATIONS\n"
            "- e.g. left knee sensitive to high volume downhill\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "history.md", mixed)
            result = BS.load_history(path)
        self.assertIn("CURRENT STACK", result)
        self.assertIn("creatine 5g daily, real dose", result)
        self.assertNotIn("520 ng/dL", result)
        self.assertNotIn("e.g.", result.lower())
        self.assertNotIn("RECENT LABS", result)      # placeholder-only section dropped
        self.assertNotIn("INJURIES", result)          # placeholder-only section dropped

    def test_case_insensitive_and_tolerant_of_leading_whitespace(self):
        content = "## STACK\n  - E.g. something fake\n- real thing here\n"
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "history.md", content)
            result = BS.load_history(path)
        self.assertIn("real thing here", result)
        self.assertNotIn("something fake", result)

    def test_default_path_honors_history_env_var(self, ):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "custom_history.md", "## S\n- a real line\n")
            old = os.environ.get("HISTORY")
            os.environ["HISTORY"] = path
            try:
                self.assertIn("a real line", BS.load_history())
            finally:
                if old is None:
                    os.environ.pop("HISTORY", None)
                else:
                    os.environ["HISTORY"] = old


class LoadProfileTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(BS.load_profile(os.path.join(tempfile.mkdtemp(), "nope.txt")), "")

    def test_comment_lines_are_stripped(self):
        content = "# a comment\nreal profile line one\n# another comment\nreal profile line two\n"
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "profile.txt", content)
            result = BS.load_profile(path)
        self.assertNotIn("comment", result)
        self.assertIn("real profile line one", result)
        self.assertIn("real profile line two", result)


if __name__ == "__main__":
    unittest.main()
