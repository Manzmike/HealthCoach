# MY SCHEDULE INPUTS
# HOW TO USE THIS FILE
#   1. Copy it:  cp schedule_inputs.example.md schedule_inputs.md
#   2. Fill in your own real wake/bed/work times below.
#   3. Then run:  python3 build_schedule.py
# The TIMES below are FIXED anchors — the schedule is built exactly around them in code,
# so the model can never move your bedtime or invent hours. Use 24-hour HH:MM.

## TIMES   (fixed anchors — replace every value with your own)
WAKE: 06:30
BED: 22:30
WORK_START: 09:00
WORK_END: 17:00
TRAIN: 18:00
STUDY_MIN: 0
TRAIN_MIN: 60
CAFFEINE_STOP:            # leave blank to auto-set = BED minus 9h

## WEEKLY SPLIT   (optional — "Day: session". Delete this whole section to use a sensible
#                  hybrid default with 2 lift days + runs. Keep your long run on its day.)
Mon: Lift A — lower body (squat/hinge, compound focus)
Tue: Zone 2 run (easy aerobic)
Wed: Lift B — upper / push-pull (compound focus)
Thu: Easy run or short intervals
Fri: Lift C — full-body / upper (no heavy legs before the long run)
Sat: Long run
Sun: Rest / mobility

## INCORPORATE   (must be in my day — non-negotiable; delete or replace these examples)
- protein target hit every day
- morning sunlight within 30 min of waking

## TO DO   (tasks/sessions to place in the day or week — delete or replace these examples)
- meal prep on Sunday

## REMEMBER   (constraints / principles to honor — delete or replace these examples)
- [any medication, injury, or schedule constraint that should shape the plan]

## REC-LEVEL NOTES   (optional — what you think matters most)
- A: [the 1-3 things you think matter most]
- watching: [anything you're unsure about or want the plan to account for]
