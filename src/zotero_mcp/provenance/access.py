"""Library access: "open via my library" links for discovered sources.

Discovery adapters find works; this module turns a work into the links Austin
can click to read it, in order of preference:

1. a legal open-access copy, when an adapter reports one;
2. the DOI through the library's EZproxy (publisher page, signed in);
3. the source's landing page through EZproxy;
4. the library's link resolver (OpenURL), which finds whichever licensed
   platform holds the full text;
5. a library catalog search by title, as a last resort.

The links open in the reader's own browser, where the library sign-in happens.
Nothing here stores, asks for or automates library credentials, and nothing
fetches through the proxy. Shadow libraries are out of scope.

A library is a :class:`LibraryProfile`. ``ZOTERO_MCP_LIBRARY`` picks a built-in
profile by name (``uconn``); ``ZOTERO_MCP_LIBRARY_PROXY``,
``ZOTERO_MCP_LIBRARY_OPENURL`` and ``ZOTERO_MCP_LIBRARY_SEARCH`` override or
supply its parts, so any EZproxy/OpenURL library can be configured.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

LIBRARY_ENV = "ZOTERO_MCP_LIBRARY"
PROXY_ENV = "ZOTERO_MCP_LIBRARY_PROXY"
OPENURL_ENV = "ZOTERO_MCP_LIBRARY_OPENURL"
SEARCH_ENV = "ZOTERO_MCP_LIBRARY_SEARCH"


@dataclass(frozen=True)
class LibraryProfile:
    name: str
    label: str
    #: EZproxy starting-point prefix; the target URL is appended as is.
    proxy_prefix: str = ""
    #: DOI base the library's own stable-link guide uses after the prefix.
    doi_base: str = "https://doi.org/"
    #: OpenURL resolver base, ending in "?" or "&", to which KEV pairs are appended.
    openurl_base: str = ""
    #: Catalog search URL with a ``{q}`` placeholder for the URL-encoded title.
    search_url: str = ""
    #: Per-part notes on where each address came from.
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def proxy_host(self) -> str:
        """The proxy's host, e.g. ``ezproxy.lib.uconn.edu`` (login host minus ``login.``)."""
        host = urlsplit(self.proxy_prefix).hostname or ""
        return host[6:] if host.startswith("login.") else host


_UCONN_GUIDE = "guides.lib.uconn.edu/stablelinks/other (checked 2026-11-21)"
_UCONN_PRIMO = "https://uconn-storrs.primo.exlibrisgroup.com/discovery"
_UCONN_VID = "01UCT_STORRS:01UCT"

PROFILES: dict[str, LibraryProfile] = {
    "uconn": LibraryProfile(
        name="uconn",
        label="UConn Library (Storrs)",
        proxy_prefix="https://ezproxy.lib.uconn.edu/login?url=",
        doi_base="http://dx.doi.org/",
        openurl_base=f"{_UCONN_PRIMO}/openurl?institution=01UCT_STORRS&vid={_UCONN_VID}&",
        search_url=f"{_UCONN_PRIMO}/search?vid={_UCONN_VID}&query=any,contains,{{q}}",
        sources={
            "proxy": f"verified: {_UCONN_GUIDE}; DOI form and 'subscribed content only' from the same page",
            "search": "verified base (library.uconn.edu off-campus page); query syntax is Primo VE's standard",
            "openurl": ("UNVERIFIED: built from Ex Libris' Primo VE OpenURL pattern and UConn's vid; "
                        "use 'Find by citation' in Library Search if it misbehaves"),
        },
    ),
}


def current_profile() -> LibraryProfile | None:
    """The configured library, or None when no library is set up."""
    name = os.environ.get(LIBRARY_ENV, "").strip().lower()
    base = PROFILES.get(name) if name else None
    if name and base is None:
        base = LibraryProfile(name=name, label=name)
    proxy, openurl, search = (os.environ.get(k, "").strip() for k in (PROXY_ENV, OPENURL_ENV, SEARCH_ENV))
    if base is None and not (proxy or openurl or search):
        return None
    base = base or LibraryProfile(name="custom", label="Library")
    over = {}
    if proxy:
        over["proxy_prefix"] = proxy
    if openurl:
        over["openurl_base"] = openurl if openurl.endswith(("?", "&")) else openurl + ("&" if "?" in openurl else "?")
    if search:
        over["search_url"] = search
    if over:
        notes = dict(base.sources)
        for part in ("proxy", "openurl", "search"):
            if f"{part}_prefix" in over or f"{part}_base" in over or f"{part}_url" in over:
                notes[part] = "set by environment"
        over["sources"] = notes
    return replace(base, **over)


