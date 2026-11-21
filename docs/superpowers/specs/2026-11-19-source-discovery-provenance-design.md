# Source discovery and provenance ("Transhuman PRISMA"): design

Date: 2026-11-19
Requested by: Austin (dissertation, secondary English curriculum and instruction)
Status: draft for Austin's approval (builder-check questions answered 2026-11-19)
Mockup: https://claude.ai/artifact/PSUyUQXeMBJTmKVAwKZ59b (approved in conversation as the look and feel: "I dig it")

## 1. Intent

Austin is writing a four-strand critical synthesis (Canon/Canon Wars, Censorship,
Moral Panics, Text Selection) for a dissertation on how political, economic and
institutional conditions shape the curricular decisions of secondary English
teachers across U.S. states. He wants one tool with two primary functions:

1. **Discovery.** Find sources he does not yet have, by (a) searching scholarly
   databases and (b) deep citation diving, backward and forward, from items
   already in his Zotero library.
2. **Provenance beyond PRISMA.** Keep a per-source record of every move from
   first sighting to the paragraph that cites it, and generate from that record
   a flow chart he could publish in a methods section or appendix. It follows
   PRISMA 2020 (https://www.prisma-statement.org/prisma-2020) and extends it
   with stages PRISMA lacks: read, coded, incorporated. The chart is
   interactive: every count opens the sources behind it, and every source opens
   its full trail.

Why: a reader (committee, journal reviewers, Dorothea) should be able to trust
how the review was assembled, and Austin should never have to hand-tally it.

## 2. Goals

- Every number on the chart is computed from the log and can be drilled down to
  the individual records behind it.
- Every record carries its trail: each stage, date, decision, reason, who made
  the decision, and the **evidence level** the decision rested on.
- Discovery results land in the same log, so a chart box can be traced back to
  the search or citation dive that produced it.
- Works from every client already connected to Austin's server (Claude, ChatGPT,
  Codex), because it is part of the MCP server.
- Produces a static, publication-ready PRISMA 2020-style diagram (SVG and PDF)
  plus a CSV/JSON export of the full log for an appendix.

## 3. Non-goals

- Not a Covidence/Rayyan clone: no multi-reviewer conflict resolution, no
  risk-of-bias tooling.
- Does not store PDFs. Full texts stay in Zotero (cloud storage) and are read
  with the existing zotero-mcp tools.
- Does not edit Austin's strand drafts.
- Does not change the Zotero library beyond adding kept candidates to one
  "Discovery inbox" collection (phase 4, gated; see section 8).

## 4. Anti-goals (failure even if it "works")

- A count on the chart that cannot be traced to records.
- A decision Claude made shown as Austin's. Every event records its actor.
- Any metadata, finding, page number or quotation that did not come from an API
  response or a source actually read. Records keep the raw API payload; nothing
  is filled in from model memory. Unknown fields stay empty or `[CHECK]`.
- Showing a source as "read" or "coded" on the basis of metadata or a past draft
  alone. Evidence level is explicit and only rises through a recorded event that
  names what was read (Zotero attachment key, page range, or URL).
- Making the 1,000+ screened-out records clutter Austin's Zotero library.

## 5. Constraints

- Home: Austin's fork `poststructural/zotero-mcp` (forked from 54yyyu/zotero-mcp
  0.17.2). Keep new code in new modules and a new toolset so upstream merges stay
  easy (Austin plans to keep syncing upstream).
- Deployment: Linux server, `/opt/zotero-mcp`, systemd unit, streamable HTTP on
  127.0.0.1:8765, Cloudflare tunnel at `https://zotero-mcp.austin-unowitz.com/mcp`,
  GitHub OAuth allowlist wrapper `deploy/serve_zotero_oauth.py`. Zotero **web API**
  mode with a **read-only** key today. Any deploy waits for Austin's approval.
- Upstream already ships `zotero_find_related_papers` and `zotero_library_coverage`
  (`src/zotero_mcp/tools/discovery.py`, OpenAlex). Reuse its helpers (DOI
  resolution, in-library check, OpenAlex client); do not duplicate them.
