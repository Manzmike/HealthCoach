#!/usr/bin/env python3
"""
HealthCoach open-access paper acquisition engine.
Stdlib only. Run in a shell that HAS internet (e.g. your real macOS Terminal):

    cd ~/GitHub/HealthCoach/papers
    python3 fetch_papers.py            # full run to quotas
    python3 fetch_papers.py --phase 1  # one phase
    python3 fetch_papers.py --topic meal_prep_deficit_athletic
    python3 fetch_papers.py --selftest # offline logic check, no network

Legal OA only: Europe PMC / PMC OA, Unpaywall best-OA PDF, publisher gold OA,
preprint servers, NIH ODS, government CPGs. No Sci-Hub, no vendor/research-chem
monographs, no blogs/shop PDFs. Dedupe by DOI; one paper reused across folders
is a hardlink, not a copy. Every file logged in MANIFEST.md; every rejection in
SOURCES_FAILED.md.

Grading (heuristic, from Europe PMC pubType + title):
  A systematic review / meta-analysis / guideline / practice-guideline / position stand
  B randomized controlled trial / clinical trial (human)
  C review / animal / mechanism / small / preliminary  (default journal-article)
  D myth-refutation only (never auto-assigned; flagged for manual use)
Confidence must match grade. No claim without a retrieved paper.
"""
import argparse, glob, json, os, re, sys, time, urllib.parse, urllib.request, hashlib

ROOT   = os.path.abspath(os.path.dirname(__file__))          # .../HealthCoach/papers
MANIFEST = os.path.join(ROOT, "MANIFEST.md")
FAILED   = os.path.join(ROOT, "SOURCES_FAILED.md")
EMAIL    = "healthcoach@local"
UA       = "Mozilla/5.0 (Macintosh) HealthCoachAcquire/1.0 (mailto:%s)" % EMAIL
EPMC     = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SLEEP    = 0.34                                              # be polite to APIs

SEEN_DOI  = {}        # doi -> primary filepath (for hardlinks)
SEEN_PMC  = set()
SUCCESS   = 0         # unique PDFs written
_T0       = time.time()
WTAG      = ""        # worker label for parallel shards, e.g. "[W1/3]"

def _hms(s):
    s = int(s); h, m = s // 3600, (s % 3600) // 60
    return ("%dh%02dm" % (h, m)) if h else ("%dm%02ds" % (m, s % 60) if m else "%ds" % s)

def progress(done, total, extra=""):
    """One clean status line: [worker] bar done/total pct  new=N  <extra>  ETA  elapsed."""
    filled = int(20 * done / total) if total else 0
    bar = "[" + "#" * filled + "." * (20 - filled) + "]"
    eta = ""
    if done and total and done < total:
        eta = "ETA %s " % _hms((time.time() - _T0) / done * (total - done))
    pre = (WTAG + " ") if WTAG else ""
    print("%s%s %d/%d %3.0f%%  new=%d  %s %s(elapsed %s)" % (
        pre, bar, done, total, (100.0*done/total if total else 0), SUCCESS,
        extra, eta, _hms(time.time()-_T0)), flush=True)
COUNTS    = {}        # folder -> count

# --------------------------------------------------------------------------- #
#  HTTP helpers
# --------------------------------------------------------------------------- #
def _get(url, binary=False, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
          "Accept": "application/pdf,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")

def _json(url):
    try:
        time.sleep(SLEEP)
        return json.loads(_get(url))
    except Exception as e:
        return {"_error": str(e)}

# --------------------------------------------------------------------------- #
#  naming / grading
# --------------------------------------------------------------------------- #
def slugify(s, n=6):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").lower()).strip("-")
    return "-".join(s.split("-")[:n]) or "untitled"

def grade_of(pubtypes, title):
    pt = " ".join(pubtypes).lower() + " " + (title or "").lower()
    # not-yet-evidence / non-systematic -> never A/B (audit fix)
    if any(k in pt for k in ("study protocol", "trial protocol", " protocol",
            "narrative review", "scoping review", "correspondence", "editorial",
            "case report", "case-report", "erratum", "study-protocol")):
        return "C"
    if any(k in pt for k in ("systematic review", "meta-analysis", "meta analysis",
            "guideline", "practice-guideline", "position stand", "cochrane",
            "network meta", "umbrella review", "consensus statement",
            "consensus guideline", "pooled analysis")):
        return "A"
    if any(k in pt for k in ("randomized controlled", "randomised controlled",
            "randomized", "randomised", "clinical trial", "rct",
            "controlled clinical trial", "crossover", "cross-over")):
        return "B"
    return "C"

def fname(grade, year, topic_slug, title):
    return "%s_%s_%s_%s.pdf" % (grade, year or "0000", topic_slug, slugify(title))

# cohort detection: keep 70-year-old TRT data from being applied to a late-20s male
OLDER_SIGNALS = ("older men", "older adults", "elderly", "geriatric", "postmenopausal",
    "late-onset hypogonadism", "aged 60", "aged 65", "aged 70", "aged 75", "≥60",
    ">=60", "65 years and older", "mean age 6", "mean age 7", "mean age, 6",
    "mean age, 7", "frailty", "nursing home", "andropause")
YOUNG_SIGNALS = ("young men", "young adult", "18-35", "18 to 35", "18-40", "18 to 40",
    "resistance-trained", "resistance trained", "eugonadal", "college-aged",
    "healthy young", "recreationally active", "mean age 2", "mean age, 2",
    "mean age 3", "mean age, 3")
COHORT = {}   # folder -> {"young":n,"older":n,"unknown":n}

def cohort_of(rec):
    txt = ((rec.get("title") or "") + " " + (rec.get("abstract") or "")).lower()
    older = any(s in txt for s in OLDER_SIGNALS)
    young = any(s in txt for s in YOUNG_SIGNALS)
    if older and not young: return "older"
    if young: return "young"
    return "unknown"

# --------------------------------------------------------------------------- #
#  logging
# --------------------------------------------------------------------------- #
def log_manifest(line):
    with open(MANIFEST, "a") as f: f.write(line.rstrip() + "\n")

def log_failed(line):
    with open(FAILED, "a") as f: f.write(line.rstrip() + "\n")

def count_table():
    print("\n--- per-folder counts (running) ---")
    for k in sorted(COUNTS): print("  %-52s %d" % (k, COUNTS[k]))
    print("  TOTAL unique PDFs: %d\n" % SUCCESS)

# --------------------------------------------------------------------------- #
#  PDF resolution (legal OA only) + download
# --------------------------------------------------------------------------- #
def pdf_candidates(rec):
    """Yield candidate OA PDF URLs in priority order."""
    pmcid = rec.get("pmcid")
    doi   = rec.get("doi")
    if rec.get("pdf_url"):                        # direct OA PDF from OpenAlex / S2
        yield ("direct-oa", rec["pdf_url"])
    if pmcid:
        acc = pmcid if pmcid.startswith("PMC") else "PMC" + pmcid
        yield ("europepmc-oa",
               "https://europepmc.org/backend/ptpmcrender.fcgi?accid=%s&blobtype=pdf" % acc)
        yield ("epmc-fulltextpdf", "%s/%s/fullTextPDF" % (EPMC, acc))
    if doi:
        up = _json("https://api.unpaywall.org/v2/%s?email=%s" %
                   (urllib.parse.quote(doi), EMAIL))
        loc = (up or {}).get("best_oa_location") or {}
        if loc.get("url_for_pdf"):
            yield ("unpaywall", loc["url_for_pdf"])
        for l in (up or {}).get("oa_locations", []) or []:
            if l.get("url_for_pdf"):
                yield ("unpaywall-alt", l["url_for_pdf"])

def download_pdf(rec, target):
    for src, url in pdf_candidates(rec):
        try:
            time.sleep(SLEEP)
            data = _get(url, binary=True)
            if data[:5] != b"%PDF-":
                continue
            with open(target, "wb") as f: f.write(data)
            return target, src, url
        except Exception:
            continue
    return None, None, None

# --------------------------------------------------------------------------- #
#  Europe PMC search + citation chaining
# --------------------------------------------------------------------------- #
def epmc_search(query, oa_only=True, page_size=25):
    q = query + (" AND (OPEN_ACCESS:y)" if oa_only else "")
    url = "%s/search?query=%s&format=json&resultType=core&pageSize=%d" % (
          EPMC, urllib.parse.quote(q), page_size)
    hits = (_json(url).get("resultList") or {}).get("result", []) or []
    out = []
    for h in hits:
        pt = []
        ptl = h.get("pubTypeList") or {}
        if isinstance(ptl.get("pubType"), list): pt = ptl["pubType"]
        elif ptl.get("pubType"):                 pt = [ptl["pubType"]]
        out.append({
            "title": h.get("title", "").strip(". "),
            "year":  h.get("pubYear"),
            "doi":   (h.get("doi") or "").lower() or None,
            "pmcid": h.get("pmcid"),
            "pmid":  h.get("pmid"),
            "isoa":  h.get("isOpenAccess") == "Y",
            "pubtypes": pt,
            "abstract": h.get("abstractText", "") or "",
            "source": h.get("source"),
            "id":    h.get("id"),
        })
    return out

def epmc_related(source, ext_id, kind):
    """kind in {references, citations}. Returns list of {source,id}."""
    url = "%s/%s/%s/%s?format=json&pageSize=100" % (EPMC, source, ext_id, kind)
    d = _json(url)
    key = kind + "List"
    lst = (d.get(key) or {}).get("reference" if kind == "references" else "citation", [])
    res = []
    for x in (lst or []):
        if x.get("id") and x.get("source"):
            res.append((x["source"], x["id"]))
    return res

def hydrate(source, ext_id):
    url = "%s/search?query=EXT_ID:%s AND SRC:%s&format=json&resultType=core&pageSize=1" % (
          EPMC, ext_id, source)
    r = (_json(url).get("resultList") or {}).get("result", [])
    if not r: return None
    return epmc_search("EXT_ID:%s AND SRC:%s" % (ext_id, source), oa_only=False, page_size=1)[:1]

# --------------------------------------------------------------------------- #
#  Extra OA providers: OpenAlex + Semantic Scholar (widen the net past EPMC).
#  Return records in the SAME shape as epmc_search so acquire() treats them
#  identically — same DOI dedup, same anchor gate, same grading, same PPR->C cap.
# --------------------------------------------------------------------------- #
OPENALEX = "https://api.openalex.org"
S2       = "https://api.semanticscholar.org/graph/v1"
PREPRINT_HOSTS = ("biorxiv", "medrxiv", "arxiv", "researchsquare", "research-square",
                  "preprints.org", "ssrn", "chemrxiv", "osf.io", "vixra")

def _is_preprint(url, typ, venue):
    s = " ".join([(url or ""), (typ or ""), (venue or "")]).lower()
    return "preprint" in s or any(h in s for h in PREPRINT_HOSTS)

def _oa_abstract(inv):
    """Reconstruct an abstract from OpenAlex's inverted index."""
    if not inv: return ""
    try:
        pos = {}
        for w, ixs in inv.items():
            for i in ixs: pos[i] = w
        return " ".join(pos[i] for i in sorted(pos))[:3000]
    except Exception:
        return ""

def openalex_search(query, n=25):
    url = ("%s/works?search=%s&filter=is_oa:true&per-page=%d&mailto=%s"
           % (OPENALEX, urllib.parse.quote(query), n, EMAIL))
    out = []
    for w in (_json(url).get("results") or []):
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower() or None
        loc = w.get("primary_location") or {}
        boa = w.get("best_oa_location") or {}
        oa  = w.get("open_access") or {}
        pdf = loc.get("pdf_url") or boa.get("pdf_url") or oa.get("oa_url")
        venue = ((loc.get("source") or {}) or {}).get("display_name") or ""
        ids = w.get("ids") or {}
        pmcid = ids["pmcid"].split("/")[-1] if ids.get("pmcid") else None
        typ = w.get("type") or ""
        rec = {"title": (w.get("title") or w.get("display_name") or "").strip(". "),
               "year": w.get("publication_year"), "doi": doi, "pmcid": pmcid, "pmid": None,
               "isoa": True, "pubtypes": [typ] if typ else [],
               "abstract": _oa_abstract(w.get("abstract_inverted_index")),
               "source": "PPR" if _is_preprint(pdf, typ, venue) else "OAX",
               "pdf_url": pdf, "id": w.get("id")}
        if rec["title"] and (doi or pmcid or pdf): out.append(rec)
    return out

def s2_search(query, n=25):
    fields = "title,year,abstract,externalIds,openAccessPdf,publicationTypes,venue"
    url = ("%s/paper/search?query=%s&limit=%d&fields=%s"
           % (S2, urllib.parse.quote(query), n, fields))
    out = []
    for w in (_json(url).get("data") or []):
        ext = w.get("externalIds") or {}
        doi = (ext.get("DOI") or "").lower() or None
        pmcid = ext.get("PubMedCentral")
        if pmcid and not str(pmcid).startswith("PMC"): pmcid = "PMC" + str(pmcid)
        pdf = (w.get("openAccessPdf") or {}).get("url")
        m = []
        for p in (w.get("publicationTypes") or []):
            p = (p or "").lower()
            if "meta" in p: m.append("meta-analysis")
            elif "clinicaltrial" in p: m.append("clinical trial")
            elif "review" in p: m.append("review")
            else: m.append(p)
        venue = w.get("venue") or ""
        rec = {"title": (w.get("title") or "").strip(". "), "year": w.get("year"),
               "doi": doi, "pmcid": pmcid, "pmid": ext.get("PubMed"),
               "isoa": bool(pdf), "pubtypes": m, "abstract": w.get("abstract") or "",
               "source": "PPR" if _is_preprint(pdf, "", venue) else "S2",
               "pdf_url": pdf, "id": w.get("paperId")}
        if rec["title"] and (doi or pmcid or pdf): out.append(rec)
    return out

def extra_search(query):
    """OpenAlex + Semantic Scholar, merged and de-duped within the call."""
    seen, out = set(), []
    for prov in (openalex_search, s2_search):
        try:
            recs = prov(query)
        except Exception as e:
            print("   extra_search %s failed: %s" % (prov.__name__, e)); recs = []
        for r in recs:
            k = r.get("doi") or r.get("pmcid") or r.get("pdf_url")
            if not k or k in seen: continue
            seen.add(k); out.append(r)
    return out

