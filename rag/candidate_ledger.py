#!/usr/bin/env python3
"""Private, durable candidate-ledger state for HealthCoach.

The implementation lives in Git; the JSON data does not. The default state directory is
ignored by Git and an explicit path override exists for tests and one-off inspection.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_LEDGER = HERE / ".healthcoach" / "candidate_ledger.json"
SCHEMA_VERSION = 2

CANDIDATE_CLASSES = (
    "supplement",
    "peptide",
    "nootropic",
    "gray_market",
    "food",
    "other",
)
CONSIDERATION_SCOPES = ("personal_candidate", "research_only_topic", "undecided")
USE_STATUSES = ("in_use", "not_in_use")
INTENTS = ("keep", "want_replace", "undecided")
OBSERVED_VALUES = ("helps", "none", "harms", "unknown")
BURDEN_VALUES = ("acceptable", "unacceptable", "unknown")
ANNOTATION_SOURCES = ("USER_REPORTED", "AUTHORED_CATALOG", "RETRIEVED")
USER_DECISIONS = ("undecided", "watch", "adopt", "reject")
COVERAGE_VALUES = ("STRONG", "WEAK", "NONE")
SUGGESTION_VALUES = (
    "CONTINUE_CURRENT",
    "ADOPT_CANDIDATE",
    "WATCH",
    "CONDITIONAL",
    "UNFAVORABLE",
)
REASON_OPTIONS = (
    ("fat_loss", "Fat loss"),
    ("lean_mass", "Lean-mass retention or gain"),
    ("strength", "Strength"),
    ("running", "Running or endurance"),
    ("recovery", "Recovery"),
    ("sleep", "Sleep"),
    ("cognition", "Cognition or focus"),
    ("joint_pain", "Joint pain, tendon, or injury context"),
    ("gi", "GI symptoms or tolerance"),
    ("hormone_context", "Hormone context"),
    ("longevity_curiosity", "Longevity curiosity"),
    ("lab_driven", "Laboratory-driven reason"),
    ("already_using", "Already using"),
    ("replace_existing", "Replace an existing item"),
    ("food_first_alternative", "Food-first alternative"),
    ("cost_simpler", "Lower cost or simpler stack"),
    ("other", "Other user-supplied reason"),
)
REASON_KEYS = tuple(key for key, _ in REASON_OPTIONS)
OUTCOME_REASON_KEYS = tuple(
    key for key in REASON_KEYS
    if key not in {"already_using", "replace_existing", "food_first_alternative", "cost_simpler"}
)
BASELINE_STATUSES = ("still_true", "update", "remove", "prefer_not")
TRISTATE_VALUES = ("yes", "no", "unknown")
WEIGHT_DIRECTIONS = ("lose", "maintain", "gain", "unknown")
SEX_VALUES = ("male", "female", "unknown")
NEAT_ACTIVITY_LEVELS = ("sedentary", "light", "moderate", "active")
EVIDENCE_APPETITES = ("conservative", "balanced", "exploratory")
FOOD_FIRST_VALUES = ("prefer", "none", "off")
MAX_NEW_ADOPTS_VALUES = ("0", "1", "2plus")
BUDGET_VALUES = ("low", "mid", "none", "unknown")


class LedgerError(ValueError):
    """Raised when private ledger state is malformed or an operation is invalid."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def ledger_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    override = os.environ.get("HC_CANDIDATE_LEDGER", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_LEDGER


def candidate_id(display_name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    if not value:
        raise LedgerError("Candidate name must contain a letter or number")
    return value


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "intake": default_intake(), "candidates": []}


def default_intake() -> dict[str, Any]:
    return {
        "baseline": {},
        "goals": [],
        "weight_direction": "unknown",
        "bodyweight_kg": None,
        "height_cm": None,
        "age_years": None,
        "sex": "unknown",
        "neat_activity_level": "sedentary",
        "flags": {
            "sleep_problem": "unknown",
            "training_limit_pain": "unknown",
            "tested_sport": "unknown",
            "gi_consider": "unknown",
        },
        "prefer_not_meds": False,
        "preferences": {
            "evidence_appetite": "balanced",
            "food_first": "none",
            "max_new_adopts": "1",
            "budget": "unknown",
            "sourcing_bar": None,
            "legal_sensitivity": None,
        },
        "followup_top_n": 10,
        "updated_at": "",
    }


