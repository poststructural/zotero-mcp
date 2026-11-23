#!/usr/bin/env python3
"""The field's common 3–5-word academic phrases (lexical bundles), with each strand's rate for the same phrases.

  python field_ngrams.py [--strands ~/Strands] [--min-sources 20] [--top 300]

Core items only, capped per source (build.CAPPED / PER_ITEM), masked text, sentence-internal n-grams.
A phrase counts if it appears in at least --min-sources distinct sources. Phrases made only of function words,
or touching a masked placeholder ([Name], (YEAR) …), are dropped; a shorter phrase is dropped when a longer one
containing it covers ≥ 90% of its sources. Output: out/field_ngrams.md and out/field_ngrams.json.
These are generic frames (counted, not quoted); never content.
"""
import argparse, collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR, sentences
from build import CAPPED, PER_ITEM, strand_texts

FUNC = set("""a an the of to in on at by for from with without into onto upon about as than that this these those which who whom whose
what when where while how why and or but nor so yet if then because although though since unless until whether is are was were be been
being am do does did done have has had having it its it's they them their there here he him his she her we us our i me my you your
not no also only even just more most less such can could may might must should would will shall one ones some any all each both
other another same very much many own over under between through during before after above below up down out off again further
once there's that's s""".split())
BOILER = re.compile(r"jstor|this content downloaded|all use subject to|terms and conditions|for personal use|downloaded from|taylor\s*&\s*francis|creative commons|copyright|all rights reserved|https?://|www\.|doi", re.I)
WORD = re.compile(r"\[[^\]]*\]|\([A-Z]+\)|[A-Za-z][A-Za-z’'\-]*")


def grams(sent, nmin=3, nmax=5):
    toks = [t.lower().replace("’", "'") for t in WORD.findall(sent)]
    out = []
    for n in range(nmin, nmax + 1):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if any(t.startswith("[") or t.startswith("(") for t in g): continue
            if all(t in FUNC for t in g): continue
            if g[0] in {"and", "or", "but"} or g[-1] in {"the", "a", "an", "and", "or", "of", "to"}: continue
            out.append(" ".join(g))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands", default="~/Strands")
    ap.add_argument("--min-sources", type=int, default=20); ap.add_argument("--top", type=int, default=300)
    a = ap.parse_args(); con = db()
    rows = con.execute(CAPPED.format(cols="item_key, masked, words", where="p.source='pdf' AND i.relevance=?"), ("core", PER_ITEM)).fetchall()
    df, tf = collections.Counter(), collections.Counter(); words = 0
    by_item = collections.defaultdict(set)
    for r in rows:
        if BOILER.search(r["masked"] or "") and re.search(r"jstor|downloaded|terms|copyright|rights reserved", r["masked"] or "", re.I): continue
        words += r["words"] or 0
        for s in sentences(r["masked"] or ""):
            if BOILER.search(s): continue
            for g in grams(s):
                tf[g] += 1; by_item[g].add(r["item_key"])
    for g, items in by_item.items():
        if len(items) >= a.min_sources: df[g] = len(items)
    keep = dict(df)
    # drop a phrase when a longer phrase containing it covers >= 90% of its sources
    longer = sorted(keep, key=lambda g: -len(g.split()))
    for g in longer:
        if g not in keep: continue
        for sub_n in range(3, len(g.split())):
            toks = g.split()
            for i in range(len(toks) - sub_n + 1):
                sub = " ".join(toks[i:i + sub_n])
                if sub in keep and keep[g] >= 0.9 * keep[sub]: keep.pop(sub, None)
    top = sorted(keep, key=lambda g: (-keep[g], -tf[g], g))[:a.top]
    strands = {}
    for name, paras in strand_texts(a.strands).items():
        txt = "\n".join(paras); wc = len(txt.split()) or 1
        c = collections.Counter(g for p in paras for s in sentences(p) for g in grams(s))
        strands[name.split(" - ")[-1]] = {"words": wc, "per10k": {g: round(c[g] * 10000 / wc, 2) for g in top}}
    field = {g: {"sources": keep[g], "count": tf[g], "per10k": round(tf[g] * 10000 / max(1, words), 2)} for g in top}
    json.dump({"field_words": words, "sources": len({r['item_key'] for r in rows}), "phrases": field, "strands": strands},
              open(os.path.join(OUT_DIR, "field_ngrams.json"), "w"), indent=1)
    names = list(strands)
    md = ["# The field's common academic phrases (3–5 words)", "",
          f"Core sources: {len({r['item_key'] for r in rows})}, {words:,} words (capped at {PER_ITEM} paragraphs per source), masked text. "
          f"A phrase is listed if it appears in at least {a.min_sources} different sources; names, years and other placeholders are excluded. "
          "Rates are per 10,000 words. These are generic frames the field shares, counted, not quoted: use them to judge whether a "
          "phrasing sounds like the field, never as content.", "",
          "| # | phrase | sources | field /10k | " + " | ".join(names) + " |", "|---|---|---|---|" + "---|" * len(names)]
    for k, g in enumerate(top, 1):
        md.append(f"| {k} | {g} | {field[g]['sources']} | {field[g]['per10k']} | " + " | ".join(str(strands[n]['per10k'][g]) for n in names) + " |")
    open(os.path.join(OUT_DIR, "field_ngrams.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"{len(keep):,} phrases in >= {a.min_sources} sources; top {len(top)} -> {os.path.join(OUT_DIR, 'field_ngrams.md')}")
    for g in top[:25]: print(f"  {field[g]['sources']:4d}  {g}")


if __name__ == "__main__":
    main()