- Many of Austin's sources predate DOIs (Tanner 1907, Applebee 1974, ERIC
  documents, book chapters). Matching cannot rely on DOI alone.
- Polite-use rules: OpenAlex and Crossref want a contact email (`mailto`),
  Unpaywall requires one, Semantic Scholar is rate limited without a key, CORE
  needs a key. All come from env vars on the server; none is hard-coded. Austin
  chooses the contact email.
- Project citation rules apply to anything the tool writes into notes or exports:
  paraphrase = author and year without page; quotation = verified locator.

## 6. Approaches considered

1. **Inside the zotero-mcp fork (chosen by Austin).** Discovery tools and the
   provenance log live on his server; the server also serves the interactive
   chart. Reachable from Claude, ChatGPT and Codex. Cost: more server work and
   an approved deploy.
2. Standalone tool in the Claude project (scripts plus a log file in project
   files, chart as an Artifact page). No deploy, but only Claude threads could
   run discovery, and ChatGPT is left out.
3. Zotero itself as the log (tags and notes per item). Lives with the sources,
   but needs a write key on every operation and floods the library with
   excluded records.

Option 1 borrows option 3's strength: only kept candidates are added to Zotero,
into one collection.

## 7. The stages

Per record, **per strand** (a source can be incorporated in Canon and excluded
from Censorship; each strand has its own chart; the "All strands" view counts
unique records and shows the per-strand split):

| Stage | PRISMA 2020 analogue | Exclusion box |
|---|---|---|
| Identified: database search / citation diving / other methods | Identification (two columns: databases; other methods) | Duplicates removed |
| Screened (title and abstract) | Records screened | Excluded at screening, with reason |
| Full text sought / retrieved | Reports sought for retrieval | Not retrieved, with reason |
| Read (full text) | Reports assessed for eligibility | Excluded after reading, with reason |
| Coded | (beyond PRISMA) | Coded, not cited (held in reserve) |
| Incorporated (cited in a strand draft, with draft version) | Studies included | |

"Other methods" covers prior drafts, advisor suggestions and hand searching.
Sources already in the drafts before the tool existed enter here, flagged
`retroactive`, with the draft date as their identification date.