# --------------------------------------------------------------------------- #
#  acquire one record into one-or-more folders (dedupe + hardlink)
# --------------------------------------------------------------------------- #
def acquire(rec, folder_rel, topic_slug, also_folders=(), tag_cohort=False):
    global SUCCESS
    rec["grade"] = grade_of(rec.get("pubtypes", []), rec.get("title", ""))
    if rec.get("source") == "PPR" and rec["grade"] in ("A", "B"):
        rec["grade"] = "C"                       # unreviewed preprint: never A/B
    doi = rec.get("doi"); pmc = rec.get("pmcid")
    key = doi or pmc
    if not key: return False
    if not anchor_ok(folder_rel, rec):           # topic-anchor gate (audit fix)
        log_failed("- OFF-TOPIC | %s | %s | %s" % (
            folder_rel, doi or pmc, (rec.get("title") or "")[:70]))
        return False
    folder_abs = os.path.join(ROOT, folder_rel)
    os.makedirs(folder_abs, exist_ok=True)
    coh = cohort_of(rec) if tag_cohort else None
    if coh == "older":
        topic_slug = topic_slug + "_older-cohort"

    if key in SEEN_DOI or (pmc and pmc in SEEN_PMC):
        primary = SEEN_DOI.get(key) or SEEN_DOI.get(pmc)
        if primary and os.path.exists(primary):
            link = os.path.join(folder_abs, os.path.basename(primary))
            if not os.path.exists(link):
                try:
                    os.link(primary, link)
                    COUNTS[folder_rel] = COUNTS.get(folder_rel, 0) + 0  # dup, not unique
                    log_manifest("| %s | %s | %s | %s | %s | HARDLINK of %s |" % (
                        rec["grade"], rec.get("year"), doi or pmc, folder_rel,
                        os.path.basename(link), os.path.relpath(primary, ROOT)))
                except OSError:
                    pass
        return False  # not a new unique paper

    target = os.path.join(folder_abs,
             fname(rec["grade"], rec.get("year"), topic_slug, rec.get("title", "")))
    # already have this exact file on disk -> register and skip (no re-download)
    if os.path.exists(target) and os.path.getsize(target) > 1000:
        SEEN_DOI[key] = target
        if doi: SEEN_DOI[doi] = target
        if pmc: SEEN_PMC.add(pmc)
        return False
    path, src, url = download_pdf(rec, target)
    if not path:
        log_failed("- FAIL pdf | %s | %s | %s | no OA PDF resolved" % (
            rec["grade"], doi or pmc, rec.get("title", "")[:80]))
        return False
    SEEN_DOI[key] = path
    if doi: SEEN_DOI[doi] = path
    if pmc: SEEN_PMC.add(pmc)
    SUCCESS += 1
    if tag_cohort:
        C = COHORT.setdefault(folder_rel, {"young": 0, "older": 0, "unknown": 0})
        C[coh] += 1
    COUNTS[folder_rel] = COUNTS.get(folder_rel, 0) + 1
    log_manifest("| %s | %s | %s | %s | %s | %s %s |" % (
        rec["grade"], rec.get("year"), doi or pmc, folder_rel,
        os.path.basename(path), src, url))
    for extra in also_folders:
        if not anchor_ok(extra, rec):            # don't hardlink off-topic into a sibling
            continue
        ea = os.path.join(ROOT, extra); os.makedirs(ea, exist_ok=True)
        link = os.path.join(ea, os.path.basename(path))
        if not os.path.exists(link):
            try:
                os.link(path, link)
                log_manifest("| %s | %s | %s | %s | %s | HARDLINK of %s |" % (
                    rec["grade"], rec.get("year"), doi or pmc, extra,
                    os.path.basename(link), folder_rel))
            except OSError: pass
    if SUCCESS % 10 == 0: count_table()
    return True

# --------------------------------------------------------------------------- #
#  run a topic to quota, with citation chaining and AA overlay
# --------------------------------------------------------------------------- #
AA_TERMS = ('("African American" OR Black OR "African ancestry" OR "skin of color")')
AA_PER_TOPIC = 6      # cap AA-overlay pulls per topic (prevents 12_population_AA ballooning)

# TOPIC-ANCHOR GATE (audit fix): a paper is only filed in a folder if its title/abstract
# contains one of that folder's keywords. Folders not listed are ungated (e.g. 12_population_AA).
ANCHORS = {
 'active_recall_memory':['memory','recall','retrieval','spaced','encoding','learning','forgetting','testing effect'],
 'sedentary_software_engineer':['sit','sedentary','standing','desk','screen','office','workstation'],
 'daily_athletic_movements':['walk','gait','step','carry','squat','hinge','movement','mobility','locomot','physical activity','neat','ruck'],
 'concurrent_hybrid_lift_run':['concurrent','endurance','resistance','strength','running','aerobic','hybrid','interference','training'],
 'compressed_4x10_schedule':['workweek','work-week','compressed','shift','working hour','four-day','4-day','10-hour','long hour','schedule','overtime'],
 'omega3':['omega','epa','dha','fish oil','n-3','polyunsaturat','fatty acid'],
 'curcumin':['curcumin','turmeric'],'copper_foods':['copper'],
 'beets_dietary_nitrate':['nitrate','beet'],
 'fermented_veg_sauerkraut_kimchi':['kimchi','sauerkraut','fermented','lacto'],
 'fermented_soy':['natto','tempeh','miso','soy'],
 'fermented_legumes_beans':['ferment','legume','bean'],'fermented_beets':['ferment','beet'],
 'creatine':['creatine'],'beta_alanine':['beta-alanine','carnosine','β-alanine'],
 'citrulline_arginine':['citrulline','arginine'],'sodium_bicarbonate':['bicarbonate'],
 'l_theanine':['theanine'],'tyrosine':['tyrosine'],'ashwagandha':['ashwagandha','withania'],
 'rhodiola':['rhodiola'],'collagen_vitc_tendon':['collagen','tendon','gelatin'],
 'tart_cherry':['cherry','montmorency'],'glucosamine_chondroitin':['glucosamine','chondroitin'],
 'electrolytes_hydration':['hydration','electrolyte','sodium','fluid','hyponatremia'],
 'multivitamin_efficacy':['multivitamin','multi-vitamin'],
 'supplement_contamination_testing':['contaminat','adulterat','undeclared','prohibited substance','third-party','certif','dshea','tainted','doping','purity'],
 'caffeine':['caffeine','coffee'],
 'tak_653':['tak-653','tak653','ampa'],'bromantane':['bromantane','ladasten','actoprotector'],
 'semax_selank':['semax','selank','noopept','acth','melanocortin','nootropic','peptide'],'cerebrolysin':['cerebrolysin'],
 'racetams':['racetam','piracetam','nootropic'],
 'ped_sarms_aas_harms':['steroid','anabolic','sarm','androgen','prohormone','doping','testosterone'],
 'thyroid_hypo_hyper_function':['thyroid','tsh','hypothyroid','hyperthyroid','graves','thyrotox','levothyrox'],
 'lipids_apob_ldl':['apob','apo-b','ldl','cholesterol','lipid','lipoprotein','statin'],
 'young_adult_male_norms':['testosterone','tsh','apob','vo2','reference','norm','body fat','young','25-hydroxy'],
 'male_hpg_testosterone_estradiol':['testosterone','estradiol','estrogen','hypogonad','hpg','aromatase','luteiniz','fsh'],
 'meal_prep_deficit_athletic':['protein','meal','diet','deficit','weight loss','body composition','hypocaloric','carbohydrate','satiety','lean mass','energy','fiber','mediterranean'],
 'foods_to_exclude_upf':['ultra-processed','ultraprocessed','sugar-sweetened','trans fat','processed meat','alcohol','energy drink','added sugar','upf','soft drink'],
 'physique_hypertrophy_selection':['hypertrophy','muscle','resistance','exercise','strength','physique','muscular','training volume','repetition'],
 'whole_foods_nutrient_dense':['whole food','nutrient','diet quality','vegetable','fruit','legume','micronutrient','dietary pattern','nuts','grain','food'],
 'foods_for_body_composition':['protein','satiety','food','diet','muscle','lean','fiber','energy density','leucine','appetite'],
 'foods_for_brain_cognition':['diet','cognit','brain','omega','fish','flavonoid','polyphenol','choline','glycemic','mediterranean','food','nutrient'],
 'zinc':['zinc'],'iron':['iron','ferritin'],'vitamin_c':['vitamin c','ascorbic'],
 'calcium_vitamin_k2':['calcium','vitamin k','menaquinone','bone'],
 'iodine_selenium':['iodine','selenium','thyroid'],
 'heat_acclimatization':['heat','hot','humid','thermoregul','acclimat','warm','temperature'],
 'core_abs_training':['core','abdominal','trunk','oblique','plank','abs'],
 'interactions_stacking':['interaction','absorption','bioavailab','combined','concomitant','nutrient','drug','supplement'],
 'daily_stretching_mobility':['stretch','mobility','flexibility','range of motion','rom','warm'],
 'fermented_foods_overview':['ferment','probiotic','microbiome','kefir','yogurt','kombucha','gut'],
 # ---- ROUND 7 ----
 'glycine':['glycine'],
 'taurine':['taurine'],
 'betaine_tmg':['betaine','trimethylglycine','tmg'],
 'boron':['boron'],
 'nac':['n-acetylcysteine','acetylcysteine','n-acetyl','nac','glutathione','cysteine'],
 'berberine':['berberine'],
 'lactoferrin':['lactoferrin','lactoglobulin'],
 'magnesium':['magnesium','mg2+'],
 'carb_timing_training':['carbohydrate','carb','glycogen','nutrient timing','pre-exercise','post-exercise','meal timing','glucose'],
 'oats_beta_glucan':['oat','beta-glucan','β-glucan','glucan','whole grain'],
 'carbohydrate_metabolism':['carbohydrate','glucose','insulin','glycemic','glycaemic','metabolism'],
 'prolactin':['prolactin','hyperprolactin','dopamine agonist'],
 'dht_regulation':['dihydrotestosterone','dht','5-alpha','5α','reductase','androgen'],
 'stress_hair_loss':['telogen','effluvium','hair loss','hair follicle','alopecia','cortisol','stress'],
 # ---- ROUND 8 (milk) ----
 'milk_types_comparison':['milk','dairy','skim','whole milk','low-fat','plant-based','fortified','lactose'],
 'goat_milk':['goat milk','goat','caprine'],
 'raw_milk_safety':['raw milk','unpasteuriz','pasteuriz','listeria','campylobacter','brucell','e. coli','salmonella'],
 'milk_body_composition':['milk','dairy','calcium','whey','casein','protein','satiety','body composition','weight','lean mass'],
 # ---- ROUND 9 (deep supplement bench) ----
 'vitamin_d3':['vitamin d','cholecalciferol','25-hydroxy','vitamin d3','25(oh)d'],
 'vitamin_b12_folate':['b12','cobalamin','folate','folic','methylfolate','homocysteine','one-carbon'],
 'vitamin_e_tocotrienols':['vitamin e','tocopherol','tocotrienol'],
 'coq10_ubiquinol':['coenzyme q','coq10','coq-10','ubiquinol','ubiquinone'],
 'alpha_lipoic_acid':['lipoic acid','alpha-lipoic','α-lipoic','thioctic'],
 'l_carnitine_alcar':['carnitine','acetyl-l-carnitine','alcar'],
 'hmb':['hmb','hydroxymethylbutyrate','beta-hydroxy-beta','β-hydroxy'],
 'eaa_bcaa':['amino acid','bcaa','leucine','eaa','branched-chain','branched chain'],
 'glutamine':['glutamine'],
 'inositol_myo':['inositol','myo-inositol'],
 'chromium_glucose':['chromium','picolinate'],
 'cinnamon_glucose':['cinnamon','cinnamaldehyde','cassia'],
 'tongkat_ali':['tongkat','eurycoma','longjack','eurycomanone','longifolia'],
 'fadogia_agrestis':['fadogia'],
 'shilajit':['shilajit','fulvic','mumijo'],
 'maca':['maca','lepidium'],
 'tribulus':['tribulus','protodioscin','terrestris'],
 'fenugreek':['fenugreek','trigonella'],
 'panax_ginseng':['ginseng','panax','ginsenoside'],
 'saw_palmetto':['saw palmetto','serenoa'],
 'nettle_pygeum':['nettle','urtica','pygeum','africanum'],
 'resveratrol':['resveratrol'],
 'quercetin':['quercetin'],
 'fisetin':['fisetin'],
 'spermidine':['spermidine'],
 'sulforaphane':['sulforaphane','broccoli sprout','glucoraphanin'],
 'egcg_green_tea':['green tea','egcg','catechin','epigallocatechin'],
 'astaxanthin':['astaxanthin'],
 'bacopa_monnieri':['bacopa','bacoside'],
 'lions_mane':["lion's mane",'lions mane','hericium','erinaceus','erinacine','hericenone'],
 'ginkgo_biloba':['ginkgo','ginkgo biloba'],
 'citicoline_cdp':['citicoline','cdp-choline','cytidine','cdp choline'],
 'phosphatidylserine':['phosphatidylserine'],
 'melatonin':['melatonin'],
 'l_tryptophan_5htp':['tryptophan','5-htp','5-hydroxytryptophan'],
 'apigenin':['apigenin'],
 'msm_joint':['methylsulfonylmethane','msm'],
 'boswellia':['boswellia','boswellic'],
 # ---- ROUND 12 (peptide landscape) ----
 'bpc157':['bpc-157','bpc157','bpc 157','body protection compound','pentadecapeptide'],
 'tb500_thymosin_b4':['thymosin beta','thymosin β4','tb-500','tb500','thymosin β-4','thymosin beta-4','thymosin beta 4'],
 'ghk_cu':['ghk-cu','ghk cu','ghk','copper peptide','copper tripeptide','glycyl-histidyl-lysine'],
 'mots_c':['mots-c','mots c','mitochondrial-derived peptide','mitochondrial derived peptide'],
 'kpv':['kpv','lysine-proline-valine'],
 'ipamorelin':['ipamorelin'],
 'cjc1295':['cjc-1295','cjc1295','cjc 1295'],
 'tesamorelin':['tesamorelin','egrifta'],
 'sermorelin':['sermorelin'],
 'hexarelin':['hexarelin'],
 'ghrp2_6':['ghrp-6','ghrp-2','ghrp','growth hormone releasing peptide','growth hormone-releasing peptide'],
 'semaglutide':['semaglutide','ozempic','wegovy'],
 'retatrutide':['retatrutide'],
 'pt141_bremelanotide':['bremelanotide','pt-141','pt 141','vyleesi'],
 'melanotan':['melanotan','afamelanotide','melanocyte-stimulating hormone','melanocortin'],
 'thymosin_alpha1':['thymosin alpha','thymosin α1','thymalfasin','thymosin alpha-1','thymosin alpha 1'],
 'll37':['ll-37','ll37','cathelicidin'],
 'epitalon':['epitalon','epithalon','epithalamin'],
 'dihexa':['dihexa'],
 'follistatin':['follistatin'],
 'aod9604':['aod9604','aod-9604','aod 9604','176-191','fragment 176'],
 'igf1_lr3':['igf-1 lr3','igf1 lr3','igf-i lr3','long r3','insulin-like growth factor'],
 # ---- ROUND 13 (clothing / fabric) ----
 'clothing_fabric_body':['fabric','textile','clothing','garment','cotton','polyester','nylon','wool','synthetic','wicking','microplastic'],
 # ---- ROUND 14 (catalog gap-fill) ----
 'mk677_ibutamoren':['mk-677','mk677','mk 677','ibutamoren','nutrobal'],
 'mgf_mechano_growth':['mechano growth factor','mechano-growth','mgf','igf-1ec','peg-mgf'],
 'dsip':['delta sleep-inducing','delta sleep inducing','dsip'],
 'agomelatine':['agomelatine','valdoxan'],
 'noopept':['noopept','gvs-111','omberacetam'],
 'phenibut':['phenibut','phenyl-gaba','fenibut'],
 'aniracetam':['aniracetam'],
 'isrib':['isrib','integrated stress response inhibitor','eif2b'],
 'methylene_blue':['methylene blue','methylthioninium'],
 'humanin':['humanin'],
 'aicar':['aicar','aminoimidazole carboxamide','acadesine'],
 'slu_pp_332':['slu-pp-332','slu pp 332','estrogen-related receptor','err agonist','errα'],
 'five_amino_1mq':['5-amino-1mq','5-amino-1-methylquinolinium','nnmt inhibitor','nnmt inhibition'],
 'oxytocin':['oxytocin'],
 'liraglutide':['liraglutide','saxenda','victoza'],
 'cagrilintide':['cagrilintide','amylin analog','cagrisema'],
 'survodutide':['survodutide'],
 'tesofensine':['tesofensine'],
 'enclomiphene':['enclomiphene','clomiphene'],
 'kisspeptin':['kisspeptin','kiss1','metastin'],
 'gonadorelin':['gonadorelin','gnrh','gonadotropin-releasing hormone','luteinizing hormone-releasing'],
 'glutathione':['glutathione','gsh'],
 'nad_nmn':['nmn','nicotinamide mononucleotide','nicotinamide riboside','nad+','nad precursor','nicotinamide adenine dinucleotide'],
 'research_peptides_misc':['ara-290','cibinetide','adipotide','foxo4','fox04','senolytic','pe-22-28','spadin','snap-8','acetyl octapeptide','vasoactive intestinal peptide','pnc-27'],
 'peptide_bioregulators_khavinson':['khavinson','bioregulator','vilon','thymalin','pinealon','cortexin','cortagen','livagen','prostamax','testagen','vesugen','cytogen','cytomax','bronchogen','cartalax','chonluten','cardiogen','thymogen','epitalon','epithalon'],
 # ---- ROUND 15 (parasites / antiparasitics / deworming — human) ----
 'ivermectin_human':['ivermectin','avermectin','strongyloid','scabies','onchocerc','mass drug administration','antiparasit','mectizan'],
 'antiparasitic_deworming_humans':['deworm','anthelmintic','anthelminthic','albendazole','mebendazole','praziquantel','helminth','soil-transmitted','ascaris','hookworm','trichuris','nitazoxanide','pyrantel','ivermectin','schistosom'],
 'intestinal_parasites_humans':['parasit','helminth','giardia','protozoa','tapeworm','pinworm','roundworm','worm infection','enterobius','blastocystis','cryptosporidi','ascaris','hookworm','amebiasis','entamoeba'],
 # ---- ROUND 15 (cravings) ----
 'sugar_cravings_control':['craving','sugar','sweet','added sugar','reward','appetite','snack'],
 'food_craving_appetite_control':['craving','appetite','satiety','hunger','reward','fullness','snack','food cue','palatab'],
 # ---- ROUND 15b (source coverage for new question clusters) ----
 'energy_availability_reds':['energy availability','red-s','red s','reds','relative energy deficiency','low energy','underfuel','under-fuel','under-eating','undereating','athlete triad'],
 'sleep_apnea_breathing':['apnea','apnoea','osa','sleep-disordered','sleep disordered','snor','cpap','ahi','upper airway','desaturation','obstructive'],
 'endurance_fueling_carbs':['carbohydrate','carbs','fuel','gel','glycogen','gastric emptying','gut training','ingestion','intake during','race nutrition','fluid','glucose','fructose','gastrointestinal'],
 'athlete_cardiac_health':['cardiac','heart','arrhythm','atrial fibrillation','coronary','athlete','myocard','ecg','electrocardiog','cardiovascular','calcium'],
 'overtraining_overreaching':['overtrain','overreach','training load','hrv','heart rate variability','monitoring','fatigue','maladaptation','recovery'],
 'exercise_immunity_vaccines':['immune','immunity','infection','respiratory','urti','vaccine','vaccinat','influenza','antibody','exercise'],
 # ---- ROUND 15c (colostrum + EMF/wireless) ----
 'bovine_colostrum':['colostrum','colostral','lactoferrin','immunoglobulin','igg','growth factor','first milk'],
 'emf_wireless_bluetooth':['electromagnetic','radiofrequency','rf-emf','rf emf','emf','wireless','bluetooth','cell phone','mobile phone','radiation','sar','5g','wi-fi','wifi'],
}
def anchor_ok(folder_rel, rec):
    kws = ANCHORS.get(os.path.basename(folder_rel))
    if not kws: return True
    txt = ((rec.get("title") or "") + " " + (rec.get("abstract") or "")).lower()
    return any(k in txt for k in kws)

