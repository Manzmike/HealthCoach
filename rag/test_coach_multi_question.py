"""Offline tests for coach.py's CLI-only multi-part question splitting and
schedule visual breakdown. No model, no database, no network -- pure
function tests against split_questions()/schedule_breakdown_for() and their
helpers. None of this touches search()/answer_from_hits(), so the eval
battery and every other caller of those functions is unaffected."""

import os
import tempfile
import unittest
from unittest.mock import patch

import coach


class SplitQuestionsTests(unittest.TestCase):
    def test_single_question_returns_one_group(self):
        groups = coach.split_questions("Does creatine cause hair loss?")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["text"], "Does creatine cause hair loss?")

    def test_the_real_five_part_question_splits_by_topic(self):
        q = ("How should I be living my live overall? What should My daily schdulue "
             "look like with gym involved? ? What should my 3 meals look like? "
             "Whats foods should I eat? How can i optmize my day for best health?")
        groups = coach.split_questions(q)
        topics = [g["topic"] for g in groups]
        self.assertEqual(topics, ["general", "schedule", "food", "general"])
        # The two food-topic segments were adjacent and merged into one pass.
        self.assertIn("3 meals", groups[2]["text"])
        self.assertIn("foods should I eat", groups[2]["text"])
        # A stray "?" fragment (from the doubled "??") contributes nothing.
        self.assertTrue(all(g["text"].strip() != "?" for g in groups))

    def test_adjacent_same_topic_segments_merge_into_one_group(self):
        groups = coach.split_questions("What should my meals look like? What foods should I eat?")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["topic"], "food")

    def test_non_adjacent_same_topic_segments_stay_separate(self):
        q = "How should I live overall? What should my meals look like? How can I optimize my day?"
        groups = coach.split_questions(q)
        # Both "general" segments are real but not adjacent (food sits between them),
        # so this heuristic keeps them as two passes rather than merging non-adjacent text.
        self.assertEqual([g["topic"] for g in groups], ["general", "food", "general"])

    def test_empty_or_whitespace_question_returns_one_group(self):
        self.assertEqual(coach.split_questions("   "), [{"topic": "general", "text": ""}])


class ScheduleQuestionDetectionTests(unittest.TestCase):
    def test_gym_and_schedule_wording_is_detected(self):
        self.assertTrue(coach.looks_like_schedule_question("What should my daily routine look like with gym involved?"))

    def test_unrelated_question_is_not_a_schedule_question(self):
        self.assertFalse(coach.looks_like_schedule_question("Does creatine cause hair loss?"))


class HasSavedScheduleTests(unittest.TestCase):
    def test_missing_file_is_no_saved_schedule(self):
        self.assertFalse(coach.has_saved_schedule(os.path.join(tempfile.mkdtemp(), "nope.md")))

    def test_trivial_stub_file_is_no_saved_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("# WEEK OPERATING PLAN\n")
            self.assertFalse(coach.has_saved_schedule(path))

    def test_real_content_is_a_saved_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("# WEEK OPERATING PLAN\n\n" + ("Real locked content. " * 30))
            self.assertTrue(coach.has_saved_schedule(path))


