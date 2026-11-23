#!/usr/bin/env python3
"""Source-audit extracts: for every study a strand cites, the passages in its PDF that state purpose, method,
sample/setting, findings and limitations, each with its page label.

  python audit_packets.py --strands ~/Strands [--strand "Text Selection"] [--per-field 3]

These are extracts for Austin to verify against the PDF (SOURCE AUDIT mode), never summaries to cite. Citations
not matched to an extracted PDF are listed so the gaps are visible.
"""
import argparse, collections, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, OUT_DIR, YEAR
from build import strand_texts

CITE = re.compile(r"\b([A-Z][A-Za-z’'\-]+)(?:,?\s+(?:and|&)\s+([A-Z][A-Za-z’'\-]+)|\s+et\s+al\.)?(?:’s|'s)?,?\s+\(?((?:1[6-9]|20)\d{2})[a-z]?\b")
FIELDS = {
    "purpose": r"\b(purpose of (?:this|the|our) (?:study|article|paper|research)|this (?:study|article|paper) (?:examines|explores|investigates|asks|argues|reports)|research questions?|we (?:ask|examine|explore|investigate)|(?:aim|goal) of (?:this|the) (?:study|article))\b",
    "method": r"\b(method(?:s|ology)?|data (?:collection|sources|analysis)|we (?:interviewed|surveyed|observed|coded|analy[sz]ed)|semi-structured|case study|ethnograph\w*|grounded theory|discourse analysis|content analysis|questionnaire|coding)\b",
    "sample": r"\b(participants?|respondents?|n\s*=\s*\d+|\d+\s+(?:teachers|students|schools|districts|librarians|respondents)|(?:high|secondary|middle) schools? in|sample)\b",
    "findings": r"\b(findings?|results? (?:show|indicate|suggest)|we found|(?:the|our) (?:data|analysis) (?:show|indicate|suggest|reveal)|most (?:teachers|respondents|participants))\b",
    "limits": r"\b(limitations?|limited (?:by|to)|caution|cannot be generali[sz]ed|generali[sz]ability|small sample|future research)\b",
}
STOPCAP = set("In The This These For See As At On And Of A An But While When Since After Before".split())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--strands", default="~/Strands"); ap.add_argument("--strand")
    ap.add_argument("--per-field", type=int, default=3); ap.add_argument("--out", default=os.path.join(OUT_DIR, "reports"))
    a = ap.parse_args(); con = db(); os.makedirs(a.out, exist_ok=True)
    for name, paras in strand_texts(a.strands).items():
        short = name.split(" - ")[-1]
        if a.strand and a.strand.lower() not in short.lower(): continue
        cites = collections.OrderedDict()
        for par in paras:
            for m in CITE.finditer(par):
                n1 = re.sub(r"(’s|'s)$", "", m.group(1))
                if n1 in STOPCAP: continue
                cites.setdefault((n1, m.group(3)), set()).add(m.group(2))
        md = [f"# Source-audit extracts: {short}\n",
              "Passages pulled from each cited study's PDF in your library, with page labels. Verify each against the PDF; "
              "these are locators, not summaries to cite. Page labels come from the PDF (printed page when the PDF has labels).\n"]
        missing, done = [], 0
        for (surname, year), _ in cites.items():
            items = con.execute("SELECT key, title, creators, year, venue, item_type FROM items WHERE year=? AND status='done' AND lower(creators) LIKE ?",
                                (year, f"%{surname.lower()}%")).fetchall()
            if not items: missing.append(f"{surname} {year}"); continue
            it = items[0]; done += 1
            md.append(f"## {it['creators']} ({it['year']}). {it['title']}\n*{it['venue'] or ''}* · {it['item_type']}\n")
            paras_rows = con.execute("SELECT text, page_label, section FROM paras WHERE item_key=? ORDER BY seq", (it["key"],)).fetchall()
            for field, rx in FIELDS.items():
                hits = []
                for r in paras_rows:
                    n = len(re.findall(rx, r["text"], re.I))
                    sec = 2 if re.search(field if field != "limits" else "limit", r["section"] or "", re.I) else 0
                    if n or sec: hits.append((n + sec, r))
                hits.sort(key=lambda x: -x[0])
                md.append(f"**{field}**")
                if not hits: md.append("- (nothing matched; read the PDF)")
                for _, r in hits[:a.per_field]:
                    t = r["text"]; t = t if len(t) < 700 else t[:700] + "…"
                    md.append(f"- p. {r['page_label']} ({(r['section'] or '')[:40]}): {t}")
                md.append("")
        md.insert(2, f"**{done} cited sources found in the corpus; {len(missing)} not found:** " + ", ".join(missing) + "\n")
        path = os.path.join(a.out, f"audit_extracts_{short.replace(' ', '_')}.md")
        open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
        print(f"{short}: {done} sources extracted, {len(missing)} not in corpus -> {path}")


if __name__ == "__main__":
    main()
