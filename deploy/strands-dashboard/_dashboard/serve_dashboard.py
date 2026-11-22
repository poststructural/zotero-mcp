#!/usr/bin/env python3
"""Interactive dashboard: a tiny server on this computer only (127.0.0.1).

Open http://127.0.0.1:8765/ (the .bat does this). Ticking, adding, editing,
moving and deleting tasks, and changing a strand's stage, all write straight to
Tasks.md, so Tasks.md stays the single list that Claude also reads and edits.
Each page load re-reads the Word files, so counts are always current.
Standard library only. Nothing is sent anywhere. Close the window to stop it.
"""
import json, os, re, secrets, sys, threading, webbrowser, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_dashboard as md  # noqa: E402
import review as rv  # noqa: E402
import gpt_review as gpt  # noqa: E402
from urllib.parse import urlparse, parse_qs

# Server mode (Ubuntu, behind Cloudflare Access) is set by environment variables;
# with none set this behaves exactly as on the PC.
PORT = int(os.environ.get("DASH_PORT", "8765"))
BIND = os.environ.get("DASH_BIND", "127.0.0.1")
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("DASH_HOSTS", "").split(",") if h.strip()}
SERVER = bool(os.environ.get("DASH_SERVER"))
TOKEN = secrets.token_urlsafe(16)
TASKS = os.path.join(md.ROOT, "Tasks.md")
LOCK = threading.Lock()
TASK_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*)$")

class Conflict(Exception): pass
class Bad(Exception): pass

# ---------- Tasks.md editing ----------
def load():
    if not os.path.exists(TASKS): return ["# Dissertation tasks", "", "## Strand stages", "", "## Waiting on you"], "\n"
    with open(TASKS, encoding="utf-8", newline="") as f: data = f.read()
    nl = "\r\n" if "\r\n" in data else "\n"
    return data.replace("\r\n", "\n").split("\n"), nl

def save(lines, nl):
    tmp = TASKS + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f: f.write(nl.join(lines))
    os.replace(tmp, TASKS)

def check(lines, i, raw):
    if not (0 <= i < len(lines)) or lines[i].rstrip() != raw.rstrip():
        raise Conflict("Tasks.md changed since this page loaded. Reloading…")

def clean_text(t):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    if not t: raise Bad("The task needs some text.")
    return t

def build(done, text, tags, due):
    tags = [re.sub(r"[\[\]\n]", "", str(x)).strip() for x in (tags or [])]
    due = str(due or "")
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due): raise Bad("Due date must be YYYY-MM-DD.")
    line = f"- [{'x' if done else ' '}] {clean_text(text)}"
    line += "".join(f" [{t}]" for t in tags if t)
    return line + (f" due:{due}" if due else "")

def section(lines, name):
    """(heading index, end index) of the '## name' section, or None."""
    for i, l in enumerate(lines):
        if re.match(r"^##\s+", l) and l[2:].strip() == name:
            j = i + 1
            while j < len(lines) and not re.match(r"^##\s+", lines[j]): j += 1
            return i, j
    return None

def insert_pos(lines, name):
    sec = section(lines, name)
    if sec is None:
        while lines and not lines[-1].strip(): lines.pop()
        lines += ["", f"## {name}"]
        return len(lines)
    i, j = sec
    k = j
    while k - 1 > i and not lines[k - 1].strip(): k -= 1
    return k

