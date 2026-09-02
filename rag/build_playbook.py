#!/usr/bin/env python3
"""
PERSONAL PLAYBOOK — one structured learning document (report + schedule + how-to).

Assembles a multi-chapter Markdown document from YOUR inputs + the graded library. Each
chapter is written for a smart beginner: terms are defined, personal numbers get a
how-to-find, and every claim is tagged A/B/C by human-evidence strength.

Chapters:
  1  How to find your numbers   (curated, reliable — from SCHEDULE_TIPS.md)
  2  The foundations that matter most (A/B)
  3  Your daily schedule (workday)
  4  Your weekly structure
  5  Supplements & compounds — what to add (tiered A/B/C/D)
  6  Putting it together — your first four weeks
  +  full Sources appendix (grade · topic · year · DOI · file)

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  nano schedule_inputs.md            # your must-haves (same file the schedule uses)
  python3 build_playbook.py          # -> logs/playbook_YYYYMMDD_HHMM.md
  MAXTOK=1800 python3 build_playbook.py   # longer chapters
"""
import os, re, datetime
import coach as C
import build_schedule as BS          # reuse parse_inputs() + block()

MAXTOK = int(os.environ.get("MAXTOK", "1400"))   # per chapter
TIPS   = "SCHEDULE_TIPS.md"

def slug(t):
    return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')

