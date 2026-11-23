#!/usr/bin/env python3
"""Write the scholarly-register guide: one Markdown file that Claude, GPT/Codex and the ChatGPT bundle can all read.

  python register.py [--strands ~/Strands]     (run build.py all and lexicon.py first)

It holds statistics and short, generic frames only (never a published sentence), so it can travel with the
writing standards. Sections: paragraph architecture norms, how paragraphs open and close (frames by role),
sentence openers and transitions, reporting verbs, hedging, register words, the phrase screen, and a checklist.
"""
import argparse, collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR, sentences
from build import CAPPED, PER_ITEM
import arch

FRAME_N = 3
FUNC = set("the a an this these that those in on of for to with by as at from and but yet while although though when "
           "because since after before during such some many most several each both one their his her its our we they "
           "he she it there here what which who how why where however moreover thus indeed instead still also only even "
           "not no more less other another first second finally drawing building taken together across among within".split())


def frame(s, n=FRAME_N):
    """Generic opener frame: function words kept, content words -> X, placeholders kept ([Author], (YEAR), [Name])."""
    out = []
    for w in re.findall(r"\[Author\]|\[Name\]|\(YEAR\)|\(CITATION\)|[A-Za-z’'\-]+|[,;:]", s)[: n + 2]:
        lw = w.lower()
        out.append(w if w.startswith(("[", "(")) or w in ",;:" else (lw if lw in FUNC else "X"))
        if len([x for x in out if x not in ",;:"]) >= n: break
    return " ".join(out).replace(" ,", ",")


