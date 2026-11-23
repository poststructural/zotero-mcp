#!/usr/bin/env python3
"""Check every direct quotation in a strand against the cited source's own text in the corpus.

  python verify_quotes.py --strands ~/Strands [--strand "Censorship"] [--out DIR]

For each quotation it finds the citation (parenthetical after the quote, or a narrative "Author (year)" before it),
looks for the cited item in the library (surname + year), and searches that item's paragraphs for the wording.
Report statuses:
  found          wording matches (>= 95% of words in order) on the page shown
  page differs   wording found, but on a different page label than the one cited
  wording differs  close match only (75-95%): the quotation may have been altered
  not found      the cited item is in the corpus but the wording isn't (check the PDF; text may be on a figure/scan)
  no source      the cited item has no extracted PDF in the corpus
  no citation    no year/page could be read near the quotation
Also flags page numbers attached to paraphrase (the project rule: paraphrase takes author and year only).
Page labels come from the PDF's own labels when it has them, otherwise the PDF page index; always confirm the
printed page in the PDF before removing a [CHECK]. A match is a pointer to check, not a verification by itself.
"""
import argparse, collections, difflib, html, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR, toks, YEAR
from build import strand_texts

QUOTE = re.compile(r"[“\"]([^”\"]{12,}?)[”\"]")
PAREN = re.compile(r"\(([^()]{0,160}?\b(" + YEAR + r")\b[^()]{0,80}?)\)")
NARR = re.compile(r"\b([A-Z][A-Za-z’'\-]+)(?:\s+(?:and|&)\s+([A-Z][A-Za-z’'\-]+)|\s+et\s+al\.)?(?:’s|'s)?\s+\((" + YEAR + r")[^)]*\)")
PAGE = re.compile(r"\bpp?\.\s*([\divxlc]+)(?:\s*[–\-]\s*([\divxlc]+))?", re.I)
SURNAME = re.compile(r"\b([A-Z][A-Za-z’'\-]{1,})\b")
STOPCAP = set("See Also In For The And Cf As Quoted Emphasis Original Added".split())


def find_cite(par, qend, qstart, prev=None):
    """Citation for the quote: the first parenthetical after it (within ~100 chars) with a year or page, else a
    narrative cite earlier in the sentence/paragraph plus a bare (p. N) after the quote."""
    tail = par[qend:qend + 140]
    m = re.match(r"[\s,.;:]*\(([^()]{0,200})\)", tail)
    page = None; names = []; year = None
    if m:
        inner = m.group(1)
        pm = PAGE.search(inner); page = pm.groups() if pm else None
        ym = re.search(r"\b(" + YEAR + r")\b", inner); year = ym.group(1)[:4] if ym else None
        names = [n for n in SURNAME.findall(inner.split(str(year))[0] if year else inner) if n not in STOPCAP]
    if not year:
        head = (prev or "") + " " + par[:qstart]
        nm = list(NARR.finditer(head))
        pc = [x for x in PAREN.finditer(head)]
        cand = []
        if nm: cand.append((nm[-1].end(), [n for n in (nm[-1].group(1), nm[-1].group(2)) if n], nm[-1].group(3)[:4]))
        if pc:
            inner = pc[-1].group(1); y = pc[-1].group(2)[:4]
            cand.append((pc[-1].end(), [n for n in SURNAME.findall(inner.split(y)[0]) if n not in STOPCAP], y))
        if cand:
            _, names, year = max(cand, key=lambda c: c[0])
    return names, year, page


def candidates(con, names, year):
    if not year: return []
    names = [re.sub(r"(\u2019s|'s)$", "", n) for n in names]
    rows = con.execute("SELECT key, title, creators, year FROM items WHERE year=? AND status='done'", (year,)).fetchall()
    out = []
    for r in rows:
        cr = (r["creators"] or "").lower()
        if names and any(n.lower().replace("’", "'") in cr for n in names): out.append(r)
    return out


def best_match(con, item_keys, quote):
    q = toks(quote)
    if not q: return None
    best = None
    for key in item_keys:
        for p in con.execute("SELECT id, text, page_label FROM paras WHERE item_key=?", (key,)):
            t = toks(p["text"])
            if len(set(q) & set(t)) < 0.5 * len(set(q)): continue
            sm = difflib.SequenceMatcher(None, q, t, autojunk=False)
            matched = sum(b.size for b in sm.get_matching_blocks())
            score = matched / len(q)
            if not best or score > best[0]:
                blocks = [b for b in sm.get_matching_blocks() if b.size]
                lo = blocks[0].b if blocks else 0; hi = (blocks[-1].b + blocks[-1].size) if blocks else 0
                best = (score, p["page_label"], " ".join(t[max(0, lo - 6):hi + 6]), key)
    return best


