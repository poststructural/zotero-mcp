"""Pluggable scholarly-database adapters for discovery.

Importing this package registers the built-in adapters listed in ``_BUILTIN``.
Each is one module; see ``base.py`` for the contract and ``_template.py`` for a
starting point. Only licensed or open-access indexes belong here.
"""

from importlib import import_module

from zotero_mcp.provenance.sources.base import (  # noqa: F401
    CAPABILITIES,
    SearchQuery,
    SourceAdapter,
    SourceRecord,
    SourceUnavailable,
)
from zotero_mcp.provenance.sources.registry import enabled, get, register, registered, status  # noqa: F401

#: Built-in adapter modules, imported for their @register side effect.
_BUILTIN = ("openalex", "core")

for _mod in _BUILTIN:
    import_module(f"zotero_mcp.provenance.sources.{_mod}")
