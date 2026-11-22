#!/usr/bin/env python3
"""Build the derived layers of the style corpus.

  python build.py embed                       # sentence embeddings for exemplar retrieval (fastembed, local CPU)
  python build.py cliches --list ai_cliches_corpus.json --strands ~/Strands
  python build.py profile --strands ~/Strands  # field paragraph-architecture baseline vs each strand
  python build.py all --list … --strands …

Outputs go to ~/style_corpus/out/. Nothing leaves the server.
"""
import argparse, glob, json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, EMB_PATH, EMB_IDS, OUT_DIR, HOME, docx_paragraphs, words
import arch

EMB_MODEL = os.environ.get("STYLE_CORPUS_EMB_MODEL", "BAAI/bge-small-en-v1.5")


def exemplar_rows(con):
    return con.execute("""SELECT p.id, p.masked FROM paras p JOIN items i ON i.key=p.item_key
                          WHERE p.source='pdf' AND p.words BETWEEN 60 AND 350 AND i.relevance IN ('core','adjacent')
                          ORDER BY p.id""").fetchall()


def cmd_embed(a):
    import numpy as np
    try:
        from fastembed import TextEmbedding
    except ImportError:
        sys.exit("fastembed isn't installed in this venv; exemplar retrieval will fall back to keyword (FTS5) search.")
    con = db(); rows = exemplar_rows(con)
    print(f"embedding {len(rows):,} paragraphs with {EMB_MODEL}…", flush=True)
    model = TextEmbedding(EMB_MODEL)
    vecs = []
    texts = [r["masked"] for r in rows]
    for i, v in enumerate(model.embed(texts, batch_size=64)):
        vecs.append(v)
        if i and i % 5000 == 0: print(f"  {i:,}", flush=True)
    M = np.asarray(vecs, dtype="float32")
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    np.save(EMB_PATH, M.astype("float16")); np.save(EMB_IDS, np.asarray([r["id"] for r in rows], dtype="int64"))
    con.execute("INSERT OR REPLACE INTO meta VALUES('emb_model', ?)", (EMB_MODEL,)); con.commit()
    print(f"saved {M.shape} -> {EMB_PATH}")


# ------------------------------------------------------------------- phrase rates
def usable(term):
    return not re.search(r"[\[\]{}<>]|\.\.\.|…|\bX\b|\bY\b", term) and 1 <= len(term.split()) <= 8 and len(term) > 2


def term_rx(term):
    t = term.lower().strip().rstrip(".!?:,")
    t = t.replace("’", "'")
    parts = [re.escape(w) for w in t.split()]
    if len(parts) == 1:
        return re.compile(r"\b" + parts[0] + r"(?:s|es|d|ed|ing|ly)?\b")
    parts[-1] += r"(?:s|es|d|ed|ing)?"
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


def strand_texts(folder):
    out = {}
    for f in sorted(glob.glob(os.path.join(os.path.expanduser(folder), "Strand *.docx"))):
        if os.path.basename(f).startswith("~$"): continue
        out[os.path.splitext(os.path.basename(f))[0]] = [p["text"] for p in docx_paragraphs(f) if not p["heading"]]
    return out


