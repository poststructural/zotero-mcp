"""Source-adapter layer: registry, env switch, OpenAlex mapping, ingest and tools.
No live HTTP: OpenAlex calls go through a patched requests.get."""

import json
from unittest.mock import MagicMock

import pytest
from conftest import DummyContext

from zotero_mcp.provenance import sources
from zotero_mcp.provenance.ingest import author_string, ingest
from zotero_mcp.provenance.sources import registry
from zotero_mcp.provenance.sources.base import SearchQuery, SourceAdapter, SourceRecord, SourceUnavailable
from zotero_mcp.provenance.sources.openalex import to_record
from zotero_mcp.provenance.store import ProvenanceStore
from zotero_mcp.tools import provenance as P
from zotero_mcp.utils import USER_AGENT

CTX = DummyContext()

WORK = {
    "id": "https://openalex.org/W4405831398",
    "doi": "https://doi.org/10.1000/POWDER",
    "title": "A powder keg for them",
    "publication_year": 2024,
    "type": "article",
    "cited_by_count": 3,
    "authorships": [{"author": {"display_name": 'Henry "Cody" Miller'}},
                    {"author": {"display_name": "Kathleen Colantonio-Yurko"}},
                    {"author": {"display_name": "Natalie Sue Svrcek"}}],
    "primary_location": {"source": {"display_name": "Example Journal"}},
    "open_access": {"is_oa": True, "oa_url": "https://example.org/pdf"},
    "abstract_inverted_index": {"Teachers": [0], "changed": [1]},
}


class FakeAdapter(SourceAdapter):
    name = "fakedb"
    label = "Fake DB"
    capabilities = frozenset({"search"})
    required_env = ("FAKEDB_KEY",)

    def search(self, query):
        if query.text == "boom":
            raise SourceUnavailable("fakedb: HTTP 503")
        return [SourceRecord(source="fakedb", source_id="F1", title="Tensions in Text Selection",
                             authors=["Brewer, A.", "Núñez, B."], year=2021)]


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(P.DB_ENV, str(tmp_path / "prov.db"))
    monkeypatch.setattr(P, "_store", None)
    monkeypatch.delenv(registry.SOURCES_ENV, raising=False)
    registry.register(FakeAdapter)
    yield
    registry.unregister("fakedb")


def test_openalex_is_registered_and_template_is_not():
    assert "openalex" in sources.registered()
    assert "example" not in sources.registered()


def test_register_rejects_bad_adapters():
    class Bad(SourceAdapter):
        name = "Bad-Name"
    with pytest.raises(ValueError):
        registry.register(Bad)

    class BadCap(SourceAdapter):
        name = "badcap"
        capabilities = frozenset({"teleport"})
    with pytest.raises(ValueError):
        registry.register(BadCap)


def test_missing_key_disables_adapter(monkeypatch):
    row = {r["name"]: r for r in registry.status()}["fakedb"]
    assert row["enabled"] is False and "FAKEDB_KEY" in row["status"]
    monkeypatch.setenv("FAKEDB_KEY", "x")
    assert {r["name"]: r for r in registry.status()}["fakedb"]["enabled"] is True


def test_env_switch_selects_adapters(monkeypatch):
    monkeypatch.setenv("FAKEDB_KEY", "x")
    monkeypatch.setenv(registry.SOURCES_ENV, "fakedb,nosuch")
    rows = {r["name"]: r for r in registry.status()}
    assert rows["fakedb"]["enabled"] and not rows["openalex"]["enabled"]
    assert rows["nosuch"]["status"] == "no such adapter"
    assert [a.name for a in registry.enabled("search")] == ["fakedb"]


def test_openalex_mapping():
    r = to_record(WORK)
    assert (r.source_id, r.doi, r.year, r.venue) == ("W4405831398", "10.1000/powder", 2024, "Example Journal")
    assert r.authors[0] == 'Henry "Cody" Miller' and r.first_author_surname() == "Miller"
    assert r.open_access_url == "https://example.org/pdf" and r.abstract == "Teachers changed"


