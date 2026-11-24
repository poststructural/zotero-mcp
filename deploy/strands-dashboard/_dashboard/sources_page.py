"""Sources to find: the books, articles and reports the strands cite that you still need a copy of.

Data lives in needed_sources.json next to this file (Claude adds rows; the page changes only "status",
"zotero_key", "has_pdf" and "checked"). The page is served at /sources by serve_dashboard.py.
"Recheck Zotero" uses the read-only key in ~/style_corpus/zotero.env (or "zotero_env" in gpt_settings.json)
and only reads from Zotero. Standard library only.
"""
import datetime as dt, difflib, html, json, os, re, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "needed_sources.json")
SETTINGS = os.path.join(HERE, "gpt_settings.json")
STATUSES = ["needed", "requested", "in Zotero"]
E = lambda s: html.escape(str(s if s is not None else ""), quote=True)


class Bad(Exception): pass


def load():
    try:
        with open(DATA, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return []


def save(rows):
    with open(DATA + ".tmp", "w", encoding="utf-8") as f: json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(DATA + ".tmp", DATA)


def set_status(sid, status):
    if status not in STATUSES: raise Bad("Unknown status")
    rows = load()
    for r in rows:
        if r.get("id") == sid:
            r["status"] = status; save(rows); return r
    raise Bad("That source is no longer in the list. Reload the page.")


# ---------- Zotero (read-only) ----------
def _env():
    path = os.path.expanduser("~/style_corpus/zotero.env")
    try:
        with open(SETTINGS, encoding="utf-8") as f: path = json.load(f).get("zotero_env", path)
    except (OSError, ValueError): pass
    env = {}
    try:
        for line in open(os.path.expanduser(path), encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError: pass
    if not env.get("ZOTERO_API_KEY") or not env.get("ZOTERO_LIBRARY_ID"):
        raise Bad("No Zotero key on this computer, so the recheck can only run on the server dashboard.")
    return env


def _get(env, path, params):
    kind = "groups" if env.get("ZOTERO_LIBRARY_TYPE", "user").startswith("group") else "users"
    url = f"https://api.zotero.org/{kind}/{env['ZOTERO_LIBRARY_ID']}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Zotero-API-Key": env["ZOTERO_API_KEY"], "Zotero-API-Version": "3"})
    with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)


def _norm(s): return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())
def _digits(s): return re.sub(r"[^0-9Xx]", "", s or "")


def _matches(row, d):
    if row.get("doi") and _norm(d.get("DOI")) == _norm(row["doi"]): return True
    if row.get("isbn") and _digits(row["isbn"]) and _digits(row["isbn"]) in _digits(d.get("ISBN")): return True
    t1, t2 = _norm(row.get("title")).split(" not matched")[0], _norm(d.get("title"))
    year = re.search(r"\d{4}", d.get("date") or "")
    sn = _norm((row.get("authors") or "").split(";")[0].split(",")[0]).split()
    names = _norm(" ".join(c.get("lastName", "") or c.get("name", "") for c in d.get("creators", [])))
    return bool(t1 and t2 and difflib.SequenceMatcher(None, t1, t2).ratio() >= 0.9 and year
                and int(year.group(0)) == int(row.get("year") or 0) and (not sn or sn[-1] in names))


def recheck():
    env = _env(); rows = load(); found = 0
    for r in rows:
        if r.get("has_pdf"): continue
        q = (r.get("doi") or "") or " ".join(_norm(r.get("title")).split(" not matched")[0].split()[:8])
        if not q: continue
        try: items = _get(env, "/items/top", {"q": q, "qmode": "everything" if r.get("doi") else "titleCreatorYear", "limit": 10})
        except Exception: continue
        hit = next((it for it in items if _matches(r, it.get("data", {}))), None)
        if not hit: continue
        key = hit["key"]
        try: kids = _get(env, f"/items/{key}/children", {"limit": 50})
        except Exception: kids = []
        r["zotero_key"] = key
        r["has_pdf"] = any(k.get("data", {}).get("contentType") == "application/pdf" for k in kids)
        if r["has_pdf"]: r["status"] = "in Zotero"; found += 1   # a record without a PDF is still needed
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for r in rows: r["checked"] = stamp
    save(rows)
    return {"found": found, "checked": stamp}


