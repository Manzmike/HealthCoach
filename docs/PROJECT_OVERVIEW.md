# HealthCoach — what this project is

_A deep description of the system, as it actually stands in the repo._

## In one sentence

HealthCoach is a **fully-local, evidence-graded personal health intelligence system**: it builds
a private library of legal open-access scientific papers, indexes them into a vector database on
your MacBook, and runs an offline LLM that answers deep health/training/nutrition questions
**only from those papers — every claim tied to a real source and ranked by how strong the evidence
is** — then compiles the answers into a personalized, maintainable report and schedule.

It is, in effect, your own private "second opinion" engine that can't hallucinate a citation,
can't be swayed by supplement marketing, and never leaves your machine.

## The problem it solves

Health/performance information online is a mix of real science, marketing, and confident nonsense,
and a general LLM answers from a blurred memory of all three with no way to check its work. You
wanted answers you can *trust and verify* for a specific person (you) — graded by evidence strength,
cited to primary sources, tailored to your body, goals, meds, and schedule, and private. HealthCoach
is that: retrieval-augmented generation where the retrieval corpus is a curated, graded scientific
library and the generation is constrained to cite it.

## Architecture — five layers

**1. Acquisition — `papers/fetch_papers.py` (~2,100 lines, stdlib-only).**
A topic-driven fetch engine. Each of ~262 topic folders is defined by a `T()` config (search
queries, seed papers, min/stretch counts) and an `ANCHORS` keyword gate. For every topic it queries
**Europe PMC, Unpaywall, OpenAlex, and Semantic Scholar** (legal open-access only — no Sci-Hub, no
vendor PDFs), follows citation chains, and pulls PDFs. Every paper is **auto-graded from its study
type** — A = systematic review / meta-analysis / guideline, B = randomized controlled trial,
C = animal / mechanism / observational (preprints can never be A/B) — and filed as
`GRADE_YEAR_topic_title.pdf`. It's **idempotent** (skips folders already full, dedupes by DOI, uses
hardlinks so one paper can live under several topics), **anchor-gated** (rejects off-topic hits at
fetch time), **resumable**, and now **auto-parallel** (`ABOOST=1` fans out to 3 worker processes and
hunts specifically for A/B reviews). `MANIFEST.md` logs every acquisition; `SOURCES_FAILED.md` logs
rejects.

**2. Indexing — `rag/ingest.py`.**
Extracts text from every live PDF, chunks it (~2,800 chars / ~500 overlap, references dropped),
embeds each chunk with **BAAI/bge-base-en-v1.5** on the Mac's GPU (MPS), and writes it into a
**LanceDB** table with per-chunk metadata: grade, year, topic folder, cohort (young/older), DOI,
source file. It builds a full-text index alongside the vectors for **hybrid search**. A full rebuild
is ~131k chunks.

**3. Retrieval + generation — `rag/coach.py`.**
The spine. For a question it does **hybrid retrieval** (vector + keyword) of a wide candidate set,
**re-ranks** with a BAAI/bge-reranker-base cross-encoder, and applies **metadata gates**: by default
only grade A/B evidence, and it refuses to apply older-cohort (65+) data to a late-20s male unless
the question is about aging. Generation runs on **MLX** with **Qwen3-30B-A3B-Instruct** (a
mixture-of-experts model — 30B total, ~3B active, so it's fast *and* strong; swappable to 14B or 8B
via `GEN_MODEL`). A hard **SYSTEM prompt** enforces the rules that make the whole thing trustworthy:
no claim without a retrieved passage; state the evidence grade; a **mechanism lane** (if only grade-C
animal/pharmacology exists it may reason at the chemical level but must label it theoretical, not
shown in humans); **never invent doses, authors, or a compound name**; and a **serious-harm carve-out**
(dangerous interactions are stated plainly, not buried). Everything runs offline once the models are
cached.

**4. Synthesis — the `build_*` / `batch_ask` scripts.**
This is where retrieval becomes usable output.
- `build_questions.py` generates the **question model** (~915 questions across 52 topic sections):
  singles, behavior×outcome and substance×outcome "matrices," stacks, his-meds interactions,
  A/B/C/D tier rankings, and deep real-life clusters (off-day training/NEAT, exact per-substance
  protocols, practical meals, troubleshooting, exact training numbers).
- `batch_ask.py` runs a question file through the coach → a graded, DOI-cited Q&A log. It shards for
  parallelism and **resumes** (a fixed `LOGFILE` skips already-answered questions).
