#!/usr/bin/env python3
"""Quote and page verifier: every direct quotation in the strands, checked against the cited source's PDF.

  python quote_check.py [--strand NAME] [--no-share]     (verify_quotes.py is an alias)

For each quotation (4+ words inside quotation marks) it finds the citation that governs it (a parenthetical
right after the quote, else the nearest earlier citation in the paragraph, else in the two paragraphs before),
resolves it to a Zotero item, downloads that item's PDF (GET only, cached), and searches the PDF text.
Printed page numbers come from running headers/footers when they can be inferred; otherwise the PDF's own
page label is reported and marked as such. Nothing in the strands is changed.
"""
import argparse, datetime as dt, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sr_common as c
from rapidfuzz import fuzz

QUOTE = re.compile(r"[“\"]([^”\"]{12,}?)[”\"]")
ELLIPSIS = re.compile(r"\s*(?:\.\s?\.\s?\.|…|\[[^\]]*\])\s*")


def fragments(q):
    return [f for f in (norm_f.strip() for norm_f in ELLIPSIS.split(q)) if len(c.norm(f).split()) >= 3]


def governing(paras, pi, q_start, q_end):
    """Citations that may govern a quote: parenthetical just after, then nearest earlier in paragraph, then earlier paragraphs."""
    t = paras[pi]["text"]; cs = c.citations(t); out = []
    m = re.search(r"[.!?](?=\s+[A-Z]|$)", t[q_end:])
    sent_end = q_end + (m.end() if m else len(t) - q_end)
    after = [x for x in cs if q_end <= x[3] <= sent_end]
    out += after
    before = sorted([x for x in cs if x[4] <= q_start], key=lambda x: q_start - x[4])
    out += before
    later = [x for x in cs if x[3] > sent_end]
    for back in (1, 2):
        if pi - back >= 0: out += list(reversed(c.citations(paras[pi - back]["text"])))
    out += later
    seen, uniq = set(), []
    for x in out:
        k = (x[0], x[1])
        if k not in seen: seen.add(k); uniq.append(x)
    return uniq, (after[0][2] if after and after[0][2] else None)


def page_after(t, q_end):
    """First page locator after the quote and before the next quotation or the end of the sentence."""
    m = re.search(r"[.!?](?=\s+[A-Z“\"]|$)", t[q_end:])
    end = q_end + (m.end() if m else len(t) - q_end)
    nq = QUOTE.search(t, q_end)
    if nq and nq.start() < end: end = nq.start()
    for pm in re.finditer(r"\(([^()]{0,120})\)", t[q_end:end]):
        pg = c.PAGE.search(pm.group(1))
        if pg: return pg.group(1)
    return None


def search(pages, frag):
    """Best match of a fragment in (index, printed, text) pages: (score, printed_page, snippet, all exact pages)."""
    nf = c.norm(frag)
    best = (0, None, "", [])
    exact = []
    for k, (i, printed, text) in enumerate(pages):
        # include the start of the next page so quotes that cross a page break are found
        nxt = c.norm(pages[k + 1][2][:600]) if k + 1 < len(pages) else ""
        here = c.norm(text); nt = here + " " + nxt
        if nf in here:
            exact.append(printed); continue
        if nf in nt:
            exact.append(f"{printed}-{pages[k + 1][1]}" if k + 1 < len(pages) else printed); continue
        if exact or len(nt) < len(nf): continue
        al = fuzz.partial_ratio_alignment(nf, nt, score_cutoff=best[0])
        if al and al.score > best[0]:
            best = (al.score, printed, nt[al.dest_start:al.dest_end], [])
    if exact: return (100, exact[0], frag, exact)
    return best


def page_eq(cited, found):
    if not cited or not found: return False
    found = str(found)
    if re.fullmatch(r"\d+-\d+", found):   # quote crossing a page break
        a, b = found.split("-"); return any(page_eq(cited, x) for x in (a, b)) or page_eq(found, cited.split("-")[0])
    if found.startswith("pdf ") and re.fullmatch(r"[ivxlcdm]+", found[4:], re.I): found = found[4:]   # roman front-matter label
    cited = cited.replace("–", "-")
    if "-" in cited:
        a, b = cited.split("-", 1)
        try:
            a, b = int(a), int(b)
            if b < a: b = int(str(a)[:len(str(a)) - len(str(b))] + str(b))
            return a <= int(found) <= b
        except ValueError: return False
    return cited.strip().lower() == str(found).strip().lower()


