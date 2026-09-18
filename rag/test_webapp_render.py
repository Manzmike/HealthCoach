"""Offline tests for webapp/render.py's pure text->HTML helpers. No Flask,
no server, no model -- these just convert the plain-text answers coach.py
already produces (its **bold** markdown and | pipe | tables) into real
markup for the browser."""

import unittest

from webapp import render as R


class MarkdownLiteToHtmlTests(unittest.TestCase):
    def test_bold_becomes_strong(self):
        self.assertEqual(R.markdown_lite_to_html("**Study Use:** do X."),
                          "<p><strong>Study Use:</strong> do X.</p>")

    def test_blank_line_separates_paragraphs(self):
        html = R.markdown_lite_to_html("First paragraph.\n\nSecond paragraph.")
        self.assertEqual(html, "<p>First paragraph.</p>\n<p>Second paragraph.</p>")

    def test_single_newline_within_a_paragraph_becomes_br(self):
        html = R.markdown_lite_to_html("line one\nline two")
        self.assertEqual(html, "<p>line one<br>line two</p>")

    def test_html_special_characters_are_escaped_not_interpreted(self):
        html = R.markdown_lite_to_html("A <script>alert(1)</script> & \"quote\"")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_asterisks_survive_escaping_so_bold_still_works_on_escaped_text(self):
        html = R.markdown_lite_to_html("**<b>bold label</b>:** value")
        self.assertIn("<strong>", html)
        self.assertIn("&lt;b&gt;", html)  # the literal <b> text is escaped, not rendered as a tag

    def test_empty_or_whitespace_input_returns_empty_string(self):
        self.assertEqual(R.markdown_lite_to_html(""), "")
        self.assertEqual(R.markdown_lite_to_html("   \n  "), "")


class PipeTableToHtmlTests(unittest.TestCase):
    def test_converts_a_simple_table(self):
        text = ("SCHEDULE BREAKDOWN:\n\n"
                "| When | What the evidence says |\n"
                "|---|---|\n"
                "| Morning | Eat breakfast. |\n"
                "| Evening | Train after work. |")
        html = R.pipe_table_to_html(text)
        self.assertIn("<table>", html)
        self.assertIn("<th>When</th>", html)
        self.assertIn("<td>Morning</td>", html)
        self.assertIn("<td>Eat breakfast.</td>", html)
        self.assertNotIn("|---|", html)

    def test_text_before_the_table_is_kept_as_a_paragraph(self):
        text = "SCHEDULE BREAKDOWN (organized from the research above):\n\n| A | B |\n|---|---|\n| 1 | 2 |"
        html = R.pipe_table_to_html(text)
        self.assertIn("<p>SCHEDULE BREAKDOWN", html)
        self.assertIn("<table>", html)

    def test_no_table_falls_back_to_markdown_lite(self):
        html = R.pipe_table_to_html("**Answer:** no table here.")
        self.assertEqual(html, R.markdown_lite_to_html("**Answer:** no table here."))

    def test_cell_content_is_escaped(self):
        text = "| Col |\n|---|\n| <b>x</b> |"
        html = R.pipe_table_to_html(text)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
        self.assertNotIn("<b>x</b>", html)

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(R.pipe_table_to_html(""), "")


class LinesToHtmlTests(unittest.TestCase):
    def test_headers_at_each_level(self):
        html = R.lines_to_html("# One\n## Two\n### Three")
        self.assertIn("<h1>One</h1>", html)
        self.assertIn("<h2>Two</h2>", html)
        self.assertIn("<h3>Three</h3>", html)

    def test_a_flat_bullet_list_becomes_one_ul(self):
        html = R.lines_to_html("- first\n- second\n- third")
        self.assertEqual(html.count("<ul>"), 1)
        self.assertEqual(html.count("</ul>"), 1)
        self.assertEqual(html.count("<li>"), 3)

    def test_a_nested_bullet_opens_and_closes_its_own_ul(self):
        text = "- Ferritin — grade B.\n  - GOOD: \"quote one\"\n  - BAD: \"quote two\"\n- Zinc — grade C."
        html = R.lines_to_html(text)
        self.assertEqual(html.count("<ul>"), 2)
        self.assertEqual(html.count("</ul>"), 2)
        self.assertIn("GOOD", html)
        # the second top-level item ("Zinc") comes after the nested list closes
        self.assertLess(html.index("</ul>"), html.index("Zinc"))

    def test_blank_line_separates_a_list_from_a_following_paragraph(self):
        html = R.lines_to_html("- an item\n\nA plain paragraph.")
        self.assertIn("</ul>\n<p>A plain paragraph.</p>", html)

    def test_bold_and_escaping_inside_list_items(self):
        html = R.lines_to_html("- **Hard warning:** <b>Ferritin</b>")
        self.assertIn("<strong>Hard warning:</strong>", html)
        self.assertIn("&lt;b&gt;Ferritin&lt;/b&gt;", html)

    def test_a_realistic_cluster_alert_block_round_trips(self):
        text = "\n".join([
            "## Pattern worth flagging: an underactive thyroid (hypothyroidism)",
            "",
            "You selected 3 symptoms commonly seen together with an underactive thyroid: Constipation, Cold intolerance, Unexplained weight gain.",
            "",
            "Diagnosis is confirmed by labs, not symptoms.",
            "",
            "What's on file for you:",
            "  - TSH: 6.2 mIU/L (HIGH), recorded 2026-06-01",
            "",
        ])
        html = R.lines_to_html(text)
        self.assertIn("<h2>Pattern worth flagging: an underactive thyroid (hypothyroidism)</h2>", html)
        self.assertIn("<li>TSH: 6.2 mIU/L (HIGH), recorded 2026-06-01</li>", html)

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(R.lines_to_html(""), "")
        self.assertEqual(R.lines_to_html("   \n  "), "")


if __name__ == "__main__":
    unittest.main()