def aboost_topic(t):
    """A-HUNT pass: pull OA systematic reviews / meta-analyses / guidelines / RCTs for a topic
       and keep ONLY grade A/B (anchor-checked). Run with:  ABOOST=1 python3 fetch_papers.py
       (optionally ABOOST_N=12 for a bigger top-up). Idempotent — dedup skips what's on disk."""
    folder = t["folder"]; slug = t["slug"]
    also = tuple(t.get("also", ())); tc = t.get("cohort", False)
    os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
    COUNTS[folder] = max(COUNTS.get(folder, 0), len(glob.glob(os.path.join(ROOT, folder, "*.pdf"))))
    kws = ANCHORS.get(os.path.basename(folder)) or [slug.replace("-", " ")]
    core = kws[0]
    n = int(os.environ.get("ABOOST_N", "8"))
    cap = COUNTS[folder] + n
    print("\n%s== ABOOST %s (have %d, hunting up to +%d A/B) ==" % ((WTAG+" ") if WTAG else "", folder, COUNTS[folder], n))
    qs = ["%s systematic review" % core,
          "%s meta-analysis" % core,
          "%s clinical practice guideline" % core,
          "%s randomized controlled trial" % core]
    if len(kws) > 1:
        qs.append("%s %s systematic review meta-analysis" % (kws[0], kws[1]))
    for q in qs:
        if COUNTS.get(folder, 0) >= cap: break
        try:
            recs = epmc_search(q)
        except Exception as e:
            log_failed("- ABOOST query err | %s | %s" % (folder, e)); continue
        for rec in recs:
            if COUNTS.get(folder, 0) >= cap: break
            if grade_of(rec.get("pubtypes", []), rec.get("title", "")) in ("A", "B") \
               and anchor_ok(folder, rec):
                acquire(rec, folder, slug, also_folders=also, tag_cohort=tc)
    print("  -> %s now %d PDFs" % (folder, COUNTS.get(folder, 0)))

def run_topic(t):
    if os.environ.get("ABOOST"):
        return aboost_topic(t)
    folder = t["folder"]; slug = t["slug"]; qmin = t["min"]; qstretch = t["stretch"]
    also = tuple(t.get("also", ()))        # hardlink every hit into these folders too
    tc   = t.get("cohort", False)          # tag young/older cohort (hormone job)
    folder_abs = os.path.join(ROOT, folder)
    os.makedirs(folder_abs, exist_ok=True)
    # seed count from PDFs ALREADY on disk (idempotent re-runs)
    on_disk = len(glob.glob(os.path.join(folder_abs, "*.pdf")))
    COUNTS[folder] = max(COUNTS.get(folder, 0), on_disk)
    print("\n%s==== TOPIC %s (have %d, min %d) ====" % ((WTAG+" ") if WTAG else "", folder, COUNTS[folder], qmin))
    # REFETCH=<substr,substr> forces matching topics to re-pull through ALL providers
    # (OpenAlex + S2 included), even if already at min — the deep-source top-up.
    _refetch = [x.strip() for x in os.environ.get("REFETCH", "").split(",") if x.strip()]
    # REFETCH=all widens EVERY topic; a category prefix (e.g. 02_training_desk,03_sleep_stress)
    # widens a whole domain; a bare slug widens one topic. Substring match against folder path.
    force = ("all" in _refetch) or any(x in folder for x in _refetch)
    if force:
        qstretch = COUNTS[folder] + 12          # push the net to find up to ~12 more
        print("  REFETCH — widening net (target +12 via OpenAlex/S2/EPMC)")
    # SKIP ENTIRELY if we already have what we need
    if COUNTS[folder] >= qmin and not force:
        print("  SKIP — already have %d PDFs on disk (>= min %d)" % (COUNTS[folder], qmin))
        return
    have = lambda: COUNTS.get(folder, 0)         # absolute total, incl. on-disk
    aa_ct = [0]                      # AA-overlay pulls this topic (capped)
    queue = []                       # (source,id) from chaining
    # 1) seed IDs first
    for sid in t.get("seeds", []):
        rec = hydrate(*sid) if isinstance(sid, tuple) else None
        if rec:
            acquire(rec[0], folder, slug, also_folders=also, tag_cohort=tc)
            queue += epmc_related(sid[0], sid[1], "references")
            queue += epmc_related(sid[0], sid[1], "citations")
    # 2) queries (prefer reviews/meta/RCT via EPMC ranking)
    for q in t.get("queries", []):
        if have() >= qstretch: break
        for rec in epmc_search(q):
            if have() >= qstretch: break
            if acquire(rec, folder, slug, also_folders=also, tag_cohort=tc) and rec.get("pmcid"):
                queue.append(("PMC", rec["pmcid"]))
        # 2b) widen the net past Europe PMC: OpenAlex + Semantic Scholar.
        #     Runs when EPMC hasn't filled the topic — the fix for thin compounds
        #     (Fadogia, bromantane, Semax, TAK-653) that EPMC barely indexes.
        if have() < qstretch:
            for rec in extra_search(q):
                if have() >= qstretch: break
                if acquire(rec, folder, slug, also_folders=also, tag_cohort=tc) and rec.get("pmcid"):
                    queue.append(("PMC", rec["pmcid"]))
        # AA overlay query (capped per topic)
        if t.get("aa", True) and aa_ct[0] < AA_PER_TOPIC:
            for rec in epmc_search(q + " AND " + AA_TERMS):
                if aa_ct[0] >= AA_PER_TOPIC: break
                if acquire(rec, "12_population_AA", "aa-"+slug,
                           also_folders=tuple([folder]) + also, tag_cohort=tc):
                    aa_ct[0] += 1
    # 3) citation chain until min met
    seen_q = set()
    for (s, i) in queue:
        if have() >= qmin: break
        if (s, i) in seen_q: continue
        seen_q.add((s, i))
        r = hydrate(s, i)
        if r: acquire(r[0], folder, slug, also_folders=also, tag_cohort=tc)
    if tc:
        c = COHORT.get(folder, {"young": 0, "older": 0, "unknown": 0})
        print("  cohort: young=%d older=%d unknown=%d" % (c["young"], c["older"], c["unknown"]))
    if have() < qmin:
        log_manifest("> NOTE %s: OA exhausted at %d (min %d)" % (folder, have(), qmin))
        print("  OA exhausted at %d / min %d" % (have(), qmin))
    else:
        print("  reached %d (min %d)" % (have(), qmin))

# --------------------------------------------------------------------------- #
#  TOPIC CONFIG  (folder, slug, min, stretch, queries, seeds, aa)
#  seeds are (SRC, EXT_ID): SRC in {MED=PubMed PMID, PMC=PMCID, DOI}
# --------------------------------------------------------------------------- #
def T(folder, slug, mn, st, queries, seeds=(), aa=True, also=(), cohort=False):
    return {"folder": folder, "slug": slug, "min": mn, "stretch": st,
            "queries": queries, "seeds": list(seeds), "aa": aa,
            "also": list(also), "cohort": cohort}

