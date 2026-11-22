#!/usr/bin/env python3
"""Pull Zotero metadata, score field relevance, and extract paragraph text from PDFs.

  python harvest.py meta                          # items, collections, PDF attachments -> items table
  python harvest.py select --limit 300            # list the pilot set (core items with a PDF)
  python harvest.py extract --limit 300 [--relevance core] [--workers 4]
  python harvest.py extract --all                 # every downloadable PDF
  python harvest.py status

PDFs are downloaded to a temporary file, parsed, and deleted; only paragraph text is kept,
in ~/style_corpus/corpus.db. If a PDF can't be parsed, Zotero's own full-text index is used
instead (marked source='fulltext': no reliable paragraph breaks, so it is used for phrase
rates and the overlap guard but not for paragraph-architecture profiles or exemplars).
Read-only against Zotero: this script only issues GET requests.
"""
import argparse, collections, concurrent.futures as cf, json, os, re, sys, tempfile, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (Zotero, db, load_env, mask, role_of, shingle_hashes, CITE_COUNT, now, words)

# ------------------------------------------------------------ field relevance
CORE_VENUES = [
    "english journal", "english education", "research in the teaching of english", "journal of adolescent & adult literacy",
    "journal of adolescent and adult literacy", "journal of literacy research", "reading research quarterly",
    "curriculum inquiry", "journal of curriculum theorizing", "journal of curriculum studies", "changing english",
    "english teaching: practice", "english in education", "journal of curriculum and pedagogy", "the alan review",
    "voices from the middle", "college english", "literacy research: theory", "english in australia",
    "journal of literary education", "children's literature in education", "research in the teaching",
    "pedagogy, culture", "curriculum perspectives", "reading & writing quarterly", "literacy", "teaching english",
]
ADJ_VENUES = [
    "teachers college record", "american educational research journal", "educational researcher",
    "harvard educational review", "educational policy", "qualitative inquiry", "review of educational research",
    "american journal of education", "sociology of education", "journal of teacher education", "teaching and teacher education",
    "educational theory", "studies in philosophy and education", "discourse: studies", "international journal of qualitative studies",
    "educational administration quarterly", "peabody journal", "education policy analysis archives", "phi delta kappan",
]
CORE_TERMS = [
    r"english teach\w*", r"english education", r"secondary english", r"english language arts", r"\bela\b",
    r"literature (?:instruction|curricul\w*|teaching)", r"literary canon", r"\bcanon\w*", r"censor\w*",
    r"book (?:challenge|ban)\w*", r"banned books?", r"text selection", r"curriculum theor\w*", r"curricul\w*",
    r"poststructural\w*", r"post-structural\w*", r"deleuz\w*", r"foucault\w*", r"derrida\w*", r"moral panic\w*",
    r"reading lists?", r"assigned (?:reading|texts?)", r"young adult literature", r"\bliteracy\b", r"teacher (?:autonomy|decision)",
]
ADJ_TERMS = [r"\beducation\w*", r"\bteach\w*", r"\bschool\w*", r"pedagog\w*", r"classroom\w*", r"\bpolic\w*",
             r"\bstudents?\b", r"\breading\b", r"\bliterat\w*"]
CORE_COLLECTION = re.compile(r"canon|censor|moral panic|text selection|dissertation|curricul|english|poststruct|deleuz|lit review", re.I)


def score_item(d, coll_names):
    title = d.get("title") or ""; venue = (d.get("publicationTitle") or d.get("bookTitle") or d.get("publisher") or "")
    abstract = d.get("abstractNote") or ""; tags = " ".join(t["tag"] for t in d.get("tags", []))
    colls = [coll_names.get(c, "") for c in d.get("collections", [])]
    text = " ".join([title, abstract, tags, " ".join(colls)]).lower(); v = venue.lower()
    s = 0.0; why = []
    if any(x in v for x in CORE_VENUES): s += 3; why.append("core venue")
    elif any(x in v for x in ADJ_VENUES): s += 1.5; why.append("education venue")
    core_hits = sorted({m.group(0) for rx in CORE_TERMS for m in re.finditer(rx, text)})
    s += min(len(core_hits), 4); why += core_hits[:4]
    adj = sum(1 for rx in ADJ_TERMS if re.search(rx, text + " " + v))
    s += min(adj, 3) * 0.4
    hit_colls = [c for c in colls if CORE_COLLECTION.search(c)]
    if hit_colls: s += 3; why.append("collection: " + hit_colls[0])
    rel = "core" if s >= 3 else "adjacent" if s >= 1.2 else "other"
    return rel, round(s, 2), why


