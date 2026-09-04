#!/usr/bin/env python3
"""
PERSONALIZED SCHEDULE BUILDER — deterministic clock, model fills content.

The daily timeline and weekly split are computed IN CODE from your fixed TIMES anchors in
schedule_inputs.md, so the model can never move your bedtime, invent work hours, or print
impossible times. The local LLM only writes the rationale / how-to for each block. Sleep
length and caffeine cut-off are computed and sanity-checked here too.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  nano schedule_inputs.md
  python3 build_schedule.py            # -> logs/schedule_YYYYMMDD_HHMM.md
  MAXTOK=2200 python3 build_schedule.py

parse_inputs() and block() are also imported by build_playbook.py — keep them.
"""
import os, re, datetime
import coach as C

MAXTOK    = int(os.environ.get("MAXTOK", "1800"))
INPUTFILE = os.environ.get("INPUTS", "schedule_inputs.md")
TIPS      = "SCHEDULE_TIPS.md"

SECTIONS = ["INCORPORATE", "TO DO", "REMEMBER", "REC-LEVEL NOTES"]
DEFAULT_SPLIT = {
    "Mon": "Lift A — lower body (squat/hinge, compound focus)",
    "Tue": "Zone 2 run (easy aerobic)",
    "Wed": "Lift B — upper / push-pull (compound focus)",
    "Thu": "Easy run or short intervals",
    "Fri": "Lift C — full-body / upper (no heavy legs before the long run)",
    "Sat": "Long run",
    "Sun": "Rest / mobility",
}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ---------------------------------------------------------------- input parsing
def parse_inputs(path):
    """Return {section: [items]} for the free-text sections. Forgiving."""
    buckets = {s: [] for s in SECTIONS}
    cur = None
    if not os.path.exists(path):
        return buckets
    for raw in open(path):
        s = raw.strip()
        if not s:
            continue
        m = re.match(r'^#{1,6}\s*(.+?)\s*$', s)
        if m:
            head = m.group(1).upper()
            cur = next((sec for sec in SECTIONS if sec in head), None)
            continue
        if s.startswith("#"):
            continue
        item = re.sub(r'^[-*+]\s*', '', s).strip()
        if item and cur:
            buckets[cur].append(item)
    return buckets

def block(title, items):
    if not items:
        return "%s: (none given)" % title
    return "%s:\n%s" % (title, "\n".join("  - " + it for it in items))