def load(name):
    p = os.path.join(OUT_DIR, name)
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands", default="~/Strands"); a = ap.parse_args()
    con = db()
    rows = con.execute(CAPPED.format(cols="masked, role, cites", where="p.source='pdf' AND i.relevance='core' AND p.words BETWEEN 60 AND 350"),
                       (PER_ITEM,)).fetchall()
    open_by = collections.defaultdict(collections.Counter); close_kind = collections.defaultdict(collections.Counter)
    sent_open = collections.Counter(); n_sent = 0; role_n = collections.Counter()
    for r in rows:
        ss = sentences(r["masked"])
        if len(ss) < 3: continue
        role_n[r["role"]] += 1
        open_by[r["role"]][frame(ss[0])] += 1
        last = ss[-1]
        kind = ("ends on a citation" if re.search(r"\(CITATION\)|\(YEAR\)|\(PAGE\)", last) else
                "ends on a quotation" if "“" in last or '"' in last else
                "ends on a concrete detail (name, number, date)" if arch.concrete(last) else
                "ends on interpretation/claim")
        close_kind[r["role"]][kind] += 1
        for s in ss[1:]:
            n_sent += 1
            m = re.match(r"^([A-Z][a-z]+(?: [a-z]+){0,2}),", s)
            if m: sent_open[m.group(1)] += 1
    prof = load("profile.json") or {}; lex = load("lexicon.json") or {}
    phrases = open(os.path.join(OUT_DIR, "field_phrases.yaml")).read() if os.path.exists(os.path.join(OUT_DIR, "field_phrases.yaml")) else ""
    f = prof.get("field_core_citing") or {}
    md = ["# Scholarly register: secondary English education, curriculum and poststructural research",
          "",
          f"Built from Austin's own Zotero library: {len(rows):,} paragraphs from core field sources (journal articles and books in English education, curriculum studies, censorship/canon/text-selection research and poststructural educational theory), capped at {PER_ITEM} paragraphs per source. Everything here is counted, not generated. It contains no published sentences, only rates and generic frames. Use it to calibrate structure and word choice. It is never a source of claims or citations.",
          "",
          "## 1. Paragraph architecture (literature-review paragraphs: 2+ citations)", "",
          "| measure | field | " + " | ".join(prof.get("strands", {}).keys()) + " |", "|---|---|" + "---|" * len(prof.get("strands", {}))]
    for k, lab in arch.LABELS.items():
        if k in f: md.append(f"| {lab} | {f[k]} | " + " | ".join(str(d.get(k, "")) for d in prof.get("strands", {}).values()) + " |")
    md += ["", "Read: in the field, about one paragraph in ten opens and closes on an abstract frame; most open on a study, text, date, decision or named position and end on evidence or the next step.", ""]
    md += ["## 2. How field paragraphs open, by what the paragraph does", "",
           "Frames are the first words of the opening sentence with content words shown as X ([Author] (YEAR) = narrative citation).", ""]
    for role, cnt in sorted(role_n.items(), key=lambda x: -x[1]):
        top = open_by[role].most_common(10); tot = sum(open_by[role].values())
        md.append(f"**{role.replace('_', ' ')}** ({cnt:,} paragraphs): " + "; ".join(f"“{fr} …” {100*c/tot:.1f}%" for fr, c in top))
        ck = close_kind[role]; ct = sum(ck.values())
        md.append("  Closes: " + "; ".join(f"{k} {100*v/ct:.0f}%" for k, v in ck.most_common()))
        md.append("")
    md += ["## 3. Sentence openers inside paragraphs (followed by a comma), per 1,000 sentences", "",
           ", ".join(f"{w} {1000*c/n_sent:.1f}" for w, c in sent_open.most_common(40)), ""]
    fl = lex.get("field", {})
    if fl:
        md += ["## 4. Reporting verbs (what follows an author or study subject)", "",
               ", ".join(f"{v} ({n})" for v, n in fl.get("reporting_verbs", [])[:40]), "",
               "What teachers do in the field's sentences (“teachers ___”): " + ", ".join(f"{v} ({n})" for v, n in fl.get("teacher_verbs", [])[:25]), "",
               "## 5. Hedges and boosters per 1,000 words", "",
               "| word | field | " + " | ".join(lex.get("strands", {}).keys()) + " |", "|---|---|" + "---|" * len(lex.get("strands", {}))]
        for grp in ("hedges_per1k", "boosters_per1k"):
            for w, v in fl.get(grp, {}).items():
                vals = [d[grp].get(w, 0) for d in lex["strands"].values()]
                if v or any(vals): md.append(f"| {w} | {v} | " + " | ".join(str(x) for x in vals) + " |")
        md += ["", "## 6. Register words each strand over- and under-uses relative to the field", "",
               "(per 1,000 words, strand / field; only words common across field sources, so names and topics drop out)", ""]
        for s, d in lex.get("strands", {}).items():
            md.append(f"**{s}.** Over: " + ", ".join(f"{w} {r}/{fr}" for w, _, _, r, fr in d["overused"][:20]))
            md.append(f"Under: " + ", ".join(f"{w} {r}/{fr}" for w, _, _, r, fr in d["underused"][:20]))
            md.append("")
    if phrases:
        never = re.findall(r"^  - (\".*\")$", phrases.split("use_sparingly:")[0], re.M)
        normal = re.findall(r"^  - (\".*\")$", phrases.split("field_normal:")[-1], re.M) if "field_normal:" in phrases else []
        md += ["## 7. Phrase screen (AI-typical phrases measured against the field)", "",
               f"Never introduce ({len(never)}): " + ", ".join(json.loads(x) for x in never), "",
               f"Common in the field, so fine in moderation ({len(normal)}): " + ", ".join(json.loads(x) for x in normal), ""]
    md += ["## 8. Checklist for a revision", "",
           "- Open on the concrete: the study, text, district, date, decision or named position. Keep interpretation for the second half.",
           "- End on evidence or the hand-off to the next paragraph, not a sentence restating the opener.",
           "- Report studies with the field's verbs (section 4); keep the author's interpretation distinct from the results and from your synthesis.",
           "- Hedge at the field's rate (section 5): one hedge where the evidence is partial, not a caveat in every paragraph.",
           "- No corrective antithesis (“X, not Y”; “not X but Y”; “rather than”) and no tagline after a colon.",
           "- Vary sentence length the way the field does (sentence-length SD in section 1).",
           "- Direct quotation: author, year, verified page. Paraphrase: author and year, no page. Unverified: [CHECK].", ""]
    path = os.path.join(OUT_DIR, "register_guide.md")
    open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"-> {path} ({len(md)} lines)")


if __name__ == "__main__":
    main()
