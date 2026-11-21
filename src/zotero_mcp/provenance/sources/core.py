"""CORE adapter: open-access papers aggregated from repositories worldwide.

Needs a free API key from https://core.ac.uk/services/api, set as
``CORE_API_KEY``. Field names follow what working v3 clients read (title, doi,
id, authors[].name, downloadUrl, sourceFulltextUrls, publishedDate, journals,
publisher, documentType); ``yearPublished`` and ``abstract`` are used when
present. The query language (``doi:"…"``, ``yearPublished>=``) is CORE's v3
field syntax; results are filtered again locally so a query the API reads
differently can only return fewer rows, never wrong matches.
"""

from __future__ import annotations

import os

from zotero_mcp.provenance.sources import http
from zotero_mcp.provenance.sources.base import SearchQuery, SourceAdapter, SourceRecord
from zotero_mcp.provenance.sources.registry import register

BASE = "https://api.core.ac.uk/v3"
KEY_ENV = "CORE_API_KEY"


def _bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
    return d or None


def _year(w: dict) -> int | None:
    y = w.get("yearPublished")
    if isinstance(y, int) and y > 0:
        return y
    for k in ("publishedDate", "depositedDate"):
        v = str(w.get(k) or "")[:4]
        if v.isdigit():
            return int(v)
    return None


def _clip(text: str | None, words: int = 80) -> str | None:
    if not text:
        return None
    parts = text.split()
    return " ".join(parts[:words]) + (" …" if len(parts) > words else "")


def _oa_url(w: dict) -> str | None:
    if w.get("downloadUrl"):
        return w["downloadUrl"]
    for link in w.get("links") or []:
        if isinstance(link, dict) and link.get("type") == "download" and link.get("url"):
            return link["url"]
    urls = w.get("sourceFulltextUrls") or []
    return urls[0] if urls else None


def to_record(w: dict) -> SourceRecord:
    journals = [j.get("title") for j in w.get("journals") or [] if isinstance(j, dict) and j.get("title")]
    wid = str(w.get("id") or "")
    return SourceRecord(
        source="core",
        source_id=wid,
        title=w.get("title"),
        authors=[a.get("name", "") for a in w.get("authors") or [] if isinstance(a, dict) and a.get("name")],
        year=_year(w),
        venue=journals[0] if journals else (w.get("publisher") or None),
        work_type=w.get("documentType"),
        doi=_bare_doi(w.get("doi")),
        url=f"https://core.ac.uk/works/{wid}" if wid else None,
        abstract=_clip(w.get("abstract")),
        open_access_url=_oa_url(w),
        cited_by=w.get("citationCount") if isinstance(w.get("citationCount"), int) else None,
        raw={k: w.get(k) for k in ("id", "doi", "documentType", "publishedDate", "yearPublished")},
    )


@register
class CoreAdapter(SourceAdapter):
    name = "core"
    label = "CORE"
    capabilities = frozenset({"search", "lookup_doi", "open_access"})
    required_env = (KEY_ENV,)
    access_note = "Free API key (core.ac.uk/services/api) as CORE_API_KEY; open-access repository copies."
    min_interval = 2.0  # CORE's published quota for single searches: 5 per 10 seconds

    def _search(self, q: str, limit: int) -> list[dict]:
        data = http.get_json(
            f"{BASE}/search/works",
            params={"q": q, "limit": min(max(limit, 1), 100)},
            headers={"Authorization": f"Bearer {os.environ.get(KEY_ENV, '')}"},
            key=self.name, min_interval=self.min_interval,
        )
        results = data.get("results") if isinstance(data, dict) else None
        return [w for w in results or [] if isinstance(w, dict) and w.get("title")]

    def search(self, query: SearchQuery) -> list[SourceRecord]:
        q = f"({query.text})"
        if query.year_from:
            q += f" AND yearPublished>={query.year_from}"
        if query.year_to:
            q += f" AND yearPublished<={query.year_to}"
        out = []
        for w in self._search(q, query.limit):
            rec = to_record(w)
            if rec.year and ((query.year_from and rec.year < query.year_from)
                             or (query.year_to and rec.year > query.year_to)):
                continue
            out.append(rec)
        return out

    def lookup_doi(self, doi: str) -> SourceRecord | None:
        d = _bare_doi(doi)
        if not d:
            return None
        hits = [to_record(w) for w in self._search(f'doi:"{d}"', 5)]
        exact = [r for r in hits if r.doi == d]
        if not exact:
            return None
        # Several repositories can hold the same paper; prefer one with a file.
        return next((r for r in exact if r.open_access_url), exact[0])

    def open_access(self, doi: str) -> str | None:
        rec = self.lookup_doi(doi)
        return rec.open_access_url if rec else None