TOPICS = [
  # ---------------- PHASE 1 priority ----------------
  T("01_food_inflammation/meal_prep_deficit_athletic", "mealprep-deficit", 12, 20, [
     "high protein meal prep adherence weight loss",
     "batch cooking diet quality randomized",
     "Mediterranean high protein hypocaloric randomized",
     "protein 1.6 2.2 g/kg fat loss lean mass meta-analysis",
     "energy density fiber satiety randomized",
     "breakfast protein cognition",
     "resistance training energy deficit lean mass meta-analysis"]),
  T("01_food_inflammation/foods_to_exclude_upf", "foods-exclude-upf", 12, 20, [
     "ultra-processed food systematic review mortality",
     "sugar-sweetened beverages meta-analysis cardiometabolic",
     "industrial trans fat cardiovascular disease",
     "alcohol sleep architecture review",
     "energy drinks arrhythmia",
     "processed meat colorectal cancer meta-analysis",
     "added sugar dental caries systematic review"]),
  T("02_training_desk/concurrent_hybrid_lift_run", "concurrent-lift-run", 12, 20, [
     "concurrent training interference running resistance meta-analysis",
     "training order resistance before endurance",
     "resistance training volume hypertrophy meta-analysis",
     "weekly training frequency hypertrophy meta-analysis",
     "diet break vs continuous energy deficit"],
     seeds=[("MED","22027800"),("PMC","PMC10933151")]),
  T("02_training_desk/compressed_4x10_schedule", "compressed-4x10", 12, 20, [
     "compressed workweek systematic review health",
     "four-day workweek compressed vs reduced hours",
     "10-hour shift 4/10 sleep fatigue",
     "long working hours cognitive performance",
     "compressed workweek fatigue recovery"], aa=True),
  T("02_training_desk/sedentary_software_engineer", "sedentary-swe", 12, 20, [
     "sit-stand workstation meta-analysis",
     "interrupting prolonged sitting glucose",
     "occupational sitting intervention office workers",
     "sedentary behaviour cardiometabolic meta-analysis",
     "breaking up sitting postprandial glucose randomized"]),
  T("03_sleep_stress/sleep_best_practices", "sleep-cbti", 12, 20, [
     "CBT-I insomnia systematic review",
     "AASM insomnia clinical practice guideline",
     "sleep restriction weight loss",
     "morning bright light circadian phase",
     "fixed wake time social jetlag"]),
  T("04_cognition_learning/active_recall_memory", "active-recall", 12, 20, [
     "retrieval practice testing effect meta-analysis",
     "spaced repetition distributed practice meta-analysis",
     "interleaving practice learning",
     "Dunlosky learning techniques review",
     "retrieval practice transfer meta-analysis"]),
  T("01_food_inflammation/omega3", "omega3", 12, 20, [
     "EPA DHA triglyceride meta-analysis",
     "omega-3 fatty acids cardiovascular meta-analysis",
     "omega-3 depression randomized meta-analysis",
     "omega-3 muscle protein synthesis",
     "fish oil inflammation CRP meta-analysis"],
     seeds=[("DOI","na")]),
  T("06_hair_teeth/aga_hair_loss_growth", "aga-approved", 12, 20, [
     "androgenetic alopecia network meta-analysis minoxidil finasteride dutasteride",
     "oral minoxidil androgenetic alopecia",
     "topical finasteride androgenetic alopecia randomized",
     "low level laser therapy androgenetic alopecia",
     "CCCA central centrifugal cicatricial alopecia review",
     "traction alopecia review"],
     seeds=[("MED","38852607")]),
  # ---------------- PHASE 1 remainder ----------------
  T("01_food_inflammation/fermented_veg_sauerkraut_kimchi", "fermented-veg", 8, 15, [
     "kimchi systematic review health",
     "sauerkraut IBS randomized",
     "fermented vegetables gut microbiome randomized"]),
  T("01_food_inflammation/fermented_soy", "fermented-soy", 8, 15, [
     "natto tempeh miso fermented soybean human",
     "fermented soy cardiovascular meta-analysis"]),
  T("01_food_inflammation/beets_dietary_nitrate", "beet-nitrate", 8, 15, [
     "beetroot nitrate blood pressure meta-analysis",
     "dietary nitrate exercise performance meta-analysis"]),
  T("01_food_inflammation/anti_inflammatory_patterns", "anti-inflam-diet", 8, 15, [
     "dietary inflammatory index meta-analysis",
     "Mediterranean DASH CRP randomized"]),
  T("01_food_inflammation/curcumin", "curcumin", 8, 15, [
     "curcumin osteoarthritis randomized",
     "curcumin bioavailability meta-analysis",
     "curcumin inflammation CRP meta-analysis"]),
  T("01_food_inflammation/copper_foods", "copper", 6, 10, [
     "dietary copper status human",
     "copper deficiency review"], aa=False),
  T("02_training_desk/lifting_programming", "lifting-prog", 8, 15, [
     "resistance training volume dose response hypertrophy",
     "training to failure hypertrophy meta-analysis",
     "full body vs split routine hypertrophy"]),
  T("02_training_desk/cutting_fat_loss_methods", "cutting", 8, 15, [
     "energy deficit lean mass preservation resistance training",
     "protein intake weight loss lean mass meta-analysis"]),
  T("02_training_desk/daily_athletic_movements", "athletic-movements", 8, 15, [
     "fundamental movement patterns training",
     "loaded carry farmer walk",
     "zone 2 cardiorespiratory fitness",
     "load carriage rucking",
     "walking cadence health outcomes",
     "breaking up sitting movement snacks"]),
  T("02_training_desk/software_engineer_performance_health", "swe-perf-health", 8, 15, [
     "software developer burnout working hours",
     "job demands resources knowledge workers",
     "programmer interruptions productivity"]),
  T("03_sleep_stress/schedule_consistency_circadian", "schedule-consistency", 8, 15, [
     "sleep regularity index mortality",
     "social jetlag metabolic health",
     "fixed sleep schedule circadian"]),
  T("03_sleep_stress/sunlight_circadian", "sunlight-circadian", 8, 15, [
     "morning outdoor light circadian rhythm",
     "light exposure mood alertness randomized"]),
  T("03_sleep_stress/burnout", "burnout", 8, 15, [
     "burnout intervention systematic review",
     "workplace stress management randomized"]),
  T("03_sleep_stress/cortisol", "cortisol", 8, 15, [
     "ashwagandha cortisol randomized",
     "psychological stress cortisol intervention",
     "caffeine cortisol response"]),
  T("03_sleep_stress/life_stress", "life-stress", 6, 10, [
     "chronic stress allostatic load review",
     "mindfulness stress reduction meta-analysis"]),
  T("03_sleep_stress/sleep_food_supplement_lifestyle", "sleep-supp", 8, 15, [
     "magnesium sleep randomized",
     "melatonin sleep onset meta-analysis",
     "tart cherry sleep randomized"]),
  T("04_cognition_learning/neuroplasticity_bdnf", "bdnf", 8, 15, [
     "aerobic exercise BDNF humans meta-analysis",
     "exercise neuroplasticity review"]),
  T("04_cognition_learning/dopamine", "dopamine", 6, 10, [
     "dopamine motivation cognition review",
     "reward prediction error learning"]),
  T("04_cognition_learning/anxiety_cognition", "anxiety", 8, 15, [
     "exercise anxiety meta-analysis",
     "anxiety cognitive performance"]),
  T("04_cognition_learning/neuroinflammation", "neuroinflammation", 6, 10, [
     "peripheral inflammation CRP cognition review",
     "neuroinflammation depression review"]),
  T("04_cognition_learning/caffeine", "caffeine", 8, 15, [
     "caffeine exercise performance meta-analysis",
     "caffeine sleep onset latency",
     "caffeine anxiety dose"]),
  # ---------------- PHASE 2 ----------------
  T("05_fat_loss_drugs/tirzepatide_incretins", "tirzepatide", 8, 15, [
     "tirzepatide obesity randomized SURMOUNT",
     "tirzepatide weight regain withdrawal",
     "tirzepatide obstructive sleep apnea",
     "obesity pharmacotherapy systematic review"],
     seeds=[("PMC","PMC11967144")]),
  T("05_fat_loss_drugs/diet_exercise_cutting", "diet-exercise-cut", 6, 10, [
     "diet plus exercise weight loss meta-analysis",
     "exercise weight maintenance meta-analysis"]),
  T("06_hair_teeth/beard_growth", "beard", 6, 10, [
     "topical minoxidil beard randomized",
     "facial hair growth androgen"]),
  T("06_hair_teeth/teeth_remineralization_caries", "teeth-remin", 8, 15, [
     "CPP-ACP remineralization systematic review",
     "fluoride varnish caries prevention meta-analysis",
     "white spot lesion remineralization randomized"]),
  T("06_hair_teeth/pp405_suvomipic", "pp405", 6, 12, [
     "PP405 Pelage alopecia",
     "suvomipic alopecia",
     "mitochondrial pyruvate carrier hair follicle stem cell",
     "lactate dehydrogenase hair follicle stem cell activation"],
     seeds=[("DOI","10.1038/ncb3575")], aa=False),   # Flores 2017-adjacent
  T("06_hair_teeth/jxl069_mpc_chemistry", "jxl069", 4, 8, [
     "JXL069 mitochondrial pyruvate carrier inhibitor",
     "UK-5099 mitochondrial pyruvate carrier",
     "7-azaindole mitochondrial pyruvate carrier inhibitor hair"],
     seeds=[("MED","33534563"),("PMC","PMC8939290")], aa=False),
  T("07_supplements/alpha_gpc", "alpha-gpc", 6, 10, [
     "alpha-GPC power output randomized",
     "alpha-GPC cognition human randomized"], aa=False),
  T("07_supplements/supplement_timing", "supp-timing", 6, 10, [
     "nutrient timing protein meta-analysis",
     "peri-workout protein vs daily total"], aa=False),
  T("07_supplements/general_ods_position_stands", "position-stands", 6, 10, [
     "ISSN position stand",
     "creatine supplementation position stand"], aa=False),
  T("09_hormones_sex/tadalafil", "tadalafil", 6, 10, [
     "tadalafil erectile dysfunction systematic review",
     "tadalafil 5 mg daily lower urinary tract symptoms"], aa=False),
  T("09_hormones_sex/estrogen_estradiol_men", "estradiol-men", 6, 10, [
     "estradiol men bone health",
     "aromatase inhibitor healthy men adverse",
     "male hypogonadism guideline"], aa=False),
  # ---------------- PHASE 3 nootropics ----------------
  T("08_peptides_gray/racetams", "racetams", 6, 10, [
     "piracetam cognition Cochrane",
     "phenylpiracetam",
     "nootropic systematic review cognition"], aa=False),
  T("08_peptides_gray/bromantane", "bromantane", 6, 10, [
     "bromantane Ladasten actoprotector",
     "bromantane asthenia randomized"],
     seeds=[("PMC","PMC3762282")], aa=False),
  T("08_peptides_gray/tak_653", "tak653", 6, 10, [
     "TAK-653 AMPA receptor potentiator clinical",
     "TAK-653 healthy volunteers"], aa=False),
  # ---------------- PHASE 4 gray peptides (document the GAP) ----------------
  T("08_peptides_gray/research_peptides_reviews", "gray-peptides", 5, 10, [
     "BPC-157 systematic review human evidence",
     "TB-500 thymosin beta-4 human",
     "MOTS-c human",
     "KPV peptide",
     "FDA compounding bulk peptides restriction"], aa=False),
  T("08_peptides_gray/uncertified_quality_risk", "peptide-quality", 5, 10, [
     "research use only peptide purity contamination",
     "unregulated peptide product quality"], aa=False),
  T("08_peptides_gray/semax_selank", "semax-selank", 8, 14, [
     "Semax cognition BDNF",
     "Selank anxiety clinical",
     "ACTH 4-10 analog cognition memory",
     "noopept cognition neuroprotection",
     "melanocortin peptide nootropic",
     "Semax stroke cognitive",
     "regulatory peptide nootropic cognition"], aa=False),
  T("08_peptides_gray/cerebrolysin", "cerebrolysin", 5, 10, [
     "cerebrolysin ischaemic stroke Cochrane",
     "cerebrolysin vascular dementia Cochrane"], aa=False),
  # ---------------- PHASE 5 ----------------
  T("09_hormones_sex/porn_csbd", "csbd", 5, 8, [
     "compulsive sexual behavior disorder review",
     "problematic pornography use systematic review",
     "CBT compulsive sexual behavior"], aa=False),
  T("09_hormones_sex/semen_retention_evidence", "semen-retention", 5, 8, [
     "sexual abstinence testosterone",
     "ejaculation testosterone levels",
     "semen retention health claims evidence"], aa=False),
  T("11_neuro_advanced/mushrooms_clinical", "mushrooms", 5, 10, [
     "UV vitamin D mushrooms randomized",
     "ergothioneine review",
     "psilocybin major depression randomized"], aa=False),
  T("11_neuro_advanced/genetic_modification_clinical_only", "crispr-clinical", 4, 6, [
     "CRISPR sickle cell disease exagamglogene review",
     "Casgevy clinical trial review"], aa=False),
  T("10_recovery_fascia/muscle_skeletal_recovery", "recovery", 6, 10, [
     "sleep muscle recovery review",
     "sleep deprivation muscle recovery"], aa=False),
  T("10_recovery_fascia/fascia_stretching_rom", "fascia-rom", 6, 10, [
     "stretching versus strength training range of motion meta-analysis",
     "stretching range of motion Behm Konrad meta-analysis"], aa=False),
  T("13_vaccines_immunology/covid19_vaccine_pk_clearance", "covid-vax-pk", 6, 10, [
     "COVID-19 mRNA vaccine pharmacokinetics biodistribution",
     "spike protein antigenemia after mRNA vaccination",
     "lipid nanoparticle clearance mRNA vaccine",
     "COVID-19 vaccine mRNA detectable duration",
     "COVID-19 vaccine myocarditis systematic review"], aa=False),

  # ---------------- SUPPLEMENTS (added round 2) ----------------
  T("07_supplements/creatine", "creatine", 6, 10, [
     "creatine monohydrate resistance training meta-analysis",
     "creatine supplementation cognition randomized",
     "creatine safety kidney review",
     "creatine dihydrotestosterone hair loss",
     "creatine loading protocol"], aa=False),
  T("07_supplements/beta_alanine", "beta-alanine", 6, 10, [
     "beta-alanine exercise performance meta-analysis",
     "beta-alanine carnosine high intensity"], aa=False),
  T("07_supplements/citrulline_arginine", "citrulline", 6, 10, [
     "citrulline malate exercise performance randomized",
     "L-citrulline blood flow nitric oxide"], aa=False),
  T("07_supplements/sodium_bicarbonate", "bicarbonate", 6, 10, [
     "sodium bicarbonate exercise performance meta-analysis",
     "bicarbonate loading high intensity"], aa=False),
  T("07_supplements/l_theanine", "l-theanine", 6, 10, [
     "L-theanine caffeine cognition randomized",
     "theanine attention stress randomized"], aa=False),
  T("07_supplements/tyrosine", "tyrosine", 6, 10, [
     "tyrosine cognition stress randomized",
     "tyrosine working memory supplementation"], aa=False),
  T("07_supplements/ashwagandha", "ashwagandha", 6, 10, [
     "ashwagandha strength testosterone randomized",
     "ashwagandha stress cortisol randomized",
     "ashwagandha sleep randomized"], aa=False),
  T("07_supplements/rhodiola", "rhodiola", 6, 10, [
     "Rhodiola rosea fatigue randomized",
     "rhodiola mental performance stress"], aa=False),
  T("07_supplements/collagen_vitc_tendon", "collagen", 6, 10, [
     "collagen peptides tendon randomized",
     "vitamin C collagen synthesis connective tissue",
     "gelatin collagen injury prevention"], aa=False),
  T("07_supplements/tart_cherry", "tart-cherry", 6, 10, [
     "tart cherry muscle recovery randomized",
     "tart cherry sleep randomized"], aa=False),
  T("07_supplements/glucosamine_chondroitin", "glucosamine", 6, 10, [
     "glucosamine chondroitin osteoarthritis meta-analysis"], aa=False),
  T("07_supplements/electrolytes_hydration", "electrolytes", 6, 10, [
     "hydration exercise performance review",
     "exertional hyponatremia endurance",
     "sodium supplementation endurance performance"], aa=False),
  T("07_supplements/multivitamin_efficacy", "multivitamin", 6, 10, [
     "multivitamin mortality randomized",
     "multivitamin supplementation cognition randomized"], aa=False),
  T("07_supplements/supplement_contamination_testing", "supp-safety", 6, 10, [
     "dietary supplement contamination adulteration",
     "supplement third party testing certification",
     "DSHEA dietary supplement regulation review",
     "tainted supplements FDA analysis"], aa=False),

  # ---------------- NEW CROSS-TOPICS (added round 2) ----------------
  T("02_training_desk/running_injury_load", "running-injury", 6, 10, [
     "running related injury prevention systematic review",
     "Achilles tendinopathy heavy slow resistance",
     "patellofemoral pain exercise randomized",
     "running injury risk factors"], cohort=True, aa=False),
  T("10_recovery_fascia/nsaids_training_adaptation", "nsaids-adaptation", 6, 10, [
     "NSAID resistance training muscle hypertrophy",
     "ibuprofen exercise adaptation",
     "anti-inflammatory drugs tendon healing"], cohort=True, aa=False),
  T("02_training_desk/desk_eye_screen", "eye-screen", 6, 10, [
     "digital eye strain computer vision syndrome",
     "screen time myopia adults",
     "20-20-20 rule eye strain randomized"], aa=False),
  T("02_training_desk/desk_low_back_neck", "desk-msk", 6, 10, [
     "exercise low back pain office workers randomized",
     "neck pain desk workers exercise",
     "workplace ergonomic intervention musculoskeletal"], aa=False),
  T("10_recovery_fascia/sauna_heat_therapy", "sauna-heat", 6, 10, [
     "sauna cardiovascular health",
     "heat therapy exercise recovery",
     "sauna bathing mortality"], cohort=True, aa=False),
  T("10_recovery_fascia/cold_water_immersion", "cold-immersion", 6, 10, [
     "cold water immersion recovery meta-analysis",
     "cold water immersion hypertrophy attenuation",
     "cryotherapy muscle recovery randomized"], cohort=True, aa=False),
  T("02_training_desk/blood_flow_restriction", "bfr", 6, 10, [
     "blood flow restriction training hypertrophy meta-analysis",
     "blood flow restriction strength rehabilitation"], cohort=True, aa=False),

  # ---------------- ROUND 3 (gaps + user requests) ----------------
  T("08_peptides_gray/ped_sarms_aas_harms", "ped-harms", 6, 10, [
     "anabolic androgenic steroid cardiovascular harm review",
     "selective androgen receptor modulator SARM adverse effects",
     "SARM hepatotoxicity liver injury",
     "prohormone supplement liver injury",
     "anabolic steroid endocrine suppression recovery axis",
     "image performance enhancing drugs harm reduction"], cohort=True, aa=False),
  T("01_food_inflammation/meal_timing_fasting", "meal-timing", 6, 10, [
     "time-restricted eating randomized weight loss",
     "intermittent fasting metabolic health meta-analysis",
     "time-restricted eating resistance training lean mass",
     "early versus late time-restricted eating"], aa=False),
  T("01_food_inflammation/gut_fiber_ibs", "gut-fiber", 6, 10, [
     "dietary fiber gut microbiome randomized",
     "prebiotic supplementation health randomized",
     "low FODMAP diet irritable bowel syndrome randomized",
     "dietary fiber cardiovascular meta-analysis",
     "gut-brain axis review"], aa=False),
  T("01_food_inflammation/fermented_legumes_beans", "fermented-beans", 5, 8, [
     "fermented legume health human",
     "fermented bean product nutrition antinutrients",
     "fermented lima bean"], aa=False),
  T("01_food_inflammation/fermented_beets", "fermented-beets", 5, 8, [
     "fermented beetroot nitrate",
     "beet kvass lacto-fermentation",
     "fermented vegetable juice blood pressure"], aa=False),
  T("15_health_maintenance/immune_resilience", "immune", 6, 10, [
     "exercise upper respiratory tract infection athletes",
     "vitamin D respiratory tract infection meta-analysis",
     "zinc common cold meta-analysis",
     "sleep immune function review",
     "training load immune function"], aa=False),
  T("15_health_maintenance/skin_health", "skin", 6, 10, [
     "sunscreen photoprotection skin aging randomized",
     "acne diet dairy glycemic load",
     "ultraviolet photoaging prevention",
     "sunscreen skin cancer prevention"], aa=True),
  T("15_health_maintenance/body_composition_measurement", "bodycomp", 6, 10, [
     "DXA body composition validity",
     "bioelectrical impedance accuracy body fat",
     "body composition assessment methods review"], aa=False),
  T("15_health_maintenance/breathwork_hrv", "breathwork-hrv", 6, 10, [
     "slow breathing blood pressure randomized",
     "heart rate variability biofeedback stress randomized",
     "HRV-guided training endurance",
     "breathing exercises anxiety randomized"], aa=False),
  T("15_health_maintenance/desk_environment_focus", "desk-env", 6, 10, [
     "indoor carbon dioxide cognitive performance",
     "office air quality cognition",
     "attention digital distraction knowledge workers",
     "deep work interruptions focus"], aa=False),
  # refusal / debunk corpus — NOT a detox protocol
  T("13_vaccines_immunology/no_detox_protocol", "no-detox", 4, 6, [
     "nattokinase spike protein claims evidence",
     "ivermectin COVID-19 ineffective systematic review",
     "chlorine dioxide health harm",
     "post-vaccination detox misinformation",
     "COVID-19 vaccine misinformation debunk"], aa=False),

  # ---------------- ROUND 4 (final gaps) ----------------
  T("01_food_inflammation/alcohol_training_recovery", "alcohol", 6, 10, [
     "alcohol muscle protein synthesis recovery",
     "alcohol athletic performance review",
     "alcohol sleep architecture randomized",
     "moderate alcohol cardiovascular meta-analysis"], aa=False),
  T("03_sleep_stress/bluelight_evening_screens", "bluelight", 6, 10, [
     "evening screen light melatonin suppression",
     "blue light blocking glasses sleep randomized",
     "smartphone use before bed sleep quality"], aa=False),
  T("03_sleep_stress/jetlag_shift_travel", "jetlag-shift", 6, 10, [
     "jet lag melatonin management",
     "shift work circadian adaptation",
     "travel across time zones athletes performance"], aa=False),
  T("06_hair_teeth/periodontal_systemic", "periodontal", 6, 10, [
     "periodontal disease cardiovascular systematic review",
     "periodontitis systemic inflammation",
     "oral health systemic disease review"], aa=False),
  T("15_health_maintenance/hearing_protection", "hearing", 6, 10, [
     "noise induced hearing loss prevention",
     "personal music player hearing loss",
     "earplugs recreational noise hearing protection"], aa=False),

  # ---------------- ROUND 5 (gap fill: physique + whole foods) ----------------
  T("02_training_desk/physique_hypertrophy_selection", "physique", 10, 16, [
     "muscle hypertrophy exercise selection",
     "regional hypertrophy muscle activation resistance training",
     "training volume hypertrophy dose response meta-analysis",
     "repetition range hypertrophy meta-analysis",
     "resistance training exercise variation muscle growth",
     "muscle protein synthesis resistance exercise"], cohort=True, aa=False),
  T("01_food_inflammation/whole_foods_nutrient_dense", "whole-foods", 10, 16, [
     "diet quality nutrient density health outcomes",
     "fruit and vegetable intake mortality meta-analysis",
     "legumes nuts whole grains cardiometabolic health",
     "nutrient dense foods micronutrient adequacy",
     "food-first nutrition athletes micronutrients",
     "dietary patterns and health meta-analysis"], aa=False),
  T("01_food_inflammation/foods_for_body_composition", "bodycomp-foods", 10, 16, [
     "high protein foods satiety weight loss",
     "protein quality leucine food sources muscle",
     "energy density satiety foods body weight",
     "dietary fiber satiety appetite",
     "food choices preserve lean mass energy deficit",
     "protein distribution whole foods muscle protein synthesis"], aa=False),
  T("01_food_inflammation/foods_for_brain_cognition", "brain-foods", 10, 16, [
     "diet and cognitive function meta-analysis",
     "oily fish omega-3 cognition",
     "flavonoids polyphenols cognitive function",
     "choline eggs cognition",
     "glycemic load and cognitive performance",
     "Mediterranean diet cognition"], aa=False),

  # ---------------- ROUND 6 (micronutrient + gap coverage for the question bank) ----------------
  T("07_supplements/zinc", "zinc", 8, 12, [
     "zinc immune function supplementation",
     "zinc testosterone men",
     "zinc common cold meta-analysis",
     "zinc deficiency supplementation"], aa=False),
  T("07_supplements/iron", "iron-ferritin", 8, 12, [
     "iron deficiency supplementation fatigue",
     "ferritin iron status athletes",
     "iron supplementation performance",
     "iron overload risk supplementation"], aa=False),
  T("07_supplements/vitamin_c", "vitamin-c", 8, 12, [
     "vitamin C immune function",
     "vitamin C supplementation exercise adaptation",
     "ascorbic acid antioxidant supplementation"], aa=False),
  T("07_supplements/calcium_vitamin_k2", "calcium-k2", 8, 12, [
     "calcium supplementation bone density",
     "vitamin K2 menaquinone bone cardiovascular",
     "calcium vitamin D bone health"], aa=False),
  T("07_supplements/iodine_selenium", "iodine-selenium", 8, 12, [
     "iodine thyroid function supplementation",
     "selenium thyroid autoimmunity",
     "iodine deficiency adults",
     "selenium supplementation health"], aa=False),
  T("02_training_desk/heat_acclimatization", "heat-acclim", 8, 12, [
     "heat acclimatization exercise training",
     "exercise performance in the heat",
     "hydration and endurance in hot humid conditions",
     "thermoregulation heat stress athletes"], cohort=True, aa=False),
  T("02_training_desk/core_abs_training", "core-abs", 8, 12, [
     "core training abdominal muscle activation",
     "trunk stability exercise performance",
     "abdominal muscle hypertrophy resistance training"], cohort=True, aa=False),
  T("07_supplements/interactions_stacking", "supp-interactions", 8, 14, [
     "mineral interactions absorption zinc iron calcium copper",
     "dietary supplement drug interactions review",
     "nutrient nutrient interactions bioavailability",
     "combined supplementation ergogenic aids",
     "supplement safety concomitant use"], aa=False),
  T("10_recovery_fascia/daily_stretching_mobility", "daily-stretch", 8, 14, [
     "daily stretching flexibility range of motion",
     "mobility training joint health",
     "stretching injury prevention evidence",
     "dynamic versus static stretching recovery",
     "hip shoulder spine mobility desk workers"], cohort=True, aa=False),
  T("01_food_inflammation/fermented_foods_overview", "fermented-overview", 10, 16, [
     "fermented foods systematic review health",
     "fermented foods gut microbiome",
     "kefir yogurt fermented dairy health",
     "kombucha health effects",
     "probiotic fermented foods immunity inflammation"], aa=False),

  # ---------------- ROUND 7 (under-the-radar supps + carbs + hormone detail) ----------------
  T("07_supplements/glycine", "glycine", 8, 12, [
     "glycine supplementation sleep quality", "glycine metabolic health", "glycine collagen synthesis"], aa=False),
  T("07_supplements/taurine", "taurine", 8, 12, [
     "taurine exercise performance", "taurine cardiovascular health", "taurine supplementation review"], aa=False),
  T("07_supplements/betaine_tmg", "betaine-tmg", 8, 12, [
     "betaine trimethylglycine power performance", "betaine homocysteine", "TMG supplementation body composition"], aa=False),
  T("07_supplements/boron", "boron", 8, 12, [
     "boron testosterone free testosterone SHBG", "boron supplementation bone", "boron estrogen inflammation"], aa=False),
  T("07_supplements/nac", "nac", 8, 12, [
     "N-acetylcysteine glutathione antioxidant", "NAC supplementation health", "N-acetylcysteine mental health"], aa=False),
  T("07_supplements/berberine", "berberine", 8, 12, [
     "berberine glucose metabolism", "berberine insulin sensitivity", "berberine lipid cholesterol"], aa=False),
  T("07_supplements/lactoferrin", "lactoferrin", 8, 12, [
     "lactoferrin immune function", "lactoferrin iron absorption", "lactoferrin antimicrobial supplementation"], aa=False),
  T("07_supplements/magnesium", "magnesium", 8, 14, [
     "magnesium glycinate citrate bioavailability form", "magnesium supplementation sleep blood pressure",
     "magnesium status thyroid function", "magnesium deficiency health"], aa=False),
  T("01_food_inflammation/carb_timing_training", "carb-timing", 10, 16, [
     "carbohydrate timing exercise performance", "pre versus post exercise carbohydrate",
     "nutrient timing carbohydrate glycogen resynthesis", "energy balance versus meal timing weight"], aa=False),
  T("01_food_inflammation/oats_beta_glucan", "oats-betaglucan", 8, 14, [
     "oat beta-glucan cholesterol LDL", "beta-glucan glycemic response", "oats whole grain cardiometabolic health"], aa=False),
  T("01_food_inflammation/carbohydrate_metabolism", "carb-metabolism", 8, 14, [
     "carbohydrate metabolism insulin glucose", "glycemic index metabolic health", "dietary carbohydrate glucose regulation"], aa=False),
  T("14_hormones_thyroid_heart/prolactin", "prolactin", 8, 12, [
     "prolactin regulation men", "hyperprolactinemia causes treatment", "prolactin exercise stress"], cohort=True, aa=False),
  T("14_hormones_thyroid_heart/dht_regulation", "dht", 8, 12, [
     "dihydrotestosterone 5-alpha reductase", "DHT androgen physiology", "5-alpha reductase activity regulation"], cohort=True, aa=False),
  T("06_hair_teeth/stress_hair_loss", "stress-hairloss", 8, 12, [
     "telogen effluvium stress hair loss", "psychological stress and hair loss", "cortisol hair follicle cycling"], aa=False),

  # ---------------- ROUND 8 (milk: types, raw, goat, and cutting) ----------------
  T("01_food_inflammation/milk_types_comparison", "milk-types", 8, 14, [
     "cow milk versus plant-based milk nutritional comparison",
     "whole milk versus skim milk health outcomes",
     "milk fat dairy cardiometabolic health",
     "dairy milk nutrient density protein calcium",
     "milk consumption and health systematic review"], aa=False),
  T("01_food_inflammation/goat_milk", "goat-milk", 6, 10, [
     "goat milk nutritional composition versus cow milk",
     "goat milk digestibility tolerance",
     "goat milk protein and micronutrients human"], aa=False),
  T("01_food_inflammation/raw_milk_safety", "raw-milk", 6, 12, [
     "raw unpasteurized milk health effects",
     "raw milk pathogen outbreak Listeria Campylobacter risk",
     "pasteurization effect on milk nutrients and proteins",
     "raw milk claimed benefits evidence review"], aa=False),
  T("01_food_inflammation/milk_body_composition", "milk-cutting", 8, 14, [
     "dairy milk intake weight loss body composition randomized",
     "milk protein casein whey satiety appetite",
     "dairy calcium and fat loss energy balance",
     "milk post-exercise muscle protein synthesis recovery",
     "high protein dairy preserving lean mass calorie deficit"], aa=False),

  # ---------------- ROUND 9 (deep supplement bench + mechanism substrate) ----------------
  # each topic carries a mechanism/pharmacology query so grade-C chemical-level data is captured
  T("07_supplements/vitamin_d3", "vitamin-d3", 8, 14, [
     "vitamin D supplementation testosterone muscle strength", "vitamin D status immune bone health",
     "vitamin D receptor mechanism physiology"], aa=False),
  T("07_supplements/vitamin_b12_folate", "b12-folate", 6, 10, [
     "vitamin B12 folate supplementation deficiency", "methylfolate homocysteine methylation",
     "B12 folate one-carbon metabolism mechanism"], aa=False),
  T("07_supplements/vitamin_e_tocotrienols", "vitamin-e", 6, 10, [
     "vitamin E tocopherol tocotrienol supplementation health", "vitamin E antioxidant exercise",
     "tocotrienol mechanism lipid oxidation"], aa=False),
  T("07_supplements/coq10_ubiquinol", "coq10", 6, 12, [
     "coenzyme Q10 ubiquinol supplementation exercise", "CoQ10 statin cardiovascular",
     "coenzyme Q10 mitochondrial electron transport mechanism"], aa=False),
  T("07_supplements/alpha_lipoic_acid", "ala", 6, 12, [
     "alpha-lipoic acid glucose insulin sensitivity", "alpha lipoic acid antioxidant neuropathy",
     "lipoic acid mitochondrial mechanism redox"], aa=False),
  T("07_supplements/l_carnitine_alcar", "carnitine", 6, 12, [
     "L-carnitine supplementation fat oxidation exercise", "acetyl-L-carnitine cognition fatigue",
     "carnitine fatty acid transport mitochondria mechanism"], aa=False),
  T("07_supplements/hmb", "hmb", 6, 12, [
     "HMB beta-hydroxy-beta-methylbutyrate muscle", "HMB resistance training lean mass",
     "HMB leucine metabolite mechanism muscle protein"], aa=False),
  T("07_supplements/eaa_bcaa", "eaa-bcaa", 6, 12, [
     "essential amino acids muscle protein synthesis", "BCAA supplementation exercise muscle",
     "leucine mTOR signaling mechanism"], aa=False),
  T("07_supplements/glutamine", "glutamine", 6, 10, [
     "glutamine supplementation immune gut exercise", "glutamine muscle recovery",
     "glutamine metabolism enterocyte mechanism"], aa=False),
  T("07_supplements/inositol_myo", "inositol", 6, 10, [
     "myo-inositol insulin sensitivity metabolic", "inositol mood anxiety",
     "inositol second messenger insulin signaling mechanism"], aa=False),
  T("07_supplements/chromium_glucose", "chromium", 6, 10, [
     "chromium picolinate glucose insulin", "chromium supplementation body weight",
     "chromium insulin receptor mechanism"], aa=False),
  T("07_supplements/cinnamon_glucose", "cinnamon", 6, 10, [
     "cinnamon supplementation blood glucose HbA1c", "cinnamon insulin sensitivity",
     "cinnamaldehyde glucose uptake mechanism"], aa=False),
  T("07_supplements/tongkat_ali", "tongkat", 6, 12, [
     "Eurycoma longifolia tongkat ali testosterone", "tongkat ali libido stress cortisol",
     "eurycomanone SHBG mechanism androgen"], cohort=True, aa=False),
  T("07_supplements/fadogia_agrestis", "fadogia", 6, 10, [
     "Fadogia agrestis testosterone", "Fadogia agrestis luteinizing hormone animal",
     "Fadogia agrestis mechanism toxicity"], cohort=True, aa=False),
  T("07_supplements/shilajit", "shilajit", 6, 10, [
     "shilajit fulvic acid testosterone", "shilajit supplementation fatigue performance",
     "fulvic acid mechanism mitochondria"], cohort=True, aa=False),
  T("07_supplements/maca", "maca", 6, 10, [
     "maca Lepidium meyenii libido mood", "maca supplementation energy performance",
     "maca mechanism hormone-independent"], aa=False),
  T("07_supplements/tribulus", "tribulus", 6, 10, [
     "Tribulus terrestris testosterone libido", "tribulus supplementation exercise",
     "protodioscin mechanism androgen"], cohort=True, aa=False),
  T("07_supplements/fenugreek", "fenugreek", 6, 10, [
     "fenugreek testosterone libido men", "fenugreek supplementation strength",
     "fenugreek saponin 5-alpha reductase mechanism"], cohort=True, aa=False),
  T("07_supplements/panax_ginseng", "ginseng", 6, 10, [
     "Panax ginseng cognition fatigue", "ginseng erectile libido",
     "ginsenoside mechanism nitric oxide"], aa=False),
  T("07_supplements/saw_palmetto", "saw-palmetto", 6, 12, [
     "saw palmetto Serenoa hair loss androgenetic", "saw palmetto benign prostatic hyperplasia",
     "saw palmetto 5-alpha reductase DHT mechanism"], aa=False),
  T("07_supplements/nettle_pygeum", "nettle-pygeum", 6, 10, [
     "stinging nettle root prostate DHT", "Pygeum africanum prostate symptoms",
     "nettle SHBG aromatase mechanism"], aa=False),
  T("07_supplements/resveratrol", "resveratrol", 6, 12, [
     "resveratrol supplementation metabolic cardiovascular human", "resveratrol exercise adaptation",
     "resveratrol SIRT1 AMPK mechanism"], aa=False),
  T("07_supplements/quercetin", "quercetin", 6, 12, [
     "quercetin supplementation exercise performance immunity", "quercetin blood pressure",
     "quercetin senolytic anti-inflammatory mechanism"], aa=False),
  T("07_supplements/fisetin", "fisetin", 6, 10, [
     "fisetin senolytic aging", "fisetin supplementation health",
     "fisetin cellular senescence mechanism"], aa=False),
  T("07_supplements/spermidine", "spermidine", 6, 10, [
     "spermidine supplementation autophagy human", "spermidine cardiovascular cognition",
     "spermidine autophagy mechanism"], aa=False),
  T("07_supplements/sulforaphane", "sulforaphane", 6, 10, [
     "sulforaphane broccoli sprout human trial", "sulforaphane detoxification oxidative stress",
     "sulforaphane Nrf2 mechanism"], aa=False),
  T("07_supplements/egcg_green_tea", "egcg", 6, 12, [
     "green tea EGCG catechin fat oxidation weight", "green tea extract metabolic health",
     "EGCG catechol-O-methyltransferase mechanism"], aa=False),
  T("07_supplements/astaxanthin", "astaxanthin", 6, 10, [
     "astaxanthin supplementation endurance oxidative", "astaxanthin skin cardiovascular",
     "astaxanthin carotenoid antioxidant mechanism"], aa=False),
  T("07_supplements/bacopa_monnieri", "bacopa", 6, 10, [
     "Bacopa monnieri memory cognition trial", "bacopa supplementation anxiety",
     "bacoside cholinergic mechanism"], aa=False),
  T("07_supplements/lions_mane", "lions-mane", 6, 10, [
     "Hericium erinaceus lion's mane cognition", "lion's mane nerve growth factor human",
     "hericenone erinacine NGF mechanism"], aa=False),
  T("07_supplements/ginkgo_biloba", "ginkgo", 6, 10, [
     "Ginkgo biloba cognition memory", "ginkgo cerebral blood flow",
     "ginkgo flavonoid terpenoid mechanism"], aa=False),
  T("07_supplements/citicoline_cdp", "citicoline", 6, 10, [
     "citicoline CDP-choline cognition attention", "citicoline brain phospholipid",
     "citicoline acetylcholine membrane mechanism"], aa=False),
  T("07_supplements/phosphatidylserine", "ps", 6, 10, [
     "phosphatidylserine cognition cortisol", "phosphatidylserine exercise stress",
     "phosphatidylserine membrane HPA axis mechanism"], aa=False),
  T("07_supplements/melatonin", "melatonin", 8, 14, [
     "melatonin supplementation sleep onset quality", "melatonin dose timing circadian",
     "melatonin receptor MT1 MT2 mechanism"], aa=False),
  T("07_supplements/l_tryptophan_5htp", "tryptophan-5htp", 6, 10, [
     "tryptophan 5-HTP sleep mood serotonin", "5-HTP supplementation appetite",
     "tryptophan serotonin synthesis mechanism"], aa=False),
  T("07_supplements/apigenin", "apigenin", 6, 10, [
     "apigenin sleep anxiety chamomile", "apigenin flavonoid health",
     "apigenin GABA-A receptor mechanism"], aa=False),
  T("07_supplements/msm_joint", "msm", 6, 10, [
     "methylsulfonylmethane MSM joint pain exercise", "MSM osteoarthritis inflammation",
     "MSM sulfur donor mechanism"], aa=False),
  T("07_supplements/boswellia", "boswellia", 6, 10, [
     "Boswellia serrata osteoarthritis inflammation", "boswellia joint pain trial",
     "boswellic acid 5-lipoxygenase mechanism"], aa=False),

  # ---------------- ROUND 12 (FULL peptide landscape — pull everything available) ----------------
  # high stretch (30) = grab all OA papers each provider can find, incl. animal/preprint/Russian
  T("08_peptides_gray/bpc157", "bpc157", 8, 30, [
     "BPC-157 body protection compound healing", "BPC-157 tendon ligament gut animal",
     "BPC-157 human clinical safety", "pentadecapeptide BPC 157 mechanism"], aa=False),
  T("08_peptides_gray/tb500_thymosin_b4", "tb500", 8, 30, [
     "thymosin beta-4 TB-500 tissue repair", "thymosin beta-4 cardiac wound healing",
     "TB-500 clinical evidence", "thymosin beta 4 angiogenesis mechanism"], aa=False),
  T("08_peptides_gray/ghk_cu", "ghk-cu", 8, 30, [
     "GHK-Cu copper peptide skin", "copper tripeptide wound healing collagen",
     "GHK-Cu hair follicle", "glycyl-histidyl-lysine copper mechanism"], aa=False),
  T("08_peptides_gray/mots_c", "mots-c", 8, 30, [
     "MOTS-c mitochondrial derived peptide metabolism", "MOTS-c exercise insulin sensitivity",
     "mitochondrial-derived peptide MOTS-c mechanism"], aa=False),
  T("08_peptides_gray/kpv", "kpv", 6, 24, [
     "KPV tripeptide anti-inflammatory", "KPV alpha-MSH gut inflammation",
     "lysine-proline-valine peptide mechanism"], aa=False),
  T("08_peptides_gray/ipamorelin", "ipamorelin", 8, 30, [
     "ipamorelin growth hormone secretagogue", "ipamorelin GH IGF-1 release",
     "ghrelin receptor agonist growth hormone"], aa=False),
  T("08_peptides_gray/cjc1295", "cjc1295", 8, 30, [
     "CJC-1295 GHRH analog growth hormone", "CJC-1295 IGF-1 secretion",
     "GHRH analog long-acting secretagogue"], aa=False),
  T("08_peptides_gray/tesamorelin", "tesamorelin", 10, 30, [
     "tesamorelin visceral adipose tissue GHRH", "tesamorelin lipodystrophy randomized trial",
     "tesamorelin IGF-1 metabolic outcomes", "tesamorelin cognition"], aa=False),
  T("08_peptides_gray/sermorelin", "sermorelin", 8, 30, [
     "sermorelin GHRH growth hormone", "sermorelin adult growth hormone deficiency",
     "sermorelin secretagogue safety"], aa=False),
  T("08_peptides_gray/hexarelin", "hexarelin", 8, 30, [
     "hexarelin growth hormone releasing peptide", "hexarelin cardiac cardiovascular",
     "hexarelin GH secretagogue mechanism"], aa=False),
  T("08_peptides_gray/ghrp2_6", "ghrp", 8, 30, [
     "GHRP-6 growth hormone releasing peptide", "GHRP-2 appetite growth hormone",
     "growth hormone releasing peptide secretagogue"], aa=False),
  T("08_peptides_gray/semaglutide", "semaglutide", 10, 30, [
     "semaglutide weight loss randomized trial", "semaglutide GLP-1 cardiometabolic outcomes",
     "semaglutide STEP obesity trial", "semaglutide muscle lean mass"], aa=False),
  T("08_peptides_gray/retatrutide", "retatrutide", 8, 30, [
     "retatrutide triple agonist obesity", "retatrutide GLP-1 GIP glucagon trial",
     "retatrutide weight loss phase 2"], aa=False),
  T("08_peptides_gray/pt141_bremelanotide", "pt141", 8, 30, [
     "bremelanotide PT-141 sexual function trial", "melanocortin agonist bremelanotide",
     "PT-141 libido mechanism"], aa=False),
  T("08_peptides_gray/melanotan", "melanotan", 6, 24, [
     "afamelanotide melanocortin clinical", "melanotan II melanocortin safety",
     "alpha-melanocyte stimulating hormone analog"], aa=False),
  T("08_peptides_gray/thymosin_alpha1", "thymosin-a1", 8, 30, [
     "thymosin alpha-1 immune modulation", "thymalfasin thymosin alpha 1 infection trial",
     "thymosin alpha-1 mechanism immunity"], aa=False),
  T("08_peptides_gray/ll37", "ll37", 6, 24, [
     "LL-37 cathelicidin antimicrobial peptide", "LL-37 immune wound healing",
     "cathelicidin LL-37 mechanism"], aa=False),
  T("08_peptides_gray/epitalon", "epitalon", 6, 24, [
     "epitalon epithalon telomerase aging", "epithalamin pineal peptide clinical",
     "epitalon peptide bioregulator"], aa=False),
  T("08_peptides_gray/dihexa", "dihexa", 6, 20, [
     "dihexa angiotensin peptide cognition", "dihexa hepatocyte growth factor synaptogenesis",
     "dihexa neurotrophic mechanism"], aa=False),
  T("08_peptides_gray/follistatin", "follistatin", 8, 30, [
     "follistatin myostatin muscle growth", "follistatin gene therapy muscle",
     "follistatin activin mechanism"], aa=False),
  T("08_peptides_gray/aod9604", "aod9604", 6, 24, [
     "AOD9604 growth hormone fragment fat loss", "AOD9604 obesity trial",
     "hGH fragment 176-191 lipolysis"], aa=False),
  T("08_peptides_gray/igf1_lr3", "igf1-lr3", 6, 24, [
     "IGF-1 LR3 muscle anabolic", "insulin-like growth factor 1 hypertrophy risk",
     "IGF-1 supplementation adverse cancer risk"], aa=False),

  # ---------------- ROUND 13 (clothing / fabric and the body) ----------------
  T("15_health_maintenance/clothing_fabric_body", "clothing-fabric", 8, 18, [
     "clothing fabric thermoregulation exercise performance",
     "synthetic versus cotton fabric skin irritation dermatitis",
     "polyester underwear scrotal temperature fertility",
     "textile microplastics skin exposure",
     "moisture-wicking fabric sweat athletic comfort"], aa=False),

  # ---------------- ROUND 14 (catalog gap-fill: missed peptides/compounds) ----------------
  # GH axis / muscle
  T("08_peptides_gray/mk677_ibutamoren", "mk677", 8, 26, [
     "MK-677 ibutamoren growth hormone IGF-1", "ibutamoren body composition older adults trial",
     "MK-677 appetite bone density", "ibutamoren secretagogue safety"], aa=False),
  T("08_peptides_gray/mgf_mechano_growth", "mgf", 6, 20, [
     "mechano growth factor MGF muscle hypertrophy", "MGF IGF-1 splice variant repair",
     "PEG-MGF skeletal muscle mechanism"], aa=False),
  # sleep / neuro
  T("08_peptides_gray/dsip", "dsip", 6, 20, [
     "delta sleep-inducing peptide DSIP sleep", "DSIP stress human study",
     "DSIP mechanism neuromodulation"], aa=False),
  T("08_peptides_gray/agomelatine", "agomelatine", 8, 24, [
     "agomelatine melatonergic depression sleep trial", "agomelatine MT1 MT2 5-HT2C circadian",
     "agomelatine efficacy tolerability"], aa=False),
  T("08_peptides_gray/noopept", "noopept", 6, 20, [
     "noopept cognition neuroprotection", "noopept BDNF NGF mechanism",
     "noopept anxiety clinical"], aa=False),
  T("08_peptides_gray/phenibut", "phenibut", 6, 20, [
     "phenibut GABA-B anxiety", "phenibut dependence withdrawal safety",
     "phenibut pharmacology cognition"], aa=False),
  T("08_peptides_gray/aniracetam", "aniracetam", 6, 18, [
     "aniracetam cognition anxiety", "aniracetam AMPA receptor memory",
     "aniracetam clinical trial"], aa=False),
  T("08_peptides_gray/isrib", "isrib", 6, 18, [
     "ISRIB integrated stress response memory", "ISRIB cognition traumatic brain injury",
     "ISRIB eIF2B mechanism"], aa=False),
  T("08_peptides_gray/methylene_blue", "methylene-blue", 6, 20, [
     "methylene blue cognition mitochondria low dose", "methylene blue memory neuroprotection",
     "methylene blue safety serotonin interaction"], aa=False),
  # mito / metabolic / exercise-mimetic
  T("08_peptides_gray/humanin", "humanin", 6, 18, [
     "humanin mitochondrial-derived peptide", "humanin metabolic neuroprotection",
     "humanin aging mechanism"], aa=False),
  T("08_peptides_gray/aicar", "aicar", 6, 18, [
     "AICAR AMPK exercise mimetic", "AICAR endurance skeletal muscle metabolism",
     "AICAR fatty acid oxidation"], aa=False),
  T("08_peptides_gray/slu_pp_332", "slu-pp-332", 5, 16, [
     "SLU-PP-332 ERR agonist exercise mimetic", "estrogen-related receptor agonist endurance mitochondria"], aa=False),
  T("08_peptides_gray/five_amino_1mq", "5amino1mq", 5, 16, [
     "5-Amino-1MQ NNMT inhibitor fat metabolism", "NNMT inhibition obesity adipocyte",
     "5-amino-1-methylquinolinium metabolic"], aa=False),
  T("08_peptides_gray/oxytocin", "oxytocin", 6, 20, [
     "intranasal oxytocin human trial", "oxytocin social behavior appetite",
     "oxytocin metabolism body weight"], aa=False),
  # metabolic / GLP-1 & obesity drugs (tirzepatide alternatives)
  T("05_fat_loss_drugs/liraglutide", "liraglutide", 8, 26, [
     "liraglutide weight loss randomized trial", "liraglutide GLP-1 cardiometabolic SCALE",
     "liraglutide obesity lean mass"], aa=False),
  T("05_fat_loss_drugs/cagrilintide", "cagrilintide", 6, 20, [
     "cagrilintide amylin analog obesity trial", "cagrilintide semaglutide CagriSema weight loss"], aa=False),
  T("05_fat_loss_drugs/survodutide", "survodutide", 6, 20, [
     "survodutide GLP-1 glucagon dual agonist obesity", "survodutide MASH liver trial"], aa=False),
  T("05_fat_loss_drugs/tesofensine", "tesofensine", 6, 20, [
     "tesofensine weight loss randomized trial", "tesofensine monoamine reuptake obesity"], aa=False),
  # hormones / fertility / testosterone
  T("09_hormones_sex/enclomiphene", "enclomiphene", 8, 24, [
     "enclomiphene testosterone secondary hypogonadism trial", "enclomiphene citrate LH FSH men",
     "enclomiphene versus testosterone fertility sperm"], cohort=True, aa=False),
  T("09_hormones_sex/kisspeptin", "kisspeptin", 6, 20, [
     "kisspeptin-10 luteinizing hormone testosterone men", "kisspeptin administration reproductive hormone",
     "kisspeptin sexual behavior brain"], cohort=True, aa=False),
  T("09_hormones_sex/gonadorelin", "gonadorelin", 6, 20, [
     "gonadorelin GnRH luteinizing hormone", "gonadorelin fertility hypogonadism men",
     "GnRH agonist testosterone testicular"], cohort=True, aa=False),
  # aminos / antioxidant / longevity
  T("07_supplements/glutathione", "glutathione", 8, 22, [
     "glutathione supplementation oxidative stress", "liposomal glutathione bioavailability human",
     "glutathione exercise recovery"], aa=False),
  T("07_supplements/nad_nmn", "nad-nmn", 8, 26, [
     "NMN nicotinamide mononucleotide human trial", "NAD+ precursor supplementation metabolism aging",
     "nicotinamide riboside NAD exercise", "NMN insulin muscle randomized"], aa=False),
  # catch-all for the niche research chems (grab whatever OA exists)
  T("08_peptides_gray/research_peptides_misc", "peptides-misc", 5, 20, [
     "ARA-290 cibinetide neuropathy trial", "adipotide prohibitin fat loss peptide",
     "FOXO4-DRI senolytic peptide", "PE-22-28 spadin antidepressant peptide",
     "SNAP-8 acetyl octapeptide", "vasoactive intestinal peptide VIP therapeutic",
     "PNC-27 anticancer peptide"], aa=False),
  # Khavinson short-peptide bioregulators (whole Russian class in one folder)
  T("08_peptides_gray/peptide_bioregulators_khavinson", "bioregulators", 5, 22, [
     "Khavinson short peptide bioregulator", "peptide bioregulator Vilon Thymalin Epitalon aging",
     "cytogen cytomax peptide immune regulation", "Thymalin Pinealon Cortexin peptide clinical Russian"], aa=False),

  # ---------------- ROUND 15 (parasites / antiparasitics / deworming — HUMAN evidence) ----------------
  # Ivermectin as a human antiparasitic (approved indications: strongyloidiasis, scabies, onchocerciasis).
  T("15_health_maintenance/ivermectin_human", "ivermectin", 8, 20, [
     "ivermectin strongyloidiasis treatment randomized trial",
     "ivermectin scabies randomized controlled trial efficacy",
     "ivermectin onchocerciasis mass drug administration",
     "ivermectin human pharmacokinetics safety review",
     "ivermectin soil-transmitted helminth efficacy",
     "ivermectin adverse events tolerability systematic review"], aa=False),
  # General human anthelmintics / deworming agents.
  T("15_health_maintenance/antiparasitic_deworming_humans", "deworming", 8, 20, [
     "albendazole mebendazole soil-transmitted helminth meta-analysis",
     "mass deworming children systematic review outcomes",
     "praziquantel schistosomiasis treatment efficacy",
     "nitazoxanide intestinal protozoa randomized trial",
     "anthelmintic efficacy hookworm ascaris trichuris",
     "single dose deworming adults efficacy review"], aa=False),
  # Human intestinal/tissue parasites: prevalence, diagnosis, symptoms, treatment.
  T("15_health_maintenance/intestinal_parasites_humans", "parasites", 8, 20, [
     "intestinal parasitic infection prevalence adults developed countries",
     "giardia lamblia treatment human trial",
     "blastocystis hominis clinical significance treatment",
     "human helminth infection diagnosis symptoms",
     "enterobius pinworm treatment household",
     "parasite eradication gut microbiome human"], aa=False),

  # ---------------- ROUND 15 (cravings: sugar + general food craving control) ----------------
  T("01_food_inflammation/sugar_cravings_control", "sugar-cravings", 8, 20, [
     "sugar craving reduction intervention randomized",
     "added sugar reduction appetite trial",
     "sweet craving reward dopamine mechanism",
     "carbohydrate craving management behavioral",
     "sugar-sweetened beverage craving intervention",
     "sweet taste adaptation reduced sugar diet"], aa=False),
  T("01_food_inflammation/food_craving_appetite_control", "food-cravings", 8, 20, [
     "food craving intervention weight loss randomized",
     "protein fiber satiety appetite suppression meta-analysis",
     "GLP-1 receptor agonist food craving appetite reduction",
     "food craving cognitive behavioral therapy trial",
     "high protein diet hunger appetite control meta-analysis",
     "mindfulness food craving eating intervention"], aa=False),

  # ---------------- ROUND 15b (source coverage for the new question clusters) ----------------
  T("02_training_desk/energy_availability_reds", "reds", 8, 20, [
     "relative energy deficiency in sport RED-S male athletes",
     "low energy availability testosterone bone male endurance",
     "energy availability threshold hormonal disruption athletes",
     "underfueling endurance performance recovery",
     "RED-S health performance consequences review",
     "energy availability assessment calculation athletes"], aa=False),
  T("03_sleep_stress/sleep_apnea_breathing", "sleep-apnea", 8, 20, [
     "obstructive sleep apnea screening diagnosis primary care",
     "sleep apnea testosterone cardiovascular blood pressure",
     "weight loss obstructive sleep apnea severity trial",
     "mouth taping sleep-disordered breathing evidence",
     "home sleep apnea test versus polysomnography accuracy",
     "upper airway resistance syndrome daytime symptoms"], aa=False),
  T("01_food_inflammation/endurance_fueling_carbs", "endurance-fueling", 8, 22, [
     "carbohydrate intake during endurance exercise grams per hour",
     "gut training carbohydrate tolerance endurance athletes",
     "multiple transportable carbohydrates glucose fructose oxidation",
     "marathon race nutrition fueling strategy",
     "carbohydrate periodization train-low endurance adaptation",
     "gastrointestinal symptoms endurance exercise runners",
     "gastric emptying exercise intensity"], aa=False),
  T("14_hormones_thyroid_heart/athlete_cardiac_health", "athlete-cardiac", 8, 20, [
     "endurance athlete atrial fibrillation risk",
     "athlete's heart cardiac remodeling exercise",
     "coronary artery calcium endurance athletes",
     "pre-participation cardiovascular screening athletes",
     "caffeine arrhythmia cardiac safety",
     "high volume endurance exercise cardiovascular risk"], aa=False),
  T("02_training_desk/overtraining_overreaching", "overtraining", 8, 20, [
     "overtraining syndrome diagnosis markers",
     "functional nonfunctional overreaching performance",
     "heart rate variability training load monitoring athletes",
     "overtraining hormonal immune markers review",
     "monitoring fatigue recovery athletes systematic review"], aa=False),
  T("13_vaccines_immunology/exercise_immunity_vaccines", "exercise-immunity", 8, 20, [
     "exercise immunology upper respiratory infection athletes open window",
     "intense training immune function J-curve",
     "influenza vaccine healthy adults effectiveness",
     "exercise timing vaccine antibody response",
     "energy deficit immune function athletes",
     "vitamin D zinc respiratory infection prevention meta-analysis"], aa=False),

  # ---------------- ROUND 15c (colostrum + EMF/wireless) ----------------
  T("07_supplements/bovine_colostrum", "colostrum", 8, 20, [
     "bovine colostrum supplementation athletes randomized",
     "bovine colostrum gut permeability leaky gut exercise",
     "bovine colostrum immune upper respiratory infection",
     "colostrum body composition muscle recovery trial",
     "bovine colostrum immunoglobulin lactoferrin bioactive",
     "colostrum gastrointestinal health adults"], aa=False),
  T("15_health_maintenance/emf_wireless_bluetooth", "emf-wireless", 8, 20, [
     "radiofrequency electromagnetic field health effects review",
     "mobile phone radiation brain tumor epidemiology",
     "Bluetooth wireless earbud RF exposure safety",
     "specific absorption rate SAR mobile phone limits",
     "radiofrequency EMF cognition sleep human study",
     "5G radiofrequency exposure health evidence"], aa=False),
]

