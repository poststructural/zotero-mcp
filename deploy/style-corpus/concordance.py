#!/usr/bin/env python3
"""Keyword-in-context lines for the strands' key terms across the library, by decade, with source and page.

  python concordance.py [--terms censorship,rejection,...] [--per-decade 6] [--relevance core,adjacent]

For term discipline: how the field uses "censorship", "challenge", "selection", "canon"... and in what company.
Lines are for Austin's reading (unmasked, with sources); they stay on the server/his PC.
"""
import argparse, collections, os, random, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR

DEFAULT = ("censorship,book challenge,challenge,ban,banning,rejection,restriction,self-censorship,text selection,"
           "selection,canon,canonical,literary canon,moral panic,curriculum,gatekeeping,culture wars,parental rights,"
           "divisive concepts,age-appropriate,obscen,controversial texts").split(",")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--terms", default=",".join(DEFAULT))
    ap.add_argument("--per-decade", type=int, default=6); ap.add_argument("--relevance", default="core,adjacent")
    ap.add_argument("--width", type=int, default=110); ap.add_argument("--out", default=os.path.join(OUT_DIR, "reports"))
    a = ap.parse_args(); con = db(); os.makedirs(a.out, exist_ok=True); rnd = random.Random(7)
    rel = a.relevance.split(",")
    md = ["# Key terms across your library\n", f"Sources: {', '.join(rel)} items. Counts are occurrences; lines are a sample per decade (source, year, page).\n"]
    summary = ["| term | " + " | ".join(["pre-1970", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s", "total", "sources"]) + " |", "|---|" + "---|" * 9]
    sections = []
    for term in [t.strip() for t in a.terms.split(",") if t.strip()]:
        rx = re.compile(r"\b" + re.escape(term) + r"\w*", re.I)
        rows = con.execute(f"""SELECT p.text, p.page_label, i.creators, i.year, i.title FROM paras p JOIN items i ON i.key=p.item_key
                               WHERE i.relevance IN ({','.join('?'*len(rel))}) AND p.id IN (SELECT rowid FROM paras_fts WHERE paras_fts MATCH ?)""",
                           (*rel, '"' + term.replace('"', '') + '"')).fetchall()
        by = collections.defaultdict(list); n = 0; srcs = set()
        for r in rows:
            y = int(r["year"]) if (r["year"] or "").isdigit() else None
            dec = "pre-1970" if y and y < 1970 else f"{(y // 10) * 10}s" if y else "?"
            for m in rx.finditer(r["text"]):
                n += 1; srcs.add((r["creators"], r["year"]))
                s, e = max(0, m.start() - a.width), min(len(r["text"]), m.end() + a.width)
                by[dec].append(f"…{r['text'][s:m.start()]}**{m.group(0)}**{r['text'][m.end():e]}… — {r['creators']} {r['year']}, p. {r['page_label']}")
        decs = ["pre-1970", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
        summary.append(f"| {term} | " + " | ".join(str(len(by.get(d, []))) for d in decs) + f" | {n} | {len(srcs)} |")
        sec = [f"## {term} ({n} uses in {len(srcs)} sources)\n"]
        for d in decs + ["?"]:
            if not by.get(d): continue
            sec.append(f"**{d}** ({len(by[d])})")
            sec += [f"- {line}" for line in rnd.sample(by[d], min(a.per_decade, len(by[d])))]
            sec.append("")
        sections.append("\n".join(sec))
    path = os.path.join(a.out, "term_concordance.md")
    open(path, "w", encoding="utf-8").write("\n".join(md + summary + [""] + sections) + "\n")
    print("\n".join(summary)); print("->", path)


if __name__ == "__main__":
    main()