def apply(op, d):
    lines, nl = load()
    if op in ("toggle", "edit", "delete", "move"):
        i = int(d.get("line", -1)); check(lines, i, d.get("raw", ""))
        m = TASK_RE.match(lines[i])
        if not m: raise Conflict("That line is no longer a task. Reloading…")
        done = m.group(1) != " "
    if op == "toggle":
        lines[i] = re.sub(r"\[( |x|X)\]", "[ ]" if done else "[x]", lines[i], count=1)
    elif op == "delete":
        del lines[i]
    elif op == "edit":
        new = build(done, d.get("text"), d.get("tags"), d.get("due"))
        group = str(d.get("group") or "")
        sec = section(lines, group)
        if group and (sec is None or not (sec[0] < i < sec[1])):
            del lines[i]; lines.insert(insert_pos(lines, group), new)
        else:
            lines[i] = new
    elif op == "move":
        raw = lines[i].strip(); del lines[i]
        if str(d.get("group")).strip().lower() == "done": raw = re.sub(r"\[ \]", "[x]", raw, count=1)
        lines.insert(insert_pos(lines, str(d.get("group"))), raw)
    elif op == "add":
        new = build(False, d.get("text"), d.get("tags"), d.get("due"))
        lines.insert(insert_pos(lines, str(d.get("group") or "Waiting on you")), new)
    elif op == "stage":
        name = str(d.get("name", "")); stage = str(d.get("stage", ""))
        if stage not in md.STAGES: raise Bad("Unknown stage.")
        note = re.sub(r"\s+", " ", str(d.get("note") or "")).replace("|", "/").strip()
        new = f"{name} | {stage} | {note}".rstrip(" |") if note else f"{name} | {stage}"
        sec = next((s for s in [section(lines, x) for x in ("Strand stages", "Strand stage")] if s), None)
        if sec is None:
            pos = next((k for k, l in enumerate(lines) if l.startswith("## ")), len(lines))
            lines[pos:pos] = ["## Strand stages", new, ""]
        else:
            hit = next((k for k in range(sec[0] + 1, sec[1]) if re.match(r"^[-*]?\s*" + re.escape(name) + r"\s*\|", lines[k])), None)
            if hit is None: lines.insert(insert_pos(lines, lines[sec[0]][2:].strip()), new)
            else: lines[hit] = new
    else:
        raise Bad("Unknown action.")
    save(lines, nl)

# ---------- review actions ----------
def claude_group():
    _, _, order = md.parse_tasks(TASKS)
    return next((g for g in order if "claude" in g.lower()), "Claude does next")

def review_op(d):
    name = str(d.get("strand", "")); strands = dict(md.STRANDS)
    if name not in strands: raise Bad("Unknown strand.")
    stem = strands[name]; path = os.path.join(md.ROOT, stem + ".docx")
    op = str(d.get("op")); i = int(d.get("i", -1)); ex = d.get("expect", "")
    if op == "accept":
        rv.change(path, md.ROOT, "accept", i, ex); rv.mark(md.ROOT, name, ex)
    elif op == "unreview":
        rv.mark(md.ROOT, name, ex, False)
    elif op in ("set_text", "revert"):
        if op == "set_text":
            new = str(d.get("text", "")).replace("\r\n", "\n").strip()
        else:
            cur = rv.paragraphs(path); base = rv.paragraphs(rv.baseline_for(md.ROOT, stem))
            b = rv.align(cur, base)[0].get(i)
            if not b: raise rv.Refused("No Nov 18 version of this paragraph was found.")
            new = b["text"]
        if not new: raise Bad("The paragraph can't be empty. Use Delete instead.")
        rv.change(path, md.ROOT, "set_text", i, ex, new_text=new); rv.mark(md.ROOT, name, new)
    elif op == "delete":
        rv.change(path, md.ROOT, "delete", i, ex)
    elif op == "restore":
        bp = rv.baseline_for(md.ROOT, stem)
        base = rv.paragraphs(bp); bi = int(d.get("base", -1))
        if not (0 <= bi < len(base)): raise Bad("Unknown paragraph.")
        bx = rv.GREEN.sub("", base[bi]["xml"])
        if i < 0: raise rv.Refused("This one sits at the very top; ask Claude to restore it.")
        rv.change(path, md.ROOT, "restore", i, ex, base_xml=bx); rv.mark(md.ROOT, name, base[bi]["text"])
    elif op == "s_accept":
        items = rv.load_sugg(md.ROOT, stem)
        sg = next((x for x in items if x.get("id") == d.get("id")), None)
        if not sg or sg.get("status", "pending") != "pending": raise Conflict("That suggestion is gone. Reloading…")
        if "text" in d:
            new = str(d.get("text", "")).replace("\r\n", "\n").strip(); status = "edited"
        else:
            new = rv.sugg_result(ex, sg); status = "accepted"
        if new != ex:
            if sg.get("old") and sg["old"] not in ex: raise Conflict("The paragraph changed since this suggestion was made. Reloading…")
            rv.change(path, md.ROOT, "set_text", i, ex, new_text=new)
        rv.set_status(md.ROOT, stem, sg["id"], status)
    elif op == "s_reject":
        rv.set_status(md.ROOT, stem, str(d.get("id")), "rejected")
    elif op == "ok_removed":
        rv.mark(md.ROOT, name, "removed:" + str(d.get("key", "")))
    elif op == "note":
        note = re.sub(r"\s+", " ", str(d.get("note", ""))).strip()
        if not note: raise Bad("The note is empty.")
        cur = rv.paragraphs(path)
        if not (0 <= i < len(cur)) or cur[i]["text"] != ex: raise Conflict("The document changed since this page loaded. Reloading…")
        rv.add_note(md.ROOT, name, ex, note)
        words = ex.split(); lead = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
        apply("add", {"text": f'Paragraph "{lead}": {note}', "tags": [name], "group": claude_group()})
    else:
        raise Bad("Unknown action.")

