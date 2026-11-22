#!/usr/bin/env python3
"""Build Dashboard.html for the Strands folder.

Reads the four strand .docx files, the dated copies in _versions folder, and Tasks.md,
then writes one self-contained Dashboard.html next to them. Standard library
only; nothing leaves the computer.

Usage:  python make_dashboard.py            (run from anywhere)
        python make_dashboard.py FOLDER     (point at another Strands folder)
"""
import datetime as dt, html, json, os, re, sys, zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = os.path.abspath(_ARGS[0]) if _ARGS else os.path.dirname(HERE)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
STRANDS = [  # (short name, file stem)
    ("Canon", "Strand 1 - Canon and Canon Wars"),
    ("Censorship", "Strand 2 - Censorship"),
    ("Moral Panics", "Strand 3 - Moral Panics"),
    ("Text Selection", "Strand 4 - Text Selection"),
]
STAGES = ["Drafting", "Claude revising", "Your review", "Source checks", "With Dorothea", "Accepted"]
NOTES_START = re.compile(r"^(Revision notes|Revision Notes|\[Transition|Appendix:)")
CHECK = re.compile(r"\[CHECK[^\]]*\]")

# ---------- reading a .docx ----------
def para_text(p):
    out = []
    for el in p.iter():
        if el.tag == W + "t" and el.text: out.append(el.text)
        elif el.tag == W + "tab": out.append(" ")
    return "".join(out)

def read_docx(path):
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read("word/document.xml"))
    paras, in_notes, section = [], False, ""
    tc = {"ins": {}, "del": {}}
    for p in doc.iter(W + "p"):
        text = para_text(p).strip()
        style = p.find(f"{W}pPr/{W}pStyle")
        style = style.get(W + "val") if style is not None else ""
        if text and NOTES_START.match(text): in_notes = True
        heading = bool(text) and (style.lower().startswith(("heading", "title")) or
                                  (len(text.split()) < 14 and not text.endswith((".", "]", ":")) and not text.startswith("[")))
        if heading and not in_notes: section = text
        # green highlight runs, grouped into passages
        green, cur = [], []
        for r in p.iter(W + "r"):
            hl = r.find(f"{W}rPr/{W}highlight")
            t = "".join(x.text or "" for x in r.iter(W + "t"))
            if hl is not None and hl.get(W + "val") == "green":
                cur.append(t)
            elif cur and t.strip():
                green.append("".join(cur)); cur = []
        if cur: green.append("".join(cur))
        green = [g.strip() for g in green if len(g.strip()) > 2]
        if not in_notes:
            for kind in ("ins", "del"):
                for el in p.iter(W + kind):
                    a = el.get(W + "author", "?")
                    tc[kind][a] = tc[kind].get(a, 0) + 1
        if text:
            paras.append({"text": text, "heading": heading, "notes": in_notes,
                          "section": section, "green": green})
    comments = []
    if "word/comments.xml" in z.namelist():
        cx = ET.fromstring(z.read("word/comments.xml"))
        for c in cx.iter(W + "comment"):
            comments.append({"author": c.get(W + "author", "?"),
                             "text": " ".join(para_text(p) for p in c.iter(W + "p")).strip()})
    return paras, tc, comments

def words(s): return re.findall(r"[A-Za-z’'-]+", s)

