# Style corpus (private, server-only)

A style reference built from the PDFs in Austin's Zotero library, used to ground the Strands
dashboard's edit suggestions in how published writers in his field actually build paragraphs.

**What it is not:** a source of citations, claims or wording. Exemplars reach the review models
with author names, years and long quotations masked and without bibliographic metadata, and
every rewrite is checked against the corpus for copied wording before Austin sees it. The text
stays on the server (`~/style_corpus/corpus.db`); only a few masked exemplar paragraphs per
review go to the models the dashboard already uses (Claude, GPT via Codex).

## Pieces

| file | does |
|---|---|
| `harvest.py` | Zotero web API (GET only) -> items + field relevance (core / adjacent / other, from venue, title, abstract, tags, collections); downloads each PDF to a temp file, parses paragraphs with page labels (PyMuPDF), deletes the PDF. Falls back to Zotero's full-text index. |
| `build.py embed` | Local embeddings (fastembed, BAAI/bge-small-en-v1.5) for exemplar retrieval. |
| `build.py cliches` | Counts each entry of the AI-cliché list in the field corpus and the strands -> `out/field_phrases.yaml` (never_introduce / use_sparingly / field_normal) + `out/cliche_report.md`. |
| `build.py profile` | Paragraph-architecture baseline (same rules as `slop_audit.py`: sandwich, abstract openers/closers, modal openers, antithesis, caveats…) for the field vs. each strand -> `out/profile.md`. |
| `exemplars.py` | Nearest field paragraphs for a draft paragraph (one per source, core-weighted, same rhetorical role preferred) and `corpus_block()` for review prompts. |
| `guard.py` | Flags a rewrite that shares 8+ consecutive words with published text (generic runs found in 5+ sources ignored) or adds an AI-typical phrase that is rare in the field. |
| `pilot_compare.py` | Blind side-by-side on one strand: current prompt vs. prompt + corpus, per engine (codex, claude). Writes an HTML page with a vote form. |
| `quote_check.py` | **The** quotation checker (`verify_quotes.py` is an alias). Every direct quotation (4+ words) in the strands is matched against the cited item's PDF, downloaded once from Zotero (GET only, cached in `~/style_corpus/cache/pdf`, mode 600). Pages are **printed** page numbers: running headers/footers first, then PDF labels (JSTOR cover pages make labels off by one), then the Zotero page range (`~`), else `pdf N`. -> `out/reports/quote_check_all_strands.md` (+ copy in `<Strands>/Corpus reports`). |
| `sr_common.py` | Shared by `quote_check.py` and `audit_packets.py`: strand citations (narrative, parenthetical, title-before-year, institutional authors), Zotero item matching, printed-page mapping. |
| `audit_packets.py` | Source-audit extracts per strand: purpose / method / sample / findings / limits passages from each cited PDF with printed pages; reference lists and notes skipped. Locators to verify, never summaries. |
| `field_ngrams.py` | The field's 3–5-word academic phrases (core, capped per source, masked, in >= 20 sources; JSTOR/publisher boilerplate dropped) with each strand's rate -> `out/field_ngrams.md`; top 60 go into `register_guide.md`. |
| `lexicon.py`, `concordance.py`, `register.py` | Word-choice profile, term concordance by decade, and the combined register guide (`out/register_guide.md`). |

## Run

```bash
bash setup.sh                                   # once; then fill ~/style_corpus/zotero.env (read-only key)
PY=~/style_corpus/venv/bin/python
$PY harvest.py meta                             # metadata + relevance for the whole library
$PY harvest.py select --limit 300               # preview the pilot set
$PY harvest.py extract --limit 300 --relevance core
cp /path/to/ai_cliches_corpus.json ~/style_corpus/
$PY build.py all --strands ~/Strands
$PY pilot_compare.py --strand Censorship --n 8 --engines dry      # pipeline check, no model calls
$PY pilot_compare.py --strand Censorship --n 8 --engines codex,claude
$PY harvest.py extract --all && $PY build.py all  # full library, after the pilot
```
