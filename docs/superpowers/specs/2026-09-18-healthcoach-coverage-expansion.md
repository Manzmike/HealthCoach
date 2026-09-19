# HealthCoach Evidence Coverage Expansion

## Goal

Make workout, lifestyle, and whole-food recommendations draw from a measurable, source-quality-gated evidence set. “Strong” means at least two distinct A/B human-relevant sources are available through the same topic route; labels, nutrition-only rows, C-grade papers, and citation metadata alone do not count.

## Scope

- Workout coverage: resistance training, concurrent training, endurance, mobility, injury/load management, recovery, energy availability, and heat acclimatization.
- Lifestyle coverage: sleep, circadian timing/light, sedentary behavior, work stress/burnout, schedule consistency, and behavior change.
- Food coverage: every food in `WHOLE_FOOD_CATALOG`, including the expanded variety/protein/seafood/sea-vegetable entries. Varieties may use an explicitly declared parent-food evidence family when the source studies the parent food rather than a cultivar or cut.
- The selector must never display `STRONG` merely because a food exists in the catalog or has USDA nutrition data.

## Safety and evidence rules

1. A/B means the existing filename-grade policy: systematic review/meta-analysis/guideline/position stand or randomized/clinical trial.
2. Human relevance and dietary/exercise/lifestyle exposure must be checked in extracted text.
3. A source is counted once by DOI or source path.
4. Food varieties and cuts must declare their parent evidence family and aliases; a generic parent source cannot silently satisfy an unrelated food.
5. The audit must report gaps honestly and exit non-zero in strict mode; it must not manufacture or promote evidence.
6. Existing deny/refusal and medical safety gates remain unchanged.

## Deliverables

- A reusable coverage audit with machine-readable JSON and strict exit status.
- Correct food routing, explicit family aliases, and refreshable food evidence generation.
- New/expanded acquisition topics for the identified workout/lifestyle gaps and food families.
- Tests for routing, source-quality counting, strict failure behavior, and stale evidence invalidation.
- A final report showing the before/after counts and any residual gaps.