def cmd_cliches(a):
    src = json.load(open(os.path.expanduser(a.list), encoding="utf-8"))
    entries = [e for e in src["entries"] if e.get("category_key") in ("words_and_phrases", "sentence_patterns", "rhetorical_and_structural_moves")
               and usable(e["term"])]
    con = db()
    groups = {}
    for rel in ("core", "adjacent", "other"):
        rows = con.execute("SELECT p.text, p.words FROM paras p JOIN items i ON i.key=p.item_key WHERE i.relevance=?", (rel,)).fetchall()
        groups[rel] = ("\n".join(r["text"] for r in rows).lower().replace("’", "'"), sum(r["words"] for r in rows))
    strands = strand_texts(a.strands) if a.strands else {}
    st_text = {k: ("\n".join(v).lower().replace("’", "'"), sum(len(words(x)) for x in v)) for k, v in strands.items()}
    print("words: " + ", ".join(f"{k} {w:,}" for k, (_, w) in groups.items()) + "; strands " + ", ".join(f"{k.split(' - ')[-1]} {w:,}" for k, (_, w) in st_text.items()), flush=True)
    res = []
    for e in entries:
        rx = term_rx(e["term"])
        row = {"term": e["term"], "category": e["category"], "confidence": e["confidence"], "ai_strength": e.get("strength_score"),
               "ai_ratio": e.get("study_ratio")}
        for rel, (txt, w) in groups.items():
            n = len(rx.findall(txt)) if w else 0
            row[f"{rel}_n"] = n; row[f"{rel}_pm"] = round(1e6 * n / w, 2) if w else None
        row["strands"] = {k.split(" - ")[-1]: len(rx.findall(t)) for k, (t, _) in st_text.items()}
        pm = row["core_pm"] if row["core_pm"] is not None else 0
        row["field_status"] = "rare_in_field" if pm < a.rare else "uncommon_in_field" if pm < a.normal else "field_normal"
        res.append(row)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({"thresholds_per_million": {"rare_below": a.rare, "normal_from": a.normal}, "core_words": groups["core"][1],
               "entries": res}, open(os.path.join(OUT_DIR, "cliche_field_rates.json"), "w"), indent=1)
    # compact standards file the review prompts can carry
    plain = lambda r: r["category"] == "Words & phrases" and not re.search(r"[\"“”?!:]", r["term"])
    never = sorted({r["term"] for r in res if plain(r) and r["field_status"] == "rare_in_field" and (len(r["term"].split()) > 1 or r["confidence"] == "red")}, key=str.lower)
    sparing = sorted({r["term"] for r in res if r["field_status"] == "uncommon_in_field"}, key=str.lower)
    normal = sorted({r["term"] for r in res if r["field_status"] == "field_normal"}, key=str.lower)
    y = ["# Field phrase screen (generated by style-corpus build.py; do not hand-edit)",
         f"# AI-overused phrases counted in {groups['core'][1]:,} words of published scholarship in Austin's field.",
         f"# rare = under {a.rare} per million words there; uncommon = under {a.normal}.",
         "never_introduce:  # AI-typical and rare in the field: suggestions must not add these",
         *[f"  - {json.dumps(t)}" for t in never],
         "use_sparingly:  # uncommon in the field: fine once, a flag when repeated",
         *[f"  - {json.dumps(t)}" for t in sparing],
         "field_normal:  # common in published field writing; NOT slop by themselves",
         *[f"  - {json.dumps(t)}" for t in normal]]
    open(os.path.join(OUT_DIR, "field_phrases.yaml"), "w").write("\n".join(y) + "\n")
    # human report
    md = [f"# AI-phrase list vs. field corpus\n", f"Field (core) corpus: {groups['core'][1]:,} words. Rates per million words.\n",
          "## Phrases in the current strands\n", "| phrase | AI tell | field rate | status | " + " | ".join(k.split(' - ')[-1] for k in st_text) + " |",
          "|---|---|---|---|" + "---|" * len(st_text)]
    for r in sorted(res, key=lambda r: (-sum(r["strands"].values()), r["term"])):
        if sum(r["strands"].values()) == 0: continue
        md.append(f"| {r['term']} | {r['confidence']} | {r['core_pm']} | {r['field_status'].replace('_', ' ')} | " + " | ".join(str(v) for v in r["strands"].values()) + " |")
    md += ["", f"## Never introduce ({len(never)})", ", ".join(never), "", f"## Common in your field, so not flagged ({len(normal)})", ", ".join(normal)]
    open(os.path.join(OUT_DIR, "cliche_report.md"), "w").write("\n".join(md) + "\n")
    print(f"never_introduce {len(never)}, use_sparingly {len(sparing)}, field_normal {len(normal)} -> {OUT_DIR}")


# ------------------------------------------------------------------- architecture profile
def cmd_profile(a):
    con = db()
    base = """SELECT p.text, p.role, p.cites FROM paras p JOIN items i ON i.key=p.item_key
              WHERE p.source='pdf' AND i.relevance=? AND p.words BETWEEN 50 AND 400"""
    rows = con.execute(base, ("core",)).fetchall()
    prof = {"field_core_all": arch.summarize([r["text"] for r in rows]),
            "field_core_citing": arch.summarize([r["text"] for r in rows if r["cites"] >= 2]),
            "by_role": {}}
    for role in sorted({r["role"] for r in rows}):
        sub = [r["text"] for r in rows if r["role"] == role]
        if len(sub) >= 30: prof["by_role"][role] = arch.summarize(sub)
    prof["strands"] = {k.split(" - ")[-1]: arch.summarize(v) for k, v in (strand_texts(a.strands).items() if a.strands else [])}
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(prof, open(os.path.join(OUT_DIR, "profile.json"), "w"), indent=1)
    cols = [("Field (all)", prof["field_core_all"]), ("Field (citing ¶s)", prof["field_core_citing"])] + list(prof["strands"].items())
    md = ["# Paragraph architecture: your field vs. the strands\n",
          "Same rules as slop_audit.py. 'Field (citing ¶s)' = paragraphs with two or more citations, the closest match to literature-review prose.\n",
          "| measure | " + " | ".join(c for c, _ in cols) + " |", "|---|" + "---|" * len(cols)]
    for k, lab in arch.LABELS.items():
        md.append(f"| {lab} | " + " | ".join(str(d.get(k, "")) for _, d in cols) + " |")
    md.append("| Paragraphs | " + " | ".join(str(d.get("paragraphs", "")) for _, d in cols) + " |")
    open(os.path.join(OUT_DIR, "profile.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("embed")
    c = sub.add_parser("cliches"); c.add_argument("--list", default=os.path.join(HOME, "ai_cliches_corpus.json"))
    c.add_argument("--strands", default="~/Strands"); c.add_argument("--rare", type=float, default=2.0); c.add_argument("--normal", type=float, default=10.0)
    p = sub.add_parser("profile"); p.add_argument("--strands", default="~/Strands")
    al = sub.add_parser("all"); al.add_argument("--list", default=os.path.join(HOME, "ai_cliches_corpus.json"))
    al.add_argument("--strands", default="~/Strands"); al.add_argument("--rare", type=float, default=2.0); al.add_argument("--normal", type=float, default=10.0)
    a = ap.parse_args()
    if a.cmd == "all":
        try: cmd_embed(a)
        except SystemExit as e: print(e)
        cmd_cliches(a); cmd_profile(a)
    else:
        {"embed": cmd_embed, "cliches": cmd_cliches, "profile": cmd_profile}[a.cmd](a)
