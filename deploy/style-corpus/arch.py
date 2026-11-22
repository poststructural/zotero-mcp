"""Paragraph-architecture measures, ported from strand_revision/slop_audit/slop_audit.py so the
field corpus and Austin's strands are measured with exactly the same rules."""
import re, statistics as st
from common import sentences, words

AUTHOR_OPEN = re.compile(r"^([A-Z][a-zA-Z’'\-]+(?: (?:and|&) [A-Z][a-zA-Z’'\-]+| et al\.)?(?:’s|'s)? ?\(\d{4}|(?:He|She|They|Their|His|Her) |In ([A-Z][a-z]+’s|a|an|her|his|their) [\w -]{0,40}(study|survey|analysis|case|interviews?))")
MASKED_AUTHOR_OPEN = re.compile(r"^\[Author\]")
DEMONSTRATIVE = re.compile(r"^(This|These|Such|That|Those) (\w+ )?(study|studies|survey|surveys|work|research|finding|findings|pattern|evidence|comparison|shift|literature|scholarship|approach|account|analysis|history|continuity|tension|distinction|period|debate|record|case)\b")
MODAL = re.compile(r"\b(can|could|may|might)( also)?\b")
ALSO_EARLY = re.compile(r"^\S+( \S+){0,4} also\b")
RATHER_THAN = re.compile(r"\brather than\b", re.I)
ANTITHESIS = re.compile(r"\bnot (simply|merely|only|just)?\s*\w+[^.;]{0,60}?,? but\b", re.I)
CAVEAT = re.compile(r"\b(does not|do not|did not|cannot)( by itself| alone| directly)? (establish|demonstrate|prove|show|settle|reveal|serve as|mean|determine)|\binsufficient evidence", re.I)
TRANSITIONS = ["however", "nevertheless", "nonetheless", "yet", "moreover", "furthermore", "additionally", "in addition",
               "consequently", "thus", "therefore", "indeed", "similarly", "likewise", "by contrast", "in contrast",
               "meanwhile", "still", "instead", "rather", "ultimately", "overall", "together"]
ING_TAIL = re.compile(r",\s+(demonstrating|suggesting|reflecting|indicating|revealing|highlighting|underscoring|illustrating|showing|signaling|positioning|making|leaving|reinforcing|complicating|raising)\b")
FIRST_PERSON = re.compile(r"\b(I|we|my|our|us|me)\b")


def concrete(s):
    """Same test as slop_audit: a name, number, date or quotation after the first character.
    Masked placeholders ([Author], (YEAR), (CITATION)) count as concrete."""
    return bool(re.search(r"\d|“|\"|\b[A-Z][a-z]+|\[Author\]|\(YEAR\)|\(CITATION\)", s[1:]))


def paragraph(t):
    ss = sentences(t); lens = [len(words(s)) for s in ss]
    r = {"words": sum(lens), "sents": len(ss), "lens": lens}
    if len(ss) >= 3:
        r["abstract_open"] = not concrete(ss[0]); r["abstract_close"] = not concrete(ss[-1])
        r["sandwich"] = r["abstract_open"] and r["abstract_close"]
        r["modal_also_open"] = bool(MODAL.search(ss[0]) or ALSO_EARLY.search(ss[0]))
    if ss:
        s0 = ss[0].lstrip("“\"(")
        r["author_open"] = bool(AUTHOR_OPEN.match(s0) or MASKED_AUTHOR_OPEN.match(s0))
        r["demonstrative_open"] = bool(DEMONSTRATIVE.match(s0))
        r["short_closer"] = len(ss) > 2 and len(words(ss[-1])) <= 14
    low = t.lower()
    r["rather_than"] = len(RATHER_THAN.findall(t)); r["antithesis"] = len(ANTITHESIS.findall(t))
    r["caveat"] = len(CAVEAT.findall(t)); r["ing_tail"] = len(ING_TAIL.findall(t))
    r["first_person"] = len(FIRST_PERSON.findall(t))
    r["transition_starts"] = sum(1 for s in ss for tr in TRANSITIONS if re.match(r"^" + re.escape(tr) + r"\b", s, re.I))
    r["sd"] = st.pstdev(lens) if len(lens) > 1 else None
    return r


def summarize(texts):
    """Aggregate measures over many paragraphs (same definitions as slop_audit's document numbers)."""
    P = [paragraph(t) for t in texts]
    P = [p for p in P if p["sents"]]
    if not P: return {}
    arc = [p for p in P if "sandwich" in p]
    W = sum(p["words"] for p in P) or 1
    lens = [l for p in P for l in p["lens"]]
    pct = lambda k, pool: round(100 * sum(1 for p in pool if p.get(k)) / max(len(pool), 1), 1)
    per1k = lambda k: round(1000 * sum(p[k] for p in P) / W, 2)
    sds = [p["sd"] for p in P if p["sd"] is not None and p["sents"] >= 4]
    return {
        "paragraphs": len(P), "words": W,
        "sandwich_pct": pct("sandwich", arc), "abstract_open_pct": pct("abstract_open", arc),
        "abstract_close_pct": pct("abstract_close", arc), "modal_also_open_pct": pct("modal_also_open", arc),
        "author_open_pct": pct("author_open", P), "demonstrative_open_pct": pct("demonstrative_open", P),
        "short_closer_pct": pct("short_closer", P),
        "rather_than_per1k": per1k("rather_than"), "antithesis_per1k": per1k("antithesis"),
        "caveat_per1k": per1k("caveat"), "ing_tail_per1k": per1k("ing_tail"), "first_person_per1k": per1k("first_person"),
        "transition_starts_per1k": per1k("transition_starts"),
        "sent_len_mean": round(st.mean(lens), 1), "sent_len_sd": round(st.pstdev(lens), 1),
        "median_para_sd": round(st.median(sds), 1) if sds else None,
        "para_len_mean": round(st.mean([p["words"] for p in P])),
        "para_len_cv": round(st.pstdev([p["words"] for p in P]) / max(st.mean([p["words"] for p in P]), 1), 2),
    }


LABELS = {
    "sandwich_pct": "Paragraphs with abstract opener AND abstract closer (%)",
    "abstract_open_pct": "Abstract first sentence (%)", "abstract_close_pct": "Abstract last sentence (%)",
    "modal_also_open_pct": "Opener with can/could/may/also (%)", "author_open_pct": "Opens on an author/study (%)",
    "demonstrative_open_pct": "Opens 'This/These + noun' (%)", "short_closer_pct": "Short (<=14 word) closing sentence (%)",
    "rather_than_per1k": "'rather than' per 1k words", "antithesis_per1k": "'not X but Y' per 1k words",
    "caveat_per1k": "'does not establish'-type caveats per 1k", "ing_tail_per1k": "', suggesting/reflecting…' tails per 1k",
    "first_person_per1k": "First person per 1k", "transition_starts_per1k": "Sentences opened by a stock transition per 1k",
    "sent_len_mean": "Mean sentence length (words)", "sent_len_sd": "Sentence-length SD", "median_para_sd": "Median within-paragraph SD",
    "para_len_mean": "Mean paragraph length (words)", "para_len_cv": "Paragraph-length spread (CV)",
}
