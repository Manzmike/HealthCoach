"""Pure text->HTML helpers for the web GUI. No Flask, no templates -- these
convert the plain-text answers coach.py already produces into real markup
instead of terminal ANSI codes (see coach._for_terminal, which this
supersedes for the web case only; coach.py itself is unchanged)."""

from __future__ import annotations

import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def markdown_lite_to_html(text: str) -> str:
    """Converts the small subset of markdown coach.py's rendered answers
    actually use -- **bold** and blank-line paragraph breaks -- into HTML.
    Escapes the raw text FIRST, so a paper title or quote pulled from a PDF
    can never inject markup; the bold regex then runs safely against the
    escaped text, since none of `**` are HTML-special characters."""
    if not text.strip():
        return ""
    escaped = html.escape(text)
    bolded = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    paragraphs = [p.strip() for p in bolded.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def _inline(text: str) -> str:
    return _BOLD_RE.sub(r"<strong>\1</strong>", html.escape(text))


def lines_to_html(text: str) -> str:
    """Converts the specific markdown subset symptom_checkin.py's
    render_short()/render_deep()/cluster_alerts() emit -- '#'/'##'/'###'
    headers, '- ' bullets with one level of '  - ' nesting, blank-line
    paragraph breaks, and **bold** -- into real HTML. Not a general
    markdown parser; matches exactly what those functions produce, the same
    way markdown_lite_to_html() matches coach.py's narrower output shape."""
    if not text.strip():
        return ""
    out: list[str] = []
    open_levels: list[int] = []  # indent of each currently-open <ul>, outermost first

    def close_lists_deeper_than(level: int) -> None:
        while open_levels and open_levels[-1] > level:
            out.append("</ul>")
            open_levels.pop()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_lists_deeper_than(-1)
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("### "):
            close_lists_deeper_than(-1)
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            close_lists_deeper_than(-1)
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            close_lists_deeper_than(-1)
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            close_lists_deeper_than(indent)
            if not open_levels or open_levels[-1] < indent:
                out.append("<ul>")
                open_levels.append(indent)
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        else:
            close_lists_deeper_than(-1)
            out.append(f"<p>{_inline(stripped)}</p>")
    close_lists_deeper_than(-1)
    return "\n".join(out)


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")


def pipe_table_to_html(text: str) -> str:
    """coach.py's generic_schedule_table()/real_schedule_block() emit plain
    `| a | b |` markdown tables (terminal-readable as-is). Converts one such
    table, if present, into a real <table>; any text before/after the table
    passes through markdown_lite_to_html() unchanged. Returns "" for empty
    input, same contract as markdown_lite_to_html()."""
    if not text.strip():
        return ""
    lines = text.splitlines()
    table_start = next((i for i, ln in enumerate(lines) if _TABLE_ROW_RE.match(ln.strip())), None)
    if table_start is None:
        return markdown_lite_to_html(text)
    before = "\n".join(lines[:table_start]).strip()
    table_lines = [ln.strip() for ln in lines[table_start:] if _TABLE_ROW_RE.match(ln.strip())]
    # drop a markdown separator row like |---|---|
    rows = [
        [html.escape(cell.strip()) for cell in _TABLE_ROW_RE.match(ln).group(1).split("|")]
        for ln in table_lines if not re.match(r"^\|[\s:|-]+\|$", ln)
    ]
    if not rows:
        return markdown_lite_to_html(text)
    header, *body = rows
    head_html = "<tr>" + "".join(f"<th>{cell}</th>" for cell in header) + "</tr>"
    body_html = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in body)
    table_html = f"<table>{head_html}{body_html}</table>"
    prefix = markdown_lite_to_html(before) if before else ""
    return prefix + table_html
