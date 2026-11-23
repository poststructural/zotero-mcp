"""Shared helpers for the private style corpus (paths, database, Zotero web API, text utilities).

Everything stays on this server. The corpus is a style reference only: it is never a
source of citations, claims or wording for the dissertation.
"""
import hashlib, json, os, re, sqlite3, time, urllib.error, urllib.parse, urllib.request

HOME = os.environ.get("STYLE_CORPUS_HOME", os.path.expanduser("~/style_corpus"))
DB_PATH = os.path.join(HOME, "corpus.db")
ENV_PATH = os.path.join(HOME, "zotero.env")
EMB_PATH = os.path.join(HOME, "embeddings.npy")
EMB_IDS = os.path.join(HOME, "embedding_ids.npy")
OUT_DIR = os.path.join(HOME, "out")
HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS items(
  key TEXT PRIMARY KEY, item_type TEXT, title TEXT, creators TEXT, year TEXT, venue TEXT,
  doi TEXT, tags TEXT, collections TEXT, relevance TEXT, score REAL, reasons TEXT,
  pdf_key TEXT, pdf_link_mode TEXT, status TEXT DEFAULT 'pending', source TEXT,
  n_paras INTEGER, n_words INTEGER, note TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS paras(
  id INTEGER PRIMARY KEY, item_key TEXT, seq INTEGER, page_label TEXT, section TEXT,
  text TEXT, masked TEXT, words INTEGER, role TEXT, cites INTEGER, source TEXT);
CREATE INDEX IF NOT EXISTS paras_item ON paras(item_key);
CREATE VIRTUAL TABLE IF NOT EXISTS paras_fts USING fts5(masked, content='paras', content_rowid='id');
CREATE TABLE IF NOT EXISTS shingles(h INTEGER, pid INTEGER, PRIMARY KEY(h, pid)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def db():
    os.makedirs(HOME, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def load_env():
    """Read ZOTERO_API_KEY / ZOTERO_LIBRARY_ID / ZOTERO_LIBRARY_TYPE from ~/style_corpus/zotero.env or the environment."""
    env = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID", "ZOTERO_LIBRARY_TYPE"):
        if os.environ.get(k): env[k] = os.environ[k]
    if not env.get("ZOTERO_API_KEY") or not env.get("ZOTERO_LIBRARY_ID"):
        raise SystemExit(f"Put ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in {ENV_PATH} (chmod 600). A read-only key is enough.")
    env.setdefault("ZOTERO_LIBRARY_TYPE", "user")
    return env


class Zotero:
    """Minimal read-only Zotero web API client (GET only, by design)."""

    def __init__(self, env):
        kind = "groups" if env["ZOTERO_LIBRARY_TYPE"].startswith("group") else "users"
        self.base = f"https://api.zotero.org/{kind}/{env['ZOTERO_LIBRARY_ID']}"
        self.headers = {"Zotero-API-Key": env["ZOTERO_API_KEY"], "Zotero-API-Version": "3",
                        "User-Agent": "style-corpus/0.1"}

    def _get(self, path, params=None, raw=False, tries=5):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(tries):
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    body = r.read()
                    backoff = r.headers.get("Backoff")
                    if backoff: time.sleep(int(backoff))
                    return (body, r.headers) if raw else (json.loads(body), r.headers)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    time.sleep(int(e.headers.get("Retry-After") or 2 ** (attempt + 1))); continue
                raise
            except urllib.error.URLError:
                if attempt < tries - 1: time.sleep(2 ** (attempt + 1)); continue
                raise

    def all(self, path, params=None):
        params = dict(params or {}); params.setdefault("limit", 100); start = 0; out = []
        while True:
            params["start"] = start
            data, h = self._get(path, params)
            out += data
            total = int(h.get("Total-Results") or 0)
            start += len(data)
            if not data or start >= total: return out

    def file(self, key):
        body, h = self._get(f"/items/{key}/file", raw=True)
        return body

    def fulltext(self, key):
        try:
            data, _ = self._get(f"/items/{key}/fulltext")
            return data.get("content") or ""
        except urllib.error.HTTPError as e:
            if e.code == 404: return ""
            raise


# ---------------------------------------------------------------- text utilities
SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]*\s+(?=[A-Z“\"(\[])")
ABBR = re.compile(r"\b(e\.g|i\.e|et al|U\.S|cf|vs|pp?|Vol|No|Dr|Mr|Ms|St|ch|ed|eds)\.$")
YEAR = r"(?:1[6-9]|20)\d{2}[a-z]?"


def sentences(p):
    out = []
    for s in SENT_SPLIT.split(p.strip()):
        if out and ABBR.search(out[-1]): out[-1] += " " + s
        else: out.append(s)
    return [s for s in out if len(s.split()) > 1]


def words(s):
    return re.findall(r"[A-Za-z’'-]+", s)


NARRATIVE_CITE = re.compile(r"\b([A-Z][A-Za-z’'\-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z’'\-]+|\s+et\s+al\.)?)(’s|'s)?\s+\(\s*"
                            + YEAR + r"(?:\s*[,:]\s*(?:pp?\.\s*)?[\divxlc–\-]+)?\s*\)")
PAREN_CITE = re.compile(r"\([^()]{0,160}?\b" + YEAR + r"\b[^()]{0,120}?\)")
LONG_QUOTE = re.compile(r"[“\"]([^”\"]{70,})[”\"]")
CITE_COUNT = re.compile(r"\b" + YEAR + r"\b")


KEEP_CAPS = set("""English American Americans Black White Latinx Latino Latina Latine Indigenous Asian African Native
Hispanic European Christian Catholic Protestant Jewish Muslim U.S. US UK I Language Arts Common Core State Standards
God Bible Western Eastern Southern Northern Supreme Court Courts Congress Constitution Amendment First Fourteenth
United States Board Boards Education Department School Schools District Districts County Counties City State States
Federal National Association Council University College Library Libraries Act Bill Senate House Legislature
Republican Republicans Democrat Democrats Democratic Party Christianity Islam Bible Black English""".split())
PROPER = set()   # filled by build.py remask from corpus statistics (capitalized-only words = names/places)
LEAD_OK = set("""The This These That Those In A An As At For From On Of To With By Yet But And Or If When While Although
Though Because Since After Before During Such Some Many Most Several Each Every Both One Two Three Their His Her Its Our
We They He She It There Here What Which Who How Why Where Moreover However Instead Still Thus Indeed Similarly""".split())
CAP_TOK = r"(?:[A-Z][a-zA-Z\u2019'\-]*|[A-Z]\.)"
CAP_RUN = re.compile(CAP_TOK + r"(?:\s+(?:(?:of|the|and|for|in|on|to|a|de|van|von|la|le|du|del)\s+)?" + CAP_TOK + r")+")
STUDY_VERB = (r"(?:found|finds|argue[sd]?|argues|note[sd]?|notes|report(?:s|ed)?|show(?:s|ed)?|examine[sd]?|observe[sd]?|"
              r"suggest(?:s|ed)?|contend(?:s|ed)?|describe[sd]?|explore[sd]?|document(?:s|ed)?|trace[sd]?|conclude[sd]?|"
              r"claim(?:s|ed)?|call(?:s|ed)?|write[s]?|wrote|survey(?:s|ed)?|interview(?:s|ed)?|analy[sz]e[sd]?|identif(?:y|ies|ied)|"
              r"demonstrate[sd]?|emphasi[sz]e[sd]?|insist(?:s|ed)?|maintain(?:s|ed)?|propose[sd]?|offer(?:s|ed)?|"
              r"et al\.|and colleagues|and (?:her|his|their) colleagues)")
NAME_VERB = re.compile(r"\b([A-Z][a-zA-Z\u2019'\-]+)(?=\s+" + STUDY_VERB + r"\b)")
POSSESSIVE = re.compile(r"\b([A-Z][a-zA-Z\-]+)(\u2019s|'s)\b")
MID_CAP = re.compile(r"(?:(?<=[a-z,;:] )|(?<=[\u2014\u2013(]))([A-Z][a-z][a-zA-Z\u2019'\-]*)\b")
YEAR_WORD = re.compile(r"\b(?:1[5-9]|20)\d{2}(s?)\b")


def _run(m):
    words = m.group(0).split()
    lead = []
    while words and words[0] in LEAD_OK: lead.append(words.pop(0))
    caps = [w for w in words if w[:1].isupper()]
    if not caps or all(w.strip(".,") in KEEP_CAPS for w in caps): return m.group(0)
    if len(caps) == 1 and not lead and m.start() == 0 and caps[0] not in PROPER: return m.group(0)
    out = [w if (w.strip(".,") in KEEP_CAPS or not w[:1].isupper()) else "[Name]" for w in words]
    return " ".join(lead + out)


PAGE_LOC = re.compile(r"\((?:p|pp|para)\.\s*[\divxlc\u2013\-]+\)")


def mask(text):
    """Hide who/when/what-was-quoted so exemplars teach shape, not content or citations:
    citations, long quotations, personal names and multi-word proper names/titles, and years."""
    t = NARRATIVE_CITE.sub(lambda m: (m.group(1) if m.group(1) in KEEP_CAPS else "[Author]") + (m.group(2) or "") + " (YEAR)", text)
    t = PAREN_CITE.sub("(CITATION)", t)
    t = LONG_QUOTE.sub("\u201c[quoted passage]\u201d", t)
    t = CAP_RUN.sub(_run, t)
    t = POSSESSIVE.sub(lambda m: m.group(0) if m.group(1) in KEEP_CAPS | LEAD_OK else "[Name]" + m.group(2), t)
    t = NAME_VERB.sub(lambda m: m.group(0) if m.group(1) in KEEP_CAPS | LEAD_OK else "[Name]", t)
    t = MID_CAP.sub(lambda m: m.group(1) if m.group(1) in KEEP_CAPS else "[Name]", t)
    if PROPER:
        t = re.sub(r"\b[A-Z][a-zA-Z\u2019'\-]+\b", lambda m: "[Name]" if m.group(0) in PROPER else m.group(0), t)
    t = PAGE_LOC.sub("(PAGE)", t)
    t = YEAR_WORD.sub(lambda m: "[decade]" if m.group(1) else "[year]", t)
    t = re.sub(r"\[Name\]\.?\s+\[Author\]", "[Author]", t)
    t = re.sub(r"\[Name\](?:\s+(?:of\s+|and\s+|the\s+)?\[Name\])+", "[Name]", t)
    return t


def toks(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


SHINGLE_N = 8


def shingle_hashes(text, n=SHINGLE_N):
    t = toks(text)
    out = []
    for i in range(len(t) - n + 1):
        h = hashlib.blake2b(" ".join(t[i:i + n]).encode(), digest_size=8).digest()
        out.append(int.from_bytes(h, "big", signed=True))
    return out


ROLE_RX = {
    "study_report": r"\b(participants?|interview(?:ed|s)?|survey(?:ed|s)?|sample|respondents|data (?:were|was)|we found|findings|case stud(?:y|ies)|n\s*=|observ(?:ed|ations)|questionnaire|coded)\b",
    "synthesis": r"\b(studies|scholars|research(?:ers)? (?:has|have)|this (?:body|literature|scholarship)|across (?:these|the)|taken together|the literature|a number of|several)\b",
    "qualification": r"\b(however|although|though|yet|but|limit(?:ed|ation)s?|caution|did not|does not|less clear|complicat)\w*",
    "theory": r"\b(discours\w*|subject(?:ivity|ivities)?|power|deleuz\w*|foucault\w*|derrida\w*|assemblage|becoming|ontolog\w*|epistem\w*|ideolog\w*|hegemon\w*|poststructural\w*)\b",
    "historical": r"\b(1[89]\d0s|in (?:1[89]|20)\d\d|during the|decades?|century|era|movement)\b",
}


def role_of(text):
    low = text.lower()
    scores = {k: len(re.findall(rx, low)) for k, rx in ROLE_RX.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def docx_paragraphs(path):
    """Plain paragraphs from a .docx (body before 'Revision notes'/'Appendix:'), stdlib only."""
    import html, zipfile
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))).strip()
        if not t: continue
        if re.match(r"^(Revision notes|Revision Notes|\[Transition|Appendix:)", t): break
        style = re.search(r'<w:pStyle w:val="([^"]+)"', p)
        head = bool(style and style.group(1).lower().startswith("heading")) or (len(t.split()) < 14 and not t.endswith("."))
        out.append({"text": t, "heading": head})
    return out


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")
