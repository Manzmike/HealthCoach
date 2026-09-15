# HealthCoach

📄 **New session, or lost track of a file?** See [`INDEX.md`](INDEX.md) — every doc, log, and
data file in this repo, what it's for, and whether it's safe to touch.

HealthCoach is a local, private personal health operating system built around an
evidence-based decision loop: **plan -> execute -> log -> adjust**. The daily experience
starts with your saved plan and recorded facts; detailed research stays available behind it.

You do not need to understand artificial intelligence, databases, or programming to use it.

**Weekly choices are directly accessible:** `f` Foods, `g` Peptides/Gray Market, `n`
Nootropics, `s` Supplements, `m` Meals, `t` Training, and `e` Export from the home dashboard.
Each new choice needs a source-linked hard reason, not just a high grade. See
[Weekly Workspace](docs/WEEKLY_WORKSPACE.md) for selection, day-by-day editing, and full-report exports.

Launch `rag/hc` for **Today**, then open **Plan**, **Log/Review**, **Research**, or
**Maintenance** as needed. Supplements, peptides, nootropics, and gray-market topics remain
in the research catalog with source-linked reviews. Research visibility and reported use
are not automatic permission to add an item to the active plan.

See [Today And Trust](docs/TODAY_AND_TRUST.md) for the implemented boundaries, commands,
verification workflow, and remaining limitations. This is decision support, not medical clearance.

## The concept

Most health information arrives as disconnected pieces: one workout from a video, one food
rule from a podcast, one supplement claim from a store, and a different answer every time an
AI is asked. Those pieces may ignore the person's schedule, medications, injuries, existing
stack, recovery, or the other recommendations already in the plan.

HealthCoach turns those scattered decisions into one repeatable process:

```text
Your selections
      ↓
Relevant passages from the local research library
      ↓
Duplicate and off-topic checks
      ↓
Evidence strength, personal fit, and safety gates
      ↓
One practical report with the plan and its references
```

The user remains in control. Selecting a food, supplement, peptide, training time, store, or
lifestyle idea means “research and evaluate this,” not “automatically recommend this.” The
compiler can keep it, make it optional, require clinician review, or explain why it should be
skipped.

## Why this is a big deal

- **It connects the decisions.** Training, food, sleep, supplements, medications, shopping,
  schedule, and recovery are evaluated as parts of the same plan instead of separate answers.
- **It shows its work.** The report keeps the questions, recorded answers, evidence grades,
  source folders, and available DOI references beside the conclusions.
- **It admits uncertainty.** Weak, indirect, animal-only, missing, and off-topic evidence is
  labeled instead of silently being turned into confident advice.
- **It produces something usable.** Research is converted into a weekly schedule, shopping
  strategy, meal structure, decision tables, safety gates, and skip rules.
- **It is personal without hiding the basis.** The user selects goals, constraints, current
  products, preferred stores, and topics to investigate; the research still controls health
  claims.
- **It stays manageable.** Today is a small daily view; the organized report remains the
  durable reference, with private decisions and daily facts stored separately.
- **It is easy to navigate.** A keyboard index can search titles or paragraph text and open a
  selected logical page with Space, so a long evidence report does not have to be read linearly.
- **It runs locally after setup.** The paper search, evidence matching, and report generation
  happen on the Mac once the required models are available.

HealthCoach is not automatically correct merely because it cites papers. Its quality still
depends on the papers in the library, retrieval accuracy, source quality, and human review.
That is why the report exposes gaps and references instead of presenting itself as a doctor.

## What you receive

HealthCoach keeps its rendered reference report at:

```text
rag/HEALTHCOACH_REPORT.md
```

Private candidate decisions and explicit daily logs live under `rag/.healthcoach/`.
Opening Today does not rewrite these files or regenerate the report. Existing report,
profile, and schedule files may be tracked by Git; local execution alone does not keep
them out of commits or external shares.

The report contains:

- your weekly training and recovery schedule;
- a practical food plan based on every store you are willing to use;
- supplement recommendations and items to skip;
- safety warnings and questions for a clinician;
- apartment and house options;
- a faith and Bible-study section when selected;
- links and references showing where the information came from; and
- a clickable chapter and page index.

Running HealthCoach again replaces the previous report. It does not create a folder full of
extra reports.

## The easiest way to run it

### 1. Open Terminal

On a Mac, press `Command + Space`, type `Terminal`, and press Enter.

### 2. Copy and paste these commands

```bash
cd ~/GitHub/HealthCoach/rag
./hc
```

The launcher keeps the Mac awake while HealthCoach works. Use `l` to log today, `w` to
review the completed week, or Tab / `1`-`5` to switch areas. Research remains available in
its own area, including experimental-source refreshes.

### 3. Review your plan when needed

Choose **Plan -> Review My Plan** to open the full assessment. It is no longer the first
screen on every launch. Old plans without a saved session snapshot show only their
recorded calendar placement until the plan is reviewed and saved again.

HealthCoach explains nine short sections one at a time:

1. Goals and current activity.
2. Training schedule and injuries.
3. Supplements currently being used and their results.
4. Medicines, confirmed deficiencies, reactions, and safety concerns.
5. Supplements to investigate.
6. Peptides or gray-market items to investigate—not automatically use.
7. Food, digestion, sleep, caffeine, and substances.
8. Food, home, faith, and alternative-health ideas to evaluate.
9. Stores, buying preferences, and deadlines.

