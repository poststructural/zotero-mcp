"""Put adapter results into the provenance log.

Matching order: the database's own id, then DOI, then normalized authors + year.
A match against a source already in the drafts is recorded as "re-found" and
not double-counted (design, 2026-11-19).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from zotero_mcp.provenance.sources.base import SourceRecord
from zotero_mcp.provenance.store import ProvenanceStore


def author_string(authors: list[str]) -> str:
    def surname(n: str) -> str:
        n = n.replace('"', " ").replace("“", " ").replace("”", " ").strip()
        if "," in n:
            return n.split(",")[0].strip()
        return n.split()[-1] if n.split() else ""

    sn = [s for s in (surname(a) for a in authors) if s]
    if not sn:
        return ""
    if len(sn) == 1:
        return sn[0]
    if len(sn) == 2:
        return f"{sn[0]} & {sn[1]}"
    return f"{sn[0]} et al."


@dataclass
class IngestResult:
    record_ids: list[int] = field(default_factory=list)
    new: int = 0
    refound_prior: int = 0
    skipped: int = 0  # no title/author/year to identify it by


def ingest(store: ProvenanceStore, records: list[SourceRecord], *, strand: str, run_id: int,
           route: str, client: str = "") -> IngestResult:
    res = IngestResult()
    for r in records:
        existing = store.find_by_source(r.source, r.source_id)
        authors = author_string(r.authors)
        year = str(r.year) if r.year else ""
        if existing is None and not (authors and year) and not r.doi:
            res.skipped += 1
            continue
        before = store.max_record_id() if existing is None else None
        if existing is not None:
            rid = existing["id"]
        else:
            rid = store.upsert_record(first_author=authors.split(" ")[0] if authors else "Unknown",
                                      year=year or "n.d.", authors=authors or "Unknown",
                                      title=r.title or "", doi=r.doi)
        store.link_source(rid, r.source, r.source_id)
        rec = store.record(rid)
        is_new = before is not None and rid > before
        res.new += is_new
        if rec["retroactive"]:
            res.refound_prior += 1
            note = f"Re-found by run {run_id} ({r.source}); already in prior drafts"
        else:
            note = f"{r.source} {r.source_id}" + (f"; OA: {r.open_access_url}" if r.open_access_url else "")
        store.add_event(rid, strand=strand, stage="identified", route=route, source_ref=f"run:{run_id}",
                        note=note, client=client, dedupe_key=f"run|{strand}|{run_id}|{rid}")
        res.record_ids.append(rid)
    return res
