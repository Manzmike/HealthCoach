# HealthCoach — Simple Guide

HealthCoach asks what you want help with, checks research stored on your Mac, and writes one
personalized document named `HEALTHCOACH_REPORT.md`.

## Run HealthCoach

Open Terminal and paste:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-supplements
```

The assessment appears in one searchable screen:

- Arrow keys move up and down.
- Space selects or unselects an item.
- `/` searches the list.
- `r` returns to the complete list.
- Enter submits everything once.

The most common choices are selected already. HealthCoach asks for at most one short written
explanation, and only when a choice needs clarification for safety or accuracy.

## Read the result

When the program finishes, open the report:

```bash
open HEALTHCOACH_REPORT.md
```

Or read it neatly inside Terminal:

```bash
glow -p HEALTHCOACH_REPORT.md
```

Every run replaces the same report. No timestamped reports, JSON side files, or additional log
documents are created.

## What is inside the report

- A Monday-through-Sunday operating plan.
- Training, cardio, steps, recovery, and skipped-workout rules.
- A Costco-first meal and grocery plan.
- Coffee, milk, food, supplement, and medication-interaction reviews.
- Apartment, house, light, water, faith, and lifestyle options.
- Supplement and peptide evidence tables.
- Safety gates and topics the research does not adequately cover.
- A clickable chapter and logical-page index.
- The questions, recorded answers, and research references used.

## Finding choices quickly

Press `/` in the assessment and search for category names such as:

```text
GOAL
TAKING NOW
DEEP REVIEW
SAFETY
FOOD TO REVIEW
HOME / FAITH
```

Press `r` after selecting an item to return to the full assessment.

## Optional commands

Use the longer interview when you want to enter exact doses, dates, mileage, or symptom timing:

```bash
./hc-supplements --detailed-assessment
```

Display the food, home, faith, and alternative-health choice names:

```bash
./hc-supplements --list-lifestyle
```

Ask one question without generating the full report:

```bash
python3 coach.py "Does creatine affect sleep?"
```

## First-time setup

Only run this if HealthCoach says the Python environment is missing:

```bash
cd ~/GitHub/HealthCoach/rag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `hc-supplements` launcher activates it automatically afterward.

## Updating the research

Creating a new report does not require downloading the research again. Update the paper library
only after you intentionally add or fetch new sources:

```bash
cd ~/GitHub/HealthCoach/papers
caffeinate -i env ABOOST=1 python3 fetch_papers.py

cd ../rag
source .venv/bin/activate
python3 ingest.py
python3 test_retrieval.py
```

`ingest.py` rebuilds the search index, so let it finish before generating another report.

## Important limits

- HealthCoach is an evidence and planning tool, not a doctor.
- Selecting something asks the program to evaluate it; selection is not approval.
- Prescription changes and unapproved-drug protocols are not generated.
- Missing or animal-only evidence is labeled instead of being presented as proven.
- The program may recommend discussing a symptom, medication, or laboratory result with a
  qualified clinician.

For the complete engineering explanation, read
[`PROJECT_AI_HANDOFF.md`](PROJECT_AI_HANDOFF.md).
