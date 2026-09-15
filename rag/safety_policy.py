"""Deterministic admission and urgent-symptom rules. No I/O or model dependencies.

Admission is not evidence grading or medical clearance. Research and truthful exposure
records remain available even when routine active-plan actions are withheld.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping


POLICY = {
    "version": 1,
    "research": {
        "personal_instruction_patterns": (
            r"\byou (?:should|must|can|need to|could|may|ought to) (?:take|inject|dose|administer|start|stop|increase|decrease|combine|stack|taper|cycle|discontinue)\b",
            r"\b(?:i|we) recommend (?:taking|injecting|starting|stopping|increasing|decreasing|combining|stacking|tapering)\b",
            r"(?:^|[.!?]\s+)(?:take|inject|administer|start|stop|increase|decrease|combine|stack|taper|discontinue)\b",
            r"\byour (?:dose|dosage|cycle|protocol) (?:is|should|will|must)\b",
        ),
    },
    "candidate": {
        "experimental_classes": ("peptide", "nootropic", "gray_market", "grey_market"),
        "experimental_folders": ("08_peptides_gray", "05_fat_loss_drugs"),
        "restricted_policy_terms": (
            "skip", "clinician", "prescription", "deficiency gated", "intake clinician gated",
            "medication review", "safety review", "no personal protocol", "no cycle",
            "do not stack", "investigational", "unapproved", "preclinical",
            "medication kidney review", "gi and sodium load review",
        ),
        # Stable identity terms also cover typed rows whose display class was changed.
        # These are admission restrictions, not claims about approval in every jurisdiction.
        "review_identities": (
            "tirzepatide", "semaglutide", "retatrutide", "liraglutide", "saxenda", "victoza",
            "cagrilintide", "cagrisema", "amylin analog", "survodutide", "tesofensine",
            "mk 677", "mk677", "ibutamoren", "tesamorelin", "semax", "selank",
            "noopept", "omberacetam", "gvs 111", "gvs111", "bromantane", "bromantan", "ladasten", "actoprotector",
            "bpc 157", "bpc157", "cjc 1295", "cjc1295", "ipamorelin", "agomelatine",
            "aicar", "acadesine", "aniracetam", "aod 9604", "aod9604", "cerebrolysin",
            "dihexa", "dsip", "delta sleep inducing peptide", "epitalon", "epithalon",
            "5 amino 1mq", "five amino 1mq", "5amino1mq", "nnmt inhibitor", "follistatin",
            "ghk cu", "ghkcu", "copper peptide", "ghrp 2", "ghrp 6", "ghrp2", "ghrp6",
            "hexarelin", "humanin", "igf 1 lr3", "igf1 lr3", "long r3 igf", "isrib", "integrated stress response inhibitor",
            "kpv", "lys pro val", "ll 37", "ll37", "cathelicidin", "melanotan", "methylene blue",
            "methylthioninium", "mgf", "peg mgf", "mechano growth factor", "mots c", "motsc",
            "oxytocin", "peptide bioregulator", "peptide bioregulators", "khavinson", "phenibut",
            "beta phenyl gaba", "pt 141", "pt141", "bremelanotide", "racetam", "racetams",
            "piracetam", "sermorelin", "slu pp 332", "slupp332", "tak 653", "tak653",
            "tb 500", "tb500", "thymosin beta 4", "thymosin alpha 1", "thymalfasin",
            "sarm", "sarms", "selective androgen receptor modulator", "anabolic androgenic", "aas",
            "modafinil", "selegiline", "deprenyl", "cardarine", "gw501516", "gw 501516",
            "rapamycin", "sirolimus", "sr9009", "sr 9009", "stenabolic", "ostarine",
            "mk2866", "mk 2866", "enobosarm", "yohimbine", "enclomiphene", "kisspeptin",
            "gonadorelin", "kratom", "mitragynine", "tianeptine", "ru58841", "ru 58841",
            "dhea", "dehydroepiandrosterone", "testosterone", "trt", "pp405", "pp 405", "jxl069",
            "vitamin d", "vitamin d3", "25 oh d", "cholecalciferol", "magnesium", "zinc", "iron", "ferritin",
            "vitamin b12", "b12", "cobalamin", "folate", "methylfolate", "folic acid",
            "calcium", "berberine", "mucuna", "levodopa", "probiotic", "probiotics",
            "psyllium", "viscous fiber", "soluble fiber", "potassium", "sodium bicarbonate", "bicarbonate",
            "acetyl l carnitine", "alcar", "uridine", "ump",
            "5 htp", "5htp", "hydroxytryptophan", "cbd", "cannabidiol", "green tea extract", "egcg",
            "copper bicarbonate", "colloidal minerals", "adrenal cocktails", "cortisol detox",
            "fat burner", "fat burners", "proprietary focus blends", "high dose vitamin e",
            "high dose vitamin a", "beta carotene in smokers", "bcaas when protein is already high",
        ),
    },
    "urgent": {
        "symptom_patterns": (
            r"\bchest (?:pain|pressure|tightness)\b",
            r"\b(?:can(?:not|'t) breathe|struggling to breathe|severe (?:shortness of breath|difficulty breathing))\b",
            r"\b(?:face drooping|facial droop|one[- ]sided weakness|sudden (?:weakness|confusion|vision loss))\b",
            r"\b(?:slurred speech|coughing (?:up )?blood|vomiting blood|uncontrolled bleeding)\b",
            r"\b(?:throat|tongue) (?:is )?swelling\b",
            r"\b(?:seizure|unconscious|unresponsive|overdose|overdosed)\b",
            r"\b(?:fainting|fainted|severe abdominal pain|severe allergic reaction|anaphylaxis)\b",
            r"\b(?:breathing difficulty|difficulty breathing|toxic exposure|poisoning)\b",
            r"\b(?:worst headache of (?:my|their|his|her) life|sudden severe headache)\b",
            r"\b(?:suicidal|kill myself|end my life)\b",
        ),
        "noncurrent_pattern": r"\b(?:history of|last (?:year|month|week)|years? ago|previously|hypothetical|what if)\b",
        "question_pattern": r"\b(?:what (?:is|are|causes)|can .+ cause|does .+ cause|research|study|paper|article)\b",
        "current_pattern": r"\b(?:now|currently|today|i have (?!a history)|i am (?!reading|researching)|i feel|i'm (?!reading|researching)|he is|she is|they are|my .+ (?:has|is))\b",
        "negation_pattern": r"\b(?:no|not|without|denies|denied|don't have|do not have|never had)\b(?:\s+\w+){0,3}\s*$",
        "message": (
            "URGENT SAFETY WARNING: If these symptoms are happening now, call your local emergency "
            "number (911 in the US) or seek emergency care immediately. Do not wait for a model answer "
            "or a supplement recommendation. For immediate risk of self-harm, contact emergency services "
            "and someone who can stay with you. This is a limited deterministic warning, not a diagnosis "
            "or exhaustive triage; no warning does not establish safety."
        ),
    },
}


def _normal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", str(value)).casefold()).strip()


def candidate_gate(row: Mapping[str, Any], candidate: Any = None) -> dict[str, Any]:
    """Assess routine plan admission without modifying user facts or hiding research.