def year_of(d):
    m = re.search(r"\b(1[5-9]|20)\d{2}\b", d.get("date") or "")
    return m.group(0) if m else ""


def creators(d):
    out = []
    for c in d.get("creators", [])[:6]:
        out.append(c.get("lastName") or c.get("name") or "")
    return "; ".join(x for x in out if x)


def cmd_meta(args):
    z = Zotero(load_env()); con = db()
    print("collections…", flush=True)
    colls = z.all("/collections")
    names = {c["key"]: c["data"]["name"] for c in colls}
    print(f"  {len(colls)} collections\ntop-level items…", flush=True)
    items = z.all("/items/top", {"format": "json"})
    print(f"  {len(items)} items\nattachments…", flush=True)
    atts = z.all("/items", {"itemType": "attachment", "format": "json"})
    pdfs = collections.defaultdict(list)
    for a in atts:
        d = a["data"]
        if d.get("contentType") == "application/pdf" and d.get("parentItem"):
            pdfs[d["parentItem"]].append((d["key"], d.get("linkMode")))
    rows = 0
    for it in items:
        d = it["data"]
        if d.get("itemType") in ("attachment", "note", "annotation"): continue
        rel, s, why = score_item(d, names)
        cands = [p for p in pdfs.get(d["key"], []) if p[1] in ("imported_file", "imported_url")] or pdfs.get(d["key"], [])
        pk, lm = cands[0] if cands else (None, None)
        con.execute("""INSERT INTO items(key,item_type,title,creators,year,venue,doi,tags,collections,relevance,score,reasons,pdf_key,pdf_link_mode,updated)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(key) DO UPDATE SET item_type=excluded.item_type,title=excluded.title,creators=excluded.creators,
                       year=excluded.year,venue=excluded.venue,doi=excluded.doi,tags=excluded.tags,collections=excluded.collections,
                       relevance=excluded.relevance,score=excluded.score,reasons=excluded.reasons,pdf_key=excluded.pdf_key,
                       pdf_link_mode=excluded.pdf_link_mode,updated=excluded.updated""",
                    (d["key"], d.get("itemType"), d.get("title"), creators(d), year_of(d),
                     d.get("publicationTitle") or d.get("bookTitle") or d.get("publisher") or "", d.get("DOI") or "",
                     json.dumps([t["tag"] for t in d.get("tags", [])]), json.dumps([names.get(c, c) for c in d.get("collections", [])]),
                     rel, s, json.dumps(why), pk, lm, now()))
        rows += 1
    con.commit()
    print_status(con)


def print_status(con):
    q = con.execute("""SELECT relevance, COUNT(*) n, SUM(pdf_key IS NOT NULL AND pdf_link_mode!='linked_file') pdf,
                       SUM(status='done') done, SUM(status='failed') failed, SUM(COALESCE(n_words,0)) w
                       FROM items GROUP BY relevance ORDER BY relevance""").fetchall()
    print(f"{'relevance':<10}{'items':>7}{'PDFs':>7}{'done':>7}{'failed':>7}{'words':>12}")
    for r in q: print(f"{r['relevance']:<10}{r['n']:>7}{r['pdf'] or 0:>7}{r['done'] or 0:>7}{r['failed'] or 0:>7}{r['w'] or 0:>12,}")
    n = con.execute("SELECT COUNT(*) FROM paras").fetchone()[0]
    print(f"paragraphs stored: {n:,}")


def selection(con, relevance, limit, everything=False):
    sql = "SELECT * FROM items WHERE pdf_key IS NOT NULL AND pdf_link_mode!='linked_file' AND status!='done'"
    par = []
    if not everything and relevance:
        rel = relevance.split(",")
        sql += f" AND relevance IN ({','.join('?' * len(rel))})"; par += rel
    sql += " ORDER BY CASE relevance WHEN 'core' THEN 0 WHEN 'adjacent' THEN 1 ELSE 2 END, score DESC"
    if limit: sql += " LIMIT ?"; par.append(limit)
    return con.execute(sql, par).fetchall()


