# HealthCoach — Simple Guide

HealthCoach is a local personal health operating system: **plan -> execute -> log -> adjust**.
Start with **Today** for weekly choices, workouts, steps, and a short daily log.
The full `HEALTHCOACH_REPORT.md` remains an explanation and research archive, not the daily front door.

## Choose, Plan, And Export

The home dashboard now has direct controls: **`f` Foods, `g` Peptides/Gray Market,
`n` Nootropics, `s` Supplements, `m` Meals, `t` Training, `c` Changes, `e` Export**.
Enter opens Your Week, including Other Items and separate **All / You** screening grades.

Selections and plan edits require a concrete purpose, personal reason, review trigger, and
supporting research/resource. Prior choices marked `[?]` need a weekly justification with
`j`; unsupported items remain browsable. A grade alone never creates a use protocol.

Choose foods with Space, open Meals, and press `b` to build dated portions. `c` sets meal
times; `e` moves/resizes a portion. Training supports daily session/time/minute edits and
an editable 10,000-step starting target. `s` **inside Your Week** saves after a reason and
`SAVE` confirmation; it is distinct from the home `s` shortcut for Supplements.

Export individual sections or the entire report to unique private Markdown files without
regenerating the report. See [Weekly Workspace](../docs/WEEKLY_WORKSPACE.md) for the full
workflow, evidence limits, and commands.

## Today And Trust

- **Today:** read-only, no model loading or automatic plan changes. Only explicitly personal,
  adopted, reported-current items that pass the shared admission screen appear in the current
  list. They are not inferred daily doses. Other reported use remains visible under review.
- **Log today:** completion/skipped/unknown, optional activity minutes, recovery, and a factual
  note. Blank preserves the previous value; `?` makes it unknown; `s` explicitly saves. The
  ignored `.healthcoach/daily_log.json` does not overwrite Bevel weekly packages.
- **Research:** the full supplement, peptide, nootropic, and gray-market catalog stays reachable.
  Gray-market candidates now use the same bounded, source-linked deep-review path; lack of
  human coverage does not erase labelled mechanistic research.
- **Evidence:** topic/relevance gates and paper deduplication run before generation. Generated
  research claims require known source IDs and matching evidence quotes. Missing or failed
  scoring withholds the answer instead of falling back to unscored nearest neighbours.
- **Safety:** one deterministic admission policy gates new adoption, research suggestions,
  current-week rendering, and symptom recommendations. Existing reported use/doses are not
  deleted or automatically changed. Explicit severe symptoms take an urgent-warning path.

These checks are not medical clearance or a semantic entailment guarantee. Existing authored
report modules and saved reports are not retroactively validated. See
[the implementation contract and limits](../docs/TODAY_AND_TRUST.md).

## What the idea means

Health advice is often scattered across videos, product pages, studies, and unrelated AI
answers. HealthCoach brings the user's schedule, goals, training, food choices, current stack,
safety concerns, and shopping options into one assessment. It then searches the local paper
library for each selected topic, removes duplicate or off-topic results, and records how strong
and personally relevant the remaining evidence is.

```text
plan -> execute -> log -> review evidence -> explicitly adjust
```

This matters because selecting something does not make it a recommendation. A supplement,
peptide, food, or lifestyle claim can be kept, marked optional, sent to clinician review, or
rejected. The final document shows the answer, the practical plan, the evidence strength, the
coverage gaps, and the references together. That makes it easier to inspect, update, and hand
to another person or AI without losing the reasoning behind the plan.

It is still a research and planning tool—not a diagnosis or a guarantee of correctness. The
library and retrieval results must be good, so missing and weak coverage remain visible.

## Run HealthCoach

Open Terminal and paste:

```bash
cd ~/GitHub/HealthCoach/rag
./hc
```

That is the only command a normal user needs. `./hc` keeps the Mac awake correctly and opens
one keyboard dashboard. It does not use the unsupported `caffeinate --help` or `--t` syntax.
The dashboard opens Today. Plan, Log/Review, Research, and Maintenance preserve the existing
workflows without showing every research and maintenance command on the home screen.

- Arrow keys choose a dashboard action.
- Space or Enter opens it.
- Tab, Left/Right, or `1`-`5` changes area; `/` searches all actions.
- `l` logs today; `w` opens weekly review; PgUp/PgDn scrolls Today details.
- `v` expands reported-use review details; `r` refreshes saved state.
- `?` explains the current workflow.
- Esc goes back; `q` exits. Explicitly saved logs and decisions remain saved.

