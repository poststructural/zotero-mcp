#!/usr/bin/env python3
"""Paragraph-by-paragraph review of a strand, used by serve_dashboard.py.

Reads a strand .docx, lines its paragraphs up with the Nov 18 baseline copy in
_dashboard/baseline/, and makes small, safe changes to the .docx:
accept (clear green highlight), set the text of one paragraph (keeping italics
and bold where the words are unchanged), restore a removed paragraph, delete a
paragraph. Before the first change of the day it saves a dated copy in
_versions/. It refuses to write while the file is open in Word.
Standard library only.
"""
import datetime as dt, difflib, hashlib, html, json, os, re, shutil, zipfile

P_RE = re.compile(r"<w:p(?: [^>]*)?>.*?</w:p>|<w:p(?: [^>]*)?/>", re.S)
R_RE = re.compile(r"<w:r(?: [^>]*)?>(.*?)</w:r>", re.S)
RPR_RE = re.compile(r"^\s*(<w:rPr>.*?</w:rPr>|<w:rPr/>)", re.S)
PIECE_RE = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>|<w:t(?: [^>]*)?/>|<w:tab/>|<w:br/>", re.S)
GREEN = re.compile(r'<w:highlight w:val="green"/>')
NOTES_START = re.compile(r"^(Revision notes|Revision Notes|\[Transition|Appendix:)")
CHECK = re.compile(r"\[CHECK[^\]]*\]")
SAFE_TAGS = {"w:p", "w:pPr", "w:pStyle", "w:r", "w:rPr", "w:t", "w:tab", "w:br", "w:b", "w:bCs", "w:i",
             "w:iCs", "w:highlight", "w:ind", "w:spacing", "w:keepNext", "w:numPr", "w:ilvl", "w:numId",
             "w:rStyle", "w:jc", "w:u", "w:sz", "w:szCs", "w:rFonts", "w:color", "w:lang", "w:proofErr",
             "w:bookmarkStart", "w:bookmarkEnd", "w:keepLines", "w:widowControl", "w:caps", "w:smallCaps",
             "w:vertAlign", "w:noProof"}


class Conflict(Exception): pass
class Refused(Exception): pass


def unesc(s): return html.unescape(s)
def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def sha(s): return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


# ---------- reading ----------
def read_xml(path):
    with zipfile.ZipFile(path) as z: return z.read("word/document.xml").decode("utf-8")

def runs_of(pxml):
    """[(rPr, text)] for each run; text uses \\t for tabs and \\n for breaks."""
    out = []
    for m in R_RE.finditer(pxml):
        inner = m.group(1)
        rp = RPR_RE.match(inner); rpr = rp.group(1) if rp else ""
        rest = inner[rp.end():] if rp else inner
        txt = []
        for pm in PIECE_RE.finditer(rest):
            tok = pm.group(0)
            if tok.startswith("<w:tab"): txt.append("\t")
            elif tok.startswith("<w:br"): txt.append("\n")
            elif pm.group(1) is not None: txt.append(unesc(pm.group(1)))
        out.append((rpr, "".join(txt)))
    return out

def para_info(pxml):
    runs = runs_of(pxml)
    text = "".join(t for _, t in runs)
    st = re.search(r'<w:pStyle w:val="([^"]+)"', pxml)
    return {"runs": runs, "text": text, "style": st.group(1) if st else ""}

def is_heading(text, style):
    t = text.strip()
    return bool(t) and (style.lower().startswith(("heading", "title")) or
                        (len(t.split()) < 14 and not t.endswith((".", "]", ":")) and not t.startswith("[")))

def paragraphs(path):
    xml = read_xml(path); out = []; notes = False; section = ""
    for i, m in enumerate(P_RE.finditer(xml)):
        info = para_info(m.group(0)); t = info["text"].strip()
        if t and NOTES_START.match(t): notes = True
        head = is_heading(t, info["style"])
        if head and not notes: section = t
        info.update(i=i, notes=notes, heading=head, section=section, xml=m.group(0),
                    green=bool(GREEN.search(m.group(0))))
        out.append(info)
    return out


# ---------- lining up with the baseline ----------
def toks(s): return re.findall(r"\s+|[^\s]+", s)

def ratio(a, b):
    sm = difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False)
    return sm.ratio()

