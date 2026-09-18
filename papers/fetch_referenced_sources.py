#!/usr/bin/env python3
"""
FETCH REFERENCED SOURCES -- pull the actual cited studies out of a third-
party commentator's articles, never their own commentary text. Filed in a
separate folder named after the source they came from (referenced_by_<slug>/)
so every citation's Reference line makes that origin visible, distinct from
this project's own curated topic folders.

  cd ~/GitHub/HealthCoach/papers
  python3 fetch_referenced_sources.py --source jay_feldman \
      --sitemap https://www.jayfeldmanwellness.com/sitemap-1.xml \
      --url-pattern jayfeldmanwellness.com

Crawls every article page on the given site (respecting robots.txt is the
caller's job -- check it before pointing this at a new site), extracts
PubMed/PMC/DOI links out of the raw HTML, resolves each to a real paper
record via Europe PMC, and files it through the exact same acquire() path
as any other topic in fetch_papers.py -- same grading (grade_of(), from the
paper's own publication type, not who cited it), same DOI dedup, same PPR
preprint cap. The referenced_by_<slug> folder is NOT added to REFUSAL, so
it gets no allow_c exemption: a genuinely strong (A/B) cited paper is
retrievable and stands on its own merits like any other evidence; a weak
or preliminary (C) one a commentator leaned on stays gated behind the same
default relevance filter as any other grade-C paper in this corpus. This
script never ingests the commentator's own writing, only what they cite.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import fetch_papers as FP  # noqa: E402

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_SKIP_SLUGS = ("about-jay", "about", "contact", "disclaimer", "privacy-policy", "terms",
               "articles", "health-topics", "calendly-embed-test")

_PUBMED_RE = re.compile(r"ncbi\.nlm\.nih\.gov/pubmed/(\d+)")
_PMC_RE = re.compile(r"ncbi\.nlm\.nih\.gov/pmc/articles/(PMC\d+)")
_DOI_RE = re.compile(r'10\.\d{4,9}/[^\s"\'<>#?]+')


def article_urls_from_sitemap(xml: str, url_pattern: str) -> list[str]:
    """Sitemap <loc> entries under url_pattern whose path is a single
    segment (an article slug), skipping known non-article pages. Takes the
    already-fetched sitemap XML text, not a URL, so this stays offline-
    testable without a network call."""
    out = []
    for u in _LOC_RE.findall(xml):
        if url_pattern not in u:
            continue
        path = u.split(url_pattern, 1)[-1].strip("/")
        if not path or "/" in path:
            continue
        if path.lower() in _SKIP_SLUGS:
            continue
        out.append(u)
    return sorted(set(out))


def extract_citations(html: str) -> set[tuple[str, str]]:
    """(SRC, ext_id) pairs -- SRC in {"MED", "PMC", "DOI"} -- found in the
    page's own outbound links (real citations), never anything parsed out
    of the article's own prose text."""
    found: set[tuple[str, str]] = set()
    for m in _PUBMED_RE.finditer(html):
        found.add(("MED", m.group(1)))
    for m in _PMC_RE.finditer(html):
        found.add(("PMC", m.group(1)))
    for href in re.findall(r'href="(https?://[^"]+)"', html):
        m = _DOI_RE.search(href)
        if m:
            found.add(("DOI", m.group(0).rstrip(".,;)")))
    return found


def _resolve_once(src: str, ext_id: str) -> dict | None:
    if src == "DOI":
        recs = FP.epmc_search("DOI:%s" % ext_id, oa_only=False, page_size=1)
        return recs[0] if recs else None
    rec = FP.hydrate(src, ext_id)
    return rec[0] if rec else None