- `build_playbook.py` assembles a chaptered learning document; `build_schedule.py` builds a
  **deterministic** daily/weekly schedule (the clock and the 3-lift/3-run split are computed in code
  from your fixed time anchors — the model only fills rationale, so it can't move your bedtime);
  `deep_dive.py` writes long per-goal briefs; `personalized_tiers.txt` produces the A/B/C/D capstone.
- `combine_report.py` folds the newest playbook + tiers + every Q&A answer into one ordered
  `MASTER_REPORT`, and `organize_logs.py` keeps `logs/` sorted by type.

**5. Application / front-end — the interactive layer.**
A keyboard-first local UI over all of the above, stored in one canonical **`HEALTHCOACH_REPORT.md`**
(currently ~206 chapters, ~800 KB):
- `healthcoach_dashboard.py` — the single "front door" (curses TUI).
- `report_navigator.py` — chapter/page/paragraph navigation of the report.
- `supplement_audit.py` (~4,700 lines) — an interactive, evidence-bound supplement auditor: takes a
  broad catalog, checks each item against the local corpus, assigns coverage from retrieved human
  evidence, and writes deep cards only from real passages.
- `weekly_checkin.py` — a manual weekly training/recovery/nutrition check-in logged into the report.
- `bevel_share.py` — a clipboard bridge to Bevel Intelligence (no fake API): copies structured
  prompts out, ingests Bevel's weekly reply, checks provenance and plan-compatibility, and can audit
  its claims against the library before storing them.
- `hc-*` shell wrappers (`hc-report`, `hc-supplements`, `hc-bevel`, `hc-refresh-*`) as the command line.

The local Flask browser app also exposes a date-keyed weekly workspace: Symptoms stores a
seven-day check-in, Workouts generates a deterministic plan from current level/target/days,
Lifestyle compares current and target habits against the saved calendar, and Meals accepts one
to seven slots alongside Food selections. Each planner saves under
`rag/.healthcoach/weekly_workspace.json`, allows edits only during its selected seven-day
window, and persists explicit advisory analysis that becomes stale after inputs change.

## Personalization

`profile.txt` (injected into every answer) and optional `history.md` make it *yours*: mid-20s male
embedded engineer, desk-bound, 4×10 workweek, Seattle→Dallas move; hybrid-athlete goal (run long
*and* keep a muscular build); cutting to ~10–12% body fat on tirzepatide while protecting muscle;
whole-foods diet, no seed oils, strong sweet tooth; morning study / evening training; wants
non-caffeine study drive, better stress coping; blunt evidence-based answers, no TRT/steroid/peptide
cycles. The coach tailors timing, dosing-from-studies, and tradeoffs to exactly this.

## Design decisions & tradeoffs

- **Fully local / offline.** Privacy (health data never leaves the Mac) and no per-query cost. The
  cost is your hardware does the work and a local model is smaller than a frontier one.
- **Open-access only.** Legal and reproducible. The ceiling: the best A-grade sources (Cochrane full
  texts, most society guidelines) are paywalled, so the honest fix is manual drop-in of papers you
  have legitimate access to.
- **Evidence grading is the core feature.** An answer is only as confident as the grade of the papers
  behind it — that's what separates this from an LLM's opinion.
- **Deterministic where correctness matters.** The schedule's clock is code, not model output, after
  the 8B model repeatedly ignored stated constraints. Small models synthesize; they don't do reliable
  constraint-satisfaction.
- **MoE model** (Qwen3-30B-A3B) to get near-32B reasoning at 8B-ish speed on 48 GB.

## Current scale

- **~4,649 graded open-access papers** — A 1,131 / B 554 / C 2,964 (~36% A/B) across **262 topics**.
- **~131k indexed chunks** in an ~850 MB LanceDB.
- **~915 questions** in the model; a canonical report of ~206 chapters.
- Runs on: MacBook Pro (Apple Silicon, 48 GB, 1 TB). Repo: github.com/Manzmike/HealthCoach.

## Honest limitations

It's a research and decision-support tool, not medicine — it can't run your labs, and it will (by
design) defer to a clinician and refuse to hand you a prescription-drug dosing protocol. The
synthesis layer (playbook/tiers) is only as good as the local model, so its A/B/C *labels* are worth
verifying against the cited DOIs; the per-question answers are the reliable layer. And the corpus is
OA-bounded. Within those limits, it does something genuinely hard: gives you deep, specific, cited,
grade-aware answers to your exact questions, privately, on your own machine.
