"""The contract every scholarly-database adapter implements.

An adapter turns one database's API into :class:`SourceRecord` objects. It
reports only what the API returned: no field is guessed or filled in, and a
missing value stays ``None``. Adapters never touch Zotero or the provenance
log; :mod:`zotero_mcp.provenance.ingest` does that.

To add a database, subclass :class:`SourceAdapter`, set the class attributes,
implement the methods named in ``capabilities``, and decorate the class with
:func:`zotero_mcp.provenance.sources.registry.register`. See
``docs/source-adapters.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, ClassVar

#: What an adapter can do. Tools check these before calling a method.
CAPABILITIES = frozenset({"search", "references", "citations", "lookup_doi", "open_access"})


@dataclass
class SourceRecord:
    """One work as a database describes it."""

    source: str  # adapter name, e.g. "openalex"
    source_id: str  # that database's own id, e.g. "W2922753666" or "ED382948"
    title: str | None = None
    authors: list[str] = field(default_factory=list)  # display names, in order
    year: int | None = None
    venue: str | None = None
    work_type: str | None = None
    doi: str | None = None  # bare, lower-case, no https://doi.org/
    url: str | None = None  # landing page in that database
    abstract: str | None = None
    open_access_url: str | None = None
    cited_by: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def first_author_surname(self) -> str:
        if not self.authors:
            return ""
        name = self.authors[0].replace('"', " ").replace("“", " ").replace("”", " ")
        if "," in name:  # "Surname, Given"
            return name.split(",")[0].strip()
        parts = name.split()
        return parts[-1] if parts else ""


@dataclass
class SearchQuery:
    text: str
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 25


class SourceUnavailable(RuntimeError):
    """The adapter cannot run here (missing key, host blocked, API down)."""


class SourceAdapter:
    """Base class. Subclasses set the ClassVars and implement their capabilities."""

    #: Short identifier used in env vars, run ids and tool arguments.
    name: ClassVar[str] = ""
    #: Human-readable name.
    label: ClassVar[str] = ""
    #: Subset of :data:`CAPABILITIES`.
    capabilities: ClassVar[frozenset[str]] = frozenset()
    #: Env vars that must be set for the adapter to run (e.g. an API key).
    required_env: ClassVar[tuple[str, ...]] = ()
    #: One line on access terms, shown by the listing tool.
    access_note: ClassVar[str] = ""
    #: Minimum seconds between requests to this API.
    min_interval: ClassVar[float] = 0.2

    def available(self) -> tuple[bool, str]:
        missing = [k for k in self.required_env if not os.environ.get(k)]
        if missing:
            return False, "missing " + ", ".join(missing)
        return True, "ready"

    # -- capabilities: override the ones listed in `capabilities` -----------
    def search(self, query: SearchQuery) -> list[SourceRecord]:
        raise NotImplementedError

    def references(self, source_id: str, limit: int = 25) -> list[SourceRecord]:
        raise NotImplementedError

    def citations(self, source_id: str, limit: int = 25) -> list[SourceRecord]:
        raise NotImplementedError

    def lookup_doi(self, doi: str) -> SourceRecord | None:
        raise NotImplementedError

    def open_access(self, doi: str) -> str | None:
        raise NotImplementedError
