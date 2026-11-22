#!/usr/bin/env python3
"""Checks applied to every model rewrite before Austin sees it.

- overlap(): any run of 8+ consecutive words shared with a paragraph in the corpus (published text).
  Generic runs that occur in 5+ different sources are ignored.
- new_cliches(): AI-typical phrases that are rare in the field and appear in the rewrite but not the original.

  python guard.py "candidate sentence…"
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, shingle_hashes, toks, SHINGLE_N, OUT_DIR

_never = None


def never_terms():
    global _never
    if _never is None:
        from exemplars import load_never
        from build import term_rx
        _never = [(t, term_rx(t)) for t in load_never()]
    return _never


def overlap(text, con=None, min_words=SHINGLE_N, generic_sources=5):
    con = con or db()
    hs = shingle_hashes(text)
    if not hs: return []
    hits = {}
    uniq = list(set(hs))
    for i in range(0, len(uniq), 500):
        chunk = uniq[i:i + 500]
        for r in con.execute(f"""SELECT s.h, s.pid, p.item_key FROM shingles s JOIN paras p ON p.id=s.pid
                                 WHERE s.h IN ({','.join('?' * len(chunk))})""", chunk):
            hits.setdefault(r["h"], {})[r["pid"]] = r["item_key"]
    # drop generic word runs found in many different sources
    hits = {h: d for h, d in hits.items() if len(set(d.values())) < generic_sources}
    t = toks(text); out = []; pos = 0
    while pos < len(hs):
        if hs[pos] not in hits: pos += 1; continue
        pids = set(hits[hs[pos]]); end = pos
        while end + 1 < len(hs) and hs[end + 1] in hits and pids & set(hits[hs[end + 1]]):
            pids &= set(hits[hs[end + 1]]); end += 1
        n = end - pos + SHINGLE_N
        if n >= min_words:
            pid = next(iter(pids))
            row = con.execute("SELECT i.title, i.creators, i.year, p.page_label FROM paras p JOIN items i ON i.key=p.item_key WHERE p.id=?", (pid,)).fetchone()
            out.append({"words": n, "text": " ".join(t[pos:end + SHINGLE_N]), "para_id": pid,
                        "source": f"{row['creators']} {row['year']}, {row['title']}" if row else "?",
                        "page": row["page_label"] if row else None})
        pos = end + 1
    return out


def new_cliches(old, new):
    o, n = (old or "").lower().replace("’", "'"), (new or "").lower().replace("’", "'")
    return [t for t, rx in never_terms() if len(rx.findall(n)) > len(rx.findall(o))]


def check(old, new, con=None):
    """List of human-readable problems with a proposed rewrite (empty = clean)."""
    if not new: return []
    probs = []
    for o in overlap(new, con):
        if o["text"] not in " ".join(toks(old or "")):
            probs.append(f"repeats {o['words']} words of published text (“{o['text']}”, {o['source']})")
    for t in new_cliches(old, new):
        probs.append(f"adds “{t}”, an AI-typical phrase that is rare in your field")
    return probs


if __name__ == "__main__":
    txt = " ".join(sys.argv[1:]) or sys.stdin.read()
    print(json.dumps({"overlap": overlap(txt), "cliches": new_cliches("", txt)}, indent=1))
