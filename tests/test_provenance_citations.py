from zotero_mcp.provenance.citations import extract_citations


def keys(text):
    return [(c.authors, c.year) for c in extract_citations(text)]


def test_narrative_forms():
    text = (
        "Sewell (2008) asks how stasis became organizing. Sewell’s (2008) argument holds. "
        "Darragh and Boyd (2019) surveyed teachers; Greig & Holloway (2016) interviewed. "
        "Stallworth et al.’s (2006) survey and Tabron et al. (2024) followed."
    )
    assert keys(text) == [
        ("Sewell", "2008"),
        ("Darragh & Boyd", "2019"),
        ("Greig & Holloway", "2016"),
        ("Stallworth et al.", "2006"),
        ("Tabron et al.", "2024"),
    ]


def test_parenthetical_lists_and_pages():
    cs = extract_citations(
        "a de facto canon (Anderson, 1964; Applebee, 1989, 1992; Stotsky, 2010) and "
        "a “raw material” (Sewell, 2008, p. 90) or (see Lauter, 1991, pp. 3-4)."
    )
    assert [(c.authors, c.year, c.quoted) for c in cs] == [
        ("Anderson", "1964", False),
        ("Applebee", "1989", False),
        ("Applebee", "1992", False),
        ("Stotsky", "2010", False),
        ("Sewell", "2008", True),
        ("Lauter", "1991", True),
    ]


def test_three_authors_and_slash_years():
    assert keys("Stotsky, Anderson, & Beierl (1990) and Applebee (1989/1992)") == [
        ("Stotsky, Anderson, & Beierl", "1990"),
        ("Applebee", "1989"),
        ("Applebee", "1992"),
    ]


def test_case_names():
    cs = extract_citations("In Mahmoud v. Taylor (2025), the Court ...")
    assert [(c.authors, c.first_author) for c in cs] == [("Mahmoud v. Taylor", "Mahmoud v. Taylor")]


def test_bare_years_and_ranges_ignored():
    assert keys("Between 1982 and 1994 (1982-1994) the Committee of Ten report of 1894 mattered.") == []


def test_quote_page_on_narrative():
    (c,) = extract_citations("Graff (1993, p. 22) wrote")
    assert c.quoted is True


def test_unique_in_first_appearance_order():
    assert keys("Agee (1999) ... (Agee, 1999) ... Agee’s (1999)") == [("Agee", "1999")]


def test_html_entity_ampersand():
    assert keys("(Greig &amp; Holloway, 2016)") == [("Greig & Holloway", "2016")]


def test_comma_list_without_ampersand_is_separate_works():
    assert keys("in Anderson, Applebee (1989, 1992), Stotsky") == [("Applebee", "1989"), ("Applebee", "1992")]


def test_corporate_words_end_author_list():
    assert keys("at Stanford University and Bennett (1984) argued") == [("Bennett", "1984")]


def test_context_kept_for_checking():
    (c,) = extract_citations("the U.S. Department of Education (1987) report")
    assert "Department of Education (1987)" in c.context
