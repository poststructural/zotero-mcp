"""Registry of source adapters and the env switch that enables them.

``ZOTERO_MCP_SOURCES`` picks the enabled adapters: unset or ``all`` means
every registered adapter whose requirements are met; otherwise a comma list
such as ``openalex,core``. Adapters that are enabled but unavailable (say, a
missing API key) are listed with the reason and skipped.
"""

from __future__ import annotations

import os

from zotero_mcp.provenance.sources.base import CAPABILITIES, SourceAdapter

SOURCES_ENV = "ZOTERO_MCP_SOURCES"

_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    if not cls.name or not cls.name.isidentifier() or cls.name != cls.name.lower():
        raise ValueError(f"Adapter name must be a lower-case identifier, got {cls.name!r}")
    unknown = set(cls.capabilities) - CAPABILITIES
    if unknown:
        raise ValueError(f"{cls.name}: unknown capabilities {sorted(unknown)}")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"Adapter {cls.name!r} is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def unregister(name: str) -> None:
    """For tests."""
    _REGISTRY.pop(name, None)


def registered() -> dict[str, type[SourceAdapter]]:
    return dict(_REGISTRY)


def _wanted() -> set[str] | None:
    raw = os.environ.get(SOURCES_ENV, "").strip().lower()
    if not raw or raw == "all":
        return None
    return {t for t in raw.replace(",", " ").split() if t}


def status() -> list[dict]:
    """Every registered adapter with whether it is enabled and why not."""
    wanted = _wanted()
    rows = []
    for name, cls in sorted(_REGISTRY.items()):
        ok, why = cls().available()
        enabled = (wanted is None or name in wanted) and ok
        if wanted is not None and name not in wanted:
            why = f"not in {SOURCES_ENV}"
        rows.append({"name": name, "label": cls.label, "enabled": enabled, "status": why,
                     "capabilities": sorted(cls.capabilities), "access": cls.access_note})
    if wanted:
        for name in sorted(wanted - set(_REGISTRY)):
            rows.append({"name": name, "label": "", "enabled": False, "status": "no such adapter",
                         "capabilities": [], "access": ""})
    return rows


def get(name: str) -> SourceAdapter:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"No source adapter {name!r}; registered: {', '.join(sorted(_REGISTRY))}")
    return cls()


def enabled(capability: str | None = None, names: list[str] | None = None) -> list[SourceAdapter]:
    """Enabled, available adapters, optionally filtered to a capability or names."""
    out = []
    allowed = {r["name"] for r in status() if r["enabled"]}
    for name in sorted(allowed):
        if names and name not in names:
            continue
        cls = _REGISTRY[name]
        if capability and capability not in cls.capabilities:
            continue
        out.append(cls())
    return out
