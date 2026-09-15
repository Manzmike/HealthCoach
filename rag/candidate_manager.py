#!/usr/bin/env python3
"""Add, decide, list, and inspect private HealthCoach candidate-ledger rows."""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

import candidate_ledger as CL
import diet_rules as DR
import food_serving_guidance as FSG


HERE = Path(__file__).resolve().parent
PAPERS = HERE.parent / "papers"
console = Console()

_CURATED_EVIDENCE_PATH = HERE / "food_curated_evidence.json"
_COVERAGE_RANK = {"NONE": 0, "WEAK": 1, "STRONG": 2}


def _load_curated_food_evidence() -> dict[str, Any]:
    if not _CURATED_EVIDENCE_PATH.exists():
        return {}
    return json.loads(_CURATED_EVIDENCE_PATH.read_text())


_CURATED_FOOD_EVIDENCE = _load_curated_food_evidence()


def _effective_food_coverage(item_id: str, local_coverage: str) -> str:
    """Coverage-boost only (see food_evidence.py for the full rationale): real curated ABCD
    citations can raise coverage to STRONG — lifting the B+ replication cap — but never supply
    a favor/harm vote themselves, since we only have their titles/tiers/URLs, not full text."""
    rec = _CURATED_FOOD_EVIDENCE.get(item_id)
    if not rec:
        return local_coverage
    ab_sources = sum(1 for s in rec.get("sources", []) if s.get("tier") in ("A", "B"))
    curated_coverage = "STRONG" if ab_sources >= 2 else local_coverage
    if _COVERAGE_RANK.get(curated_coverage, 0) > _COVERAGE_RANK.get(local_coverage, 0):
        return curated_coverage
    return local_coverage

BASELINE_FACTS = (
    ("body_context", "Body/weight context"),
    ("goals", "Existing goal narrative"),
    ("training", "Training pattern"),
    ("injuries", "Pain or injury context"),
    ("medications", "Medication context"),
    ("current_supplements", "Current supplement text"),
    ("confirmed_deficiencies_or_labs", "Known laboratory or deficiency context"),
    ("conditions_and_safety_flags", "Conditions or safety flags"),
    ("diet_and_gi", "Diet and GI context"),
    ("sleep", "Sleep context"),
    ("preferences", "Product or practical preferences"),
    ("timeline", "Time horizon"),
)
FOLLOWUP_DETAIL_REASONS = {"recovery", "hormone_context", "longevity_curiosity", "other"}


def csv_values(raw: str | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in (raw or "").split(",") if value.strip()))


def reason_values(raw: str | None, *, require: bool = False) -> list[str]:
    values = csv_values(raw)
    unknown = sorted(set(values) - set(CL.REASON_KEYS))
    if unknown:
        raise CL.LedgerError("Unknown reason key(s): " + ", ".join(unknown))
    if require and not values:
        raise CL.LedgerError("Choose at least one reason; use 'other' when no named reason fits")
    return values


def find_ledger_row(ledger: dict[str, Any], value: str) -> dict[str, Any]:
    """Resolve one private row by stable ID, display name, or recorded alias."""
    wanted = value.strip().casefold()
    matches = [
        row for row in ledger["candidates"]
        if wanted in {
            str(row["id"]).casefold(),
            str(row["display_name"]).casefold(),
            *(str(alias).casefold() for alias in row.get("aliases", ())),
        }
    ]
    if not matches:
        raise CL.LedgerError(f"Unknown candidate name or id: {value}")
    if len(matches) > 1:
        ids = ", ".join(str(row["id"]) for row in matches)
        raise CL.LedgerError(f"Ambiguous candidate name or alias '{value}'; use one of these IDs: {ids}")
    return matches[0]


def catalog_rows() -> list[tuple[Any, str]]:
    import supplement_audit as audit

    rows: list[tuple[Any, str]] = []
    rows.extend((candidate, "supplement") for candidate in audit.CATALOG)
    rows.extend((candidate, audit.default_ledger_class(candidate)) for candidate in audit.PEPTIDE_CATALOG)
    rows.extend((candidate, "food") for candidate in audit.WHOLE_FOOD_CATALOG)
    return rows


def find_catalog(value: str) -> tuple[Any, str] | None:
    wanted = value.strip().lower()
    exact = [
        item for item in catalog_rows()
        if wanted in {item[0].key.lower(), item[0].name.lower(), *(alias.lower() for alias in item[0].aliases)}
    ]
    if len(exact) == 1:
        return exact[0]
    contains = [
        item for item in catalog_rows()
        if wanted in (item[0].name + " " + " ".join(item[0].aliases)).lower()
    ]
    return contains[0] if len(contains) == 1 else None


def candidate_flags(row: dict[str, Any]) -> str:
    evaluations = row.get("reason_evaluations", {})
    flags: list[str] = []
    if not row.get("reasons"):
        flags.append("REASON_UNSPECIFIED")
    if row.get("blocker", {}).get("present"):
        flags.append("USER_REPORTED_BLOCKER")
    if row.get("observed") == "harms":
        flags.append("USER_REPORTED_HARM")
    try:
        import supplement_audit as audit

        candidate, built_in = audit.candidate_from_ledger_row(row)
        if built_in and candidate.policy:
            flags.append(f"LEGACY_POLICY={candidate.policy}")
        if built_in and candidate.gate:
            flags.append(f"LEGACY_GATE={candidate.gate}")
    except (ImportError, KeyError, ValueError):
        # The ledger remains usable on its own; inspect provides full provenance when the
        # audit module is available.
        pass
    for value in evaluations.values() if isinstance(evaluations, dict) else ():
        if not isinstance(value, dict):
            continue
        stack_fit = str(value.get("stack_fit", ""))
        if stack_fit in {"interacts", "conflicts_lock"}:
            flags.append(stack_fit.upper())
        for key in ("regulatory", "sport", "sourcing"):
            annotation = value.get(key, {})
            if isinstance(annotation, dict) and annotation.get("present"):
                flags.append(key.upper())
    return ", ".join(dict.fromkeys(flags)) or "none"


def row_direction(row: dict[str, Any]) -> str:
    evaluations = row.get("reason_evaluations", {})
    values = {
        str(value.get("direction", "unknown"))
        for value in evaluations.values()
        if isinstance(value, dict)
    }
    values.discard("unknown")
    if not values:
        return "unknown"
    return next(iter(values)) if len(values) == 1 else "mixed"


def matrix_table(rows: Sequence[dict[str, Any]]) -> Table:
    table = Table(title="Candidate stack matrix — private ledger", box=box.ROUNDED, show_lines=False)
    for heading in ("Name", "Class", "Use/research", "Reasons", "Coverage", "Direction", "Flags", "Suggestion", "Decision"):
        table.add_column(heading, overflow="fold")
    if not rows:
        table.add_row("No candidates", "—", "—", "—", "—", "—", "—", "—", "—")
    for row in rows:
        table.add_row(
            row["display_name"],
            row["class"],
            f"{row['use_status']} / {row['consideration_scope']}",
            ", ".join(row.get("reasons", ())) or "UNSPECIFIED",
            row.get("last_coverage") or "NOT_EVALUATED",
            row_direction(row),
            candidate_flags(row),
            row.get("last_suggestion") or "WATCH",
            row["user_decision"],
        )
    return table


def print_matrix(
    path: str | Path | None = None,
    *,
    decision: str | None = None,
    item_class: str | None = None,
) -> int:
    ledger = CL.load_ledger(path)
    rows = ledger["candidates"]
    if decision is not None:
        rows = [row for row in rows if row["user_decision"] == decision]
    if item_class is not None:
        rows = [row for row in rows if row["class"] == item_class]
    console.print(matrix_table(rows))
    console.print(f"[dim]Private state: {CL.ledger_path(path)} — {len(rows)} of {len(ledger['candidates'])} shown[/dim]")
    return 0


# Six real-world states, crossing the decision you recorded against whether you're actually
# taking the thing. The two "still/not incorporated" mismatches are action items, not just labels.
STATUS_GROUPS: tuple[tuple[str, str], ...] = (
    ("approved_incorporated", "ADOPTION INTENT & REPORTED IN USE (not medical approval)"),
    ("approved_pending", "ADOPTION INTENT & NOT REPORTED IN USE"),
    ("denied_still_in_use", "REJECTED BUT REPORTED IN USE — review, no automatic change"),
    ("denied_clear", "REJECTED & NOT REPORTED IN USE"),
    ("watching", "WATCHING — waiting zone"),
    ("undecided", "UNDECIDED"),
)


def status_group(row: dict[str, Any]) -> str:
    decision = row["user_decision"]
    in_use = row["use_status"] == "in_use"
    if decision == "adopt":
        return "approved_incorporated" if in_use else "approved_pending"
    if decision == "reject":
        return "denied_still_in_use" if in_use else "denied_clear"
    if decision == "watch":
        return "watching"
    return "undecided"


def sync_food_catalog(args: argparse.Namespace) -> int:
    """Add every built-in whole-food catalog item not already in the ledger, as a fresh
    undecided row ready for `rank`/`triage`. Never touches an item already in the ledger —
    an existing decision, in-use status, or recorded reasons are left completely alone, so
    this is always safe to re-run after the catalog grows."""
    import supplement_audit as audit

    ledger = CL.load_ledger(args.ledger)
    existing_ids = {row["id"] for row in ledger["candidates"]}
    added: list[str] = []
    for candidate in audit.WHOLE_FOOD_CATALOG:
        if candidate.key in existing_ids:
            continue
        ledger, _row, created = CL.upsert_candidate(
            ledger,
            item_id=candidate.key,
            display_name=candidate.name,
            item_class=audit.default_ledger_class(candidate),
            aliases=candidate.aliases,
            folder=candidate.folders[0] if candidate.folders else None,
        )
        if created:
            added.append(candidate.name)
    if not added:
        console.print("[dim]Every catalog food is already in the ledger — nothing to add.[/dim]")
        return 0
    CL.save_ledger(ledger, args.ledger)
    console.print(f"[green]Added {len(added)} new food candidate(s) to the ledger as undecided:[/green]")
    for name in added:
        console.print(f"  - {name}")
    console.print("\nNext: python3 candidate_manager.py rank --categories food --all-decisions --limit 0")
    return 0


def print_status(path: str | Path | None = None, *, item_class: str | None = None) -> int:
    ledger = CL.load_ledger(path)
    rows = ledger["candidates"]
    if item_class is not None:
        rows = [row for row in rows if row["class"] == item_class]
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in STATUS_GROUPS}
    for row in rows:
        grouped[status_group(row)].append(row)
    for key, label in STATUS_GROUPS:
        members = grouped[key]
        style = "red" if key == "denied_still_in_use" else ("yellow" if key == "watching" else "bright_cyan")
        console.print(Panel.fit(
            "\n".join(f"- {row['display_name']}" for row in members) or "(none)",
            title=f"{label} ({len(members)})",
            border_style=style,
        ))
    console.print(f"[dim]Private state: {CL.ledger_path(path)} — {len(rows)} candidate(s) shown[/dim]")
    return 0


