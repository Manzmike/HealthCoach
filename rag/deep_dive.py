#!/usr/bin/env python3
"""
Deep-dive synthesis: for each GOAL, pull many passages across several sub-queries,
then write a thorough, graded, actionable evidence brief. Grounded in the library only.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 deep_dive.py                 # all themes
  python3 deep_dive.py hybrid cut      # only themes whose name contains these words
Output -> logs/deep_dive_YYYYMMDD_HHMM.md   (long; ~1-2 pages per goal)
Heavier than batch_ask.py — expect 20-40 min on a 14B model. Swap coach.py GEN_MODEL
to Llama-3.1-8B-Instruct-4bit for ~2x speed.
"""
import os, re, sys, datetime
import coach as C

THEMES = [
 {"name": "Hybrid athlete (lift + run)",
  "focus": "becoming a hybrid athlete who lifts and runs without killing either adaptation",
  "q": ["concurrent training interference lifting and running",
        "weekly programming order strength and endurance same week",
        "protein and energy needs to preserve muscle while running",
        "zone 2 and VO2max development for endurance"]},
 {"name": "Engineer top performance, 10-hour days",
  "focus": "sustaining focus, energy and output across a 10-hour workday as a software engineer",
  "q": ["sustaining focus and energy through a long workday knowledge worker",
        "breaking up prolonged sitting during the workday",
        "caffeine timing for alertness without wrecking sleep",
        "deep work, interruptions and cognitive fatigue in programmers"]},
 {"name": "Recovery",
  "focus": "recovering well from training and long workdays (sleep, muscle, modalities)",
  "q": ["sleep and muscle recovery", "sleep restriction performance and recovery",
        "sauna heat therapy recovery cardiovascular", "cold water immersion recovery tradeoffs"]},
 {"name": "Learning brain",
  "focus": "making the brain learn and retain faster",
  "q": ["retrieval practice testing effect spacing interleaving",
        "aerobic exercise BDNF and cognition in humans",
        "sleep and memory consolidation"]},
 {"name": "Dopamine regulation & motivation",
  "focus": "regulating dopamine, motivation and distraction for consistent output",
  "q": ["dopamine reward motivation and cognition",
        "high-stimulation distraction before focused work",
        "anxiety and cognitive performance"]},
 {"name": "Teeth remineralization",
  "focus": "remineralizing early enamel and preventing cavities",
  "q": ["CPP-ACP remineralization early enamel lesion",
        "fluoride varnish and toothpaste caries prevention",
        "diet sugar and dental caries"]},
 {"name": "Hair care & beard growth",
  "focus": "keeping scalp hair and growing beard/facial hair, evidence-based",
  "q": ["androgenetic alopecia minoxidil finasteride evidence",
        "topical minoxidil beard facial hair growth",
        "nutrition and hair growth"]},
 {"name": "Smart cut to lean body fat",
  "focus": ("the smartest, most sustainable way to cut to a lean body fat; include what "
            "body-fat percentage is healthy vs the risks of very low (5%) body fat"),
  "q": ["calorie deficit lean mass preservation resistance training",
        "protein intake fat loss meta-analysis",
        "low energy availability RED-S male athletes hormones thyroid",
        "diet break refeed continuous deficit",
        "very low body fat health risks hormones"]},
 {"name": "10k steps daily (NEAT / walking)",
  "focus": "hitting ~10,000 steps a day and using walking/NEAT for health, fat loss and desk-offset",
  "q": ["daily step count and health outcomes dose response",
        "non-exercise activity thermogenesis NEAT and weight management",
        "breaking up prolonged sitting with walking",
        "walking cadence and cardiometabolic health"]},
 {"name": "Daily schedule for a 4x10 day",
  "focus": ("an hour-by-hour daily schedule for a four-day 10-hour workweek that fits a fixed "
            "wake time, morning light, deep-work blocks, training, 10k steps, meals and sleep"),
  "q": ["fixed wake time and consistent sleep schedule circadian",
        "morning bright light exposure and circadian timing",
        "caffeine timing for alertness without harming sleep",
        "timing of exercise around a long work day",
        "breaking up sitting with movement during the workday",
        "sleep duration and next-day cognitive performance"]},
 {"name": "Quit porn (reduce compulsive use)",
  "focus": "reducing or quitting problematic/compulsive pornography use to free up focus and drive",
  "q": ["problematic pornography use compulsive sexual behavior treatment",
        "cognitive behavioral therapy compulsive sexual behavior disorder",
        "sexual abstinence effects evidence",
        "cue avoidance and relapse prevention behavior change"]},
 {"name": "Foods for cutting, muscle & staying lean",
  "focus": "what to actually eat to lose fat, build/keep muscle, and stay lean (food choices, not just macros)",
  "q": ["high protein foods satiety weight loss",
        "protein quality leucine food sources muscle",
        "energy density and satiety food choices",
        "food choices to preserve lean mass in a deficit",
        "nutrient dense whole foods diet quality"]},
 {"name": "Foods for brain health",
  "focus": "foods and dietary patterns that support cognition and brain health",
  "q": ["diet and cognitive function", "oily fish omega-3 cognition",
        "flavonoids polyphenols cognition", "Mediterranean diet brain health",
        "glycemic load and cognitive performance"]},
 {"name": "Semax & peptide nootropics",
  "focus": ("what is actually known about semax, selank, noopept and related peptide/regulatory "
            "nootropics — separating mechanism/animal data from real human evidence"),
  "q": ["semax cognition BDNF", "selank anxiety clinical",
        "ACTH 4-10 analog cognition memory", "noopept cognition neuroprotection",
        "regulatory peptide nootropic human evidence"]},
]

