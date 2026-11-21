"""Provenance log for literature reviews: a PRISMA 2020-style record extended
through reading, coding and incorporation. Pure Python; the MCP tools that
wrap it live in :mod:`zotero_mcp.tools.provenance`."""

STAGES = ("identified", "duplicate", "screened", "retrieved", "read", "coded", "incorporated")
EVIDENCE = ("metadata", "abstract", "full_text", "page_derived", "quote_verified")
ACTORS = ("austin", "assistant_suggested_austin_confirmed", "assistant")
ROUTES = ("database", "citation", "other")
STRANDS = ("Canon", "Censorship", "Moral Panics", "Text Selection")
