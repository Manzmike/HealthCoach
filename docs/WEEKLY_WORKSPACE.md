# Weekly Workspace

Run `./hc` from `rag/`. The home screen shows weekly food/item choices, today's workout,
and logged steps against the editable starting target of 10,000. The full catalog is
available without launching a model or regenerating the report.

## Direct Home Controls

| Key | Opens |
|---|---|
| Enter | Your Week: selections, grades, meals, training, and changes |
| `f` | Food selections |
| `g` | Peptides / Gray Market |
| `n` | Nootropics, including cognition-related supplements |
| `s` | Supplements |
| `m` | Meal plan: what, how much, and when |
| `t` | Training and step targets |
| `c` | Saved changes and reasons |
| `e` | Export menu, including the entire report |
| `l` | Daily facts, including completed steps |
| `w` | Existing completed-week check-in |

Gray-market nootropics appear in both relevant browsing areas without being duplicated
in the underlying selection. Safety review does not hide an item or erase its research.

## Choose And Justify

Inside Your Week, `1`-`9` opens Week, Foods, Peptides/Gray, Nootropics, Supplements,
Other, Meals, Training, and Changes. `[` and `]` move between dated weeks after saving
or discarding a draft. Arrow keys move through items; `/` searches names/aliases; `p`
filters to selected items; `o` switches between overall and personal-fit ordering.

Each item has two separate screening grades:

- **All:** overall evidence signal from the available cached evaluation or an explicit
  local research refresh. Changing personal goals does not change this grade.
- **You:** fit to recorded goals and catalog reason tags, adjusted for recorded harm,
  blockers, and available applicability information. Missing context remains `?`.

These are heuristics, not clinical GRADE certainty or approval ratings. Cached evaluations
may be old or imperfect. Enter opens the grade explanation, source trail, actual-use
record, policy caveats, and review rationale. `r` explicitly retrieves and refreshes an
item's local research; it never silently changes selections or routines.

Space selects an item only after a **hard reason** is recorded:

1. Choose a source/resource actually offered for the item.
2. State the specific purpose it supports.
3. Explain why that support fits the user's context.
4. State a review date/condition or result that would justify changing course.

The backend requires the structured fields and source identity on save. Short placeholders
and fabricated source IDs are rejected. This validates the record and its provenance,
not semantic entailment of a human-written rationale. Choosing a real citation does not
by itself prove that the source supports the proposed interpretation.

Food composition can be justified with its mapped USDA FoodData Central resource even
when outcome research is absent. That resource supports nutrient arithmetic, not claims
that the food treats disease. Authored planning references support practical planning
choices, not proof that a specific clock time, workout, or step count is optimal.

Prior assessment/ledger choices are shown in an unsaved draft. A `[?]` means the old
choice needs a source-linked weekly reason: press `j` to justify it or Space to unselect
it. `[x]` means a justification is present. Unsupported items remain browsable, but cannot
become justified weekly selections until usable support is available.

## Meals

Choose foods, then open `7 Meals` and press `b` to construct a draft. Actual use does not
have to be marked `in_use` to plan future meals. Missing biometrics are shown rather than
invented; `i` opens the existing goals/biometrics intake after saving/discarding edits.

Weekly portion quantities use the existing energy/protein estimator and nutrition data.
Recorded or matching catalog goals help prioritize food allocation. Portions are spread
across dated meal slots, with per-food daily planning ceilings, recorded weekly caps,
and shared red-meat/liver caps. Foods that cannot be placed remain visible with a reason.
Target estimates and actually placed totals are shown separately; deficits are not hidden.

- `c` sets your Breakfast, Lunch, Dinner, and Snack clock times; unset times stay unset.
- `e` moves or resizes a selected portion; zero removes that portion, not the food choice.
- Enter shows the portion basis, practical-placement reason, and available source trail.
- Changes to foods or intake mark previous meals stale; rebuild explicitly with `b`.

Food portions/macros remain estimates using the mapped food state and category portions.
Meal-slot distribution is a transparent planning heuristic, not an optimized recipe system
or evidence that the selected timing improves the study outcome. Changes require a
supporting planning/nutrition resource and concrete reason.

## Training And Other Items

Open `8 Training` to edit a specific day's session, start time, minutes, and step target
with `e`. `t` changes the seven-day step target. `j` records a supporting basis for a
previously saved template. The requested starting target is 10,000 steps; logged steps
are independent facts, not inferred completion or exercise calories.

Existing calendar constraints stay visible. The editor does not automatically resolve
schedule conflicts, add missed sessions, or guarantee safe training progression. Every
new workout/target change needs a purpose, personal rationale, source/resource, and review
trigger. Steps can be recorded in the daily log without rewriting Bevel weekly packages.

For a selected supplement, peptide/gray item, nootropic, or other item, `e` records an
existing routine in the user's own words only if actual use is already recorded. Otherwise
it records a research/review note. Dates can be selected for these records. No dose,
initiation protocol, taper, or clinician clearance is inferred from a high grade or checkbox.

## Save And Export

`s` inside the weekly workspace asks for the change reason and explicit `SAVE` confirmation.
The save records before/after state and preserves other weeks. A stale same-week editor
cannot overwrite another session's changes. `u` discards the draft; quitting with edits
requires `DISCARD`. Selection, adoption, actual use, and completed activity remain distinct.

Use `e` on the **home dashboard** for 12 export choices: overview, food choices, gray-market
items, nootropics, supplements, other items, meals, training/steps, changes, sources, complete
current week, or current week plus the entire existing report. `x` opens the same exporter
from a saved weekly workspace.

Exports are explicit, private local Markdown files in `rag/.healthcoach/exports/`. Each
filename is unique; nothing is overwritten, uploaded, or copied to the clipboard. The full
report export includes the original report as an explicitly labelled archive, not a silently
regenerated document. Exporting an unsaved imported draft labels its unconfirmed status.

Direct commands from `rag/`:

```bash
./hc --action food-review
./hc --action gray-review
./hc --action food-plan
./hc --action workouts
./hc --action export
.venv/bin/python plan_export.py --section current-plan
.venv/bin/python plan_export.py --section full-report
```

Weekly state, rationale snapshots, and explicit research-refresh results live in the ignored
`.healthcoach/week_plan.json`. This does not rewrite the existing report or candidate ledger.
The original research/adoption tools remain available under Your Tracked Items and Research.

Run offline regression tests from the repository root:

```bash
rag/.venv/bin/python -m unittest discover -s rag -p 'test_*.py'
```
