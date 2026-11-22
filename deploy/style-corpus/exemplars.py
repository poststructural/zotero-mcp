#!/usr/bin/env python3
"""Retrieve field exemplars for a draft paragraph and build the prompt block for reviewers.

  python exemplars.py "paragraph text…" [-k 3]      # show exemplars (with sources, for you only)

The prompt block carries MASKED exemplar text only (no author names, years or long quotations)
and no bibliographic metadata, so a reviewer model has nothing it could turn into a citation.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import db, mask, role_of, EMB_PATH, EMB_IDS, OUT_DIR, words
import arch

STOP = set("the of and to in a is that for on as with by this be are was it from at or an which not their its they his her have has but these those can more such been also than other into how what when who about there were would should could may might between through within".split())


class Retriever:
    def __init__(self):
        self.con = db(); self.M = self.ids = self.model = None
        if os.path.exists(EMB_PATH) and os.path.exists(EMB_IDS):
            import numpy as np
            self.np = np
            self.M = np.load(EMB_PATH).astype("float32"); self.ids = np.load(EMB_IDS)
            row = self.con.execute("SELECT v FROM meta WHERE k='emb_model'").fetchone()
            self.model_name = row["v"] if row else "BAAI/bge-small-en-v1.5"

    def _embed(self, text):
        if self.model is None:
            from fastembed import TextEmbedding
            self.model = TextEmbedding(self.model_name)
        v = next(iter(self.model.embed([text])))
        v = self.np.asarray(v, dtype="float32"); return v / (self.np.linalg.norm(v) + 1e-9)

    def _rows(self, ids):
        if not ids: return []
        q = f"""SELECT p.id, p.item_key, p.masked, p.text, p.role, p.words, p.page_label, i.relevance, i.title, i.creators, i.year
                FROM paras p JOIN items i ON i.key=p.item_key WHERE p.id IN ({','.join('?' * len(ids))})"""
        by = {r["id"]: r for r in self.con.execute(q, ids).fetchall()}
        return [by[i] for i in ids if i in by]

    def candidates(self, text, n=200):
        if self.M is not None:
            sims = self.M @ self._embed(mask(text))
            top = self.np.argsort(-sims)[:n]
            return [(int(self.ids[j]), float(sims[j])) for j in top]
        terms = [w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP]
        terms = sorted(set(terms), key=lambda w: -len(w))[:14]
        if not terms: return []
        q = " OR ".join(f'"{t}"' for t in terms)
        rows = self.con.execute("""SELECT p.id, bm25(paras_fts) s FROM paras_fts JOIN paras p ON p.id=paras_fts.rowid
                                   WHERE paras_fts MATCH ? AND p.source='pdf' AND p.words BETWEEN 60 AND 350
                                   ORDER BY s LIMIT ?""", (q, n)).fetchall()
        return [(r["id"], -r["s"]) for r in rows]

    def search(self, text, k=2, exclude=()):
        """Nearest field paragraphs, at most one per source, nudged toward core items and the same rhetorical role."""
        want = role_of(text); seen = set(exclude); out = []
        cands = self.candidates(text)
        sim = dict(cands)
        rows = self._rows([i for i, _ in cands])
        top = max(sim.values(), default=1) or 1
        ranked = []
        for r in rows:
            if r["relevance"] not in ("core", "adjacent"): continue
            s = sim[r["id"]] / top + (0.04 if r["relevance"] == "core" else 0) + (0.03 if r["role"] == want else 0)
            ranked.append((s, r))
        for _, r in sorted(ranked, key=lambda x: -x[0]):
            if r["item_key"] in seen: continue
            seen.add(r["item_key"]); out.append(r)
            if len(out) >= k: break
        return out


def load_never():
    p = os.path.join(OUT_DIR, "field_phrases.yaml")
    if not os.path.exists(p): return []
    out, on = [], False
    for line in open(p, encoding="utf-8"):
        if line.startswith("never_introduce"): on = True; continue
        if re.match(r"^\w", line): on = False
        if on and line.strip().startswith("- "): out.append(json.loads(line.strip()[2:]))
    return out


def field_profile():
    p = os.path.join(OUT_DIR, "profile.json")
    return json.load(open(p)) if os.path.exists(p) else None


def pick_targets(paras, max_targets):
    body = [(i, t) for i, t, h in paras if not h and len(words(t)) >= 60]
    def weight(it):
        a = arch.paragraph(it[1])
        return (2 if a.get("sandwich") else 0) + (1 if a.get("abstract_open") else 0) + (1 if a.get("modal_also_open") else 0) + min(a["words"], 300) / 600
    keep = {i for i, _ in sorted(body, key=lambda it: -weight(it))[:max_targets]}
    return [(i, t) for i, t in body if i in keep]


PREAMBLE = """######## FIELD EXEMPLARS (style anchors only, NOT sources) ########
Below are paragraphs from published scholarship in Austin's field (secondary English education, curriculum
studies, poststructural educational research), retrieved from his own library because they do a similar job to
the draft paragraph named. Author names, years and long quotations are masked.
How to use them:
- Use them ONLY to calibrate paragraph architecture and register: how published writers in this field open a
  paragraph (usually on the concrete study, text, date or claim, not an abstract frame), how they move from report
  to interpretation, how they hedge, how they hand off to the next paragraph, and how they end (often on the
  evidence or the next step, not on a restatement of the opener).
