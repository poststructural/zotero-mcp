# Provenance log, phase 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A SQLite provenance log with retroactive import from the strand drafts and audit logs, PRISMA-style counts, and CSV/JSON/SVG export, exposed as an opt-in `provenance` MCP toolset.

**Architecture:** New package `zotero_mcp.provenance` (pure Python, no MCP imports) holds the store, the citation and audit parsers, counts and export. A thin tool module `zotero_mcp.tools.provenance` wraps it as MCP tools and handles Zotero matching and actor stamping. New code only; upstream files change in two registration lines and one toolset entry.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, FastMCP (existing), pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-source-discovery-provenance-design.md`

## Global Constraints

- Strands: `Canon`, `Censorship`, `Moral Panics`, `Text Selection` (free text allowed, these are the seeded values).
- Stages: `identified`, `duplicate`, `screened`, `retrieved`, `read`, `coded`, `incorporated`.
- Evidence levels, ordered: `metadata` < `abstract` < `full_text` < `page_derived` < `quote_verified`.
- Actors: `austin`, `assistant_suggested_austin_confirmed`, `assistant`. MCP tools may record only the last two; `assistant_suggested_austin_confirmed` requires non-empty `confirmation` text, stored on the event.
- Events are append-only; corrections are new events with `supersedes` set.
- Nothing is filled from model memory: a citation the parser cannot match stays a record holding the raw string with `needs_check = 1`.
- Audit import never assigns `quote_verified` (conservative); `page_derived` when the entry says "derived".
- DB path: env `ZOTERO_MCP_PROVENANCE_DB`, default `~/.local/share/zotero-mcp/provenance.db`.
- Toolset name `provenance`; not in `DEFAULT_ON`.

## Review Focus

- Citation forms in the drafts: `Sewell (2008)`, `Sewell's (2008)`, `(Sewell, 2008, p. 90)`, `Darragh & Boyd (2019)`, `Stotsky et al. (1990)`, `(Anderson, 1964; Applebee, 1989, 1992)`, `Applebee (1989/1992)` must all parse; `1894`-style years in prose without an author must not.
- Re-importing the same draft must not duplicate records or incorporated events (idempotent per strand + draft label).
- A record cited in two strands counts once in "All strands" and once in each strand.
- Audit entries naming two sources (log_moral A5) yield two linked records, and an entry with no parseable source is reported, not dropped silently.
- Counts with an empty database return zeros, not errors; SVG renders with zeros.

---

### Task 1: Store

**Files:** Create `src/zotero_mcp/provenance/__init__.py`, `src/zotero_mcp/provenance/store.py`; Test `tests/test_provenance_store.py`

**Produces:**
- `ProvenanceStore(path: str | Path)`; `:memory:` allowed.
- `.upsert_record(*, first_author: str, year: str, authors: str, title: str = "", zotero_key: str | None = None, doi: str | None = None, raw: str = "", needs_check: bool = False, retroactive: bool = False) -> int` — matches by zotero_key, then doi, then normalized (first_author, year, authors); fills empty fields only.
- `.add_event(record_id, *, strand, stage, decision="keep", reason="", note="", evidence="metadata", actor="assistant", client="", reader="", what_read="", route="", source_ref="", confirmation="", supersedes=None, dedupe_key=None) -> int | None` — returns None when `dedupe_key` already exists.
- `.add_code(record_id, *, field, value, evidence, locator="", actor="assistant", client="") -> int`
- `.record(record_id) -> dict`, `.find(first_author, year) -> list[dict]`, `.trail(record_id) -> dict` (record, events, codes), `.events(strand=None) -> list[dict]`, `.records() -> list[dict]`.
- Validation raises `ValueError` for unknown stage/evidence/actor.

Tests: upsert dedupes by key and by author-year; dedupe_key idempotency; invalid stage raises; trail returns events in time order.

### Task 2: Citation extractor

**Files:** Create `src/zotero_mcp/provenance/citations.py`; Test `tests/test_provenance_citations.py`

**Produces:** `Citation(first_author: str, authors: str, year: str, raw: str, quoted: bool)`; `extract_citations(text: str) -> list[Citation]` — unique by (authors, year), order of first appearance. `quoted` true when a page locator follows. Handles every form in Review Focus line 1; years 1600-2099 with optional letter suffix.

### Task 3: Audit-log parser

**Files:** Create `src/zotero_mcp/provenance/audit.py`; Test `tests/test_provenance_audit.py` (fixture snippets copied from the four real logs' formats)

**Produces:** `AuditEntry(heading: str, citations: list[Citation], zotero_keys: list[str], pdf_keys: list[str], status: str, evidence: str, text: str)`; `parse_audit_log(text: str) -> tuple[list[AuditEntry], list[str]]` (entries, unparsed headings). Entry boundaries: lines matching `^#{2,3} (?:[A-Z]?\d+\.)`. Evidence: `metadata` if "metadata only", "no PDF", "no attachment" or "Not readable"; else `page_derived` if "derived"; else `full_text` if a PDF key is present; else `metadata`.

### Task 4: Counts and export

**Files:** Create `src/zotero_mcp/provenance/counts.py`, `src/zotero_mcp/provenance/export.py`; Test `tests/test_provenance_counts.py`

**Produces:** `compute_counts(store, strand: str | None = None) -> dict` with keys `identified_db, identified_citation, identified_other, duplicates, screened_out, not_retrieved, read_out, read, coded, coded_not_cited, incorporated, prior_total, prior_read, prior_incorporated, strands` (latest event per record+strand+stage wins). `to_csv(store) -> str`, `to_json(store) -> str`, `to_svg(counts, title) -> str` (PRISMA 2020 layout with "Before logging (from drafts)" lane).

### Task 5: MCP tools and registration

**Files:** Create `src/zotero_mcp/tools/provenance.py`; Modify `src/zotero_mcp/tools/__init__.py`, `src/zotero_mcp/toolsets.py`; Test `tests/test_provenance_tools.py`

**Produces tools:** `provenance_import_draft(strand, draft_label, draft_date, text, match_zotero=True)`, `provenance_import_audit(strand, audit_log, log_name)`, `provenance_screen(record_ids, strand, decision, reason, actor, confirmation, note)`, `provenance_record_event(record_id, strand, stage, evidence, actor, confirmation, reader, what_read, note)`, `provenance_code(record_id, fields, evidence, locator, actor, confirmation)`, `provenance_trail(record_id)`, `provenance_counts(strand)`, `provenance_export(format, strand)`. Zotero matching: `backend.search_items(first_author, qmode="titleCreatorYear", limit=25)` filtered by year and creator lastName; exactly one hit → key, else `needs_check`. Client name from the MCP context when available, else `"mcp"`. Tests run against a temp DB via env var and FakeZotero; toolset validation test still passes.