# ---------- GPT second opinion (runs in the background) ----------
JOBS = {}  # strand name -> {"state": "running"|"done"|"error", "msg": str, "when": str}

def gpt_start(name):
    strands = dict(md.STRANDS)
    if name not in strands: raise Bad("Unknown strand.")
    if JOBS.get(name, {}).get("state") == "running": raise Bad("GPT is already reading this strand.")
    try: gpt.codex_path()
    except gpt.Unavailable as e: raise Bad(str(e))
    import time
    JOBS[name] = {"state": "running", "msg": "Starting GPT…", "when": time.strftime("%H:%M")}
    def work():
        def prog(m): JOBS[name]["msg"] = m
        try:
            a, dr, dg = gpt.run(md.ROOT, name, strands[name], lock=LOCK, progress=prog)
            extra = (f" {dr} didn't match the text and were dropped." if dr else "") + \
                    (f" {dg} rewrite(s) that added a citation, page or quotation became notes." if dg else "")
            JOBS[name] = {"state": "done", "msg": f"GPT added {a} suggestion(s).{extra}", "when": time.strftime("%H:%M")}
        except gpt.Unavailable as e:
            JOBS[name] = {"state": "error", "msg": str(e), "when": time.strftime("%H:%M")}
        except Exception as e:
            JOBS[name] = {"state": "error", "msg": f"GPT review failed: {e}", "when": time.strftime("%H:%M")}
    threading.Thread(target=work, daemon=True).start()

