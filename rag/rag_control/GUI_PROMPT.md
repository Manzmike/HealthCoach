# HealthCoach GUI prompt — verbose Today + coach
Paste this into the UI agent. Do not invent new medical advice. Bind to existing files only.

---

Build a **verbose** desktop/TUI-or-web Today view for HealthCoach. Verbose means the user can *see why* the system chose this week’s three actions and what it refused. It does **not** mean twelve competing protocols on one screen.

## Hard product rules (do not violate)
- One `primary_focus` from `rag/rag_control/plan_this_week.json`.
- At most **3** numbered actions. Optional helpers are collapsed, not peers.
- Always show the safety line if `person_state.sleep.drowsy_drive_0_10` is set: **Do not drive while fighting sleep.**
- Never show TRT, copper, peptides, nofap, detox/lymph-cleanse, home statin, extra D, or “you are cleared of apnea.”
- `person_state.json` is current reality. `schedule_inputs.md` 04:30/20:15 block is a **goal**, shown as a goal only, never as “how you sleep now.”
- January 2026 labs are **stale**. Banner them. Do not treat LDL 191 as today’s order.
- Tirzepatide is an **aggravator**, not the root of years-long nights.
- Post-orgasm drop is hypnagogia/inertia, never labeled psychosis.

Data sources (read-only):
- `rag/rag_control/person_state.json`
- `rag/rag_control/plan_this_week.json`
- `rag/rag_control/critic.json` (for the “not this” chip list)
- Coach answers from `coach.py` (router + critic already wired)

## Layout — Today (top to bottom)

### 0. Masthead
Title: **This week**  
Sub: `week_of` date + one sentence from `plan_this_week.why`.  
Right side: three status pills
- Sleep: `split` (red/amber)
- Drug: `tirzepatide on — considering stop` (amber)
- Labs: `Jan 2026 — stale` (grey)

Clicking a pill opens the matching drawer (below). Do not navigate away.

### 1. Safety strip (always visible, sticky)
Full-width, high contrast.

Line 1 (required): **Do not drive while fighting sleep.**  
Line 2: drowsy 4–8/10 on a ~20 min drive home.  
Line 3: partner-heard pauses + inconclusive study — this app does not clear an airway.

If coach.py or the report generator ever omit line 1, the GUI still renders it from person_state.

### 2. Primary focus card
Huge type, one phrase: `sleep_continuity_and_safety` rendered as human text  
**Sleep continuity and safety**

Under it, the `why` paragraph in full (verbose on purpose). Example voice:

> Nights were already split before tirzepatide. People next to you hear breathing stop. The first study was inconclusive. You fight sleep on the drive. The shot can make late dinner and nausea worse. It is not the diagnosis. Screens and a 22:00 plate can make the hole at 02:00 worse. They do not cause the pauses.

### 3. The three actions (checklist)
Each action is a wide row, not a tiny checkbox.

```
A1  [ ]  If you are fighting sleep, do not drive.
    Lane: sleep-drive
    Done when: You did not drive through a 4–8/10 drowsy window.
    Why this exists: person_state.drowsy_drive + NICE CKS OSAS driving.
    Not a substitute for: a completed sleep test.

A2  [ ]  Move the one meal off 22:00. Put protein in it.
    Lane: meal-sleep
    Done when: Dinner finished before deep-work end at least 4 nights.
    Why: dinner ~22:00 + split nights; delayed emptying if still on the shot.
    Not: OMAD-as-optimal, juice cleanse, extra supplements.

A3  [ ]  If still on tirzepatide: message the prescriber about fatigue,
         nausea, stomach pain, considering stop. Do not change the dose.
    Lane: incretin-context
    Done when: Message sent, or you logged that you already stopped.
    Why: in-label GI/fatigue; discontinuation rebound is a clinician talk.
    Not: RAG dosing, stacking another peptide.
```

Checking a box writes a local `week_log.json` (`action_id, date, done`). Do not call a model to celebrate.

### 4. Not this (verbose deny wall)
A two-column chip board titled **The model is not allowed to tell you to…**

Cut · 5-day lift return · copper · TRT · nofap · extra D · home statin · lymph/detox cleanse · “psychosis” label · “you’re cleared” · change the tirzepatide dose yourself

Each chip, on click, expands one sentence:

- Cut → “Nights are split and training is zero. A deficit waits.”
- TRT → “Old T was 598. Sleep first.”
- Detox → “Standing and walking move lymph. Tea does not treat an airway.”
- Cleared → “Inconclusive study + witnessed pauses. This GUI cannot close that.”

### 5. How you actually live (person-state panel)
Default **expanded** (this is the verbose part). Sections with short tables, not paragraphs of fluff.