def main():
    inp = BS.parse_inputs(os.environ.get("INPUTS", "schedule_inputs.md"))
    profile = getattr(C, "PROFILE", "") or "(no profile on file)"
    histfile = os.environ.get("HISTORY", "history.md")
    history = open(histfile).read().strip() if os.path.exists(histfile) else ""
    hist_block = ("\n\nMY HISTORY (skip what I already do, respect what I tried that failed, account for my "
                  "recent labs/metrics — don't re-recommend or contradict it):\n%s" % history) if history else ""
    inputs_block = "%s\n%s\n%s\n%s" % (
        BS.block("INCORPORATE", inp["INCORPORATE"]),
        BS.block("TO DO", inp["TO DO"]),
        BS.block("REMEMBER", inp["REMEMBER"]),
        BS.block("REC-LEVEL NOTES", inp["REC-LEVEL NOTES"]))

    print("loading models once (embedding + reranker + MLX)...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load, generate
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr  = C.load_reranker()
    model, tok = load(C.GEN_MODEL)
    chat = bool(getattr(tok, "chat_template", None))

    all_hits, seen_src = [], set()

    def retrieve(queries, k=4, cap=14):
        hits, seen = [], set()
        for q in queries:
            hs, _ = C.search(tbl, emb, q, k, rr)
            for h in hs:
                if h["source_pdf"] in seen:
                    continue
                seen.add(h["source_pdf"]); hits.append(h)
        return hits[:cap]

    def gen(task, queries):
        hits = retrieve(queries)
        ctx = "\n\n".join("[%s | %s | %s]\n%s" % (
                h["grade"], h["folder"], h.get("doi") or "no-doi", h["text"][:1000]) for h in hits)
        for h in hits:
            if h["source_pdf"] not in seen_src:
                seen_src.add(h["source_pdf"]); all_hits.append(h)
        rules = ("Write for a smart beginner who does NOT know the jargon: define any technical term in one "
                 "plain sentence and say how to find the personal number (cheapest method first). Tag claims "
                 "A/B/C by human-evidence strength. Don't invent supplement/drug doses; label weak evidence. "
                 "Prefer concrete numbers and ranges. Use short sections and clear headers.")
        user = ("USER PROFILE:\n%s\n\nMY INPUTS (honor these first):\n%s%s\n\nEVIDENCE CONTEXT:\n%s\n\n%s\n\nTASK: %s"
                % (profile, inputs_block, hist_block, ctx, rules, task))
        if chat:
            prompt = tok.apply_chat_template(
                [{"role": "system", "content": C.SYSTEM}, {"role": "user", "content": user}],
                add_generation_prompt=True, tokenize=False)
        else:
            prompt = "%s\n\n%s\n\nANSWER:" % (C.SYSTEM, user)
        return generate(model, tok, prompt=prompt, max_tokens=MAXTOK, verbose=False).strip()

    tips = open(TIPS).read() if os.path.exists(TIPS) else "_(SCHEDULE_TIPS.md not found)_"

    chapters = [("How to find your numbers", tips)]

    print("[1/5] foundations...")
    chapters.append(("The foundations that matter most", gen(
        "List the highest-evidence A/B FOUNDATIONS for me across sleep, nutrition, training, recovery, and "
        "stress. For each: what it is, why it matters, how to do it, and its A/B/C level. Rank most-to-least "
        "important, and be clear that these outrank any supplement.",
        ["highest evidence health behaviors mortality", "sleep duration health outcomes",
         "protein intake muscle preservation", "zone 2 aerobic base training",
         "resistance training hypertrophy meta-analysis", "calorie deficit fat loss"])))

    # Chapters 3 & 4: times/split are FIXED IN CODE (from schedule_inputs.md TIMES) — the model
    # only adds rationale. This is why the playbook's clock can't drift like the old 8B version.
    print("[2/5] daily schedule (deterministic clock)...")
    T = BS.parse_times(os.environ.get("INPUTS", "schedule_inputs.md"))
    daily_ch = "_(no ## TIMES section in schedule_inputs.md — add WAKE/BED/WORK_START/WORK_END/TRAIN.)_"
    if T:
        rows, caf_m, sleep_min, (wake, bed, ws, we, train) = BS.build_timeline(T)
        sh = sleep_min / 60.0
        warn = "  ⚠️ under 7 h — adjust BED/WAKE." if sh < 7 else ""
        tl = "\n".join("| %s | %s |" % (BS.to_hhmm(t), l) for t, l in rows)
        rationale = gen(
            "The daily timeline below is FIXED (I set the times). Do NOT restate or change any times. Just add, "
            "for each block, a 1–2 line note on exactly what to do/eat/take and WHY, tagged A/B/C.\n\nFIXED TIMELINE:\n" + tl,
            ["supplement timing morning versus night", "caffeine timing half-life sleep",
             "morning light exposure circadian", "evening resistance training sleep", "meal timing protein distribution"])
        daily_ch = ("**Fixed anchors:** wake %s · sleep %s → **%.1f h in bed**%s · work %s–%s · training %s · "
                    "last caffeine %s.\n\n| Time | Block |\n|---|---|\n%s\n\n### Why each block\n\n%s"
                    % (BS.to_hhmm(wake), BS.to_hhmm(bed), sh, warn, BS.to_hhmm(ws), BS.to_hhmm(we),
                       BS.to_hhmm(train), BS.to_hhmm(caf_m), tl, rationale))
    chapters.append(("Your daily schedule (workday)", daily_ch))

    print("[3/5] weekly structure (deterministic split)...")
    split = BS.parse_split(os.environ.get("INPUTS", "schedule_inputs.md"))
    sp_md = "\n".join("| %s | %s |" % (d, split.get(d, "—")) for d in BS.DAYS)
    n_lift = sum(1 for d in BS.DAYS if __import__("re").search(r'lift|strength|weight', split.get(d, ""), __import__("re").I))
    lift_warn = "" if n_lift >= 2 else "\n\n> ⚠️ only %d lifting day(s) — 2–3 is better for muscle retention on a cut." % n_lift
    wk_detail = gen(
        "The weekly split below is FIXED. Do NOT change it. For each session give the specifics — for runs the "
        "zone-2 HR method + target, for intervals a sample format, for lifts sets/reps and reps-in-reserve; note "
        "the long-run fueling point and how to avoid the lifting/running interference effect.\n\nFIXED SPLIT:\n" + sp_md,
        ["zone 2 heart rate determination", "VO2max interval training", "concurrent training interference",
         "long run fueling carbohydrate", "recovery deload overtraining"])
    weekly_ch = "| Day | Session |\n|---|---|\n%s%s\n\n### Session detail\n\n%s" % (sp_md, lift_warn, wk_detail)
    chapters.append(("Your weekly structure", weekly_ch))

    print("[4/5] supplements & compounds (tiered)...")
    chapters.append(("Supplements & compounds — what to add (tiered)", gen(
        "Give an A/B/C/D tier list of supplements and compounds for me. A = would significantly help, add it; "
        "B = worth adding; C = little change; D = not supported / hype. For each: what it does, its level, and "
        "an honest one-line evidence note. Be blunt and put hype in C/D. Do NOT give doses.",
        ["creatine strength cognition evidence", "caffeine performance", "vitamin D testosterone immune",
         "omega-3 recovery inflammation", "magnesium sleep", "ashwagandha cortisol", "peptide evidence human"])))

    print("[5/5] first four weeks...")
    chapters.append(("Putting it together — your first four weeks", gen(
        "Give a phased 4-WEEK adoption plan: which 2-3 changes to add each week (start with A-tier), how to add "
        "ONE thing at a time so I can tell what works, what to measure, and how to know it's working. Keep it "
        "realistic for a busy 10-hour-workday schedule.",
        ["habit formation behavior change", "minimum effective dose", "n=1 self experiment tracking",
         "progressive overload beginner", "adherence sustainable routine"])))

    # ---- assemble the document ----
    os.makedirs("logs", exist_ok=True)
    out = os.path.join("logs", "playbook_" + datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".md")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    toc = "\n".join("%d. %s" % (i, t) for i, (t, _) in enumerate(chapters, 1))
    srcs, ss = [], set()
    for h in all_hits:
        if h["source_pdf"] in ss:
            continue
        ss.add(h["source_pdf"]); doi = h.get("doi") or ""
        ref = "https://doi.org/%s" % doi if doi else "(no DOI)"
        srcs.append("- [%s] %s (%s) — %s — %s" % (
            h["grade"], h["folder"], h.get("year") or "n.d.", ref, os.path.basename(h["source_pdf"])))

    with open(out, "w") as f:
        f.write("# My Health & Performance Playbook\n\n")
        f.write("_Generated %s · built from your inputs and the graded library · model %s_\n\n" % (ts, C.GEN_MODEL))
        f.write("> **How to read this:** A/B/C marks how strong the *human* evidence is (A = systematic review / "
                "guideline, B = randomized trial, C = animal / mechanism / weak). Prioritize A/B; treat C as "
                "optional experiments. No supplement or drug doses are prescribed here — see a clinician for those.\n\n")
        f.write("## Contents\n\n%s\n\nAppendix — Sources\n\n---\n\n" % toc)
        f.write("## Your inputs\n\n%s\n\n---\n\n" % inputs_block)
        for i, (t, body) in enumerate(chapters, 1):
            f.write("## %d. %s\n\n%s\n\n---\n\n" % (i, t, body))
        f.write("## Appendix — Sources\n\n%s\n" % ("\n".join(srcs) or "- none"))
    print("wrote", out, "(%d chapters, %d sources)" % (len(chapters), len(srcs)))

if __name__ == "__main__":
    main()
