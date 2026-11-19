"""PRISMA 2020-style counts computed from the event log.

Per (record, strand) the latest event of each stage wins. Retroactive records
that have never been screened in the logged flow sit in the "before logging"
lane. With no strand given, each record counts once (its furthest state across
strands) and ``strands`` gives the per-strand incorporated split.
"""

from __future__ import annotations

from collections import Counter

from zotero_mcp.provenance.store import ProvenanceStore

_EV_RANK = {"metadata": 0, "abstract": 1, "full_text": 2, "page_derived": 3, "quote_verified": 4}


def _state(record: dict, events: list[dict], has_codes: bool) -> dict:
    latest: dict[str, dict] = {}
    route = ""
    for e in events:  # id order
        latest[e["stage"]] = e
        if e["stage"] == "identified" and not route:
            route = e["route"] or "other"

    def kept(stage):
        e = latest.get(stage)
        return e is not None and e["decision"] == "keep"

    def cut(stage):
        e = latest.get(stage)
        return e is not None and e["decision"] == "exclude"

    lane = bool(record["retroactive"]) and "screened" not in latest
    read_ev = latest.get("read")
    return {
        "lane": lane,
        "route": route,
        "duplicate": "duplicate" in latest,
        "screened_out": cut("screened"),
        "screened_out_reason": latest["screened"]["reason"] if cut("screened") else "",
        "not_retrieved": cut("retrieved"),
        "not_retrieved_reason": latest["retrieved"]["reason"] if cut("retrieved") else "",
        "read_out": cut("read"),
        "read_out_reason": latest["read"]["reason"] if cut("read") else "",
        "read": kept("read") and _EV_RANK[read_ev["evidence"]] >= 2,
        "coded": kept("coded") or has_codes,
        "incorporated": kept("incorporated"),
    }


_PROGRESS = ("duplicate", "screened_out", "not_retrieved", "read_out", "read", "coded", "incorporated")


def _furthest(states: list[dict]) -> dict:
    """Collapse one record's per-strand states into one for the all-strands view."""
    logged = [s for s in states if not s["lane"]]
    pool = logged or states
    best = max(pool, key=lambda s: (s["incorporated"], s["coded"], s["read"], not s["duplicate"]))
    merged = dict(best)
    merged["lane"] = not logged
    return merged


def compute_counts(store: ProvenanceStore, strand: str | None = None) -> dict:
    records = {r["id"]: r for r in store.records()}
    coded_ids = {c["record_id"] for c in store.codes()}
    by_pair: dict[tuple[int, str], list[dict]] = {}
    for e in store.events(strand):
        by_pair.setdefault((e["record_id"], e["strand"]), []).append(e)

    per_record: dict[int, list[dict]] = {}
    strand_inc: Counter = Counter()
    for (rid, st), evs in by_pair.items():
        s = _state(records[rid], evs, rid in coded_ids)
        per_record.setdefault(rid, []).append(s)
        if s["incorporated"]:
            strand_inc[st] += 1

    states = [_furthest(v) if len(v) > 1 else v[0] for v in per_record.values()]
    c: Counter = Counter()
    reasons = {k: Counter() for k in ("screened_out", "not_retrieved", "read_out")}
    for s in states:
        if s["lane"]:
            c["prior_total"] += 1
            c["prior_read"] += s["read"]
            c["prior_incorporated"] += s["incorporated"]
            continue
        c[{"database": "identified_db", "citation": "identified_citation"}.get(s["route"], "identified_other")] += 1
        if s["duplicate"]:
            c["duplicates"] += 1
            continue
        for k in ("screened_out", "not_retrieved", "read_out"):
            if s[k]:
                c[k] += 1
                reasons[k][s[f"{k}_reason"] or "No reason given"] += 1
        c["read"] += s["read"]
        c["coded"] += s["coded"]
        c["incorporated"] += s["incorporated"]
        c["coded_not_cited"] += s["coded"] and not s["incorporated"]

    keys = ("identified_db", "identified_citation", "identified_other", "duplicates", "screened_out",
            "not_retrieved", "read_out", "read", "coded", "coded_not_cited", "incorporated",
            "prior_total", "prior_read", "prior_incorporated")
    out = {k: int(c[k]) for k in keys}
    out["identified"] = out["identified_db"] + out["identified_citation"] + out["identified_other"]
    out["screened"] = out["identified"] - out["duplicates"]
    out["sought"] = out["screened"] - out["screened_out"]
    out["retrieved"] = out["sought"] - out["not_retrieved"]
    out["screened_out_reasons"] = dict(reasons["screened_out"])
    out["not_retrieved_reasons"] = dict(reasons["not_retrieved"])
    out["read_out_reasons"] = dict(reasons["read_out"])
    out["strands"] = dict(strand_inc)
    out["strand"] = strand or "All strands"
    return out
