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

    checks = [
        ("protein intake to preserve lean mass in a calorie deficit", ()),
        ("does creatine cause hair loss", ()),
        ("does boron raise free testosterone in men", ()),
        ("how does zinc affect testosterone", ()),
        ("acetyl-L-carnitine ALCAR cognition or fatigue in healthy adults",
         ("07_supplements/l_carnitine_alcar",)),
        ("citicoline CDP-choline attention and memory in healthy adults",
         ("07_supplements/citicoline_cdp",)),
        ("uridine monophosphate cognition or attention in human trials",
         ("07_supplements/uridine",)),
        ("noopept omberacetam human cognition and product safety",
         ("08_peptides_gray/noopept", "08_peptides_gray/uncertified_quality_risk")),
        ("bromantane Ladasten human fatigue cognition trial",
         ("08_peptides_gray/bromantane",)),
        ("retatrutide obesity human randomized clinical trial adverse effects",
         ("08_peptides_gray/retatrutide",)),
        ("tesamorelin human clinical trial safety glucose IGF-1",
         ("08_peptides_gray/tesamorelin",)),
        ("cerebrolysin human randomized clinical trial safety",
         ("08_peptides_gray/cerebrolysin",)),
        ("liraglutide obesity human randomized trial adverse effects",
         ("05_fat_loss_drugs/liraglutide",)),
        ("survodutide obesity human clinical trial adverse effects",
         ("05_fat_loss_drugs/survodutide",)),
        ("unapproved peptide product identity contamination quality risk",
         ("08_peptides_gray/uncertified_quality_risk",)),
        ("beets beetroot whole food human exercise or blood pressure trial",
         ("01_food_inflammation/beets_dietary_nitrate",)),
        ("oregano culinary food consumption human trial",
         ("01_food_inflammation/oregano",)),
        ("saffron culinary food consumption human trial",
         ("01_food_inflammation/saffron_food",)),
        ("kimchi fermented vegetable consumption human trial",
         ("01_food_inflammation/fermented_veg_sauerkraut_kimchi",)),
        ("tamarind fruit or pulp consumption human trial",
         ("01_food_inflammation/tamarind",)),
        ("blueberry whole fruit consumption human randomized trial",
         ("01_food_inflammation/blueberries",)),
        ("garlic as food consumption human randomized trial",
         ("01_food_inflammation/garlic_food",)),
        ("ginger as food consumption human randomized trial",
         ("01_food_inflammation/ginger_food",)),
        ("honey as food consumption human randomized trial",
         ("01_food_inflammation/honey_food",)),
        ("cinnamon culinary food consumption human trial",
         ("01_food_inflammation/cinnamon_food",)),
        ("turmeric culinary food consumption human trial",
         ("01_food_inflammation/turmeric_food",)),
    ]
    ok = True
    coverage_missing = []
    for q, expected_folders in checks:
        try:
            hits, weak = C.search(tbl, emb, q, 5, rr)
        except Exception as e:
            ok = False
            print("\nQ: %s\n  ERROR: %s" % (q, e))
            continue
        print("\nQ: %s  ->  %d hits%s" % (q, len(hits), "  (weak/C-only)" if weak else ""))
        for h in hits[:3]:
            print("   [%s | %s] %s" % (h["grade"], h["folder"], (h.get("doi") or "no-doi")[:48]))
        if expected_folders and not any(h.get("folder") in expected_folders for h in hits):
            coverage_missing.append(q)
            print("   MISSING EXPECTED FOLDER: %s" % " or ".join(expected_folders))
    if not ok:
        result = "SOME QUERIES FAILED — do not launch the full run yet"
    elif coverage_missing:
        result = "PIPELINE OK — %d FOCUSED COVERAGE GAP(S) REMAIN; report them as NONE/WEAK" % len(coverage_missing)
    else:
        result = "ALL QUERIES OK — focused folders are retrievable"
    print("\n%s" % result)

if __name__ == "__main__":
    main()
