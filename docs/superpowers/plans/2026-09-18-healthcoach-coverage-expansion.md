# HealthCoach Evidence Coverage Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (inline execution is being used here). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand and verify strong evidence coverage for all workout, lifestyle, and whole-food selector pathways without counting weak, unrelated, or metadata-only sources.

**Architecture:** Add one pure, offline coverage-audit module that consumes catalog/topic definitions and indexed rows. Fix food candidates so their actual per-food folders, declared parent-family folders, and aliases are explicit. Use the existing legal-OA acquisition engine for missing A/B sources, then incrementally ingest and refresh food evidence through a versioned command. The application continues to fail closed when a target remains below strong coverage.

**Tech Stack:** Python 3 stdlib, unittest, LanceDB, existing SentenceTransformers retrieval, Europe PMC/OpenAlex/Semantic Scholar OA acquisition, JSON evidence artifacts.

**Spec:** `docs/superpowers/specs/2026-09-18-healthcoach-coverage-expansion.md`

## Global Constraints

- “Strong” requires two distinct A/B human-relevant sources; curated citation metadata and USDA nutrition rows cannot raise evidence coverage by themselves.
- Food parent-family reuse is explicit and alias-gated; no broad folder match may bypass `hit_is_on_topic()` or `whole_food_human_hit()`.
- Workout/lifestyle and food acquisition uses existing legal OA providers and the existing grade policy.
- No safety-router, deny-lane, or personal-row behavior may be loosened.
- Existing user-authored untracked files `.continues-handoff.md` and `HEALTHCOACH_DEMO_COPY.md` must remain untouched.
- Every production change follows red-green TDD and is verified with a fresh command before being reported as complete.

### Task 1: Add the offline coverage model and baseline audit

**Files:**
- Create: `rag/coverage_audit.py`
- Create: `rag/test_coverage_audit.py`
- Modify: `rag/README.md`

**Interfaces:**
- `source_key(row: Mapping[str, Any]) -> str`
- `is_human_exposure(row: Mapping[str, Any], domain: str) -> bool`
- `count_strong_sources(rows: Sequence[Mapping[str, Any]], domain: str) -> dict[str, Any]`
- `audit_food_rows(catalog, rows) -> dict[str, Any]`
- `audit_topic_rows(topics, rows, domains) -> dict[str, Any]`
- `run_audit(...) -> dict[str, Any]`
- CLI: `python3 coverage_audit.py --json-out PATH [--strict]`

- [ ] Write tests first for DOI/path deduplication, A/B filtering, human dietary/exercise/lifestyle signals, two-source strong status, and strict non-zero failure.
- [ ] Run `./.venv/bin/python -m unittest rag.test_coverage_audit -v` and observe expected failures for missing module/functions.
- [ ] Implement the pure counting functions with conservative domain-specific signal checks.
- [ ] Add a CLI that loads the existing LanceDB table and current topic/catalog definitions, writes a JSON report, and exits 1 when configured targets are not strong.
- [ ] Run the focused tests and an unrestricted baseline audit; save the baseline counts in the final report.
- [ ] Update the README with the exact audit command and meaning of each status.
- [ ] Commit as `feat: add strict evidence coverage audit`.

### Task 2: Correct food-family routing and stale evidence invalidation

**Files:**
- Modify: `rag/supplement_audit.py`
- Modify: `rag/food_evidence.py`
- Create or modify: `rag/test_food_evidence.py`

**Interfaces:**
- `food_evidence_folders(key: str, group_folder: str) -> tuple[str, ...]`
- `food_evidence_aliases(key: str, display_name: str) -> tuple[str, ...]`
- `FOOD_EVIDENCE_SCHEMA_VERSION: str`
- `food_evidence.py --refresh` recomputes records whose schema version or route signature changed.

- [ ] Write failing tests proving an expanded food retains its per-key folder plus its declared parent group/family, variants match parent-food text only through explicit aliases, unrelated food text does not match, and old evidence records are refreshed after a route signature change.
- [ ] Run the focused tests and confirm they fail against the current one-folder/no-version behavior.
- [ ] Implement the smallest routing change: preserve the actual per-key path, add only declared family folders, and add explicit aliases for varieties/cuts.
- [ ] Add a schema/route signature to `food_evidence.json` records and a `--refresh` option that invalidates stale records without deleting the artifact.
- [ ] Run focused tests plus the existing food/catalog tests.
- [ ] Commit as `fix: route food evidence by explicit family`.

### Task 3: Expand workout and lifestyle acquisition coverage

**Files:**
- Modify: `papers/fetch_papers.py`
- Create: `papers/test_coverage_topics.py`
- Modify: `rag/README.md`

**Interfaces:**
- Add topic definitions for every baseline workout/lifestyle gap identified by `coverage_audit.py`, including at minimum heat acclimatization and any topic with fewer than two qualifying A/B human sources.
- Keep topic folder names stable so the existing ingest table and retrieval filters remain compatible.

- [ ] Write offline tests that assert each workout/lifestyle domain has a topic, each topic has at least two focused queries, and no new topic points to a forbidden or refusal folder.
- [ ] Run the tests and observe the expected missing-topic failures for the baseline gaps.
- [ ] Add focused queries/seeds using authoritative human systematic reviews, guidelines, and randomized trials; do not lower grade thresholds or admit C-grade rows.
- [ ] Run `python3 fetch_papers.py --selftest` and targeted acquisition with the existing resumable engine.
- [ ] Re-run `coverage_audit.py` for workout/lifestyle and run the relevant retrieval tests.
- [ ] Commit as `feat: expand workout and lifestyle evidence topics`.

### Task 4: Expand all-food evidence families through legal OA sources

**Files:**
- Modify: `papers/fetch_papers.py`
- Create: `papers/test_food_topic_coverage.py`
- Modify: `rag/README.md`

**Interfaces:**
- Every `WHOLE_FOOD_CATALOG` key maps to an explicit source family and query terms; no key is silently omitted.
- Food topic acquisition remains idempotent and writes to the existing `papers/01_food_inflammation/...` taxonomy.

- [ ] Write tests that compare the food catalog keys with food acquisition keys, require non-empty search terms, and reject accidental supplement-only queries for whole foods.
- [ ] Run them and capture any catalog/topic mismatch.
- [ ] Add or extend family topics for fruit, vegetables, grains, legumes, nuts/seeds, animal protein, seafood, fermented dairy/vegetables, culinary fats, herbs/spices, and sea vegetables; route cultivar/cut entries to declared parents.
- [ ] Run the acquisition in resumable shards, beginning with families below the audit’s strong threshold; keep the existing A/B and human/dietary gates intact.
- [ ] Incrementally ingest only newly downloaded PDFs and run `food_evidence.py --refresh`.
- [ ] Run the strict audit and inspect every residual gap rather than relabeling it.
- [ ] Commit as `feat: expand whole-food evidence families`.

### Task 5: End-to-end verification and coverage report

**Files:**
- Modify: `rag/README.md`
- Create: `docs/reports/2026-09-18-healthcoach-coverage-expansion.md`

- [ ] Run the complete Python test suite.
- [ ] Run the strict coverage audit against the rebuilt table and refreshed food evidence.
- [ ] Verify the web food/workout/lifestyle pathways still load and preserve `NONE`/`WEAK` behavior for intentionally unsupported rows.
- [ ] Record before/after counts, source counts, commands, and any honest residual gaps in the report.
- [ ] Review `git diff --check`, `git status`, and the untracked-file guard.
- [ ] Commit as `docs: report evidence coverage expansion` only after fresh verification.
