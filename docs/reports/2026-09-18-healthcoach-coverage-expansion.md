# HealthCoach Evidence Coverage Expansion

## Result

The final gated audit is complete, with two honest whole-food gaps preserved:

| Domain | Targets | STRONG | WEAK | NONE |
|---|---:|---:|---:|---:|
| Whole foods | 346 | 344 | 2 | 0 |
| Workout | 16 | 16 | 0 | 0 |
| Lifestyle | 11 | 11 | 0 | 0 |

`coverage_audit.py --strict` exits `1` because `saffron_food` and `cilantro` each have one
qualifying A/B human-food source after candidate-topic and ordinary-food exposure gates.

## What changed

- Added a conservative, machine-readable audit. `STRONG` requires two distinct A/B human-relevant sources, deduplicated by DOI or source path, with domain-specific dietary, exercise, or lifestyle exposure signals.
- Expanded workout/lifestyle acquisition routes, including heat acclimatization and sedentary behavior, with focused human queries and open-access seeds.
- Added explicit whole-food evidence families for fruit, vegetables, grains, legumes, nuts/seeds, animal protein, seafood, sea vegetables, dairy/fermented foods/fats, and herbs/spices/cocoa.
- Expanded food routing so varieties and cuts retain their own route and can use a declared parent-family route only through explicit aliases. This is labeled family-level evidence; it is not treated as a direct cultivar or cut trial.
- Versioned `food_evidence.json` records with a route signature so changed routing cannot silently reuse stale evidence.
- Removed the ability for citation metadata or USDA nutrition rows to promote local `NONE`/`WEAK` full-text coverage to `STRONG`.

## Acquisition status after the final resumable pull

- The configured fetcher attempted all 363 topic folders in minimum-quota mode, then ran
  targeted fallback searches for the remaining exact-food gaps.
- The local corpus now contains 5,866 PDFs. Newly acquired PDFs were incrementally ingested
  into LanceDB and the food evidence artifact was force-refreshed afterwards.
- Three exact-food folders remain empty after normal, provider-widening, and targeted legal-OA
  attempts: `limes`, `turkey`, and `beef_heart`.
- Five additional exact-food folders remain below their two-PDF minimum: `onions`, `farro`,
  `gelatin_broth`, `mackerel`, and `pasteurized_dairy`. The remaining below-quota
  folders are supplement/gray-market or drug topics where the configured OA providers were
  exhausted. These are acquisition gaps, not silently promoted evidence.

The selector remains fail-closed for the two weak foods. Explicit family routes can support
investigation where applicable, but family-level coverage is not direct cultivar, cut, or
item-trial evidence and cannot promote these two records without qualifying passages.

## Verification

Fresh verification commands:

```bash
cd ~/GitHub/HealthCoach/rag
./.venv/bin/python -m unittest discover -p 'test_*.py'
./.venv/bin/python coverage_audit.py --strict --json-out /tmp/healthcoach-coverage.json
cd ../papers
../rag/.venv/bin/python fetch_papers.py --selftest
```

The complete suite passed with 575 tests. The strict report is generated from the indexed full-text rows, not from the food citation workbook alone.

## Interpretation

This is a retrieval-coverage result, not a claim that every food, workout, or lifestyle behavior has the same health effect or is appropriate for every person. The existing safety gates, evidence grades, personal-context requirements, and fail-closed behavior remain in place. A `STRONG` route means the system has enough qualifying source coverage to investigate the item; it does not authorize a medical recommendation by itself.