def curses_multiselect(rows: Sequence[dict[str, Any]]) -> set[str] | None:
    """Space toggles a row, Enter confirms the current selection, q/Esc cancels (returns None)."""
    selected: set[str] = {row["id"] for row in rows if row["user_decision"] == "adopt"}
    result: dict[str, set[str] | None] = {"value": None}

    def run(stdscr) -> None:
        curses.curs_set(0)
        cursor = 0
        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            stdscr.addnstr(
                0, 0, "REVIEW BATCH  —  Space select/unselect · Enter add selected as ADOPT · q cancel",
                max(1, width - 1), curses.A_BOLD,
            )
            header = f"    {'Name':<38}{'Class':<12}{'Coverage':<10}{'Suggestion':<14}{'Decision':<10}"
            stdscr.addnstr(2, 0, header, max(1, width - 1), curses.A_UNDERLINE)
            page_size = max(1, height - 5)
            first = max(0, min(cursor - page_size // 2, len(rows) - page_size))
            for index in range(first, min(len(rows), first + page_size)):
                row = rows[index]
                mark = "[x]" if row["id"] in selected else "[ ]"
                line = (
                    f"{mark} {row['display_name'][:36]:<38}{row['class']:<12}"
                    f"{(row.get('last_coverage') or 'not evaluated')[:9]:<10}"
                    f"{(row.get('last_suggestion') or 'WATCH')[:13]:<14}{row['user_decision']:<10}"
                )
                attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                stdscr.addnstr(3 + (index - first), 0, line, max(1, width - 1), attr)
            stdscr.addnstr(
                height - 1, 0, f"{len(selected)} selected of {len(rows)}",
                max(1, width - 1), curses.A_DIM,
            )
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(rows)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(rows)
            elif key == ord(" "):
                row_id = rows[cursor]["id"]
                selected.symmetric_difference_update({row_id})
            elif key in (10, 13, curses.KEY_ENTER):
                result["value"] = set(selected)
                return
            elif key in (ord("q"), 27):
                result["value"] = None
                return

    curses.wrapper(run)
    return result["value"]


def review_batch(args: argparse.Namespace) -> int:
    """Curses checklist over ledger rows; Enter sets every checked row to user_decision=adopt."""
    ledger = CL.load_ledger(args.ledger)
    rows = [
        row for row in ledger["candidates"]
        if (args.item_class is None or row["class"] == args.item_class)
        and (not args.undecided_only or row["user_decision"] == "undecided")
    ]
    if not rows:
        console.print("[yellow]No matching candidates to review.[/yellow]")
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console.print("The review screen needs an interactive terminal. Run this from a real shell, not a pipe.")
        return 2
    selected = curses_multiselect(rows)
    if selected is None:
        console.print("Cancelled; no changes made.")
        return 0
    changed = 0
    for row in rows:
        if row["id"] in selected and row["user_decision"] != "adopt":
            if not _adoption_allowed(ledger, row):
                continue
            ledger, _updated = CL.update_candidate(ledger, row["id"], user_decision="adopt")
            changed += 1
    if changed:
        CL.save_ledger(ledger, args.ledger)
    console.print(f"[green]Recorded adoption intent for {changed} item(s).[/green] Actual use is unchanged.")
    return 0


def add_candidate(args: argparse.Namespace) -> int:
    ledger = CL.load_ledger(args.ledger)
    matched = find_catalog(args.catalog) if args.catalog else None
    if args.catalog and matched is None:
        raise CL.LedgerError(f"Catalog candidate is missing or ambiguous: {args.catalog}")
    if matched:
        candidate, item_class = matched
        item_id = candidate.key
        display_name = candidate.name
        aliases = list(dict.fromkeys((*candidate.aliases, *csv_values(args.aliases))))
        folder = args.folder or (candidate.folders[0] if candidate.folders else None)
        item_class = args.item_class or item_class
    else:
        if not args.name:
            raise CL.LedgerError("Typed add requires --name")
        item_id = args.item_id or CL.candidate_id(args.name)
        display_name = args.name
        aliases = csv_values(args.aliases)
        folder = args.folder
        item_class = args.item_class
    if not item_class:
        raise CL.LedgerError("Choose a candidate class")
    reasons = reason_values(args.reasons, require=False)
    ledger, row, created = CL.upsert_candidate(
        ledger,
        item_id=item_id,
        display_name=display_name,
        item_class=item_class,
        aliases=aliases,
        folder=folder,
        consideration_scope=args.consideration_scope,
        use_status=args.use_status,
        intent=args.intent,
        observed=args.observed,
        burden=args.burden,
        blocker={
            "present": bool(args.blocker),
            "description": args.blocker,
            "provenance": "USER_REPORTED",
        },
        reasons=reasons,
        user_dose=args.user_dose,
        notes=args.notes,
    )
    CL.save_ledger(ledger, args.ledger)
    console.print(f"[green]{'Added' if created else 'Updated'}[/green] {row['display_name']} ({row['id']})")
    return 0


def _adoption_allowed(
    ledger: dict[str, Any], row: dict[str, Any], evaluation: dict[str, Any] | None = None,
) -> bool:
    import supplement_audit as audit

    if evaluation is None:
        evaluation = {"direction": "harm" if any(
            fit.get("direction") == "harm" for fit in row.get("reason_evaluations", {}).values()
            if isinstance(fit, dict)
        ) else "unknown"}
    gate = audit.candidate_plan_gate(dict(row, user_decision="adopt"), ledger["candidates"], evaluation)
    if not gate["active_plan_allowed"]:
        console.print(
            f"[yellow]Adoption withheld for {row['display_name']}: {', '.join(gate['reasons'])}. "
            "Research and reported actual use remain available; existing decision/use/dose are unchanged.[/yellow]"
        )
    return gate["active_plan_allowed"]


def decide_candidate(args: argparse.Namespace) -> int:
    ledger = CL.load_ledger(args.ledger)
    target = find_ledger_row(ledger, args.item_id)
    if args.decision == "adopt" and target["user_decision"] != "adopt" and not _adoption_allowed(ledger, target):
        return 2
    ledger, row = CL.update_candidate(ledger, target["id"], user_decision=args.decision)
    CL.save_ledger(ledger, args.ledger)
    console.print(f"[green]Decision saved:[/green] {row['display_name']} → {row['user_decision']}")
    if args.decision == "adopt":
        console.print("Adoption records intent only, not medical approval or actual use.")
    return 0


def edit_candidate(args: argparse.Namespace) -> int:
    ledger = CL.load_ledger(args.ledger)
    current = find_ledger_row(ledger, args.item_id)
    changes: dict[str, Any] = {}
    if args.item_class is not None:
        changes["class"] = args.item_class
    if args.use_status is not None:
        changes["use_status"] = args.use_status
    if args.consideration_scope is not None:
        changes["consideration_scope"] = args.consideration_scope
    if args.intent is not None:
        changes["intent"] = args.intent
    if args.observed is not None:
        changes["observed"] = args.observed
    if args.burden is not None:
        changes["burden"] = args.burden
    if args.blocker is not None:
        changes["blocker"] = {
            "present": bool(args.blocker),
            "description": args.blocker or None,
            "provenance": "USER_REPORTED",
        }
    if args.reasons is not None:
        changes["reasons"] = reason_values(args.reasons, require=False)
    if args.aliases is not None:
        changes["aliases"] = csv_values(args.aliases)
    if args.folder is not None:
        changes["folder"] = args.folder or None
    if args.user_dose is not None:
        changes["user_dose"] = args.user_dose or None
    if args.notes is not None:
        changes["notes"] = args.notes or None
    ledger, row = CL.update_candidate(ledger, current["id"], **changes)
    CL.save_ledger(ledger, args.ledger)
    console.print(f"[green]Updated[/green] {row['display_name']}")
    return 0


def folder_pdf_count(folders: Sequence[str]) -> int:
    seen: set[Path] = set()
    for folder in folders:
        root = PAPERS / folder
        if not root.exists():
            continue
        for path in root.rglob("*.pdf"):
            if "_pruned" not in path.parts:
                seen.add(path.resolve())
    return len(seen)


def inspect_candidate(args: argparse.Namespace) -> int:
    import supplement_audit as audit

    ledger = CL.load_ledger(args.ledger)
    row = find_ledger_row(ledger, args.item_id)
    candidate, built_in = audit.candidate_from_ledger_row(row)
    reasons = row.get("reasons", ())
    gate = audit.candidate_plan_gate(row, ledger["candidates"])
    week = gate["active_plan_allowed"] and (row["user_decision"] == "adopt" or row["use_status"] == "in_use")
    console.print(Panel.fit(
        "\n".join((
            f"ID: {row['id']}",
            f"Name: {row['display_name']}",
            f"Class: {row['class']}",
            f"Use status: {row['use_status']}",
            f"Consideration scope: {row['consideration_scope']}",
            f"Intent: {row['intent']}",
            f"Observed: {row['observed']} (USER_REPORTED)",
            f"Burden: {row['burden']} (USER_REPORTED)",
            f"Blocker: {row['blocker']['description'] if row['blocker']['present'] else 'none reported'}",
            f"Reasons: {', '.join(reasons) or 'UNSPECIFIED'}",
            f"Decision: {row['user_decision']}",
            f"User dose: {row.get('user_dose') or 'unset'}",
            f"Aliases: {', '.join(row.get('aliases', ())) or 'none'}",
            f"Folders: {', '.join(candidate.folders) or 'none; exact-term global search'}",
            f"Cached coverage: {row.get('last_coverage') or 'not evaluated'}",
            f"Cached suggestion: {row.get('last_suggestion') or 'WATCH'}",
            f"Why: {row.get('last_suggestion_reason') or 'not evaluated'}",
            f"Sort positions: {row.get('last_sort_lists') or 'not ranked'}",
            f"Intake fields used: {', '.join(row.get('last_intake_fields_used', ())) or 'not recorded'}",
        )),
        title="Candidate ledger row",
        border_style="bright_cyan",
    ))
    if row["class"] == "food":
        guidance = FSG.serving_guidance(row["id"])
        cap_line = (
            f"Weekly max: {guidance['weekly_max_servings']} servings/week — {guidance['weekly_max_reason']} "
            f"({guidance['weekly_max_source']})"
            if guidance["weekly_max_servings"] else "Weekly max: none — no real moderation guideline applies to this food"
        )
        console.print(Panel.fit(
            f"Serving size: {guidance['serving_size']}\n{cap_line}",
            title="Serving guidance",
            border_style="green",
        ))
    policy = candidate.policy or "none"
    catalog_gate = candidate.gate or "none"
    provenance = "built-in Candidate.policy / Candidate.gate" if built_in else "custom ledger row; no catalog policy"
    applied = "preliminary_decisions(); stack_action() for legacy Part IV tables" if built_in else "new ledger evaluation only"
    disputed = (
        "The shared safety policy controls plan admission, not research depth. "
        "experimental_screen_markdown() is coverage triage only."
        if candidate.queue == audit.QUEUE_PEPTIDE else
        "No gray recommendation function applies."
    )
    console.print(Panel.fit(
        f"Policy: {policy}\nGate: {catalog_gate}\nField origin: {provenance}\nLegacy applying functions: {applied}\n{disputed}",
        title="Policy provenance",
        border_style="yellow",
    ))
    console.print(
        f"Surfaces: matrix=yes; inventory=yes; fixed card=yes; "
        f"routine week={'yes' if week else 'no'}; reported exposure={row['use_status']}; "
        f"admission reasons={', '.join(gate['reasons']) or 'none (not medical clearance)'}."
    )
    console.print(f"PDFs in configured folders: {folder_pdf_count(candidate.folders)}")
    if args.cached_only:
        console.print("Retrieval: cached-only requested; hybrid/vector mode was not tested.")
        return 0

    import lancedb
    from sentence_transformers import SentenceTransformer
    import coach as HC

    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    chunk_count = 0
    if candidate.folders:
        try:
            chunk_count = tbl.count_rows(audit.sql_folder_filter(candidate.folders))
        except Exception:
            chunk_count = 0
    reranker = HC.load_reranker()
    reason_labels = [dict(CL.REASON_OPTIONS).get(reason, reason) for reason in reasons]
    evidence = audit.retrieve_candidate(tbl, emb, reranker, candidate, reason_labels or ["unspecified reason"], "")
    live_evaluation = audit.evaluate_ledger_rows(
        [row], {row["id"]: candidate}, {row["id"]: evidence}, {}, ledger["intake"],
        ledger_rows=ledger["candidates"],
    )[row["id"]]
    mode = "VECTOR-ONLY FALLBACK" if evidence.hybrid_fallback else "HYBRID"
    console.print(Panel.fit(
        f"Configured-folder chunks: {chunk_count}\n"
        f"Retained hits: {len(evidence.hits)}\n"
        f"Coverage: {evidence.coverage}\n"
        f"Unique A/B human sources: {evidence.unique_papers}\n"
        f"Best grade: {evidence.best_grade}\n"
        f"Live suggestion: {live_evaluation['system_suggestion']}\n"
        f"Why: {live_evaluation['suggestion_reason']}\n"
        f"Search mode: {mode}\n"
        f"Fallback details: {', '.join(evidence.retrieval_notes) or 'none'}",
        title="Live local evidence inspection",
        border_style="green" if not evidence.hybrid_fallback else "yellow",
    ))
    for hit in evidence.hits[:8]:
        console.print(
            f"- [{hit.get('grade', '—')} | {hit.get('folder', 'unknown')} | "
            f"{hit.get('doi') or 'no-doi'}] {os.path.basename(hit.get('source_pdf', 'unknown'))}"
        )
    return 0


# Letter grade bands, highest threshold first. Score combines evidence quality with how well
HERB_IDS = frozenset({
    "oregano", "saffron_food", "garlic_food", "ginger_food",
    "cinnamon_food", "turmeric_food", "parsley", "cilantro",
})

BATCH_LOG_PATH = HERE / ".healthcoach" / "batch_log.json"
BATCH_LOG_MAX = 20


def _load_batch_log() -> list[dict[str, Any]]:
    if not BATCH_LOG_PATH.exists():
        return []
    try:
        return json.loads(BATCH_LOG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_batch_log(log: list[dict[str, Any]]) -> None:
    BATCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_LOG_PATH.write_text(json.dumps(log[-BATCH_LOG_MAX:], indent=2))


def _start_batch(kind: str, item_class: str | None) -> dict[str, Any]:
    return {
        "id": dt.datetime.now().strftime("%Y%m%d-%H%M%S"),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "kind": kind, "item_class": item_class, "changes": [],
    }


def _record_change(batch: dict[str, Any], row: dict[str, Any]) -> None:
    """Snapshot a row's state BEFORE you change it, so `undo` can put it back."""
    batch["changes"].append({
        "id": row["id"], "display_name": row["display_name"],
        "prev_decision": row["user_decision"], "prev_use_status": row["use_status"],
        "prev_reasons": list(row.get("reasons", ())),
    })


def _finish_batch(batch: dict[str, Any]) -> None:
    if not batch["changes"]:
        return
    log = _load_batch_log()
    log.append(batch)
    _save_batch_log(log)
    console.print(f"[dim]Batch {batch['id']} recorded ({len(batch['changes'])} change(s)) — "
                  f"run `candidate_manager.py undo` to revert it if needed.[/dim]")


def undo_batch(args: argparse.Namespace) -> int:
    log = _load_batch_log()
    if args.list:
        if not log:
            console.print("[yellow]No recorded batches to undo.[/yellow]")
            return 0
        table = Table(title="Recent batches", box=box.ROUNDED)
        for heading in ("Batch ID", "When", "Kind", "Class", "Items"):
            table.add_column(heading)
        for entry in reversed(log):
            table.add_row(entry["id"], entry["timestamp"], entry["kind"],
                          entry.get("item_class") or "all", str(len(entry["changes"])))
        console.print(table)
        return 0
    if not log:
        console.print("[yellow]No recorded batches to undo.[/yellow]")
        return 0
    if args.batch_id:
        matches = [entry for entry in log if entry["id"] == args.batch_id]
        if not matches:
            console.print(f"[red]No batch with id {args.batch_id}. Use --list to see recent ones.[/red]")
            return 2
        batch = matches[0]
    else:
        batch = log[-1]
    ledger = CL.load_ledger(args.ledger)
    reverted = []
    for change in batch["changes"]:
        try:
            ledger, _ = CL.update_candidate(
                ledger, change["id"], user_decision=change["prev_decision"],
                use_status=change["prev_use_status"], reasons=change["prev_reasons"],
            )
            reverted.append(change["display_name"])
        except CL.LedgerError:
            continue  # row may have been removed/edited since; skip rather than crash
    CL.save_ledger(ledger, args.ledger)
    log = [entry for entry in log if entry["id"] != batch["id"]]
    _save_batch_log(log)
    console.print(f"[green]Reverted batch {batch['id']}[/green] — {len(reverted)} item(s) back to their prior state: "
                  + ", ".join(reverted[:10]) + (", ..." if len(reverted) > 10 else ""))
    return 0


# Known nutrient-competition facts, stated confidently because they're textbook-level, not
# obscure claims — not a general interaction database. Each is (ids-that-trigger-it, message).
KNOWN_COMPETITIONS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"zinc"}),
     "Zinc alone (no copper in your stack): long-term high-dose zinc depletes copper. Worth "
     "knowing your copper level if you're taking zinc indefinitely."),
    (frozenset({"calcium_with_vitamin_d_if_intake_is_low", "iron_if_deficient"}),
     "Calcium and iron compete for absorption — take them at separate times of day, not in the same dose."),
    (frozenset({"zinc", "iron_if_deficient"}),
     "Zinc and iron also compete for absorption at high doses — separate timing helps both actually get absorbed."),
    (frozenset({"caffeine", "l_theanine"}),
     "This is a well-documented GOOD pairing, not a conflict — L-theanine offsets caffeine jitteriness in human trials."),
)