HealthCoach resumes intake answers embedded inside `HEALTHCOACH_REPORT.md`. `START OVER FROM
GROUND ZERO` requires typing `RESET`; even then, the existing report is not replaced until the
new generation actually begins successfully.

`LOG THE COMPLETED WEEK` is a three-page keyboard grid. Tab moves through Training, Recovery,
and Fuel; arrows choose a day and field; Space cycles fixed answers; Enter edits a number; and
`s` saves. Blank values remain `UNKNOWN`. Workout HR and device calories are stored with their
origin for trend review and are never converted into an exact amount of food to “eat back.”
The next report generation compares up to three stored weeks and adjusts the seven-day food
rotation only when the weight/execution trend is persistent enough to justify it.

The assessment guides you through ten explained sections: goals, training choices, a visual
weekly calendar, current stack, safety, supplement research, experimental/peptide research,
daily routine and meal count, food/home ideas, and shopping. Each screen tells you why the
question matters. Meals are a one-choice Space selector: 3, 4, or 5. Four is preselected because
the current 165 g Phase A protein target divides into about 41 g per feeding; the report still
checks retrieved meal-distribution evidence and clearly labels the arithmetic as planning.

On the calendar screen, every day already shows the session from the operating week and its
time. Use ↑/↓ to choose a day and Space to cycle its placement:

- `PLAN` keeps the authored time.
- `AM` requests the main session after morning study.
- `PM` uses the 17:00 training window.
- `BOTH` allows easy movement in one window and the single main session in the other; it never
  creates two hard sessions.
- `OFF` records that the session cannot happen and applies that day's skip rule without moving
  it to tomorrow.

Press `1`–`5` to jump directly to a placement, `z` to undo, `r` to reset the week, and `?` for
an explanation. The board labels work/Anki conflicts before you save. A conflict can remain as
a user preference for the evidence check, but HealthCoach will not silently move the fixed
wake, work, Anki, or sleep blocks. The final report stores all seven choices under stable keys,
and the Bevel handoff includes that calendar context.

On `SUPPLEMENTS TO INVESTIGATE`, choose one intake strategy with Space:

- `Whole-food first` uses ordinary foods whenever a meaningful food route exists.
- `Mixed` compares food and isolated products.
- `Products allowed` permits product evaluation but does not bypass evidence or safety checks.

The report distinguishes a real whole-food route from a food that merely contains a related
compound. It also says when no practical whole-food equivalent exists. “No food equivalent”
never means “automatically buy the supplement.” Creatine remains the user's locked 5 g/day
exception, even though meat and fish contain creatine.

- Arrow keys move up and down.
- Space selects or unselects an item.
- `/` searches longer lists.
- `r` returns to that section's complete list.
- Enter continues to the next section.

The most common choices are selected already. HealthCoach asks for at most one short written
explanation, and only when a choice needs clarification for safety or accuracy. A final review
shows what was recorded before research begins; choose `generate`, `restart`, or `cancel`.

Current-use facts and doses must come from the user's recorded context, not catalog labels
such as "current prescription". Historical authored templates may still contain example
amounts; Today does not infer a dose from them.
Every other checked choice is saved under a stable internal name and validated before research
starts. The one report includes a `HARD-DEFINED SELECTION LOCK` table showing exactly what was
locked, selected, or left unselected. HealthCoach does not guess personal answers that the user
did not choose.

The food-review page locks the complete named whole-food research library: the original beets,
oregano, saffron, kimchi, tamarind, blueberries, garlic, ginger, honey, cinnamon, and turmeric,
plus the requested fruits, vegetables, grains, pulses, nuts, seeds, dairy, eggs, poultry, meat,
organs, fish, culinary fats, herbs, seaweed, and fermented foods. Locked here means “must be
checked and shown in the evidence ledger,” not “must be eaten.” Food selections separately
define which items may appear in the adaptive menu. The report keeps normal culinary food
separate from oils, extracts, capsules, or standardized study forms.

## Read the result

When the program finishes, browse it by chapter and logical page:

```bash
./hc-report
```

