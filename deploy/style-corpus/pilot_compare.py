#!/usr/bin/env python3
"""Blind side-by-side: current review prompt vs. the same prompt plus field exemplars.

  python pilot_compare.py --strand Censorship --n 8 --engines codex,claude

For each engine it sends the SAME selected paragraphs twice (A = current dashboard prompt,
B = current prompt + corpus block), applies each answer's suggestions to the paragraphs, runs
the guards, and writes a self-contained HTML page where the two versions appear as
"Version 1/2" in random order. Austin picks the better one per paragraph; the key and the
architecture numbers are hidden in a fold at the bottom. Nothing is written to the strands.
"""
import argparse, concurrent.futures as cf, datetime as dt, difflib, html, json, os, random, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arch, guard
from common import db, OUT_DIR
from exemplars import Retriever, corpus_block


def load_dashboard(root):
    sys.path.insert(0, os.path.join(root, "_dashboard"))
    argv = sys.argv; sys.argv = sys.argv[:1]
    import gpt_review, make_dashboard
    sys.argv = argv
    return gpt_review, dict(make_dashboard.STRANDS)


JSON_TAIL = """

######## OUTPUT ########
Return ONLY one JSON object, no prose before or after, matching:
{"overall": string, "suggestions": [{"paragraph": int, "old": string, "new": string or null, "why": string}]}
"""


def call_claude(prompt, workdir):
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", "1",
           "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task"]
    r = subprocess.run(cmd, input=prompt + JSON_TAIL, capture_output=True, text=True, cwd=workdir, timeout=20 * 60)
    try: out = json.loads(r.stdout).get("result", "")
    except ValueError: out = r.stdout
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m: raise RuntimeError("Claude returned no JSON: " + (r.stderr or out)[-300:])
    return json.loads(m.group(0))


def ask(gr, engine, prompt):
    with tempfile.TemporaryDirectory(prefix="pilot_") as wd:
        if engine == "dry":  # pipeline check without calling any model
            return {"overall": f"dry run ({len(prompt)} chars)", "suggestions": []}
        return gr.call_codex(prompt, wd) if engine == "codex" else call_claude(prompt, wd)


def apply(gr, paras, answer, con):
    """Apply valid suggestions to a copy of the paragraphs. Returns (revised {i: text}, notes {i: [..]})."""
    text = {i: t for i, t, _ in paras}; rev = dict(text); notes = {i: [] for i in text}
    for s in answer.get("suggestions", []):
        i, old, new, why = s.get("paragraph"), s.get("old") or "", s.get("new"), (s.get("why") or "").strip()
        if i not in text or not old or text[i].count(old) != 1:
            continue
        flags = []
        if new is not None and new != old:
            if gr.adds_evidence(old, new): flags.append("adds a citation, year, page or quotation (would be shown as a note only)")
            flags += guard.check(old, new, con)
            if old in rev[i] and not flags: rev[i] = rev[i].replace(old, new, 1)
        notes[i].append({"old": old, "new": new, "why": why, "flags": flags})
    return rev, notes


def diff_html(a, b):
    aw, bw = re.findall(r"\S+|\s+", a), re.findall(r"\S+|\s+", b); out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw, autojunk=False).get_opcodes():
        if op == "equal": out.append(html.escape("".join(aw[i1:i2])))
        if op in ("delete", "replace"): out.append("<del>" + html.escape("".join(aw[i1:i2])) + "</del>")
        if op in ("insert", "replace"): out.append("<ins>" + html.escape("".join(bw[j1:j2])) + "</ins>")
    return "".join(out)


