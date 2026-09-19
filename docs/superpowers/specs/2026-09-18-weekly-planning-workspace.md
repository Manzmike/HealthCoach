# Weekly Planning Workspace Design

## Goal

Add a simple date-based weekly workspace to the Flask web app for symptom check-ins, workout generation, lifestyle improvement, and meal-plan analysis.

## User flow

The user selects a week start date. The active editing window is the inclusive seven-day range beginning on that date. During the window, the user can edit that week's inputs; outside it, the saved week is read-only until another week is selected.

The left navigation exposes Symptoms, Workouts, Lifestyle, Meals, and Food. Each new planner follows the same pattern: current state, target state, weekly inputs, Save, Analyze, and a readable result. Analysis is advisory, persisted locally, and becomes stale whenever the analyzed inputs change.

## Scope

- Symptoms: dated selected symptom labels and notes, using the existing symptom catalog/report logic.
- Workouts: current level, target, available days, focus, constraints, and deterministic weekly session generation; the existing Schedule page remains the calendar editor.
- Lifestyle: current and target habit selections, notes, and a link to the current calendar; analysis includes saved calendar blocks.
- Meals: 1–7 meal slots with names/notes, current Food selections, and a consolidated analysis.
- Shared week state is stored in `rag/.healthcoach/weekly_workspace.json`; existing Food, Schedule, and Labs stores remain compatible.

## Safety and UX

Recommendations are advisory and do not provide medical clearance or diagnosis. Forms use labels, keyboard-accessible controls, empty states, and explicit read-only messaging when a week is outside its editing window. No analysis runs implicitly on page load.

## Verification

Pure weekly-state tests cover seven-day window boundaries, normalization, stale analysis, meal limits, and workout generation. Flask route tests cover date selection, read-only behavior, saves, analysis calls, and sidebar links. The full existing unittest suite must remain green.
