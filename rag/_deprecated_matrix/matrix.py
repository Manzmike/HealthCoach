#!/usr/bin/env python3
"""
Cross-effects MATRIX — "everything affects everything." For every ordered pair (X, Y) of
entities in entities.txt, ask the library "how does X affect Y", grade it, cite the papers,
and — when no human (A/B) evidence exists — fall back to a MECHANISTIC (grade C / chemical-
level) read, clearly marked.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 matrix.py                    # full grid (resumes automatically)
  python3 matrix.py --only creatine    # just pairs touching this slug/name
  python3 matrix.py --undirected       # X<->Y once instead of both directions (~half the pairs)
  python3 matrix.py --max-pairs 300    # generate 300 NEW pairs this run, then stop (chunking)
  python3 matrix.py --fresh            # ignore saved state and start over
  python3 matrix.py --k 6              # passages retrieved per pair

Outputs (logs/):
  matrix_state.json                — STABLE checkpoint (all computed cells). Resume reads this.
  matrix_YYYYMMDD_HHMM.md          — the grid, rendered from state at the end of each run.
  matrix_details_YYYYMMDD_HHMM.md  — per-pair direction, mechanism, grade, and SOURCES.

Why this is a summation problem: N entities -> N*(N-1) ordered pairs (or N*(N-1)/2 undirected).
60 entities = 3,540 ordered pairs. That is HOURS on an 8B. So this script is built to be run
in chunks: it checkpoints after every few pairs and skips anything already done, so you can
Ctrl-C, close the laptop, come back, and re-run — it picks up where it left off. Use
--max-pairs to cap a session. Ctrl-C is safe: it saves state and renders before exiting.

Honesty: same retrieval + guardrails as coach.py. A pair with NO passage at all -> "·"
(na, no generation). A pair with only mechanism/C passages -> a THEORETICAL cell marked "*".
"""
import os, re, sys, json, argparse, datetime, signal
import coach as C

HERE = os.path.dirname(__file__)
STATE = os.path.join(HERE, "logs", "matrix_state.json")

GLYPH = {"up": "↑", "down": "↓", "mixed": "↕", "none": "–", "na": "·"}

CELL_INSTR = (
 "You are filling ONE cell of a cross-effects matrix. Using ONLY the CONTEXT passages, state "
 "how {X} affects {Y} in a healthy late-20s man.\n"
 "Your FIRST line MUST be exactly this format and nothing else:\n"
 "EFFECT: <up|down|mixed|none|na> | <A|B|C> | <=12-word mechanism>\n"
 "  up = {X} raises/improves {Y};  down = lowers/impairs;  mixed = depends/both;\n"
 "  none = evidence says no meaningful effect;  na = passages don't address this pair at all.\n"
 "  grade = strongest grade you relied on. Use C for any mechanism/animal/theoretical read.\n"
 "Then, after a blank line, 2-4 sentences: direction, mechanism, and whether it transfers to a "
 "late-20s man. If there is no direct human (A/B) evidence but the passages give chemistry/"
 "pharmacology, reason at the MECHANISTIC level and say plainly it is THEORETICAL (grade C), "
 "not shown in humans. No dosing protocols for peptides/PP405/JXL069/SARMs. Do not invent "
 "authors/years/titles; cite only by [grade | folder | doi]."
)
FIRST_RE = re.compile(r"EFFECT:\s*(up|down|mixed|none|na)\s*\|\s*([ABCabc])\s*\|\s*(.*)", re.I)

def parse_first(ans):
    for ln in ans.splitlines():
        m = FIRST_RE.search(ln)
        if m:
            return m.group(1).lower(), m.group(2).upper(), m.group(3).strip()
    return "na", "-", ""