def cmd_select(args):
    con = db()
    for r in selection(con, args.relevance, args.limit):
        print(f"{r['relevance']:<9}{r['score']:>5}  {r['year'] or '----'}  {(r['creators'] or '')[:24]:<24}  {(r['title'] or '')[:70]}  | {(r['venue'] or '')[:40]}")


# ------------------------------------------------------------ PDF parsing
REFS_HEAD = re.compile(r"^(references|works cited|bibliography|literature cited|reference list|notes|endnotes)\s*$", re.I)
TERMINAL = re.compile(r"[.!?:][\"”’)\]]*$")


def clean(t):
    t = t.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_pdf(path):
    try: import pymupdf as fitz
    except ImportError: import fitz
    doc = fitz.open(path)
    n_pages = len(doc); blocks = []
    for pno, page in enumerate(doc):
        h = page.rect.height or 1
        try: label = page.get_label() or str(pno + 1)
        except Exception: label = str(pno + 1)
        for b in page.get_text("blocks", sort=True):
            if len(b) >= 7 and b[6] != 0: continue
            lines = [x.strip() for x in b[4].split("\n")]
            # a heading or "References" line fused into a text block: split it off
            for j, ln in enumerate(lines):
                if REFS_HEAD.match(ln) and pno > 0.4 * n_pages:
                    pre = clean("\n".join(lines[:j]))
                    if pre: blocks.append({"p": pno, "label": label, "y0": b[1] / h, "y1": b[3] / h, "t": pre})
                    blocks.append({"p": pno, "label": label, "y0": b[1] / h, "y1": b[3] / h, "t": ln})
                    lines = None; break
            if lines is None: continue
            if len(lines) > 2 and 0 < len(lines[0].split()) <= 8 and not TERMINAL.search(lines[0]) and lines[1][:1].isupper() \
                    and not lines[0][-1:] in ",;-":
                blocks.append({"p": pno, "label": label, "y0": b[1] / h, "y1": b[1] / h, "t": lines[0]}); lines = lines[1:]
            t = clean("\n".join(lines))
            if t: blocks.append({"p": pno, "label": label, "y0": b[1] / h, "y1": b[3] / h, "t": t})
    doc.close()
    key = lambda t: re.sub(r"\d+", "#", t.lower())[:60]
    rep = collections.Counter(key(b["t"]) for b in blocks if len(b["t"].split()) < 25)
    paras, cur, section = [], None, ""
    for b in blocks:
        t = b["t"]; nw = len(t.split())
        if nw < 25 and rep[key(t)] >= 3: continue                      # running heads / footers
        if (b["y0"] > 0.92 or b["y1"] < 0.07) and nw < 15: continue     # page furniture
        if REFS_HEAD.match(t) and b["p"] > 0.4 * n_pages: break        # stop at the reference list
        if nw <= 12 and not TERMINAL.search(t) and not (cur and not TERMINAL.search(cur["t"]) and t[:1].islower()):
            section = t[:120]
            if cur: paras.append(cur); cur = None
            continue
        if cur and not TERMINAL.search(cur["t"]):                       # paragraph runs on across a column/page
            cur["t"] = (cur["t"][:-1] + t) if cur["t"].endswith("-") else cur["t"] + " " + t
            continue
        if cur: paras.append(cur)
        cur = {"label": b["label"], "t": t, "section": section}
    if cur: paras.append(cur)
    return [p for p in paras if keep(p["t"])]


def keep(t):
    w = t.split(); nw = len(w)
    if nw < 40 or nw > 600: return False
    letters = sum(ch.isalpha() for ch in t); digits = sum(ch.isdigit() for ch in t)
    if letters / max(len(t), 1) < 0.72 or digits / max(len(t), 1) > 0.06: return False
    if len(CITE_COUNT.findall(t)) > nw / 10: return False                # reference-list fragments
    if sum(1 for x in w if x.isupper() and len(x) > 2) > nw / 5: return False
    if not re.search(r"\b(the|and|of|to|in)\b", t): return False
    return True