# -- building links -----------------------------------------------------------


def unproxy(url: str, profile: LibraryProfile) -> str:
    """Remove a proxy the URL already carries, so links are never proxied twice.

    Handles the starting-point form (``…/login?url=<target>``) and the rewritten
    host form (``muse.jhu.edu.ezproxy.lib.uconn.edu`` → ``muse.jhu.edu``), which
    the UConn guide says to strip before adding the prefix.
    """
    u = url.strip()
    if profile.proxy_prefix and u.startswith(profile.proxy_prefix):
        u = u[len(profile.proxy_prefix):]
    host = profile.proxy_host
    if not host:
        return u
    parts = urlsplit(u)
    netloc = parts.netloc
    suffix = "." + host
    hostname = parts.hostname or ""
    if hostname.endswith(suffix):
        real = hostname[: -len(suffix)]
        # EZproxy turns dots inside a hyphenated host into hyphens on some setups
        # ("www-jstor-org.ezproxy…"); only undo that when no dot is left.
        if "." not in real and "-" in real:
            real = real.replace("-", ".")
        netloc = netloc.replace(hostname, real, 1)
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return u


def proxied(url: str, profile: LibraryProfile) -> str | None:
    if not profile.proxy_prefix or not url:
        return None
    return profile.proxy_prefix + unproxy(url, profile)


def bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip()
    d = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", d, flags=re.I)
    return d.lower() or None


def openurl(profile: LibraryProfile, *, doi: str | None = None, title: str | None = None,
            authors: str | None = None, year: str | int | None = None, venue: str | None = None) -> str | None:
    """OpenURL 1.0 (KEV) link to the library's resolver. Needs a DOI or a title."""
    if not profile.openurl_base or not (doi or title):
        return None
    kev: list[tuple[str, str]] = [("url_ver", "Z39.88-2004"), ("ctx_ver", "Z39.88-2004"),
                                  ("rft_val_fmt", "info:ofi/fmt:kev:mtx:journal"),
                                  ("rfr_id", "info:sid/zotero-mcp")]
    d = bare_doi(doi)
    if d:
        kev.append(("rft_id", f"info:doi/{d}"))
    if title:
        kev.append(("rft.atitle", title))
    if venue:
        kev.append(("rft.jtitle", venue))
    if authors:
        first = authors.split(" & ")[0].replace(" et al.", "").strip()
        if first and first != "Unknown":
            kev.append(("rft.aulast", first))
    if year and str(year) not in ("", "n.d."):
        kev.append(("rft.date", str(year)))
    return profile.openurl_base + urlencode(kev)


@dataclass
class AccessLink:
    kind: str  # open_access | library_doi | library_page | resolver | catalog
    label: str
    url: str
    note: str = ""


def access_links(profile: LibraryProfile | None, *, doi: str | None = None, title: str | None = None,
                 authors: str | None = None, year: str | int | None = None, venue: str | None = None,
                 landing_url: str | None = None, open_access_url: str | None = None) -> list[AccessLink]:
    """Every way to open one work, best first. Works without a library profile
    (then only the open-access copy and the plain DOI are offered)."""
    links: list[AccessLink] = []
    if open_access_url:
        links.append(AccessLink("open_access", "Open-access copy", open_access_url,
                                "legal OA location reported by the index"))
    d = bare_doi(doi)
    if profile is None:
        if d:
            links.append(AccessLink("doi", "Publisher page (DOI)", f"https://doi.org/{d}",
                                    "no library configured; set ZOTERO_MCP_LIBRARY"))
        return links
    lib = profile.label
    if d and profile.proxy_prefix:
        links.append(AccessLink("library_doi", f"Publisher page via {lib}",
                                profile.proxy_prefix + profile.doi_base + d,
                                "full text if the library subscribes; otherwise usually the abstract"))
    if landing_url and profile.proxy_prefix and not (d and "doi.org/" in landing_url.lower()):
        p = proxied(landing_url, profile)
        if p:
            links.append(AccessLink("library_page", f"Landing page via {lib}", p))
    r = openurl(profile, doi=d, title=title, authors=authors, year=year, venue=venue)
    if r:
        links.append(AccessLink("resolver", f"{lib} link resolver", r, profile.sources.get("openurl", "")))
    if title and profile.search_url:
        links.append(AccessLink("catalog", f"Search {lib}",
                                profile.search_url.replace("{q}", quote(title[:200], safe="")),
                                "catalog search by title"))
    return links
