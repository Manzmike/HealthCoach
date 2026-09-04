# HealthCoach

HealthCoach is a private program that reads a local library of health and exercise research,
asks a few questions about your goals, and creates one personalized report.

You do not need to understand artificial intelligence, databases, or programming to use it.

## What you receive

HealthCoach creates one file:

```text
rag/HEALTHCOACH_REPORT.md
```

The report contains:

- your weekly training and recovery schedule;
- a practical food and Costco plan;
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
caffeinate -i ./hc-supplements
```

`caffeinate` simply keeps the Mac awake while HealthCoach works.

### 3. Complete the one-screen assessment

- Use the arrow keys to move.
- Press Space to select or unselect something.
- Press `/` to search for an item or category.
- Press `r` to return to the complete list.
- Press Enter once when finished.

Useful choices are already selected. If those choices are correct, you can press Enter
immediately.

HealthCoach only asks for a short typed explanation when a choice cannot be understood safely,
such as an injury, another medication, an abnormal lab result, or a supplement reaction. All
needed details are collected in one short line rather than a long interview.

### 4. Wait for the report

The first run can be slower because the Mac may need to download the local language model.
Later runs reuse it. Leave Terminal open until HealthCoach says the report is complete.

### 5. Open the report

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

1. You select your goals, current supplements, health concerns, foods, and preferred habits.
2. HealthCoach searches the research papers stored on your Mac.
3. It removes duplicate sources and checks how directly each source fits your question.
4. It labels strong, weak, missing, and indirect evidence instead of pretending every idea is
   proven.
5. It creates one organized report with chapters, logical page numbers, recommendations,
   cautions, and source references.

The report is generated locally after the required models have been downloaded. It is a
research and planning tool, not a doctor, prescription service, or medical diagnosis.

## Common commands

Run the normal one-screen assessment:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-supplements
```

Use the longer assessment when exact dates, doses, mileage, and symptom details are needed:

```bash
./hc-supplements --detailed-assessment
```

See the available food, home, faith, and alternative-health choices:

```bash
./hc-supplements --list-lifestyle
```

Ask one research question without rebuilding the full report:

```bash
python3 coach.py "Does creatine affect sleep?"
```

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
- Full technical explanation for another engineer or AI: [`rag/PROJECT_AI_HANDOFF.md`](rag/PROJECT_AI_HANDOFF.md)
- The generated report: [`rag/HEALTHCOACH_REPORT.md`](rag/HEALTHCOACH_REPORT.md)