def fulltext_paras(text):
    """Zotero's index has line breaks but no reliable paragraphs: make ~150-word chunks on sentence ends."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    m = re.search(r"\n\s*(references|works cited|bibliography)\s*\n", text, re.I)
    if m and m.start() > 0.4 * len(text): text = text[:m.start()]
    flat = re.sub(r"\s+", " ", text)
    out, cur = [], []
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat):
        cur.append(s)
        if sum(len(x.split()) for x in cur) >= 150:
            out.append(" ".join(cur)); cur = []
    if cur: out.append(" ".join(cur))
    return [{"label": None, "t": t, "section": ""} for t in out if keep(t)]


lock = threading.Lock()


def store(con, item_key, paras, source):
    with lock:
        con.execute("DELETE FROM paras_fts WHERE rowid IN (SELECT id FROM paras WHERE item_key=?)", (item_key,))
        con.execute("DELETE FROM shingles WHERE pid IN (SELECT id FROM paras WHERE item_key=?)", (item_key,))
        con.execute("DELETE FROM paras WHERE item_key=?", (item_key,))
        tot = 0
        for i, p in enumerate(paras):
            t = p["t"]; m = mask(t); nw = len(words(t)); tot += nw
            cur = con.execute("INSERT INTO paras(item_key,seq,page_label,section,text,masked,words,role,cites,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (item_key, i, p["label"], p["section"], t, m, nw, role_of(t), len(CITE_COUNT.findall(t)), source))
            pid = cur.lastrowid
            con.execute("INSERT INTO paras_fts(rowid, masked) VALUES(?,?)", (pid, m))
            con.executemany("INSERT OR IGNORE INTO shingles(h,pid) VALUES(?,?)", [(h, pid) for h in set(shingle_hashes(t))])
        con.execute("UPDATE items SET status='done', source=?, n_paras=?, n_words=?, note=NULL, updated=? WHERE key=?",
                    (source, len(paras), tot, now(), item_key))
        con.commit()
    return len(paras), tot


def process(z, con, row):
    paras, source, note = [], None, None
    try:
        data = z.file(row["pdf_key"])
        if data[:5] == b"%PDF-":
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as f:
                f.write(data); f.flush()
                paras = parse_pdf(f.name); source = "pdf"
        else:
            note = "file was not a PDF"
    except Exception as e:  # noqa: BLE001 - record and fall back
        note = f"pdf: {type(e).__name__}: {str(e)[:120]}"
    if len(paras) < 5:
        ft = z.fulltext(row["pdf_key"])
        fp = fulltext_paras(ft) if ft else []
        if len(fp) > len(paras): paras, source = fp, "fulltext"
    if not paras:
        with lock:
            con.execute("UPDATE items SET status='failed', note=?, updated=? WHERE key=?", (note or "no usable text (scanned PDF?)", now(), row["key"]))
            con.commit()
        return row, 0, 0, "failed"
    n, w = store(con, row["key"], paras, source)
    return row, n, w, source


def cmd_extract(args):
    z = Zotero(load_env()); con = db()
    rows = selection(con, None if args.all else args.relevance, None if args.all else args.limit, everything=args.all)
    print(f"{len(rows)} items to extract", flush=True)
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for row, n, w, src in ex.map(lambda r: process(z, con, r), rows):
            done += 1
            print(f"[{done}/{len(rows)}] {src:<8} {n:>4} paras {w:>7,} words  {(row['title'] or '')[:70]}", flush=True)
    print_status(con)


def cmd_status(args):
    print_status(db())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("meta")
    s = sub.add_parser("select"); s.add_argument("--limit", type=int, default=300); s.add_argument("--relevance", default="core")
    e = sub.add_parser("extract"); e.add_argument("--limit", type=int, default=300); e.add_argument("--relevance", default="core")
    e.add_argument("--all", action="store_true"); e.add_argument("--workers", type=int, default=4)
    sub.add_parser("status")
    a = ap.parse_args()
    {"meta": cmd_meta, "select": cmd_select, "extract": cmd_extract, "status": cmd_status}[a.cmd](a)