Optional direction/stack_fit fields let callers supply fresh evaluation context. A
catalog gate cannot be cleared by a user decision or by self-reported absence of blockers.
"""
    rules = POLICY["candidate"]
    reasons: list[str] = []
    if row.get("consideration_scope") == "research_only_topic":
        reasons.append("RESEARCH_ONLY_SCOPE")
    if row.get("blocker", {}).get("present"):
        reasons.append("USER_REPORTED_BLOCKER")
    if row.get("observed") == "harms":
        reasons.append("USER_REPORTED_HARM")
    if row.get("user_decision") == "reject":
        reasons.append("USER_REJECTED")
    if row.get("direction") == "harm":
        reasons.append("RETRIEVED_HARM")
    if "direction" not in row:
        if any(fit.get("direction") == "harm" for fit in row.get("reason_evaluations", {}).values() if isinstance(fit, Mapping)):
            reasons.append("RECORDED_EVIDENCE_HARM_REVIEW")
        if row.get("last_suggestion") in {"CONDITIONAL", "UNFAVORABLE"}:
            reasons.append("RECORDED_REVIEW_REQUIRED")
    if row.get("stack_fit") in {"interacts", "conflicts_lock"}:
        reasons.append("STACK_REVIEW_REQUIRED")

    identities = [row.get("id", ""), row.get("display_name", ""), *row.get("aliases", ())]
    folders = [row.get("folder", "")]
    if candidate is not None:
        identities.extend((candidate.key, candidate.name, *candidate.aliases))
        folders.extend(candidate.folders)
        policy = " " + _normal(candidate.policy) + " "
        if any(" " + term + " " in policy for term in rules["restricted_policy_terms"]):
            reasons.append("CATALOG_RESTRICTION")
        if candidate.gate:
            reasons.append("CATALOG_GATE_UNRESOLVED")

    identity_texts = [" " + _normal(value) + " " for value in identities if value]
    if any(" " + term + " " in text for term in rules["review_identities"] for text in identity_texts):
        reasons.append("IDENTITY_REVIEW_REQUIRED")
    if row.get("class") in rules["experimental_classes"] or any(
        str(folder or "").strip("/").startswith(prefix)
        for folder in folders for prefix in rules["experimental_folders"]
    ):
        reasons.append("EXPERIMENTAL_REVIEW_REQUIRED")
    return {"active_plan_allowed": not reasons, "reasons": reasons, "research_allowed": True}


def urgent_message(text: str) -> str | None:
    """Flag explicit present high-severity symptoms, not ordinary research questions.

Bare symptom phrases are accepted for check-in selectors. Negation and historical
context are deliberately local; this is not a natural-language triage engine.
"""
    rules = POLICY["urgent"]
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    for clause in re.split(r"[.!?;\n]|\bbut\b|\bhowever\b", normalized):
        current = re.search(rules["current_pattern"], clause)
        if not current and re.search(rules["noncurrent_pattern"], clause):
            continue
        if not current and re.search(rules["question_pattern"], clause):
            continue
        for pattern in rules["symptom_patterns"]:
            for match in re.finditer(pattern, clause):
                if re.search(rules["negation_pattern"], clause[:match.start()]):
                    continue
                return rules["message"]
    return None


def research_claim_allowed(text: str) -> bool:
    """Reject explicit personal treatment directives, not descriptive trial exposures.

    This deterministic language screen is deliberately limited, not a semantic validator.
    """
    return not any(re.search(pattern, text, re.I) for pattern in POLICY["research"]["personal_instruction_patterns"])