# ---------- a light slop screen (subset of strand_revision/slop_audit/slop_audit.py) ----------
SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]*\s+(?=[A-Z“\"(\[])")
ABBR = re.compile(r"\b(e\.g|i\.e|et al|U\.S|cf|vs|pp?|Vol|No|Dr|Mr|Ms|St)\.$")
ANTITHESIS = r"\b(not (simply|merely|only|just)?\s*\w+[^.;]{0,60}?,? but\b|rather than)\b"
ING_TAIL = r",\s+(demonstrating|suggesting|reflecting|indicating|revealing|highlighting|underscoring|illustrating|showing|signaling|positioning|making|leaving|reinforcing|complicating|raising)\b"
CAVEAT = r"\b(does not|do not|did not|cannot)( by itself| alone| directly)? (establish|demonstrate|prove|show|settle|reveal|serve as|mean|determine)|\binsufficient evidence"
DEMONSTRATIVE = r"^(This|These|Such|That|Those) (\w+ )?(study|studies|survey|surveys|work|research|finding|findings|pattern|evidence|comparison|shift|literature|scholarship|approach|account|analysis|history|continuity|tension|distinction|period|debate|record|case)\b"
AUTHOR_OPEN = r"^([A-Z][a-zA-Z’'\-]+(?: (?:and|&) [A-Z][a-zA-Z’'\-]+| et al\.)?(?:’s|'s)? ?\(\d{4}|(?:He|She|They|Their|His|Her) |In ([A-Z][a-z]+’s|a|an|her|his|their) [\w -]{0,40}(study|survey|analysis|case|interviews?))"
BANNED = ["delve","tapestry","pivotal","landscape","harness","robust","streamline","leverage","navigate",
          "intricate","embark","illuminate","foster","underscore","profound","unpack","nuanced","multifaceted",
          "realm","serves as a","testament to","sheds light","it is important to note","it is worth noting",
          "crucially","notably","highlighting","underscoring","complex interplay","broader","in turn"]

def sentences(p):
    out = []
    for s in SENT_SPLIT.split(p.strip()):
        if out and ABBR.search(out[-1]): out[-1] += " " + s
        else: out.append(s)
    return [s for s in out if len(s.split()) > 1]

def concrete(s): return bool(re.search(r"\d|“|\"|\b[A-Z][a-z]+", s[1:]))

def slop(body):
    f = {"Sandwich paragraphs": 0, "Corrective antithesis": 0, "Author-led paragraphs": 0,
         "“This study…” openers": 0, "-ing tails": 0, "Limit caveats": 0, "Banned words": 0}
    arc = 0
    for t in body:
        ss = sentences(t)
        f["Corrective antithesis"] += len(re.findall(ANTITHESIS, t, re.I))
        f["-ing tails"] += len(re.findall(ING_TAIL, t))
        f["Limit caveats"] += len(re.findall(CAVEAT, t, re.I))
        low = t.lower()
        f["Banned words"] += sum(1 for b in BANNED if re.search(r"\b" + re.escape(b), low))
        auth = sum(1 for s in ss if re.match(AUTHOR_OPEN, s.lstrip("“\"(")))
        f["“This study…” openers"] += sum(1 for s in ss if re.match(DEMONSTRATIVE, s.lstrip("“\"(")))
        if len(ss) >= 3:
            arc += 1
            if auth / len(ss) >= 0.6: f["Author-led paragraphs"] += 1
            if not concrete(ss[0]) and not concrete(ss[-1]): f["Sandwich paragraphs"] += 1
    return f, (round(100 * f["Sandwich paragraphs"] / arc) if arc else 0)

# ---------- strands ----------
def snippet(text, m, width=110):
    a = max(0, m.start() - width); b = min(len(text), m.end() + 20)
    return ("…" if a else "") + text[a:m.start()].lstrip(), m.group(0), text[m.end():b] + ("…" if b < len(text) else "")

def word_count(paras): return sum(len(words(p["text"])) for p in paras if not p["notes"] and not p["heading"])

def latest_version(stem):
    vd = os.path.join(ROOT, "_versions")
    if not os.path.isdir(vd): return None
    c = [os.path.join(vd, f) for f in os.listdir(vd) if f.startswith(stem) and f.endswith(".docx")]
    return max(c, key=os.path.getmtime) if c else None

def strand_info(name, stem):
    path = os.path.join(ROOT, stem + ".docx")
    if not os.path.exists(path): return {"name": name, "file": stem + ".docx", "missing": True}
    paras, tc, comments = read_docx(path)
    body = [p for p in paras if not p["notes"]]
    checks = []
    for p in body:
        for m in CHECK.finditer(p["text"]):
            checks.append({"section": p["section"], "parts": snippet(p["text"], m)})
    green = [{"section": p["section"], "text": g} for p in body for g in p["green"]]
    flags, sandwich = slop([p["text"] for p in body if not p["heading"]])
    wc = word_count(paras)
    v = latest_version(stem); vwc = None
    if v:
        try: vwc = word_count(read_docx(v)[0])
        except Exception: pass
    notes_open = [CHECK.sub("", p["text"]) for p in paras if p["notes"] and re.match(r"^(Still open|Remaining|Open \[CHECK\]|Not yet done)", p["text"])]
    return {"name": name, "file": stem + ".docx", "words": wc,
            "modified": dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%b %d, %I:%M %p"),
            "version": os.path.basename(v) if v else None, "version_words": vwc,
            "outline": [(p["text"], p["section"] != p["text"]) for p in body if p["heading"]][1:],
            "checks": checks, "green": green, "tc": tc,
            "comments": comments, "flags": flags, "sandwich": sandwich, "notes_open": notes_open}

# ---------- Tasks.md ----------
def parse_tasks(path):
    stages, groups, order, cur = {}, {}, [], None
    if not os.path.exists(path): return stages, groups, order
    with open(path, encoding="utf-8") as fh: lines = fh.read().splitlines()
    for n, line in enumerate(lines):
        line = line.rstrip()
        h = re.match(r"^##\s+(.*)", line)
        if h:
            cur = h.group(1).strip()
            if not cur.lower().startswith("strand stage") and cur not in groups:
                groups[cur] = []; order.append(cur)
            continue
        if cur and cur.lower().startswith("strand stage"):
            m = re.match(r"^[-*]?\s*([^|]+)\|\s*([^|]+)\|?\s*(.*)$", line)
            if m: stages[m.group(1).strip()] = (m.group(2).strip(), m.group(3).strip())
            continue
        m = re.match(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*)$", line)
        if m and cur:
            t = m.group(2)
            tags = re.findall(r"\[([^\]]+)\](?!\()", t)
            due = re.search(r"\bdue:(\d{4}-\d{2}-\d{2})", t)
            clean = re.sub(r"\s*\[[^\]]+\](?!\()|\s*due:\S+", "", t).strip()
            groups[cur].append({"done": m.group(1) != " ", "text": clean, "tags": tags,
                                "due": due.group(1) if due else None, "line": n, "raw": line})
    return stages, groups, order

# ---------- HTML ----------
E = lambda s: html.escape(str(s), quote=True)

def md_inline(s):
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"(?<![\"=>])(https?://[^\s<]+)", r'<a href="\1">link</a>', s)
    return s