def check_strand(con, name, stem, cache):
    paras = c.strand_paras(stem); rows = []
    for pi, p in enumerate(paras):
        t = p["text"]
        for m in QUOTE.finditer(t):
            q = m.group(1).strip()
            if len(c.norm(q).split()) < 4: continue
            if re.search(r"\(\s*(?:1[6-9]|20)\d{2}", q) or len(q.split()) > 70: continue   # mispaired quotation marks
            cands, _ = governing(paras, pi, m.start(), m.end())
            cited_page = page_after(t, m.end())
            row = {"strand": name, "para": p["i"], "opening": c.opening(t), "quote": q, "cited_page": cited_page,
                   "cite": None, "item": None, "status": None, "found_page": None, "score": None, "source_text": None,
                   "page_note": "", "alternatives": []}
            frs = fragments(q) or [q]
            tried = []
            # drop candidate names that don't resolve when another candidate for the same year does
            for sn, yr, pg, _, _ in cands[:24]:
                items = c.resolve(con, sn, yr)
                if not items and any(c.resolve(con, s2, y2) for s2, y2, *_ in cands[:24] if y2 == yr and s2 != sn): continue
                label = f"{' & '.join(x for x in sn if x not in c.INSTITUTION) or ' '.join(sn)} ({yr})"
                if len([t for t in tried if len(t) > 2]) >= 4: break
                if not items: tried.append((label, "not in library")); continue
                for it in items[:3]:
                    if it["key"] not in cache: cache[it["key"]] = c.pdf_pages(it)
                    pages = cache[it["key"]]
                    if not pages:
                        texts = [(r["page_label"], r["text"]) for r in con.execute("SELECT page_label,text FROM paras WHERE item_key=? ORDER BY seq", (it["key"],))]
                        pages = [(k, lab, tx) for k, (lab, tx) in enumerate(texts)]
                        src_note = "no PDF; matched against Zotero's extracted text, page labels unreliable"
                    else: src_note = ""
                    res = [search(pages, f) for f in frs]
                    score = min(r[0] for r in res) if res else 0
                    tried.append((label, it, score, res, src_note, pg))
            hits = [x for x in tried if len(x) > 2]
            # the nearest citation governs unless a farther one matches the wording exactly
            if tried and len(tried[0]) == 2 and not any(x[2] >= 97 for x in hits): hits = []
            elif hits and not any(x[2] >= 97 for x in hits): hits = [x for x in hits if x[0] == hits[0][0]]
            if not hits:
                row["status"] = "SOURCE NOT IN LIBRARY" if tried else "NO CITATION FOUND"
                row["cite"] = tried[0][0] if tried else None
                rows.append(row); continue
            label, it, score, res, src_note, pg = max(hits, key=lambda x: x[2])
            row["checked"] = sorted(set(x[0] for x in tried))
            row.update(cite=label, item=c.cite_label(it), score=round(score), page_note=src_note,
                       found_page=res[0][1] if res else None,
                       source_text=" … ".join(r[2] for r in res if r[0] < 100) or None)
            cited_page = cited_page or pg
            row["cited_page"] = cited_page
            allp = [x for r in res for x in r[3]] or [row["found_page"]]
            row["all_pages"] = sorted(set(str(x) for x in allp if x))
            hit = next((x for x in allp if page_eq(cited_page, str(x).rstrip("~"))), None)
            roman_ok = hit is not None and str(hit).startswith("pdf ")
            if hit: row["found_page"] = hit
            if any(str(x).startswith("pdf ") for x in allp):
                row["page_note"] = (row["page_note"] + "; " if row["page_note"] else "") + "printed page numbers not detected in this PDF; 'pdf N' is the PDF's page, not the journal page"
            elif any(str(x).endswith("~") for x in allp):
                row["page_note"] = (row["page_note"] + "; " if row["page_note"] else "") + "page (~) inferred from the Zotero page range, not printed in the PDF text; confirm by eye"
            if score >= 97:
                if not cited_page: row["status"] = "FOUND - NO PAGE GIVEN"
                elif hit:
                    row["status"] = "VERIFIED"
                    if roman_ok: row["page_note"] = "front-matter page matched by the PDF's roman page label"
                elif any(str(x).startswith("pdf ") for x in allp): row["status"] = "FOUND - PAGE UNCONFIRMED"
                else: row["status"] = "PAGE DIFFERS"
            elif score >= 72: row["status"] = "WORDING DIFFERS"
            else: row["status"] = "NOT FOUND IN CITED SOURCE"
            rows.append(row)
    return rows