def align(cur, base):
    """For each current paragraph index -> baseline paragraph (or None).
    Also returns baseline paragraphs that were removed, keyed by the current index they follow."""
    c = [p for p in cur if p["text"].strip()]
    b = [p for p in base if p["text"].strip()]
    match, removed = {}, {}
    sm = difflib.SequenceMatcher(None, [p["text"] for p in c], [p["text"] for p in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1): match[c[i1 + k]["i"]] = b[j1 + k]
            continue
        used = set()
        for ci in range(i1, i2):
            best, bj = 0.0, None
            for bjj in range(j1, j2):
                if bjj in used: continue
                r = ratio(c[ci]["text"], b[bjj]["text"])
                if r > best: best, bj = r, bjj
            if bj is not None and best >= 0.45:
                match[c[ci]["i"]] = b[bj]; used.add(bj)
        after = c[i1 - 1]["i"] if i1 > 0 else -1
        for bjj in range(j1, j2):
            if bjj not in used: removed.setdefault(after, []).append(b[bjj])
    return match, removed

def diff_html(old, new):
    a, b = toks(old), toks(new); out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal": out.append(html.escape("".join(a[i1:i2])))
        if op in ("delete", "replace"): out.append(f'<del>{html.escape("".join(a[i1:i2]))}</del>')
        if op in ("insert", "replace"): out.append(f'<ins>{html.escape("".join(b[j1:j2]))}</ins>')
    return "".join(out)

def runs_html(runs):
    out = []
    for rpr, t in runs:
        h = html.escape(t).replace("\n", "<br>")
        h = CHECK.sub(lambda m: f'<mark class="chk">{m.group(0)}</mark>', h)
        if re.search(r"<w:i/>|<w:i w:val=\"(1|true)\"/>", rpr): h = f"<i>{h}</i>"
        if re.search(r"<w:b/>|<w:b w:val=\"(1|true)\"/>", rpr): h = f"<b>{h}</b>"
        if 'w:val="green"' in rpr: h = f'<span class="grn">{h}</span>'
        elif 'w:val="yellow"' in rpr: h = f'<span class="ylw">{h}</span>'
        out.append(h)
    return "".join(out)


# ---------- writing ----------
def lock_open(path):
    d, f = os.path.split(path)
    for n in os.listdir(d):
        if n.startswith("~$") and (f.endswith(n[2:]) or n[2:] in f):
            return True
    return False

def snapshot(path, root):
    vd = os.path.join(root, "_versions"); os.makedirs(vd, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(vd, f"{stem} ({dt.date.today().isoformat()} before dashboard review).docx")
    if not os.path.exists(dest): shutil.copy2(path, dest)

def write_xml(path, xml):
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = xml.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename)
            zout.writestr(item, data)
    try:
        os.replace(tmp, path)
    except PermissionError:
        os.remove(tmp); raise Refused("Word has the file open. Close it in Word and try again.")

def locate(xml, idx, expect_text):
    spans = list(P_RE.finditer(xml))
    if not (0 <= idx < len(spans)): raise Conflict("The document changed. Reloading…")
    m = spans[idx]
    if para_info(m.group(0))["text"] != expect_text: raise Conflict("The document changed since this page loaded. Reloading…")
    return m

def build_runs(chars):
    """chars: [(ch, rPr)] -> run XML, grouping equal formatting."""
    out, i = [], 0
    while i < len(chars):
        rpr = chars[i][1]; j = i
        while j < len(chars) and chars[j][1] == rpr: j += 1
        seg = "".join(c for c, _ in chars[i:j]); body = []
        for part in re.split(r"(\t|\n)", seg):
            if part == "\t": body.append("<w:tab/>")
            elif part == "\n": body.append("<w:br/>")
            elif part: body.append(f'<w:t xml:space="preserve">{esc(part)}</w:t>')
        out.append(f"<w:r>{rpr}{''.join(body)}</w:r>")
        i = j
    return "".join(out)

def strip_green(rpr):
    r = GREEN.sub("", rpr)
    return "" if r in ("<w:rPr></w:rPr>",) else r

def new_paragraph_xml(pxml, new_text):
    tags = set(re.findall(r"<(w:[A-Za-z]+)", pxml))
    odd = tags - SAFE_TAGS
    if odd: raise Refused("This paragraph has Word features the dashboard can't edit safely (" + ", ".join(sorted(odd)) + "). Leave a note for Claude instead.")
    runs = runs_of(pxml)
    chars = [(ch, rpr) for rpr, t in runs for ch in t]
    old = "".join(c for c, _ in chars)
    a, b = toks(old), toks(new_text)
    offs, o = [], 0
    for t in a: offs.append(o); o += len(t)
    default = chars[0][1] if chars else ""
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            s, e = offs[i1], (offs[i2] if i2 < len(offs) else len(old))
            out += chars[s:e]
        else:
            if i1 < len(offs): fmt = chars[offs[i1]][1]
            elif chars: fmt = chars[-1][1]
            else: fmt = default
            out += [(ch, fmt) for ch in "".join(b[j1:j2])]
    out = [(ch, strip_green(f)) for ch, f in out]
    head = re.match(r"<w:p(?: [^>]*)?>", pxml).group(0)
    ppr = re.search(r"<w:pPr>.*?</w:pPr>|<w:pPr/>", pxml, re.S)
    return head + (ppr.group(0) if ppr else "") + build_runs(out) + "</w:p>"

def change(path, root, op, idx, expect, new_text=None, base_xml=None):
    if lock_open(path): raise Refused("The file is open in Word. Close it there and try again.")
    xml = read_xml(path)
    m = locate(xml, idx, expect)
    p = m.group(0)
    if op == "accept":
        newp = GREEN.sub("", p)
    elif op == "set_text":
        newp = new_paragraph_xml(p, new_text)
    elif op == "delete":
        newp = ""
    elif op == "restore":
        if not base_xml: raise Refused("Nothing to restore.")
        newp = p + base_xml
    else:
        raise Refused("Unknown action.")
    snapshot(path, root)
    write_xml(path, xml[:m.start()] + newp + xml[m.end():])
    return newp


# ---------- review state (what Austin has looked at) ----------
def state_path(root): return os.path.join(root, "_dashboard", "review_state.json")

def load_state(root):
    try:
        with open(state_path(root), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def save_state(root, st):
    tmp = state_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(st, f, indent=1)
    os.replace(tmp, state_path(root))

def mark(root, strand, text, value=True):
    st = load_state(root); s = st.setdefault(strand, {}); rv = set(s.get("reviewed", []))
    (rv.add if value else rv.discard)(sha(text))
    s["reviewed"] = sorted(rv); save_state(root, st)

def add_note(root, strand, text, note):
    st = load_state(root); s = st.setdefault(strand, {})
    s.setdefault("notes", {}).setdefault(sha(text), []).append(
        {"note": note, "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
    save_state(root, st)

def baseline_for(root, stem):
    bd = os.path.join(root, "_dashboard", "baseline")
    if not os.path.isdir(bd): return None
    c = [os.path.join(bd, f) for f in os.listdir(bd) if f.startswith(stem) and f.endswith(".docx")]
    return sorted(c)[-1] if c else None

def progress(root, strand, stem):
    path = os.path.join(root, stem + ".docx")
    if not os.path.exists(path): return None
    rv = set(load_state(root).get(strand, {}).get("reviewed", []))
    body = [p for p in paragraphs(path) if p["text"].strip() and not p["notes"]]
    done = sum(1 for p in body if sha(p["text"]) in rv)
    return done, len(body), pending_count(root, stem)


# ---------- Claude's suggestions ----------
# _dashboard/suggestions/<strand stem>.json : list of
#   {"id": "c1", "old": "exact text now in one paragraph", "new": "replacement" (or null for a comment only),
#    "why": "reason", "date": "YYYY-MM-DD", "status": "pending" | "accepted" | "edited" | "rejected"}
def sugg_path(root, stem): return os.path.join(root, "_dashboard", "suggestions", stem + ".json")

def load_sugg(root, stem):
    try:
        with open(sugg_path(root, stem), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return []

def save_sugg(root, stem, items):
    p = sugg_path(root, stem); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f: json.dump(items, f, indent=1, ensure_ascii=False)
    os.replace(p + ".tmp", p)

def place_sugg(cur, items):
    """{paragraph index: [suggestion]} for pending ones, plus the ones whose text no longer matches."""
    placed, stale = {}, []
    for sg in items:
        if sg.get("status", "pending") != "pending": continue
        hits = [p for p in cur if sg.get("old") and sg["old"] in p["text"]]
        if len(hits) == 1: placed.setdefault(hits[0]["i"], []).append(sg)
        else: stale.append(sg)
    return placed, stale

def sugg_result(text, sg):
    return text if sg.get("new") is None else text.replace(sg["old"], sg["new"], 1)

def set_status(root, stem, sid, status):
    items = load_sugg(root, stem)
    for sg in items:
        if sg.get("id") == sid:
            sg["status"] = status; sg["decided"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            save_sugg(root, stem, items); return sg
    raise Conflict("That suggestion is gone. Reloading…")

def pending_count(root, stem):
    return sum(1 for s in load_sugg(root, stem) if s.get("status", "pending") == "pending")


# ---------- page ----------
def render_page(root, strands, name, token):
    stem = dict(strands)[name]
    path = os.path.join(root, stem + ".docx")
    cur = paragraphs(path)
    bpath = baseline_for(root, stem)
    base = paragraphs(bpath) if bpath else []
    match, removed = align(cur, base) if base else ({}, {})
    placed, stale = place_sugg(cur, load_sugg(root, stem))
    st = load_state(root).get(name, {})
    rv = set(st.get("reviewed", [])); notes = st.get("notes", {})
    E = lambda s: html.escape(str(s), quote=True)
    cards, nav, pending_by_sec = [], [], {}
    done = total = 0
    notes_divider = False

    def removed_cards(after):
        out = []
        for b in removed.get(after, []):
            h = sha("removed:" + b["text"])
            if h in rv: continue
            out.append(f'''<article class="para removed need" id="r{b["i"]}" data-sec="{E(cur_sec[0])}">
  <div class="badges"><span class="badge rem">Cut in the Nov 20 pass</span></div>
  <div class="text">{runs_html(b["runs"])}</div>
  <div class="acts"><button data-op="restore" data-i="{after}" data-base="{b["i"]}" data-expect="{E(after_text.get(after, ""))}">Put it back</button>
  <button data-op="ok_removed" data-key="{E(b["text"])}">Keep it out</button></div></article>''')
        return out

    after_text = {p["i"]: p["text"] for p in cur}
    cur_sec = [""]
    cards += removed_cards(-1)
    for p in cur:
        t = p["text"]
        if not t.strip(): continue
        if p["notes"] and not notes_divider:
            notes_divider = True
            cards.append('<h2 class="divider" id="notes">Revision notes and appendix (not part of the manuscript; delete these paragraphs when you are done with them)</h2>')
            nav.append('<a href="#notes" class="navnotes">Revision notes</a>')
        if p["heading"] and not p["notes"]:
            cur_sec[0] = t
            nav.append(f'<a href="#p{p["i"]}" data-sec="{E(t)}">{E(t)}<span class="pend"></span></a>')
        b = match.get(p["i"])
        changed = b is not None and b["text"] != t
        new = bool(base) and b is None and not p["notes"]
        checks = len(CHECK.findall(t))
        reviewed = sha(t) in rv
        sgs = placed.get(p["i"], [])
        need = (not reviewed and not p["notes"]) or bool(sgs)
        if not p["notes"]:
            total += 1; done += reviewed
        badges = []
        if new and not reviewed: badges.append('<span class="badge new">New in the Nov 20 pass</span>')
        if changed and not reviewed: badges.append('<span class="badge chg">Changed in the Nov 20 pass</span>')
        if p["green"]: badges.append('<span class="badge grn">Green highlight</span>')
        if checks: badges.append(f'<span class="badge chk">{checks} [CHECK]</span>')
        if not reviewed and not (new or changed or p["green"] or checks or p["notes"]): badges.append('<span class="badge plain">No open changes</span>')
        if sgs:
            whos = sorted({sg.get("by", "Claude") for sg in sgs})
            if len(whos) > 1: badges.insert(0, f'<span class="badge agree">{" and ".join(whos)} both flagged this</span>')
            badges.insert(0, f'<span class="badge sug">{len(sgs)} suggestion{"s" if len(sgs) > 1 else ""} from {" + ".join(whos)}</span>')
        if reviewed: badges.append('<span class="badge ok">✓ Reviewed</span>')
        sbox = "".join(f'''<div class="sugg by-{E(sg.get("by", "Claude").lower())}" data-id="{E(sg.get("id"))}" data-new="{E(sugg_result(t, sg))}">
    <div class="small"><b>{E(sg.get("by", "Claude"))} suggests</b>{(" · " + E(sg["date"])) if sg.get("date") else ""}</div>
    {f'<div class="sdiff">{diff_html(t, sugg_result(t, sg))}</div>' if sg.get("new") is not None else ""}
    <div class="why">{E(sg.get("why", ""))}</div>
    <div class="acts">{'<button data-op="s_accept" class="primary">Accept</button><button data-op="s_edit">Edit, then accept</button>' if sg.get("new") is not None else '<button data-op="s_accept" class="primary">Done</button>'}<button data-op="s_reject" class="quiet">Reject</button></div></div>''' for sg in sgs)
        nl = "".join(f'<li><b>Your note to Claude</b> ({E(n["when"])}): {E(n["note"])}</li>' for n in notes.get(sha(t), []))
        diff = f'<div class="diff hidden"><div class="small muted">Before the Nov 20 pass, compared with now: <del>removed</del> <ins>added</ins></div><div>{diff_html(b["text"], t)}</div><button data-op="revert">Go back to the pre-Nov 20 wording</button></div>' if changed else ""
        acc_label = "Accept" if (new or changed or p["green"]) else "Looks good"
        acts = []
        if p["notes"]:
            acts.append('<button data-op="delete" class="danger">Delete this paragraph</button>')
        elif reviewed:
            acts.append('<button data-op="unreview" class="quiet">Undo reviewed</button>')
        else:
            acts.append(f'<button data-op="accept" class="primary">{acc_label}</button>')
        acts.append('<button data-op="edit">Edit</button>')
        if changed: acts.append('<button data-op="showdiff" class="quiet">What the Nov 20 pass changed</button>')
        if not p["notes"]: acts.append('<button data-op="note">Note for Claude</button>')
        if not p["notes"]: acts.append('<button data-op="delete" class="danger quiet">Delete</button>')
        kind = "head" if p["heading"] and not p["notes"] else ("notes" if p["notes"] else "")
        cls = " ".join(x for x in ["para", kind, "need" if need else "", "isrev" if reviewed else ""] if x)
        cards.append(f'''<article class="{cls}" id="p{p["i"]}" data-i="{p["i"]}" data-expect="{E(t)}" data-sec="{E(cur_sec[0])}">
  <div class="badges">{"".join(badges)}</div>
  <div class="text">{runs_html(p["runs"])}</div>
  {sbox}
  {f'<ul class="mynotes">{nl}</ul>' if nl else ""}
  {diff}
  <div class="acts">{"".join(acts)}</div></article>''')
        cards += removed_cards(p["i"])
    stale_html = "".join(f'<li><b>{E(sg.get("id"))}</b>: “{E(str(sg.get("old"))[:120])}” — {E(sg.get("why", ""))} <button data-op="s_reject_stale" data-id="{E(sg.get("id"))}" class="quiet">Dismiss</button></li>' for sg in stale)
    if stale_html: cards.insert(0, f'<div class="help warnbox">These suggestions no longer match the text (it was edited since). Ask Claude to redo them, or dismiss them:<ul>{stale_html}</ul></div>')
    nsug = sum(len(v) for v in placed.values())
    try:
        import gpt_review as _g
        op = _g.load_opinion(stem)
    except Exception: op = None
    opinion = (f'<details class="opinion"><summary><b>GPT\'s overall read</b> ({E(op.get("date", ""))})</summary>'
               f'<div class="otext">{E(op.get("overall", ""))}</div></details>') if op and op.get("overall") else ""
    tabs = "".join(f'<a class="tab{" on" if n == name else ""}" href="/review?s={E(n)}">{E(n)}</a>' for n, _ in strands)
    pct = round(100 * done / total) if total else 0
    return REVIEW_TEMPLATE.format(name=E(name), tabs=tabs, done=done, total=total, pct=pct,
                                  nav="".join(nav), cards="\n".join(cards), token=E(token),
                                  strand=json.dumps(name), nsug=nsug, opinion=opinion, base=E(os.path.basename(bpath)) if bpath else "none found")

REVIEW_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review {name}</title>
<style>
:root{{--bg:#f6f5f1;--panel:#fff;--ink:#1d1d1b;--muted:#6d6a63;--line:#e3e0d8;--accent:#2f5d8a;--warn:#b5521b;--warnbg:#fbeee5;--info:#2e6b4a;--infobg:#e7f2ec;--grn:#c9f0c9;--ylw:#fde68a;--del:#b42318;--delbg:#fde7e4;--ins:#1d6b3a;--insbg:#dff3e5}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328;--grn:#1f4a2a;--ylw:#5b4a12;--del:#ff9b8f;--delbg:#45201c;--ins:#8fe0a8;--insbg:#1c3b27}}}}
:root[data-theme="dark"]{{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328;--grn:#1f4a2a;--ylw:#5b4a12;--del:#ff9b8f;--delbg:#45201c;--ins:#8fe0a8;--insbg:#1c3b27}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
.bar{{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px}}
.bar .row{{max-width:1180px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}}
.back{{color:var(--accent);text-decoration:none;font-size:14px}} .tabs{{display:flex;gap:4px;flex-wrap:wrap}}
.tab{{padding:4px 11px;border-radius:999px;border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:13.5px;background:var(--panel)}} .tab.on{{background:var(--accent);color:var(--panel);border-color:var(--accent)}}
.prog{{flex:1;min-width:180px;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}} .prog .track{{flex:1;height:8px;border-radius:4px;background:var(--line);overflow:hidden}} .prog .fill{{height:100%;background:var(--accent)}}
label.tog{{font-size:13.5px;display:flex;gap:6px;align-items:center;cursor:pointer}}
.wrap{{max-width:1180px;margin:0 auto;padding:16px;display:grid;grid-template-columns:250px 1fr;gap:22px}}
nav{{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 80px);overflow:auto;font-size:13px}} nav a{{display:flex;justify-content:space-between;gap:6px;color:var(--ink);text-decoration:none;padding:5px 8px;border-radius:6px}} nav a:hover{{background:var(--panel)}}
nav .pend{{color:var(--warn);font-weight:600}} .navnotes{{color:var(--muted)!important;margin-top:8px}}
.help{{font-size:13px;color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}}
.para{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:10px;scroll-margin-top:80px}}
.para.need{{border-left:4px solid var(--accent)}} .para.isrev{{opacity:.78}} .para.head .text{{font:600 18px Georgia,serif}}
.para.notes{{background:transparent;border-style:dashed}} .para.removed{{background:transparent;border-style:dashed;border-left:4px solid var(--del)}} .para.removed .text{{color:var(--muted)}}
.text{{font-family:Georgia,"Times New Roman",serif;font-size:16px;line-height:1.65;white-space:pre-wrap}}
.grn{{background:var(--grn);border-radius:2px}} .ylw{{background:var(--ylw)}} mark.chk{{background:var(--ylw);color:inherit;font-family:system-ui,sans-serif;font-size:13px;padding:0 3px;border-radius:3px}}
.badges{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}} .badge{{font-size:11.5px;border-radius:4px;padding:1px 7px;background:var(--bg);color:var(--muted)}}
.badge.new,.badge.chg{{background:var(--infobg);color:var(--info)}} .badge.grn{{background:var(--grn);color:var(--ink)}} .badge.chk{{background:var(--warnbg);color:var(--warn)}} .badge.ok{{color:var(--accent)}} .badge.rem{{background:var(--delbg);color:var(--del)}}
.acts{{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}} button{{font:inherit;font-size:13px;padding:4px 11px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}}
button:hover{{border-color:var(--accent)}} button.primary{{background:var(--accent);border-color:var(--accent);color:var(--panel)}} button.danger{{color:var(--warn)}} button.quiet{{background:transparent}}
.diff{{margin-top:10px;padding:10px 12px;border-radius:8px;background:var(--bg);font-family:Georgia,serif;font-size:15px}} .diff button{{margin-top:8px;font-family:system-ui,sans-serif}}
del{{color:var(--del);background:var(--delbg);text-decoration:line-through}} ins{{color:var(--ins);background:var(--insbg);text-decoration:none}}
textarea{{width:100%;min-height:160px;font:16px/1.6 Georgia,serif;padding:10px;border:1px solid var(--accent);border-radius:8px;background:var(--bg);color:var(--ink);resize:vertical}}
textarea.note{{min-height:70px;font:14px system-ui,sans-serif}}
.sugg.by-gpt{{border-color:var(--info)}} .badge.agree{{background:var(--infobg);color:var(--info)}}
.gptbox{{display:block}} .gptbox button{{margin-right:8px}} .opinion{{margin-top:8px}} .opinion .otext{{white-space:pre-wrap;color:var(--ink);margin-top:6px;font-size:14px}}
.sugg{{margin-top:10px;border:1px solid var(--accent);border-radius:8px;padding:10px 12px;background:var(--bg)}} .sdiff{{font-family:Georgia,serif;font-size:15px;margin:6px 0}} .why{{font-size:13.5px;color:var(--muted)}}
.badge.sug{{background:var(--accent);color:var(--panel)}} .warnbox{{border-color:var(--warn)}}
.mynotes{{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--accent)}}
h2.divider{{font:600 14px system-ui,sans-serif;color:var(--muted);margin:30px 0 10px;border-top:1px solid var(--line);padding-top:14px;scroll-margin-top:80px}}
.hidden{{display:none!important}} .small{{font-size:12.5px}} .muted{{color:var(--muted)}}
#toast{{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:9px 16px;border-radius:8px;font-size:14px;display:none;z-index:9;max-width:90vw}}
body.only .para:not(.need):not(.notes){{display:none}}
@media (max-width:820px){{.wrap{{grid-template-columns:1fr}} nav{{display:none}}}}
</style></head><body>
<div class="bar"><div class="row"><a class="back" href="/">← Dashboard</a><div class="tabs">{tabs}</div>
<div class="prog"><div class="track"><div class="fill" style="width:{pct}%"></div></div>{done} of {total} reviewed</div>
<label class="tog"><input type="checkbox" id="only"> Only what still needs me</label></div></div>
<div class="wrap"><nav>{nav}</nav><main>
<div class="help">This is the current draft, paragraph by paragraph. <b>Accept / Looks good</b> marks a paragraph reviewed and clears any green highlight. <b>Edit</b> rewrites it in the Word file (italics on unchanged words are kept). <b>Note for Claude</b> puts a task on my list; my answers come back here as <b>suggestions</b> you can accept, edit, or reject. Every change saves to the Word file right away, so close it in Word first; the first change each day saves a copy in _versions. {nsug} open suggestion(s) in this strand.</div>
<div class="help gptbox"><button id="gptbtn">Ask GPT for a second opinion</button> <span id="gptmsg">GPT reads this strand against the rubric, Dorothea's standards and the slop patterns. Its edits appear here as suggestions labeled GPT, next to Claude's. It runs on your ChatGPT plan and takes a few minutes.</span>{opinion}</div>
{cards}
</main></div><div id="toast"></div>
<script>
var TOKEN="{token}", STRAND={strand};
function toast(m){{var t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(function(){{t.style.display='none'}},4500)}}
function post(d,anchor){{d.strand=STRAND;return fetch('/review',{{method:'POST',headers:{{'Content-Type':'application/json','X-Token':TOKEN}},body:JSON.stringify(d)}})
 .then(function(r){{return r.json().then(function(j){{if(!r.ok)throw new Error(j.error||r.status);return j}})}})
 .then(function(){{try{{sessionStorage.setItem('ry',scrollY)}}catch(e){{}};location.reload()}})
 .catch(function(e){{toast(e.message);if(/changed/.test(e.message))setTimeout(function(){{location.reload()}},1500)}})}}
try{{var y=sessionStorage.getItem('ry');if(y!==null){{scrollTo(0,+y);sessionStorage.removeItem('ry')}}}}catch(e){{}}
var only=document.getElementById('only');try{{only.checked=localStorage.getItem('only')==='1'}}catch(e){{}}
function applyOnly(){{document.body.classList.toggle('only',only.checked);try{{localStorage.setItem('only',only.checked?'1':'0')}}catch(e){{}}}}
only.onchange=applyOnly;applyOnly();
// pending counts per section in the nav
var pend={{}};document.querySelectorAll('.para.need').forEach(function(p){{var s=p.dataset.sec;pend[s]=(pend[s]||0)+1}});
document.querySelectorAll('nav a[data-sec]').forEach(function(a){{var n=pend[a.dataset.sec];a.querySelector('.pend').textContent=n?n:'✓'}});
document.querySelectorAll('.para').forEach(function(p){{
 var i=+p.dataset.i, ex=p.dataset.expect;
 p.querySelectorAll('button[data-op]').forEach(function(b){{b.onclick=function(){{var op=b.dataset.op,ex2=null,sid=null;
  if(op==='accept')return post({{op:'accept',i:i,expect:ex}});
  if(op==='unreview')return post({{op:'unreview',i:i,expect:ex}});
  if(op==='revert')return post({{op:'revert',i:i,expect:ex}});
  if(op==='restore')return post({{op:'restore',i:+b.dataset.i,expect:b.dataset.expect,base:+b.dataset.base}});
  if(op==='ok_removed')return post({{op:'ok_removed',key:b.dataset.key}});
  var sg=b.closest('.sugg');
  if(op==='s_accept')return post({{op:'s_accept',i:i,expect:ex,id:sg.dataset.id}});
  if(op==='s_reject')return post({{op:'s_reject',id:sg.dataset.id}});
  if(op==='s_edit'){{op='edit';ex2=sg.dataset.new;sid=sg.dataset.id}}
  if(op==='showdiff'){{p.querySelector('.diff').classList.toggle('hidden');return}}
  if(op==='delete'){{if(b.dataset.armed)return post({{op:'delete',i:i,expect:ex}});b.dataset.armed=1;b.textContent='Click again to delete';setTimeout(function(){{delete b.dataset.armed;b.textContent='Delete'}},4000);return}}
  if(op==='edit'||op==='note'){{var acts=p.querySelector('.acts');acts.classList.add('hidden');
   var box=document.createElement('div');var ta=document.createElement('textarea');if(op==='note'){{ta.className='note';ta.placeholder='What should Claude do with this paragraph?'}}else ta.value=(typeof ex2!=='undefined'&&ex2!==null)?ex2:ex;
   var row=document.createElement('div');row.className='acts';var sv=document.createElement('button');sv.className='primary';sv.textContent=op==='edit'?'Save to the Word file':'Add note';
   var cn=document.createElement('button');cn.textContent='Cancel';row.appendChild(sv);row.appendChild(cn);box.appendChild(ta);box.appendChild(row);acts.after(box);ta.focus();
   if(op==='edit')p.querySelector('.text').classList.add('hidden');
   cn.onclick=function(){{box.remove();acts.classList.remove('hidden');p.querySelector('.text').classList.remove('hidden')}};
   sv.onclick=function(){{var v=ta.value;if(!v.trim())return;if(op==='edit')post(sid?{{op:'s_accept',i:i,expect:ex,id:sid,text:v}}:{{op:'set_text',i:i,expect:ex,text:v}});else post({{op:'note',i:i,expect:ex,note:v}})}};}}
 }}}});
}});
document.querySelectorAll('button[data-op="s_reject_stale"]').forEach(function(b){{b.onclick=function(){{post({{op:'s_reject',id:b.dataset.id}})}}}});
(function(){{var btn=document.getElementById('gptbtn'),msg=document.getElementById('gptmsg'),was=null;
 function poll(){{fetch('/gpt_status?s='+encodeURIComponent(STRAND)).then(function(r){{return r.json()}}).then(function(j){{
  if(j.state==='running'){{btn.disabled=true;btn.textContent='GPT is reading…';msg.textContent=j.msg;was='running';setTimeout(poll,5000)}}
  else if(j.state==='done'){{if(was==='running'){{try{{sessionStorage.setItem('ry',scrollY)}}catch(e){{}};location.reload();return}}btn.disabled=false;btn.textContent='Ask GPT again';msg.textContent=j.msg+' ('+j.when+')'}}
  else if(j.state==='error'){{btn.disabled=false;btn.textContent='Ask GPT for a second opinion';msg.textContent=j.msg}}
 }}).catch(function(){{}})}}
 btn.onclick=function(){{fetch('/gpt',{{method:'POST',headers:{{'Content-Type':'application/json','X-Token':TOKEN}},body:JSON.stringify({{strand:STRAND}})}})
  .then(function(r){{return r.json().then(function(j){{if(!r.ok)throw new Error(j.error||r.status);return j}})}}).then(function(){{was='running';poll()}}).catch(function(e){{msg.textContent=e.message}})}};
 poll();}})();
if(location.hash){{var el=document.querySelector(location.hash);if(el)el.scrollIntoView()}}
</script></body></html>"""
