#!/usr/bin/env python3
"""
COMBINE everything into one master report, with EVERY answer ordered by topic:
  Part 1  newest PLAYBOOK   (logs/playbooks/playbook_*.md)
  Part 2  newest TIERS      (logs/tiers/coach_log_*.md)
  Part 3  newest SUPPLEMENT AUDIT (logs/supplement_audits/supplement_audit_*.md)
  Part 4  ALL Q&A answers   (logs/qa/answers/*.md), de-duplicated (newest wins), placed
          under topic SECTIONS in canonical order. Answers whose wording still matches a
          question file are ordered exactly; older-worded answers are slotted into their
          best-fit section by word overlap (never dumped unordered).

  cd ~/GitHub/HealthCoach/rag && python3 combine_report.py
  -> logs/MASTER_REPORT_YYYYMMDD_HHMM.md
"""
import os, re, glob, datetime, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _slug(t):
    s = re.sub(r"[^a-z0-9 \-]", "", t.lower()).strip().replace(" ", "-")
    return re.sub(r"-+", "-", s)
LOGS = os.path.join(HERE, "logs")
# union of every question source, richest/newest first — defines sections + order
ORDER_FILES = ["interactions.txt", "new_questions_r15.txt", "questions.txt", "themes.txt"]
STOP = set("the a an and or of to for with in on at is are be how does do i my me what "
           "which when should can it its into vs versus at by from as if that this these my "
           "you your me best most more than about over under while within".split())

def newest(pattern):
    fs = glob.glob(pattern)
    return max(fs, key=os.path.getmtime) if fs else None

def norm(q):
    return re.sub(r"\s+", " ", q.lower()).strip().rstrip("?").strip()

def toks(q):
    return {w for w in re.findall(r"[a-z0-9\-]+", q.lower()) if len(w) > 3 and w not in STOP}

def parse_qa(text):
    out = []
    for p in re.split(r"\n##\s*Q\d+\s*—\s*", text)[1:]:
        head, _, rest = p.partition("\n")
        q = head.strip()
        body = re.sub(r"\n---\s*$", "", rest.strip())
        if q:
            out.append((q, body))
    return out

def build_order():
    """Return (sections_in_order, section_of_qkey, qkeys_in_order_per_section)."""
    sections, seen_sec = [], set()
    sec_qkeys = {}          # section -> [qkey,...] in order
    qkey_sec = {}           # qkey -> section (first seen)
    cur = "General"
    for fname in ORDER_FILES:
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            continue
        for raw in open(path, encoding="utf-8", errors="ignore"):
            s = raw.strip()
            if not s:
                continue
            m = re.match(r"^#\s*=+\s*(.+?)\s*=+\s*$", s)
            if m:
                cur = m.group(1)
                if cur not in seen_sec:
                    seen_sec.add(cur); sections.append(cur); sec_qkeys.setdefault(cur, [])
                continue
            if s.startswith("#"):
                continue
            if cur not in seen_sec:
                seen_sec.add(cur); sections.append(cur); sec_qkeys.setdefault(cur, [])
            k = norm(s)
            if k not in qkey_sec:
                qkey_sec[k] = cur; sec_qkeys[cur].append(k)
    return sections, qkey_sec, sec_qkeys