DEEP = ("Write a thorough, well-structured evidence brief on: {focus}.\n"
        "Use ONLY the CONTEXT passages. Sections:\n"
        "1) What the STRONG (grade A/B) evidence supports.\n"
        "2) Key mechanisms (brief).\n"
        "3) A concrete, actionable plan tailored to a late-20s man on a four-day 10-hour "
        "workweek who lifts, runs, and is in a calorie deficit — be specific (frequencies, "
        "ranges, sequencing), not generic.\n"
        "4) Myths / what to avoid.\n"
        "5) Where the evidence is weak or missing.\n"
        "Grade every claim (A/B strong, C weak). Cite passages. If context is thin, say so.")

def parse_themes_file(path):
    """Read extra themes from a plain-text file. Format:
         :: Theme name
         focus: one line describing the goal
         q: a retrieval sub-query
         q: another sub-query
       Blank lines and #comments ignored. Returns list of theme dicts."""
    if not os.path.exists(path):
        return []
    out, cur = [], None
    for ln in open(path):
        s = ln.rstrip("\n")
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if s.startswith("::"):
            if cur:
                out.append(cur)
            cur = {"name": s[2:].strip(), "focus": "", "q": []}
        elif cur is not None and s.lower().startswith("focus:"):
            cur["focus"] = s.split(":", 1)[1].strip()
        elif cur is not None and s.lower().startswith("q:"):
            cur["q"].append(s.split(":", 1)[1].strip())
    if cur:
        out.append(cur)
    return [t for t in out if t["q"] and t["focus"]]

def gather(tbl, emb, queries, reranker=None, focus="", k=6, cap=16):
    pool = {}
    for q in queries:
        hits, _ = C.search(tbl, emb, q, k, reranker=None)   # candidate pool per sub-query
        for h in hits:
            pool[h["source_pdf"] + h["text"][:40]] = h
    items = list(pool.values())
    if reranker and focus and items:                        # rerank the whole pool against the theme
        scores = reranker.predict([(focus, h["text"][:512]) for h in items])
        for h, s in zip(items, scores):
            h["_rr"] = float(s)
        items.sort(key=lambda h: h["_rr"], reverse=True)
    return items[:cap]

def main():
    picks = [a.lower() for a in sys.argv[1:]]
    extra = parse_themes_file(os.path.join(os.path.dirname(__file__), "themes.txt"))
    all_themes = THEMES + extra
    if extra:
        print("loaded %d built-in + %d themes.txt themes" % (len(THEMES), len(extra)))
    themes = [t for t in all_themes if not picks or any(p in t["name"].lower() for p in picks)]
    os.makedirs("logs", exist_ok=True)
    log = os.path.join("logs", "deep_dive_" + datetime.datetime.now().strftime("%Y%m%d_%H%M") + ".md")

    print("loading models once...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load, generate
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr = C.load_reranker()
    model, tok = load(C.GEN_MODEL)
    chat = bool(getattr(tok, "chat_template", None))

    with open(log, "w") as f:
        f.write("# HealthCoach deep-dive briefs\n\nGenerated %s · %d goals · %s\n"
                % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), len(themes), C.GEN_MODEL))

    for i, t in enumerate(themes, 1):
        print("[%d/%d] %s" % (i, len(themes), t["name"]))
        hits = gather(tbl, emb, t["q"], rr, t["focus"])
        if not hits:
            with open(log, "a") as f:
                f.write("\n\n# %s\n\n(nothing in the library covers this.)\n\n---\n" % t["name"])
            continue
        ctx = "\n\n".join("[%s | %s | %s]\n%s" % (h["grade"], h["folder"],
                h.get("doi") or "no-doi", h["text"][:1100]) for h in hits)
        instr = DEEP.format(focus=t["focus"])
        pfx = ("USER PROFILE (tailor the plan to this person):\n%s\n\n" % C.PROFILE) if getattr(C, "PROFILE", "") else ""
        uc = pfx + "CONTEXT:\n%s\n\nTASK: %s" % (ctx, instr)
        if chat:
            prompt = tok.apply_chat_template(
                [{"role": "system", "content": C.SYSTEM},
                 {"role": "user", "content": uc}],
                add_generation_prompt=True, tokenize=False)
        else:
            prompt = "%s\n\n%s\n\nBRIEF:" % (C.SYSTEM, uc)
        ans = generate(model, tok, prompt=prompt, max_tokens=1600, verbose=False).strip()
        seen, srcs = set(), []
        for h in hits:
            if h["source_pdf"] in seen: continue
            seen.add(h["source_pdf"])
            srcs.append("[%s] %s  %s" % (h["grade"], h.get("doi") or "", h["source_pdf"]))
        with open(log, "a") as f:
            f.write("\n\n# %s\n\n%s\n\n**Sources (%d)**\n%s\n\n---\n"
                    % (t["name"], ans, len(srcs), "\n".join("- " + s for s in srcs)))
    print("\nDONE -> %s" % log)

if __name__ == "__main__":
    main()
