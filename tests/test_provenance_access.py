"""Library access links (UConn EZproxy / resolver / catalog) and the CORE adapter.
No live HTTP: CORE calls go through a patched requests.get."""

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import DummyContext

from zotero_mcp.provenance import access, sources
from zotero_mcp.provenance.sources import registry
from zotero_mcp.provenance.sources.base import SearchQuery, SourceAdapter, SourceUnavailable
from zotero_mcp.provenance.sources.core import to_record as core_record
from zotero_mcp.tools import provenance as P

CTX = DummyContext()
UCONN = access.PROFILES["uconn"]

CORE_WORK = {
    "id": 12345,
    "title": "Walking a Fine Line",
    "doi": "https://doi.org/10.1000/FINE",
    "authors": [{"name": "Woo, Bryan"}, {"name": "Wolfe, Zachary"}, {"name": "Steiner, Elizabeth"}],
    "publishedDate": "2022-03-01T00:00:00",
    "journals": [{"title": "Example Review", "identifiers": []}],
    "publisher": "Example Press",
    "documentType": "research",
    "downloadUrl": "https://core.ac.uk/download/12345.pdf",
    "fullText": "very long text " * 1000,
}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(P.DB_ENV, str(tmp_path / "prov.db"))
    monkeypatch.setattr(P, "_store", None)
    for k in (access.LIBRARY_ENV, access.PROXY_ENV, access.OPENURL_ENV, access.SEARCH_ENV,
              registry.SOURCES_ENV, "CORE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


# -- library profile -----------------------------------------------------------


def test_no_library_configured_by_default():
    assert access.current_profile() is None


def test_uconn_profile_uses_verified_addresses(monkeypatch):
    monkeypatch.setenv(access.LIBRARY_ENV, "UConn")
    p = access.current_profile()
    assert p.proxy_prefix == "https://ezproxy.lib.uconn.edu/login?url="
    assert p.proxy_host == "ezproxy.lib.uconn.edu"
    assert p.search_url.startswith("https://uconn-storrs.primo.exlibrisgroup.com/discovery/search?vid=01UCT_STORRS:01UCT")
    assert "UNVERIFIED" in p.sources["openurl"] and p.sources["proxy"].startswith("verified")


def test_env_overrides_and_custom_library(monkeypatch):
    monkeypatch.setenv(access.PROXY_ENV, "https://proxy.example.edu/login?url=")
    monkeypatch.setenv(access.OPENURL_ENV, "https://resolver.example.edu/openurl")
    p = access.current_profile()
    assert p.name == "custom" and p.openurl_base == "https://resolver.example.edu/openurl?"
    assert p.sources["proxy"] == "set by environment"


# -- links ---------------------------------------------------------------------


def test_doi_link_matches_uconn_stable_link_form():
    links = access.access_links(UCONN, doi="https://doi.org/10.1000/ABC")
    by = {link.kind: link for link in links}
    assert by["library_doi"].url == "https://ezproxy.lib.uconn.edu/login?url=http://dx.doi.org/10.1000/abc"
    assert "subscribes" in by["library_doi"].note


def test_links_order_open_access_first_and_resolver_has_doi():
    links = access.access_links(UCONN, doi="10.1000/abc", title="A powder keg for them",
                                authors="Miller et al.", year="2024", open_access_url="https://example.org/pdf")
    assert [link.kind for link in links] == ["open_access", "library_doi", "resolver", "catalog"]
    q = parse_qs(urlsplit(links[2].url).query)
    assert q["rft_id"] == ["info:doi/10.1000/abc"] and q["rft.aulast"] == ["Miller"]
    assert q["institution"] == ["01UCT_STORRS"] and q["rft.date"] == ["2024"]
    assert "query=any,contains,A%20powder%20keg%20for%20them" in links[3].url


def test_without_library_only_oa_and_plain_doi():
    links = access.access_links(None, doi="10.1/x", open_access_url="https://oa.example/x.pdf")
    assert [(link.kind, link.url) for link in links] == [
        ("open_access", "https://oa.example/x.pdf"), ("doi", "https://doi.org/10.1/x")]


@pytest.mark.parametrize("url,expected", [
    ("https://muse.jhu.edu.ezproxy.lib.uconn.edu/book/24965", "https://muse.jhu.edu/book/24965"),
    ("https://www-jstor-org.ezproxy.lib.uconn.edu/stable/1", "https://www.jstor.org/stable/1"),
    ("https://ezproxy.lib.uconn.edu/login?url=https://example.org/a", "https://example.org/a"),
    ("https://example.org/a?b=1", "https://example.org/a?b=1"),
])
def test_never_proxies_twice(url, expected):
    assert access.unproxy(url, UCONN) == expected
    assert access.proxied(url, UCONN) == UCONN.proxy_prefix + expected


def test_landing_page_link_when_no_doi():
    links = access.access_links(UCONN, title="T", landing_url="https://muse.jhu.edu.ezproxy.lib.uconn.edu/book/1")
    assert links[0].kind == "library_page"
    assert links[0].url == "https://ezproxy.lib.uconn.edu/login?url=https://muse.jhu.edu/book/1"


# -- CORE adapter ----------------------------------------------------------------


def test_core_registered_and_needs_key(monkeypatch):
    row = {r["name"]: r for r in registry.status()}["core"]
    assert row["enabled"] is False and "CORE_API_KEY" in row["status"]
    monkeypatch.setenv("CORE_API_KEY", "k")
    assert {r["name"]: r for r in registry.status()}["core"]["enabled"] is True


def test_core_mapping():
    r = core_record(CORE_WORK)
    assert (r.source_id, r.doi, r.year, r.venue) == ("12345", "10.1000/fine", 2022, "Example Review")
    assert r.first_author_surname() == "Woo" and r.url == "https://core.ac.uk/works/12345"
    assert r.open_access_url == "https://core.ac.uk/download/12345.pdf"
    assert "fullText" not in r.raw


def _patch_core(monkeypatch, results):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"totalHits": len(results), "results": results}
    get = MagicMock(return_value=resp)
    monkeypatch.setattr("zotero_mcp.provenance.sources.http.requests.get", get)
    return get