CSS = """
:root{--bg:#fbfaf7;--fg:#1f1d1a;--mute:#6b665e;--card:#fff;--line:#e4e0d8;--ins:#dff3e4;--del:#f8dcdc;--acc:#2f5d8a;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#171614;--fg:#ece8e1;--mute:#a39d93;--card:#211f1c;--line:#38342e;--ins:#1f4a2c;--del:#5a2424;--acc:#8db7e3;--warn:#e7a54a}}
body{background:var(--bg);color:var(--fg);font:16px/1.55 Georgia,serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:auto} h1{font-size:1.5rem;margin:.2em 0} .mute{color:var(--mute);font-size:.9rem}
.p{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:22px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px} @media(max-width:800px){.grid{grid-template-columns:1fr}}
.v h3{font:600 .95rem system-ui,sans-serif;margin:.2em 0 .5em} ins{background:var(--ins);text-decoration:none} del{background:var(--del)}
.why{font:.85rem/1.4 system-ui,sans-serif;color:var(--mute);margin:.4em 0 0 0;padding-left:1.1em} .flag{color:var(--warn)}
.orig{font-size:.95rem;color:var(--mute);border-left:3px solid var(--line);padding-left:10px;margin-bottom:12px}
.vote{font:.9rem system-ui,sans-serif;margin-top:10px} .vote label{margin-right:14px}
button{font:600 .9rem system-ui,sans-serif;padding:8px 14px;border-radius:8px;border:1px solid var(--acc);background:none;color:var(--acc);cursor:pointer}
table{border-collapse:collapse;font:.85rem system-ui,sans-serif} td,th{border:1px solid var(--line);padding:4px 8px;text-align:right} th:first-child,td:first-child{text-align:left}
details{margin-top:28px} textarea{width:100%;height:120px;margin-top:8px;background:var(--card);color:var(--fg);border:1px solid var(--line)}
"""


