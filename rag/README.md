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

The food-review page also locks the eleven foods Michael specifically requested: beets,
oregano, saffron, kimchi, tamarind, blueberries, garlic, ginger, honey, cinnamon, and turmeric.
Locked here means “must be checked and shown in the report,” not “must be eaten.” The report
keeps normal culinary food separate from oils, extracts, capsules, or standardized study forms.

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

### One-time refresh for the eleven locked foods

The first version of the library already covered beets and kimchi and had some extract-oriented
coverage for turmeric and cinnamon. Run this focused command once to search for dedicated human
whole-food evidence for all eleven foods, rebuild the index, and check that each folder is
retrievable:

```bash
cd ~/GitHub/HealthCoach/rag
caffeinate -i ./hc-refresh-whole-foods
```

After that finishes, generate the one report:

```bash
caffeinate -i ./hc-supplements
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
