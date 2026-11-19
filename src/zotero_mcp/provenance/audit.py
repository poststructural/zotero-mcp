"""Tolerant parser for the hand-written source audit logs (log_*.md).

Each numbered heading is one entry. The parser pulls what the entry states
(citations, Zotero item and PDF keys, status, evidence level) and keeps the
entry text verbatim. Entries with no citation and no Zotero key are reported
as unparsed rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from zotero_mcp.provenance.citations import Citation, extract_citations

_HEAD_RE = re.compile(r"^#{2,3}\s+((?:[A-Z]?\d+)\..*)$", re.M)
_ITEM_KEY_RE = re.compile(r"\b(?:Zotero|key)\s+([A-Z0-9]{8})\b")
_PDF_KEY_RE = re.compile(r"\bPDF(?:\s+(?:attachment|child))?\s+([A-Z0-9]{8})\b")
_STATUS_RE = re.compile(r"Status:\s*(.+)")
_SOURCE_LINE_RE = re.compile(r"^\s*\d+\.\s*Sources?\b[^:]*:(.*)$", re.M)
_METADATA_ONLY = re.compile(r"metadata only|no PDF|no attachment|not readable", re.I)
# "American Oversight (2025)": corporate authors the citation pattern can't see.
_CORP_RE = re.compile(r"\(\w\)\s+((?:[A-Z][\w’'\-]+\s+){1,4})\((\d{4})\)")


@dataclass
class AuditEntry:
    heading: str
    citations: list[Citation]
    zotero_keys: list[str]
    pdf_keys: list[str]
    status: str
    evidence: str
    text: str = field(repr=False)


def _uniq(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def _entry_citations(heading: str, body: str) -> list[Citation]:
    source_lines = " ".join(m.group(1) for m in _SOURCE_LINE_RE.finditer(body))
    cites: list[Citation] = []
    for m in _CORP_RE.finditer(source_lines):
        name = m.group(1).strip()
        if " " in name:  # multi-word corporate author
            cites.append(Citation(name, name, m.group(2), m.group(0), False, m.group(0)))
    seen = {(c.authors, c.year) for c in cites}
    for c in extract_citations(heading) + extract_citations(source_lines):
        if (c.authors, c.year) in seen:
            continue
        # Drop a bare surname already covered by a fuller author string.
        if any(c.year == s[1] and c.authors != s[0] and s[0].endswith(c.authors) for s in seen):
            continue
        seen.add((c.authors, c.year))
        cites.append(c)
    return cites


def parse_audit_log(text: str) -> tuple[list[AuditEntry], list[str]]:
    heads = list(_HEAD_RE.finditer(text))
    entries: list[AuditEntry] = []
    unparsed: list[str] = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end():end]
        heading = h.group(1).strip()
        pdf_keys = _uniq(_PDF_KEY_RE.findall(body))
        item_keys = [k for k in _uniq(_ITEM_KEY_RE.findall(body)) if k not in pdf_keys]
        cites = _entry_citations(heading, body)
        if not cites and not item_keys and entries:
            # Follow-up entries name the source without a year
            # ("4. Darragh & Boyd: recruitment"): inherit the earlier entry's.
            title = re.sub(r"^[A-Z]?\d+\.\s*", "", heading)
            for prev in reversed(entries):
                if prev.citations and any(title.startswith(c.authors) for c in prev.citations):
                    cites = [c for c in prev.citations if title.startswith(c.authors)]
                    item_keys = item_keys or (prev.zotero_keys if len(prev.citations) == 1 else [])
                    pdf_keys = pdf_keys or prev.pdf_keys
                    break
        if not cites and not item_keys:
            unparsed.append(heading)
            continue
        sm = _STATUS_RE.search(body)
        status = re.sub(r"\*\*", "", sm.group(1)).strip() if sm else ""
        if _METADATA_ONLY.search(body) and not pdf_keys:
            evidence = "metadata"
        elif _METADATA_ONLY.search(status):
            evidence = "metadata"
        elif re.search(r"\bderived\b", body):
            evidence = "page_derived"
        elif pdf_keys:
            evidence = "full_text"
        else:
            evidence = "metadata"
        entries.append(AuditEntry(heading, cites, item_keys, pdf_keys, status, evidence, body.strip()))
    return entries, unparsed
