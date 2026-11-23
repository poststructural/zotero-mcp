"""Shared helpers for quote_check.py and audit_packets.py: strand citations, Zotero item matching, printed page numbers.

Reads: the strands (.docx, via the dashboard's review.py), ~/style_corpus/corpus.db (read-only),
and, for cited items only, the PDF from Zotero cloud storage (GET only, cached in ~/style_corpus/cache/pdf).
Writes: reports only (~/style_corpus/out/register and the Strands "Scholarly register" folder).
"""
import os, re, sqlite3, sys, unicodedata

HOME = os.environ.get("STYLE_CORPUS_HOME", os.path.expanduser("~/style_corpus"))
SRC = os.path.dirname(os.path.abspath(__file__))
STRANDS_DIR = os.path.expanduser(os.environ.get("STRANDS_DIR", "~/Strands"))
DASH = os.path.join(STRANDS_DIR, "_dashboard")
OUT = os.path.join(HOME, "out", "reports")
SHARE = os.path.join(STRANDS_DIR, "Corpus reports")
CACHE = os.path.join(HOME, "cache", "pdf")
for p in (SRC, DASH):
    if p not in sys.path: sys.path.insert(0, p)

STRANDS = [("Canon and Canon Wars", "Strand 1 - Canon and Canon Wars"), ("Censorship", "Strand 2 - Censorship"),
           ("Moral Panics", "Strand 3 - Moral Panics"), ("Text Selection", "Strand 4 - Text Selection")]


def ro_db():
    con = sqlite3.connect(f"file:{HOME}/corpus.db?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def strand_paras(stem):
    import review as rv
    return [p for p in rv.paragraphs(os.path.join(STRANDS_DIR, stem + ".docx")) if p["text"].strip() and not p["notes"]]


def opening(t, n=8):
    w = t.split(); return " ".join(w[:n]) + ("…" if len(w) > n else "")


# ------------------------------------------------------------------ normalization
QMAP = {"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'", "–": "-", "—": "-", "‐": "-", "‑": "-",
        "­": "", "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "…": "...", " ": " "}


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    for a, b in QMAP.items(): s = s.replace(a, b)
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s)          # line-break hyphenation
    s = s.lower()
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ citations in the strands
SURNAME = r"(?:(?:[Dd]e\s[Ll]os|[Dd]e|[Dd]el|[Vv]an|[Vv]on|[Dd]a|[Ll]e|[Ll]a)\s)?[A-Z][A-Za-zÀ-ÿ]+(?:[’'][A-Z][A-Za-zÀ-ÿ]+)?(?:-[A-Z][A-Za-zÀ-ÿ]+)?"
YEAR = r"(?:1[6-9]|20)\d{2}[a-z]?"
NAMES = SURNAME + r"(?:\s*(?:,|and|&)\s*" + SURNAME + r")*(?:\s+et\s+al\.)?"
NARR = re.compile(r"(" + NAMES + r")(?:[’']s)?\s+\((" + YEAR + r"(?:\s*[,;]\s*" + YEAR + r")*)(?:,\s*(pp?\.\s*[\divxlc–\-]+))?\)")
PAREN = re.compile(r"\(([^()]*?\b" + YEAR + r"\b[^()]*)\)")
PAGE = re.compile(r"\bpp?\.\s*([\divxlcIVXLC]+(?:\s*[–\-]\s*[\divxlc]+)?)")
STOP_CAP = {"The", "This", "These", "In", "As", "For", "See", "Also", "But", "And", "Of", "On", "At", "By", "Per", "A", "An", "Their"}


def surnames(names):
    out = []
    for n in re.split(r"\s*(?:,|\band\b|&|et al\.)\s*", names):
        n = re.sub(r"[’']s$", "", n.strip())
        if n and n not in STOP_CAP and n.split()[-1] not in STOP_CAP: out.append(n)
    return out


def fold(s):
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower().strip()


INSTITUTION = {"Education", "University", "Commission", "Department", "Council", "Board", "Association", "America",
               "County", "House", "Library", "Humanities", "Endowment", "Office", "Senate", "Court", "Institute", "Foundation", "Literature", "Legacy", "Canons"}


def name_match(sn, creator):
    a, b = fold(sn), re.sub(r",?\s+(jr|sr|ii|iii|iv)\.?$", "", fold(creator))
    return a == b or b.endswith(" " + a) or a.endswith(" " + b) or a.replace(" ", "") == b.replace(" ", "")


def citations(text):
    """[(surnames tuple, year, page or None, start, end)] for narrative and parenthetical citations."""
    out = []
    for m in NARR.finditer(text):
        sn = surnames(m.group(1))
        for y in re.findall(YEAR, m.group(2)):
            pg = PAGE.search(m.group(3) or "")
            if sn: out.append((tuple(sn), y, pg.group(1) if pg else None, m.start(), m.end()))
            # titles before the year ("Bennett's To Reclaim a Legacy (1984)"): also offer earlier capitalized names
            for tok in reversed(re.findall(r"\b([A-Z][A-Za-zÀ-ÿ\-]+)(?:[’']s)?\b", text[max(0, m.start() - 220):m.start()])):
                if tok not in STOP_CAP and (tok,) != tuple(sn[:1]):
                    out.append(((tok,), y, pg.group(1) if pg else None, m.start(), m.end()))
    for m in PAREN.finditer(text):
        inner = m.group(1)
        for part in inner.split(";"):
            ym = re.search(r"(" + NAMES + r")?,?\s*(" + YEAR + r")(?:\s*,\s*(pp?\.\s*[\divxlc–\-]+))?", part.strip())
            if not ym: continue
            sn = surnames(ym.group(1) or "")
            pg = PAGE.search(ym.group(3) or "")
            if sn: out.append((tuple(sn), ym.group(2), pg.group(1) if pg else None, m.start(), m.end()))
    return out


def resolve(con, sn, year):
    """Zotero items whose creators include the first surname and whose year matches."""
    y = year[:4]
    sn = tuple(x for x in sn if x not in INSTITUTION)
    if not sn: return []
    rows = con.execute("SELECT * FROM items WHERE year=?", (y,)).fetchall()
    rows = [r for r in rows if any(name_match(sn[0], c) for c in (r["creators"] or "").split(";"))]
    if len(rows) > 1 and len(sn) > 1:
        both = [r for r in rows if all(any(name_match(s, c) for c in r["creators"].split(";")) for s in sn)]
        rows = both or rows
    if len(rows) > 1:  # duplicates of one work: prefer the one with text
        done = [r for r in rows if r["status"] == "done"]
        if done: rows = done
    return rows


def cite_label(r):
    au = (r["creators"] or "?").split(";"); au = [a.strip() for a in au if a.strip()]
    who = au[0] if len(au) == 1 else (f"{au[0]} & {au[1]}" if len(au) == 2 else f"{au[0]} et al.")
    return f"{who} ({r['year']})"


# ------------------------------------------------------------------ PDFs of cited items, with printed page numbers
BOILER = re.compile(r"This content downloaded|All use subject to|JSTOR|Downloaded from|For personal use|Terms and Conditions|https?://|doi\.org|©", re.I)


def item_meta(key):
    """Zotero metadata for a top-level item (GET only), cached."""
    import json as _j
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path): return _j.load(open(path))
    import common
    try: data, _ = common.Zotero(common.load_env())._get(f"/items/{key}")
    except Exception: return {}
    d = data.get("data", {}); _j.dump(d, open(path, "w")); os.chmod(path, 0o600)
    return d