def _stack_conflicts(row: dict[str, Any]) -> str | None:
    """Catalog-level explicit conflicts, e.g. 'do not stack with tirzepatide' in the name itself."""
    match = re.search(r"do not stack with (\w+)", row["display_name"], re.IGNORECASE)
    return match.group(1).lower() if match else None


def stack_check(args: argparse.Namespace) -> int:
    """Check your actual current stack (adopt + in_use, cap-counted) for known conflicts,
    textbook nutrient-competition, and structural redundancy — not a full pharmacology engine."""
    ledger = CL.load_ledger(args.ledger)
    stack = [
        row for row in ledger["candidates"]
        if row["use_status"] == "in_use" and _counts_toward_cap(row)
    ]
    if not stack:
        console.print("[yellow]No actual use is recorded — nothing to check.[/yellow]")
        return 0
    stack_ids = {row["id"] for row in stack}
    stack_names = {row["id"]: row["display_name"] for row in stack}

    console.print(Panel.fit(
        "\n".join(f"- {row['display_name']} ({row['class']})" for row in stack),
        title=f"Current stack ({len(stack)} items)", border_style="cyan",
    ))

    findings: list[str] = []
    import supplement_audit as audit

    for row in stack:
        gate = audit.candidate_plan_gate(row, ledger["candidates"])
        if not gate["active_plan_allowed"]:
            findings.append(f"[yellow]REPORTED EXPOSURE / REVIEW:[/yellow] {row['display_name']}: "
                            + ", ".join(gate["reasons"]) + "; no automatic cessation or dose change.")

    # 1. Explicit catalog conflicts ("do not stack with X")
    for row in stack:
        conflict = _stack_conflicts(row)
        if conflict and any(conflict in other_id for other_id in stack_ids):
            findings.append(f"[red]CONFLICT:[/red] {row['display_name']} is explicitly labeled "
                             f"'do not stack with {conflict}', and something matching that is also in your stack.")

    # 2. Known nutrient-competition facts
    for trigger_ids, message in KNOWN_COMPETITIONS:
        if trigger_ids <= stack_ids:
            names = ", ".join(stack_names[i] for i in trigger_ids)
            findings.append(f"[yellow]NOTE ({names}):[/yellow] {message}")

    # 3. Structural redundancy — multiple items tagged with the same reason
    by_reason: dict[str, list[str]] = {}
    for row in stack:
        for reason in row.get("reasons", ()):
            by_reason.setdefault(reason, []).append(row["display_name"])
    for reason, names in by_reason.items():
        if len(names) >= 3:
            findings.append(f"[dim]REDUNDANCY:[/dim] {len(names)} items all tagged `{reason}`: "
                             f"{', '.join(names)} — not necessarily wrong, but check you need all of them.")

    if not findings:
        console.print("[green]No known conflicts, competitions, or redundancy found in your current stack.[/green]")
    else:
        for line in findings:
            console.print(line)
    console.print(f"\n[dim]This checks catalog-declared conflicts, a handful of well-established nutrient-"
                  f"competition facts, and structural overlap in your own tagged reasons — it is NOT a full "
                  f"drug-interaction engine. Ask coach.py directly for anything not covered here, "
                  f"e.g. python3 coach.py \"does X interact with Y\".[/dim]")
    return 0


# The grade comes from an actual vote count across your retrieved sources — not a category
# lookup. Every retained source is deduped, classified positive/negative/neutral from its own
# text (the same lexical terms the report already uses for "direction"), and weighted by its
# own evidence grade (A/B human sources count double a C-grade animal/mechanism source). The
# net of that tally — not "how many sources exist" alone — sets the grade, so one strongly
# negative human trial can outweigh five weak animal papers, and five consistent positive
# sources outweigh one middling one. Intake goals can only nudge the result by one notch, and
# a real harm signal always forces an F regardless of everything else.
_LETTER_ORDER: tuple[str, ...] = (
    "F-", "F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+",
)


def _nudge_grade(letter: str, steps: int) -> str:
    index = _LETTER_ORDER.index(letter)
    return _LETTER_ORDER[max(0, min(len(_LETTER_ORDER) - 1, index + steps))]


def _hit_sentiment(text: str, names: Sequence[str] = ()) -> str:
    """Classify a source's sentiment toward the candidate specifically — not toward whatever
    else the passage happens to discuss. If the candidate's own name/alias appears in the text,
    only scan sentences that actually mention it (catches the case where a broad review chunk
    reports harm/benefit for something else entirely, e.g. chemotherapy toxicity inside a
    melatonin-and-cancer paper). Falls back to whole-text scanning when the name isn't found
    verbatim (pronouns, "the compound", etc. still need some signal rather than none)."""
    import re as _re
    import supplement_audit as audit

    lowered_names = [n.lower() for n in names if n]
    scoped_text = text
    if lowered_names:
        sentences = _re.split(r"(?<=[.!?])\s+", text)
        matching = [s for s in sentences if any(n in s.lower() for n in lowered_names)]
        if matching:
            scoped_text = " ".join(matching)
    lowered = scoped_text.lower()
    if any(term in lowered for term in audit.DIRECTION_HARM_TERMS):
        return "harm"
    if any(term in lowered for term in audit.DIRECTION_FAVOR_TERMS):
        return "favor"
    if any(term in lowered for term in audit.DIRECTION_NULL_TERMS):
        return "null"
    return "unknown"


def _tally_sources(evidence: Any, names: Sequence[str] = ()) -> dict[str, Any]:
    """One vote per unique source: +weight if it reads positive, -weight if negative, weight is
    2 for A/B grade, 1 for C grade. Dedups by DOI/filename so one paper's chunks aren't double-counted.
    `names` (candidate name + aliases) scopes sentiment to sentences that actually mention the
    candidate, so an unrelated harm/benefit claim elsewhere in a broad review chunk isn't counted."""
    seen: set[str] = set()
    net = 0
    favor_n = harm_n = null_n = unknown_n = 0
    strong_harm = False
    for hit in evidence.hits:
        key = str(hit.get("doi") or hit.get("source_pdf") or id(hit))
        if key in seen:
            continue
        seen.add(key)
        grade = hit.get("grade", "C")
        weight = 2 if grade in ("A", "B") else 1
        sentiment = _hit_sentiment(str(hit.get("text", "")), names)
        if sentiment == "favor":
            net += weight
            favor_n += 1
        elif sentiment == "harm":
            net -= weight
            harm_n += 1
            strong_harm = strong_harm or grade in ("A", "B")
        elif sentiment == "null":
            null_n += 1
        else:
            unknown_n += 1
    return dict(net=net, sources=len(seen), favor_n=favor_n, harm_n=harm_n,
                null_n=null_n, unknown_n=unknown_n, strong_harm=strong_harm)


def _letter_from_tally(tally: dict[str, Any], coverage: str, *, is_food: bool = False) -> tuple[str, str]:
    if tally["strong_harm"]:
        return "F", (f"a grade-A/B source reads negative ({tally['harm_n']} negative source(s) total) "
                      "— a real harm signal forces this regardless of anything else")
    net, sources = tally["net"], tally["sources"]
    if sources == 0:
        return "?", "no local evidence retrieved either way — not evaluated"
    if net >= 6:
        letter = "A+"
    elif net >= 4:
        letter = "A"
    elif net >= 3:
        letter = "A-"
    elif net >= 2:
        letter = "B+"
    elif net == 1:
        letter = "B"
    elif net == 0:
        letter = "C+" if tally["favor_n"] or tally["harm_n"] else "C"
    elif net == -1:
        letter = "C-"
    elif net == -2:
        letter = "D+"
    else:
        letter = "D"
    why = (f"{tally['favor_n']} positive vs {tally['harm_n']} negative source(s) "
           f"({tally['null_n']} null, {tally['unknown_n']} non-directional) across {sources} unique source(s), "
           f"grade-weighted net {net:+d}")
    # Replication gate: this app already defines STRONG as 2+ independent A/B human sources
    # (see supplement_audit.py). A single positive study — even a real grade-B one — is not yet
    # replicated evidence; it shouldn't be able to buy an A-range grade on its own. This is the
    # exact gap that let Shilajit (1 real B-grade study, everything else "ayurvedic panacea"/
    # "elixir" review papers, coverage WEAK) hit A- on tally math alone.
    if coverage != "STRONG" and _LETTER_ORDER.index(letter) > _LETTER_ORDER.index("B+"):
        why += f"; capped at B+ — coverage is {coverage}, not STRONG (fewer than 2 independent A/B sources agree, so this isn't replicated yet)"
        letter = "B+"
    return letter, why


