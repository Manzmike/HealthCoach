#!/usr/bin/env python3
"""
PERSONALIZED SCHEDULE BUILDER — you give the inputs, the coach builds the day.

Reads schedule_inputs.md (you edit it), pulls supporting evidence from the library,
and writes a concrete daily + weekly schedule that HONORS your inputs and layers the
strongest A/B-tier evidence-based habits around them. Each scheduled item is tagged
with a recommendation level (A/B/C) and a one-line why + smallest step to make it stick.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  # edit schedule_inputs.md first, then:
  python3 build_schedule.py                 # -> logs/schedule_YYYYMMDD_HHMM.md
  MAXTOK=2200 python3 build_schedule.py     # give it more room for a long plan

Grounded in the same library + guardrails as coach.py (no invented doses; weak evidence
is labeled and tagged C). This is a first-draft planner — sanity-check it against your life.
"""
import os, re, datetime
import coach as C

MAXTOK    = int(os.environ.get("MAXTOK", "2600"))   # bigger default: plan now includes how-to + cheat sheet
INPUTFILE = os.environ.get("INPUTS", "schedule_inputs.md")

SECTIONS = ["INCORPORATE", "TO DO", "REMEMBER", "REC-LEVEL NOTES"]

def parse_inputs(path):
    """Return {section: [items]} from the markdown template. Very forgiving."""
    buckets = {s: [] for s in SECTIONS}
    cur = None
    if not os.path.exists(path):
        return buckets
    for raw in open(path):
        line = raw.rstrip("\n")
        s = line.strip()
        if not s:
            continue
        m = re.match(r'^#{1,6}\s*(.+?)\s*$', s)           # a header line
        if m:
            head = m.group(1).upper()
            cur = next((sec for sec in SECTIONS if sec in head), None)
            continue
        if s.startswith("#"):
            continue
        item = re.sub(r'^[-*+]\s*', '', s).strip()         # strip bullet
        if item and cur:
            buckets[cur].append(item)
    return buckets

def block(title, items):
    if not items:
        return "%s: (none given)" % title
    return "%s:\n%s" % (title, "\n".join("  - " + it for it in items))