def parse_times(path):
    """Read the ## TIMES section: KEY: HH:MM or KEY: int. Returns dict."""
    t, in_times = {}, False
    if not os.path.exists(path):
        return t
    for raw in open(path):
        s = raw.strip()
        if re.match(r'^#{1,6}\s*TIMES', s, re.I):
            in_times = True; continue
        if s.startswith("##"):
            if in_times: break
            continue
        if not in_times or not s or s.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z_]+)\s*:\s*([^#]*)', s)
        if m:
            k, v = m.group(1).strip().upper(), m.group(2).strip()
            if v:
                t[k] = v
    return t

def parse_split(path):
    """Read optional ## WEEKLY SPLIT lines 'Day: session'. Empty -> default."""
    sp, in_sp = {}, False
    if os.path.exists(path):
        for raw in open(path):
            s = raw.strip()
            if re.match(r'^#{1,6}\s*WEEKLY SPLIT', s, re.I):
                in_sp = True; continue
            if s.startswith("##"):
                if in_sp: break
                continue
            if not in_sp or not s or s.startswith("#"):
                continue
            m = re.match(r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*:\s*(.+)$', s, re.I)
            if m:
                sp[m.group(1).title()] = m.group(2).strip()
    return sp or dict(DEFAULT_SPLIT)

# ---------------------------------------------------------------- time helpers
def to_min(s):
    m = re.match(r'^(\d{1,2}):(\d{2})$', s.strip())
    if not m:
        raise ValueError("bad time %r (use HH:MM)" % s)
    return int(m.group(1)) * 60 + int(m.group(2))

def to_hhmm(x):
    x %= 1440
    return "%02d:%02d" % (x // 60, x % 60)

def build_timeline(T):
    """Deterministic Mon–Thu workday timeline from the fixed anchors."""
    wake  = to_min(T.get("WAKE", "05:00"))
    bed   = to_min(T.get("BED", "21:30"))
    ws    = to_min(T.get("WORK_START", "08:00"))
    we    = to_min(T.get("WORK_END", "16:00"))
    train = to_min(T.get("TRAIN", "17:00"))
    smin  = int(T.get("STUDY_MIN", "60"))
    tmin  = int(T.get("TRAIN_MIN", "75"))
    caf   = T.get("CAFFEINE_STOP", "")
    caf_m = to_min(caf) if caf else (bed - 540) % 1440   # default BED − 9h

    study_start = wake + 20
    study_end   = min(study_start + smin, ws - 5) if ws > study_start else study_start + smin
    lunch       = (ws + we) // 2
    tr_end      = train + tmin
    winddown    = bed - 60

    rows = [
        (wake,        "Wake"),
        (wake + 5,    "Morning bright light / sunlight (10–20 min)"),
        (study_start, "Morning study: Bible/Jesus + Anki/technical (%d min)" % smin),
        (max(study_end, ws - 25), "Breakfast — front-load protein"),
        (ws,          "Work begins (10-hour day)"),
        (lunch,       "Lunch — protein + veg"),
        (we,          "Work ends"),
        (train,       "TRAINING (see weekly split for today's session) — %d min" % tmin),
        (tr_end + 10, "Post-training: protein + creatine 5 g"),
        (min(tr_end + 75, winddown - 30), "Dinner"),
        (winddown,    "Wind-down — screens off, dim lights"),
        (bed,         "Lights out / sleep"),
    ]
    rows = [(t % 1440, lbl) for t, lbl in rows]
    sleep_min = (wake - bed) % 1440
    return rows, caf_m, sleep_min, (wake, bed, ws, we, train)

# ---------------------------------------------------------------- main
def main():
    inp   = parse_inputs(INPUTFILE)
    T     = parse_times(INPUTFILE)
    split = parse_split(INPUTFILE)
    if not T:
        print("No ## TIMES section found in %s — add WAKE/BED/WORK_START/WORK_END/TRAIN and rerun." % INPUTFILE)
        return
    try:
        rows, caf_m, sleep_min, anchors = build_timeline(T)
    except ValueError as e:
        print("TIMES error:", e); return
    wake, bed, ws, we, train = anchors
    sleep_h = sleep_min / 60.0
    sleep_note = ""
    if sleep_h < 7:
        sleep_note = "  ⚠️ only %.1f h in bed — under the 7–9 h range; move BED earlier or WAKE later." % sleep_h
    elif sleep_h > 9.5:
        sleep_note = "  (note: %.1f h scheduled — generous.)" % sleep_h

    # deterministic text blocks (times guaranteed correct)
    timeline_md = "\n".join("| %s | %s |" % (to_hhmm(t), lbl) for t, lbl in rows)
    split_md = "\n".join("| %s | %s |" % (d, split.get(d, "—")) for d in DAYS)
    n_lift = sum(1 for d in DAYS if re.search(r'lift|strength|weight', split.get(d, ""), re.I))
    lift_note = "" if n_lift >= 2 else ("  ⚠️ only %d lifting day(s) — for muscle retention on a cut, 2–3 is better." % n_lift)

    # ---- LLM: fills rationale/how-to ONLY; cannot change the clock ----
    print("loading models once (embedding + reranker + MLX)...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load, generate
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr  = C.load_reranker()
    model, tok = load(C.GEN_MODEL)
    chat = bool(getattr(tok, "chat_template", None))

    themes = ["supplement timing morning night", "caffeine timing half-life sleep",
              "morning light circadian alertness", "evening resistance training sleep",
              "protein distribution per meal", "zone 2 heart rate determination",
              "concurrent training interference lifting running", "calorie deficit muscle retention",
              "long run fueling carbohydrate", "energy availability under-fueling"]
    seen, hits = set(), []
    for q in inp["INCORPORATE"] + inp["REMEMBER"] + themes:
        for h in C.search(tbl, emb, q, 4, rr)[0]:
            if h["source_pdf"] in seen: continue
            seen.add(h["source_pdf"]); hits.append(h)
    hits = hits[:16]
    ctx = "\n\n".join("[%s | %s | %s]\n%s" % (
            h["grade"], h["folder"], h.get("doi") or "no-doi", h["text"][:1000]) for h in hits)

    profile = getattr(C, "PROFILE", "") or "(no profile on file)"
    histfile = os.environ.get("HISTORY", "history.md")
    history = open(histfile).read().strip() if os.path.exists(histfile) else ""
    hist_block = ("MY HISTORY (skip what I already do, respect what failed, account for my labs):\n%s\n\n"
                  % history) if history else ""

    user = (
        "USER PROFILE:\n%s\n\n"
        "MY INPUTS:\n%s\n%s\n%s\n%s\n\n%s"
        "The DAILY TIMELINE and WEEKLY SPLIT below are FIXED (already set by me). Do NOT change any "
        "times or restate the table. Your job is the CONTENT for each block.\n\n"
        "FIXED DAILY TIMELINE (Mon–Thu):\n%s\n\nFIXED WEEKLY SPLIT:\n%s\n\n"
        "EVIDENCE CONTEXT:\n%s\n\n"
        "Write for a smart beginner (define any term, say how to find my number). TASK — produce:\n"
        "1) BLOCK NOTES: for each daily block above, 1–2 lines on exactly what to do/eat/take and WHY, "
        "tagged A/B/C by human-evidence strength.\n"
        "2) TRAINING DETAIL: for each weekly session, the specifics — for runs give the zone-2 HR method "
        "and target, for intervals a sample format, for lifts sets/reps and reps-in-reserve; note the long-run "
        "fueling point.\n"
        "3) CONFLICTS: flag anything in my inputs that fights the fixed times, don't silently 'fix' it.\n"
        "Rules: don't invent supplement/drug doses; label weak evidence; be concrete."
    ) % (profile,
         block("INCORPORATE", inp["INCORPORATE"]), block("TO DO", inp["TO DO"]),
         block("REMEMBER", inp["REMEMBER"]), block("REC-LEVEL NOTES", inp["REC-LEVEL NOTES"]),
         hist_block, timeline_md, split_md, ctx)

    if chat:
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": C.SYSTEM}, {"role": "user", "content": user}],
            add_generation_prompt=True, tokenize=False)
    else:
        prompt = "%s\n\n%s\n\nANSWER:" % (C.SYSTEM, user)
    print("filling content around the fixed schedule (max_tokens=%d)..." % MAXTOK)
    notes = generate(model, tok, prompt=prompt, max_tokens=MAXTOK, verbose=False).strip()

    tips = open(TIPS).read() if os.path.exists(TIPS) else "_(SCHEDULE_TIPS.md not found)_"

    # ---- assemble ----
    os.makedirs("logs", exist_ok=True)
    out = os.path.join("logs", "schedule_" + datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".md")
    srcs, ss = [], set()
    for h in hits:
        if h["source_pdf"] in ss: continue
        ss.add(h["source_pdf"]); doi = h.get("doi") or ""
        ref = "https://doi.org/%s" % doi if doi else "(no DOI)"
        srcs.append("- [%s] %s (%s) — %s — %s" % (
            h["grade"], h["folder"], h.get("year") or "n.d.", ref, os.path.basename(h["source_pdf"])))

    with open(out, "w") as f:
        f.write("# My schedule\n\n_Generated %s · times fixed in code from your anchors · model %s_\n\n"
                % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), C.GEN_MODEL))
        f.write("## Fixed anchors\n\n")
        f.write("- Wake **%s** · Sleep **%s** → **%.1f h in bed**%s\n" % (to_hhmm(wake), to_hhmm(bed), sleep_h, sleep_note))
        f.write("- Work **%s–%s** · Training **%s**\n" % (to_hhmm(ws), to_hhmm(we), to_hhmm(train)))
        f.write("- Last caffeine by **%s** (≈9 h before bed; caffeine half-life ~5–6 h)\n\n" % to_hhmm(caf_m))
        f.write("## Daily timeline (Mon–Thu workday)\n\n| Time | Block |\n|---|---|\n%s\n\n" % timeline_md)
        f.write("## Weekly split\n\n| Day | Session |\n|---|---|\n%s\n%s\n\n"
                % (split_md, ("\n> " + lift_note.strip()) if lift_note else ""))
        f.write("---\n\n## Notes, rationale & training detail\n\n%s\n\n---\n\n" % notes)
        f.write("## How to find your numbers\n\n%s\n\n---\n\n" % tips)
        f.write("## Evidence drawn on\n\n%s\n" % ("\n".join(srcs) or "- none"))
    print("wrote", out, "| sleep %.1fh | lift days %d" % (sleep_h, n_lift))

if __name__ == "__main__":
    main()
