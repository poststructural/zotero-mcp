"""Deterministic extraction of author-year citations from draft prose.

Only what is written in the text is returned; nothing is looked up or filled
in. Matching to Zotero happens elsewhere.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_NAME = r"[A-Z][A-Za-zÀ-ſ’'\-]+"
_SEP = r"(?:,\s*&\s*|,\s*and\s+|\s*&\s*|\s+and\s+|,\s*)"
_AUTHORS = rf"{_NAME}(?:{_SEP}{_NAME})*(?:\s+et\s+al\.)?"
_YEAR = r"1[6-9]\d\d[a-z]?|20\d\d[a-z]?"
_YEARS = rf"(?:{_YEAR})(?:\s*[,/]\s*(?:{_YEAR}))*"
_LOC = r"(?:,\s*(?:pp?\.|para\.|chap\.|ch\.)\s*[^;)]*)"
_CASE = rf"{_NAME}(?:\s+{_NAME})*\s+v\.\s+{_NAME}(?:\s+{_NAME})*"

_CASE_RE = re.compile(rf"(?P<authors>{_CASE})\s*\((?P<years>{_YEARS})(?P<loc>{_LOC})?\)")
_NARR_RE = re.compile(
    rf"(?P<authors>{_AUTHORS})(?:’s|'s|’|')?\s*\((?P<years>{_YEARS})(?P<loc>{_LOC})?\)"
)
_PAREN_RE = re.compile(r"\(([^()]*\d{4}[^()]*)\)")
_PART_RE = re.compile(
    rf"^\s*(?:(?:see|cf\.|e\.g\.,?|i\.e\.,?|also|quoted in|as cited in)\s+)*"
    rf"(?P<authors>{_AUTHORS}|{_CASE}),\s*(?P<years>{_YEARS})(?P<loc>{_LOC})?\s*$"
)
#: Words that end an author list when they appear in it: corporate or venue
#: words caught by the name pattern ("Stanford University and Bennett").
_CORPORATE = {
    "University", "College", "Review", "Literature", "Area", "Commission", "Education",
    "Department", "Press", "Journal", "Council", "Association", "Center", "Centre",
    "Institute", "Board", "Foundation", "Society", "Project", "Report", "English",
}
_STOP = {"In", "The", "A", "An", "As", "See", "For", "And", "But", "While", "Although", "Since", "By", "On", "At"}


@dataclass(frozen=True)
class Citation:
    first_author: str
    authors: str
    year: str
    raw: str
    quoted: bool
    context: str = ""


def _norm_authors(raw: str) -> tuple[str, str]:
    raw = re.sub(r"\s+", " ", raw.strip())
    if " v. " in raw:
        words = raw.split(" ")
        while words and words[0] in _STOP:
            words = words[1:]
        raw = " ".join(words)
        return raw, raw
    et_al = bool(re.search(r"\bet al\.$", raw))
    core = re.sub(r"\s*et al\.$", "", raw)
    seps = re.findall(_SEP, core)
    names = [re.sub(r"(?:’s|'s|’|')$", "", n) for n in re.split(_SEP, core) if n]
    while names and names[0] in _STOP:
        names = names[1:]
        seps = seps[1:]
    # A plain comma list with no '&'/'and' before its last name is a list of
    # separate works ("Anderson, Applebee (1989)"), not co-authors.
    if len(names) > 1 and seps and not re.search(r"&|\band\b", seps[-1]):
        names = names[-1:]
    # Corporate/venue words end the list: keep the names after the last one.
    corp = [i for i, n in enumerate(names) if n in _CORPORATE]
    if corp and corp[-1] < len(names) - 1:
        names = names[corp[-1] + 1:]
    if not names:
        return "", ""
    if et_al:
        authors = f"{names[0]} et al."
    elif len(names) == 1:
        authors = names[0]
    elif len(names) == 2:
        authors = f"{names[0]} & {names[1]}"
    else:
        authors = ", ".join(names[:-1]) + f", & {names[-1]}"
    return names[0], authors


def _years(raw: str) -> list[str]:
    return re.findall(_YEAR, raw)


def extract_citations(text: str) -> list[Citation]:
    text = html.unescape(text)
    found: list[tuple[int, Citation]] = []
    taken: list[tuple[int, int]] = []

    def add(pos: int, span: tuple[int, int], authors_raw: str, years: str, loc: str | None, raw: str):
        first, authors = _norm_authors(authors_raw)
        if not first:
            return
        taken.append(span)
        for y in _years(years):
            ctx = text[max(0, span[0] - 80):span[1]].replace("\n", " ").strip()
            found.append((pos, Citation(first, authors, y, raw.strip(), bool(loc), ctx)))

    for m in _CASE_RE.finditer(text):
        add(m.start(), m.span(), m["authors"], m["years"], m["loc"], m.group(0))
    for m in _NARR_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        add(m.start(), m.span(), m["authors"], m["years"], m["loc"], m.group(0))
    for m in _PAREN_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        for part in m.group(1).split(";"):
            pm = _PART_RE.match(part)
            if pm:
                add(m.start(), m.span(), pm["authors"], pm["years"], pm["loc"], part)

    found.sort(key=lambda t: t[0])
    seen: set[tuple[str, str]] = set()
    out: list[Citation] = []
    for _, c in found:
        k = (c.authors.lower(), c.year)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out