# --------------------------------------------------------------------------- #
#  AA overlay-only final pass (population folder)
# --------------------------------------------------------------------------- #
AA_QUERIES = [
  "vitamin D deficiency African American 25-hydroxyvitamin D",
  "DASH diet hypertension Black adults randomized",
  "exercise blood pressure African American randomized",
  "lactose intolerance African American",
  "central centrifugal cicatricial alopecia systematic review",
  "traction alopecia",
  "keloid review",
  "tirzepatide obesity race subgroup",
  "sedentary behavior cardiovascular African American",
  "finasteride counseling Black men",
]
def run_aa_overlay():
    t = {"folder": "12_population_AA", "slug": "aa-overlay", "min": 30,
         "stretch": 60, "queries": AA_QUERIES, "seeds": [], "aa": False}
    run_topic(t)

# --------------------------------------------------------------------------- #
#  SIDE JOB: hormones / thyroid / heart for a LATE-20s MALE (age filter is law)
# --------------------------------------------------------------------------- #
AGE = (' AND (young adult OR "18-35" OR "18-40" OR men OR male OR eugonadal'
       ' OR "resistance trained")')
def aq(qs):                      # append the age filter to every query
    return [q + AGE for q in qs]

H = "14_hormones_thyroid_heart/"
HORMONE_TOPICS = [
  T(H+"young_adult_male_norms", "yam-norms", 12, 16, aq([          # DO FIRST
     "reference range testosterone healthy men 20-30",
     "TSH thyroid reference interval young adults",
     "ApoB LDL young adult men primary prevention",
     "blood pressure young adults ACC AHA classification",
     "VO2max reference values men 20-29",
     "body fat percentage testosterone young men",
     "energy availability male athletes thyroid testosterone",
     "sleep duration young adults cognitive performance",
     "25-hydroxyvitamin D young Black men"]), cohort=True),
  T(H+"thyroid_hypo_hyper_function", "thyroid", 12, 16, aq([
     "hypothyroidism management clinical guideline",
     "hyperthyroidism thyrotoxicosis management guideline",
     "subclinical hypothyroidism young adults treatment",
     "iodine selenium thyroid function",
     "TSH reference interval African American"]), cohort=True),
  T(H+"lipids_apob_ldl", "lipids-apob", 12, 16, aq([
     "apolipoprotein B primary prevention young adults",
     "ACC AHA blood cholesterol guideline",
     "LDL cholesterol young adults cardiovascular risk",
     "familial hypercholesterolemia young adult",
     "lipoprotein(a) measurement review",
     "resistance training lipid profile"]), cohort=True),
  T(H+"male_hpg_testosterone_estradiol", "male-hpg", 12, 16, aq([
     "obesity weight loss testosterone young men",
     "sleep restriction testosterone randomized young men",
     "estradiol men bone health",
     "aromatase inhibitor healthy young men adverse",
     "secondary hypogonadism obesity young men",
     "testosterone deficiency Endocrine Society guideline"]),
     cohort=True, also=["09_hormones_sex/estrogen_estradiol_men"]),
  T(H+"hormone_regulation_overview", "horm-overview", 8, 14, aq([
     "relative energy deficiency sport male RED-S",
     "low energy availability men endocrine",
     "hypothalamic pituitary gonadal axis exercise young men",
     "hormonal responses resistance training young men"]), cohort=True),
  T(H+"metabolic_rate_t3_energy_deficit", "t3-deficit", 8, 14, aq([
     "calorie restriction triiodothyronine reverse T3 athletes",
     "low energy availability thyroid hormone men",
     "adaptive thermogenesis weight loss resting metabolic rate",
     "overreaching hormonal response resistance trained"]),
     cohort=True, also=["02_training_desk/cutting_fat_loss_methods"]),
  T(H+"cortisol_hpa_overreach", "cortisol-hpa", 8, 14, aq([
     "overtraining cortisol hypothalamic pituitary adrenal",
     "psychological stress cortisol young adults",
     "sleep restriction cortisol response"]), cohort=True),
  T(H+"insulin_glucose_heart", "insulin-glucose", 8, 14, aq([
     "insulin sensitivity exercise young adults",
     "interrupting prolonged sitting postprandial glucose",
     "cardiorespiratory fitness insulin resistance young adults"]), cohort=True),
  T(H+"blood_pressure_endothelium", "bp-endothelium", 8, 14, aq([
     "blood pressure guideline young adults ACC AHA",
     "DASH diet blood pressure randomized",
     "DASH diet African American hypertension",
     "aerobic exercise blood pressure meta-analysis",
     "prolonged sitting endothelial function young adults"]),
     cohort=True, also=["02_training_desk/sedentary_software_engineer"]),
  T(H+"aerobic_resistance_cardio", "aero-resist", 8, 14, aq([
     "cardiorespiratory fitness all-cause mortality",
     "VO2max mortality meta-analysis",
     "resistance training cardiovascular disease risk",
     "concurrent training cardiovascular young men"]),
     cohort=True, also=["02_training_desk/concurrent_hybrid_lift_run"]),
  T(H+"sleep_hormones_heart", "sleep-horm", 8, 14, aq([
     "sleep restriction testosterone young men",
     "short sleep blood pressure young adults",
     "social jetlag cardiometabolic young adults",
     "cognitive behavioral therapy insomnia"]),
     cohort=True, also=["03_sleep_stress/sleep_best_practices",
                        "02_training_desk/compressed_4x10_schedule"]),
  T(H+"micronutrients_thyroid_heart", "micros", 8, 14, aq([
     "iodine excess thyroid dysfunction",
     "selenium thyroid autoimmunity",
     "vitamin D African American young adults",
     "magnesium blood pressure randomized",
     "omega-3 triglycerides meta-analysis"]),
     cohort=True, also=["01_food_inflammation/omega3"]),
  T(H+"what_not_to_optimize", "not-optimize", 5, 10, aq([
     "adrenal fatigue myth critique",
     "testosterone booster supplement systematic review",
     "over-the-counter thyroid support supplement",
     "testosterone replacement eugonadal young men risk",
     "hormone balance supplement overclaim"]), cohort=True, aa=False),
  T(H+"bone_stress_density", "bone-stress", 8, 14, aq([
     "bone stress fracture athletes",
     "low bone mineral density male athletes",
     "relative energy deficiency sport bone health male",
     "resistance training bone mineral density young adults"]), cohort=True),
]

