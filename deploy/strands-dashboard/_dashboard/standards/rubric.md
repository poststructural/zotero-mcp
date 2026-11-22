# Writing rubric, v1.1 (calibrated against Austin's blind seed scores, 2026-11-02)

For literature review and theoretical prose in Austin's dissertation. Each dimension is scored 1 to 4. Sources: **D** = Dorothea's 206 coded comments (`dorothea_standards.md`), **C** = the published corpus in Austin's Zotero library, **S** = Austin's `academic-writing` and `critical-synthesis` skills, **X** = Austin's own slop excerpts. Anchor passages get filled in from the seed-tagging round; the slots are marked.

Weighting for current work follows the trend in Dorothea's comments: concreteness, organization and signposting matter most right now. Study anchoring is mostly fixed.

| # | Dimension | 4 looks like | 1 looks like | Source | Weight now |
|---|---|---|---|---|---|
| 1 | **Concreteness** | Claims tied to an example, a number, or participants' words; plain verbs; few -tion/-ment nouns | Abstract nouns doing the work; reader asks "What does this mean?" | D (42), C | High |
| 2 | **Architecture** | Order is visible (chronology or logic); each turn named by a transition; section opens by stating its question | Order must be inferred; "what you say is later is earlier" | D (37) | High |
| 3 | **Signposting findings** | Key findings stated, labeled, and repeated in the draft | Findings implied; "hard to identify and retain" | D (9), email Oct 28 | High |
| 4 | **Term discipline** | One term per concept, kept; analytic uses ("grammar of schooling") flagged | "field," "approach," "curriculum" drift; everyday and analytic senses mixed | D (33), C | Medium |
| 5 | **Study anchoring** | Research question, method, sample, findings before interpretation | Study named, then interpreted | D (29), S | Medium |
| 6 | **Evidence fit** | Claims scoped to what the cited studies show | "Do the studies show that?" | D (28) | Medium |
| 7 | **Attribution** | Author's claim vs. yours always marked; their terms quoted | Narrator adjudicates sources without saying so | D (12), X | Medium |
| 8 | **Focus** | Every paragraph serves the section's question | Intro material or side arguments inside a review section | D (16) | Medium |
| 9 | **Genre and scope** | Study vs. essay, university vs. secondary, inclusion criteria explicit | Mixed genres and levels without comment | D (13) | Medium |
| 10 | **Rhythm** | Sentence length varies (SD near 12 or more); some short sentences | Even, mid-length sentences throughout (SD under 8) | C | Medium |
| 11 | **Theoretical move** | Theory enters after empirical ground, through a named move (pivot, concept invention, return) | Theory asserted before the studies, or ornamental | S, D | Medium |
| 12 | **Slop absence** | None of the structural patterns in `slop_patterns.yaml` | Teacher glosses, callbacks, narrator verdicts, personified abstractions, "important because," overused "account," author-led paragraphs | X, Austin | High |

## Settled tension
Dorothea's push toward concrete, declarative description applies to reviewing studies. Poststructural moves belong after that ground is laid, which is the sequence principle in `critical-synthesis`. The rubric scores dimensions 1 to 9 on review passages and dimension 11 on theoretical passages.

## Anchors
Full passages in `anchors.md`: for each dimension, one published passage and one of your Dorothea-praised drafts that you scored 4, plus a low passage.

## Calibration (50 passages scored blind, Nov 2)
Six passages were front matter or abstracts (copyright pages, OCR headers, a book blurb) and are left out below. All six scored 1.

| Group | n | Mean score (1 to 4) |
|---|---|---|
| Your drafts Dorothea praised | 10 | 3.6 |
| Published passages from items you labeled Love | 17 | 3.1 |
| Published passages from Solid or Content-only items | 7 | 2.4 |
| Your drafts Dorothea flagged | 10 | 2.3 |

What this means for the rubric:
1. **Your taste and Dorothea's line up.** Scoring blind, you put her praised paragraphs 1.3 points above her flagged ones, and above the published work you love. The rubric can treat her comments as a fair proxy for your own standard.
2. **Surface counts do not predict your scores.** Sentence-length spread, nominalizations, first person, hedges, narrative citations and "account" all correlate with your score at |r| < 0.25. The praised and flagged drafts have nearly the same median spread (10.1 vs 12.1) and nominalizations (5.8 vs 5.6). So the computed checks stay as flags for a second look and never count as a score. The judgment dimensions (1 to 9, 11) need a reader, human or model, working from the anchors.
3. **What 4s have in common.** In passages you scored 4 and marked dimensions on, the most frequent + marks were concreteness (8), rhythm (8), theory (7), then anchoring, architecture, focus, genre and evidence (6 each). The most frequent − marks anywhere were signposting (5), architecture (4), concreteness, anchoring and terms (3 each). That keeps concreteness, architecture and signposting at High.
4. **Rhythm is something you hear, not a number.** You marked rhythm + on 13 passages, but sentence-length SD did not track those marks. The rhythm row stays, scored by ear against the anchors; the SD threshold in `slop_patterns.yaml` is now a soft flag.
