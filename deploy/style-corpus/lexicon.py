#!/usr/bin/env python3
"""Word-level profile of the field corpus vs. the strands (the "verbiage" layer).

  python lexicon.py --strands ~/Strands

Writes out/lexicon.md (human report) and out/lexicon.json (used by exemplars.corpus_block):
- reporting verbs: what follows a study/author subject ("[Author] (YEAR) documented…", "the authors found…")
- hedges and boosters per 1,000 words
- register keyness: words a strand over- or under-uses relative to the field (log-likelihood), restricted to
  words that appear across many field sources, so topic words and names don't dominate
- verbs that follow "teachers" (how the field describes what teachers do)
Field side = core items, capped per source like the other norms. Nothing leaves the server.
"""
import argparse, collections, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR, PROPER
from build import CAPPED, PER_ITEM, strand_texts

SUBJ = r"(?:\[Author\](?:’s|'s)? \(YEAR\)|\[Name\]|the (?:authors?|researchers?|study|studies|survey|analysis|findings|report|data)|(?:he|she|they)|this (?:study|work|analysis|survey))"
REPORT = ("found finds argued argues contended contends noted notes observed observes reported reports showed shows "
          "documented documents traced traces described describes examined examines explored explores suggested suggests "
          "concluded concludes claimed claims identified identifies demonstrated demonstrates emphasized emphasizes "
          "maintained maintains proposed proposes insisted insists asserted asserts acknowledged acknowledges "
          "illustrated illustrates analyzed analyzes surveyed surveys interviewed interviews studied studies "
          "recounted recounts characterized characterizes framed frames located locates posited posits theorized theorizes "
          "cautioned cautions warned warns questioned questions challenged challenges extended extends complicated complicates "
          "highlighted highlights revealed reveals indicated indicates offered offers recorded records catalogued catalogs "
          "categorized categorizes compared compares measured measures tracked tracks calls called terms termed").split()
VERB_AFTER = re.compile(SUBJ + r"\s+(?:also\s+|further\s+|similarly\s+|instead\s+)?(" + "|".join(REPORT) + r")\b", re.I)
TEACHER_VERB = re.compile(r"\bteachers\s+(?:often\s+|also\s+|sometimes\s+|still\s+)?([a-z]+(?:ed|s)?)\b", re.I)
HEDGES = ["may", "might", "could", "perhaps", "possibly", "likely", "appear", "appears", "appeared", "seem", "seems",
          "suggest", "suggests", "suggested", "tend to", "tended to", "in part", "somewhat", "relatively", "arguably",
          "to some extent", "largely", "generally", "often", "frequently", "rarely"]
BOOSTERS = ["clearly", "certainly", "indeed", "undoubtedly", "obviously", "always", "never", "must", "demonstrates",
            "proves", "shows that", "of course", "in fact", "crucially", "fundamentally", "precisely"]
STOP_VERBS = set("was has is does goes comes makes takes gets gives uses needs means seems remains becomes".split())


def words_of(t):
    return re.findall(r"[a-z][a-z'\-]+", t.lower().replace("’", "'"))


def rate(text_low, phrase, n_words):
    return round(1000 * len(re.findall(r"\b" + re.escape(phrase) + r"\b", text_low)) / max(n_words, 1), 2)