HORMONE_CONTEXT = """
## SIDE JOB CONTEXT — late-20s male (hormones / thyroid / heart)
Subject: male, ~27-29, software engineer, compressed 4x10 week, lifting + running,
in a calorie deficit, wants to stay athletic, lean, cognitively sharp.
"Maximize" here means keeping thyroid, lipids/ApoB, blood pressure, insulin
sensitivity, sleep, and energy availability in ranges tied to health and
performance AT THIS AGE — not "raise testosterone into a cycle." Age-related TRT
indications for older men do NOT automatically apply to a late-20s male. Crash
diets + 10-hour days + short sleep suppress T3/testosterone far more than any
missing supplement. Abnormal labs -> clinician, not a stack. Files tagged
_older-cohort used a >~50-60y sample and are kept for MECHANISM only; do not
apply their TRT/effect sizes to a late-20s male.
No TRT/HCG/clomiphene/T3/T4 dosing. No 12-supplement 'hormone balance' protocols.
No adrenal-fatigue manuals (critiques only). No anti-aging-clinic PDFs for men 50+.
"""

def write_hormone_context():
    if os.path.exists(MANIFEST):
        if "SIDE JOB CONTEXT" in open(MANIFEST).read():
            return
    with open(MANIFEST, "a") as f:
        f.write("\n" + HORMONE_CONTEXT + "\n")