def load_entities(path):
    ents = []
    for ln in open(path):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split("::")]
        slug = parts[0]
        disp = parts[1] if len(parts) > 1 and parts[1] else slug.replace("_", " ")
        hint = parts[2] if len(parts) > 2 and parts[2] else disp
        ents.append({"slug": slug, "disp": disp, "hint": hint})
    return ents

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"))
    os.replace(tmp, STATE)      # atomic; a crash mid-write can't corrupt the checkpoint

def render(ents, state, stamp, model_name, gen, mech, skipped):
    grid = os.path.join(HERE, "logs", "matrix_%s.md" % stamp)
    det  = os.path.join(HERE, "logs", "matrix_details_%s.md" % stamp)
    # grid
    cols = ents
    hdr = "| cause ＼ affected | " + " | ".join(c["slug"] for c in cols) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    lines = [hdr, sep]
    for x in ents:
        cells = []
        for y in cols:
            if x["slug"] == y["slug"]:
                cells.append(""); continue
            e = state.get(x["slug"] + "\t" + y["slug"])
            if not e:
                cells.append(""); continue           # not computed yet
            d, g, mk = e["dir"], e.get("grade", "-"), e.get("mech")
            if d == "na":
                cells.append(GLYPH["na"])
            else:
                cells.append("%s%s%s" % (GLYPH.get(d, "?"), g if g != "-" else "", "*" if mk else ""))
        lines.append("| **%s** | %s |" % (x["slug"], " | ".join(cells)))
    legend = ("\n\n**Legend** — cell = *how the ROW affects the COLUMN*.  "
              "%s raises/improves · %s lowers/impairs · %s mixed/depends · %s no meaningful effect · "
              "%s not covered.  Letter = strongest evidence grade (A/B strong, C weak).  "
              "**\\*** = MECHANISTIC / theoretical (no direct human evidence — reasoned from "
              "chemistry/pharmacology).  Blank = not computed yet (resume to fill).\n\n"
              "Full direction, mechanism, transfer note and SOURCES per cell: `%s`.\n"
              % (GLYPH["up"], GLYPH["down"], GLYPH["mixed"], GLYPH["none"], GLYPH["na"],
                 os.path.basename(det)))
    with open(grid, "w") as f:
        f.write("# HealthCoach cross-effects matrix\n\nGenerated %s · %d entities · "
                "%d cells computed (%d mechanistic, %d na) · %s\n\n"
                % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), len(ents),
                   len(state), mech, skipped, model_name))
        f.write("\n".join(lines)); f.write(legend)
    # details
    with open(det, "w") as f:
        f.write("# HealthCoach cross-effects — details\n\nGenerated %s · %s\n"
                % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), model_name))
        for x in ents:
            for y in ents:
                e = state.get(x["slug"] + "\t" + y["slug"])
                if not e or e["dir"] == "na":
                    continue
                f.write("\n\n## %s  →  %s   (%s, grade %s%s)\n\n%s\n\n**Sources**\n%s\n\n---\n"
                        % (x["disp"], y["disp"], e["dir"], e.get("grade", "-"),
                           ", MECHANISTIC" if e.get("mech") else "", e.get("ans", ""),
                           "\n".join("- " + s for s in e.get("srcs", [])) or "- none"))
    return grid, det

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--max-pairs", type=int, default=0)
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--undirected", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()

    ents = load_entities(os.path.join(HERE, "entities.txt"))
    if len(ents) < 2:
        print("need >=2 entities in entities.txt"); return
    only = a.only.lower().strip()

    if a.undirected:
        pairs = [(ents[i], ents[j]) for i in range(len(ents)) for j in range(i + 1, len(ents))]
    else:
        pairs = [(x, y) for x in ents for y in ents if x["slug"] != y["slug"]]
    if only:
        pairs = [(x, y) for (x, y) in pairs if only in x["slug"].lower()
                 or only in y["slug"].lower() or only in x["disp"].lower() or only in y["disp"].lower()]

    state = {} if a.fresh else load_state()
    todo = [(x, y) for (x, y) in pairs if (x["slug"] + "\t" + y["slug"]) not in state]
    print("entities: %d   target pairs: %d   already done: %d   to do this run: %d%s"
          % (len(ents), len(pairs), len(pairs) - len(todo), len(todo),
             ("  (cap %d)" % a.max_pairs) if a.max_pairs else ""))
    if not todo:
        print("nothing to do — all requested pairs already computed. Rendering current state.")

    print("loading models once (embedding + reranker + MLX)...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load, generate
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr = C.load_reranker()
    model, tok = load(C.GEN_MODEL)
    chat = bool(getattr(tok, "chat_template", None))

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    gen = mech = skipped = 0
    stop = {"flag": False}
    def onint(sig, frm):
        print("\n[interrupt] saving state and rendering before exit...")
        stop["flag"] = True
    signal.signal(signal.SIGINT, onint)

    for n, (x, y) in enumerate(todo, 1):
        if stop["flag"] or (a.max_pairs and gen >= a.max_pairs):
            break
        key = x["slug"] + "\t" + y["slug"]
        q = "how does %s affect %s" % (x["hint"], y["hint"])
        print("[%d/%d] %s -> %s" % (n, len(todo), x["slug"], y["slug"]))
        try:
            hits, weak = C.search(tbl, emb, q, a.k, rr)
        except Exception as e:
            print("   retrieval error: %s" % e); continue
        if not hits:
            state[key] = {"dir": "na", "grade": "-", "mech": False}
            skipped += 1
        else:
            banner = ("NOTE: no direct human (A/B) evidence matched — the passages below are "
                      "mechanism/animal (grade C). Reason at the CHEMICAL/mechanistic level and "
                      "mark it THEORETICAL (grade C).\n\n") if weak else ""
            ctx = banner + "\n\n".join("[%s | %s | %s]\n%s" % (
                    h["grade"], h["folder"], h.get("doi") or "no-doi", h["text"][:1000]) for h in hits)
            instr = CELL_INSTR.format(X=x["disp"], Y=y["disp"])
            pfx = ("USER PROFILE (tailor transfer/relevance to this person):\n%s\n\n" % C.PROFILE) if getattr(C, "PROFILE", "") else ""
            uc = pfx + "CONTEXT:\n%s\n\nTASK: %s" % (ctx, instr)
            if chat:
                prompt = tok.apply_chat_template(
                    [{"role": "system", "content": C.SYSTEM}, {"role": "user", "content": uc}],
                    add_generation_prompt=True, tokenize=False)
            else:
                prompt = "%s\n\n%s\n\nCELL:" % (C.SYSTEM, uc)
            ans = generate(model, tok, prompt=prompt, max_tokens=320, verbose=False).strip()
            direction, grade, note = parse_first(ans)
            seen, srcs = set(), []
            for h in hits:
                if h["source_pdf"] in seen: continue
                seen.add(h["source_pdf"])
                srcs.append("[%s] %s  %s" % (h["grade"], h.get("doi") or "", h["source_pdf"]))
            state[key] = {"dir": direction, "grade": grade, "mech": bool(weak),
                          "ans": ans, "srcs": srcs}
            gen += 1
            if weak: mech += 1
        if (gen + skipped) % 10 == 0:
            save_state(state)      # checkpoint every 10 pairs

    save_state(state)
    grid, det = render(ents, state, stamp, C.GEN_MODEL, gen, mech, skipped)
    print("\n%s" % ("STOPPED early (interrupt or --max-pairs) — state saved, safe to resume."
                    if (stop["flag"] or (a.max_pairs and gen >= a.max_pairs)) else "DONE"))
    print("  this run: %d generated (%d mechanistic), %d na" % (gen, mech, skipped))
    print("  total computed cells: %d / %d target" % (len(state), len(pairs)))
    print("  grid    -> %s" % grid)
    print("  details -> %s" % det)
    print("  checkpoint -> %s  (re-run to resume)" % STATE)

if __name__ == "__main__":
    main()
