#!/usr/bin/env python3
"""Second opinion from GPT, through the Codex CLI signed in with your ChatGPT plan.

The review page's "Ask GPT" button calls run(). It sends one strand's manuscript
(the text before the revision notes) plus the writing standards in
_dashboard/standards/ to `codex exec`, read-only, with no tools and no files
written by Codex. GPT's edits come back as suggestions in the same
_dashboard/suggestions/<strand>.json that Claude uses, labeled "GPT", so you
accept, edit or reject them in the same place. Nothing is changed in the Word
file until you accept.

Safety checks on what comes back:
- each suggestion must quote text that appears in exactly one paragraph;
- a rewrite that adds a year, page number, citation or quotation that was not
  already in the quoted text is turned into a flag only (no rewrite), because
  GPT cannot see the sources.

Setup (once): install Node.js, then `npm install -g @openai/codex`, then run
`codex login` and choose "Sign in with ChatGPT". Optional settings go in
_dashboard/gpt_settings.json, e.g. {"model": "gpt-5.5", "effort": "high"}.

Command line test:  python gpt_review.py "Censorship"
Standard library only.
"""
import datetime as dt, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review as rv  # noqa: E402

BY = "GPT"
TIMEOUT = 20 * 60
STD_DIR = os.path.join(HERE, "standards")
SETTINGS = os.path.join(HERE, "gpt_settings.json")
OPINIONS = os.path.join(HERE, "second_opinions")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["overall", "suggestions"],
    "properties": {
        "overall": {"type": "string"},
        "suggestions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["paragraph", "old", "new", "why"],
            "properties": {
                "paragraph": {"type": "integer"},
                "old": {"type": "string"},
                "new": {"type": ["string", "null"]},
                "why": {"type": "string"},
            }}},
    },
}

INSTRUCTIONS = """You are giving a second opinion on one strand of a doctoral literature review in secondary English curriculum and instruction, written by Austin (advisor: Dorothea Anagnostopoulos). Another reviewer (Claude) also comments; Austin compares the two. Do not run commands, read files or browse. Work only from the text below.

TASK: REVIEW and light REVISE. Find the highest-leverage problems against the standards below: rubric dimensions, Dorothea's standards, the strand revision checklist, and the structural slop patterns. Propose the smallest effective fix for each. Preserve Austin's syntax, word choices and accepted prose wherever they work. Do not standardize strong passages or rewrite whole paragraphs to your taste.

HARD RULES ON EVIDENCE (these override everything else):
- You cannot see the sources. Never add, change or guess a citation, author, year, page number, quotation, sample size, method or finding.
- Paraphrase takes author and year with no page number; a direct quotation needs a verified page number. If a quotation lacks a page, or a claim needs a source, or a detail looks doubtful, do not fix it: make a flag (new = null) whose "why" begins with [CHECK] and says what must be verified.
- You may insert the literal marker [CHECK] into a rewrite. Keep every existing [CHECK] mark unless the "why" explains that the sentence carrying it was cut.
- Keep a study's results, its authors' interpretations and Austin's own synthesis distinct; flag places where they blur.

FORMAT OF EACH SUGGESTION:
- "paragraph": the number shown in brackets before the paragraph.
- "old": an exact, character-for-character copy of a short span from that paragraph (a phrase or one or two sentences; never the whole paragraph unless it is one sentence). It must occur only once in that paragraph.
- "new": the replacement for exactly that span, or null for a comment-only flag.
- "why": one or two plain sentences naming the problem (cite the rubric dimension, Dorothea standard or slop pattern id where one applies).
Give at most 30 suggestions, most important first. Skip trivia.

"overall": 120-250 words. Score the rubric dimensions that apply (1-4) with a short quoted piece of evidence for each, name the single highest-leverage improvement, and note anything you think Claude-style revision may have flattened. Plain prose, no headings.
"""


class Unavailable(Exception): pass


def settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}


def codex_path():
    p = settings().get("codex_path") or shutil.which("codex")
    if not p and os.name == "nt":
        cand = os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")
        if os.path.exists(cand): p = cand
    if not p:
        raise Unavailable("The Codex CLI isn't installed. In a terminal run: npm install -g @openai/codex  then: codex login  (choose Sign in with ChatGPT).")
    return p


def standards_text():
    if not os.path.isdir(STD_DIR): return ""
    out = []
    for fn in sorted(os.listdir(STD_DIR)):
        if fn.lower().endswith((".md", ".yaml", ".yml", ".txt")):
            with open(os.path.join(STD_DIR, fn), encoding="utf-8") as f:
                out.append(f"===== {fn} =====\n{f.read().strip()}\n")
    return "\n".join(out)


def manuscript(path):
    """[(paragraph index, text, is_heading)] for the manuscript body only."""
    return [(p["i"], p["text"], p["heading"]) for p in rv.paragraphs(path)
            if p["text"].strip() and not p["notes"]]


def build_prompt(name, paras):
    body = "\n\n".join((f"[{i}] ## {t}" if h else f"[{i}] {t}") for i, t, h in paras)
    return (INSTRUCTIONS + "\n\n######## STANDARDS ########\n" + standards_text() +
            f"\n\n######## STRAND: {name} ########\n(Numbers in brackets are paragraph ids; '##' marks a heading.)\n\n" + body + "\n")


CITE_BITS = re.compile(r"\b(?:1[5-9]|20)\d{2}[a-z]?\b|\bpp?\.\s*\d+|\(\s*[A-Z][^()]{0,80}?\d{4}[^()]*\)|[\"“][^\"”]{3,}[\"”]")