def resolve(src: str, ext_id: str, *, attempts: int = 3, _sleep=time.sleep) -> dict | None:
    """A real Europe PMC paper record for this citation, or None if it
    can't be resolved there after `attempts` tries. DOI has no EXT_ID/SRC
    pair in EPMC's model (that's PubMed/PMC-specific), so it goes through a
    direct DOI: query instead of hydrate().

    Retries a falsy result, not just an exception: _json() (underneath both
    hydrate() and epmc_search()) swallows a transient network failure into
    an error-shaped dict rather than raising, so a real, resolvable
    citation can come back empty on one attempt. Confirmed live: the same
    22 PMIDs that mostly failed to resolve in one run (17/20 unresolved)
    all resolved cleanly run again moments later -- this is the network
    being unreliable at this volume, not the citations not existing."""
    for attempt in range(attempts):
        result = _resolve_once(src, ext_id)
        if result:
            return result
        if attempt < attempts - 1:
            _sleep(0.5 * (attempt + 1))
    return None


def run(source: str, sitemap_xml: str, url_pattern: str, *, limit: int = 0,
        _fetch=None, _resolve=None, _acquire=None) -> dict:
    """The whole crawl-extract-resolve-acquire pipeline, with every network/
    IO seam injectable so this is fully unit-testable offline. Production
    callers (main()) pass none of the _* overrides and get the real thing."""
    fetch = _fetch or FP._get
    resolve_fn = _resolve or resolve
    acquire_fn = _acquire or FP.acquire
    folder = "referenced_by_%s" % source

    urls = article_urls_from_sitemap(sitemap_xml, url_pattern)
    if limit:
        urls = urls[:limit]

    citations: dict[tuple[str, str], set[str]] = {}
    fetch_failures = 0
    for url in urls:
        try:
            html = fetch(url)
        except Exception:
            fetch_failures += 1
            continue
        for key in extract_citations(html):
            citations.setdefault(key, set()).add(url)

    resolved = unresolved = acquired = 0
    for (src, ext_id), citing_urls in citations.items():
        rec = resolve_fn(src, ext_id)
        if not rec:
            unresolved += 1
            FP.log_failed("- REFERENCE UNRESOLVED | %s:%s | cited by %s" %
                           (src, ext_id, next(iter(citing_urls))))
            continue
        resolved += 1
        if acquire_fn(rec, folder, source):
            acquired += 1

    return {
        "folder": folder,
        "pages_crawled": len(urls),
        "fetch_failures": fetch_failures,
        "citations_found": len(citations),
        "resolved": resolved,
        "unresolved": unresolved,
        "acquired": acquired,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                     help="short slug, e.g. 'jay_feldman' -- used for the folder name and the file-naming slug")
    ap.add_argument("--sitemap", required=True)
    ap.add_argument("--url-pattern", required=True,
                     help="substring identifying this site's own article URLs, e.g. 'jayfeldmanwellness.com'")
    ap.add_argument("--limit", type=int, default=0, help="cap the number of article pages crawled (0 = no cap)")
    a = ap.parse_args()

    FP.init_logs()
    FP.load_seen_from_manifest()

    print("fetching sitemap: %s" % a.sitemap)
    sitemap_xml = FP._get(a.sitemap)
    urls = article_urls_from_sitemap(sitemap_xml, a.url_pattern)
    if a.limit:
        urls = urls[:a.limit]
    print("crawling %d article pages from %s" % (len(urls), a.url_pattern))

    def fetch_with_progress(url):
        # The site itself is unreliable at this crawl volume -- confirmed
        # live (2 of 5 page fetches failed on one real run, succeeded on
        # a re-run moments later) -- so retry a couple of times before
        # counting this page as a real fetch failure.
        for attempt in range(3):
            time.sleep(0.3)
            try:
                return FP._get(url)
            except Exception:
                if attempt == 2:
                    raise

    result = run(a.source, sitemap_xml, a.url_pattern, limit=a.limit, _fetch=fetch_with_progress)
    print("pages crawled: %d (%d fetch failures)" % (result["pages_crawled"], result["fetch_failures"]))
    print("unique citations found: %d (%d resolved, %d unresolved)" %
          (result["citations_found"], result["resolved"], result["unresolved"]))
    FP.count_table()
    print("acquired %d new PDFs into %s/" % (result["acquired"], result["folder"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