def _grade_candidate(
    row: dict[str, Any], evidence: Any, live_evaluation: dict[str, Any], intake: dict[str, Any],
) -> tuple[str, int, list[str]]:
    """Grade from a real source tally first; your intake goals can only nudge it, never drive it."""
    notes: list[str] = []
    names = [row["display_name"], *row.get("aliases", ())]
    tally = _tally_sources(evidence, names)
    is_food = row.get("class") == "food"
    coverage = _effective_food_coverage(row["id"], evidence.coverage) if is_food else evidence.coverage
    letter, why = _letter_from_tally(tally, coverage, is_food=is_food)
    notes.append(f"source tally: {why} -> base {letter}")

    if letter != "F":
        reasons = set(row.get("reasons", ()))
        goals = set(intake.get("goals", ()))
        if reasons & goals:
            letter = _nudge_grade(letter, +1)
            notes.append(f"nudged up one notch: matches your stated top goal(s) {', '.join(reasons & goals)}")
        elif not reasons:
            letter = _nudge_grade(letter, -1)
            notes.append("nudged down one notch: no reason recorded for wanting this")

        if row.get("blocker", {}).get("present"):
            letter = _nudge_grade(letter, -2)
            notes.append("nudged down two notches: unresolved blocker on record")

    if row.get("observed") == "harms":
        letter = "F"
        notes.append("forced to F: you've personally observed this cause harm")

    return letter, _LETTER_ORDER.index(letter), notes


def _triage_recommendation(row: dict[str, Any], evidence: Any, live_evaluation: dict[str, Any], intake: dict[str, Any]) -> str:
    import supplement_audit as audit

    grade, _rank, notes = _grade_candidate(row, evidence, live_evaluation, intake)
    gate = audit.candidate_plan_gate(row, evaluation=live_evaluation)
    verb_map = {
        "A": "strong evidence behind it — adopt if it's practical for you",
        "B": "reasonable evidence — worth considering",
        "C": "marginal or thin evidence — watch, not a clear yes",
        "D": "weak evidence — leans toward reject",
        "F": "no real evidence or a real harm signal — reject",
        "?": "not evaluated — no local evidence retrieved",
    }
    verb = verb_map.get(grade[0], "unknown grade")
    color = "green" if grade.startswith(("A", "B")) else "yellow" if grade.startswith("C") else "red" if grade.startswith(("D", "F")) else "dim"
    if not gate["active_plan_allowed"] or live_evaluation.get("system_suggestion") not in {"ADOPT_CANDIDATE", "CONTINUE_CURRENT"}:
        verb = "research grade only; no routine adoption recommendation"
        notes.extend(gate["reasons"])
    return (
        f"[bold {color}]MY GRADE: {grade}[/bold {color}] — {verb}\n"
        f"[dim]" + "; ".join(notes) + "[/dim]"
    )


def _counts_toward_cap(row: dict[str, Any]) -> bool:
    """Herbs count toward the stack cap like supplements do — you take them deliberately for a
    reason. Plain diet food (chicken, broccoli, apples) doesn't compete for a stack slot."""
    return row["class"] != "food" or row["id"] in HERB_IDS


def _incorporated_count(ledger: dict[str, Any]) -> int:
    return sum(
        1 for row in ledger["candidates"]
        if row["use_status"] == "in_use" and _counts_toward_cap(row)
    )


# The built-in catalog already tags every item with a small set of "issues" (heart, focus,
# endurance, stress, strength, joints, immune, sleep, deficiency, cut, gi, skin). That's a real,
# existing categorization — reusing it as a *suggested default* means most items only need an
# Enter to accept, instead of typing a reason from scratch. It's a suggestion, not an answer:
# nothing gets saved until you accept or override it.
ISSUE_TO_REASON: dict[str, str] = {
    "heart": "longevity_curiosity", "focus": "cognition", "endurance": "running",
    "stress": "recovery", "strength": "strength", "joints": "joint_pain",
    "immune": "other", "sleep": "sleep", "deficiency": "lab_driven",
    "cut": "fat_loss", "gi": "gi", "skin": "other",
}


def _suggested_reasons(candidate: Any | None) -> str:
    if candidate is None:
        return ""
    mapped = dict.fromkeys(ISSUE_TO_REASON[issue] for issue in candidate.issues if issue in ISSUE_TO_REASON)
    return ",".join(mapped)


def _require_reasons(
    ledger: dict[str, Any], row: dict[str, Any], ledger_path: str | Path | None, candidate: Any | None = None,
) -> list[str]:
    """Use temporary catalog search labels without inventing user-recorded reasons."""
    reasons = list(row.get("reasons", ()))
    if reasons:
        return reasons
    suggestion = _suggested_reasons(candidate)
    return reason_values(suggestion, require=True) if suggestion else ["other"]


_PLAIN_ENGLISH_SYSTEM = """You explain a supplement, food, or drug candidate to a smart adult in
completely plain, simple English — no jargon, no hedging filler. Use ONLY the CONTEXT passages
given; each is tagged [grade | folder | doi]. If the context doesn't support a claim, say the
evidence isn't there instead of guessing. Never invent a dose. Output EXACTLY this format, each
line under 20 words:
WHAT IT IS: <one plain sentence>
PROS:
- <plain sentence>
- <plain sentence>
CONS:
- <plain sentence>
- <plain sentence>"""


def _plain_english_procon(model: Any, tok: Any, candidate: Any, evidence: Any) -> str:
    if not evidence.hits:
        return "WHAT IT IS: not enough in your local library to explain this yet.\nPROS:\n- none found\nCONS:\n- none found"
    ctx = "\n\n".join(
        f"[{h['grade']} | {h['folder']} | {h.get('doi') or 'no-doi'}]\n{h['text'][:800]}"
        for h in evidence.hits[:6]
    )
    prompt = f"{_PLAIN_ENGLISH_SYSTEM}\n\nCONTEXT:\n{ctx}\n\nCandidate: {candidate.name}\n\nANSWER:"
    if hasattr(tok, "apply_chat_template") and tok.chat_template:
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": _PLAIN_ENGLISH_SYSTEM},
             {"role": "user", "content": f"CONTEXT:\n{ctx}\n\nCandidate: {candidate.name}"}],
            add_generation_prompt=True, tokenize=False,
        )
    from mlx_lm import generate
    return generate(model, tok, prompt=prompt, max_tokens=350, verbose=False).strip()


def triage_batch(args: argparse.Namespace) -> int:
    """Walk a batch of undecided candidates with live evidence + a recommendation, one at a time."""
    import lancedb
    from sentence_transformers import SentenceTransformer
    import coach as HC
    import supplement_audit as audit

    ledger = CL.load_ledger(args.ledger)
    rows = [row for row in ledger["candidates"] if row["user_decision"] == "undecided"]
    if args.item_class is not None:
        rows = [row for row in rows if row["class"] == args.item_class]
    if not rows:
        console.print("[yellow]Nothing undecided matches that filter.[/yellow]")
        return 0
    batch = rows[: args.batch]
    batch_log = _start_batch("triage", args.item_class)
    console.print(f"[bold]Triaging {len(batch)} of {len(rows)} undecided candidate(s)"
                  f"{f' in class {args.item_class}' if args.item_class else ''}.[/bold]\n")

    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    reranker = HC.load_reranker()
    gen_model = gen_tok = None
    if args.explain:
        console.print("[dim]Loading the local generator for plain-English pro/con writeups...[/dim]")
        from mlx_lm import load
        gen_model, gen_tok = load(HC.GEN_MODEL)

    for index, row in enumerate(batch, 1):
        candidate, _built_in = audit.candidate_from_ledger_row(row)
        reasons = _require_reasons(ledger, row, args.ledger, candidate)
        reason_labels = [dict(CL.REASON_OPTIONS).get(reason, reason) for reason in reasons] or ["general benefit"]
        evidence = audit.retrieve_candidate(tbl, emb, reranker, candidate, reason_labels, "")
        live_evaluation = audit.evaluate_ledger_rows(
            [row], {row["id"]: candidate}, {row["id"]: evidence}, {}, ledger["intake"],
            ledger_rows=ledger["candidates"],
        )[row["id"]]
        direction = live_evaluation.get("direction", "unknown")
        suggestion = live_evaluation["system_suggestion"]
        top_hits = "\n".join(
            f"  - [{hit.get('grade', '—')}] {os.path.basename(hit.get('source_pdf', 'unknown'))}"
            for hit in evidence.hits[:3]
        ) or "  (no relevant sources retrieved)"
        procon_block = ""
        if args.explain:
            with console.status(f"[dim]Writing plain-English pro/con for {row['display_name']}...[/dim]"):
                procon = _plain_english_procon(gen_model, gen_tok, candidate, evidence)
            procon_block = f"\n\n{procon}"
        lab_lines = _lab_context_lines(row["id"])
        lab_block = ("\n" + "\n".join(lab_lines) + "\n") if lab_lines else ""
        console.print(Panel.fit(
            f"[bold]{row['display_name']}[/bold] ({row['class']}) — item {index}/{len(batch)}\n"
            f"Coverage: {evidence.coverage} | Direction: {direction} | System suggestion: {suggestion}\n"
            f"Why: {live_evaluation['suggestion_reason']}\n"
            f"{lab_block}\n"
            f"Top sources:\n{top_hits}\n"
            f"{procon_block}\n\n"
            f"{_triage_recommendation(row, evidence, live_evaluation, ledger['intake'])}",
            border_style="cyan",
        ))
        decision = Prompt.ask(
            "Decision", choices=("skip", "watch", "adopt", "reject"), default="skip",
        )
        if decision == "skip":
            continue
        if decision == "adopt":
            if not _adoption_allowed(ledger, row, live_evaluation):
                continue
            current = _incorporated_count(ledger)
            pending = sum(1 for item in ledger["candidates"] if item["user_decision"] == "adopt"
                          and item["use_status"] != "in_use" and _counts_toward_cap(item))
            if _counts_toward_cap(row) and row["use_status"] != "in_use" and current + pending >= args.cap:
                console.print(
                    f"[yellow]At the cap of {args.cap} reported or planned items. "
                    "No decision or actual-use status changed.[/yellow]"
                )
                continue
        _record_change(batch_log, row)
        ledger, _ = CL.update_candidate(ledger, row["id"], user_decision=decision)
        CL.save_ledger(ledger, args.ledger)

    _finish_batch(batch_log)
    console.print(
        f"\n[bold]Batch done.[/bold] Cap-counted items currently incorporated: "
        f"{_incorporated_count(ledger)}/{args.cap} (plain diet food doesn't count against this cap)."
    )
    return 0


