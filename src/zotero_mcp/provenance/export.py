"""Exports: CSV and JSON of the full log, and a static PRISMA 2020-style SVG."""

from __future__ import annotations

import csv
import io
import json
from html import escape

from zotero_mcp.provenance.store import ProvenanceStore

_CSV_COLS = ("event_id", "record_id", "authors", "year", "title", "zotero_key", "doi", "needs_check",
             "retroactive", "strand", "stage", "decision", "reason", "evidence", "actor", "client",
             "reader", "what_read", "route", "source_ref", "note", "confirmation", "supersedes", "created_at")


def to_csv(store: ProvenanceStore) -> str:
    recs = {r["id"]: r for r in store.records()}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_COLS, extrasaction="ignore")
    w.writeheader()
    for e in store.events():
        r = recs[e["record_id"]]
        row = {**{k: r[k] for k in ("authors", "year", "title", "zotero_key", "doi", "needs_check", "retroactive")},
               **e, "event_id": e["id"]}
        w.writerow(row)
    return buf.getvalue()


def to_json(store: ProvenanceStore) -> str:
    return json.dumps({"records": store.records(), "events": store.events(), "codes": store.codes()},
                      indent=1, ensure_ascii=False)


def _box(x, y, w, h, lines, cls="b"):
    parts = [f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="4"/>']
    ty = y + 20
    for i, line in enumerate(lines):
        weight = ' font-weight="600"' if i == 0 else ""
        parts.append(f'<text x="{x + 10}" y="{ty}"{weight}>{escape(line)}</text>')
        ty += 17
    return "".join(parts)


def _arrow(x1, y1, x2, y2):
    return f'<line class="a" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#h)"/>'


def _reason_lines(reasons: dict, limit=3):
    items = sorted(reasons.items(), key=lambda kv: -kv[1])[:limit]
    return [f"  {k}: {v}" for k, v in items]


def to_svg(c: dict, title: str) -> str:
    W, BW, XW, LX = 1000, 300, 250, 720
    mx, ex = 40, 380
    rows = []
    y = 70
    rows.append(_box(mx, y, 200, 62, ["Database search", f"n = {c['identified_db']}"]))
    rows.append(_box(mx + 210, y, 200, 62, ["Citation diving", f"n = {c['identified_citation']}"]))
    rows.append(_box(mx + 420, y, 200, 62, ["Other methods", f"n = {c['identified_other']}"]))
    y2 = 170
    for x in (mx + 100, mx + 310, mx + 520):
        rows.append(_arrow(x, y + 62, mx + BW / 2, y2))
    stages = [
        (["Records identified", f"n = {c['identified']}"], ["Duplicates removed", f"n = {c['duplicates']}"], {}),
        (["Records screened (title, abstract)", f"n = {c['screened']}"],
         ["Excluded at screening", f"n = {c['screened_out']}"], c["screened_out_reasons"]),
        (["Full text sought", f"n = {c['sought']}"], ["Not retrieved", f"n = {c['not_retrieved']}"],
         c["not_retrieved_reasons"]),
        (["Full text read", f"n = {c['retrieved']}"], ["Excluded after reading", f"n = {c['read_out']}"],
         c["read_out_reasons"]),
        (["Coded", f"n = {c['coded']}"], ["Coded, not cited", f"n = {c['coded_not_cited']}"], {}),
        (["Incorporated", f"n = {c['incorporated']}"], None, {}),
    ]
    yy = y2
    for main, cut, reasons in stages:
        h = 62
        rows.append(_box(mx, yy, BW, h, main))
        if cut:
            lines = cut + _reason_lines(reasons)
            ch = max(h, 22 + 17 * len(lines))
            rows.append(_box(ex, yy, XW + 60, ch, lines, "b" if cut[0].startswith("Coded") else "x"))
            rows.append(_arrow(mx + BW, yy + h / 2, ex, yy + h / 2))
        if main[0] != "Incorporated":
            rows.append(_arrow(mx + BW / 2, yy + h, mx + BW / 2, yy + 100))
        yy += 100
    # Before-logging lane.
    rows.append(f'<text x="{LX}" y="160" class="lane">Before logging (from drafts)</text>')
    rows.append(_box(LX, 170, XW, 62, ["Sources in drafts or audit logs", f"n = {c['prior_total']}"], "p"))
    rows.append(_arrow(LX + XW / 2, 232, LX + XW / 2, 470))
    rows.append(_box(LX, 470, XW, 62, ["Full text read in source audits", f"n = {c['prior_read']}"], "p"))
    rows.append(_arrow(LX + XW / 2, 532, LX + XW / 2, 670))
    rows.append(_box(LX, 670, XW, 62, ["Cited in drafts", f"n = {c['prior_incorporated']}"], "p"))
    total = c["incorporated"] + c["prior_incorporated"]
    fy = yy + 10
    rows.append(_box(mx, fy, W - 2 * mx, 44, [f"Total sources cited: {total}  ({c['incorporated']} logged, "
                                               f"{c['prior_incorporated']} before logging)"], "t"))
    strands = ", ".join(f"{k} {v}" for k, v in sorted(c.get("strands", {}).items()))
    H = fy + 44 + 40
    style = (
        "text{font:13px 'Helvetica Neue',Arial,sans-serif;fill:#18212c}"
        ".b{fill:#fff;stroke:#0e6670;stroke-width:1.2}.x{fill:#f6e4e7;stroke:#9a3b4b}"
        ".p{fill:#fbefd6;stroke:#8a5a00;stroke-dasharray:4 3}.t{fill:#dceef0;stroke:#0e6670}"
        ".a{stroke:#5b6878;stroke-width:1.2}.lane{font-weight:600;fill:#8a5a00}"
        ".h1{font-size:18px;font-weight:600}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f'<defs><marker id="h" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        f'<path d="M0,0 L8,4 L0,8 z" fill="#5b6878"/></marker><style>{style}</style></defs>'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<text x="{mx}" y="34" class="h1">{escape(title)}: source provenance (PRISMA 2020, extended)</text>'
        f'<text x="{mx}" y="54">{escape("Incorporated by strand: " + strands) if strands else ""}</text>'
        + "".join(rows) + "</svg>"
    )