def main():
    # 1) always organize logs first, so the report reads from a tidy tree
    try:
        import organize_logs
        organize_logs.main()
    except Exception as e:
        print("(organize step skipped: %s)" % e)

    pb  = newest(os.path.join(LOGS, "playbooks", "playbook_*.md"))
    tir = newest(os.path.join(LOGS, "tiers", "coach_log_*.md"))
    sup = newest(os.path.join(LOGS, "supplement_audits", "supplement_audit_*.md"))

    ans = {}   # norm(q) -> (question, body)   newest file wins
    qa_files = sorted(glob.glob(os.path.join(LOGS, "qa", "answers", "*.md")), key=os.path.getmtime)
    for f in qa_files:
        for q, body in parse_qa(open(f, encoding="utf-8", errors="ignore").read()):
            ans[norm(q)] = (q, body)

    sections, qkey_sec, sec_qkeys = build_order()

    # section token profiles, for classifying older-worded (leftover) answers
    sec_tokens = {s: set().union(*[toks(k) for k in sec_qkeys[s]]) if sec_qkeys[s] else set()
                  for s in sections}
    matched = set(k for k in ans if k in qkey_sec)
    extras = {s: [] for s in sections}
    uncategorized = []
    for k in ans:
        if k in qkey_sec:
            continue
        kt = toks(k)
        best, best_score = None, 0
        for s in sections:
            score = len(kt & sec_tokens[s])
            if score > best_score:
                best, best_score = s, score
        if best and best_score >= 2:
            extras[best].append(k)
        else:
            uncategorized.append(k)

    # emit Part 3: numbered sections + clickable TOC + anchors
    ordered_secs = [s for s in sections if [k for k in sec_qkeys[s] if k in ans] or extras[s]]
    n = 0; parts = []; toc = []; used_slugs = set()
    def anchor(title):
        base = _slug(title) or "section"; a = base; i = 2
        while a in used_slugs:
            a = "%s-%d" % (base, i); i += 1
        used_slugs.add(a); return a
    for idx, s in enumerate(ordered_secs, 1):
        rows = [k for k in sec_qkeys[s] if k in ans] + sorted(extras[s])
        a = anchor(s)
        toc.append("%d. [%s](#%s) — %d" % (idx, s, a, len(rows)))
        parts.append('\n\n<a id="%s"></a>\n\n### %d. %s  <sub>(%d)</sub>\n' % (a, idx, s, len(rows)))
        for k in rows:
            q, b = ans[k]; n += 1
            parts.append("\n#### Q%d — %s\n\n%s\n\n[↑ contents](#qa-contents)\n" % (n, q, b))
    if uncategorized:
        a = anchor("Uncategorized")
        toc.append("%d. [Uncategorized](#%s) — %d" % (len(ordered_secs) + 1, a, len(uncategorized)))
        parts.append('\n\n<a id="%s"></a>\n\n### Uncategorized  <sub>(%d)</sub>\n' % (a, len(uncategorized)))
        for k in sorted(uncategorized):
            q, b = ans[k]; n += 1
            parts.append("\n#### Q%d — %s\n\n%s\n" % (n, q, b))
    sec_used = len(ordered_secs)
    toc_md = '<a id="qa-contents"></a>\n\n**Q&A sections** (jump to any):\n\n' + "\n".join(toc) + "\n"

    ts = datetime.datetime.now()
    out = os.path.join(LOGS, "MASTER_REPORT_" + ts.strftime("%Y%m%d_%H%M") + ".md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# HealthCoach — MASTER REPORT\n\n")
        f.write("_Generated %s — playbook + A/B/C/D tiers + supplement audit + all %d Q&A answers, ordered by topic._\n\n"
                % (ts.strftime("%Y-%m-%d %H:%M"), n))
        f.write("## Contents\n\n1. Playbook  2. A/B/C/D tiers  3. Supplement evidence audit  4. Q&A (every answer, ordered by topic)\n\n---\n\n")
        f.write("# 1. Playbook\n\n" + (open(pb, encoding="utf-8", errors="ignore").read()
                if pb else "_(no playbook — run build_playbook.py)_") + "\n\n---\n\n")
        f.write("# 2. A/B/C/D tiers\n\n" + (open(tir, encoding="utf-8", errors="ignore").read()
                if tir else "_(no tier log — run batch_ask.py personalized_tiers.txt)_") + "\n\n---\n\n")
        f.write("# 3. Supplement evidence audit\n\n" + (open(sup, encoding="utf-8", errors="ignore").read()
                if sup else "_(no supplement audit — run ./hc-supplements)_") + "\n\n---\n\n")
        f.write("# 4. Q&A — every answer, ordered by topic (%d answers, %d sections)\n\n" % (n, sec_used))
        f.write(toc_md + "\n---\n")
        f.write("".join(parts) + "\n")

    print("wrote", out)
    print("  playbook:", os.path.basename(pb) if pb else "MISSING",
          "| tiers:", os.path.basename(tir) if tir else "MISSING",
          "| supplement audit:", os.path.basename(sup) if sup else "MISSING")
    print("  Q&A: %d answers, %d sections | matched-in-order %d, slotted-by-topic %d, uncategorized %d"
          % (n, sec_used, len(matched), sum(len(v) for v in extras.values()), len(uncategorized)))

if __name__ == "__main__":
    main()
