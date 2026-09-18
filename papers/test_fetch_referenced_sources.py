"""Offline tests for fetch_referenced_sources.py: sitemap URL filtering,
citation-link extraction from real-shaped HTML, and the crawl-resolve-
acquire pipeline with every network call replaced. No real HTTP requests."""

import os
import tempfile
import unittest
from unittest.mock import patch

import fetch_referenced_sources as FRS
import fetch_papers as FP


class ArticleUrlsFromSitemapTests(unittest.TestCase):
    SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.jayfeldmanwellness.com/articles/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/health-topics/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/the-cholesterol-nonsense-continues/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/about-jay/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/contact/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/category/nutrition/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/sugar-does-not-cause-inflammation-part-1/</loc></url>
<url><loc>https://www.jayfeldmanwellness.com/sugar-does-not-cause-inflammation-part-1/</loc></url>
</urlset>"""

    def test_keeps_only_single_segment_article_slugs(self):
        urls = FRS.article_urls_from_sitemap(self.SITEMAP, "jayfeldmanwellness.com")
        self.assertEqual(urls, [
            "https://www.jayfeldmanwellness.com/sugar-does-not-cause-inflammation-part-1/",
            "https://www.jayfeldmanwellness.com/the-cholesterol-nonsense-continues/",
        ])

    def test_known_non_article_pages_are_excluded(self):
        urls = FRS.article_urls_from_sitemap(self.SITEMAP, "jayfeldmanwellness.com")
        self.assertNotIn("https://www.jayfeldmanwellness.com/about-jay/", urls)
        self.assertNotIn("https://www.jayfeldmanwellness.com/contact/", urls)

    def test_nested_category_pages_are_excluded(self):
        urls = FRS.article_urls_from_sitemap(self.SITEMAP, "jayfeldmanwellness.com")
        self.assertNotIn("https://www.jayfeldmanwellness.com/category/nutrition/", urls)

    def test_duplicate_urls_collapse_once(self):
        urls = FRS.article_urls_from_sitemap(self.SITEMAP, "jayfeldmanwellness.com")
        self.assertEqual(len(urls), len(set(urls)))

    def test_a_url_pattern_not_present_returns_nothing(self):
        self.assertEqual(FRS.article_urls_from_sitemap(self.SITEMAP, "someothersite.com"), [])


class ExtractCitationsTests(unittest.TestCase):
    def test_pubmed_links_are_extracted(self):
        html = '<a href="https://www.ncbi.nlm.nih.gov/pubmed/12397569">study</a>'
        self.assertEqual(FRS.extract_citations(html), {("MED", "12397569")})

    def test_pmc_links_are_extracted(self):
        html = '<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3247776/">study</a>'
        self.assertEqual(FRS.extract_citations(html), {("PMC", "PMC3247776")})

    def test_doi_links_are_extracted_from_arbitrary_publisher_domains(self):
        html = '<a href="http://www.nejm.org/doi/pdf/10.1056/NEJM193012252032601">study</a>'
        self.assertEqual(FRS.extract_citations(html), {("DOI", "10.1056/NEJM193012252032601")})

    def test_trailing_punctuation_is_stripped_from_a_doi(self):
        html = '<a href="https://doi.org/10.1056/NEJM193012252032601.">study</a>'
        citations = FRS.extract_citations(html)
        self.assertEqual(citations, {("DOI", "10.1056/NEJM193012252032601")})

    def test_multiple_distinct_citations_on_one_page_are_all_found(self):
        html = ('<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a</a> '
                '<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC222/">b</a> '
                '<a href="https://doi.org/10.1000/xyz">c</a>')
        self.assertEqual(FRS.extract_citations(html),
                          {("MED", "111"), ("PMC", "PMC222"), ("DOI", "10.1000/xyz")})

    def test_a_repeated_citation_link_is_not_duplicated(self):
        html = ('<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a</a> '
                '<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a again</a>')
        self.assertEqual(FRS.extract_citations(html), {("MED", "111")})

    def test_navigation_and_social_links_produce_no_citations(self):
        html = ('<a href="https://www.facebook.com/jayfeldmanwellness">fb</a> '
                '<a href="https://www.jayfeldmanwellness.com/about-jay/">about</a>')
        self.assertEqual(FRS.extract_citations(html), set())

    def test_a_bare_doi_looking_string_outside_an_href_is_not_extracted(self):
        html = "<p>See DOI 10.1056/NEJM193012252032601 in the references below.</p>"
        self.assertEqual(FRS.extract_citations(html), set())


class ResolveTests(unittest.TestCase):
    def test_pubmed_id_resolves_via_hydrate(self):
        with patch.object(FP, "hydrate", return_value=[{"doi": "10.1/x", "title": "t"}]) as mock_hydrate:
            rec = FRS.resolve("MED", "12345")
        mock_hydrate.assert_called_once_with("MED", "12345")
        self.assertEqual(rec["doi"], "10.1/x")

    def test_pmc_id_resolves_via_hydrate(self):
        with patch.object(FP, "hydrate", return_value=[{"pmcid": "PMC1"}]):
            rec = FRS.resolve("PMC", "PMC1")
        self.assertEqual(rec["pmcid"], "PMC1")

    def test_doi_resolves_via_a_direct_epmc_query_not_hydrate(self):
        with patch.object(FP, "epmc_search", return_value=[{"doi": "10.1/y"}]) as mock_search, \
             patch.object(FP, "hydrate") as mock_hydrate:
            rec = FRS.resolve("DOI", "10.1/y")
        mock_search.assert_called_once_with("DOI:10.1/y", oa_only=False, page_size=1)
        mock_hydrate.assert_not_called()
        self.assertEqual(rec["doi"], "10.1/y")

    def test_unresolvable_citation_returns_none_after_exhausting_retries(self):
        with patch.object(FP, "hydrate", return_value=None) as mock_hydrate:
            result = FRS.resolve("MED", "0", _sleep=lambda *_: None)
        self.assertIsNone(result)
        self.assertEqual(mock_hydrate.call_count, 3)  # default attempts=3, all exhausted

    def test_a_transient_empty_result_is_retried_and_then_succeeds(self):
        """Confirmed live: the same citations that mostly failed to resolve
        in one real run all resolved cleanly moments later -- the network is
        unreliable at this volume, not the citations missing from EPMC."""
        responses = iter([None, None, [{"doi": "10.1/z"}]])
        with patch.object(FP, "hydrate", side_effect=lambda *_: next(responses)) as mock_hydrate:
            rec = FRS.resolve("MED", "12345", _sleep=lambda *_: None)
        self.assertEqual(rec["doi"], "10.1/z")
        self.assertEqual(mock_hydrate.call_count, 3)

    def test_success_on_the_first_attempt_never_sleeps_or_retries(self):
        sleeps = []
        with patch.object(FP, "hydrate", return_value=[{"doi": "10.1/x"}]) as mock_hydrate:
            FRS.resolve("MED", "12345", _sleep=sleeps.append)
        mock_hydrate.assert_called_once()
        self.assertEqual(sleeps, [])


class RunPipelineTests(unittest.TestCase):
    """The full crawl-extract-resolve-acquire pipeline, every network/IO
    seam replaced -- no real HTTP requests, no real papers/ writes."""

    SITEMAP = """<urlset><url><loc>https://example.com/article-one/</loc></url>