class RealScheduleBlockTests(unittest.TestCase):
    def test_extracts_the_week_at_a_glance_table_only(self):
        content = (
            "# WEEK OPERATING PLAN\n\nintro text\n\n"
            "# LOCKED NUMBERS\n\n- Wake: 04:30\n\n"
            "# WEEK AT A GLANCE\n\n| Day | Session |\n|---|---|\n| Monday | Lift A |\n\n"
            "# DAILY CARDS\n\n## Monday\n\nlots of detail here\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write(content)
            block = coach.real_schedule_block(path)
        self.assertIn("| Day | Session |", block)
        self.assertIn("| Monday | Lift A |", block)
        self.assertNotIn("Wake: 04:30", block)
        self.assertNotIn("lots of detail here", block)
        self.assertIn("YOUR SAVED SCHEDULE", block)

    def test_missing_section_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("# WEEK OPERATING PLAN\n\nno glance section here\n")
            self.assertEqual(coach.real_schedule_block(path), "")


class GenericScheduleTableTests(unittest.TestCase):
    def test_groups_claims_by_time_of_day_without_inventing_clock_times(self):
        answer = (
            "- **Study Use:** Eat a protein-rich breakfast to support morning satiety. [source_a]\n"
            "- **Safety:** Do not train in the evening if fighting sleep. [source_b]\n"
            "- **Mechanism:** Circadian rhythm affects hormone release generally. [source_c]\n"
        )
        table = coach.generic_schedule_table(answer)
        self.assertIn("SCHEDULE BREAKDOWN", table)
        self.assertIn("| Morning | Eat a protein-rich breakfast to support morning satiety. [source_a] |", table)
        self.assertIn("| Evening | Do not train in the evening if fighting sleep. [source_b] |", table)
        self.assertIn("| General | Circadian rhythm affects hormone release generally. [source_c] |", table)
        # Never a specific invented clock time -- only the generic period label.
        self.assertNotIn(":00", table.split("SCHEDULE BREAKDOWN")[1])

    def test_no_claims_returns_empty(self):
        self.assertEqual(coach.generic_schedule_table("No sufficiently relevant evidence was found."), "")


class ScheduleBreakdownForTests(unittest.TestCase):
    def test_non_schedule_question_gets_no_breakdown(self):
        self.assertEqual(coach.schedule_breakdown_for("Does creatine cause hair loss?", "- **X:** y [z]"), "")

    def test_schedule_question_prefers_the_real_saved_schedule(self):
        with patch("coach.has_saved_schedule", return_value=True), \
             patch("coach.real_schedule_block", return_value="YOUR SAVED SCHEDULE (from WEEK_OPERATING_PLAN.md):\n\nreal table"):
            block = coach.schedule_breakdown_for("What should my gym routine look like?", "- **X:** y [z]")
        self.assertIn("real table", block)

    def test_schedule_question_falls_back_to_generic_table_with_no_saved_schedule(self):
        with patch("coach.has_saved_schedule", return_value=False):
            block = coach.schedule_breakdown_for(
                "What should my daily routine look like with gym involved?",
                "- **Study Use:** Train in the evening after work. [source_a]\n",
            )
        self.assertIn("SCHEDULE BREAKDOWN", block)
        self.assertIn("Train in the evening after work.", block)


class ScheduleOverridePromptTests(unittest.TestCase):
    """prompt_schedule_override() never auto-writes a new schedule -- both
    non-'keep' choices back up the current file and hand the user their real
    editor, since WEEK_OPERATING_PLAN.md's LOCKED NUMBERS cross-reference
    dozens of derived values elsewhere in the file that an automated rewrite
    could get out of sync."""

    def test_non_interactive_stream_never_prompts(self):
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as mock_input:
            coach.prompt_schedule_override()
        mock_input.assert_not_called()

    def test_keep_choice_does_not_touch_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("original content")
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="keep"), \
                 patch("subprocess.run") as mock_run:
                coach.prompt_schedule_override(path)
            mock_run.assert_not_called()
            with open(path) as f:
                self.assertEqual(f.read(), "original content")
            self.assertEqual([f for f in os.listdir(d) if f != "plan.md"], [])

    def test_empty_input_defaults_to_keep(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""), \
             patch("subprocess.run") as mock_run:
            coach.prompt_schedule_override()
        mock_run.assert_not_called()

    def test_override_backs_up_before_opening_the_editor(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("original content")
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="override"), \
                 patch("subprocess.run") as mock_run, patch.dict(os.environ, {"EDITOR": "myeditor"}):
                coach.prompt_schedule_override(path)
            backups = [f for f in os.listdir(d) if f.startswith("plan.md.bak-")]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(d, backups[0])) as f:
                self.assertEqual(f.read(), "original content")
            mock_run.assert_called_once_with(["myeditor", path])

    def test_edit_asks_which_field_then_still_opens_the_editor(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.md")
            with open(path, "w") as f:
                f.write("original content")
            with patch("sys.stdin.isatty", return_value=True), \
                 patch("builtins.input", side_effect=["edit", "wake time"]), \
                 patch("subprocess.run") as mock_run:
                coach.prompt_schedule_override(path)
            self.assertTrue(any(f.startswith("plan.md.bak-") for f in os.listdir(d)))
            mock_run.assert_called_once()

    def test_unrecognized_choice_keeps_current_and_does_not_open_editor(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="delete everything"), \
             patch("subprocess.run") as mock_run:
            coach.prompt_schedule_override()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