ORDER = ["NOT FOUND IN CITED SOURCE", "WORDING DIFFERS", "PAGE DIFFERS", "FOUND - PAGE UNCONFIRMED", "FOUND - NO PAGE GIVEN", "SOURCE NOT IN LIBRARY", "NO CITATION FOUND", "VERIFIED"]
EXPLAIN = {
    "VERIFIED": "wording matches the PDF and the cited page matches the printed page",
    "PAGE DIFFERS": "wording matches, but the PDF has it on a different page",
    "FOUND - NO PAGE GIVEN": "wording matches; add the page",
    "FOUND - PAGE UNCONFIRMED": "wording matches, but this PDF has no readable page numbers; check the page by eye",
    "WORDING DIFFERS": "close but not exact; compare with the source wording shown",
    "NOT FOUND IN CITED SOURCE": "no close match in the cited source's PDF (wrong source, a quotation of a quotation, or a scan problem)",
    "SOURCE NOT IN LIBRARY": "the cited author/year isn't in your Zotero (or has no PDF)",
    "NO CITATION FOUND": "no citation near the quote to check against",
}


def write(rows, stamp):
    os.makedirs(c.OUT, exist_ok=True); os.makedirs(c.SHARE, exist_ok=True)
    js = os.path.join(c.OUT, "quote_check_all_strands.json")
    json.dump(rows, open(js, "w"), indent=1, ensure_ascii=False)
    from collections import Counter
    md = [f"# Quotation and page check ({stamp})", "",
          "Every direct quotation (4+ words) in the strands, checked against the PDF of the source it cites, from your Zotero. "
          "Printed page numbers are read from each PDF's running headers/footers; where that failed the PDF's own page label is used and marked. "
          "This report only checks; nothing in the strands was changed. Treat every line as something to confirm, not a correction to paste.", "",
          "| status | meaning | count |", "|---|---|---|"]
    cnt = Counter(r["status"] for r in rows)
    for s in ORDER:
        if cnt[s]: md.append(f"| {s} | {EXPLAIN[s]} | {cnt[s]} |")
    md.append(f"| **total** | | **{len(rows)}** |")
    for name, _ in c.STRANDS:
        rs = [r for r in rows if r["strand"] == name]
        if not rs: continue
        md += ["", f"## {name}", ""]
        for r in sorted(rs, key=lambda r: (ORDER.index(r["status"]), r["para"])):
            q = r["quote"] if len(r["quote"]) < 220 else r["quote"][:217] + "…"
            md.append(f"- **{r['status']}** — paragraph beginning “{r['opening']}”")
            md.append(f"  - quote: “{q}”")
            bits = []
            if r["cite"]: bits.append(f"cited: {r['cite']}" + (f", p. {r['cited_page']}" if r["cited_page"] else ""))
            if r["item"] and r["status"] not in ("SOURCE NOT IN LIBRARY", "NO CITATION FOUND"):
                bits.append(f"checked against: {r['item']}")
                if r["found_page"]:
                    ps = r.get("all_pages") or []
                    bits.append(f"found on p. {r['found_page']} (match {r['score']}%)" + (f"; also on {', '.join(p for p in ps if p != str(r['found_page']))}" if len(ps) > 1 else ""))
            if bits: md.append("  - " + "; ".join(bits))
            if r["page_note"]: md.append(f"  - note: {r['page_note']}")
            if r.get("checked") and len(r["checked"]) > 1 and r["status"] == "NOT FOUND IN CITED SOURCE":
                md.append("  - citations near the quote that were checked: " + ", ".join(r["checked"]))
            if r["source_text"] and r["status"] in ("WORDING DIFFERS", "NOT FOUND IN CITED SOURCE"):
                md.append(f"  - closest source text (normalized): “{r['source_text'][:300]}”")
    mdp = os.path.join(c.OUT, "quote_check_all_strands.md")
    open(mdp, "w").write("\n".join(md) + "\n")
    if SHARE_COPY:
        import shutil; shutil.copy(mdp, os.path.join(c.SHARE, "quote_check_all_strands.md"))
    return mdp, cnt


SHARE_COPY = True


def main():
    global SHARE_COPY
    ap = argparse.ArgumentParser(); ap.add_argument("--strand"); ap.add_argument("--strands", help="Strands folder (default ~/Strands)")
    ap.add_argument("--no-share", action="store_true", help="don't copy the report into <Strands>/Corpus reports")
    a = ap.parse_args(); SHARE_COPY = not a.no_share
    if a.strands:
        c.STRANDS_DIR = os.path.expanduser(a.strands); c.SHARE = os.path.join(c.STRANDS_DIR, "Corpus reports")
    con = c.ro_db(); cache = {}; rows = []
    for name, stem in c.STRANDS:
        if a.strand and a.strand != name: continue
        rs = check_strand(con, name, stem, cache); rows += rs
        print(f"{name}: {len(rs)} quotations", flush=True)
    mdp, cnt = write(rows, dt.datetime.now().strftime("%Y-%m-%d_%H%M"))
    print(mdp); print(dict(cnt))


if __name__ == "__main__":
    main()
