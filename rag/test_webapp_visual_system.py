"""Structural UI checks for the server-rendered GUI.

These are deliberately small browser-independent checks: they protect the
shared landmarks and layout contracts that make every page feel like the same
application, without trying to test CSS pixels in a Flask unit test.
"""

import unittest
from html.parser import HTMLParser

from webapp.app import app


class _Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs = {}
        self.nested_interactive = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        self.attrs.setdefault(tag, []).append(attrs)
        if tag in {"a", "button"} and self.tags[-2:-1] in (["a"], ["button"]):
            self.nested_interactive.append((self.tags[-2], tag))

    def handle_endtag(self, tag):
        if tag in self.tags:
            index = len(self.tags) - 1 - self.tags[::-1].index(tag)
            del self.tags[index:]


class SharedGuiStructureTests(unittest.TestCase):
    PAGES = ("/ask", "/food", "/settings", "/setup", "/setup/intake", "/schedule", "/symptoms", "/labs", "/more")

    def _page(self, path):
        response = app.test_client().get(path)
        self.assertEqual(response.status_code, 200, path)
        parsed = _Structure()
        parsed.feed(response.get_data(as_text=True))
        return parsed, response.get_data(as_text=True)

    def test_every_page_has_shared_landmarks_and_page_header(self):
        for path in self.PAGES:
            with self.subTest(path=path):
                parsed, html = self._page(path)
                self.assertIn('href="#main-content"', html)
                self.assertIn('id="main-content"', html)
                self.assertIn('aria-label="Primary navigation"', html)
                self.assertIn('class="page-header"', html)
                self.assertEqual(len(parsed.attrs.get("h1", [])), 1)

    def test_settings_marks_itself_as_the_current_page(self):
        _, html = self._page("/settings")
        self.assertIn('href="/settings" class="tab current" aria-current="page"', html)

    def test_food_and_labs_tables_have_responsive_wrappers_and_column_headers(self):
        for path in ("/food", "/labs"):
            with self.subTest(path=path):
                _, html = self._page(path)
                self.assertIn('class="table-wrap"', html)
                self.assertIn("<thead>", html)
                self.assertIn('scope="col"', html)

    def test_pages_have_no_nested_interactive_controls(self):
        for path in self.PAGES:
            with self.subTest(path=path):
                parsed, _ = self._page(path)
                self.assertEqual(parsed.nested_interactive, [])


if __name__ == "__main__":
    unittest.main()