def loglik(a, b, c, d):
    """Dunning log-likelihood for a word with count a in corpus 1 (size c) and b in corpus 2 (size d)."""
    e1 = c * (a + b) / (c + d); e2 = d * (a + b) / (c + d)
    ll = 0.0
    if a: ll += a * math.log(a / e1)
    if b: ll += b * math.log(b / e2)
    return 2 * ll


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands", default="~/Strands")
    ap.add_argument("--min-source-share", type=float, default=0.05)
    a = ap.parse_args()
    con = db()
    rows = con.execute(CAPPED.format(cols="item_key, text, masked", where="i.relevance='core'"), (PER_ITEM,)).fetchall()
    field = collections.Counter(); docfreq = collections.Counter(); per_item = collections.defaultdict(set)
    verbs = collections.Counter(); tverbs = collections.Counter(); fw = 0
    low_parts = []
    for r in rows:
        w = words_of(r["text"]); field.update(w); fw += len(w); per_item[r["item_key"]].update(w)
        low_parts.append(r["text"].lower())
        for m in VERB_AFTER.finditer(r["masked"]):
            v = m.group(1).lower()
            if v not in STOP_VERBS: verbs[v] += 1
        for m in TEACHER_VERB.finditer(r["text"]):
            v = m.group(1).lower()
            if v not in STOP_VERBS and len(v) > 3: tverbs[v] += 1
    for item, ws in per_item.items(): docfreq.update(ws)
    n_items = len(per_item); field_low = "\n".join(low_parts)
    proper_low = {p.lower() for p in PROPER}
    common_words = {w for w, n in docfreq.items() if n >= a.min_source_share * n_items and w not in proper_low}

    strands = strand_texts(a.strands)
    rep = {"field": {"words": fw, "sources": n_items,
                     "reporting_verbs": verbs.most_common(40), "teacher_verbs": tverbs.most_common(30),
                     "hedges_per1k": {h: rate(field_low, h, fw) for h in HEDGES},
                     "boosters_per1k": {b: rate(field_low, b, fw) for b in BOOSTERS}},
           "strands": {}}
    for name, paras in strands.items():
        short = name.split(" - ")[-1]
        txt = "\n".join(paras); low = txt.lower(); w = words_of(txt); sc = collections.Counter(w); sw = len(w)
        sv = collections.Counter(m.group(1).lower() for p in paras for m in VERB_AFTER.finditer(p) if m.group(1).lower() not in STOP_VERBS)
        over, under = [], []
        for word in common_words | {x for x in sc if x in common_words}:
            s_n, f_n = sc.get(word, 0), field.get(word, 0)
            if s_n + f_n < 5: continue
            ll = loglik(s_n, f_n, sw, fw)
            if ll < 10.83: continue  # p < .001
            ratio = (s_n / sw) / max(f_n / fw, 1e-9)
            (over if ratio > 1 else under).append((word, round(ll, 1), s_n, round(1000 * s_n / sw, 2), round(1000 * f_n / fw, 2)))
        over.sort(key=lambda x: -x[1]); under.sort(key=lambda x: -x[1])
        rep["strands"][short] = {"words": sw, "reporting_verbs": sv.most_common(15),
                                 "hedges_per1k": {h: rate(low, h, sw) for h in HEDGES},
                                 "boosters_per1k": {b: rate(low, b, sw) for b in BOOSTERS},
                                 "overused": over[:40], "underused": under[:40]}
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(rep, open(os.path.join(OUT_DIR, "lexicon.json"), "w"), indent=1)

    f = rep["field"]
    md = [f"# Word choice: your field vs. the strands\n",
          f"Field = {f['sources']} core sources, {f['words']:,} words (capped per source). Keyness uses log-likelihood (p < .001) and only words found in at least {int(a.min_source_share*100)}% of field sources, so topic words and names drop out.\n",
          "## How the field reports studies (verb after an author/study subject)\n",
          ", ".join(f"{v} ({n})" for v, n in f["reporting_verbs"][:30]), "",
          "## What teachers do, in the field's sentences (“teachers ___”)\n",
          ", ".join(f"{v} ({n})" for v, n in f["teacher_verbs"][:25]), "",
          "## Hedges and boosters per 1,000 words\n",
          "| word | field | " + " | ".join(rep["strands"]) + " |", "|---|---|" + "---|" * len(rep["strands"])]
    for h in HEDGES + BOOSTERS:
        src = "hedges_per1k" if h in HEDGES else "boosters_per1k"
        vals = [rep["strands"][s][src][h] for s in rep["strands"]]
        if f[src][h] == 0 and not any(vals): continue
        md.append(f"| {h} | {f[src][h]} | " + " | ".join(str(v) for v in vals) + " |")
    for s, d in rep["strands"].items():
        md += ["", f"## {s}", "Reporting verbs: " + (", ".join(f"{v} ({n})" for v, n in d["reporting_verbs"]) or "none found"),
               "", "**Used much more than in the field** (word: per 1k here vs field)",
               ", ".join(f"{w} {r}/{fr}" for w, _, _, r, fr in d["overused"][:30]),
               "", "**Used much less than in the field**", ", ".join(f"{w} {r}/{fr}" for w, _, _, r, fr in d["underused"][:30])]
    open(os.path.join(OUT_DIR, "lexicon.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md[:12]))
    print(f"-> {OUT_DIR}/lexicon.md")


if __name__ == "__main__":
    main()