def page_ok(cited, label):
    if not cited or not label: return None
    a, b = cited
    try:
        lab = int(label); lo = int(a); hi = int(b) if b else lo
        if hi < lo: hi = int(str(lo)[: len(str(lo)) - len(str(hi))] + str(hi))  # 123-25
        return lo <= lab <= hi
    except ValueError:
        return str(label).lower() == str(a).lower()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands", default="~/Strands"); ap.add_argument("--strand")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "reports"))
    a = ap.parse_args()
    con = db(); os.makedirs(a.out, exist_ok=True)
    for name, paras in strand_texts(a.strands).items():
        short = name.split(" - ")[-1]
        if a.strand and a.strand.lower() not in short.lower(): continue
        rows, counts = [], collections.Counter()
        for pi, par in enumerate(paras):
            for m in QUOTE.finditer(par):
                quote = m.group(1).strip()
                if len(quote.split()) < 3: continue
                names, year, page = find_cite(par, m.end(), m.start(), " ".join(paras[max(0, pi - 2):pi]))
                if not page and len(quote.split()) <= 5 and not re.match(r"[\s,.;:]*\(", par[m.end():m.end() + 5]):
                    continue  # scare quotes / a term in quotation marks, not a quotation needing a locator
                if not year:
                    st = "no citation"; info = ""
                else:
                    items = candidates(con, names, year)
                    if not items:
                        st = "no source"; info = f"{', '.join(names) or '?'} {year} not in corpus"
                    else:
                        bm = best_match(con, [i["key"] for i in items], quote)
                        title = items[0]["title"]
                        if not bm or bm[0] < 0.75:
                            st = "not found"; info = f"in {items[0]['creators']} {year}, {title[:70]}"
                        else:
                            ok = page_ok(page, bm[1])
                            st = ("found" if ok in (True, None) else "page differs") if bm[0] >= 0.95 else "wording differs"
                            info = f"p. {bm[1]} in {items[0]['creators']} {year}, {title[:70]} (match {bm[0]:.0%}); source reads: “…{bm[2]}…”"
                cited = (f"p. {page[0]}" + (f"–{page[1]}" if page and page[1] else "")) if page else "no page"
                counts[st] += 1
                names = [re.sub(r"(\u2019s|'s)$", "", n) for n in names]
                rows.append((pi + 1, quote, f"{', '.join(names)} {year or ''}".strip(), cited, st, info,
                             "[CHECK]" in par[m.end():m.end() + 200]))
        # page numbers on paraphrase: (Author, 2001, p. 4) not preceded by a quotation in the same sentence
        para_pages = []
        for pi, par in enumerate(paras):
            for m in PAREN.finditer(par):
                if PAGE.search(m.group(1)):
                    before = par[max(0, m.start() - 250):m.start()]
                    sent = re.split(r"(?<=[.!?])\s+", before)[-1]
                    if not QUOTE.search(sent) and not re.search(r"[”\"]\s*$", before.strip()):
                        para_pages.append((pi + 1, m.group(0)))
        md = [f"# Quotation check: {short}\n",
              "Matches are pointers into your PDFs. Confirm the printed page in the PDF before clearing a [CHECK].\n",
              "**Summary:** " + ", ".join(f"{k} {v}" for k, v in counts.most_common()) + "\n",
              "| ¶ | quotation | cited | cited page | status | where it is | [CHECK] |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            md.append("| " + " | ".join([str(r[0]), html.escape(r[1][:120]) + ("…" if len(r[1]) > 120 else ""), r[2], r[3], f"**{r[4]}**", html.escape(r[5]), "yes" if r[6] else ""]) + " |")
        if para_pages:
            md += ["", "## Page numbers on what looks like paraphrase (rule: paraphrase takes author and year only)", ""]
            md += [f"- ¶{p}: {c}" for p, c in para_pages]
        path = os.path.join(a.out, f"quote_check_{short.replace(' ', '_')}.md")
        open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
        print(f"{short}: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()) + f"; {len(para_pages)} paged paraphrases -> {path}")


if __name__ == "__main__":
    main()