def curses_grade_select(rows: Sequence[dict[str, Any]], cap: int, already_incorporated: int) -> set[str] | None:
    """Ranked checklist, best grade first. Space toggles, Enter/x applies — a SOFT cap: going
    over it warns and asks you to confirm again rather than silently blocking, since a hard
    limit doesn't fit how people actually decide to add one more thing. Already-adopted rows
    start pre-checked. This changes intent only, never recorded actual use."""
    selected: set[str] = {row["id"] for row in rows if row["user_decision"] == "adopt"}
    # already_incorporated counts your WHOLE real stack, but rows already pre-checked above are
    # PART of that same stack — counting both double-counts them. Subtract out whatever this
    # pool already accounts for, leaving only the baseline that lives outside this screen
    # entirely (e.g. adopted items in a class you didn't include in this run).
    baseline_within_pool = sum(1 for row in rows if row["id"] in selected
                               and row["use_status"] == "in_use" and _counts_toward_cap(row))
    baseline_outside_pool = max(0, already_incorporated - baseline_within_pool)
    result: dict[str, set[str] | None] = {"value": None}

    # Number-key quick filters. "herbs"/"food" split the single food class into culinary
    # herbs/spices vs everything else, since those behave very differently (deliberate add
    # vs plain diet) even though the ledger stores them under one class.
    CLASS_FILTER_KEYS: dict[str, tuple[str, str]] = {
        "1": ("supplement", "Supplements"), "2": ("peptide", "Peptides"),
        "3": ("nootropic", "Nootropics"), "4": ("gray_market", "Gray-market"),
        "5": ("herbs", "Herbs"), "6": ("food", "Food (non-herb)"), "7": ("other", "Other"),
    }
    # Decision-zone filters: "Applied" = adopted, "Denied" = rejected, "Watching" = your waiting
    # zone, "Unzoned" = undecided, not placed in any zone yet. Combine freely with each other and
    # with the class filters (1-7) — every filter here is a plain AND against the rest.
    DECISION_FILTER_KEYS: dict[str, tuple[str, str]] = {
        "a": ("adopt", "Applied"), "d": ("reject", "Denied"),
        "w": ("watch", "Watching"), "u": ("undecided", "Unzoned"),
    }

    def matches_one_filter(row: dict[str, Any], filter_id: str) -> bool:
        if filter_id == "herbs":
            return row["class"] == "food" and row["id"] in HERB_IDS
        if filter_id == "food":
            return row["class"] == "food" and row["id"] not in HERB_IDS
        return row["class"] == filter_id

    def matches_class_filters(row: dict[str, Any], active: set[str]) -> bool:
        return not active or any(matches_one_filter(row, filter_id) for filter_id in active)

    def matches_decision_filters(row: dict[str, Any], active: set[str]) -> bool:
        return not active or row["user_decision"] in active

    # Food-type cycle filter: a single key (t/T) steps forward/back through broad, everyday
    # food groups (Meats, Fruits, Nuts & Seeds, ...) rather than diet_rules' 16 fine-grained
    # diet-exclusion categories (organ_meat vs red_meat, starchy_veg vs vegetable) — those
    # distinctions matter for diet-preset exclusion logic, not for browsing. A cycle needs no
    # typing at all, unlike a free-text prompt. Meaningless for non-food rows (no group), so it
    # only ever narrows food rows; combines with the 1-7/a-d-w-u filters like any other filter.
    FOOD_TYPE_CYCLE: tuple[str | None, ...] = (None, *DR.BROAD_GROUPS)

    def matches_food_type(row: dict[str, Any], food_type: str | None) -> bool:
        if food_type is None:
            return True
        return row["class"] == "food" and DR.FOOD_BROAD_GROUP.get(row["id"]) == food_type

    def run(stdscr) -> None:
        curses.curs_set(0)
        cursor = 0
        pending_confirm = False
        view_checked_only = False
        active_filters: set[str] = set()  # empty = no filter = show all classes
        active_decisions: set[str] = set()  # empty = no filter = show all decision zones
        food_type_index = 0  # index into FOOD_TYPE_CYCLE; 0 = None = no food-type filter
        while True:
            active_food_type = FOOD_TYPE_CYCLE[food_type_index]
            visible = [
                row for row in rows
                if matches_class_filters(row, active_filters)
                and matches_decision_filters(row, active_decisions)
                and matches_food_type(row, active_food_type)
                and (not view_checked_only or row["id"] in selected)
            ]
            cursor = max(0, min(cursor, len(visible) - 1)) if visible else 0
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            if not active_filters:
                mode_bits = ["All classes"]
            else:
                by_id = {cls: label for cls, label in CLASS_FILTER_KEYS.values()}
                # keep display order stable (matches the 1-7 key order), not set iteration order
                mode_bits = [by_id[cls] for _key, (cls, _label) in CLASS_FILTER_KEYS.items() if cls in active_filters]
            if active_decisions:
                by_decision = {dec: label for dec, label in DECISION_FILTER_KEYS.values()}
                mode_bits += [by_decision[dec] for _key, (dec, _label) in DECISION_FILTER_KEYS.items() if dec in active_decisions]
            if active_food_type:
                mode_bits.append(f"type={active_food_type}")
            if view_checked_only:
                mode_bits.append("checked only")
            stdscr.addnstr(
                0, 0, f"RANKED PICKER — showing: {' + '.join(mode_bits)}",
                max(1, width - 1), curses.A_BOLD,
            )
            stdscr.addnstr(
                1, 0, "Space toggle one · A toggle all visible · 1-7 class filter · a/d/w/u zone filter "
                "(Applied/Denied/Watching/Unzoned) · t/T cycle food type · combine freely, 0 clears · "
                "v checked-only · Enter/x apply · q cancel",
                max(1, width - 1), curses.A_DIM,
            )
            header = f"    {'Grade':<7}{'Name':<36}{'Class':<12}{'Decision':<11}{'Reasons'}"
            stdscr.addnstr(3, 0, header, max(1, width - 1), curses.A_UNDERLINE)
            if not visible:
                stdscr.addnstr(5, 0, "(nothing matches this filter — press the same key again, or 0, to clear it)",
                                max(1, width - 1), curses.A_DIM)
            page_size = max(1, height - 7)
            first = max(0, min(cursor - page_size // 2, len(visible) - page_size)) if visible else 0
            for index in range(first, min(len(visible), first + page_size)):
                row = visible[index]
                mark = "[x]" if row["id"] in selected else "[ ]"
                cap_tag = " [REVIEW ONLY]" if not row.get("_safety_gate", {}).get("active_plan_allowed", True) else ""
                if row["class"] == "food":
                    weekly_max = FSG.serving_guidance(row["id"])["weekly_max_servings"]
                    if weekly_max:
                        cap_tag = f" [max {weekly_max}/wk]"
                line = (
                    f"{mark} {row['_grade']:<7}{row['display_name'][:34]:<36}"
                    f"{row['class']:<12}{row['user_decision']:<11}"
                    f"{', '.join(row.get('reasons', ())) or 'UNSPECIFIED'}{cap_tag}"
                )
                attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                stdscr.addnstr(4 + (index - first), 0, line, max(1, width - 1), attr)
            selected_capped = sum(1 for row in rows if row["id"] in selected and _counts_toward_cap(row))
            projected = baseline_outside_pool + selected_capped
            over = projected > cap
            footer = (
                f"{len(selected)} adoption intents — projected {projected}/{cap} if started; actual use is unchanged"
                + (f"  [OVER SOFT CAP by {projected - cap} — press Enter/x again to confirm anyway]" if over else "")
            )
            stdscr.addnstr(height - 1, 0, footer, max(1, width - 1), curses.A_BOLD if over else curses.A_DIM)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                if visible:
                    cursor = (cursor - 1) % len(visible)
                pending_confirm = False
            elif key in (curses.KEY_DOWN, ord("j")):
                if visible:
                    cursor = (cursor + 1) % len(visible)
                pending_confirm = False
            elif key == ord("v"):
                view_checked_only = not view_checked_only
                cursor = 0
                pending_confirm = False
            elif key == ord("0"):
                active_filters.clear()
                active_decisions.clear()
                food_type_index = 0
                cursor = 0
                pending_confirm = False
            elif key == ord("t"):
                food_type_index = (food_type_index + 1) % len(FOOD_TYPE_CYCLE)
                cursor = 0
                pending_confirm = False
            elif key == ord("T"):
                food_type_index = (food_type_index - 1) % len(FOOD_TYPE_CYCLE)
                cursor = 0
                pending_confirm = False
            elif 0 <= key < 256 and chr(key) in CLASS_FILTER_KEYS:
                wanted = CLASS_FILTER_KEYS[chr(key)][0]
                active_filters.symmetric_difference_update({wanted})
                cursor = 0
                pending_confirm = False
            elif 0 <= key < 256 and chr(key) in DECISION_FILTER_KEYS:
                wanted = DECISION_FILTER_KEYS[chr(key)][0]
                active_decisions.symmetric_difference_update({wanted})
                cursor = 0
                pending_confirm = False
            elif key == ord(" "):
                if visible:
                    selected.symmetric_difference_update({visible[cursor]["id"]})
                pending_confirm = False
            elif key == ord("A"):
                # toggle: if not everything currently visible is checked, check it all;
                # if it's all already checked, uncheck it all. Only touches what's on screen
                # right now, so filter first, then A to bulk-select just that slice.
                visible_ids = {row["id"] for row in visible}
                if visible_ids - selected:
                    selected.update(visible_ids)
                else:
                    selected.difference_update(visible_ids)
                pending_confirm = False
            elif key in (10, 13, curses.KEY_ENTER, ord("x")):
                if over and not pending_confirm:
                    pending_confirm = True
                    continue
                result["value"] = set(selected)
                return
            elif key in (ord("q"), 27):
                result["value"] = None
                return

    curses.wrapper(run)
    return result["value"]


def _curve_food_grades(rows: list[dict[str, Any]]) -> None:
    """Foods only, mutates in place. Re-ranks each broad food group's already-graded rows
    (evidence tally + goal-match/no-reason/blocker nudges already applied by _grade_candidate)
    against each other on a curve, since absolute evidence-tally thresholds leave almost
    everything bunched at a flat C while the local library is this sparse.

    Curves over DISTINCT underlying scores, not raw row counts — if 60 fruits all sit at the
    same score (zero local evidence, no goal match), they all land in the same tier together;
    ties are never split apart just to manufacture a spread. A group with only one distinct
    score (everyone identical) is left alone entirely: there's no real signal to curve on.

    F is an absolute safety floor (forced by a real harm signal or personally-observed harm in
    _grade_candidate) and is never touched here — it's excluded from its group's curve pool so
    a harm-flagged food can't accidentally get curved up, and it never appears as a bottom-of-
    curve grade either, since "least evidence in its group" isn't the same claim as "avoid this."
    """
    CURVE_BANDS: tuple[tuple[float, str], ...] = (
        (0.15, "A"), (0.35, "B"), (0.65, "C"), (0.85, "C-"), (1.01, "D"),
    )
    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["class"] != "food" or row["_grade"] == "F":
            continue
        group = DR.FOOD_BROAD_GROUP.get(row["id"])
        if group is not None:
            by_group.setdefault(group, []).append(row)

    for group_rows in by_group.values():
        distinct_scores = sorted({r["_score"] for r in group_rows}, reverse=True)
        if len(distinct_scores) <= 1:
            continue  # everyone tied — no real signal to curve on, leave the flat grade as-is
        tier_of_score: dict[int, str] = {}
        span = len(distinct_scores) - 1
        for rank, score in enumerate(distinct_scores):
            percentile = rank / span
            tier_of_score[score] = next(letter for cutoff, letter in CURVE_BANDS if percentile <= cutoff)
        for row in group_rows:
            row["_grade_absolute"] = row["_grade"]
            row["_grade"] = tier_of_score[row["_score"]]
            row["_score"] = _LETTER_ORDER.index(row["_grade"])


def rank_and_select(args: argparse.Namespace) -> int:
    """Grade every undecided candidate (optionally filtered), rank best-first, then a real
    checkbox picker to adopt as many as you want — the 15-ish cap warns, it doesn't block."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console.print("The ranked picker needs an interactive terminal. Run this from a real shell, not a pipe.")
        return 2
    import lancedb
    from sentence_transformers import SentenceTransformer
    import coach as HC
    import supplement_audit as audit

    ledger = CL.load_ledger(args.ledger)
    rows = list(ledger["candidates"]) if args.all_decisions else [
        row for row in ledger["candidates"] if row["user_decision"] == "undecided"
    ]
    categories = [c.strip() for c in args.categories.split(",")] if args.categories else None
    if categories:
        unknown = sorted(set(categories) - set(CL.CANDIDATE_CLASSES) - {"herbs"})
        if unknown:
            console.print(f"[red]Unknown --categories value(s): {', '.join(unknown)}. "
                          f"Valid: herbs, {', '.join(CL.CANDIDATE_CLASSES)}[/red]")
            return 2
        wants_herbs = "herbs" in categories
        classes = [c for c in categories if c != "herbs"]
        rows = [
            row for row in rows
            if row["class"] in classes or (wants_herbs and row["id"] in HERB_IDS)
        ]
    else:
        if args.item_class is not None:
            rows = [row for row in rows if row["class"] == args.item_class]
        if args.herbs_only:
            rows = [row for row in rows if row["class"] != "food" or row["id"] in HERB_IDS]
    if not rows:
        console.print("[yellow]Nothing undecided matches that filter.[/yellow]")
        return 0
    pool = rows if args.limit <= 0 else rows[: args.limit]
    if len(rows) > len(pool):
        console.print(f"[dim]Grading {len(pool)} of {len(rows)} undecided candidates "
                       f"(use --limit 0 to grade all of them; this scans live evidence for each one).[/dim]")
    elif args.limit <= 0 and len(pool) > 40:
        console.print(f"[yellow]Grading all {len(pool)} undecided candidates — this scans live evidence "
                       "for every one, so it will take a while.[/yellow]")

    missing_reasons = [row for row in pool if not row.get("reasons")]
    if missing_reasons:
        console.print(f"[yellow]{len(missing_reasons)} of {len(pool)} have no reason recorded. "
                       "Temporary catalog search labels will not be saved as user reasons.[/yellow]")

    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    reranker = HC.load_reranker()

    graded: list[dict[str, Any]] = []
    with console.status("[bold]Grading against your intake goals and local evidence...[/bold]") as status:
        for i, row in enumerate(pool, 1):
            status.update(f"[bold]Grading {i}/{len(pool)}: {row['display_name']}[/bold]")
            candidate, _built_in = audit.candidate_from_ledger_row(row)
            reasons = _require_reasons(ledger, row, args.ledger, candidate)
            reason_labels = [dict(CL.REASON_OPTIONS).get(r, r) for r in reasons]
            evidence = audit.retrieve_candidate(tbl, emb, reranker, candidate, reason_labels, "")
            live_evaluation = audit.evaluate_ledger_rows(
                [row], {row["id"]: candidate}, {row["id"]: evidence}, {}, ledger["intake"],
                ledger_rows=ledger["candidates"],
            )[row["id"]]
            grade, score, _notes = _grade_candidate(row, evidence, live_evaluation, ledger["intake"])
            enriched = dict(row)
            enriched["_grade"] = grade
            enriched["_score"] = score
            enriched["_evaluation"] = live_evaluation
            enriched["_safety_gate"] = audit.candidate_plan_gate(row, ledger["candidates"], live_evaluation)
            graded.append(enriched)

    _curve_food_grades(graded)
    graded.sort(key=lambda r: r["_score"], reverse=True)
    already = _incorporated_count(ledger)
    selected = curses_grade_select(graded, args.cap, already)
    if selected is None:
        console.print("Cancelled; no changes made.")
        return 0
    rows_by_id = {row["id"]: row for row in graded}
    already_adopted = {
        row["id"] for row in graded if row["user_decision"] == "adopt"
    }
    newly_adopted = selected - already_adopted
    reverted = already_adopted - selected
    batch_log = _start_batch("rank", args.item_class or args.categories)
    applied = 0
    for row_id in newly_adopted:
        if not _adoption_allowed(ledger, rows_by_id[row_id], rows_by_id[row_id]["_evaluation"]):
            continue
        _record_change(batch_log, rows_by_id[row_id])
        ledger, _ = CL.update_candidate(ledger, row_id, user_decision="adopt")
        applied += 1
    for row_id in reverted:
        _record_change(batch_log, rows_by_id[row_id])
        ledger, _ = CL.update_candidate(ledger, row_id, user_decision="watch")
    if batch_log["changes"]:
        CL.save_ledger(ledger, args.ledger)
    _finish_batch(batch_log)
    console.print(
        f"[green]Recorded adoption intent for {applied} new item(s)"
        + (f", reverted {len(reverted)} to watch" if reverted else "") + ".[/green] "
        f"Actual use unchanged; cap-counted reported exposures: {_incorporated_count(ledger)} "
        f"(soft target was {args.cap}). Run the full ranking to reflect this in the report."
    )
    return 0


# Study-reported dosing protocols (DOSING below) are keyed by candidate id. "per_kg" scales
# low/high by bodyweight_kg; "fixed" does not. Any item NOT in DOSING — including every
# peptide/nootropic/gray_market row — still gets an evidence-review card (policy, gate, human-
# data status, documented harm, and any study dose) rather than being excluded or handed an
# invented number. Gray-market rows never get a fabricated dose; their USER_REPORTED dose field
# stays fully available.

GRAY_HARM: dict[str, str] = {
    "sarms_non_prescribed_anabolic_androgenic_drugs_class_harm_review":
        "Documented hepatotoxicity (drug-induced liver injury), testosterone/HPTA suppression, "
        "and HDL suppression; banned in tested sport; legal gray.",
    "phenibut": "GABA-B-active; documented dependence and severe withdrawal (agitation, "
        "psychosis, and seizures in some reports).",
    "melanotan": "Unapproved injectable; blood-pressure changes, skin-pigmentation/nevi changes, "
        "and injection-site reactions reported.",
    "mk_677_ibutamoren": "Growth-hormone secretagogue; appetite, edema/fluid retention, and "
        "insulin/glucose changes; human trial data is older-cohort only.",
    "methylene_blue": "MAO-inhibitory at higher doses; serotonin-toxicity risk with serotonergic "
        "medications; medical-grade use only.",
    "tesofensine": "Catecholamine stimulant; blood-pressure and heart-rate elevation; unapproved.",
}

STUDY_DOSE: dict[str, str] = {
    "mk_677_ibutamoren": "Human trials in older adults used ~25 mg/day (grade C, older cohort; "
        "NOT demonstrated for a healthy late-20s man).",
    "phenibut": "Historical prescription range in some countries ~250-500 mg up to 3x/day; "
        "gray-market numbers circulating online are not clinical evidence.",
}

NO_HUMAN_DATA = {"slu_pp_332", "aicar", "5_amino_1mq", "dihexa", "isrib"}
DOSING: dict[str, dict[str, Any]] = {
    "creatine_monohydrate": dict(mode="fixed", low=3, high=5, unit="g/day",
        timing="any time of day; consistency matters more than timing", source="ISSN creatine 2017"),
    "protein_whey": dict(mode="per_kg", low=1.6, high=2.4, unit="g/day total protein (whey is one contributor)",
        timing="spread across meals roughly every 3-4h, ~0.4 g/kg per feeding; one serving within ~2h post-training",
        source="ISSN protein 2017"),
    "caffeine": dict(mode="per_kg", low=3, high=6, unit="mg",
        timing="~60 min pre-training; cut off at least 8-9h before bed", source="ISSN caffeine 2018"),
    "beta_alanine": dict(mode="fixed", low=4, high=6, unit="g/day",
        timing="split into 2+ doses to reduce paresthesia; best for 1-4 min efforts", source="ISSN beta-alanine"),
    "sodium_bicarbonate": dict(mode="per_kg", low=0.2, high=0.3, unit="g",
        timing="60-150 min pre-event; GI-limited, test in training before competition", source="ISSN bicarbonate 2021"),
    "citrulline_citrulline_malate": dict(mode="fixed", low=6, high=8, unit="g",
        timing="~60 min pre-workout", source="ISSN 2018 ergogenic aids table"),
    "hmb": dict(mode="fixed", low=3, high=3, unit="g/day",
        timing="split doses through the day", source="ISSN HMB"),
    "magnesium": dict(mode="fixed", low=200, high=400, unit="mg/day",
        timing="citrate/glycinate better tolerated than oxide; evening if used for sleep",
        source="ODS magnesium fact sheet"),
    "vitamin_d3": dict(mode="fixed", low=1000, high=2000, unit="IU/day",
        timing="with a meal containing fat",
        source="ODS vitamin D fact sheet (maintenance; a real deficiency needs a clinician-guided repletion dose, not this range)"),
    "omega_3_epa_and_dha": dict(mode="fixed", low=1, high=2, unit="g/day EPA+DHA",
        timing="with meals", source="ODS omega-3 fact sheet"),
    "dietary_nitrate_beetroot": dict(mode="fixed", low=5, high=9, unit="mmol nitrate (~70-140 mL concentrate)",
        timing="2-3h before event; avoid antibacterial mouthwash the same day", source="ISSN nitrate; Jones/Bailey nitrate SRs"),
    "taurine": dict(mode="fixed", low=1, high=3, unit="g",
        timing="pre-workout", source="small human MAs (ISSN, mixed/limited evidence)"),
    "l_theanine": dict(mode="fixed", low=100, high=200, unit="mg",
        timing="often paired with caffeine", source="small anxiety/sleep RCTs"),
    "glycine": dict(mode="fixed", low=3, high=3, unit="g",
        timing="pre-bed", source="small sleep RCTs"),
    "nac": dict(mode="fixed", low=600, high=1800, unit="mg/day",
        timing="split doses", source="ISSN category; psychiatric/pulmonary literature"),
    "zinc": dict(mode="fixed", low=15, high=40, unit="mg/day (40 mg is the adult UL)",
        timing="away from high-calcium meals",
        source="ODS zinc fact sheet — long-term high-dose zinc can cause copper deficiency; not for indefinite use without knowing your levels"),
    "tart_cherry": dict(mode="fixed", low=480, high=600, unit="mg extract (or ~250-350 mL juice)",
        timing="in the days around hard training or racing", source="recovery SRs; ISSN antioxidants 2026"),
    "curcumin_turmeric_extract": dict(mode="fixed", low=500, high=1000, unit="mg curcumin",
        timing="with a fat-containing meal; needs an absorption-enhanced formulation (e.g. piperine) to matter",
        source="OA pain MAs"),
    "ashwagandha_ksm_66_or_sensoril": dict(mode="fixed", low=300, high=600, unit="mg/day extract",
        timing="evening if used for stress/sleep",
        source="stress/sleep SRs — rare liver-injury case reports exist"),
    "rhodiola_rosea": dict(mode="fixed", low=200, high=400, unit="mg/day standardized extract",
        timing="morning, on an empty stomach if tolerated", source="small fatigue SRs"),
}


def compute_dose(item_id: str, bodyweight_kg: float | None) -> dict[str, Any] | None:
    spec = DOSING.get(item_id)
    if spec is None:
        return None
    if spec["mode"] == "per_kg":
        if bodyweight_kg is None:
            return {"needs_weight": True, **spec}
        low = round(spec["low"] * bodyweight_kg, 1)
        high = round(spec["high"] * bodyweight_kg, 1)
        amount = f"{low}-{high} {spec['unit']} (scaled from {spec['low']}-{spec['high']} {spec['unit']}/kg at {bodyweight_kg:g} kg)"
    else:
        amount = f"{spec['low']}-{spec['high']} {spec['unit']}" if spec["low"] != spec["high"] else f"{spec['low']} {spec['unit']}"
    return {"amount": amount, "timing": spec["timing"], "source": spec["source"], "needs_weight": False}


def _human_data_line(item_id: str) -> str:
    if item_id in NO_HUMAN_DATA:
        return "None — preclinical/research only. Nothing exists to scale to your weight."
    return "No citable human dosing protocol in this library — nothing is scaled; this system never invents a number."


def _lab_context_lines(item_id: str) -> list[str]:
    try:
        import labs as LABS
    except ImportError:
        return []
    lines = []
    for key, entry in LABS.labs_for_candidate(item_id):
        spec = LABS.MARKERS[key]
        status = LABS.marker_status(key, entry["value"])
        color = {"LOW": "yellow", "HIGH": "red", "NORMAL": "green"}.get(status, "white")
        lines.append(
            f"Your {spec['name']}: {entry['value']} {entry.get('unit', spec['unit'])} "
            f"([{color}]{status}[/{color}], recorded {entry.get('date', 'unknown')})"
        )
    return lines


def _print_computed_dose(row: dict[str, Any], result: dict[str, Any]) -> None:
    lab_lines = _lab_context_lines(row["id"])
    lab_block = ("\n".join(lab_lines) + "\n\n") if lab_lines else ""
    console.print(Panel.fit(
        f"Amount: {result['amount']}\n"
        f"Timing: {result['timing']}\n"
        f"Source: {result['source']}\n\n"
        f"{lab_block}"
        "[dim]This is the study-reported protocol, scaled to your weight where applicable — "
        "not a personal prescription. Adjust for your own tolerance and check for medication "
        "interactions.[/dim]",
        title=f"Study dose reference — {row['display_name']}",
        border_style="green",
    ))


def _print_evidence_review(row: dict[str, Any], candidate: Any) -> None:
    policy = candidate.policy or "none"
    gate = candidate.gate or "none"
    harm = GRAY_HARM.get(row["id"])
    study = STUDY_DOSE.get(row["id"])
    lines = [
        f"Class: {row['class']}",
        f"Catalog policy: {policy}",
        f"Gate: {gate}",
        f"Human dosing data: {_human_data_line(row['id'])}",
    ]
    if harm:
        lines.append(f"Documented harm: {harm}")
    if study:
        lines.append(f"Study dose (grade C / NOT a personal protocol): {study}")
    lines.append(f"Your recorded dose: {row.get('user_dose') or 'unset'}")
    lines.extend(_lab_context_lines(row["id"]))
    flag = bool(harm) or any(token in policy.upper() for token in (
        "NO PERSONAL PROTOCOL", "HARM", "DEPENDENCE", "PRECLINICAL", "RESEARCH DRUG",
    ))
    console.print(Panel.fit(
        "\n".join(lines),
        title=f"Evidence review — {row['display_name']} (no computed dose)",
        border_style="yellow" if flag else "dim",
    ))


def _dose_one(ledger: dict[str, Any], row: dict[str, Any], bodyweight_kg: float | None) -> None:
    import supplement_audit as audit

    candidate, _built_in = audit.candidate_from_ledger_row(row)
    gate = audit.candidate_plan_gate(row, ledger["candidates"])
    if not gate["active_plan_allowed"]:
        console.print("Research/reference only; no personal dose calculation: " + ", ".join(gate["reasons"]))
        _print_evidence_review(row, candidate)
        return
    result = compute_dose(row["id"], bodyweight_kg)
    if result is not None:
        if result.get("needs_weight"):
            console.print(
                f"[yellow]{row['display_name']} scales by bodyweight — pass --weight-kg.[/yellow]"
            )
            return
        _print_computed_dose(row, result)
        return
    _print_evidence_review(row, candidate)


def dose_candidate(args: argparse.Namespace) -> int:
    ledger = CL.load_ledger(args.ledger)
    if args.weight_kg is not None and args.save_weight:
        ledger["intake"]["bodyweight_kg"] = args.weight_kg
        CL.save_ledger(ledger, args.ledger)
    bodyweight_kg = args.weight_kg if args.weight_kg is not None else ledger["intake"].get("bodyweight_kg")

    if not args.all and args.item_class is None and not args.item_id:
        console.print("Pick one candidate, or use --all / --class to review a group.")
        return 2
    if args.all or args.item_class is not None:
        rows = list(ledger["candidates"])
        if args.item_class is not None:
            rows = [row for row in rows if row["class"] == args.item_class]
        if not rows:
            console.print("[yellow]No matching candidates in the ledger.[/yellow]")
            return 0
        for row in rows:
            _dose_one(ledger, row, bodyweight_kg)
        return 0

    row = find_ledger_row(ledger, args.item_id)
    _dose_one(ledger, row, bodyweight_kg)
    return 0


def _saved_profile() -> dict[str, Any]:
    try:
        import supplement_audit as audit

        return audit.load_saved_profile(audit.DEFAULT_OUT) or {}
    except (ImportError, OSError, ValueError):
        return {}


def _ordered_goals(raw: str) -> list[str]:
    goals = csv_values(raw)
    unknown = sorted(set(goals) - set(CL.OUTCOME_REASON_KEYS))
    if unknown:
        raise CL.LedgerError("Unknown outcome goal key(s): " + ", ".join(unknown))
    if not 1 <= len(goals) <= 3:
        raise CL.LedgerError("Choose one to three ordered outcome goal keys")
    return goals


def prompt_candidate_followups(
    ledger: dict[str, Any],
    item_ids: Sequence[str],
    *,
    limit: int,
) -> dict[str, Any]:
    """Screen F: optional candidate-specific context; no answer is inferred from silence."""
    ordered = list(dict.fromkeys(item_ids))[:limit]
    if not ordered or not Confirm.ask(
        f"Screen F — review up to {len(ordered)} candidate-specific matches now?",
        default=False,
    ):
        return ledger
    for item_id in ordered:
        row = CL.rows_by_id(ledger).get(item_id)
        if row is None:
            continue
        console.rule(f"F · {row['display_name']}")
        if not Confirm.ask("Review this row?", default=True):
            continue
        scope = Prompt.ask(
            "Personally consider, research only, or undecided",
            choices=CL.CONSIDERATION_SCOPES,
            default=row["consideration_scope"],
        )
        console.print("Outcome reason keys: " + ", ".join(CL.OUTCOME_REASON_KEYS))
        raw_reasons = Prompt.ask(
            "Candidate-specific outcome reasons, ordered and comma-separated",
            default=",".join(row.get("reasons", ())),
        )
        reasons = reason_values(raw_reasons)
        outcome_lines = dict(row.get("outcome_lines", {}))
        for reason in reasons:
            if reason in FOLLOWUP_DETAIL_REASONS:
                existing = outcome_lines.get(reason, "")
                line = Prompt.ask(
                    f"What exact outcome would matter for {reason}? (blank keeps unknown)",
                    default=existing,
                ).strip()
                if line:
                    outcome_lines[reason] = line
                else:
                    outcome_lines.pop(reason, None)
        use_status = Prompt.ask("Use status", choices=CL.USE_STATUSES, default=row["use_status"])
        user_dose = row.get("user_dose")
        if use_status == "in_use":
            user_dose = Prompt.ask(
                "Confirm your own dose/schedule (blank leaves dose unset)",
                default=user_dose or "",
            ).strip() or None
        intent = Prompt.ask("Add/keep or replace intent", choices=CL.INTENTS, default=row["intent"])
        burden = Prompt.ask("Practical burden", choices=CL.BURDEN_VALUES, default=row["burden"])
        blocker_present = Confirm.ask(
            "Is there something specific stopping you from using this (cost, access, side effect, interaction)?",
            default=bool(row.get("blocker", {}).get("present")),
        )
        blocker_description = None
        if blocker_present:
            blocker_description = Prompt.ask(
                "Describe the blocker",
                default=row.get("blocker", {}).get("description") or "",
            ).strip() or None
            if blocker_description is None:
                console.print("[yellow]No description entered; recording no blocker instead.[/yellow]")
                blocker_present = False
        decision = Prompt.ask("Your decision", choices=CL.USER_DECISIONS, default=row["user_decision"])
        if decision == "adopt" and row["user_decision"] != "adopt" and not _adoption_allowed(ledger, {
            **row, "consideration_scope": scope, "use_status": use_status,
            "blocker": {"present": blocker_present},
        }):
            decision = row["user_decision"]
        ledger, _updated = CL.update_candidate(
            ledger,
            row["id"],
            consideration_scope=scope,
            reasons=reasons,
            outcome_lines=outcome_lines,
            use_status=use_status,
            user_dose=user_dose,
            intent=intent,
            burden=burden,
            blocker={
                "present": blocker_present,
                "description": blocker_description,
                "provenance": "USER_REPORTED",
            },
            user_decision=decision,
        )
    return ledger


def intake_candidate_identity(name: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    matched = find_catalog(name)
    if matched:
        candidate, item_class = matched
        return {
            "item_id": candidate.key,
            "display_name": candidate.name,
            "item_class": item_class,
            "aliases": candidate.aliases,
            "folder": candidate.folders[0] if candidate.folders else None,
        }
    default_class = existing.get("class", "other") if existing else "other"
    item_class = Prompt.ask(
        f"Class for typed current item '{name}'",
        choices=CL.CANDIDATE_CLASSES,
        default=default_class,
    )
    return {
        "item_id": existing["id"] if existing else CL.candidate_id(name),
        "display_name": name,
        "item_class": item_class,
        "aliases": existing.get("aliases", ()) if existing else (),
        "folder": existing.get("folder") if existing else None,
    }


def ranking_intake(path: str | Path | None = None) -> int:
    """Run intake screens A–F and persist only to the ignored private ledger."""
    ledger = CL.load_ledger(path)
    intake = CL.normalize_intake(ledger.get("intake"))
    saved_profile = _saved_profile()

    console.rule("A · BASELINE CONFIRMATION")
    console.print("Each displayed fact must be confirmed, updated, removed, or withheld. Old report text is not treated as current truth.")
    baseline: dict[str, dict[str, Any]] = {}
    previous_baseline = intake.get("baseline", {})
    for key, label in BASELINE_FACTS:
        previous = previous_baseline.get(key, {})
        value = previous.get("value") or saved_profile.get(key)
        if isinstance(value, (list, dict)):
            value = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        value = str(value or "").strip()
        if not value and not previous:
            continue
        console.print(f"[bold]{label}:[/bold] {value or 'not recorded'}")
        status = Prompt.ask(
            "Status",
            choices=CL.BASELINE_STATUSES,
            default=previous.get("status", "still_true"),
        )
        if status == "update":
            value = Prompt.ask("Updated value", default=value).strip() or None
        elif status in {"remove", "prefer_not"}:
            value = None
        baseline[key] = {"status": status, "value": value}
    intake["baseline"] = baseline

    console.rule("B · ORDERED GOALS")
    console.print("Choose one to three ordered outcome keys: " + ", ".join(CL.OUTCOME_REASON_KEYS))
    while True:
        try:
            intake["goals"] = _ordered_goals(Prompt.ask(
                "Goals, highest priority first",
                default=",".join(intake.get("goals", ())),
            ))
            break
        except CL.LedgerError as exc:
            console.print(f"[red]{exc}[/red]")
    intake["weight_direction"] = Prompt.ask(
        "Weight direction",
        choices=CL.WEIGHT_DIRECTIONS,
        default=intake.get("weight_direction", "unknown"),
    )

    console.rule("B2 · BIOMETRICS (for real TDEE / calorie math — tdee.py, weekly_food_plan.py)")
    console.print("Blank keeps the current value unset. Nothing here is guessed — the weekly food "
                   "plan and TDEE estimate simply won't compute until these are filled in.")

    def _float_prompt(label: str, current: float | None, low: float, high: float) -> float | None:
        while True:
            raw = Prompt.ask(label, default="" if current is None else str(current)).strip()
            if not raw:
                return None
            try:
                value = float(raw)
            except ValueError:
                console.print("[red]Enter a number, or leave blank.[/red]")
                continue
            if not low <= value <= high:
                console.print(f"[red]Must be between {low} and {high}.[/red]")
                continue
            return value

    intake["bodyweight_kg"] = _float_prompt("Bodyweight (kg — e.g. 82; 230 lb ≈ 104 kg)", intake.get("bodyweight_kg"), 25, 400)
    intake["height_cm"] = _float_prompt("Height (cm — e.g. 178; 5'10\" ≈ 178 cm)", intake.get("height_cm"), 100, 250)
    intake["age_years"] = _float_prompt("Age (years)", intake.get("age_years"), 13, 100)
    intake["sex"] = Prompt.ask(
        "Sex (for the Mifflin-St Jeor BMR formula, which uses a different constant for male/female)",
        choices=CL.SEX_VALUES, default=intake.get("sex", "unknown"),
    )
    intake["neat_activity_level"] = Prompt.ask(
        "Daily activity level OUTSIDE of structured training (ordinary daily-living movement — "
        "structured workouts are added separately from your real logged weekly check-ins)",
        choices=CL.NEAT_ACTIVITY_LEVELS, default=intake.get("neat_activity_level", "sedentary"),
    )

    console.rule("C · REQUIRED CONTEXT FLAGS")
    for key, label in (
        ("sleep_problem", "Current sleep problem"),
        ("training_limit_pain", "Pain currently limits training"),
        ("tested_sport", "Participates in tested sport"),
        ("gi_consider", "GI tolerance should affect ranking"),
    ):
        intake["flags"][key] = Prompt.ask(
            label, choices=CL.TRISTATE_VALUES, default=intake["flags"].get(key, "unknown")
        )

    console.rule("D · CURRENT ITEMS")
    existing_current = [row for row in ledger["candidates"] if row["use_status"] == "in_use"]
    saved_current_keys = set(saved_profile.get("current_supplement_keys", ()))
    saved_current_names = [
        candidate.name for candidate, _item_class in catalog_rows()
        if candidate.key in saved_current_keys
    ]
    current_defaults = [row["display_name"] for row in existing_current] or saved_current_names
    raw_current = Prompt.ask(
        "Current item names, comma-separated; blank means an empty list",
        default=",".join(current_defaults),
    ).strip()
    current_names = [] if raw_current.lower() in {"", "none"} else csv_values(raw_current)
    current_ids: set[str] = set()
    existing_lookup = {
        name.casefold(): row
        for row in ledger["candidates"]
        for name in (row["id"], row["display_name"], *row.get("aliases", ()))
    }
    for name in current_names:
        existing = existing_lookup.get(name.casefold())
        identity = intake_candidate_identity(name, existing)
        current_ids.add(identity["item_id"])
        dose = Prompt.ask(
            f"Your dose/schedule for {identity['display_name']} (blank leaves unset)",
            default=existing.get("user_dose") if existing and existing.get("user_dose") else "",
        ).strip() or None
        observed = Prompt.ask(
            f"Observed result for {identity['display_name']}",
            choices=CL.OBSERVED_VALUES,
            default=existing.get("observed", "unknown") if existing else "unknown",
        )
        intent = Prompt.ask(
            f"Intent for {identity['display_name']}",
            choices=CL.INTENTS,
            default=existing.get("intent", "keep") if existing else "keep",
        )
        ledger, _row, _created = CL.upsert_candidate(
            ledger,
            **identity,
            consideration_scope="personal_candidate",
            use_status="in_use",
            intent=intent,
            observed=observed,
            burden=existing.get("burden", "unknown") if existing else "unknown",
            blocker=existing.get("blocker", {}) if existing else {},
            reasons=existing.get("reasons", ()) if existing else (),
            outcome_lines=existing.get("outcome_lines", {}) if existing else {},
            user_dose=dose,
            notes=existing.get("notes") if existing else None,
        )
    for row in list(ledger["candidates"]):
        if row["use_status"] == "in_use" and row["id"] not in current_ids:
            ledger, _row = CL.update_candidate(ledger, row["id"], use_status="not_in_use")
    intake["prefer_not_meds"] = Confirm.ask(
        "Prefer not to answer medication questions? This will remain unknown, never 'no medications'",
        default=bool(intake.get("prefer_not_meds", False)),
    )

    console.rule("E · OPTIONAL SORT PREFERENCES")
    preferences = intake["preferences"]
    preferences["evidence_appetite"] = Prompt.ask(
        "Evidence appetite", choices=CL.EVIDENCE_APPETITES, default=preferences["evidence_appetite"]
    )
    preferences["food_first"] = Prompt.ask(
        "Food-first preference", choices=CL.FOOD_FIRST_VALUES, default=preferences["food_first"]
    )
    preferences["max_new_adopts"] = Prompt.ask(
        "Maximum new adoptions to consider", choices=CL.MAX_NEW_ADOPTS_VALUES,
        default=preferences["max_new_adopts"],
    )
    preferences["budget"] = Prompt.ask(
        "Budget", choices=CL.BUDGET_VALUES, default=preferences["budget"]
    )
    preferences["sourcing_bar"] = Prompt.ask(
        "Optional sourcing requirement", default=preferences.get("sourcing_bar") or ""
    ).strip() or None
    preferences["legal_sensitivity"] = Prompt.ask(
        "Optional legal/regulatory sensitivity", default=preferences.get("legal_sensitivity") or ""
    ).strip() or None
    while True:
        raw_top_n = Prompt.ask(
            "Maximum candidate-specific follow-ups", default=str(intake.get("followup_top_n", 10))
        )
        try:
            top_n = int(raw_top_n)
        except ValueError:
            console.print("[red]Enter a whole number from 1 to 50.[/red]")
            continue
        if 1 <= top_n <= 50:
            intake["followup_top_n"] = top_n
            break
        console.print("[red]Enter a whole number from 1 to 50.[/red]")
    ledger = CL.update_intake(ledger, intake)
    ledger = prompt_candidate_followups(
        ledger,
        [row["id"] for row in ledger["candidates"]],
        limit=ledger["intake"]["followup_top_n"],
    )
    CL.save_ledger(ledger, path)
    console.print(Panel.fit(
        "Deep intake saved to the ignored private ledger. Run the full ranking audit to scan the complete configured catalog.",
        border_style="green",
    ))
    return 0


def interactive_add(*, catalog: bool, ledger_path: str | None) -> None:
    if catalog:
        query = Prompt.ask("Catalog name or ID").strip()
        matched = find_catalog(query)
        if matched is None:
            console.print("[red]No unique catalog match. Use a more exact name or choose typed add.[/red]")
            return
        candidate, item_class = matched
        console.print(f"Selected: [bold]{candidate.name}[/bold] ({candidate.key})")
        name = None
        catalog_value = candidate.key
    else:
        name = Prompt.ask("Candidate name").strip()
        catalog_value = None
        item_class = Prompt.ask("Class", choices=CL.CANDIDATE_CLASSES, default="other")
    console.print("Reasons: " + ", ".join(key for key, _ in CL.REASON_OPTIONS))
    reasons = Prompt.ask("Candidate-specific reason keys, comma-separated", default="").strip()
    use_status = Prompt.ask("Use status", choices=CL.USE_STATUSES, default="not_in_use")
    consideration_scope = Prompt.ask(
        "Consideration scope", choices=CL.CONSIDERATION_SCOPES, default="undecided"
    )
    intent = Prompt.ask("Intent", choices=CL.INTENTS, default="undecided")
    observed = Prompt.ask("Observed", choices=CL.OBSERVED_VALUES, default="unknown")
    burden = Prompt.ask("Burden", choices=CL.BURDEN_VALUES, default="unknown")
    blocker = Prompt.ask("Unresolved user-reported blocker (blank means none)", default="").strip()
    aliases = Prompt.ask("Aliases, comma-separated", default="").strip()
    user_dose = Prompt.ask("User-supplied dose (blank leaves unset)", default="").strip()
    notes = Prompt.ask("Notes (optional)", default="").strip()
    args = argparse.Namespace(
        ledger=ledger_path,
        catalog=catalog_value,
        name=name,
        item_id=None,
        item_class=item_class,
        reasons=reasons,
        use_status=use_status,
        consideration_scope=consideration_scope,
        intent=intent,
        observed=observed,
        burden=burden,
        blocker=blocker or None,
        aliases=aliases,
        folder=None,
        user_dose=user_dose or None,
        notes=notes or None,
    )
    add_candidate(args)


def interactive_manage(ledger_path: str | None) -> int:
    while True:
        print_matrix(ledger_path)
        action = Prompt.ask(
            "Action",
            choices=("deep_intake", "add_catalog", "add_typed", "decide", "inspect", "review", "quit"),
            default="quit",
        )
        if action == "quit":
            return 0
        if action == "deep_intake":
            ranking_intake(ledger_path)
        elif action == "add_catalog":
            interactive_add(catalog=True, ledger_path=ledger_path)
        elif action == "add_typed":
            interactive_add(catalog=False, ledger_path=ledger_path)
        elif action == "decide":
            item_id = Prompt.ask("Candidate ID").strip()
            decision = Prompt.ask("Decision", choices=CL.USER_DECISIONS, default="undecided")
            decide_candidate(argparse.Namespace(ledger=ledger_path, item_id=item_id, decision=decision))
        elif action == "inspect":
            item_id = Prompt.ask("Candidate ID").strip()
            inspect_candidate(argparse.Namespace(ledger=ledger_path, item_id=item_id, cached_only=False))
        elif action == "review":
            class_filter = Prompt.ask(
                "Filter by class (blank for all)", choices=(*CL.CANDIDATE_CLASSES, ""), default="", show_choices=False
            ).strip() or None
            undecided_only = Confirm.ask("Only show undecided rows?", default=True)
            review_batch(argparse.Namespace(
                ledger=ledger_path, item_class=class_filter, undecided_only=undecided_only,
            ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deep ranking intake and manage the private HealthCoach candidate ledger")
    parser.add_argument("--ledger", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command")

    matrix = sub.add_parser("matrix", help="show the current candidate matrix")
    matrix.add_argument("--decision", choices=CL.USER_DECISIONS, help="only show rows with this decision")
    matrix.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES, help="only show this class")
    sub.add_parser("intake", help="run the deeper private ranking intake")

    add = sub.add_parser("add", help="add a catalog or typed candidate")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--catalog", help="existing catalog ID/name/alias")
    source.add_argument("--name", help="open typed candidate name")
    add.add_argument("--id", dest="item_id", help="stable ID for a typed candidate")
    add.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)
    add.add_argument("--status", dest="use_status", choices=CL.USE_STATUSES, default="not_in_use")
    add.add_argument("--scope", dest="consideration_scope", choices=CL.CONSIDERATION_SCOPES, default="undecided")
    add.add_argument("--intent", choices=CL.INTENTS, default="undecided")
    add.add_argument("--observed", choices=CL.OBSERVED_VALUES, default="unknown")
    add.add_argument("--burden", choices=CL.BURDEN_VALUES, default="unknown")
    add.add_argument("--blocker", help="unresolved USER_REPORTED blocker description")
    add.add_argument("--reasons", help="comma-separated stable reason keys")
    add.add_argument("--aliases", help="comma-separated aliases")
    add.add_argument("--folder", help="optional corpus folder")
    add.add_argument("--user-dose", help="user-supplied dose; never inferred")
    add.add_argument("--notes")

    decide = sub.add_parser("decide", help="record an explicit user decision")
    decide.add_argument("item_id", metavar="name_or_id")
    decide.add_argument("decision", choices=CL.USER_DECISIONS)

    edit = sub.add_parser("edit", help="edit a ledger row")
    edit.add_argument("item_id", metavar="name_or_id")
    edit.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)
    edit.add_argument("--status", dest="use_status", choices=CL.USE_STATUSES)
    edit.add_argument("--scope", dest="consideration_scope", choices=CL.CONSIDERATION_SCOPES)
    edit.add_argument("--intent", choices=CL.INTENTS)
    edit.add_argument("--observed", choices=CL.OBSERVED_VALUES)
    edit.add_argument("--burden", choices=CL.BURDEN_VALUES)
    edit.add_argument("--blocker", help="description; pass an empty value to clear")
    edit.add_argument("--reasons")
    edit.add_argument("--aliases")
    edit.add_argument("--folder")
    edit.add_argument("--user-dose")
    edit.add_argument("--notes")

    inspect = sub.add_parser("inspect", help="inspect one candidate without regenerating the report")
    inspect.add_argument("item_id", metavar="name_or_id")
    inspect.add_argument("--cached-only", action="store_true", help="skip live LanceDB/model retrieval")

    review = sub.add_parser("review", help="curses checklist: space to select, enter to adopt selected rows")
    review.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)
    review.add_argument(
        "--all", dest="undecided_only", action="store_false", default=True,
        help="include rows that already have a decision (default: undecided only)",
    )

    dose = sub.add_parser("dose", help="study-based dose/timing for any item; evidence review where no study protocol exists")
    dose.add_argument("item_id", metavar="name_or_id", nargs="?", help="one item; omit with --all or --class")
    dose.add_argument("--all", action="store_true", help="review every candidate in the ledger")
    dose.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES, help="review every candidate of this class")
    dose.add_argument("--weight-kg", type=float, help="your bodyweight, for compounds dosed per kg")
    dose.add_argument("--save-weight", action="store_true", help="remember --weight-kg for future `dose` calls")

    status = sub.add_parser("status", help="group user decisions and reported actual use (not medical approval)")
    status.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)

    triage = sub.add_parser("triage", help="walk undecided candidates one at a time with live evidence + a recommendation")
    triage.add_argument("--batch", type=int, default=15, help="how many undecided items to review this run (default 15)")
    triage.add_argument("--cap", type=int, default=15, help="max items allowed adopt+in_use at once (default 15)")
    triage.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)
    triage.add_argument("--explain", action="store_true",
        help="also write a plain-English pro/con for each item (loads the local generator; slower)")

    rank = sub.add_parser("rank", help="grade+rank undecided candidates, then a checkbox picker to adopt several at once")
    rank.add_argument("--limit", type=int, default=40, help="how many undecided items to grade this run (default 40; 0 = grade all of them)")
    rank.add_argument("--cap", type=int, default=15, help="soft target for cap-counted items incorporated (default 15; warns, doesn't block)")
    rank.add_argument("--class", dest="item_class", choices=CL.CANDIDATE_CLASSES)
    rank.add_argument("--herbs-only", action="store_true", help="with --class food, only include culinary herbs/spices, not the whole food catalog")
    rank.add_argument("--categories", help="comma-separated combined pool, e.g. 'herbs,supplement,gray_market' — overrides --class/--herbs-only")
    rank.add_argument("--all-decisions", action="store_true",
        help="include already-decided items too, not just undecided — see everything graded, with already-adopted rows pre-checked")

    undo = sub.add_parser("undo", help="revert the last rank/triage batch (or a specific one with --batch-id)")
    undo.add_argument("--list", action="store_true", help="show recent batches instead of undoing")
    undo.add_argument("--batch-id", help="undo this specific batch id instead of the most recent one")

    sub.add_parser("stack-check", help="check your current adopted stack for known conflicts, nutrient competition, and redundancy")
    sub.add_parser("sync-foods", help="add every built-in whole-food catalog item not already in the ledger, as undecided (safe to re-run)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command is None:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                console.print("Use one of: intake, matrix, add, edit, decide, inspect, review")
                return 2
            return interactive_manage(args.ledger)
        if args.command == "matrix":
            return print_matrix(args.ledger, decision=args.decision, item_class=args.item_class)
        if args.command == "intake":
            return ranking_intake(args.ledger)
        if args.command == "add":
            return add_candidate(args)
        if args.command == "edit":
            return edit_candidate(args)
        if args.command == "decide":
            return decide_candidate(args)
        if args.command == "inspect":
            return inspect_candidate(args)
        if args.command == "review":
            return review_batch(args)
        if args.command == "dose":
            return dose_candidate(args)
        if args.command == "status":
            return print_status(args.ledger, item_class=args.item_class)
        if args.command == "triage":
            return triage_batch(args)
        if args.command == "rank":
            return rank_and_select(args)
        if args.command == "undo":
            return undo_batch(args)
        if args.command == "stack-check":
            return stack_check(args)
        if args.command == "sync-foods":
            return sync_food_catalog(args)
    except CL.LedgerError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
