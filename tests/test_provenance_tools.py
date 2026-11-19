import json

import pytest
from conftest import DummyContext

from zotero_mcp.provenance.citations import Citation
from zotero_mcp.tools import provenance as P

CTX = DummyContext()


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv(P.DB_ENV, str(tmp_path / "prov.db"))
    monkeypatch.setattr(P, "_store", None)
    yield


def _item(key, last, year, title="T"):
    return {"key": key, "data": {"key": key, "title": title, "date": f"{year}-01-01",
                                 "creators": [{"lastName": last, "creatorType": "author"}]}}


def test_match_items_filters_year_and_surname():
    items = [_item("AAAA1111", "Sewell", 2008), _item("BBBB2222", "Sewell", 2010), _item("CCCC3333", "Smith", 2008)]
    c = Citation("Sewell", "Sewell", "2008", "", False)
    assert [i["key"] for i in P._match_items(items, c)] == ["AAAA1111"]


def test_import_draft_matches_and_flags(monkeypatch):
    lib = {"Sewell": [_item("UJL4QLW5", "Sewell", 2008, "Entrenched pedagogy")],
           "Tremmel": []}
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: lib.get(c.first_author, []))
    text = "Sewell (2008) argues ... Tremmel (2006) compared standards."
    out = P.provenance_import_draft("Text Selection", "TS rev 11.18", "2026-11-18", text, ctx=CTX)
    assert "2 cited sources" in out and "Tremmel (2006)" in out and "[CHECK] 1" in out
    recs = {r["first_author"]: r for r in P.get_store().records()}
    assert recs["Sewell"]["zotero_key"] == "UJL4QLW5" and recs["Sewell"]["needs_check"] == 0
    assert recs["Tremmel"]["needs_check"] == 1 and recs["Tremmel"]["retroactive"] == 1


def test_import_draft_is_idempotent(monkeypatch):
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: [])
    for _ in range(2):
        P.provenance_import_draft("Canon", "v6", "2026-11-18", "Agee (1999) and Applebee (1974)", ctx=CTX)
    counts = json.loads(P.provenance_counts("Canon", ctx=CTX))
    assert counts["prior_total"] == 2 and counts["prior_incorporated"] == 2
    assert len(P.get_store().events("Canon")) == 4


def test_import_audit_links_keys_and_marks_read(monkeypatch):
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: [])
    P.provenance_import_draft("Text Selection", "TS", "2026-11-18", "Darragh & Boyd (2019)", ctx=CTX)
    log = ("## 2. Darragh & Boyd (2019): list\n\n2. Source: Darragh & Boyd. Zotero IPPRRA9L (PDF 8QSTB2ZV).\n"
           "5. Status: **verified**\n\n## 9. Nothing here\n\n5. Status: ok\n")
    out = P.provenance_import_audit("Text Selection", log, "log_textsel.md", ctx=CTX)
    assert "Nothing here" in out
    rec = P.get_store().records()[0]
    assert rec["zotero_key"] == "IPPRRA9L"
    counts = json.loads(P.provenance_counts("Text Selection", ctx=CTX))
    assert counts["prior_read"] == 1


def test_actor_rules():
    assert "Only Austin" in P.provenance_screen([1], "Canon", "keep", actor="austin", ctx=CTX)
    assert "confirming message" in P.provenance_screen(
        [1], "Canon", "keep", actor="assistant_suggested_austin_confirmed", ctx=CTX)


def test_full_text_needs_what_read(monkeypatch):
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: [])
    P.provenance_import_draft("Canon", "v6", "2026-11-18", "Agee (1999)", ctx=CTX)
    out = P.provenance_record_event(1, "Canon", "read", evidence="full_text", ctx=CTX)
    assert out.startswith("Error") and "what_read" in out
    ok = P.provenance_record_event(1, "Canon", "read", evidence="full_text", what_read="PDF M9EU96J3 pp. 1-20",
                                   reader="Austin", ctx=CTX)
    assert ok.startswith("Recorded read")


def test_screen_exclusion_needs_reason_and_trail_shows_confirmation(monkeypatch):
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: [])
    P.provenance_import_draft("Canon", "v6", "2026-11-18", "Agee (1999)", ctx=CTX)
    assert "needs a reason" in P.provenance_screen([1], "Canon", "exclude", ctx=CTX)
    P.provenance_screen([1], "Canon", "keep", actor="assistant_suggested_austin_confirmed",
                        confirmation="yes keep it", ctx=CTX)
    P.provenance_code(1, '{"genre": "Qualitative case or interview study"}', "full_text", ctx=CTX)
    trail = P.provenance_trail(1, ctx=CTX)
    assert "screened (keep" in trail and "assistant_suggested_austin_confirmed" in trail
    assert "genre: Qualitative case or interview study" in trail


def test_export_formats(monkeypatch):
    monkeypatch.setattr(P, "_zotero_candidates", lambda c: [])
    P.provenance_import_draft("Canon", "v6", "2026-11-18", "Agee (1999)", ctx=CTX)
    assert P.provenance_export("svg", "Canon", ctx=CTX).startswith("<svg")
    assert P.provenance_export("csv", ctx=CTX).startswith("event_id")
    assert json.loads(P.provenance_export("json", ctx=CTX))["records"]
    assert P.provenance_export("pdf", ctx=CTX).startswith("Error")
