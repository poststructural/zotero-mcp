"""Provenance tools: a PRISMA 2020-style log of how each source moved from
first sighting to the strand draft that cites it.

Opt-in toolset ``provenance``. The log is a SQLite file at
``ZOTERO_MCP_PROVENANCE_DB`` (default ``~/.local/share/zotero-mcp/provenance.db``).
These tools record what the caller states and what the parsers find in the
text; they never fill in metadata from memory.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from zotero_mcp import library as _library
from zotero_mcp._app import mcp
from zotero_mcp._context import Context
from zotero_mcp.client import zotero_api_lock
from zotero_mcp.provenance import EVIDENCE, STAGES
from zotero_mcp.provenance.audit import parse_audit_log
from zotero_mcp.provenance.citations import Citation, extract_citations
from zotero_mcp.provenance.counts import compute_counts
from zotero_mcp.provenance.export import to_csv, to_json, to_svg
from zotero_mcp.provenance.store import ProvenanceStore

DB_ENV = "ZOTERO_MCP_PROVENANCE_DB"
_DEFAULT_DB = "~/.local/share/zotero-mcp/provenance.db"
_MCP_ACTORS = ("assistant", "assistant_suggested_austin_confirmed")

_store: ProvenanceStore | None = None
_store_path: str | None = None
_lock = threading.Lock()


def get_store() -> ProvenanceStore:
    global _store, _store_path
    path = os.environ.get(DB_ENV) or str(Path(_DEFAULT_DB).expanduser())
    with _lock:
        if _store is None or _store_path != path:
            _store = ProvenanceStore(path)
            _store_path = path
        return _store


def _client(ctx) -> str:
    """Who is calling: MCP client name plus signed-in GitHub login when present."""
    name = ""
    try:
        name = ctx.session.client_params.clientInfo.name  # type: ignore[union-attr]
    except Exception:
        try:
            name = ctx.client_id or ""
        except Exception:
            name = ""
    login = ""
    try:
        from fastmcp.server.dependencies import get_access_token

        tok = get_access_token()
        claims = getattr(tok, "claims", {}) or {}
        login = claims.get("login") or claims.get("preferred_username") or ""
    except Exception:
        pass
    name = name if isinstance(name, str) and name else "mcp"
    return f"{name} ({login})" if login else name


def _check_actor(actor: str, confirmation: str) -> str | None:
    if actor not in _MCP_ACTORS:
        return ("Error: from chat, actor must be 'assistant' or "
                "'assistant_suggested_austin_confirmed'. Only Austin's own page records 'austin'.")
    if actor == "assistant_suggested_austin_confirmed" and not confirmation.strip():
        return "Error: 'assistant_suggested_austin_confirmed' needs the confirming message text in `confirmation`."
    return None


# -- Zotero matching ---------------------------------------------------------


def _match_items(items: list[dict], cite: Citation) -> list[dict]:
    """Zotero items whose year and first creator surname match the citation."""
    out = []
    want = cite.first_author.lower()
    for it in items:
        d = it.get("data", it)
        year = str(d.get("date", ""))[:4] if d.get("date") else ""
        if year != cite.year[:4]:
            continue
        creators = d.get("creators") or []
        first = creators[0] if creators else {}
        last = (first.get("lastName") or first.get("name") or "").lower()
        if last and (last == want or want.startswith(last) or last.startswith(want)):
            out.append(it)
    return out


def _zotero_candidates(cite: Citation) -> list[dict]:
    with zotero_api_lock():
        backend = _library.get_library_backend()
        items = backend.search_items(f"{cite.first_author} {cite.year[:4]}", qmode="titleCreatorYear", limit=25)
    return _match_items(items or [], cite)


def _item_key(it: dict) -> str:
    return it.get("key") or it.get("data", {}).get("key", "")


def _item_title(it: dict) -> str:
    return it.get("data", it).get("title", "")


# -- tools -------------------------------------------------------------------


@mcp.tool(
    name="provenance_import_draft",
    description=(
        "Record the sources cited in a strand draft as 'before logging' sources "
        "(PRISMA 'other methods: prior draft'). Pass the draft's plain text in `text`; "
        "author-year citations are extracted deterministically from it, matched to "
        "Zotero by first author and year when match_zotero is true, and logged as "
        "identified + incorporated for `strand`. Unmatched or ambiguous citations are "
        "kept with their raw text and flagged [CHECK]; nothing is filled in. Safe to "
        "re-run: the same strand + draft_label is not logged twice."
    ),
)
def provenance_import_draft(
    strand: str,
    draft_label: str,
    draft_date: str,
    text: str,
    match_zotero: bool = True,
    *,
    ctx: Context,
) -> str:
    try:
        store, client = get_store(), _client(ctx)
        cites = extract_citations(text)
        new_inc, flagged = 0, []
        for c in cites:
            key, title, check = None, "", True
            if match_zotero:
                try:
                    hits = _zotero_candidates(c)
                except Exception as e:  # Zotero unreachable: keep going, flag
                    ctx.warning(f"Zotero lookup failed for {c.authors} ({c.year}): {e}")
                    hits = []
                if len(hits) == 1:
                    key, title, check = _item_key(hits[0]), _item_title(hits[0]), False
            rid = store.upsert_record(first_author=c.first_author, year=c.year, authors=c.authors,
                                      title=title, zotero_key=key or None, raw=c.context,
                                      needs_check=check, retroactive=True)
            if check and not store.record(rid)["zotero_key"]:
                flagged.append(f"{c.authors} ({c.year})")
            ref = f"draft:{draft_label}"
            store.add_event(rid, strand=strand, stage="identified", route="other", source_ref=ref,
                            note=f"Cited in {draft_label} ({draft_date})", client=client,
                            dedupe_key=f"id|{strand}|{rid}")
            if store.add_event(rid, strand=strand, stage="incorporated", source_ref=ref,
                               note=f"Cited in {draft_label} ({draft_date})", client=client,
                               dedupe_key=f"inc|{strand}|{draft_label}|{rid}") is not None:
                new_inc += 1
        lines = [f"# Imported {draft_label} into {strand}",
                 f"{len(cites)} cited sources found; {new_inc} newly logged as incorporated."]
        if flagged:
            lines.append(f"\n[CHECK] {len(flagged)} not matched to exactly one Zotero item:")
            lines += [f"- {f}" for f in flagged]
        return "\n".join(lines)
    except Exception as e:
        ctx.error(f"provenance_import_draft failed: {e}")
        return f"Error: {e}"


@mcp.tool(
    name="provenance_import_audit",
    description=(
        "One-time backfill from a source audit log (markdown, e.g. log_textsel.md). Each "
        "numbered entry is parsed for its citation(s), Zotero keys, status and evidence "
        "level (metadata / full_text / page_derived; never quote_verified), and logged as "
        "a 'read' event (or 'retrieved' with metadata only) for `strand`, with the entry "
        "text kept verbatim. Entries that name no source are reported, not guessed."
    ),
)
def provenance_import_audit(strand: str, audit_log: str, log_name: str, *, ctx: Context) -> str:
    try:
        store, client = get_store(), _client(ctx)
        entries, unparsed = parse_audit_log(audit_log)
        logged = 0
        for e in entries:
            targets: list[int] = []
            for k in e.zotero_keys:
                r = store.find_by_zotero_key(k)
                if r:
                    targets.append(r["id"])
            for c in e.citations:
                found = store.find(c.first_author, c.year)
                exact = [r for r in found if r["authors"].lower() == c.authors.lower()] or found
                if exact:
                    rid = exact[0]["id"]
                else:
                    rid = store.upsert_record(first_author=c.first_author, year=c.year, authors=c.authors,
                                              raw=c.context, needs_check=True, retroactive=True)
                    store.add_event(rid, strand=strand, stage="identified", route="other",
                                    source_ref=f"audit:{log_name}", client=client,
                                    note=f"Named in audit log {log_name}", dedupe_key=f"id|{strand}|{rid}")
                if len(e.citations) == 1 and len(e.zotero_keys) == 1 and not store.record(rid)["zotero_key"]:
                    store.upsert_record(first_author=c.first_author, year=c.year, authors=c.authors,
                                        zotero_key=e.zotero_keys[0])
                if rid not in targets:
                    targets.append(rid)
            stage = "read" if e.evidence != "metadata" else "retrieved"
            decision = "keep" if stage == "read" else "exclude"
            for rid in targets:
                done = store.add_event(
                    rid, strand=strand, stage=stage, decision=decision, evidence=e.evidence,
                    reader="assistant (audit)", what_read=", ".join(e.pdf_keys),
                    reason="" if decision == "keep" else "Full text not seen (metadata only)",
                    source_ref=f"audit:{log_name}#{e.heading.split('.')[0]}",
                    note=f"{e.heading} | Status: {e.status}\n\n{e.text[:4000]}", client=client,
                    dedupe_key=f"audit|{strand}|{log_name}|{e.heading}|{rid}")
                logged += done is not None
        lines = [f"# Imported audit log {log_name} into {strand}",
                 f"{len(entries)} entries parsed; {logged} events logged."]
        if unparsed:
            lines.append("\nEntries naming no source (not imported):")
            lines += [f"- {h}" for h in unparsed]
        return "\n".join(lines)
    except Exception as e:
        ctx.error(f"provenance_import_audit failed: {e}")
        return f"Error: {e}"


@mcp.tool(
    name="provenance_screen",
    description=(
        "Record a screening decision (keep or exclude, with reason) for one or more log "
        "records in a strand. actor is 'assistant' or "
        "'assistant_suggested_austin_confirmed' (then pass Austin's confirming message in "
        "`confirmation`)."
    ),
)
def provenance_screen(
    record_ids: list[int],
    strand: str,
    decision: str,
    reason: str = "",
    actor: str = "assistant",
    confirmation: str = "",
    note: str = "",
    evidence: str = "abstract",
    *,
    ctx: Context,
) -> str:
    err = _check_actor(actor, confirmation)
    if err:
        return err
    if decision == "exclude" and not reason.strip():
        return "Error: an exclusion needs a reason."
    try:
        store, client = get_store(), _client(ctx)
        ids = [store.add_event(int(r), strand=strand, stage="screened", decision=decision, reason=reason,
                               note=note, evidence=evidence, actor=actor, confirmation=confirmation,
                               client=client) for r in record_ids]
        return f"Recorded {decision} for {len(ids)} record(s) in {strand}."
    except (ValueError, KeyError) as e:
        return f"Error: {e}"


@mcp.tool(
    name="provenance_record_event",
    description=(
        f"Record a stage for a record in a strand. stage: {', '.join(STAGES)}. "
        f"evidence: {', '.join(EVIDENCE)}. For 'read', say who read it (`reader`) and "
        "what was read (`what_read`: Zotero attachment key, pages, or URL); a full-text "
        "level without `what_read` is refused."
    ),
)
def provenance_record_event(
    record_id: int,
    strand: str,
    stage: str,
    evidence: str = "metadata",
    decision: str = "keep",
    reason: str = "",
    actor: str = "assistant",
    confirmation: str = "",
    reader: str = "",
    what_read: str = "",
    note: str = "",
    *,
    ctx: Context,
) -> str:
    err = _check_actor(actor, confirmation)
    if err:
        return err
    if evidence in ("full_text", "page_derived", "quote_verified") and not what_read.strip():
        return "Error: a full-text evidence level needs `what_read` (attachment key, pages, or URL)."
    try:
        eid = get_store().add_event(int(record_id), strand=strand, stage=stage, decision=decision,
                                    reason=reason, evidence=evidence, actor=actor,
                                    confirmation=confirmation, reader=reader, what_read=what_read,
                                    note=note, client=_client(ctx))
        return f"Recorded {stage} ({decision}, {evidence}) for record {record_id} in {strand} [event {eid}]."
    except (ValueError, KeyError) as e:
        return f"Error: {e}"


@mcp.tool(
    name="provenance_code",
    description=(
        "Record coded attributes of a source (e.g. genre, purpose, method, sample, setting, "
        "findings, limitations) as a JSON object in `fields`. Each value carries the "
        "evidence level and optional locator. Keep surveys of assigned reading, teacher "
        "reports of decision authority, and student reading experiences as distinct genres."
    ),
)
def provenance_code(
    record_id: int,
    fields: dict[str, str] | str,
    evidence: str,
    locator: str = "",
    actor: str = "assistant",
    confirmation: str = "",
    *,
    ctx: Context,
) -> str:
    err = _check_actor(actor, confirmation)
    if err:
        return err
    try:
        if isinstance(fields, str):
            fields = json.loads(fields)
        store, client = get_store(), _client(ctx)
        for k, v in fields.items():
            store.add_code(int(record_id), field=str(k), value=str(v), evidence=evidence,
                           locator=locator, actor=actor, client=client)
        return f"Coded {len(fields)} field(s) for record {record_id}."
    except (ValueError, KeyError) as e:
        return f"Error: {e}"


@mcp.tool(
    name="provenance_trail",
    description="Show one record's full provenance trail: metadata, every event in order, and its codes.",
)
def provenance_trail(record_id: int, *, ctx: Context) -> str:
    try:
        t = get_store().trail(int(record_id))
    except KeyError as e:
        return f"Error: {e}"
    r = t["record"]
    lines = [f"# {r['authors']} ({r['year']})" + (" [CHECK]" if r["needs_check"] else ""),
             f"Title: {r['title'] or '(none recorded)'} | Zotero: {r['zotero_key'] or '-'}"
             + (" | before logging" if r["retroactive"] else ""), "", "## Trail"]
    for e in t["events"]:
        who = e["actor"] + (f" via {e['client']}" if e["client"] else "")
        lines.append(f"- {e['created_at'][:10]} {e['strand']}: {e['stage']} ({e['decision']}, "
                     f"{e['evidence']}) by {who}" + (f"; reason: {e['reason']}" if e["reason"] else "")
                     + (f"; read: {e['what_read']}" if e["what_read"] else "")
                     + (f"; {e['source_ref']}" if e["source_ref"] else ""))
    if t["codes"]:
        lines += ["", "## Codes"] + [f"- {c['field']}: {c['value']} ({c['evidence']}"
                                     + (f", {c['locator']}" if c["locator"] else "") + ")" for c in t["codes"]]
    return "\n".join(lines)


@mcp.tool(
    name="provenance_counts",
    description="PRISMA 2020-style counts for one strand (or all strands when omitted), including the before-logging lane.",
)
def provenance_counts(strand: str | None = None, *, ctx: Context) -> str:
    return json.dumps(compute_counts(get_store(), strand or None), indent=1)


@mcp.tool(
    name="provenance_export",
    description="Export the log: format 'csv' or 'json' (full log), or 'svg' (static PRISMA-style diagram for `strand`, all strands when omitted).",
)
def provenance_export(format: str = "svg", strand: str | None = None, *, ctx: Context) -> str:
    store = get_store()
    if format == "csv":
        return to_csv(store)
    if format == "json":
        return to_json(store)
    if format == "svg":
        return to_svg(compute_counts(store, strand or None), strand or "All strands")
    return "Error: format must be csv, json or svg."


# -- discovery across source adapters ------------------------------------------


def _sources():
    from zotero_mcp.provenance import sources  # registers built-in adapters

    return sources


def _render_hits(store: ProvenanceStore, ids: list[int], limit: int = 40) -> list[str]:
    lines = []
    for rid in ids[:limit]:
        r = store.record(rid)
        flag = " [prior draft]" if r["retroactive"] else (" [in Zotero]" if r["zotero_key"] else "")
        lines.append(f"- #{rid} {r['authors']} ({r['year']}). {r['title'] or '(no title)'}{flag}")
    if len(ids) > limit:
        lines.append(f"- … {len(ids) - limit} more (provenance_export for all)")
    return lines


@mcp.tool(
    name="discover_sources",
    description="List the scholarly-database adapters, whether each is enabled here, what it can do, and its access terms.",
)
def discover_sources(*, ctx: Context) -> str:
    rows = _sources().status()
    if not rows:
        return "No source adapters are registered."
    out = ["| Source | Enabled | Status | Can do | Access |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['label'] or r['name']} (`{r['name']}`) | {'yes' if r['enabled'] else 'no'} | "
                   f"{r['status']} | {', '.join(r['capabilities'])} | {r['access']} |")
    return "\n".join(out)


@mcp.tool(
    name="discover_search",
    description=(
        "Search enabled scholarly databases (all enabled ones, or those named in `sources`) "
        "and log each as a run. Results are metadata only and enter the provenance log as "
        "'identified' (route: database) for `strand`, matched against existing records so "
        "nothing is double-counted. Returns log record ids for screening."
    ),
)
def discover_search(
    query: str,
    strand: str,
    sources: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 25,
    *,
    ctx: Context,
) -> str:
    from zotero_mcp.provenance.ingest import ingest

    src = _sources()
    adapters = src.enabled("search", sources)
    if not adapters:
        return "Error: no enabled adapter can search. Run discover_sources to see why."
    store, client = get_store(), _client(ctx)
    q = src.SearchQuery(text=query, year_from=year_from, year_to=year_to, limit=max(1, min(int(limit), 100)))
    params = json.dumps({"year_from": year_from, "year_to": year_to, "limit": q.limit})
    out = [f"# Search: {query} ({strand})"]
    for a in adapters:
        run = store.start_run(kind="search", source=a.name, query=query, strand=strand, params=params, client=client)
        try:
            recs = a.search(q)
        except src.SourceUnavailable as e:
            store.finish_run(run, hits=None, new_records=None, error=str(e))
            out.append(f"\n## {a.label}: FAILED ({e}). This is not a zero.")
            continue
        res = ingest(store, recs, strand=strand, run_id=run, route="database", client=client)
        store.finish_run(run, hits=len(recs), new_records=res.new)
        out.append(f"\n## {a.label} (run {run}): {len(recs)} hits, {res.new} new to the log, "
                   f"{res.refound_prior} already in prior drafts")
        out += _render_hits(store, res.record_ids)
    return "\n".join(out)


@mcp.tool(
    name="discover_citations",
    description=(
        "Citation dive from one source: direction 'references' (works it cites), 'citations' "
        "(works citing it) or 'both'. `seed` is a log record id, a DOI, or a database id "
        "with prefix (e.g. 'openalex:W2922753666'). Logs one run per direction; results enter "
        "the log as 'identified' (route: citation) for `strand`."
    ),
)
def discover_citations(
    seed: str,
    strand: str,
    direction: str = "both",
    source: str = "openalex",
    limit: int = 25,
    *,
    ctx: Context,
) -> str:
    from zotero_mcp.provenance.ingest import ingest

    src = _sources()
    if direction not in ("references", "citations", "both"):
        return "Error: direction must be references, citations or both."
    try:
        adapter = src.get(source)
    except KeyError as e:
        return f"Error: {e}"
    if source not in {r["name"] for r in src.status() if r["enabled"]}:
        return f"Error: source {source!r} is not enabled here. Run discover_sources."
    store, client = get_store(), _client(ctx)

    seed_rid, source_id = None, None
    s = str(seed).strip()
    if s.isdigit():
        seed_rid = int(s)
        try:
            rec = store.record(seed_rid)
        except KeyError as e:
            return f"Error: {e}"
        source_id = store.source_ids(seed_rid).get(source)
        doi = rec["doi"]
    elif s.startswith(f"{source}:"):
        source_id, doi = s.split(":", 1)[1], None
    else:
        doi = s
    try:
        if source_id is None:
            if not doi or "lookup_doi" not in adapter.capabilities:
                return f"Error: no {source} id or DOI to start from for seed {seed!r}."
            found = adapter.lookup_doi(doi)
            if found is None:
                return f"{adapter.label} has no record for DOI {doi}."
            source_id = found.source_id
            if seed_rid is not None:
                store.link_source(seed_rid, source, source_id)
    except src.SourceUnavailable as e:
        return f"Error: {adapter.label} lookup failed ({e})."

    dirs = ["references", "citations"] if direction == "both" else [direction]
    out = [f"# Citation dive from {seed} via {adapter.label} ({strand})"]
    for d in dirs:
        if d not in adapter.capabilities:
            out.append(f"\n## {d}: {adapter.label} does not support this.")
            continue
        run = store.start_run(kind=d, source=source, query=source_id, strand=strand,
                              seed_record_id=seed_rid, client=client)
        try:
            recs = getattr(adapter, d)(source_id, limit=max(1, min(int(limit), 100)))
        except src.SourceUnavailable as e:
            store.finish_run(run, hits=None, new_records=None, error=str(e))
            out.append(f"\n## {d}: FAILED ({e}). This is not a zero.")
            continue
        res = ingest(store, recs, strand=strand, run_id=run, route="citation", client=client)
        store.finish_run(run, hits=len(recs), new_records=res.new)
        out.append(f"\n## {d} (run {run}): {len(recs)} found, {res.new} new to the log, "
                   f"{res.refound_prior} already in prior drafts")
        out += _render_hits(store, res.record_ids)
    return "\n".join(out)