def next_wednesday(today):
    d = (2 - today.weekday()) % 7
    return today + dt.timedelta(days=d)

def render(strands, stages, groups, order, live=False, token="", progress=None):
    today = dt.date.today(); wed = next_wednesday(today); days = (wed - today).days
    when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
    now = dt.datetime.now().strftime("%a %b %d, %I:%M %p")
    tagset = []
    for g in order:
        for t in groups[g]:
            for tg in t["tags"]:
                if tg not in tagset: tagset.append(tg)
    def review_link(n):
        if not live: return ""
        pr = (progress or {}).get(n)
        lab = f"{pr[0]} of {pr[1]} reviewed" if pr else "Go paragraph by paragraph"
        if pr and len(pr) > 2 and pr[2]: lab += f" · {pr[2]} suggestion{'s' if pr[2] > 1 else ''} from Claude"
        return f'<a class="review" href="/review?s={E(n)}"><b>Review this strand →</b><span>{E(lab)}</span></a>'
    cards = []
    for s in strands:
        if s.get("missing"):
            cards.append(f'<section class="card"><h2>{E(s["name"])}</h2><p class="muted">File not found: {E(s["file"])}</p></section>'); continue
        stage, note = stages.get(s["name"], ("", ""))
        si = STAGES.index(stage) if stage in STAGES else -1
        track = "".join(f'<li class="{ "done" if i < si else ("now" if i == si else "") }" title="{E(st)}" data-stage="{E(st)}"><span></span>{E(st) if i == si else ""}</li>' for i, st in enumerate(STAGES))
        snap = re.sub(r".*\((.*)\)\.docx$", r"\1", s["version"]) if s["version"] else ""
        ins = sum(s["tc"]["ins"].values()); dele = sum(s["tc"]["del"].values())
        by = ", ".join(f"{a} {s['tc']['ins'].get(a,0)+s['tc']['del'].get(a,0)}" for a in sorted(set(s["tc"]["ins"]) | set(s["tc"]["del"])))
        delta = ""
        if s["version_words"] is not None and s["version_words"] != s["words"]:
            d = s["words"] - s["version_words"]; delta = f' <span class="delta">{d:+,} since snapshot</span>'
        fl = s["flags"]; nflags = sum(fl.values())
        def stat(n, label, cls="", tip=""):
            return f'<div class="stat {cls if n else "zero"}" title="{E(tip)}"><b>{n}</b><span>{E(label)}</span></div>'
        stats = (stat(len(s["checks"]), "open [CHECK]s", "warn", "Unverified details still marked in the manuscript text")
                 + stat(len(s["green"]), "green passages", "info", "Nov 20 changes still highlighted green, i.e. not yet accepted by you")
                 + stat(ins + dele, "tracked changes", "info", by or "No tracked changes")
                 + stat(len(s["comments"]), "comments", "", ", ".join(sorted(set(c['author'] for c in s['comments'])))))
        checks = "".join(f'<li><span class="sec">{E(c["section"])}</span>{E(c["parts"][0])}<mark>{E(c["parts"][1])}</mark>{E(c["parts"][2])}</li>' for c in s["checks"]) or '<li class="muted">None in the manuscript text.</li>'
        green = "".join(f'<li><span class="sec">{E(g["section"])}</span>{E(g["text"][:260])}{"…" if len(g["text"])>260 else ""}</li>' for g in s["green"]) or '<li class="muted">Nothing highlighted.</li>'
        outline = "".join(f'<li class="{"sub" if sub else ""}">{E(h)}</li>' for h, sub in s["outline"])
        slopl = "".join(f'<li><span>{E(k)}</span><b>{v}</b></li>' for k, v in fl.items())
        notes = "".join(f"<li>{E(n)}</li>" for n in s["notes_open"])
        cards.append(f'''<section class="card" data-tag="{E(s["name"])}" data-stage="{E(stage)}" data-note="{E(note)}">
  <header><h2>{E(s["name"])}</h2><a class="open" href="{E(s["file"])}" data-file="{E(s["file"])}" title="Open in Word">open in Word</a></header>
  <ol class="track">{track}</ol>
  <p class="note" title="Click to edit">{md_inline(note) if note else '<span class="muted">Add a note</span>'}</p>
  {review_link(s["name"])}
  <div class="stats">{stats}</div>
  <p class="meta">{s["words"]:,} words{delta} · saved {E(s["modified"])}{(" · snapshot " + E(snap)) if snap else ""}</p>
  <details><summary>Open [CHECK]s ({len(s["checks"])})</summary><ul class="list">{checks}</ul></details>
  <details><summary>Unaccepted green passages ({len(s["green"])})</summary><ul class="list">{green}</ul></details>
  <details><summary>Slop screen ({nflags} flags · {s["sandwich"]}% sandwich paragraphs)</summary><ul class="slop">{slopl}</ul>
    <p class="muted small">A light version of slop_audit.py. Counts are prompts to look, not verdicts. Dorothea's v5 baseline was about 20% sandwich paragraphs.</p></details>
  <details><summary>Outline</summary><ul class="outline">{outline}</ul></details>
</section>''')
    cols = []
    for g in order:
        items = []
        for t in groups[g]:
            overdue = t["due"] and not t["done"] and t["due"] < today.isoformat()
            due = f'<span class="due{" late" if overdue else ""}">{dt.date.fromisoformat(t["due"]).strftime("%a %b %d")}</span>' if t["due"] else ""
            tags = "".join(f'<span class="tag">{E(x)}</span>' for x in t["tags"])
            items.append(f'<li class="task{" isdone" if t["done"] else ""}" data-tags="{E("|".join(t["tags"]))}" data-line="{t["line"]}" data-raw="{E(t["raw"])}" data-text="{E(t["text"])}" data-due="{E(t["due"] or "")}" data-group="{E(g)}"><span class="box" title="Mark done">{"✓" if t["done"] else ""}</span><div class="tbody">{md_inline(t["text"])}<div class="tline">{tags}{due}</div></div></li>')
        open_n = sum(1 for t in groups[g] if not t["done"]) or len(groups[g])
        cls = "col you" if re.search(r"\byou\b", g, re.I) else "col"
        cols.append(f'<div class="{cls}"><h3>{E(g)} <span class="count">{open_n}</span></h3><ul>{"".join(items)}</ul><button class="add" data-group="{E(g)}">+ Add task</button></div>')
    chips = '<button class="chip on" data-f="">All</button>' + "".join(f'<button class="chip" data-f="{E(t)}">{E(t)}</button>' for t in tagset)
    you = sum(1 for g in order if re.search(r"\byou\b", g, re.I) for t in groups[g] if not t["done"])
    tot_checks = sum(len(s.get("checks", [])) for s in strands); tot_green = sum(len(s.get("green", [])) for s in strands)
    groups_json = json.dumps(order).replace("</", "<\\/"); tags_json = json.dumps(tagset).replace("</", "<\\/")
    return TEMPLATE.format(stages_json=json.dumps(STAGES), live="live" if live else "static", token=E(token), groups_json=groups_json, tags_json=tags_json, now=E(now), wed=wed.strftime("%A, %B %d"), when=when, you=you,
                           checks=tot_checks, green=tot_green, cards="\n".join(cards),
                           chips=chips, cols="\n".join(cols))

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dissertation Dashboard</title>
<style>
:root{{--bg:#f6f5f1;--panel:#fff;--ink:#1d1d1b;--muted:#6d6a63;--line:#e3e0d8;--accent:#2f5d8a;--warn:#b5521b;--warnbg:#fbeee5;--info:#2e6b4a;--infobg:#e7f2ec;--mark:#fde68a;--now:#2f5d8a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328;--mark:#6b5a1a;--now:#8db6e0}}}}
:root[data-theme="dark"]{{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328;--mark:#6b5a1a;--now:#8db6e0}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:24px 16px 60px}}
.top{{display:flex;flex-wrap:wrap;gap:12px 28px;align-items:baseline;justify-content:space-between;margin-bottom:18px}}
h1{{font:600 24px/1.2 Georgia,"Times New Roman",serif;margin:0}} .muted{{color:var(--muted)}} .small{{font-size:12.5px}}
.pills{{display:flex;gap:10px;flex-wrap:wrap}} .pill{{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13.5px}}
.pill b{{color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.card header{{display:flex;justify-content:space-between;align-items:baseline}} .card h2{{font:600 18px Georgia,serif;margin:0}}
.open{{font-size:12.5px;color:var(--accent)}}
.track{{list-style:none;display:flex;gap:4px;padding:0;margin:12px 0 6px}} .track li{{flex:1;font-size:11.5px;color:var(--now);font-weight:600;white-space:nowrap}}
.track li span{{display:block;height:6px;border-radius:3px;background:var(--line);margin-bottom:4px}} .track li.done span{{background:var(--muted)}} .track li.now span{{background:var(--now)}}
.note{{margin:4px 0 10px;font-size:13.5px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}} .stat{{border-radius:7px;padding:6px 4px;text-align:center;background:var(--bg)}}
.stat b{{display:block;font-size:20px;line-height:1.1}} .stat span{{font-size:11px;color:var(--muted)}}
.stat.warn{{background:var(--warnbg)}} .stat.warn b{{color:var(--warn)}} .stat.info{{background:var(--infobg)}} .stat.info b{{color:var(--info)}} .stat.zero b{{color:var(--muted)}}
.meta{{font-size:12.5px;color:var(--muted);margin:8px 0}} .delta{{color:var(--accent)}}
details{{border-top:1px solid var(--line);padding:6px 0}} summary{{cursor:pointer;font-size:13.5px;font-weight:600}}
.list{{margin:6px 0;padding-left:18px;font-size:13px}} .list li{{margin:5px 0}} .sec{{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}}
mark{{background:var(--mark);color:inherit;border-radius:3px;padding:0 2px}}
.slop{{list-style:none;padding:0;margin:6px 0;font-size:13px}} .slop li{{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:2px 0}}
.outline{{font-size:13px;padding-left:18px;margin:6px 0}} .outline .sub{{margin-left:16px;list-style:circle;color:var(--muted)}}
h2.sect{{font:600 19px Georgia,serif;margin:34px 0 10px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}} .chip{{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:3px 11px;cursor:pointer}}
.chip.on{{background:var(--accent);border-color:var(--accent);color:var(--panel)}}
.board{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;align-items:start}}
.col{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}} .col.you{{border-color:var(--accent);box-shadow:inset 0 3px 0 var(--accent)}}
.col h3{{font-size:14.5px;margin:0 0 8px;display:flex;justify-content:space-between}} .count{{color:var(--muted);font-weight:400}}
.col ul{{list-style:none;margin:0;padding:0}} .task{{display:flex;gap:9px;padding:7px 0;border-top:1px solid var(--line);font-size:13.5px}}
.box{{flex:0 0 16px;height:16px;border:1.5px solid var(--muted);border-radius:4px;font-size:11px;text-align:center;line-height:13px;margin-top:3px}}
.task.isdone{{color:var(--muted)}} .task.isdone>div{{text-decoration:line-through}}
.tline{{margin-top:3px;display:flex;gap:5px;flex-wrap:wrap}} .tag{{font-size:11px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 6px;color:var(--muted)}}
.due{{font-size:11px;color:var(--accent)}} .due.late{{color:var(--warn);font-weight:600}}
.task a{{overflow-wrap:anywhere}} .review{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:0 0 10px;padding:8px 10px;border-radius:8px;background:var(--accent);color:var(--panel);text-decoration:none;font-size:13.5px}} .review span{{font-size:12px;opacity:.85}}
.hidden{{display:none!important}} code{{font-size:12px}} a{{color:var(--accent)}}
footer{{margin-top:36px;font-size:12.5px;color:var(--muted)}}
.add{{font:inherit;font-size:13px;color:var(--accent);background:none;border:1px dashed var(--line);border-radius:6px;width:100%;padding:5px;margin-top:8px;cursor:pointer}}
.static .add{{display:none}}
.live .box,.live .tbody,.live .note,.live .track li{{cursor:pointer}} .live .task:hover .tbody{{color:var(--accent)}} .live .note:hover{{outline:1px dashed var(--line);border-radius:4px}}
.live .track li:hover span{{outline:2px solid var(--accent)}}
.live .box:hover{{border-color:var(--accent)}}
.col.drop{{outline:2px dashed var(--accent)}} .live .task{{cursor:grab}}
dialog{{border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);padding:18px 20px;width:min(460px,calc(100vw - 32px))}}
dialog::backdrop{{background:rgba(0,0,0,.35)}}
dialog h3{{margin:0 0 12px;font:600 17px Georgia,serif}} dialog label{{display:block;font-size:12.5px;color:var(--muted);margin:10px 0 3px}}
dialog input,dialog select,dialog textarea{{font:inherit;font-size:14px;width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}}
dialog textarea{{min-height:70px;resize:vertical}}
.tagpick{{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}} .tagpick button{{font:inherit;font-size:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:2px 9px;cursor:pointer}} .tagpick button.on{{background:var(--accent);color:var(--panel);border-color:var(--accent)}}
.dbtns{{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}} .dbtns button{{font:inherit;font-size:14px;padding:6px 14px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}}
.dbtns .primary{{background:var(--accent);border-color:var(--accent);color:var(--panel)}} .dbtns .danger{{margin-right:auto;color:var(--warn)}}
#toast{{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 16px;border-radius:8px;font-size:13.5px;display:none}}
</style></head><body class="{live}"><main>
<div class="top"><div><h1>Dissertation dashboard</h1><div class="muted small">Built {now} from the files in this folder</div></div>
<div class="pills"><span class="pill">Dorothea: <b>{wed}</b> ({when})</span><span class="pill"><b>{you}</b> waiting on you</span><span class="pill"><b>{checks}</b> open [CHECK]s</span><span class="pill"><b>{green}</b> green passages to accept</span></div></div>
<div class="grid">{cards}</div>
<h2 class="sect">Tasks</h2>
<div class="chips">{chips}</div>
<div class="board">{cols}</div>
<footer class="live-only">Changes save straight to Tasks.md in this folder. Reload the page to pick up new edits to the Word files. Close the black "Dashboard" window to stop it.</footer>
<footer class="static-only">This copy is read-only. Double-click <b>Open dashboard.bat</b> to check off, add and edit tasks on the page. (You can still edit Tasks.md by hand.)</footer>
</main>
<dialog id="dlg"><form method="dialog" id="dform">
  <h3 id="dtitle">Task</h3>
  <label for="dtext">Task</label><textarea id="dtext" required></textarea>
  <label>Tags</label><div class="tagpick" id="dtags"></div>
  <input id="dnewtag" placeholder="New tag, then Enter" style="margin-top:6px">
  <label for="ddue">Due (optional)</label><input type="date" id="ddue">
  <label for="dgroup">Column</label><select id="dgroup"></select>
  <div class="dbtns"><button type="button" class="danger" id="ddel">Delete</button><button type="button" id="dcancel">Cancel</button><button type="submit" class="primary">Save</button></div>
</form></dialog>
<dialog id="sdlg"><form method="dialog" id="sform">
  <h3 id="stitle">Stage</h3>
  <label for="sstage">Stage</label><select id="sstage"></select>
  <label for="snote">Note</label><textarea id="snote"></textarea>
  <div class="dbtns"><button type="button" id="scancel">Cancel</button><button type="submit" class="primary">Save</button></div>
</form></dialog>
<div id="toast"></div>
<script>
var TOKEN="{token}", GROUPS={groups_json}, TAGS={tags_json}, STAGES={stages_json};
var LIVE=document.body.classList.contains('live');
document.querySelectorAll(LIVE?'.static-only':'.live-only').forEach(function(e){{e.remove()}});
function toast(m){{var t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(function(){{t.style.display='none'}},3500)}}
function api(op,data){{data.op=op;return fetch('/api',{{method:'POST',headers:{{'Content-Type':'application/json','X-Token':TOKEN}},body:JSON.stringify(data)}})
 .then(function(r){{return r.json().then(function(j){{if(!r.ok)throw new Error(j.error||r.status);return j}})}})
 .then(function(){{sessionStorage.setItem('y',scrollY);location.reload()}})
 .catch(function(e){{toast(e.message);if(/changed/.test(e.message))setTimeout(function(){{location.reload()}},1500)}})}}
try{{var y=sessionStorage.getItem('y');if(y){{scrollTo(0,+y);sessionStorage.removeItem('y')}}}}catch(e){{}}
// filters
document.querySelectorAll('.chip').forEach(function(c){{c.addEventListener('click',function(){{
 document.querySelectorAll('.chip').forEach(function(x){{x.classList.remove('on')}});c.classList.add('on');var f=c.dataset.f;
 try{{sessionStorage.setItem('f',f)}}catch(e){{}}
 document.querySelectorAll('.task').forEach(function(t){{t.classList.toggle('hidden',!!f&&t.dataset.tags.split('|').indexOf(f)<0)}});
 document.querySelectorAll('.card[data-tag]').forEach(function(k){{k.classList.toggle('hidden',!!f&&STR.indexOf(f)>=0&&k.dataset.tag!==f)}});
}})}});
try{{var f0=sessionStorage.getItem('f');if(f0){{var c0=document.querySelector('.chip[data-f="'+CSS.escape(f0)+'"]');if(c0)c0.click()}}}}catch(e){{}}
if(LIVE){{
 var dlg=document.getElementById('dlg'),cur=null,picked=[];
 function drawTags(){{var w=document.getElementById('dtags');w.innerHTML='';TAGS.concat(picked.filter(function(t){{return TAGS.indexOf(t)<0}})).forEach(function(t){{
  var b=document.createElement('button');b.type='button';b.textContent=t;if(picked.indexOf(t)>=0)b.className='on';
  b.onclick=function(){{var i=picked.indexOf(t);if(i>=0)picked.splice(i,1);else picked.push(t);drawTags()}};w.appendChild(b)}})}}
 document.getElementById('dnewtag').addEventListener('keydown',function(e){{if(e.key==='Enter'){{e.preventDefault();var v=this.value.trim().replace(/[\[\]]/g,'');if(v&&picked.indexOf(v)<0)picked.push(v);this.value='';drawTags()}}}});
 var gs=document.getElementById('dgroup');GROUPS.forEach(function(g){{var o=document.createElement('option');o.textContent=g;gs.appendChild(o)}});
 function openTask(li,group){{cur=li;document.getElementById('dtitle').textContent=li?'Edit task':'New task';
  document.getElementById('dtext').value=li?li.dataset.text:'';picked=li&&li.dataset.tags?li.dataset.tags.split('|'):[];
  var f=document.querySelector('.chip.on');if(!li&&f&&f.dataset.f)picked=[f.dataset.f];
  document.getElementById('ddue').value=li?li.dataset.due:'';gs.value=li?li.dataset.group:group;
  document.getElementById('ddel').style.display=li?'':'none';document.getElementById('dnewtag').value='';drawTags();dlg.showModal();document.getElementById('dtext').focus()}}
 document.getElementById('dcancel').onclick=function(){{dlg.close()}};
 document.getElementById('ddel').onclick=function(){{dlg.close();api('delete',{{line:+cur.dataset.line,raw:cur.dataset.raw}})}};
 document.getElementById('dform').addEventListener('submit',function(e){{e.preventDefault();var d={{text:document.getElementById('dtext').value.replace(/\s+/g,' ').trim(),tags:picked,due:document.getElementById('ddue').value,group:gs.value}};
  if(!d.text)return;dlg.close();
  if(cur){{d.line=+cur.dataset.line;d.raw=cur.dataset.raw;api('edit',d)}}else api('add',d)}});
 document.querySelectorAll('.add').forEach(function(b){{b.onclick=function(){{openTask(null,b.dataset.group)}}}});
 document.querySelectorAll('.task').forEach(function(li){{
  li.querySelector('.box').onclick=function(e){{e.stopPropagation();api('toggle',{{line:+li.dataset.line,raw:li.dataset.raw}})}};
  li.querySelector('.tbody').onclick=function(e){{if(e.target.closest('a'))return;openTask(li)}};
  li.draggable=true;li.addEventListener('dragstart',function(e){{e.dataTransfer.setData('text/plain',li.dataset.line);window._drag=li}});
 }});
 document.querySelectorAll('.col').forEach(function(c){{var g=c.querySelector('.add').dataset.group;
  c.addEventListener('dragover',function(e){{e.preventDefault();c.classList.add('drop')}});
  c.addEventListener('dragleave',function(){{c.classList.remove('drop')}});
  c.addEventListener('drop',function(e){{e.preventDefault();c.classList.remove('drop');var li=window._drag;if(!li||li.dataset.group===g)return;
   api('move',{{line:+li.dataset.line,raw:li.dataset.raw,group:g}})}})}});
 // stages
 var sdlg=document.getElementById('sdlg'),scard=null,ss=document.getElementById('sstage');
 STAGES.forEach(function(s){{var o=document.createElement('option');o.textContent=s;ss.appendChild(o)}});
 function openStage(card,stage){{scard=card;document.getElementById('stitle').textContent=card.dataset.tag;ss.value=stage||card.dataset.stage||STAGES[0];
  document.getElementById('snote').value=card.dataset.note;sdlg.showModal()}}
 document.getElementById('scancel').onclick=function(){{sdlg.close()}};
 document.getElementById('sform').addEventListener('submit',function(e){{e.preventDefault();sdlg.close();
  api('stage',{{name:scard.dataset.tag,stage:ss.value,note:document.getElementById('snote').value.replace(/\s+/g,' ').trim()}})}});
 document.querySelectorAll('.card[data-tag]').forEach(function(card){{
  card.querySelectorAll('.track li').forEach(function(li){{li.onclick=function(){{openStage(card,li.dataset.stage)}}}});
  card.querySelector('.note').onclick=function(e){{if(e.target.closest('a'))return;openStage(card)}};
  card.querySelector('.open').onclick=function(e){{e.preventDefault();fetch('/open',{{method:'POST',headers:{{'Content-Type':'application/json','X-Token':TOKEN}},body:JSON.stringify({{file:this.dataset.file}})}})
   .then(function(r){{return r.json()}}).then(function(j){{if(j.url){{location.href=j.url;toast('Downloading a copy. Edit the synced file in Word for changes to stick.');return}}toast(j.ok?'Opening in Word…':(j.error||'Could not open'))}})}};
 }});
}}
var STR={{strs}};
</script></body></html>"""
def main():
    strands = [strand_info(n, s) for n, s in STRANDS]
    stages, groups, order = parse_tasks(os.path.join(ROOT, "Tasks.md"))
    out = render(strands, stages, groups, order).replace("{strs}", json.dumps([n for n, _ in STRANDS]))
    dest = os.path.join(ROOT, "Dashboard.html")
    with open(dest, "w", encoding="utf-8") as f: f.write(out)
    print("Wrote", dest)

if __name__ == "__main__":
    main()