- Arrow keys choose a chapter or page.
- `/` searches chapter titles and the full paragraph text.
- Space or Enter opens the highlighted page.
- Inside a page, Space scrolls to the next screen.
- `[` and `]` move to the previous or next chapter.
- `b` returns to the index and `q` quits.

You can also search or print a page without opening the interactive navigator:

```bash
./hc-report --search "raw milk"
./hc-report --page 017
```

To open the complete static report in a Mac application:

```bash
open HEALTHCOACH_REPORT.md
```

Or read it neatly inside Terminal:

```bash
glow -p HEALTHCOACH_REPORT.md
```

Every run replaces the same report. No timestamped reports, JSON side files, or additional log
documents are created. The navigator only reads that report; it does not make another copy.

## Weekly exchange with Bevel Intelligence

HealthCoach and Bevel can now pass the week back and forth. HealthCoach supplies the locked plan;
Bevel supplies the data it can actually see; HealthCoach checks the reply against the plan and
local research before returning a verified response. Start with:

```bash
./hc-bevel
```

Use the arrow keys, then press Space or Enter. The numbered choices form one loop.

### First time only

1. Choose `1. INTRODUCE / REFRESH HEALTHCOACH`.
2. Open **Bevel → Intelligence → new chat**, paste, and send.
3. Bevel is asked to create `HealthCoach Operating Context` and a recurring `HealthCoach weekly
   exchange` check-in every Monday at 04:25 for the Monday-through-Sunday week that just ended.
   It can run before the 04:30 wake time; the user does not need to open it during morning light.

### Every week

1. Choose `2. REQUEST WEEKLY PACKAGE`; paste and send the copied prompt in Bevel.
2. Bevel returns a marked JSON package. Copy Bevel's entire reply.
3. Run `./hc-bevel` again and choose `3. IMPORT + VERIFY BEVEL REPLY`. HealthCoach reads the
   clipboard automatically, checks the seven-day dates, data provenance, plausible ranges,
   locked-plan conflicts, and Bevel's health claims against the local RAG sources.
4. HealthCoach stores that verified week in **Part V of the same `HEALTHCOACH_REPORT.md`** and
   replaces the clipboard with a verified return prompt. Paste that return into Bevel.
5. Bevel is instructed to state what it saved, rejected, still does not know, and why.

The Monday time is deliberate: Sunday 18:30 would omit the end of Sunday from a week defined as
Monday 00:00 through Sunday 23:59. The report retains the newest 12 weekly exchanges.
Regenerating the report carries this ledger forward instead of deleting it. No timestamped
weekly file or sidecar JSON is created.
The imported package can contain sensitive health data and is stored locally in the canonical
report; HealthCoach sends nothing back until the user explicitly pastes the verified response.

`OPTIONAL: BUILD BEVEL WORKOUT TEMPLATES` separately copies the exact three lifting sessions for
Bevel's Strength Builder.

Universal Clipboard can carry copied text from a Mac to an iPhone when both devices use the same
Apple Account and Handoff is enabled.

This is a deliberate clipboard handoff, not an invisible account connection. Bevel has no
public chat-import API used by this project. HealthCoach uploads nothing by itself and keeps
`HEALTHCOACH_REPORT.md` as the only generated document.
Completed workouts, steps, sleep, heart rate, and related wearable data should reach Bevel
through the data source configured inside Bevel, such as Apple Health or Garmin. The text handoff
supplies the plan and its rules; the connected device supplies what actually happened.

The same actions are available as direct commands:

```bash
./hc-bevel --mode setup
./hc-bevel --mode weekly
./hc-bevel --mode verify
./hc-bevel --mode workouts
./hc-bevel --mode setup --print
```

After changing the weekly calendar, regenerate the report and run Bevel `setup` once so its
saved context receives the new schedule. Weekly packages then include the calendar overlay.

`verify` normally reads the Bevel response directly from the clipboard. A file or stdin is also
accepted when troubleshooting:

```bash
./hc-bevel --mode verify --input bevel-reply.txt
pbpaste | ./hc-bevel --mode verify --input -
```