def render(name, engine_runs, paras, out_path):
    text = {i: t for i, t, _ in paras}
    H = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Corpus pilot</title><style>{CSS}</style></head><body><main>",
         f"<h1>Corpus pilot: {html.escape(name)}</h1>",
         "<p class='mute'>Each paragraph was reviewed twice by the same model: once with the current dashboard prompt, once with field exemplars from your library added. "
         "The order is random per model, so you don't know which is which. Pick the version whose edits sound more like publishable writing in your field (or 'neither'), then press Copy and paste the result into the thread. "
         "Edits a guard blocked (published wording, an AI-typical phrase, an added citation) are listed but not applied.</p>"]
    for eng, run in engine_runs.items():
        H.append(f"<h2>{'GPT (Codex)' if eng == 'codex' else 'Claude'}</h2>")
        for i in run["targets"]:
            H.append(f"<div class='p'><div class='orig'><b>Original</b> \u00b6{i}: {html.escape(text[i])}</div><div class='grid'>")
            for slot, arm in enumerate(run["order"], 1):
                rev, notes = run[arm]["rev"], run[arm]["notes"]
                H.append(f"<div class='v'><h3>Version {slot}</h3><div>{diff_html(text[i], rev[i])}</div><ul class='why'>")
                for n in notes.get(i, []):
                    fl = "".join(f"<div class='flag'>Blocked: {html.escape(f)}</div>" for f in n["flags"])
                    kind = "note" if n["new"] is None else "edit"
                    H.append(f"<li>{kind}: {html.escape(n['why'])}{fl}</li>")
                if not notes.get(i): H.append("<li>no change suggested</li>")
                H.append("</ul></div>")
            q = f"{eng}-{i}"
            H.append(f"</div><div class='vote'>Better: <label><input type=radio name='{q}' value='1'> Version 1</label><label><input type=radio name='{q}' value='2'> Version 2</label>"
                     f"<label><input type=radio name='{q}' value='same'> about the same</label><label><input type=radio name='{q}' value='neither'> neither is good</label></div></div>")
    H.append("<button onclick='copyVotes()'>Copy my choices</button><textarea id='out' placeholder='Your choices appear here'></textarea>")
    # hidden key + numbers
    H.append("<details><summary>Reveal which version had the corpus, and the paragraph-shape numbers</summary>")
    for eng, run in engine_runs.items():
        H.append(f"<p><b>{eng}</b>: Version 1 = {'corpus' if run['order'][0] == 'B' else 'current prompt'}, Version 2 = {'corpus' if run['order'][1] == 'B' else 'current prompt'}.</p>")
        rows = [("Original", run["orig_arch"]), ("Current prompt", run["A"]["arch"]), ("With corpus", run["B"]["arch"]), ("Field (citing ¶s)", run.get("field") or {})]
        H.append("<table><tr><th>measure</th>" + "".join(f"<th>{r}</th>" for r, _ in rows) + "</tr>")
        for k in ["sandwich_pct", "abstract_open_pct", "abstract_close_pct", "modal_also_open_pct", "rather_than_per1k", "antithesis_per1k", "ing_tail_per1k", "sent_len_mean"]:
            H.append(f"<tr><td>{arch.LABELS[k]}</td>" + "".join(f"<td>{d.get(k, '')}</td>" for _, d in rows) + "</tr>")
        H.append("</table>")
        for arm in ("A", "B"):
            H.append(f"<p class='mute'>{'Current' if arm == 'A' else 'Corpus'} overall read: {html.escape(run[arm]['overall'])}</p>")
    H.append("</details>")
    order_js = json.dumps({e: r["order"] for e, r in engine_runs.items()})
    H.append("<script>function copyVotes(){const o=[];document.querySelectorAll('.vote').forEach(v=>{const c=v.querySelector('input:checked');const n=v.querySelector('input').name;o.push(n+': '+(c?c.value:'-'))});"
             f"const t='Corpus pilot choices ({html.escape(name)}), key {html.escape(order_js)}\\n'+o.join('\\n');document.getElementById('out').value=t;try{{navigator.clipboard.writeText(t)}}catch(e){{}}}}</script>")
    H.append("</main></body></html>")
    open(out_path, "w", encoding="utf-8").write("\n".join(H))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strand", default="Censorship"); ap.add_argument("--root", default=os.path.expanduser("~/Strands"))
    ap.add_argument("--n", type=int, default=8); ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--engines", default="codex,claude"); ap.add_argument("--out", default=os.path.join(OUT_DIR, "pilot"))
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    gr, stems = load_dashboard(a.root)
    if a.strand not in stems: sys.exit(f"Unknown strand; choose {', '.join(stems)}")
    allp = gr.manuscript(os.path.join(a.root, stems[a.strand] + ".docx"))
    from exemplars import pick_targets
    targets = [i for i, _ in pick_targets(allp, a.n)]
    sub = [p for p in allp if p[0] in targets]
    base = gr.build_prompt(a.strand, sub)
    block, used = corpus_block(allp, Retriever(), k=a.k, targets=targets)
    corpus = base.replace("\n\n######## STRAND:", "\n\n" + block + "\n\n######## STRAND:", 1)
    os.makedirs(a.out, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    open(os.path.join(a.out, f"prompt_corpus_{a.strand}_{stamp}.txt"), "w").write(corpus)
    rnd = random.Random(a.seed)
    con = db(); field = (json.load(open(os.path.join(OUT_DIR, "profile.json"))).get("field_core_citing") if os.path.exists(os.path.join(OUT_DIR, "profile.json")) else {})
    engines = [e.strip() for e in a.engines.split(",") if e.strip()]
    jobs = {(e, arm): p for e in engines for arm, p in (("A", base), ("B", corpus))}
    print(f"{len(targets)} paragraphs; prompts ~{len(base)//4000}k / ~{len(corpus)//4000}k tokens; running {len(jobs)} reviews…", flush=True)
    answers = {}
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        fut = {ex.submit(ask, gr, e, p): (e, arm) for (e, arm), p in jobs.items()}
        for f in cf.as_completed(fut):
            k = fut[f]
            try: answers[k] = f.result(); print("done", k, flush=True)
            except Exception as err: print("FAILED", k, err, flush=True); answers[k] = {"overall": f"(failed: {err})", "suggestions": []}
    runs = {}
    for e in engines:
        order = ["A", "B"]; rnd.shuffle(order)
        run = {"targets": targets, "order": order, "field": field, "orig_arch": arch.summarize([t for _, t, _ in sub])}
        for arm in ("A", "B"):
            rev, notes = apply(gr, sub, answers[(e, arm)], con)
            run[arm] = {"rev": rev, "notes": notes, "overall": answers[(e, arm)].get("overall", ""), "arch": arch.summarize(list(rev.values())),
                        "n_suggestions": len(answers[(e, arm)].get("suggestions", []))}
        runs[e] = run
    out_html = os.path.join(a.out, f"side_by_side_{a.strand}_{stamp}.html")
    render(a.strand, runs, sub, out_html)
    json.dump({"strand": a.strand, "targets": targets, "used_exemplars": used, "answers": {f"{e}|{arm}": v for (e, arm), v in answers.items()},
               "order": {e: r["order"] for e, r in runs.items()}}, open(out_html[:-5] + ".json", "w"), indent=1)
    print(out_html)


if __name__ == "__main__":
    main()