def main():
    inp = parse_inputs(INPUTFILE)
    n_items = sum(len(v) for v in inp.values())
    if n_items == 0:
        print("No inputs found in %s — fill it in (INCORPORATE / TO DO / REMEMBER / REC-LEVEL NOTES) and rerun."
              % INPUTFILE)
        return

    print("loading models once (embedding + reranker + MLX)...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load, generate
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr  = C.load_reranker()
    model, tok = load(C.GEN_MODEL)
    chat = bool(getattr(tok, "chat_template", None))

    # --- retrieve evidence: your own items + core daily-timing themes ---
    themes = [
        "daily supplement timing testosterone sleep energy",
        "caffeine timing half-life effect on sleep",
        "protein distribution per meal muscle grams per kilogram",
        "morning light exposure circadian alertness",
        "evening resistance training effect on sleep",
        "zone 2 training heart rate lactate threshold talk test determination",
        "maximum heart rate estimation training zones",
        "rating of perceived exertion RPE reps in reserve training",
        "VO2 max intervals endurance protocol",
        "sleep duration need recovery hormones",
        "calorie deficit rate energy availability muscle retention",
        "how to estimate calorie needs TDEE deficit weight loss",
    ]
    queries = inp["INCORPORATE"] + inp["REMEMBER"] + themes
    seen, hits = set(), []
    for q in queries:
        hs, _ = C.search(tbl, emb, q, 4, rr)
        for h in hs:
            if h["source_pdf"] in seen:
                continue
            seen.add(h["source_pdf"]); hits.append(h)
    hits = hits[:16]
    ctx = "\n\n".join("[%s | %s | %s]\n%s" % (
            h["grade"], h["folder"], h.get("doi") or "no-doi", h["text"][:1100]) for h in hits)

    profile = getattr(C, "PROFILE", "") or "(no profile on file)"
    histfile = os.environ.get("HISTORY", "history.md")
    history = open(histfile).read().strip() if os.path.exists(histfile) else ""
    hist_block = ("MY HISTORY (use this: skip what I already do, respect things I tried that didn't work, "
                  "and account for my recent labs/metrics — don't re-recommend or contradict it):\n%s\n\n"
                  % history) if history else ""
    user = (
        "USER PROFILE:\n%s\n\n"
        "MY INPUTS — these are the highest priority and MUST be honored:\n%s\n%s\n%s\n%s\n\n"
        "%s"
        "EVIDENCE CONTEXT (use to justify timing and to add high-value A/B items around my inputs):\n%s\n\n"
        "Assume I am a smart beginner who does NOT know the jargon. Write so I could act on this with no "
        "other source. Whenever you use a technical term or method (e.g. zone 2, RPE, reps-in-reserve, "
        "minimum effective dose, TDEE, protein g/kg, sleep latency), you MUST: (a) define it in one plain "
        "sentence, and (b) tell me the concrete way to find MY OWN number — cheapest/no-gear method first, "
        "then more precise ones — and how to check I got it right.\n\n"
        "TASK — build me all FOUR, be specific with clock times:\n"
        "1) A DAILY schedule for a Mon-Thu workday, wake to sleep, that: includes EVERY 'incorporate' item "
        "at the best evidence-based time; places my 'to do' items sensibly; honors EVERY 'remember' constraint; "
        "and layers in the strongest A/B-tier evidence-based habits around them.\n"
        "2) A WEEKLY structure (Mon-Thu work, Fri-Sun off, long run Sat) showing where training, recovery, "
        "and each item land across the week.\n"
        "3) A 'why + how + first step' list: for each item, tag its recommendation level A/B/C from human "
        "evidence, give a one-line reason, the how-to (definition + how to find my number, per the rule above), "
        "and the smallest first step to make it stick.\n"
        "4) A 'HOW TO FIND YOUR NUMBERS' cheat sheet covering every personal metric the plan relies on — "
        "at minimum: zone 2 heart rate (give the age-estimate, the talk-test, and the more precise options), "
        "training max-HR estimate, RPE / reps-in-reserve scale, daily protein target in grams (from bodyweight), "
        "calorie/TDEE and deficit estimate, caffeine cut-off time (from its ~5-6h half-life and my bedtime), and "
        "nightly sleep need. For each: what it is, how to find mine, and how to verify.\n"
        "Rules: honor my inputs first; don't invent supplement/drug doses; where evidence is weak, say so and "
        "tag it C; if two things conflict on timing, flag the tradeoff instead of guessing; prefer concrete "
        "numbers and ranges over vague advice."
    ) % (profile,
         block("INCORPORATE (must be in my day)", inp["INCORPORATE"]),
         block("TO DO (place these in the day/week)", inp["TO DO"]),
         block("REMEMBER (constraints / principles to honor)", inp["REMEMBER"]),
         block("REC-LEVEL NOTES (what I think matters most)", inp["REC-LEVEL NOTES"]),
         hist_block,
         ctx)

    if chat:
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": C.SYSTEM}, {"role": "user", "content": user}],
            add_generation_prompt=True, tokenize=False)
    else:
        prompt = "%s\n\n%s\n\nANSWER:" % (C.SYSTEM, user)

    print("building schedule from %d inputs + %d evidence passages (max_tokens=%d)..."
          % (n_items, len(hits), MAXTOK))
    ans = generate(model, tok, prompt=prompt, max_tokens=MAXTOK, verbose=False).strip()

    os.makedirs("logs", exist_ok=True)
    out = os.path.join("logs", "schedule_" + datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".md")
    srcs, sseen = [], set()
    for h in hits:
        if h["source_pdf"] in sseen: continue
        sseen.add(h["source_pdf"])
        doi = h.get("doi") or ""
        ref = "https://doi.org/%s" % doi if doi else "(no DOI)"
        yr  = h.get("year") or "n.d."
        srcs.append("[%s] %s (%s) — %s — %s" % (
            h["grade"], h["folder"], yr, ref, os.path.basename(h["source_pdf"])))
    with open(out, "w") as f:
        f.write("# HealthCoach — personalized schedule\n\nGenerated %s · model %s\n\n"
                % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), C.GEN_MODEL))
        f.write("## My inputs\n\n%s\n%s\n%s\n%s\n\n---\n\n"
                % (block("INCORPORATE", inp["INCORPORATE"]), block("TO DO", inp["TO DO"]),
                   block("REMEMBER", inp["REMEMBER"]), block("REC-LEVEL NOTES", inp["REC-LEVEL NOTES"])))
        f.write("## Schedule\n\n%s\n\n---\n\n**Evidence drawn on**\n%s\n"
                % (ans, "\n".join("- " + s for s in srcs) or "- none"))
    print("wrote", out)

if __name__ == "__main__":
    main()
