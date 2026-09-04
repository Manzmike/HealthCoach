# HealthCoach — Simple Guide

HealthCoach asks what you want help with, checks research stored on your Mac, and writes one
personalized document named `HEALTHCOACH_REPORT.md`.

## What the idea means

Health advice is often scattered across videos, product pages, studies, and unrelated AI
answers. HealthCoach brings the user's schedule, goals, training, food choices, current stack,
safety concerns, and shopping options into one assessment. It then searches the local paper
library for each selected topic, removes duplicate or off-topic results, and records how strong
and personally relevant the remaining evidence is.

```text
select → retrieve → check → compare → build one report
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
caffeinate -i ./hc-supplements
```

The assessment guides you through nine explained sections: goals, training schedule, current
stack, safety, supplement research, experimental/peptide research, daily routine, food/home
ideas, and shopping. Each screen tells you why the question matters.

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

Choices marked `LOCKED` are facts already fixed for this HealthCoach profile: tirzepatide is a
current prescription and creatine monohydrate is 5 g/day. They cannot be cleared accidentally.
Every other checked choice is saved under a stable internal name and validated before research
starts. The one report includes a `HARD-DEFINED SELECTION LOCK` table showing exactly what was
locked, selected, or left unselected. HealthCoach does not guess personal answers that the user
did not choose.

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

Changing assessment choices, locking selections, changing stores, or generating another report
does **not** require a source pull. Those actions reuse the indexed library already on the Mac.

### Refresh the five focus/nootropic topics

ALCAR, citicoline, uridine, Noopept, and bromantane have a focused updater. It downloads only
legal open-access material, rebuilds the local search index, and runs the retrieval check:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-nootropics
```

Then generate the one canonical report again:

```bash
caffeinate -i ./hc-supplements
```

Selection asks HealthCoach to investigate an item; it does not automatically add it to the
stack. Noopept and bromantane stay in the peptide/gray-market research screen and never receive
a personal-use protocol.

### Optional experimental-drug evidence screen

The `PEPTIDE / GRAY-MARKET RESEARCH` page now starts with one research-boundary choice:

- Keep `Approved medicines and ordinary supplements only` for the normal conservative report.
- Choose `Research-only broad scan` only if you want HealthCoach to check every configured
  experimental/unapproved topic and surface the ones with at least two unique candidate-folder
  A/B sources containing human-participant and intervention/exposure signals.

The second choice expands **research**, not permission to use a drug. A topic can have promising
human results and still fail on adverse effects, interactions, product identity, manufacturing
quality, sport rules, or applicability to this user. Chemistry and biology are used to flag
receptor, CYP/transporter, cardiac, glucose, growth, liver/kidney, and other possible overlaps.
They cannot prove two products are safe together. Without direct human interaction/co-use data,
the report prints `UNKNOWN / NOT VERIFIED` and keeps the item at clinician-only or skip.

The searchable named-item list includes the configured incretins, peptides, research drugs, and
gray nootropics. Press `/` and type part of a name instead of scrolling through the full list.

To search for additional A/B source candidates across every configured experimental folder,
rebuild the index, and check retrieval in one resumable command (the report applies the separate
human/intervention gate afterward):

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-experimental
```

This source refresh can take a while. It is not required every time a report is generated.
Afterward, run `caffeinate -i ./hc-supplements` and choose the broad scan in the assessment.

For an automated non-interactive evidence-only check (no model-written deep cards):

```bash
./hc-supplements --non-interactive --experimental-policy screen_strong_human --evidence-only
```

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
[`PROJECT_AI_HANDOFF.md`](PROJECT_AI_HANDOFF.md).