def adds_evidence(old, new):
    """True if new introduces a year, page number, parenthetical citation or quotation absent from old."""
    have = set(CITE_BITS.findall(old))
    return any(x not in have and x not in old for x in CITE_BITS.findall(new))


def call_codex(prompt, workdir):
    st = settings()
    schema = os.path.join(workdir, "schema.json"); out = os.path.join(workdir, "answer.json")
    with open(schema, "w", encoding="utf-8") as f: json.dump(SCHEMA, f)
    cmd = [codex_path(), "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
           "-s", "read-only", "-C", workdir, "--output-schema", schema, "-o", out, "--color", "never"]
    if st.get("model"): cmd += ["-m", st["model"]]
    if st.get("effort"): cmd += ["-c", f'model_reasoning_effort="{st["effort"]}"']
    cmd.append("-")
    kw = {}
    if os.name == "nt": kw["creationflags"] = 0x08000000  # no console window
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, **kw)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"GPT took longer than {TIMEOUT // 60} minutes; try again later.")
    if not os.path.exists(out) or not open(out, encoding="utf-8").read().strip():
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
        msg = " ".join(tail)
        if re.search(r"log ?in|auth|401|unauthori", msg, re.I):
            raise Unavailable("Codex isn't signed in. In a terminal run: codex login  and choose Sign in with ChatGPT.")
        if re.search(r"usage limit|rate limit|429|quota", msg, re.I):
            raise Unavailable("Your ChatGPT plan's Codex limit is used up for now. Codex shows the reset time with /status.")
        raise Unavailable("Codex returned nothing. " + msg[-400:])
    raw = open(out, encoding="utf-8").read().strip()
    m = re.search(r"\{.*\}", raw, re.S)
    try: return json.loads(m.group(0) if m else raw)
    except ValueError: raise Unavailable("GPT's answer wasn't readable JSON. Try again.")


def merge(root, name, stem, answer, sent):
    """Validate GPT's suggestions against the CURRENT text and append them. Returns counts."""
    path = os.path.join(root, stem + ".docx")
    cur = {p["i"]: p for p in rv.paragraphs(path) if p["text"].strip() and not p["notes"]}
    sent_text = {i: t for i, t, _ in sent}
    items = rv.load_sugg(root, stem)
    have = {(s.get("old"), s.get("new")) for s in items if s.get("status", "pending") == "pending"}
    n = sum(1 for s in items if str(s.get("id", "")).startswith("g")) + 1
    today = dt.date.today().isoformat()
    added = dropped = downgraded = 0
    for s in answer.get("suggestions", [])[:40]:
        old = str(s.get("old") or ""); new = s.get("new"); why = str(s.get("why") or "").strip()
        pi = s.get("paragraph")
        p = cur.get(pi)
        if not old or p is None or sent_text.get(pi) != p["text"] or p["text"].count(old) != 1 \
                or sum(1 for q in cur.values() if old in q["text"]) != 1:
            dropped += 1; continue
        if new is not None:
            new = str(new)
            if new == old: new = None
            elif adds_evidence(old, new):
                why = (why + " [GPT's rewrite added a citation, year, page or quotation that isn't in the text, so it is shown as a note only.]").strip()
                new = None; downgraded += 1
        if (old, new) in have: continue
        items.append({"id": f"g{n}", "by": BY, "old": old, "new": new, "why": why or "(no reason given)",
                      "date": today, "status": "pending"})
        have.add((old, new)); n += 1; added += 1
    rv.save_sugg(root, stem, items)
    os.makedirs(OPINIONS, exist_ok=True)
    op = os.path.join(OPINIONS, stem + ".json")
    with open(op + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"by": BY, "date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "overall": str(answer.get("overall") or ""),
                   "added": added, "dropped": dropped, "downgraded": downgraded}, f, indent=1, ensure_ascii=False)
    os.replace(op + ".tmp", op)
    return added, dropped, downgraded


def load_opinion(stem):
    try:
        with open(os.path.join(OPINIONS, stem + ".json"), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return None


def run(root, name, stem, lock=None, progress=lambda m: None):
    """Full pass for one strand. `lock` guards file reads/writes; it is NOT held while GPT thinks."""
    codex_path()
    path = os.path.join(root, stem + ".docx")
    if lock:
        with lock: sent = manuscript(path)
    else: sent = manuscript(path)
    prompt = build_prompt(name, sent)
    progress(f"GPT is reading {name} (about {len(prompt) // 4000}k tokens). This usually takes a few minutes.")
    with tempfile.TemporaryDirectory(prefix="gpt_review_") as wd:
        answer = call_codex(prompt, wd)
    if lock:
        with lock: return merge(root, name, stem, answer, sent)
    return merge(root, name, stem, answer, sent)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--root=")), os.path.dirname(HERE))
    prompt_only = "--prompt-only" in sys.argv
    sys.argv = sys.argv[:1]
    import make_dashboard as md
    want = args[0] if args else md.STRANDS[0][0]
    stems = dict(md.STRANDS)
    if want not in stems: sys.exit(f"Unknown strand. Choose one of: {', '.join(stems)}")
    if prompt_only:
        print(build_prompt(want, manuscript(os.path.join(root, stems[want] + ".docx")))); sys.exit()
    a, d, g = run(root, want, stems[want], progress=print)
    print(f"Added {a} GPT suggestion(s); dropped {d} that didn't match the text; {g} rewrite(s) turned into notes.")