def test_openalex_search_sends_user_agent_and_filters(monkeypatch):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"results": [WORK]}
    get = MagicMock(return_value=resp)
    monkeypatch.setattr("zotero_mcp.provenance.sources.http.requests.get", get)
    recs = sources.get("openalex").search(SearchQuery("text selection", year_from=2000, limit=5))
    assert recs[0].title == "A powder keg for them"
    kw = get.call_args.kwargs
    assert kw["headers"]["User-Agent"] == USER_AGENT
    assert kw["params"]["filter"] == "from_publication_date:2000-01-01"


def test_http_failure_raises_not_empty(monkeypatch):
    resp = MagicMock(status_code=403)
    monkeypatch.setattr("zotero_mcp.provenance.sources.http.requests.get", MagicMock(return_value=resp))
    with pytest.raises(SourceUnavailable):
        sources.get("openalex").search(SearchQuery("x"))


def test_author_string():
    assert author_string(['Henry "Cody" Miller']) == "Miller"
    assert author_string(["Brewer, A.", "Núñez, B."]) == "Brewer & Núñez"
    assert author_string(["A B", "C D", "E F"]) == "B et al."


def test_ingest_matches_prior_draft_and_source_id():
    s = ProvenanceStore(":memory:")
    prior = s.upsert_record(first_author="Brewer", year="2021", authors="Brewer & Núñez", retroactive=True)
    rec = FakeAdapter().search(SearchQuery("x"))
    run = s.start_run(kind="search", source="fakedb", query="x", strand="Text Selection")
    res = ingest(s, rec, strand="Text Selection", run_id=run, route="database")
    assert res.record_ids == [prior] and res.new == 0 and res.refound_prior == 1
    assert s.find_by_source("fakedb", "F1")["id"] == prior
    # Same run again: no duplicate event.
    ingest(s, rec, strand="Text Selection", run_id=run, route="database")
    assert len([e for e in s.events() if e["source_ref"] == f"run:{run}"]) == 1


def test_discover_search_tool_logs_runs_and_failures(monkeypatch):
    monkeypatch.setenv("FAKEDB_KEY", "x")
    out = P.discover_search("text selection", "Text Selection", sources=["fakedb"], ctx=CTX)
    assert "1 hits, 1 new" in out and "Tensions in Text Selection" in out
    fail = P.discover_search("boom", "Text Selection", sources=["fakedb"], ctx=CTX)
    assert "FAILED" in fail and "not a zero" in fail
    runs = P.get_store().runs()
    assert [r["hits"] for r in runs] == [1, None] and "503" in runs[1]["error"]
    assert json.loads(P.provenance_export("json", ctx=CTX))["runs"]


def test_discover_search_with_nothing_enabled(monkeypatch):
    monkeypatch.setenv(registry.SOURCES_ENV, "nosuch")
    assert P.discover_search("x", "Canon", ctx=CTX).startswith("Error")


def test_discover_citations_via_doi(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or {})))
        resp = MagicMock(status_code=200)
        if "/works/doi:" in url:
            resp.json.return_value = {**WORK, "referenced_works": []}
        else:
            resp.json.return_value = {"results": [{**WORK, "id": "https://openalex.org/W1", "doi": None,
                                                   "authorships": [{"author": {"display_name": "Ann Citer"}}]}]}
        return resp

    monkeypatch.setattr("zotero_mcp.provenance.sources.http.requests.get", fake_get)
    out = P.discover_citations("10.1000/powder", "Text Selection", direction="citations", ctx=CTX)
    assert "citations (run 1): 1 found, 1 new" in out
    assert any(p.get("filter") == "cites:W4405831398" for _, p in calls)
    run = P.get_store().runs()[0]
    assert run["kind"] == "citations" and run["query"] == "W4405831398"


def test_discover_sources_lists_access_terms():
    out = P.discover_sources(ctx=CTX)
    assert "OpenAlex" in out and "missing FAKEDB_KEY" in out