**Before-logging lane (Austin's decision, 2026-11-19).** On the chart these
retroactive sources sit in a clearly labeled "Before logging (from drafts)" lane
that enters the flow at Read (if the audit logs show a full-text read) or at
Incorporated, rather than passing through screening boxes that were never logged.
The lane is visible and counted, never hidden. A later optional attestation pass
(Austin confirms reads in batches) can move sources into the normal boxes.

**Baseline searches (Austin's decision, 2026-11-19).** Austin has no records of
earlier database searches. Instead the tool starts a documented process now: for
each strand, a written set of search strings and databases (drafted with Austin
and approved by him before running) is run once as the strand's baseline search,
dated, and logged as ordinary runs. When a baseline search re-finds a source
already in the before-logging lane, the record is linked, not duplicated: it
keeps its retroactive flag and history and also shows the run that re-found it.
The chart reports how many prior sources the baseline searches recovered, a
useful check on coverage. *(How re-found records are counted, once and marked
"also in prior drafts", is Claude's call; Austin can change it.)*

Evidence levels, in order: `metadata` (title, reference-list entry), `abstract`,
`full_text`, `page_derived` (wording confirmed; printed page inferred from text
layout or header/footer offsets, as the audit logs mark "derived"),
`quote_verified` (wording and printed page confirmed from the page itself).
*(Builder-check call: `page_derived` added so derived locators are not
overstated.)*

Actors: `austin`, `assistant_suggested_austin_confirmed`, `assistant` (an
assistant acted alone, e.g. read a PDF during an audit). The server stamps every
event with the client that made the call (Claude, ChatGPT, Codex, or the web
page) from the request, not from a tool argument. MCP calls can record at most
`assistant_suggested_austin_confirmed`, and only when the call carries the
confirming message text; only the `/prisma` page (Austin signed in) records
`austin`. "Read" events also record **who read**. *(Builder-check call.)*

Coding fields (Austin: "what kind of study is it, what is the sample, etc."),
matching the project's SOURCE AUDIT fields: genre (controlled list below),
purpose/question, method, sample, setting/context, principal findings,
limitations, quotation locations. Each coded value carries its evidence level and
locator. Seed genre list (Austin can edit): survey of assigned reading; teacher
reports of decision authority; student reading experiences; qualitative case or
interview study; historical analysis; policy or legal analysis; commentary or
professional essay; report (advocacy/NGO). The first three must never be merged
(project rule).

Reason codes are a controlled, editable vocabulary per strand, seeded from the
inclusion criteria (secondary level, U.S. context, English/literature,
curricular decisions or text selection, strand topic).

## 8. What gets built (decided parts)

### 8.1 Provenance log
- SQLite file on the server (path from env, default `/opt/zotero-mcp/data/provenance.db`),
  owned by the service user, included in a nightly backup/export.
- Core tables (builder may refine): `record` (normalized metadata, all external
  IDs: DOI, OpenAlex, ERIC, Semantic Scholar, Zotero key; raw payload JSON),
  `run` (one search or one citation dive: kind, API, query or seed, params,
  timestamp, hits, already-in-Zotero, new), `sighting` (record seen in run: rank,
  depth, parent record → lineage), `event` (record, strand, stage, decision,
  reason code, note, evidence level, actor, reader, what was read, timestamp),
  `code` (record, field, value, evidence level, locator, actor, timestamp).
- Append-only events. A correction is a new event that supersedes an old one;
  the trail shows both.
- Deduplication: exact match on any shared external ID, then normalized
  title + year + first-author surname; uncertain matches are queued for Austin,
  never auto-merged.

### 8.2 Discovery (MCP tools, new `provenance` toolset)
- `discover_search(query, sources, strand, year_from, year_to, limit)`: OpenAlex,
  ERIC, Semantic Scholar, Crossref. Logs a run; returns new records flagged
  in-Zotero / already-in-log.
- `discover_citations(seed, direction, depth, strand, limit)`: seed is a Zotero
  key, DOI, or log record; backward and forward; depth 1 by default, 2 allowed
  with a hard cap. Records lineage.
- `discover_from_strand(strand, direction, limit_per_seed)`: batch dive from every
  incorporated record in a strand.
- Open-access lookup (Unpaywall, then CORE) when full text is sought.

### 8.3 Provenance tools
- `provenance_import_draft(strand, draft_label, draft_date, references)`:
  retroactive import of a draft's reference list as "other methods". The caller
  passes the raw reference-list text; the **server** parses it deterministically
  (one entry per line or paragraph), matches entries to Zotero items and returns
  unparsed or unmatched lines. Unmatched entries become records holding only the
  raw string, marked `[CHECK]`; no model fills in metadata. Baseline drafts: the
  `*_rev_11.18.26.docx` files; identification date is the earliest known draft
  date (10.20.26 for the strands drafted then) when known. *(Builder-check call.)*
- `provenance_import_audit(strand, audit_log)`: one-time backfill from Austin's
  audit logs (`log_canon.md`, `log_censor.md`, `log_moral.md`, `log_textsel.md`;
  layouts differ). Tolerant parser that pulls Zotero keys, statuses and locators
  per entry and stores the entry's text verbatim beside each event; entries it
  cannot parse are reported, not guessed. Future audits are recorded with the
  normal tools, not new logs. *(Builder-check call.)*
- `provenance_screen(records, strand, decision, reason, actor, note)`.
- `provenance_record_event(record, strand, stage, evidence, actor, reader, what_read, note)`.
- `provenance_code(record, fields, evidence, locator, actor)`.
- `provenance_trail(record)`, `provenance_queue(strand, stage)`,
  `provenance_counts(strand)`.
- `provenance_export(strand, format)`: CSV, JSON, and the static PRISMA SVG/PDF.

### 8.4 Interactive chart
- Viewer: Austin only (decision, 2026-11-19). Others (Dorothea, committee) get
  the static export or a snapshot, not the live page.
- Served by the same process at `/prisma`, matching the mockup: flow boxes,
  strand filter, drill-down to records, full trail, discovery-runs table with
  lineage tree.
- Screening and stage buttons on the page as well as in chat ("both"). Page
  decisions are recorded with actor `austin`.
- Needs browser auth separate from the MCP OAuth tokens (see section 10).

### 8.5 Zotero "Discovery inbox" (phase 4, gated)
- `discover_add_to_inbox(records)`: creates items in one collection. Requires a
  separate write-enabled key (`ZOTERO_WRITE_API_KEY`) used only by this tool;
  the read-only key stays the default. **Ask Austin before creating or installing
  that key.**
- Any Zotero tags this tool writes use the `prov:` prefix; Austin's Marginalia
  app owns `theme:` and `ask:` (2026-11-21).

## 9. Phasing

1. Log, retroactive import from the four strand drafts and audit logs, counts,
   static export. (Gives a real chart for the existing review first.)
2. Discovery tools across the four APIs plus open-access lookup, then the
   per-strand baseline searches (search strings approved by Austin first).
3. Interactive `/prisma` page with screening.
4. Zotero inbox writes, after Austin approves the write key.

Each phase is a PR to the fork; nothing reaches the live server until Austin
approves a deploy.

## 10. Left to the builder

- Schema details, indexes, migrations.
- HTTP client structure, caching of API responses, retry and rate limiting.
- Browser auth for `/prisma` (options: Cloudflare Access on that path; a second
  GitHub OAuth web login reusing the allowlist). Recommend whichever needs the
  least new secret handling; document it in `deploy/README.md`.
- How FastMCP serves the page (custom route or a small sibling app behind the
  same tunnel).
- Static diagram rendering library.
- Tests with recorded API fixtures; no live API calls in CI.
- Exact wording of tool descriptions (they must say that results are metadata
  only until full text is read).

## 11. Source-adapter layer (added 2026-11-21, Austin's request)

Before choosing which databases to add (CORE, BASE, etc.), Austin asked for the
structure that supports them. Each database is one adapter module in
`zotero_mcp/provenance/sources/` implementing a small contract (`search`,
`references`, `citations`, `lookup_doi`, `open_access`, as it can), enabled by
`ZOTERO_MCP_SOURCES` and its own API-key env vars. OpenAlex is the reference
adapter; others are added from `_template.py`. Every call is logged as a run;
results enter the log as Identified and are matched by database id, DOI, then
authors + year. Licensed or open-access indexes only. Guide: `docs/source-adapters.md`.

## 12. Library access ("discovery proxies", added 2026-11-21)

Austin reads through the UConn library with his own NetID login. Discovery now
ends in links he can click: `discover_access` takes log record ids or DOIs and
returns, best first, a legal open-access copy (from adapters with the
`open_access` capability: OpenAlex, CORE), the DOI through UConn's EZproxy, the
landing page through EZproxy, UConn's link resolver, and a Library Search query.

- Links open in Austin's own browser, where the UConn sign-in and Duo happen.
  The server never stores, asks for or automates library credentials, and
  never fetches through the proxy (that would put his NetID session on a
  server and breach the library's licence terms).
- `zotero_mcp/provenance/access.py` holds library profiles. `uconn` uses the
  proxy prefix and DOI form from UConn's stable-link guide (verified
  2026-11-21) and the Storrs Primo VE search address. The OpenURL address
  follows Ex Libris' standard pattern and is marked unverified until Austin
  clicks one.
- Opening a link records nothing. "Retrieved" is still recorded when Austin
  (or a confirmed suggestion) says the full text was obtained, with the route.
- CORE is the first added adapter (search, DOI lookup, open-access copy), with
  a free `CORE_API_KEY`.
