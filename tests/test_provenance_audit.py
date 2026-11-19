from zotero_mcp.provenance.audit import parse_audit_log

TEXTSEL = """# Source audit log: Strand 4

## 1. Sewell (2008): span "1894-2008" in heading

1. Drafted: heading ...
2. Source: Sewell, W. C. (2008). Entrenched pedagogy... Zotero UJL4QLW5 (PDF 89LEIWKV).
4. Locator: pp. 87-91 (derived).
5. Status: **corrected** (span is the draft's, not Sewell's).

## 2. Darragh & Boyd (2019): list of influences

2. Source: Darragh & Boyd, Action in Teacher Education. Zotero IPPRRA9L (PDF 8QSTB2ZV).
5. Status: **verified** (list obtained).
"""

CANON = """## 3. Region of Stotsky, Anderson, & Beierl (1990)

2. Source: Stotsky, Anderson & Beierl (1990), "Variety and individualism", Zotero 8MUW2BD8.
3. What the source says: Not readable. The record has no attachment.
5. Status: not found in source.
"""

MORAL = """## PART A. The 12 [CHECK] items

### A5. CRT sentence: syllabus and community-college studies

2. Sources found in library: (a) American Oversight (2025), Zotero BDNINU82 (PDF 8XHWIZ6A); (b) Kisker & Romano (2025), Zotero DY2FTVXJ (PDF TCMXPRG3).
5. Status: partly verified.

### A9. A heading with no citation at all

5. Status: verified.
"""

CENSOR = """## 4. Hastie (2017), NSW Protestant schools

2. Source: Hastie, "Teacher and Institutional Self-Censorship", key KPMVSSNC. Metadata only: no PDF, no abstract in Zotero.
5. Status: metadata only (survey items: not found).
"""


def test_textsel_entries():
    entries, unparsed = parse_audit_log(TEXTSEL)
    assert unparsed == []
    sewell, darragh = entries
    assert [(c.authors, c.year) for c in sewell.citations] == [("Sewell", "2008")]
    assert sewell.zotero_keys == ["UJL4QLW5"] and sewell.pdf_keys == ["89LEIWKV"]
    assert sewell.evidence == "page_derived"
    assert sewell.status.startswith("corrected")
    assert darragh.evidence == "full_text"
    assert darragh.zotero_keys == ["IPPRRA9L"]


def test_no_attachment_is_metadata():
    (e,), _ = parse_audit_log(CANON)
    assert e.evidence == "metadata"
    assert e.citations[0].authors == "Stotsky, Anderson, & Beierl"


def test_two_sources_and_unparsed_heading():
    entries, unparsed = parse_audit_log(MORAL)
    assert len(entries) == 1
    (a5,) = entries
    assert a5.zotero_keys == ["BDNINU82", "DY2FTVXJ"]
    assert [c.authors for c in a5.citations] == ["American Oversight", "Kisker & Romano"]
    assert unparsed == ["A9. A heading with no citation at all"]


def test_key_word_and_metadata_only():
    (e,), _ = parse_audit_log(CENSOR)
    assert e.zotero_keys == ["KPMVSSNC"]
    assert e.evidence == "metadata"


def test_follow_up_entry_inherits_source():
    text = TEXTSEL + """
## 3. Darragh & Boyd: years of data collection

5. Status: **not found in source**.
"""
    entries, unparsed = parse_audit_log(text)
    assert unparsed == []
    assert entries[-1].citations[0].authors == "Darragh & Boyd"
    assert entries[-1].zotero_keys == ["IPPRRA9L"]