<url><loc>https://example.com/article-two/</loc></url></urlset>"""

    def test_full_pipeline_counts_and_acquires_correctly(self):
        pages = {
            "https://example.com/article-one/":
                '<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a</a>',
            "https://example.com/article-two/":
                '<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a</a> '  # same citation, both pages
                '<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC222/">b</a>',
        }

        def fake_fetch(url):
            return pages[url]

        def fake_resolve(src, ext_id):
            if (src, ext_id) == ("MED", "111"):
                return {"doi": "10.1/a", "title": "Study A"}
            return None  # PMC222 is unresolvable

        acquired_calls = []

        def fake_acquire(rec, folder, slug):
            acquired_calls.append((rec, folder, slug))
            return True

        with patch.object(FP, "log_failed") as mock_log_failed:
            result = FRS.run("jay_feldman", self.SITEMAP, "example.com",
                              _fetch=fake_fetch, _resolve=fake_resolve, _acquire=fake_acquire)

        self.assertEqual(result["pages_crawled"], 2)
        self.assertEqual(result["fetch_failures"], 0)
        self.assertEqual(result["citations_found"], 2)  # MED:111 (deduped across both pages) + PMC:222
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(result["acquired"], 1)
        self.assertEqual(result["folder"], "referenced_by_jay_feldman")
        self.assertEqual(len(acquired_calls), 1)
        self.assertEqual(acquired_calls[0][1], "referenced_by_jay_feldman")
        mock_log_failed.assert_called_once()  # the unresolvable PMC222 citation

    def test_a_fetch_failure_on_one_page_does_not_abort_the_whole_crawl(self):
        def fake_fetch(url):
            if url.endswith("article-one/"):
                raise TimeoutError("slow site")
            return '<a href="https://www.ncbi.nlm.nih.gov/pubmed/111">a</a>'

        with patch.object(FP, "log_failed"):
            result = FRS.run("jay_feldman", self.SITEMAP, "example.com",
                              _fetch=fake_fetch, _resolve=lambda s, e: {"doi": "x"},
                              _acquire=lambda r, f, s: True)
        self.assertEqual(result["fetch_failures"], 1)
        self.assertEqual(result["pages_crawled"], 2)
        self.assertEqual(result["acquired"], 1)  # article-two's citation still went through

    def test_limit_caps_the_number_of_pages_crawled(self):
        fetched = []

        def fake_fetch(url):
            fetched.append(url)
            return ""

        with patch.object(FP, "log_failed"):
            result = FRS.run("jay_feldman", self.SITEMAP, "example.com", limit=1, _fetch=fake_fetch)
        self.assertEqual(result["pages_crawled"], 1)
        self.assertEqual(len(fetched), 1)

    def test_no_citations_found_acquires_nothing(self):
        def fake_fetch(url):
            return "<p>no links here</p>"
        result = FRS.run("jay_feldman", self.SITEMAP, "example.com", _fetch=fake_fetch)
        self.assertEqual(result["citations_found"], 0)
        self.assertEqual(result["acquired"], 0)


if __name__ == "__main__":
    unittest.main()