def pdf_pages(item):
    """[(pdf_index, printed_page, text)] for one item, downloading its PDF once (GET only).
    printed_page is read from running headers/footers; failing that, from the Zotero 'pages' range
    aligned to the title page (suffix '~'); failing that, the PDF label or index (prefix 'pdf ')."""
    import pymupdf
    if not item["pdf_key"]: return []
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, item["pdf_key"] + ".pdf")
    if not os.path.exists(path):
        import common
        z = common.Zotero(common.load_env())
        try: body = z.file(item["pdf_key"])
        except Exception: return []
        if not body.startswith(b"%PDF"): return []
        with open(path + ".tmp", "wb") as f: f.write(body)
        os.replace(path + ".tmp", path); os.chmod(path, 0o600)
    try: doc = pymupdf.open(path)
    except Exception: return []
    pages = []
    for i, pg in enumerate(doc):
        try: lab = pg.get_label() or ""
        except Exception: lab = ""
        pages.append([i, lab, pg.get_text("text") or ""])
    printed = infer_printed(pages) or from_labels(pages) or from_range(item, pages)
    out = []
    for i, lab, t in pages:
        pr = printed.get(i)
        if pr is not None and re.fullmatch(r"-?\d+~?", pr) and int(pr.rstrip("~")) <= 0: pr = None   # front matter
        if pr is None: pr = ("pdf " + lab) if lab else f"pdf {i + 1}"
        out.append((i, pr, t))
    return out


def from_labels(pages):
    """Use the PDF's own page labels when they look like real page numbers (not just 1..n)."""
    labs = {}
    for i, lab, _ in pages:
        v = re.sub(r"^\s*(?:p\.|page)\s*", "", lab or "", flags=re.I).strip()
        if re.fullmatch(r"\d+|[ivxlcdm]+", v, re.I): labs[i] = v
    nums = [(i, int(v)) for i, v in labs.items() if v.isdigit()]
    if len(labs) < max(2, len(pages) // 2) or not nums: return {}
    if all(n == i + 1 for i, n in nums): return {}          # labels are just the PDF index
    return labs


def infer_printed(pages):
    """Printed page numbers from running headers/footers: the offset (printed - index) most pages agree on."""
    from collections import Counter
    votes = Counter(); usable = 0
    for i, lab, t in pages:
        lines = [l.strip() for l in t.splitlines() if l.strip() and not BOILER.search(l)]
        if len(lines) < 5: continue
        usable += 1
        for l in lines[:3] + lines[-3:]:
            if len(l) > 90: continue
            for m in re.finditer(r"(?<![\d.,])(\d{1,4})(?![\d.,])", l):
                n = int(m.group(1))
                if 0 < n < 5000 and not (1900 <= n <= 2030): votes[n - i] += 1
    if not votes: return {}
    off, n = votes.most_common(1)[0]
    second = votes.most_common(2)[1][1] if len(votes) > 1 else 0
    if n < max(3, usable // 3) or n < 2 * second: return {}
    return {i: str(i + off) for i, _, _ in pages}


def from_range(item, pages):
    d = item_meta(item["key"])
    m = re.match(r"\s*(\d+)", str(d.get("pages") or ""))
    if not m: return {}
    start = int(m.group(1))
    tw = [w for w in norm(item["title"] or "").split() if len(w) > 3][:8]
    first = 0
    for i, _, t in pages[:4]:
        head = norm(" ".join(t.splitlines()[:25]))
        if tw and sum(w in head for w in tw) >= max(2, int(0.6 * len(tw))) and not re.search(r"collaborating with jstor|this content downloaded", head):
            first = i; break
    else:
        if pages and re.search(r"jstor", pages[0][2][:2000], re.I): first = 1
    return {i: f"{start + i - first}~" for i, _, _ in pages if i >= first}