def test_core_search_sends_bearer_key_and_year_filter(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "secret")
    old = {**CORE_WORK, "id": 1, "publishedDate": "1990-01-01"}
    get = _patch_core(monkeypatch, [CORE_WORK, old])
    monkeypatch.setattr(sources.get("core").__class__, "min_interval", 0.0)
    recs = sources.get("core").search(SearchQuery("text selection", year_from=2000, limit=5))
    assert [r.source_id for r in recs] == ["12345"]  # 1990 row dropped locally
    kw = get.call_args.kwargs
    assert kw["headers"]["Authorization"] == "Bearer secret"
    assert kw["params"]["q"] == "(text selection) AND yearPublished>=2000"


def test_core_doi_lookup_requires_exact_match(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "k")
    monkeypatch.setattr(sources.get("core").__class__, "min_interval", 0.0)
    _patch_core(monkeypatch, [{**CORE_WORK, "doi": "10.9/other"}])
    assert sources.get("core").lookup_doi("10.1000/fine") is None
    _patch_core(monkeypatch, [CORE_WORK])
    assert sources.get("core").open_access("https://doi.org/10.1000/FINE") == "https://core.ac.uk/download/12345.pdf"


# -- discover_access tool ----------------------------------------------------------


class OAOk(SourceAdapter):
    name = "oaok"
    label = "OA OK"
    capabilities = frozenset({"open_access"})

    def open_access(self, doi):
        return "https://repo.example/fine.pdf" if doi == "10.1000/fine" else None


class OADown(SourceAdapter):
    name = "oadown"
    label = "OA Down"
    capabilities = frozenset({"open_access"})

    def open_access(self, doi):
        raise SourceUnavailable("oadown: HTTP 503")


@pytest.fixture
def oa_adapters(monkeypatch):
    registry.register(OAOk)
    registry.register(OADown)
    monkeypatch.setenv(registry.SOURCES_ENV, "oaok,oadown")
    yield
    registry.unregister("oaok")
    registry.unregister("oadown")


def test_discover_access_for_record_and_doi(monkeypatch, oa_adapters):
    monkeypatch.setenv(access.LIBRARY_ENV, "uconn")
    rid = P.get_store().upsert_record(first_author="Woo", year="2022", authors="Woo et al.",
                                      title="Walking a Fine Line", doi="10.1000/fine")
    out = P.discover_access([str(rid), "10.2000/closed"], ctx=CTX)
    assert "UConn Library (Storrs)" in out
    assert "Open-access copy: https://repo.example/fine.pdf" in out
    assert "login?url=http://dx.doi.org/10.1000/fine" in out
    # The second DOI: OK adapter says none, the other failed; the failure is not reported as "no copy".
    closed = out.split("DOI 10.2000/closed")[1]
    assert "OA Down check failed" in closed and "not the same as 'no OA copy'" in closed
    assert "login?url=http://dx.doi.org/10.2000/closed" in closed


def test_discover_access_without_library(oa_adapters):
    out = P.discover_access(["10.1000/fine"], ctx=CTX)
    assert "no library configured" in out and "https://doi.org/10.1000/fine" in out


def test_discover_access_rejects_junk():
    out = P.discover_access(["hello", "999"], check_open_access=False, ctx=CTX)
    assert "not a record id or DOI" in out and "Error" in out.split("## 999")[1]