def load_seen_from_manifest():
    """Cross-run dedupe: skip DOIs/PMCIDs already logged in MANIFEST."""
    if not os.path.exists(MANIFEST): return 0
    n = 0
    for line in open(MANIFEST):
        m = re.match(r"\|\s*[ABCD]\s*\|[^|]*\|\s*([^|]+?)\s*\|", line)
        if m:
            key = m.group(1).strip()
            if key and key.lower() not in ("doi/pmcid", "doi"):
                if key not in SEEN_DOI:
                    SEEN_DOI[key] = None          # known -> acquire() will skip
                    if key.startswith("PMC"): SEEN_PMC.add(key)
                    n += 1
    return n

# --------------------------------------------------------------------------- #
#  MANIFEST required rule-lines (inherited by any future model)
# --------------------------------------------------------------------------- #
RULES = [
 "## HARD RULES (inherited)",
 "1. No claim without a retrieved paper; confidence matches grade.",
 "2. Research peptides / JXL069 / PP405: explain only. No human dosing, reconstitution, or 'buy research chem'.",
 "3. Tirzepatide / tadalafil / finasteride: explain trials only; do not prescribe.",
 "4. PP405 is investigational (Phase 1 + Phase 2a NCT06393452). Company-reported 2a is NOT approval.",
 "5. Pelage states PP405 is NOT JXL069 / NOT JXL082. Folders kept SEPARATE. Naming conflict noted. Do not claim same molecule unless a peer-reviewed paper says so.",
 "6. Compressed 4x10 != shorter week; 10-hour days can raise same-day fatigue; the 3-day weekend is the recovery lever; fixed sleep/wake beats weekend inversion.",
 "7. Foods 'ruining the body' = ultra-processed pattern, SSBs, industrial trans fat, heavy alcohol, frequent energy drinks. Not 'never eat fruit'; no seed-oil religion.",
 "8. Tooth chips/fractures need dentistry; remineralization papers are for early enamel lesions only.",
 "9. Semen-retention / beard-peptide stacks: the evidence GAP is filed so the model can refuse bro claims.",
 "10. Genetic-modification folder = approved CRISPR medicine reviews only. No DIY plasmids.",
 "11. COVID vaccine: NO evidence-based protocol to 'remove the vaccine from the body'. Detox claims are grade D. Model must refuse.",
 "> No evidence-based vaccine-removal protocol. Detox claims are D. Model must refuse.",
 "> PP405 investigational 0.05% topical gel; Phase 2a n≈78; not FDA approved; refuse personal protocol.",
 "> PP405 != JXL069 per Pelage; naming conflict logged; folders separate.",
 "",
 "| GRADE | YEAR | DOI/PMCID | FOLDER | FILENAME | SOURCE |",
 "|-------|------|-----------|--------|----------|--------|",
]