# ---------- page ----------
def _links(r):
    out = []
    if r.get("doi"): out.append(f'<a href="https://doi.org/{E(r["doi"])}" target="_blank" rel="noopener">DOI</a>')
    if r.get("oa_url"): out.append(f'<a class="oa" href="{E(r["oa_url"])}" target="_blank" rel="noopener">free copy</a>')
    if r.get("uconn_url"): out.append(f'<a href="{E(r["uconn_url"])}" target="_blank" rel="noopener">UConn</a>')
    if r.get("url") and r.get("url") != r.get("oa_url"): out.append(f'<a href="{E(r["url"])}" target="_blank" rel="noopener">web</a>')
    if r.get("isbn"): out.append(f'<a href="https://openlibrary.org/isbn/{E(_digits(r["isbn"]))}" target="_blank" rel="noopener">Open Library</a>')
    return " · ".join(out)


def render(token):
    rows = load()
    strands = []
    for r in rows:
        for s in r.get("strands") or ["Other"]:
            if s not in strands: strands.append(s)
    n_need = sum(1 for r in rows if r.get("status") == "needed")
    n_id = sum(1 for r in rows if r.get("doi") or r.get("isbn"))
    groups = []
    for s in strands:
        trs = []
        for r in [r for r in rows if s in (r.get("strands") or ["Other"])]:
            opts = "".join(f'<option{" selected" if r.get("status") == st else ""}>{E(st)}</option>' for st in STATUSES)
            ident = (f'doi:{E(r["doi"])}' if r.get("doi") else "") + (("<br>" if r.get("doi") else "") + f'ISBN {E(r["isbn"])}' if r.get("isbn") else "")
            if not ident: ident = '<span class="muted">not matched</span>'
            if r.get("candidate_doi") and not r.get("doi"): ident += f'<br><span class="muted">candidate: {E(r["candidate_doi"])}</span>'
            pdf = "" if r.get("has_pdf") is None else (' <span class="tag">PDF in Zotero</span>' if r.get("has_pdf") else ' <span class="tag warn">no PDF yet</span>')
            trs.append(
                f'<tr data-id="{E(r["id"])}" data-status="{E(r.get("status"))}" data-ident="{E(r.get("doi") or r.get("isbn") or "")}">'
                f'<td data-k="{E(r.get("authors"))}">{E(r.get("authors"))}</td><td data-k="{E(r.get("year"))}">{E(r.get("year"))}</td>'
                f'<td data-k="{E(r.get("title"))}"><b>{E(r.get("title"))}</b><div class="muted small">{E(r.get("container"))}{" · " if r.get("container") else ""}{E(r.get("type"))} · cited as “{E(r.get("cited_as"))}”</div>'
                f'<div class="need">{E(r.get("needed_for"))}</div></td>'
                f'<td class="small" data-k="{E(r.get("doi") or r.get("isbn") or "~")}">{ident}</td><td class="small">{_links(r)}</td>'
                f'<td data-k="{E(r.get("status"))}"><select class="st">{opts}</select>{pdf}</td></tr>')
        groups.append(f'<h2 class="sect">{E(s)} <span class="muted small">({len(trs)})</span></h2>'
                      '<table class="src"><thead><tr><th>Author(s)</th><th>Year</th><th>Title · why it is needed</th><th>DOI / ISBN</th><th>Find it</th><th>Status</th></tr></thead>'
                      f'<tbody>{"".join(trs)}</tbody></table>')
    checked = max((r.get("checked") or "" for r in rows), default="")
    return PAGE.format(token=E(token), groups="".join(groups) or "<p>Nothing on the list.</p>", total=len(rows), need=n_need, ids=n_id,
                       checked=E(checked) or "not yet")


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sources to find</title><style>
:root{{--bg:#f6f5f1;--panel:#fff;--ink:#1d1d1b;--muted:#6d6a63;--line:#e3e0d8;--accent:#2f5d8a;--warn:#b5521b;--warnbg:#fbeee5;--info:#2e6b4a;--infobg:#e7f2ec}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328}}}}
:root[data-theme="dark"]{{--bg:#18191b;--panel:#222326;--ink:#ebe9e4;--muted:#9c998f;--line:#35363a;--accent:#8db6e0;--warn:#f0a070;--warnbg:#3a2a20;--info:#86cfa5;--infobg:#1f3328}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:20px 16px 60px}} a{{color:var(--accent)}} h1{{margin:0;font-size:24px}}
.top{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-end}} .muted{{color:var(--muted)}} .small{{font-size:12.5px}}
.btns{{display:flex;gap:8px;flex-wrap:wrap}} button{{font:inherit;font-size:14px;padding:6px 13px;border-radius:7px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}}
button.primary{{background:var(--accent);border-color:var(--accent);color:var(--panel)}}
.sect{{font-size:17px;margin:26px 0 8px}} table.src{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.src th,.src td{{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}} .src th{{font-size:12.5px;color:var(--muted);cursor:pointer;user-select:none;white-space:nowrap}}
.src th:hover{{color:var(--ink)}} .need{{font-size:13px;margin-top:4px}} .tag{{display:inline-block;margin-top:4px;font-size:11.5px;border-radius:4px;padding:0 6px;background:var(--infobg);color:var(--info)}}
.tag.warn{{background:var(--warnbg);color:var(--warn)}} a.oa{{font-weight:600}} select{{font:inherit;font-size:13px;padding:3px 6px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}}
tr[data-status="in Zotero"] td{{opacity:.65}} .note{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:14px;font-size:13.5px}}
#toast{{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 16px;border-radius:8px;font-size:13.5px;display:none;max-width:90vw}}
@media (max-width:760px){{.src thead{{display:none}} .src tr{{display:block;border-bottom:1px solid var(--line)}} .src td{{display:block;border:0;padding:4px 10px}}}}
</style></head><body><main>
<div class="top"><div><a href="/" class="small">← Dashboard</a><h1>Sources to find</h1>
<div class="muted small">{total} sources · {need} still needed · {ids} with a DOI or ISBN · Zotero last checked: {checked}</div></div>
<div class="btns"><button id="copy" class="primary">Copy identifiers</button><button id="recheck">Recheck Zotero</button></div></div>
<div class="note"><b>Copy identifiers</b> copies the DOIs and ISBNs of the sources still marked “needed”, one per line. In Zotero, click the magic wand (Add Item by Identifier) and paste them all. Sources without an identifier need the UConn or web link. <b>Free copy</b> links go to legal open-access copies only. A DOI or ISBN is listed only when the title, author and year matched exactly; a “candidate” still needs checking.</div>
{groups}
</main><div id="toast"></div>
<script>
const TOKEN="{token}";
function toast(m){{const t=document.getElementById('toast');t.textContent=m;t.style.display='block';clearTimeout(window._t);window._t=setTimeout(()=>t.style.display='none',3200)}}
function post(d){{return fetch('/sources',{{method:'POST',headers:{{'Content-Type':'application/json','X-Token':TOKEN}},body:JSON.stringify(d)}}).then(r=>r.json().then(j=>{{if(!r.ok)throw new Error(j.error||r.status);return j}}))}}
document.querySelectorAll('select.st').forEach(s=>s.addEventListener('change',e=>{{const tr=s.closest('tr');post({{op:'status',id:tr.dataset.id,status:s.value}}).then(()=>{{tr.dataset.status=s.value;toast('Saved: '+s.value)}}).catch(err=>toast(err.message))}}));
document.getElementById('copy').onclick=()=>{{const ids=[...document.querySelectorAll('tr[data-status="needed"]')].map(t=>t.dataset.ident).filter(Boolean);const uniq=[...new Set(ids)];if(!uniq.length){{toast('No DOIs or ISBNs among the needed sources.');return}}const txt=uniq.join('\\n');(navigator.clipboard?navigator.clipboard.writeText(txt):Promise.reject()).then(()=>toast('Copied '+uniq.length+' identifier(s). Paste them into Zotero\\'s magic wand.')).catch(()=>{{prompt('Copy these identifiers:',txt)}})}};
document.getElementById('recheck').onclick=e=>{{e.target.disabled=true;toast('Checking Zotero…');post({{op:'recheck'}}).then(j=>{{toast(j.found+' now have a PDF in Zotero. Reloading…');setTimeout(()=>location.reload(),900)}}).catch(err=>{{toast(err.message);e.target.disabled=false}})}};
document.querySelectorAll('table.src').forEach(tb=>tb.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{{const body=tb.tBodies[0];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';[...body.rows].sort((a,b)=>{{const x=(a.cells[i].dataset.k||a.cells[i].textContent).trim(),y=(b.cells[i].dataset.k||b.cells[i].textContent).trim();return (asc?1:-1)*x.localeCompare(y,undefined,{{numeric:true}})}}).forEach(r=>body.appendChild(r))}})));
</script></body></html>"""
