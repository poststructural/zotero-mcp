import pytest

from zotero_mcp.provenance.store import ProvenanceStore


@pytest.fixture
def store():
    return ProvenanceStore(":memory:")


def test_upsert_dedupes_by_author_year(store):
    a = store.upsert_record(first_author="Sewell", year="2008", authors="Sewell")
    b = store.upsert_record(first_author="sewell", year="2008", authors="Sewell", title="Entrenched pedagogy")
    assert a == b
    assert store.record(a)["title"] == "Entrenched pedagogy"


def test_upsert_prefers_zotero_key(store):
    a = store.upsert_record(first_author="Darragh", year="2019", authors="Darragh & Boyd", zotero_key="IPPRRA9L")
    b = store.upsert_record(first_author="Darragh", year="2018", authors="Darragh & Boyd", zotero_key="IPPRRA9L")
    assert a == b
    assert store.record(a)["year"] == "2019"  # existing non-empty fields are kept


def test_same_surname_different_coauthors_are_distinct(store):
    a = store.upsert_record(first_author="Stotsky", year="1990", authors="Stotsky")
    b = store.upsert_record(first_author="Stotsky", year="1990", authors="Stotsky et al.")
    assert a != b


def test_dedupe_key_makes_events_idempotent(store):
    r = store.upsert_record(first_author="Tanner", year="1907", authors="Tanner")
    first = store.add_event(r, strand="Canon", stage="incorporated", dedupe_key="draft:Canon:v6:1")
    again = store.add_event(r, strand="Canon", stage="incorporated", dedupe_key="draft:Canon:v6:1")
    assert first is not None and again is None
    assert len(store.events("Canon")) == 1


@pytest.mark.parametrize("kw", [{"stage": "skimmed"}, {"evidence": "vibes"}, {"actor": "someone"}])
def test_invalid_values_raise(store, kw):
    r = store.upsert_record(first_author="Agee", year="1999", authors="Agee")
    args = {"strand": "Canon", "stage": "read"} | kw
    with pytest.raises(ValueError):
        store.add_event(r, **args)


def test_trail_is_time_ordered_with_codes(store):
    r = store.upsert_record(first_author="Applebee", year="1974", authors="Applebee")
    store.add_event(r, strand="Canon", stage="identified", route="other")
    store.add_event(r, strand="Canon", stage="read", evidence="full_text")
    store.add_code(r, field="genre", value="Historical analysis", evidence="full_text")
    t = store.trail(r)
    assert [e["stage"] for e in t["events"]] == ["identified", "read"]
    assert t["codes"][0]["value"] == "Historical analysis"


def test_persists_to_file(tmp_path):
    p = tmp_path / "p.db"
    s = ProvenanceStore(p)
    s.upsert_record(first_author="Rios", year="2024", authors="Rios")
    s.close()
    assert len(ProvenanceStore(p).records()) == 1