def init_logs():
    if not os.path.exists(MANIFEST) or "--reset" in sys.argv:
        with open(MANIFEST, "w") as f:
            f.write("# HealthCoach paper MANIFEST\n\n")
            f.write("\n".join(RULES) + "\n")
    if not os.path.exists(FAILED) or "--reset" in sys.argv:
        with open(FAILED, "w") as f:
            f.write("# Sources failed / rejected\n")
            f.write("# tag rejected-detox = spike-detox/shedding/ivermectin-as-detox/chlorine-dioxide/binder\n\n")

# --------------------------------------------------------------------------- #
def selftest():
    assert grade_of(["Meta-Analysis"], "x") == "A"
    assert grade_of(["Randomized Controlled Trial"], "x") == "B"
    assert grade_of(["Journal Article"], "y review") == "C"
    assert grade_of([], "A systematic review of X") == "A"
    assert fname("A", 2021, "omega3", "EPA and DHA: a study!").startswith("A_2021_omega3_")
    assert cohort_of({"title": "TRT in older men aged 65", "abstract": ""}) == "older"
    assert cohort_of({"title": "Testosterone in young men 18-35", "abstract": ""}) == "young"
    assert cohort_of({"title": "Thyroid physiology", "abstract": ""}) == "unknown"
    print("selftest OK  |  main topics %d  |  hormone topics %d  |  folders %d" % (
          len(TOPICS), len(HORMONE_TOPICS),
          len({t['folder'] for t in TOPICS + HORMONE_TOPICS})))

def cohort_summary():
    rows = {k: v for k, v in COHORT.items() if k.startswith("14_")}
    if not rows: return
    print("\n--- hormone-job cohort check (young-adult vs older) ---")
    for k in sorted(rows):
        c = rows[k]
        print("  %-52s young=%d older=%d unknown=%d" %
              (k, c["young"], c["older"], c["unknown"]))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int)
    ap.add_argument("--topic", type=str)
    ap.add_argument("--hormones", action="store_true",
                    help="run only the 14_hormones_thyroid_heart side job")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--shard", type=str,
                    help="i/n — run every n-th topic only, for parallel processes (e.g. --shard 0/3)")
    a, _ = ap.parse_known_args()
    if a.selftest: return selftest()

    # AUTO-PARALLEL: a plain `ABOOST=1 python3 fetch_papers.py` (no --shard/--topic) fans out
    # into JOBS parallel worker processes automatically — fast, and each shard is idempotent so
    # a dropped connection just means re-running resumes. Override count with ABOOST_JOBS.
    JOBS = int(os.environ.get("ABOOST_JOBS", "3"))
    if os.environ.get("ABOOST") and not a.shard and not a.topic and JOBS > 1:
        import subprocess
        print("ABOOST parallel — launching %d worker shards (idempotent; resumable)..." % JOBS)
        env = dict(os.environ)
        procs = [subprocess.Popen([sys.executable, os.path.abspath(__file__),
                                   "--shard", "%d/%d" % (i, JOBS)], env=env) for i in range(JOBS)]
        rc = 0
        for p in procs:
            rc |= (p.wait() or 0)
        print("ABOOST parallel done — %d shards finished." % JOBS)
        return rc

    init_logs()
    skipped = load_seen_from_manifest()          # cross-run dedupe
    if skipped: print("preloaded %d already-logged DOIs from MANIFEST (will skip)" % skipped)

    if a.hormones:
        write_hormone_context()
        for t in HORMONE_TOPICS:
            try: run_topic(t)
            except KeyboardInterrupt: break
            except Exception as e:
                log_failed("- TOPIC ERROR %s: %s" % (t["folder"], e))
        count_table(); cohort_summary()
        print("MANIFEST:", MANIFEST); print("NEW unique PDFs this run:", SUCCESS)
        return

    todo = TOPICS
    if a.topic:
        todo = [t for t in (TOPICS + HORMONE_TOPICS) if a.topic in t["folder"]]
    shard_i = shard_n = None
    if a.shard:
        global WTAG
        shard_i, shard_n = (int(x) for x in a.shard.split("/"))
        todo = [t for k, t in enumerate(todo) if k % shard_n == shard_i]
        WTAG = "[W%d/%d]" % (shard_i + 1, shard_n)
        print("%s SHARD owns %d topics (idempotent; safe in parallel)" % (WTAG, len(todo)))
    tot = len(todo)
    for k, t in enumerate(todo, 1):
        try: run_topic(t)
        except KeyboardInterrupt: break
        except Exception as e:
            log_failed("- TOPIC ERROR %s: %s" % (t["folder"], e))
        progress(k, tot, "done %s" % t["folder"])
    # AA overlay runs once: only when not topic-filtered and (no shard, or the first shard)
    if not a.topic and (shard_i is None or shard_i == 0):
        run_aa_overlay()
    count_table(); cohort_summary()
    print("MANIFEST:", MANIFEST)
    print("NEW unique PDFs this run:", SUCCESS)

if __name__ == "__main__":
    main()
