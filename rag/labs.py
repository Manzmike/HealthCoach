#!/usr/bin/env python3
"""Private lab-value store: manual entry, listing, and assisted PDF import.

Storage: rag/.healthcoach/labs.json (gitignored, private — same directory as the candidate
ledger). Every value has a reference range so it can be flagged LOW/NORMAL/HIGH automatically.

PDF import NEVER auto-saves a parsed number. Lab report formats vary too much between
providers (Quest, LabCorp, Function Health, hospital portals, ...) to trust a regex blindly on
real medical data. Every candidate match found in the PDF is shown to you with its surrounding
text for confirmation, or you can edit or skip it, before anything is written.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 labs.py add ferritin 45 --unit ng/mL
  python3 labs.py list
  python3 labs.py import-pdf ~/Downloads/quest_results.pdf
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

HERE = Path(__file__).resolve().parent
LABS_PATH = HERE / ".healthcoach" / "labs.json"
console = Console()

# key -> (display name, unit, low, high, aliases for PDF text matching, candidate ids this
# marker is relevant to — used to surface lab context on `inspect`/`dose` for those items).
MARKERS: dict[str, dict[str, Any]] = {
    "ferritin": dict(name="Ferritin", unit="ng/mL", low=30, high=300,
        aliases=("ferritin",), candidates=("iron_if_deficient",)),
    "vitamin_d_25oh": dict(name="Vitamin D, 25-OH", unit="ng/mL", low=30, high=100,
        aliases=("vitamin d, 25-oh", "25-hydroxyvitamin d", "25-oh vitamin d", "vitamin d3"),
        candidates=("vitamin_d3",)),
    "vitamin_b12": dict(name="Vitamin B12", unit="pg/mL", low=232, high=1245,
        aliases=("vitamin b12", "cobalamin"), candidates=("vitamin_b12_if_deficient",)),
    "folate": dict(name="Folate", unit="ng/mL", low=3.4, high=40,
        aliases=("folate", "folic acid"), candidates=("folate_methylfolate_if_deficient",)),
    "tsh": dict(name="TSH", unit="mIU/L", low=0.4, high=4.5,
        aliases=("tsh", "thyroid stimulating hormone"), candidates=()),
    "free_t4": dict(name="Free T4", unit="ng/dL", low=0.8, high=1.8,
        aliases=("free t4", "ft4"), candidates=()),
    "testosterone_total": dict(name="Testosterone, Total", unit="ng/dL", low=264, high=916,
        aliases=("testosterone, total", "total testosterone"), candidates=()),
    "testosterone_free": dict(name="Testosterone, Free", unit="pg/mL", low=8.7, high=25.1,
        aliases=("free testosterone", "testosterone, free"), candidates=()),
    "shbg": dict(name="SHBG", unit="nmol/L", low=10, high=57,
        aliases=("shbg", "sex hormone binding globulin"), candidates=()),
    "lh": dict(name="LH", unit="mIU/mL", low=1.7, high=8.6,
        aliases=("luteinizing hormone", " lh "), candidates=("enclomiphene", "kisspeptin", "gonadorelin")),
    "fsh": dict(name="FSH", unit="mIU/mL", low=1.5, high=12.4,
        aliases=("follicle stimulating hormone", " fsh "), candidates=("enclomiphene", "kisspeptin", "gonadorelin")),
    "alt": dict(name="ALT", unit="U/L", low=7, high=56,
        aliases=("alt", "alanine aminotransferase"),
        candidates=("sarms_non_prescribed_anabolic_androgenic_drugs_class_harm_review", "ostarine_mk_2866")),
    "ast": dict(name="AST", unit="U/L", low=10, high=40,
        aliases=("ast", "aspartate aminotransferase"),
        candidates=("sarms_non_prescribed_anabolic_androgenic_drugs_class_harm_review", "ostarine_mk_2866")),
    "creatinine": dict(name="Creatinine", unit="mg/dL", low=0.7, high=1.3,
        aliases=("creatinine",), candidates=("creatine_monohydrate",)),
    "egfr": dict(name="eGFR", unit="mL/min/1.73m2", low=90, high=200,
        aliases=("egfr",), candidates=("creatine_monohydrate",)),
    "hba1c": dict(name="HbA1c", unit="%", low=4.0, high=5.6,
        aliases=("hba1c", "hemoglobin a1c"), candidates=("mk_677_ibutamoren", "aicar")),
    "fasting_glucose": dict(name="Fasting Glucose", unit="mg/dL", low=70, high=99,
        aliases=("fasting glucose", "glucose, fasting"), candidates=("mk_677_ibutamoren", "aicar")),
    "ldl": dict(name="LDL Cholesterol", unit="mg/dL", low=0, high=99,
        aliases=("ldl cholesterol", "ldl-c", " ldl "), candidates=()),
    "hdl": dict(name="HDL Cholesterol", unit="mg/dL", low=40, high=200,
        aliases=("hdl cholesterol", "hdl-c", " hdl "),
        candidates=("sarms_non_prescribed_anabolic_androgenic_drugs_class_harm_review", "ostarine_mk_2866")),
    "triglycerides": dict(name="Triglycerides", unit="mg/dL", low=0, high=149,
        aliases=("triglycerides",), candidates=()),
    "apob": dict(name="ApoB", unit="mg/dL", low=0, high=90,
        aliases=("apob", "apolipoprotein b"), candidates=()),
    "zinc": dict(name="Zinc (serum)", unit="mcg/dL", low=60, high=120,
        aliases=(" zinc ",), candidates=("zinc",)),
    "copper": dict(name="Copper (serum)", unit="mcg/dL", low=70, high=140,
        aliases=(" copper ",), candidates=("zinc",)),
    "magnesium_rbc": dict(name="Magnesium, RBC", unit="mg/dL", low=4.2, high=6.8,
        aliases=("magnesium, rbc", "rbc magnesium"), candidates=("magnesium",)),
    "hscrp": dict(name="hs-CRP", unit="mg/L", low=0, high=1.0,
        aliases=("hs-crp", "high sensitivity crp", "hscrp"), candidates=()),
    "homocysteine": dict(name="Homocysteine", unit="umol/L", low=0, high=15,
        aliases=("homocysteine",), candidates=("folate_methylfolate_if_deficient", "vitamin_b12_if_deficient")),
}


def load_labs() -> dict[str, Any]:
    if not LABS_PATH.exists():
        return {"entries": {}}
    try:
        return json.loads(LABS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"entries": {}}


def save_labs(data: dict[str, Any]) -> None:
    LABS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABS_PATH.write_text(json.dumps(data, indent=2))


def marker_status(key: str, value: float) -> str:
    spec = MARKERS.get(key)
    if spec is None:
        return "UNKNOWN RANGE"
    if value < spec["low"]:
        return "LOW"
    if value > spec["high"]:
        return "HIGH"
    return "NORMAL"


def resolve_marker(name_or_key: str) -> str:
    wanted = name_or_key.strip().lower()
    if wanted in MARKERS:
        return wanted
    exact = [
        key for key, spec in MARKERS.items()
        if wanted == spec["name"].lower() or wanted in (a.strip().lower() for a in spec["aliases"])
    ]
    if len(exact) == 1:
        return exact[0]
    contains = [
        key for key, spec in MARKERS.items()
        if wanted in spec["name"].lower() or any(wanted in a.strip().lower() for a in spec["aliases"])
    ]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        raise SystemExit(
            f"Ambiguous marker '{name_or_key}'; matches: {', '.join(sorted(contains))}. Use the exact key."
        )
    raise SystemExit(
        f"Unknown marker '{name_or_key}'. Known markers: {', '.join(sorted(MARKERS))}"
    )


def add_lab(args: argparse.Namespace) -> int:
    key = resolve_marker(args.marker)
    spec = MARKERS[key]
    unit = args.unit or spec["unit"]
    if unit != spec["unit"]:
        if not getattr(args, "confirm_unit", False):
            console.print(f"[red]Unit mismatch: expected {spec['unit']}, got {unit}. Re-run with --confirm-unit to override.[/red]")
            return 1
    date = args.date or dt.date.today().isoformat()
    data = load_labs()
    data["entries"][key] = {"value": args.value, "unit": unit, "date": date, "source": "manual"}
    save_labs(data)
    status = marker_status(key, args.value)
    color = {"LOW": "yellow", "HIGH": "red", "NORMAL": "green"}.get(status, "white")
    console.print(f"Saved {spec['name']} = {args.value} {unit} on {date} — [{color}]{status}[/{color}] "
                  f"(reference {spec['low']}-{spec['high']} {spec['unit']})")
    return 0


def list_labs(_args: argparse.Namespace) -> int:
    data = load_labs()
    entries = data.get("entries", {})
    table = Table(title="Private lab values", box=box.ROUNDED)
    for heading in ("Marker", "Value", "Reference range", "Status", "Date", "Source"):
        table.add_column(heading)
    if not entries:
        table.add_row("No labs recorded", "—", "—", "—", "—", "—")
    for key, spec in MARKERS.items():
        entry = entries.get(key)
        if entry is None:
            continue
        status = marker_status(key, entry["value"])
        style = {"LOW": "yellow", "HIGH": "red", "NORMAL": "green"}.get(status, "white")
        table.add_row(
            spec["name"], f"{entry['value']} {entry.get('unit', spec['unit'])}",
            f"{spec['low']}-{spec['high']} {spec['unit']}", f"[{style}]{status}[/{style}]",
            entry.get("date", "unknown"), entry.get("source", "manual"),
        )
    console.print(table)
    console.print(f"[dim]{LABS_PATH}[/dim]")
    return 0


_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _alias_pattern(alias: str) -> re.Pattern:
    core = alias.strip().lower()
    # \b fails on a leading/trailing space in the alias itself, so strip it and let \b do the
    # boundary check instead — this is what broke short aliases like " copper " at line-start.
    return re.compile(r"\b" + re.escape(core) + r"\b")


def _find_candidates_in_text(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    found: list[dict[str, Any]] = []
    for key, spec in MARKERS.items():
        for alias in spec["aliases"]:
            for match in _alias_pattern(alias).finditer(lowered):
                window = text[match.end(): match.end() + 60]
                number_match = _NUMBER_RE.search(window)
                if not number_match:
                    continue
                snippet_start = max(0, match.start() - 20)
                snippet = text[snippet_start: match.end() + 60].replace("\n", " ").strip()
                found.append({
                    "key": key, "value": float(number_match.group(1)), "snippet": snippet,
                })
                break  # one hit per alias is enough; avoid duplicate noise from repeated headers
    return found


def import_pdf(args: argparse.Namespace) -> int:
    from pypdf import PdfReader

    path = Path(args.pdf_path).expanduser()
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        return 2
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        console.print("[yellow]No extractable text in this PDF — it may be a scanned image. "
                       "Use `labs.py add` to enter values manually instead.[/yellow]")
        return 0

    candidates = _find_candidates_in_text(text)
    if not candidates:
        console.print("[yellow]No recognized marker names found in this PDF. "
                       "Known markers: " + ", ".join(sorted(MARKERS)) + "[/yellow]")
        return 0

    console.print(Panel.fit(
        f"Found {len(candidates)} possible value(s) in {path.name}. "
        "Nothing is saved automatically — confirm, edit, or skip each one.",
        border_style="cyan",
    ))
    data = load_labs()
    saved = 0
    for match in candidates:
        spec = MARKERS[match["key"]]
        console.print(Panel.fit(
            f"[dim]...{match['snippet']}...[/dim]\n\n"
            f"Parsed: [bold]{spec['name']} = {match['value']} {spec['unit']}[/bold] "
            f"(reference {spec['low']}-{spec['high']} {spec['unit']})",
            title=spec["name"], border_style="yellow",
        ))
        action = Prompt.ask("Save this value?", choices=("yes", "edit", "skip"), default="skip")
        if action == "skip":
            continue
        value = match["value"]
        if action == "edit":
            raw = Prompt.ask("Correct value", default=str(match["value"]))
            try:
                value = float(raw)
            except ValueError:
                console.print("[red]Not a number; skipping this one.[/red]")
                continue
        date = Prompt.ask("Date of this lab (YYYY-MM-DD)", default=dt.date.today().isoformat())
        data["entries"][match["key"]] = {
            "value": value, "unit": spec["unit"], "date": date, "source": f"pdf:{path.name}",
        }
        saved += 1
    save_labs(data)
    console.print(f"[green]Saved {saved} of {len(candidates)} parsed value(s).[/green]")
    return 0


def labs_for_candidate(item_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Return (marker_key, entry) pairs whose reference table lists this candidate id."""
    data = load_labs()
    entries = data.get("entries", {})
    return [
        (key, entries[key]) for key, spec in MARKERS.items()
        if item_id in spec["candidates"] and key in entries
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage private lab values: manual entry or assisted PDF import")
    sub = parser.add_subparsers(dest="command")

    add = sub.add_parser("add", help="record one lab value")
    add.add_argument("marker", help="marker name or key, e.g. ferritin, 'vitamin d', tsh")
    add.add_argument("value", type=float)
    add.add_argument("--unit", help="override the default unit")
    add.add_argument("--confirm-unit", action="store_true", help="allow unit override without matching the default")
    add.add_argument("--date", help="YYYY-MM-DD; defaults to today")

    sub.add_parser("list", help="show all recorded lab values with status flags")

    imp = sub.add_parser("import-pdf", help="scan a lab-report PDF; confirm each value before saving")
    imp.add_argument("pdf_path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "add":
        return add_lab(args)
    if args.command == "list":
        return list_labs(args)
    if args.command == "import-pdf":
        return import_pdf(args)
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
