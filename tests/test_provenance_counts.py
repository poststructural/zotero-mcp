import csv
import io
import json

import pytest

from zotero_mcp.provenance.counts import compute_counts
from zotero_mcp.provenance.export import to_csv, to_json, to_svg
from zotero_mcp.provenance.store import ProvenanceStore


@pytest.fixture
def store():
    s = ProvenanceStore(":memory:")
    # Before-logging lane: two draft sources in Canon, one also in Text Selection.
    a = s.upsert_record(first_author="Applebee", year="1974", authors="Applebee", retroactive=True)
    t = s.upsert_record(first_author="Stotsky", year="2010", authors="Stotsky", retroactive=True)
    for r in (a, t):
        s.add_event(r, strand="Canon", stage="identified", route="other", source_ref="draft:v6")
        s.add_event(r, strand="Canon", stage="incorporated", source_ref="draft:v6")
    s.add_event(a, strand="Canon", stage="read", evidence="full_text")
    s.add_event(t, strand="Text Selection", stage="identified", route="other", source_ref="draft:ts")
    s.add_event(t, strand="Text Selection", stage="incorporated", source_ref="draft:ts")
    # Logged flow in Canon: one database hit screened out, one citation find read and coded.
    x = s.upsert_record(first_author="Example", year="2020", authors="Example")
    s.add_event(x, strand="Canon", stage="identified", route="database")
    s.add_event(x, strand="Canon", stage="screened", decision="exclude", reason="Not secondary")
    y = s.upsert_record(first_author="Tanner", year="1907", authors="Tanner")
    s.add_event(y, strand="Canon", stage="identified", route="citation")
    s.add_event(y, strand="Canon", stage="screened")
    s.add_event(y, strand="Canon", stage="retrieved", evidence="full_text")
    s.add_event(y, strand="Canon", stage="read", evidence="full_text")
    s.add_code(y, field="genre", value="Survey of assigned reading", evidence="full_text")
    return s


def test_empty_store_is_all_zero():
    c = compute_counts(ProvenanceStore(":memory:"))
    assert c["identified_db"] == 0 and c["prior_total"] == 0 and c["incorporated"] == 0


def test_canon_counts(store):
    c = compute_counts(store, "Canon")
    assert (c["identified_db"], c["identified_citation"], c["identified_other"]) == (1, 1, 0)
    assert c["screened_out"] == 1
    assert c["read"] == 1 and c["coded"] == 1 and c["coded_not_cited"] == 1
    assert c["incorporated"] == 0
    assert (c["prior_total"], c["prior_read"], c["prior_incorporated"]) == (2, 1, 2)
    assert c["screened_out_reasons"] == {"Not secondary": 1}


def test_all_strands_counts_unique_records(store):
    c = compute_counts(store)
    assert c["prior_total"] == 2  # Stotsky counted once despite two strands
    assert c["strands"]["Canon"] == 2 and c["strands"]["Text Selection"] == 1


def test_latest_event_wins(store):
    x = store.find("Example", "2020")[0]["id"]
    store.add_event(x, strand="Canon", stage="screened", decision="keep", note="re-screened")
    assert compute_counts(store, "Canon")["screened_out"] == 0


def test_exports(store):
    rows = list(csv.DictReader(io.StringIO(to_csv(store))))
    assert {"record_id", "authors", "year", "strand", "stage", "evidence", "actor"} <= set(rows[0])
    data = json.loads(to_json(store))
    assert len(data["records"]) == 4 and data["codes"][0]["field"] == "genre"
    svg = to_svg(compute_counts(store, "Canon"), "Canon")
    assert svg.startswith("<svg") and "Before logging" in svg and "Records identified" in svg


def test_svg_with_zeros():
    assert "<svg" in to_svg(compute_counts(ProvenanceStore(":memory:")), "All strands")
