# Today And Trust

The [Weekly Workspace](WEEKLY_WORKSPACE.md) adds directly visible category selection,
separate overall/personal-fit grades, mandatory source-linked reasons, dated meals,
editable workouts/steps, and section/full-report exports. Its weekly choices are separate
from the stricter adopted/current-use list described below.

HealthCoach's daily loop is **plan -> execute -> log -> adjust**. Research supports that
loop rather than occupying the entire first screen. This is a local decision-support
system, not a diagnosis, prescription, or claim of clinical validation.

## Start Here

From `rag/`, run `./hc`. The initial area is Today; Tab or `1`-`5` opens Today, Plan,
Log/Review, Research, and Maintenance. `/` searches every action across areas. All
previous `--action` keys remain available. Both reset entry points require `RESET`.

Useful direct commands from `rag/`:

```bash
./hc --action today
./hc --action daily
.venv/bin/python today.py --review
.venv/bin/python coach.py --show --retrieval-audit "What do human studies show about creatine and strength?"
```

Today does not generate recommendations, write state, run source refreshes, or load a
model. It reads the marked profile block, candidate ledger, and exact dated daily log.
It never mines research prose for supposed instructions.

Newly saved reports include a snapshot of the authored calendar shown during assessment.
Today displays that session/placement and any conflict verbatim. Older saved reports with
placement only remain usable, but no clock time, session, or duration is invented for them.
The snapshot is an authored planning template, not a newly validated health recommendation.

Current items require `personal_candidate`, `adopt`, `in_use`, and a passing admission
screen. Their doses remain explicitly user-recorded and are not treated as daily timing
instructions. Other reported exposures can be expanded for review. Missing personal-context
review dates and review dates older than 30 days prompt a context check; 30 days is an
operational reminder, not a medical reassessment interval.

## Daily Facts

`daily_log.py` stores an explicit main-activity status, optional duration, subjective
recovery, and optional factual note under `.healthcoach/daily_log.json`.

Blank input retains the saved value. `?` clears a note or records unknown. Only `s` saves.
Each write preserves other dates, uses an atomic replacement and private file permissions,
and refuses to overwrite malformed or incompatible data. Cancellation performs no write.
Completion describes the main activity, not every supplement or the whole plan.

Daily facts do not yet merge into weekly Bevel packages or automatically adjust the plan.
Use the existing weekly review for the longitudinal feedback workflow. The next Monday is
shown as a review prompt; it is not an automatic reminder service or a new adjustment rule.

## Research Without Endorsement

The complete configured catalog remains available, including gray-market items, peptides,
nootropics, prescriptions, and custom research topics. Legal open-access source routing,
aliases, evidence gaps, rejection, and recorded use remain part of the workflow.

Experimental candidates are no longer excluded from deep research cards by queue. They use
the same source-linked path as supplements. Human-coverage `NONE` can still support a clearly
labelled animal/mechanistic review when relevant passages exist. No passage means no synthesis.

`safety_policy.py` holds a machine-readable `POLICY` and pure admission/urgent-warning
functions. Catalog restrictions, unresolved gates, identity/alias checks, experimental
classes, reported harms/blockers, scope, and stack-review context affect routine plan
admission, not access to research. Candidate evaluation, manager adoption commands, week
overlays, Today, symptom suggestions, and food allocation consume these checks.

Adoption records intent, not actual use or medical approval. Selecting an item no longer
sets `in_use`; unselecting it does not claim the person stopped. Reported existing use and
user-entered doses remain inspectable even for restricted items. No automatic stopping,
medication adjustment, or gray-market use protocol is prescribed.

The policy does not currently store clinician clearance. A review-required item therefore
remains review-only rather than inferring clearance from an enthusiastic selection, a
positive study, or an absence of recorded blockers. The alias tests cover the current
experimental catalog; new identities and policy rules require maintenance and review.

## Evidence Contract

`evidence_control.py` supplies the shared retrieval and claim-provenance contract:

1. Retain topic-matching passages. General questions use a lexical subject/overlap gate;
   candidate research additionally uses the candidate's explicit names/aliases and reason scope.
2. Score the exact context excerpt with `BAAI/bge-reranker-base`, explicitly requesting raw
   logits. The default minimum is `0.0`, equivalent to sigmoid(score) >= 0.5. This is an
   initial screening threshold, not a calibrated probability that a claim is true.
3. Withhold generation when scoring is absent, fails, is non-finite, or has no passing result.
   Hybrid-search failure can use vector candidates, but never bypasses reranking.
4. Cap context at two passages per paper, using normalized DOI, available physical-file
   identity, and filename fallbacks. Identical excerpts are also deduplicated. Independent
   human-source counts in the candidate audit use the same identities.
5. Retain available vector distance, keyword/hybrid score, reranker score, minimum, topic-gate
   status, and admission reason. Missing upstream scores remain unknown rather than invented.
6. Require generated claims to name supplied source IDs and copy an exact supporting quote.
   The JSON contract rejects unsupported fields, unknown IDs, invented quotes, personal-action
   claim types, explicit personal treatment directives, and malformed/truncated output.
   Validation fails the complete response closed; directive detection is a limited language
   screen, not a semantic safety guarantee. Unscored legacy hits cannot be passed directly
   to the shared generator to bypass retrieval admission.
7. Render the claim and quote together with a source map. Claim records mark certainty as
   `not_assessed` and entailment as `not_verified`. A/B/C remains study-design metadata.

The coach, batch answers, deep dives, supplement/experimental cards, timing synthesis, and
legacy playbook/schedule generators use the shared claim renderer. Authored planning text is
separate and is not magically source-validated by this change. Existing saved reports and
cached evaluations have not been regenerated or certified.

Use `--retrieval-audit` to inspect rejected as well as accepted candidates. The optional
`HC_MIN_RERANK_SCORE` changes the raw-logit cutoff; it must be finite. Evaluate threshold
changes on labelled relevant/irrelevant questions, not on a desire to obtain more answers.
First-term lexical anchoring, alias coverage, excerpt truncation, and the score cutoff can
all produce false negatives. Identical papers with different filenames, no DOI, and no
shared physical identity can still evade deduplication. Page/section provenance is not added.

Exact quote membership is **not** semantic entailment, risk-of-bias assessment, or proof of
personal applicability. Curated emergency patterns are also not exhaustive triage. Explicit
urgent symptoms are handled before research generation in the coach and at the daily/symptom
check-in boundaries; a missing warning does not establish safety.

## Verification And Privacy

Use the project environment, not system Python. From the repository root:

```bash
rag/.venv/bin/python -m unittest discover -s rag -p 'test_*.py'
python3 -m compileall -q rag papers
```

For the live local index and cached models, from `rag/`:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python test_retrieval.py
```

The unit suite uses synthetic state/model responses and temporary files. The live smoke test
checks pipeline execution and reports focused coverage gaps; it is not a retrieval accuracy
benchmark. No live generation evaluation or clinical validation is implied by those tests.

The pipeline is local after model setup; source refreshes use the network and Bevel uses
explicit clipboard movement. `.healthcoach/` is ignored by Git, but historical report,
profile, and schedule files are tracked. Review those before committing or sharing. This
implementation does not remove existing files from Git or rewrite private report/ledger data.
