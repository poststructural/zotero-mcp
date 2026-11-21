# Source adapters (discovery databases)

Discovery searches and citation dives run through small, pluggable adapters in
`src/zotero_mcp/provenance/sources/`. Each adapter wraps one scholarly index and
returns `SourceRecord`s (title, authors, year, venue, DOI, the index's own id,
open-access link when the API gives one). The `discover_*` tools put those
records into the provenance log, logging every request as a run, so each
"Identified" count on the chart traces back to the search that produced it.

Only licensed or open-access indexes belong here. Shadow libraries are out of
scope.

## What exists

| Adapter | Status | Can do |
|---|---|---|
| `openalex` | built in (reference implementation) | search, references, citations, DOI lookup, open-access link |

Run `discover_sources` to see what is enabled on a given server and why.

## Turning adapters on and off

- `ZOTERO_MCP_SOURCES` unset or `all`: every registered adapter whose
  requirements are met.
- `ZOTERO_MCP_SOURCES=openalex,core`: only those.
- An adapter with a missing key is listed as unavailable and skipped.
- `ZOTERO_MCP_CONTACT_EMAIL`: contact address sent to APIs that ask for one
  (OpenAlex polite pool, Crossref, Unpaywall). Austin chooses it; it is never
  hard-coded.

## Adding an adapter

1. Copy `sources/_template.py` to `sources/<name>.py`.
2. Set `name`, `label`, `capabilities` (any of `search`, `references`,
   `citations`, `lookup_doi`, `open_access`), `required_env`, `access_note`,
   `min_interval`.
3. Implement each listed capability with `http.get_json` (shared User-Agent,
   request spacing, retries; raises `SourceUnavailable` so a failure is never
   reported as zero results). Map only what the API returns.
4. Add the module to `_BUILTIN` in `sources/__init__.py`.
5. Add a test with a recorded response; CI makes no live calls.

## Candidates and what each needs

| Index | Access | Notes for the adapter |
|---|---|---|
| ERIC (IES) | free, no key | `api.ies.ed.gov/eric/`; ERIC ids (ED/EJ), peer-review and full-text flags. Most relevant to English education. |
| CORE | free API key | `api.core.ac.uk/v3`; open-access full texts from repositories; `CORE_API_KEY`. |
| BASE (Bielefeld) | access by request, IP allowlist | HTTP API is granted per IP after registration; the server's IP would need allowlisting. |
| Semantic Scholar | free; key optional, raises rate limit | citations and references, recommendations; `S2_API_KEY` optional. |
| Crossref | free; contact email | DOI metadata, reference lists where deposited. |
| Unpaywall | free; email required | open-access lookup by DOI only (`open_access` capability). |
| DOAJ | free | open-access journals and articles. |

## Zotero tags

Nothing in this layer writes to Zotero. If a later phase tags items (for
example a Discovery inbox), it uses the `prov:` prefix. Austin's Marginalia app
owns `theme:` and `ask:`.