Use `setup` again whenever a new HealthCoach report materially changes the plan. Bevel
Intelligence and some related features may depend on the installed Bevel version or subscription.
The workflow follows Bevel's documented support for
[Files and plans](https://help.bevel.health/en/articles/11586881),
[recurring check-ins](https://help.bevel.health/en/articles/12308801),
[written strength-workout creation](https://help.bevel.health/en/articles/11242561), and
[connected device data](https://help.bevel.health/en/articles/10400449).

## What is inside the report

- A Monday-through-Sunday operating plan.
- Training, cardio, steps, recovery, and skipped-workout rules.
- A meal and grocery plan based on all selected stores.
- Coffee, milk, food, supplement, and medication-interaction reviews.
- Apartment, house, light, water, faith, and lifestyle options.
- Supplement and peptide evidence tables.
- Whole-food routes for supplement-like nutrients, with non-equivalent forms clearly marked.
- Safety gates and topics the research does not adequately cover.
- A clickable chapter and logical-page index.
- The questions, recorded answers, and research references used.

## Finding choices quickly

Press `/` when a longer supplement, peptide, food/home, or store list is open. Search for an
item name, such as:

```text
creatine
magnesium
tirzepatide
morning light
Whole Foods
```

Press `r` after selecting an item to return to that section's complete list.

`STORE / MULTI` lets you select Costco, Whole Foods, Sam's Club, H-E-B, Walmart, Sprouts,
Trader Joe's, pharmacies, supplement stores, online stores, and other sourcing options. Choose
every place you are willing to search; Costco is optional.

## Optional commands

Use the longer interview when you want to enter exact doses, dates, mileage, or symptom timing:

```bash
./hc-supplements --detailed-assessment
```

Display the store, food, home, faith, and alternative-health choice names:

```bash
./hc-supplements --list-lifestyle
```

Ask one question without generating the full report:

```bash
python3 coach.py "Does creatine affect sleep?"
python3 coach.py --show "Does creatine affect sleep?"       # also print source passages/DOIs
python3 coach.py --max-tokens 1400 "Give me the benefits, negatives, and description of X"
```

`--max-tokens` (default 700) is worth raising for multi-part questions — a broad "benefits,
negatives, and description" question can get cut off mid-sentence at the default length.
`--k` (default 6) controls how many source chunks get pulled into context; raise it for a
broader question. The answer only speaks from what's actually retrieved from your indexed
papers, tags every claim's evidence grade (A/B = strong, C = weak/preliminary), and says so
plainly instead of guessing when nothing in the library covers a question.

## First-time setup

Only run this if HealthCoach says the Python environment is missing:

```bash
cd ~/GitHub/HealthCoach/rag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `hc-supplements` launcher activates it automatically afterward.

### Set up your own personal files

`profile.txt` and `schedule_inputs.md` hold **your** personal information — they are not
included with the project on purpose. Copy the example templates and fill in your own details:

```bash
cd ~/GitHub/HealthCoach/rag
cp profile.example.txt profile.txt
cp schedule_inputs.example.md schedule_inputs.md
```

Then open each copy in any text editor and replace the bracketed placeholders with your own
real information — occupation, location, training, goals, medications, preferences. Both files
are plain free text; `#` lines are comments and are ignored. Delete anything that doesn't apply
to you. If this repo is ever shared with someone else or pushed somewhere they can see it, do
not share your filled-in `profile.txt` or `schedule_inputs.md` — they can contain sensitive
health information. The `.example` versions are safe to share; your personal copies are not.

## Updating the research

Creating a new report does not require downloading the research again. In the dashboard, choose
one of the `REFRESH ... SOURCES` actions only when you intentionally want newer or broader papers.
The updater appends only newly found source paths to the index, then checks retrieval.

For maintainers, the equivalent low-level full-library commands are:

```bash
cd ~/GitHub/HealthCoach/papers
caffeinate -i env ABOOST=1 python3 fetch_papers.py

cd ../rag
source .venv/bin/activate
python3 ingest.py --incremental
python3 test_retrieval.py
```

Use plain `python3 ingest.py` for an intentional full rebuild after deleting or replacing PDFs.
Let either mode finish before generating another report.

> **A full re-ingest destroys the safety-control plane. Re-apply it afterwards.**
>
> `python3 ingest.py` without `--incremental` does `drop_table` + `create_table`, and the
> new table has none of the five control columns (`lane`, `personal`, `quarantined`,
> `quarantine_reason`, `allow_c`). Every quarantine flag and lane assignment is silently
> gone, and the coach's retrieval filter then has nothing to filter on. `--incremental`
> keeps the existing table and is unaffected.
>
> After **any** full re-ingest, run these four in order from `rag/`, with the venv active:
>
> ```bash
> python3 -m rag_control.schema_migration                    # re-add the 5 control columns
> python3 -m rag_control.apply_lane_map                      # re-assign lanes from lane_map.json
> python3 -m rag_control.ingest_gold_pack --pack-dir <dir>   # re-insert the personal gold-pack rows
> python3 quarantine_scan.py                                 # re-flag quarantined rows (--dry-run to preview)
> ```
>
> Order matters: `apply_lane_map.py` and `ingest_gold_pack.py` both write columns that
> `schema_migration` has to have created first, and `quarantine_scan.py` filters on
> `personal = false`, so the gold-pack rows must already be tagged before it runs or it
> will quarantine hand-curated personal rows. Re-run
> `python3 -m rag_control.eval_run` afterwards to confirm the pipeline is still green.

Changing assessment choices, locking selections, changing stores, or generating another report
does **not** require a source pull. Those actions reuse the indexed library already on the Mac.

### Refresh the complete locked food library

The focused updater searches the eleven original foods plus every requested fruit, vegetable,
grain, pulse, nut, seed, dairy food, egg, poultry/meat/organ food, fish, culinary fat, herb,
seaweed, and fermented food. It attempts a dedicated source folder for all 116 entries. Missing
legal open-access or direct human evidence stays visible as a coverage gap.

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-whole-foods
```

After that finishes, return to the one dashboard and rebuild the report:

```bash
./hc
```

You do not need to refresh again for every report. Repeat it only when intentionally updating
the research library.

### Refresh the five focus/nootropic topics

ALCAR, citicoline, uridine, Noopept, and bromantane have a focused updater. It downloads only
legal open-access material, rebuilds the local search index, and runs the retrieval check:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-nootropics
```

Then return to the dashboard and rebuild the one canonical report:

```bash
./hc
```

Selection asks HealthCoach to investigate an item; it does not automatically add it to the
stack. Noopept and bromantane stay in the peptide/gray-market research screen and never receive
a personal-use protocol.

### Optional experimental-drug evidence screen

The `PEPTIDE / GRAY-MARKET RESEARCH` page now starts with one research-boundary choice:

- Keep `Approved medicines and ordinary supplements only` for the normal conservative report.
- Choose `Research-only broad scan` if you want HealthCoach to check every configured
  experimental/unapproved topic and surface the ones with at least two unique candidate-folder
  A/B sources containing human-participant and intervention/exposure signals. This ranks source
  coverage only; it does not decide use.

The second choice expands **research**, not permission to use a drug. A topic can have promising
human results and still fail on adverse effects, interactions, product identity, manufacturing
quality, sport rules, or applicability to this user. Chemistry and biology are used to flag
receptor, CYP/transporter, cardiac, glucose, growth, liver/kidney, and other possible overlaps.
They cannot prove two products are safe together. Without direct human interaction/co-use data,
the compatibility field remains `UNKNOWN / NOT VERIFIED`; the selected row still remains visible.

Use **DEEP INTAKE / RANK / ADD / DECIDE / INSPECT** from `./hc` for the private durable ledger.
The progressive intake confirms old facts instead of trusting them, records ordered goals and
context flags, captures current items and practical preferences, then asks candidate-specific
follow-ups after the full-catalog scan. Each selected or typed item keeps separate reasons,
coverage, direction, applicability, safety, regulatory/sport/sourcing annotations, system
suggestion, and user decision. `NONE` emits `WATCH` rather than disappearing. Only `adopt` or
`use_status=in_use` can place an item on the week overlay, and no dose appears unless supplied by
the user.

Recommended dashboard sequence:

1. Open **DEEP INTAKE / RANK / ADD / DECIDE / INSPECT** and choose `deep_intake`.
2. Confirm baseline facts, ordered goals, context flags, current items, and sort preferences.
3. Open **START / UPDATE PLAN + RUN FULL RANKING** to scan the complete configured catalog.
4. Optionally answer the capped candidate-specific follow-ups produced after retrieval.
5. Inspect the two full-catalog orders and explicitly decide `watch`, `adopt`, or `reject`.

The searchable named-item list includes the configured incretins, peptides, research drugs, and
gray nootropics. Press `/` and type part of a name instead of scrolling through the full list.

### candidate_manager.py from the command line

Every action under **DEEP INTAKE / RANK / ADD / DECIDE / INSPECT** also works as a direct
command, which is faster once you know what you're looking for:

```bash
cd ~/GitHub/HealthCoach/rag
source .venv/bin/activate

python3 candidate_manager.py matrix                                # full table
python3 candidate_manager.py matrix --decision watch                # only items marked "watch"
python3 candidate_manager.py matrix --decision undecided --class gray_market
python3 candidate_manager.py decide creatine_monohydrate adopt      # record your decision
python3 candidate_manager.py inspect creatine_monohydrate           # one item's full evidence
python3 candidate_manager.py edit creatine_monohydrate --reasons strength,sleep
```

`--decision` accepts `undecided`, `watch`, `adopt`, or `reject`; `--class` accepts `supplement`,
`peptide`, `nootropic`, `gray_market`, or `food`.

`review` opens a full-screen checklist for bulk decisions — **Space** toggles a row, **Enter**
immediately sets every checked row's decision to `adopt` (unchecked rows are left as they were):

```bash
python3 candidate_manager.py review --class gray_market --all
```

Be deliberate with Enter — it commits right away for everything currently checked. Leaving off
`--all` shows only `undecided` rows by default.

### Adding a compound that isn't in the catalog yet

If something you want evaluated isn't in the built-in list, add it as a typed candidate, give
it a dedicated evidence folder, and pull sources for just that one topic:

```bash
cd ~/GitHub/HealthCoach/rag
source .venv/bin/activate

# 1. Add it to the private ledger
python3 candidate_manager.py add --name "Compound name" --class gray_market --reasons fat_loss

# 2. Point it at a dedicated evidence folder (use the same id add_candidate printed)
python3 candidate_manager.py edit compound_name --folder 08_peptides_gray/compound_name
```

Then add a matching topic to `papers/fetch_papers.py`'s `TOPICS` list (a maintainer/code task —
ask an AI assistant working in this repo to do it, or copy an existing entry near the bottom of
the file as a template), and pull sources for just that topic:

```bash
cd ~/GitHub/HealthCoach/papers
source ../rag/.venv/bin/activate
python3 fetch_papers.py --topic 08_peptides_gray/compound_name

cd ../rag
python3 ingest.py --incremental
python3 candidate_manager.py inspect compound_name
```

`OA exhausted at N / min M` in the fetch output is a normal outcome, not an error — it means
there simply isn't more legally-downloadable open-access literature to find for that topic yet.

To search for additional A/B source candidates across every configured experimental folder,
rebuild the index, and check retrieval in one resumable command (the report applies the separate
human/intervention gate afterward):

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-experimental
```

This source refresh can take a while. It is not required every time a report is generated.
Afterward, run `caffeinate -i ./hc-supplements` and choose the broad scan in the assessment.

For an automated non-interactive evidence-only full-catalog check (no model-written deep cards):

```bash
./hc-supplements --non-interactive --experimental-policy screen_strong_human --evidence-only
```

`--evidence-only` skips legacy model-written catalog prose. The structured candidate matrix and
fixed cards still emit coverage and unknown fields without guessing that a high source count means
a positive or personally applicable result.

## Morning Bible and Jesus study

“Bible study, prayer, and learning about Jesus” is preselected under `HOME / FAITH`. When kept,
the report divides the existing morning learning hour without changing wake time or work:

```text
04:50–05:15  Scripture/Jesus study: read, write one observation, pray
05:15–05:50  Anki or technical study
05:50        Breakfast
06:00        Work Monday–Thursday
```

The report includes an eight-week reading path, official church-document links, early Christian
texts, and non-Christian historical references. It keeps history, doctrine, and personal faith
practice labeled separately.

## Important limits

- HealthCoach is an evidence and planning tool, not a doctor.
- Selecting something asks the program to evaluate it; selection is not approval.
- Prescription changes and unapproved-drug protocols are not generated.
- Missing or animal-only evidence is labeled instead of being presented as proven.
- The program may recommend discussing a symptom, medication, or laboratory result with a
  qualified clinician.

For the complete engineering explanation, read
[`docs/PROJECT_AI_HANDOFF.md`](../docs/PROJECT_AI_HANDOFF.md).