- Use the arrow keys to move.
- Press Space to select or unselect something.
- Press `/` to search longer lists.
- Press `r` to return to that section's complete list.
- Press Enter to continue to the next section.

Each screen explains what its answers change. Useful choices are already checked, so pressing
Enter keeps them. At the end, HealthCoach shows a readable summary and lets you generate the
report, restart the assessment, or cancel without changing the current report.

The `STORE / MULTI` section includes Costco, Whole Foods, Sam's Club, H-E-B, Walmart,
Sprouts, Trader Joe's, pharmacies, supplement shops, online stores, and more. Select as many
as you are willing to use. The report uses those choices for sourcing; no chain is required.

HealthCoach only asks for a short typed explanation when a choice cannot be understood safely,
such as an injury, another medication, an abnormal lab result, or a supplement reaction. All
needed details are collected in one short line rather than a long interview.

### 4. Wait for the report

The first run can be slower because the Mac may need to download the local language model.
Later runs reuse it. Leave Terminal open until HealthCoach says the report is complete.

### 5. Browse the report

```bash
./hc-report
```

Use the arrow keys to choose a chapter. Press Space or Enter to open it. Press Space again to
move down one screen, `b` to return to the chapter index, `[` or `]` to change chapters, and
`q` to quit. Press `/` at the index to search both chapter titles and paragraph text.

For a direct lookup without the interactive screen:

```bash
./hc-report --search "raw milk"
./hc-report --page 017
```

To open the complete static file in a Mac application:

```bash
open HEALTHCOACH_REPORT.md
```

For a cleaner Terminal reading view, install Glow once and then use it:

```bash
brew install glow
glow -p HEALTHCOACH_REPORT.md
```

## What HealthCoach is doing

In plain language:

1. You select your goals, current supplements, health concerns, foods, preferred habits, and every store you are willing to search.
2. HealthCoach searches the research papers stored on your Mac.
3. It removes duplicate sources and checks how directly each source fits your question.
4. It labels strong, weak, missing, and indirect evidence instead of pretending every idea is
   proven.
5. It creates one organized report with chapters, logical page numbers, recommendations,
   cautions, and source references.

The report is generated locally after the required models have been downloaded. It is a
research and planning tool, not a doctor, prescription service, or medical diagnosis.

## Common commands

Run the normal guided assessment:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-supplements
```

Use the longer assessment when exact dates, doses, mileage, and symptom details are needed:

```bash
./hc-supplements --detailed-assessment
```

See the available stores, food, home, faith, and alternative-health choices:

```bash
./hc-supplements --list-lifestyle
```

Ask one research question without rebuilding the full report:

```bash
python3 coach.py "Does creatine affect sleep?"
```

Use **DEEP INTAKE / RANK / ADD / DECIDE / INSPECT** in `./hc` to confirm ranking context and
maintain the private candidate ledger. Every ranking run scans the configured supplements,
foods, peptides, nootropics, and gray-market topics. Selected rows remain visible even when
coverage is `NONE`; only an explicit `adopt` decision or `use_status=in_use` can put a candidate
on the generated week overlay.

Recommended order: run **DEEP INTAKE / RANK / ADD / DECIDE / INSPECT** first, choose
`deep_intake`, then run **START / UPDATE PLAN + RUN FULL RANKING**. The second action scans the
entire configured catalog and offers up to the saved follow-up cap without auto-adopting rank 1.

Refresh the focused evidence folders for ALCAR, citicoline, uridine, Noopept, and bromantane,
then rebuild and test the search index:

```bash
caffeinate -i ./hc-refresh-nootropics
```

When Bible/Jesus study is selected in the assessment, the report assigns 04:50–05:15 to its
eight-week reading-and-prayer path and keeps 05:15–05:50 for Anki or technical study.

## First-time installation

Only do this if the `.venv` folder has not already been created:

```bash
cd ~/GitHub/HealthCoach/rag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `hc-supplements` command activates this environment automatically during normal use.

## Updating the research library

You do not need to update the research library every time you create a report. Update it only
after adding or downloading new papers.

```bash
cd ~/GitHub/HealthCoach/papers
caffeinate -i env ABOOST=1 python3 fetch_papers.py

cd ../rag
source .venv/bin/activate
python3 ingest.py
python3 test_retrieval.py
```

This does three things: downloads legal open-access research, rebuilds the searchable local
library, and checks that important questions retrieve appropriate papers.

Do not close Terminal during `ingest.py`. It intentionally replaces the old search index with
the newly rebuilt one.

## Important safety limits

- Selecting an item means “research this,” not “recommend this.”
- The program does not change prescription doses.
- It does not provide personal protocols for gray-market peptides or unapproved drugs.
- Weak, animal-only, or irrelevant evidence cannot become a strong recommendation.
- Deficiency-dependent supplements remain behind diet, laboratory, or clinician checks.
- Home IVs, coffee enemas, raw milk, detox clay, and unsupported frequency treatments are not
  approved simply because they appear in the assessment.

## Where to find more detail

- Beginner and troubleshooting notes: [`rag/README.md`](rag/README.md)
- Full technical explanation for another engineer or AI: [`docs/PROJECT_AI_HANDOFF.md`](docs/PROJECT_AI_HANDOFF.md)
- The generated report: [`rag/HEALTHCOACH_REPORT.md`](rag/HEALTHCOACH_REPORT.md)
