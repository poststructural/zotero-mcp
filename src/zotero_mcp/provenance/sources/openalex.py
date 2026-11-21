"""OpenAlex adapter: the reference implementation for new adapters.

Free, no key. A contact email (``ZOTERO_MCP_CONTACT_EMAIL``) puts requests in
OpenAlex's faster "polite pool"; without one the upstream noreply address is used.
"""

from __future__ import annotations

import os

from zotero_mcp.provenance.sources import http
from zotero_mcp.provenance.sources.base import SearchQuery, SourceAdapter, SourceRecord
from zotero_mcp.provenance.sources.registry import register

BASE = "https://api.openalex.org"
_FALLBACK_MAILTO = "zotero-mcp@users.noreply.github.com"
_SELECT = ("id,doi,title,display_name,publication_year,type,cited_by_count,authorships,"
           "primary_location,open_access,abstract_inverted_index")


def _short(oa_id: str | None) -> str:
    return (oa_id or "").rsplit("/", 1)[-1]


def _bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
    return d or None


def _abstract(inv: dict | None, words: int = 80) -> str | None:
    if not inv:
        return None
    pos = sorted((i, w) for w, idx in inv.items() for i in idx)
    text = " ".join(w for _, w in pos[:words])
    return text + (" …" if len(pos) > words else "")


def to_record(w: dict) -> SourceRecord:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    oa = w.get("open_access") or {}
    return SourceRecord(
        source="openalex",
        source_id=_short(w.get("id")),
        title=w.get("title") or w.get("display_name"),
        authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
        year=w.get("publication_year"),
        venue=src.get("display_name"),
        work_type=w.get("type"),
        doi=_bare_doi(w.get("doi")),
        url=w.get("id"),
        abstract=_abstract(w.get("abstract_inverted_index")),
        open_access_url=oa.get("oa_url") if oa.get("is_oa") else None,
        cited_by=w.get("cited_by_count"),
        raw={k: w.get(k) for k in ("id", "doi", "type", "publication_year")},
    )


@register
class OpenAlexAdapter(SourceAdapter):
    name = "openalex"
    label = "OpenAlex"
    capabilities = frozenset({"search", "references", "citations", "lookup_doi", "open_access"})
    access_note = "Free, no key; set ZOTERO_MCP_CONTACT_EMAIL for the polite pool."
    min_interval = 0.15

    def _get(self, path: str, params: dict | None = None) -> dict:
        p = {"mailto": os.environ.get("ZOTERO_MCP_CONTACT_EMAIL") or _FALLBACK_MAILTO, **(params or {})}
        data = http.get_json(f"{BASE}{path}", params=p, key=self.name, min_interval=self.min_interval)
        return data if isinstance(data, dict) else {}

    def search(self, query: SearchQuery) -> list[SourceRecord]:
        filters = []
        if query.year_from:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        if query.year_to:
            filters.append(f"to_publication_date:{query.year_to}-12-31")
        params = {"search": query.text, "per-page": min(max(query.limit, 1), 100), "select": _SELECT}
        if filters:
            params["filter"] = ",".join(filters)
        return [to_record(w) for w in self._get("/works", params).get("results") or []]

    def lookup_doi(self, doi: str) -> SourceRecord | None:
        d = _bare_doi(doi)
        if not d:
            return None
        w = self._get(f"/works/doi:{d}", {"select": _SELECT + ",referenced_works"})
        return to_record(w) if w.get("id") else None

    def references(self, source_id: str, limit: int = 25) -> list[SourceRecord]:
        w = self._get(f"/works/{_short(source_id)}", {"select": "id,referenced_works"})
        ids = [_short(r) for r in w.get("referenced_works") or []][:limit]
        out: list[SourceRecord] = []
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self._get("/works", {"filter": "openalex_id:" + "|".join(chunk),
                                        "per-page": len(chunk), "select": _SELECT})
            by_id = {_short(x.get("id")): x for x in data.get("results") or []}
            out += [to_record(by_id[c]) for c in chunk if c in by_id]
        return out

    def citations(self, source_id: str, limit: int = 25) -> list[SourceRecord]:
        data = self._get("/works", {"filter": f"cites:{_short(source_id)}", "sort": "cited_by_count:desc",
                                    "per-page": min(max(limit, 1), 100), "select": _SELECT})
        return [to_record(w) for w in data.get("results") or []]

    def open_access(self, doi: str) -> str | None:
        rec = self.lookup_doi(doi)
        return rec.open_access_url if rec else None
