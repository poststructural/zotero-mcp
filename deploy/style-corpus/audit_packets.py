#!/usr/bin/env python3
"""Source-audit extracts: for every study a strand cites, the passages in its PDF that state purpose, method,
sample/setting, findings and limitations, each with its PRINTED page number.

  python audit_packets.py [--strands ~/Strands] [--strand "Text Selection"] [--per-field 3] [--no-share]

Citations are read and matched to Zotero items the same way as quote_check.py (sr_common). Page numbers come
from the printed page mapping of each cited PDF (running headers/footers, then PDF labels, then the Zotero page
range; 'pdf N' when none could be read). Reference lists, notes and bibliography entries are skipped.
These are extracts for Austin to verify against the PDF (SOURCE AUDIT mode), never summaries to cite.
"""
import argparse, collections, os, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sr_common as c

FIELDS = {
    "purpose": (r"\b(purpose of (?:this|the|our) (?:study|article|paper|research|chapter|book)|(?:this|the present|our) (?:study|article|paper|chapter|book|essay) (?:examines|explores|investigates|asks|argues|reports|describes|considers|traces|analy[sz]es)|research questions?|we (?:ask|examine|explore|investigate|argue)|(?:aim|goal)s? of (?:this|the|our) (?:study|article|research)|in this (?:article|study|paper|chapter|book), (?:I|we))\b",
                r"^(introduction|purpose|research questions?|overview|abstract)\b"),
    "method": (r"\b(method(?:s|ology)?|data (?:collection|sources|analysis)|we (?:interviewed|surveyed|observed|coded|analy[sz]ed|collected)|semi-structured|case study|ethnograph\w*|grounded theory|discourse analysis|content analysis|questionnaire|survey (?:instrument|items|was)|thematic(?:ally)? analy\w+|archival|interviews? (?:were|with))\b",
               r"^(method|methods|methodology|research design|data|data (?:collection|sources|analysis)|procedures?|analysis)\b"),
    "sample": (r"\b(participants? (?:were|included|ranged)|respondents? (?:were|included)|n\s*=\s*\d+|\d+\s+(?:teachers|students|schools|districts|librarians|respondents|participants|interviews)|(?:high|secondary|middle) schools? in|(?:the|our) sample|recruited|setting)\b",
               r"^(participants|sample|setting|context|site|participants and setting)\b"),
    "findings": (r"\b(findings? (?:show|indicate|suggest|reveal)|results? (?:show|indicate|suggest|reveal)|we found|(?:the|our) (?:data|analysis) (?:show|indicate|suggest|reveal)|most (?:teachers|respondents|participants)|(?:teachers|participants|respondents) (?:reported|described|explained))\b",
                 r"^(findings|results|discussion|key findings)\b"),
    "limits": (r"\b(limitations? (?:of|include)|(?:is|are|was|were) limited (?:by|to|in)|cannot be generali[sz]ed|generali[sz]ab\w+|small sample|self-report\w*|future research (?:should|could|might))\b",
               r"^(limitations?|limits)\b"),
}
FIELDS_ANY = re.compile("|".join(v[1].lstrip("^") for v in FIELDS.values()), re.I)
REF_SECTION = re.compile(r"^(references?|bibliography|works cited|notes|endnotes|footnotes|sources|literature cited)\b", re.I)
REF_ENTRY = re.compile(r"\((?:1[6-9]|20)\d{2}[a-z]?\)\.|\b(?:1[6-9]|20)\d{2}[a-z]?\.\s+[A-Z“\"]|Retrieved from|doi\.org|https?://|\bpp\.\s*\d+\s*[–-]\s*\d+|\bVol\.\s*\d+|\b\d+\(\d+\),\s*\d+")


def is_reference(text, section):
    if REF_SECTION.search((section or "").strip()): return True
    n = len(REF_ENTRY.findall(text))
    return n >= 2 or (n >= 1 and len(text.split()) < 40)


def page_of(text, normed, start=0):
    """Index of the PDF page holding a stored paragraph: locate its opening words."""
    w = c.norm(text).split()
    for L in (12, 8, 5):
        if len(w) < L: continue
        probe = " ".join(w[:L])
        for k in range(len(normed)):
            i = (start + k) % len(normed)
            if probe in normed[i][1]: return i
    return None


