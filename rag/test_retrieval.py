#!/usr/bin/env python3
"""
Fast retrieval sanity check — NO MLX, no generation. Confirms the LanceDB hybrid
search + reranker work before you launch the long batch_ask/matrix run.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate && python3 test_retrieval.py
"""
import lancedb
from sentence_transformers import SentenceTransformer
import coach as C

def main():
    print("lancedb", lancedb.__version__)
    tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
    print("rows in table:", tbl.count_rows())
    emb = SentenceTransformer(C.EMB_MODEL, device="mps")
    rr = C.load_reranker()

    qs = [
        "protein intake to preserve lean mass in a calorie deficit",
        "does creatine cause hair loss",
        "does boron raise free testosterone in men",
        "how does zinc affect testosterone",
    ]
    ok = True
    for q in qs:
        try:
            hits, weak = C.search(tbl, emb, q, 5, rr)
        except Exception as e:
            ok = False
            print("\nQ: %s\n  ERROR: %s" % (q, e))
            continue
        print("\nQ: %s  ->  %d hits%s" % (q, len(hits), "  (weak/C-only)" if weak else ""))
        for h in hits[:3]:
            print("   [%s | %s] %s" % (h["grade"], h["folder"], (h.get("doi") or "no-doi")[:48]))
    print("\n%s" % ("ALL QUERIES OK — safe to run batch_ask.py / matrix.py" if ok
                    else "SOME QUERIES FAILED — do not launch the full run yet"))

if __name__ == "__main__":
    main()
