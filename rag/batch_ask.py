#!/usr/bin/env python3
"""
Batch-run the coach over a list of questions and log Q + A + sources to a markdown file.
Loads the embedding + MLX models ONCE (fast), then loops. Same guardrails as coach.py.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 batch_ask.py                 # uses questions.txt
  python3 batch_ask.py my_qs.txt       # custom question file
Output -> logs/coach_log_YYYYMMDD_HHMM.md
"""
import os, re, sys, datetime
import coach as C                       # reuse constants + SYSTEM prompt (keeps them in sync)

MAXTOK = int(os.environ.get("MAXTOK", "1400"))

def retrieve(tbl, emb, q, k=8):
    return C.search(tbl, emb, q, k, C.load_reranker())

def main():
    qfile = sys.argv[1] if len(sys.argv) > 1 else "questions.txt"
    qs = [l.strip() for l in open(qfile) if l.strip() and not l.strip().startswith("#")]
    if not qs:
        print("no questions in", qfile); return
    # optional parallel shard:  python3 batch_ask.py FILE i/n   (run i=0..n-1 in separate terminals)
    shard = sys.argv[2] if len(sys.argv) > 2 else None
    tag = ""
    if shard:
        si, sn = (int(x) for x in shard.split("/"))
        qs = [q for k, q in enumerate(qs) if k % sn == si]
        tag = "_shard%dof%d" % (si, sn)
        print("SHARD %d/%d — this process answers %d of the questions" % (si, sn, len(qs)))
    os.makedirs("logs", exist_ok=True)
    # RESUME: set LOGFILE=<path> to append to a fixed log and SKIP questions already answered in it.
    # Re-running the exact same command then continues where it left off (great for the full 912 run).
    log = os.environ.get("LOGFILE") or os.path.join(
        "logs", "coach_log_" + datetime.datetime.now().strftime("%Y%m%d_%H%M") + tag + ".md")
    done, resuming = set(), False
    if os.path.exists(log):
        txt = open(log, encoding="utf-8", errors="ignore").read()
        for m in re.findall(r"^##\s*Q\d+\s*—\s*(.+)$", txt, re.M):
            done.add(m.strip().lower())
        if done:
            resuming = True
            qs = [q for q in qs if q.strip().lower() not in done]
            print("RESUME — %d already answered in %s; %d left" % (len(done), log, len(qs)))
    if not qs:
        print("nothing left to answer — %s is complete." % log); return

    print("loading models once (embedding + MLX)...")
    import lancedb
    from sentence_transformers import SentenceTransformer
    from mlx_lm import load
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    rr = C.load_reranker()
    model = tok = None

    if not resuming:
        with open(log, "w") as f:
            f.write("# HealthCoach coach log\n\nGenerated %s · %d questions · model %s\n"
                    % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), len(qs), C.GEN_MODEL))

    def _hms(s):
        s = int(s); m = s // 60
        return ("%dm%02ds" % (m, s % 60)) if m else ("%ds" % s)
    t0 = datetime.datetime.now()
    for i, q in enumerate(qs, 1):
        el = (datetime.datetime.now() - t0).total_seconds()
        eta = (el / (i - 1) * (len(qs) - i + 1)) if i > 1 else 0
        fill = int(20 * (i - 1) / len(qs))
        bar = "[" + "#" * fill + "." * (20 - fill) + "]"
        print("%s%s %d/%d %3.0f%%  ETA %s  (elapsed %s)\n   Q: %s" % (
            (tag + " ") if tag else "", bar, i, len(qs), 100.0 * (i - 1) / len(qs),
            _hms(eta), _hms(el), q[:90]), flush=True)
        warning = C.SP.urgent_message(q)
        hits = [] if warning else C.search(tbl, emb, q, 8, rr)[0]
        if warning or not hits:
            ans, srcs = warning or C.EC.NO_EVIDENCE, []
        else:
            if model is None:
                model, tok = load(C.GEN_MODEL)
            ans = C.answer_from_hits(model, tok, q, hits, MAXTOK)
            srcs = C.EC.source_lines(hits)
        with open(log, "a") as f:
            f.write("\n\n## Q%d — %s\n\n%s\n\n**Sources**\n%s\n\n---\n"
                    % (i, q, ans, "\n".join("- " + s for s in srcs) or "- none"))
    print("\nDONE — %d answers written to %s" % (len(qs), log))

if __name__ == "__main__":
    main()