def snippet(text, rx, width=650):
    if len(text) <= width: return text
    m = re.search(rx, text, re.I)
    if not m: return text[:width] + "…"
    a = max(0, m.start() - width // 3); b = min(len(text), a + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def packet(con, it, per_field):
    rows = con.execute("SELECT text, section, page_label FROM paras WHERE item_key=? ORDER BY seq", (it["key"],)).fetchall()
    pages = c.pdf_pages(it)
    normed = [(pr, c.norm(t)) for _, pr, t in pages]
    scored = {f: [] for f in FIELDS}
    last = skipped = 0; in_refs = False
    for seq, r in enumerate(rows):
        sec = (r["section"] or "").strip()
        if REF_SECTION.search(sec): in_refs = True
        elif sec and in_refs and FIELDS_ANY.search(sec): in_refs = False
        if in_refs or is_reference(r["text"], sec): skipped += 1; continue
        pi = page_of(r["text"], normed, last) if normed else None
        if pi is not None: last = pi
        page = normed[pi][0] if pi is not None else (("pdf " + r["page_label"]) if r["page_label"] else "?")
        pos = seq / max(1, len(rows))
        for f, (rx, sec_rx) in FIELDS.items():
            n = len(re.findall(rx, r["text"], re.I))
            s = n + (3 if re.search(sec_rx, sec, re.I) else 0)
            if f == "purpose" and n and pos < 0.25: s += 1
            if f == "limits" and n and pos > 0.6: s += 1
            if s and len(r["text"].split()) >= 25: scored[f].append((s, seq, page, r["text"], sec))
    for f in scored: scored[f].sort(key=lambda x: (-x[0], x[1])); scored[f] = scored[f][:per_field]
    return scored, skipped, bool(pages)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands"); ap.add_argument("--strand")
    ap.add_argument("--per-field", type=int, default=3); ap.add_argument("--no-share", action="store_true")
    a = ap.parse_args()
    if a.strands: c.STRANDS_DIR = os.path.expanduser(a.strands); c.SHARE = os.path.join(c.STRANDS_DIR, "Corpus reports")
    con = c.ro_db(); os.makedirs(c.OUT, exist_ok=True)
    for name, stem in c.STRANDS:
        if a.strand and a.strand.lower() not in name.lower(): continue
        cites = collections.OrderedDict()
        for p in c.strand_paras(stem):
            for sn, yr, *_ in c.citations(p["text"]): cites.setdefault((sn, yr[:4]), None)
        found, missing, seen = [], [], set()
        for (sn, yr) in cites:
            items = c.resolve(con, sn, yr)
            if not items:
                # title words caught before a year: only report if no other name for that year matched
                if not any(c.resolve(con, s2, y2) for s2, y2 in cites if y2 == yr and s2 != sn):
                    missing.append(f"{' & '.join(sn)} {yr}")
                continue
            for it in items[:2]:
                if it["key"] not in seen: seen.add(it["key"]); found.append(it)
        missing = sorted(set(missing))
        md = [f"# Source-audit extracts: {name}", "",
              "For each study the strand cites, the passages in its PDF (from your Zotero) that state its purpose, method, sample/setting, "
              "findings and limitations, with the **printed page** where it could be read from the PDF (`pdf N` = the PDF's own page, "
              "`~` = inferred from the Zotero page range; confirm both by eye). Reference lists and notes are skipped. "
              "These are locators to verify, never summaries to cite.", "",
              f"**{len(found)} cited sources matched to your library; {len(missing)} citations not matched** "
              "(often institutions, statutes, news items, or works without a PDF): " + ", ".join(missing), ""]
        for it in found:
            if it["status"] != "done":
                md += [f"## {c.cite_label(it)}. {it['title']}", f"*{it['venue'] or ''}* · {it['item_type']} · no extracted text (status: {it['status']}); read the PDF directly.", ""]
                continue
            pk, skipped, has_pdf = packet(con, it, a.per_field)
            md += [f"## {c.cite_label(it)}. {it['title']}",
                   f"*{it['venue'] or ''}* · {it['item_type']}" + ("" if has_pdf else " · no PDF file, so no printed pages (Zotero text only)")
                   + (f" · {skipped} reference/note paragraphs skipped" if skipped else ""), ""]
            for f, hits in pk.items():
                md.append(f"**{f}**")
                if not hits: md.append("- (nothing matched; read the PDF)")
                for s, seq, page, text, sec in hits:
                    md.append(f"- p. {page}" + (f" ({sec[:40]})" if sec else "") + f": {snippet(text, FIELDS[f][0])}")
                md.append("")
        path = os.path.join(c.OUT, f"audit_extracts_{name.replace(' ', '_')}.md")
        open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
        if not a.no_share:
            os.makedirs(c.SHARE, exist_ok=True); shutil.copy(path, os.path.join(c.SHARE, os.path.basename(path)))
        print(f"{name}: {len(found)} sources matched, {len(missing)} citations not matched -> {path}", flush=True)


if __name__ == "__main__":
    main()