- Never take a claim, fact, finding, example, citation, or any wording of four or more consecutive words from them.
  They are not evidence for this strand and must never be cited or alluded to. Austin's sources are the only sources.
- When a suggestion is motivated by the exemplars, say what structural move you are borrowing in "why"
  (e.g. "field paragraphs open on the study and keep interpretation for the last third").
- Prefer Austin's own lexicon. A rewrite should sound like his best paragraphs, not like the exemplars.
"""


def corpus_block(paras, retriever=None, max_targets=10, k=2, targets=None):
    """Return (prompt_text, used) where used = [{paragraph, exemplar ids…}] for audit/overlap checks."""
    retriever = retriever or Retriever()
    parts = [PREAMBLE]
    prof = field_profile()
    if prof:
        mine = arch.summarize([t for _, t, h in paras if not h])
        f = prof.get("field_core_citing") or prof.get("field_core_all")
        keys = ["sandwich_pct", "abstract_open_pct", "abstract_close_pct", "modal_also_open_pct", "author_open_pct",
                "demonstrative_open_pct", "rather_than_per1k", "antithesis_per1k", "caveat_per1k", "ing_tail_per1k",
                "sent_len_mean", "para_len_mean"]
        parts.append("FIELD BASELINE vs THIS STRAND (same measures as slop_patterns; field = published paragraphs with 2+ citations):")
        parts += [f"- {arch.LABELS[x]}: field {f.get(x)} | this strand {mine.get(x)}" for x in keys if x in f]
        parts.append("Where this strand departs sharply from the field, prefer fixes that move it toward the field pattern.\n")
    never = load_never()
    if never:
        parts.append("PHRASES THAT ARE AI-TYPICAL AND RARE IN THIS FIELD (a rewrite must never introduce one; flag existing ones):")
        parts.append("; ".join(never) + "\n")
    used = []
    chosen = [(i, t) for i, t, h in paras if i in set(targets)] if targets is not None else pick_targets(paras, max_targets)
    for i, t in chosen:
        ex = retriever.search(t, k=k)
        if not ex: continue
        w = t.split()
        parts.append(f"--- For paragraph [{i}] (opens: “{' '.join(w[:10])}…”) ---")
        for n, r in enumerate(ex, 1):
            parts.append(f"Exemplar {n} ({r['role'].replace('_', ' ')}):\n{r['masked']}\n")
        used.append({"paragraph": i, "exemplars": [r["id"] for r in ex]})
    return "\n".join(parts), used


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("text"); ap.add_argument("-k", type=int, default=3)
    a = ap.parse_args()
    for r in Retriever().search(a.text, k=a.k):
        print(f"== {r['relevance']} | {r['role']} | {r['creators']} {r['year']} | {r['title'][:80]} | p. {r['page_label']}\n{r['masked']}\n")