def _strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _choice(value: Any, allowed: Sequence[str], default: str, field: str) -> str:
    normalized = str(value or default).strip()
    if normalized not in allowed:
        raise LedgerError(f"Invalid {field}: {normalized}")
    return normalized


def normalize_blocker(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    present = raw.get("present", False)
    if not isinstance(present, bool):
        raise LedgerError("blocker.present must be true or false")
    return {
        "present": present,
        "description": str(raw.get("description") or "").strip() or None,
        "provenance": "USER_REPORTED",
    }


def normalize_intake(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    normalized = default_intake()
    baseline = raw.get("baseline") if isinstance(raw.get("baseline"), Mapping) else {}
    for key, item in baseline.items():
        if not isinstance(item, Mapping):
            continue
        status = _choice(item.get("status"), BASELINE_STATUSES, "prefer_not", f"baseline.{key}.status")
        normalized["baseline"][str(key)] = {
            "status": status,
            "value": str(item.get("value") or "").strip() or None,
        }
    raw_goals = raw.get("goals", ())
    if isinstance(raw_goals, str):
        raw_goals = [value.strip() for value in raw_goals.split(",")]
    goals = _strings(raw_goals)
    if len(goals) > 3:
        raise LedgerError("intake goals must contain at most three ordered outcome keys")
    unknown_goals = sorted(set(goals) - set(OUTCOME_REASON_KEYS))
    if unknown_goals:
        raise LedgerError("Invalid intake goal key(s): " + ", ".join(unknown_goals))
    normalized["goals"] = goals
    normalized["weight_direction"] = _choice(
        raw.get("weight_direction"), WEIGHT_DIRECTIONS, "unknown", "weight_direction"
    )
    raw_bodyweight = raw.get("bodyweight_kg")
    if raw_bodyweight is None or raw_bodyweight == "":
        normalized["bodyweight_kg"] = None
    else:
        try:
            bodyweight_kg = float(raw_bodyweight)
        except (TypeError, ValueError):
            raise LedgerError("bodyweight_kg must be a number")
        if not 25 <= bodyweight_kg <= 400:
            raise LedgerError("bodyweight_kg must be between 25 and 400")
        normalized["bodyweight_kg"] = bodyweight_kg
    raw_height = raw.get("height_cm")
    if raw_height is None or raw_height == "":
        normalized["height_cm"] = None
    else:
        try:
            height_cm = float(raw_height)
        except (TypeError, ValueError):
            raise LedgerError("height_cm must be a number")
        if not 100 <= height_cm <= 250:
            raise LedgerError("height_cm must be between 100 and 250")
        normalized["height_cm"] = height_cm
    raw_age = raw.get("age_years")
    if raw_age is None or raw_age == "":
        normalized["age_years"] = None
    else:
        try:
            age_years = float(raw_age)
        except (TypeError, ValueError):
            raise LedgerError("age_years must be a number")
        if not 13 <= age_years <= 100:
            raise LedgerError("age_years must be between 13 and 100")
        normalized["age_years"] = age_years
    normalized["sex"] = _choice(raw.get("sex"), SEX_VALUES, "unknown", "sex")
    normalized["neat_activity_level"] = _choice(
        raw.get("neat_activity_level"), NEAT_ACTIVITY_LEVELS, "sedentary", "neat_activity_level"
    )
    flags = raw.get("flags") if isinstance(raw.get("flags"), Mapping) else {}
    normalized["flags"] = {
        key: _choice(flags.get(key), TRISTATE_VALUES, "unknown", f"flags.{key}")
        for key in normalized["flags"]
    }
    normalized["prefer_not_meds"] = bool(raw.get("prefer_not_meds", False))
    preferences = raw.get("preferences") if isinstance(raw.get("preferences"), Mapping) else {}
    normalized["preferences"] = {
        "evidence_appetite": _choice(
            preferences.get("evidence_appetite"), EVIDENCE_APPETITES, "balanced", "evidence_appetite"
        ),
        "food_first": _choice(preferences.get("food_first"), FOOD_FIRST_VALUES, "none", "food_first"),
        "max_new_adopts": _choice(
            preferences.get("max_new_adopts"), MAX_NEW_ADOPTS_VALUES, "1", "max_new_adopts"
        ),
        "budget": _choice(preferences.get("budget"), BUDGET_VALUES, "unknown", "budget"),
        "sourcing_bar": str(preferences.get("sourcing_bar") or "").strip() or None,
        "legal_sensitivity": str(preferences.get("legal_sensitivity") or "").strip() or None,
    }
    try:
        normalized["followup_top_n"] = min(50, max(1, int(raw.get("followup_top_n", 10))))
    except (TypeError, ValueError):
        raise LedgerError("followup_top_n must be an integer from 1 to 50") from None
    normalized["updated_at"] = str(raw.get("updated_at") or "").strip()
    return normalized


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    display_name = str(row.get("display_name", "")).strip()
    if not display_name:
        raise LedgerError("Candidate display_name is required")
    item_id = str(row.get("id", "")).strip() or candidate_id(display_name)
    item_class = str(row.get("class", "other")).strip()
    if item_class not in CANDIDATE_CLASSES:
        raise LedgerError(f"Invalid candidate class for {item_id}: {item_class}")
    raw_use_status = str(row.get("use_status", "not_in_use")).strip()
    # Schema v1 used research_only to mean only that an item was not currently in use.
    use_status = "not_in_use" if raw_use_status == "research_only" else raw_use_status
    if use_status not in USE_STATUSES:
        raise LedgerError(f"Invalid use_status for {item_id}: {use_status}")
    reasons = _strings(row.get("reasons", ()))
    unknown_reasons = sorted(set(reasons) - set(REASON_KEYS))
    if unknown_reasons:
        raise LedgerError(f"Invalid reason key(s) for {item_id}: {', '.join(unknown_reasons)}")
    consideration_scope = _choice(
        row.get("consideration_scope"), CONSIDERATION_SCOPES,
        "personal_candidate" if use_status == "in_use" else "undecided",
        f"consideration_scope for {item_id}",
    )
    intent = _choice(row.get("intent"), INTENTS, "undecided", f"intent for {item_id}")
    observed = _choice(row.get("observed"), OBSERVED_VALUES, "unknown", f"observed for {item_id}")
    burden = _choice(row.get("burden"), BURDEN_VALUES, "unknown", f"burden for {item_id}")
    decision = str(row.get("user_decision", "undecided")).strip()
    if decision not in USER_DECISIONS:
        raise LedgerError(f"Invalid user_decision for {item_id}: {decision}")
    last_coverage = str(row.get("last_coverage", "")).strip().upper()
    if last_coverage and last_coverage not in COVERAGE_VALUES:
        raise LedgerError(f"Invalid last_coverage for {item_id}: {last_coverage}")
    last_suggestion = str(row.get("last_suggestion", "")).strip().upper()
    if last_suggestion and last_suggestion not in SUGGESTION_VALUES:
        raise LedgerError(f"Invalid last_suggestion for {item_id}: {last_suggestion}")
    last_reported_decision = str(row.get("last_reported_decision", "")).strip().lower()
    if last_reported_decision and last_reported_decision not in USER_DECISIONS:
        raise LedgerError(f"Invalid last_reported_decision for {item_id}: {last_reported_decision}")
    raw_timestamps = row.get("timestamps") if isinstance(row.get("timestamps"), Mapping) else {}
    created = str(raw_timestamps.get("created_at", "")).strip() or utc_now()
    updated = str(raw_timestamps.get("updated_at", "")).strip() or created
    folder = str(row.get("folder") or "").strip() or None
    user_dose = str(row.get("user_dose") or "").strip() or None
    notes = str(row.get("notes") or "").strip() or None
    evaluations = row.get("reason_evaluations", {})
    if not isinstance(evaluations, Mapping):
        evaluations = {}
    raw_outcome_lines = row.get("outcome_lines") if isinstance(row.get("outcome_lines"), Mapping) else {}
    outcome_lines = {
        str(key): str(value).strip()
        for key, value in raw_outcome_lines.items()
        if key in REASON_KEYS and str(value).strip()
    }
    raw_sort_lists = row.get("last_sort_lists") if isinstance(row.get("last_sort_lists"), Mapping) else {}
    last_sort_lists = {
        key: int(value)
        for key, value in raw_sort_lists.items()
        if key in {"adopt_consider", "research"} and isinstance(value, int) and value > 0
    }
    return {
        "id": item_id,
        "display_name": display_name,
        "class": item_class,
        "aliases": _strings(row.get("aliases", ())),
        "folder": folder,
        "consideration_scope": consideration_scope,
        "use_status": use_status,
        "intent": intent,
        "observed": observed,
        "burden": burden,
        "blocker": normalize_blocker(row.get("blocker")),
        "reasons": reasons,
        "outcome_lines": outcome_lines,
        "user_dose": user_dose,
        "notes": notes,
        "last_coverage": last_coverage,
        "last_suggestion": last_suggestion,
        "last_suggestion_reason": str(row.get("last_suggestion_reason") or "").strip(),
        "last_sort_lists": last_sort_lists,
        "last_intake_fields_used": _strings(row.get("last_intake_fields_used", ())),
        "last_reported_decision": last_reported_decision,
        "user_decision": decision,
        "reason_evaluations": copy.deepcopy(dict(evaluations)),
        "timestamps": {"created_at": created, "updated_at": updated},
    }


def normalize_ledger(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not data:
        return empty_ledger()
    version = data.get("schema_version", 1)
    if version not in (1, SCHEMA_VERSION):
        raise LedgerError(f"Unsupported candidate-ledger schema_version: {version}")
    raw_rows = data.get("candidates", ())
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise LedgerError("Candidate ledger 'candidates' must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise LedgerError("Every candidate ledger row must be an object")
        row = normalize_row(raw)
        if row["id"] in seen:
            raise LedgerError(f"Duplicate candidate id: {row['id']}")
        seen.add(row["id"])
        rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "intake": normalize_intake(data.get("intake")),
        "candidates": rows,
    }


def load_ledger(path: str | Path | None = None) -> dict[str, Any]:
    target = ledger_path(path)
    if not target.exists():
        return empty_ledger()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"Cannot read candidate ledger {target}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise LedgerError(f"Candidate ledger {target} must contain a JSON object")
    return normalize_ledger(value)


def save_ledger(data: Mapping[str, Any], path: str | Path | None = None) -> Path:
    target = ledger_path(path)
    normalized = normalize_ledger(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def rows_by_id(data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in normalize_ledger(data)["candidates"]}


def upsert_candidate(
    data: Mapping[str, Any],
    *,
    item_id: str | None,
    display_name: str,
    item_class: str,
    aliases: Sequence[str] = (),
    folder: str | None = None,
    consideration_scope: str = "undecided",
    use_status: str = "not_in_use",
    intent: str = "undecided",
    observed: str = "unknown",
    burden: str = "unknown",
    blocker: Mapping[str, Any] | None = None,
    reasons: Sequence[str] = (),
    outcome_lines: Mapping[str, str] | None = None,
    user_dose: str | None = None,
    notes: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    ledger = normalize_ledger(data)
    wanted_id = item_id or candidate_id(display_name)
    existing = next((row for row in ledger["candidates"] if row["id"] == wanted_id), None)
    now = utc_now()
    if existing:
        merged = dict(existing)
        merged.update({
            "display_name": display_name or existing["display_name"],
            "class": item_class or existing["class"],
            "aliases": _strings((*existing.get("aliases", ()), *aliases)),
            "folder": folder or existing.get("folder"),
            "consideration_scope": consideration_scope or existing.get("consideration_scope"),
            "use_status": use_status,
            "intent": intent or existing.get("intent"),
            "observed": observed or existing.get("observed"),
            "burden": burden or existing.get("burden"),
            "blocker": blocker if blocker is not None else existing.get("blocker"),
            "reasons": _strings((*existing.get("reasons", ()), *reasons)),
            "outcome_lines": outcome_lines if outcome_lines is not None else existing.get("outcome_lines"),
            "user_dose": user_dose if user_dose is not None else existing.get("user_dose"),
            "notes": notes if notes is not None else existing.get("notes"),
            "timestamps": {
                "created_at": existing["timestamps"]["created_at"],
                "updated_at": now,
            },
        })
        normalized = normalize_row(merged)
        index = ledger["candidates"].index(existing)
        ledger["candidates"][index] = normalized
        return ledger, normalized, False
    row = normalize_row({
        "id": wanted_id,
        "display_name": display_name,
        "class": item_class,
        "aliases": aliases,
        "folder": folder,
        "consideration_scope": consideration_scope,
        "use_status": use_status,
        "intent": intent,
        "observed": observed,
        "burden": burden,
        "blocker": blocker or {},
        "reasons": reasons,
        "outcome_lines": outcome_lines or {},
        "user_dose": user_dose,
        "notes": notes,
        "last_coverage": "",
        "last_suggestion": "",
        "last_suggestion_reason": "",
        "last_sort_lists": {},
        "last_intake_fields_used": [],
        "last_reported_decision": "",
        "user_decision": "undecided",
        "reason_evaluations": {},
        "timestamps": {"created_at": now, "updated_at": now},
    })
    ledger["candidates"].append(row)
    return ledger, row, True


def update_candidate(
    data: Mapping[str, Any], item_id: str, **changes: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    ledger = normalize_ledger(data)
    row = next((item for item in ledger["candidates"] if item["id"] == item_id), None)
    if row is None:
        raise LedgerError(f"Unknown candidate id: {item_id}")
    updated = dict(row)
    updated.update(changes)
    updated["timestamps"] = {
        "created_at": row["timestamps"]["created_at"],
        "updated_at": utc_now(),
    }
    normalized = normalize_row(updated)
    ledger["candidates"][ledger["candidates"].index(row)] = normalized
    return ledger, normalized


def update_intake(data: Mapping[str, Any], intake: Mapping[str, Any]) -> dict[str, Any]:
    ledger = normalize_ledger(data)
    normalized = normalize_intake(intake)
    normalized["updated_at"] = utc_now()
    ledger["intake"] = normalized
    return normalize_ledger(ledger)


def regeneration_diff(
    rows: Sequence[Mapping[str, Any]],
    evaluations: Mapping[str, Mapping[str, Any]],
    inventory_ids: Iterable[str],
    matrix_ids: Iterable[str],
) -> dict[str, list[str]]:
    inventory = set(inventory_ids)
    matrix = set(matrix_ids)
    added: list[str] = []
    adopted: list[str] = []
    suggestion_changes: list[str] = []
    coverage_changes: list[str] = []
    missing: list[str] = []
    for raw in rows:
        row = normalize_row(raw)
        item_id = row["id"]
        current = evaluations.get(item_id, {})
        coverage = str(current.get("coverage", "NONE"))
        suggestion = str(current.get("system_suggestion", "WATCH"))
        if not row["last_coverage"] and not row["last_suggestion"]:
            added.append(item_id)
        if row["user_decision"] == "adopt" and row.get("last_reported_decision") != "adopt":
            adopted.append(item_id)
        if row["last_suggestion"] and row["last_suggestion"] != suggestion:
            suggestion_changes.append(f"{item_id}: {row['last_suggestion']} → {suggestion}")
        if row["last_coverage"] and row["last_coverage"] != coverage:
            coverage_changes.append(f"{item_id}: {row['last_coverage']} → {coverage}")
        if item_id not in inventory or item_id not in matrix:
            absent = []
            if item_id not in inventory:
                absent.append("inventory")
            if item_id not in matrix:
                absent.append("matrix")
            missing.append(f"{item_id} ({'+'.join(absent)})")
    return {
        "ledger_added": added,
        "newly_adopted": adopted,
        "suggestion_changes": suggestion_changes,
        "coverage_changes": coverage_changes,
        "selected_but_missing_from_inventory": missing,
    }


def record_reported_state(
    data: Mapping[str, Any], evaluations: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    ledger = normalize_ledger(data)
    now = utc_now()
    for row in ledger["candidates"]:
        current = evaluations.get(row["id"])
        if current:
            row["last_coverage"] = str(current.get("coverage", row["last_coverage"]))
            row["last_suggestion"] = str(current.get("system_suggestion", row["last_suggestion"]))
            row["last_suggestion_reason"] = str(current.get("suggestion_reason", ""))
            sort_lists = current.get("sort_lists")
            if isinstance(sort_lists, Mapping):
                row["last_sort_lists"] = dict(sort_lists)
            row["last_intake_fields_used"] = _strings(current.get("intake_fields_used", ()))
            per_reason = current.get("per_reason")
            if isinstance(per_reason, Mapping):
                row["reason_evaluations"] = copy.deepcopy(dict(per_reason))
        row["last_reported_decision"] = row["user_decision"]
        row["timestamps"]["updated_at"] = now
    return normalize_ledger(ledger)