# ---------- pages ----------
def page():
    strands = [md.strand_info(n, s) for n, s in md.STRANDS]
    stages, groups, order = md.parse_tasks(TASKS)
    strs = json.dumps([n for n, _ in md.STRANDS])
    prog = {}
    for n, stem in md.STRANDS:
        try: prog[n] = rv.progress(md.ROOT, n, stem)
        except Exception: prog[n] = None
    live = md.render(strands, stages, groups, order, live=True, token=TOKEN, progress=prog).replace("{strs}", strs)
    static = md.render(strands, stages, groups, order).replace("{strs}", strs)
    try:
        with open(os.path.join(md.ROOT, "Dashboard.html"), "w", encoding="utf-8") as f: f.write(static)
    except OSError: pass
    return live

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def host_ok(self):
        h = self.headers.get("Host", "").lower()
        return h in (f"127.0.0.1:{PORT}", f"localhost:{PORT}") or h in EXTRA_HOSTS
    def send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if not self.host_ok(): return self.send(403, '{"error":"forbidden"}')
        u = urlparse(self.path)
        if u.path == "/review":
            name = (parse_qs(u.query).get("s") or [md.STRANDS[0][0]])[0]
            if name not in dict(md.STRANDS): return self.send(404, "Unknown strand", "text/plain")
            try:
                with LOCK: out = rv.render_page(md.ROOT, md.STRANDS, name, TOKEN)
                return self.send(200, out, "text/html")
            except Exception as e:
                return self.send(500, f"<pre>Review error: {md.E(e)}</pre>", "text/html")
        if u.path == "/file":
            q = parse_qs(u.query)
            f = (q.get("f") or [""])[0]
            if (q.get("t") or [""])[0] != TOKEN or f not in {s + ".docx" for _, s in md.STRANDS}:
                return self.send(403, '{"error":"forbidden"}')
            with open(os.path.join(md.ROOT, f), "rb") as fh: data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", f'attachment; filename="{f}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if u.path == "/gpt_status":
            name = (parse_qs(u.query).get("s") or [""])[0]
            return self.send(200, json.dumps(JOBS.get(name) or {"state": "idle"}))
        if u.path in ("/", "/index.html"):
            try:
                with LOCK: html = page()
                self.send(200, html, "text/html")
            except Exception as e:
                self.send(500, f"<pre>Dashboard error: {md.E(e)}</pre>", "text/html")
        else:
            self.send(404, '{"error":"not found"}')
    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-Token") != TOKEN:
            return self.send(403, '{"error":"Forbidden. Reload the page."}')
        try:
            n = int(self.headers.get("Content-Length", "0"))
            d = json.loads(self.rfile.read(min(n, 100000)) or b"{}")
        except Exception:
            return self.send(400, '{"error":"Bad request"}')
        if self.path == "/open":
            names = {s + ".docx" for _, s in md.STRANDS}
            f = d.get("file")
            if f not in names: return self.send(400, '{"error":"Unknown file"}')
            p = os.path.join(md.ROOT, f)
            if SERVER:
                from urllib.parse import quote
                return self.send(200, json.dumps({"ok": True, "url": f"/file?f={quote(f)}&t={TOKEN}"}))
            try:
                if hasattr(os, "startfile"): os.startfile(p)
                elif sys.platform == "darwin": subprocess.Popen(["open", p])
                else: subprocess.Popen(["xdg-open", p])
                return self.send(200, '{"ok":true}')
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)}))
        if self.path == "/gpt":
            try:
                gpt_start(str(d.get("strand", "")))
                return self.send(200, '{"ok":true}')
            except Bad as e: return self.send(400, json.dumps({"error": str(e)}))
        if self.path == "/review":
            try:
                with LOCK: review_op(d)
                return self.send(200, '{"ok":true}')
            except (rv.Conflict, Conflict) as e: return self.send(409, json.dumps({"error": str(e)}))
            except (rv.Refused, Bad) as e: return self.send(400, json.dumps({"error": str(e)}))
            except Exception as e: return self.send(500, json.dumps({"error": f"Error: {e}"}))
        if self.path != "/api": return self.send(404, '{"error":"not found"}')
        try:
            with LOCK: apply(str(d.get("op")), d)
            self.send(200, '{"ok":true}')
        except Conflict as e: self.send(409, json.dumps({"error": str(e)}))
        except Bad as e: self.send(400, json.dumps({"error": str(e)}))
        except Exception as e: self.send(500, json.dumps({"error": f"Error: {e}"}))

def main():
    url = f"http://127.0.0.1:{PORT}/"
    try:
        srv = ThreadingHTTPServer((BIND, PORT), H)
    except OSError:
        print("The dashboard is already running. Opening it in your browser.")
        webbrowser.open(url); return
    print(f"Dashboard running at {url}\nKeep this window open while you use it. Close it to stop.")
    if "--no-browser" not in sys.argv and not SERVER: webbrowser.open(url)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