**Night (actual, not goal)**  
| Window | 22:00–02:00 then 03:30–07:00, or 23:00–02:00 then 04:00–08:00 |  
| Pauses | Witnessed by bed partner |  
| Study | Inconclusive |  
| Morning HA | Yes |  
| 02:00–04:00 | Sometimes strong sexual urge; after release can drop 20 min–2 h, aware in bed, vivid dream, headache |  
| Midday | Same drop can happen after orgasm in daylight |  
| Label | Hypnagogia / sleep inertia — not psychosis |

**Day**  
| Work | Desk, sedentary |  
| Drive | ~20 min; drowsy 4–8/10 |  
| Meals | Skip breakfast, sometimes lunch, dinner ~22:00 |  
| Deep work | 18:00–22:00/23:00 (allowed; dim after) |  
| Caffeine | Last dose 11:00–12:00 — do not add an afternoon coffee |  
| Alcohol | Weekend 0 or 3–6; keep off the late slot |  
| Training | Stopped. Intended later: 3 lift + 2 easy run |  
| Weight | 230–240, same as January |  
| Goal | Fat loss, blocked by sleep |

**Drug**  
Tirzepatide on, considering stop. Fatigue, nausea, stomach pain, no vomiting. Role: aggravator.

**Labs (stale — first week Jan 2026)**  
LDL 191 · non-HDL 209 · Lp(a) 154 · hs-CRP 5.6 · T 598 · TSH 0.97 · D 42  
Caption: “Hypothesis only. Repeat. Do not start a statin from this card.”

**Goal schedule (not current)**  
Collapsed row: `schedule_inputs.md` wants wake 04:30 / bed 20:15, no apnea.  
Label: **Target, not tonight.** Do not let this overwrite the split-night table.

### 6. Optional helpers (collapsed `<details>`)
Title: Helpers — not the job this week

- Deep work 18:00–22:00 can stay. Dim/warm display after. No phone in bed.
- Same morning wake. Morning outdoor light.
- Sit-breaks / short walks if nausea allows. This is the lymph lever. No cleanse.
- Side-sleep if it is comfortable. Positional therapy is second-line, not a diagnosis.

### 7. Relations (why A connects to B)
A small graph or a bullet list pulled from `MERGED_relations.csv`, humanized:

- Screens **may worsen** the 02:00 hole. They **do not** cause witnessed pauses.
- Tirzepatide **aggravates** a 22:00 plate. It **does not** explain years of nights.
- Post-orgasm drop is the **same pile** as daytime sleepiness.
- Caffeine is already cut — leave it.
- Sitting still is the opposite of lymph flow. Walking is the intervention.

Use “may / likely / same pile / unlikely” language. No causal banners.

### 8. Citations strip
One row of source names, not a wall of PDFs:  
NICE NG202 · NICE CKS OSAS/insomnia · ICSD-3-TR · ICHD-3 4.3 · Ceriello 2026 (context)

Click → opens a drawer with the locator from the gold CSV. Do not dump 4,556 papers.

### 9. Coach dock (right side or bottom sheet)
Input: the question.  
Output: the model answer **plus** a chrome box the GUI adds even if the model forgets:

```
Intent: sleep_eds | Lanes used: … | Critic: ok / FALLBACK
Person-state injected: yes
Quarantine filter: on
```

If critic fails, render `plan_this_week.json` fallback in place of the model text, and a red banner: **Draft rejected — showing the safety card instead.**

Verbose extras under each coach answer (collapsed by default, open on “Why this answer”):
- Intent + keyword hits
- Top 5 retrieved titles + lane + grade
- Which deny terms were scanned
- Which person_state fields the critic used

### 10. Visual night strip (simple, not a medical waveform)
A 24-hour bar:

```
18      22     02     04     08     12     16
[deep work][dinner?][wake hole][2nd block][desk][drive risk]
```

Mark 02:00–04:00 as the known hole. Mark the commute window as drive-risk. Do not fake an AHI chart.

### 11. Copy / tone
Direct. Short sentences in the cards. Longer sentences only in the why drawers. No wellness voice, no “you’ve got this,” no flame icons, no green detox leaves. Dark theme is fine.

Primary button labels:
- Log tonight
- Open coach
- Message prescriber (opens a prefilled note, does not send)

Prefill note:

```
On tirzepatide. Fatigue, nausea, stomach pain, no vomiting.
Considering stopping. Split sleep, partner-witnessed pauses,
inconclusive study, drowsy on the drive home. Do not change
dose without you.
```

## What not to build
- A 12-pillar dashboard (sleep, hormones, detox, vaccine, lipids, training as equals)
- A lymph-cleanse wizard
- A vaccine score
- Live lab interpretation that treats January numbers as now
- Fake CPAP / sleep-study replacement UI
- Goal schedule as if it already happened

## Acceptance
A stranger can open Today and in ten seconds know: don’t drive sleepy, eat earlier, talk to the prescriber, and why the app is refusing a cut. If they open every drawer they can see the full person-state and the deny wall. If they never open a drawer they still only have three actions.

---
End of GUI prompt.
