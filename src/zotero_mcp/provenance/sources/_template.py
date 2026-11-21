"""Copy this file to add a database. It is not imported, so it never registers.

Steps:
1. Copy to ``<name>.py`` in this folder and rename the class.
2. Set ``name`` (lower-case, used in ZOTERO_MCP_SOURCES and run ids), ``label``,
   ``capabilities``, ``required_env`` (API keys) and ``access_note``.
3. Implement each method listed in ``capabilities``. Map only fields the API
   returns; leave the rest ``None``. Use ``http.get_json`` (one User-Agent,
   spacing, retries; raises SourceUnavailable on failure).
4. Add the module name to ``_BUILTIN`` in ``sources/__init__.py``.
5. Add a test with a recorded response under ``tests/`` (no live calls).
"""

from __future__ import annotations

import os

from zotero_mcp.provenance.sources import http
from zotero_mcp.provenance.sources.base import SearchQuery, SourceAdapter, SourceRecord
from zotero_mcp.provenance.sources.registry import register


@register
class ExampleAdapter(SourceAdapter):
    name = "example"
    label = "Example Index"
    capabilities = frozenset({"search"})
    required_env = ("EXAMPLE_API_KEY",)
    access_note = "Free key from example.org; 10 requests/second."
    min_interval = 0.1

    def search(self, query: SearchQuery) -> list[SourceRecord]:
        data = http.get_json(
            "https://api.example.org/search",
            params={"q": query.text, "limit": query.limit},
            headers={"Authorization": f"Bearer {os.environ['EXAMPLE_API_KEY']}"},
            key=self.name, min_interval=self.min_interval,
        )
        return [
            SourceRecord(source=self.name, source_id=str(hit["id"]), title=hit.get("title"),
                         authors=hit.get("authors") or [], year=hit.get("year"), doi=hit.get("doi"))
            for hit in data.get("results", [])
        ]
