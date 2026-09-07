# Phase 13 — Query-understanding experiment: measured results

**Status: EXPERIMENT. Not production-ready. Not integrated into search.**

Reproduce with:

```powershell
python evaluation/query_understanding/evaluate.py
python -m pytest tests/test_query_understanding.py -q
```

## Read this first

The labels in `queries.json` were authored by the same agent that later wrote
the classifier (the dataset the phase brief referred to did not exist in the
repository). The labels were committed **before** any implementation existed, so
they were not fitted to the code — but the figures below are still a
**consistency check, not independent validation.** See `LABELS.md`.

`topic` and `confidence` carry no labels, so **no accuracy is reported for them.**
Confidence appears only as a descriptive distribution.

## Approach: deterministic, corpus-derived. No LLM, no embedding model.

| Layer | Method |
|---|---|
| Intent | Ordered surface-marker matching (procedural → informational → reference → unknown) |
| Topic | Corpus-anchored query terms (unlabelled, not scored) |
| Candidates | Term matching against filename (weight 3.0) / section heading (1.5) / chunk text (0.5), read-only from the existing SQLite index |
| Domain & categories | Read off candidates scoring within 50% of the best match |
| Ambiguity | **A function of how many corpus candidates the query admits, not of query length** |
| Clarification | Facet chosen by discriminating power: domain → category → document type → distinguishing filename token |

An LLM was **not required** and none was used. No model was downloaded; the
experiment adds no runtime dependency beyond the standard library. Latency is
sub-millisecond per query after the corpus profile is built.

Two guards keep it honest rather than merely confident:

1. A candidate must match a **filename or heading**, not body text alone. Without
   this, "how do I file a travel expense claim?" collected a false candidate off
   an incidental body word in a long document.
2. Clarification options that select *every* candidate (or none) are dropped, and
   a question is only asked when at least two narrowing options survive **and**
   the candidate set exceeds 3 — asking the user to choose between two documents
   costs more than simply listing both.

## Results — 60 queries

| Metric | Result |
|---|---:|
| Fully correct on every labelled field | 36/60 = 0.600 |
| Domain accuracy | 58/60 = **0.967** |
| Intent accuracy | 54/60 = **0.900** |
| Ambiguity accuracy | 50/60 = **0.833** |
| Clarification-needed accuracy | 52/60 = **0.867** |
| Category — exact set match | 48/60 = 0.800 |
| Category — primary category in labelled set | 59/60 = **0.983** |
| Category — mean Jaccard overlap | 0.876 |

Confusion (expected → predicted), off-diagonal only:

- ambiguity: `low→medium` 4, `medium→low` 3, `low→high` 1, `high→low` 1, `medium→high` 1
- intent: `unknown→reference` 3, `reference→unknown` 2, `procedural→unknown` 1
- needs_clarification: `True→False` 6, `False→True` 2
- domain: `plm→cross_domain` 1, `it→cross_domain` 1

Confidence (unlabelled, descriptive): range 0.10–1.00, mean 0.617; mean **0.467
when asking for clarification** vs **0.655 when searching directly**. The
separation is in the right direction but the bands overlap, so confidence is not
yet a usable routing threshold on its own.

## Does clarification actually reduce the search space?

All 12 generated questions narrow the candidate set (every option is a strict,
non-empty subset). But **the magnitude is modest for skewed facets**, which is the
most important negative finding here:

| Query | Candidates | Worst case after one answer | Reduction |
|---|---:|---:|---:|
| `gate` | 7 | 1 | **85.7%** |
| `chatbot` | 3 | 1 | **66.7%** |
| `user guide` | 5 | 2 | 60.0% |
| `change management` | 4 | 2 | 50.0% |
| `work request` | 5 | 3 | 40.0% |
| `windchill battlecard` | 3 | 2 | 33.3% |
| `deployment` | 4 | 3 | 25.0% |
| `Windchill` | 4 | 3 | 25.0% |
| `java utility deployment for the chatbot` | 4 | 3 | 25.0% |
| `BOM` | 6 | 5 | 16.7% |
| `NPD` | 8 | 7 | 12.5% |
| `SOP` | 16 | 14 | 12.5% |
| **Total** | **69** | **46** | **33.3%** |

Clarification pays off when the filenames carry an *enumerable discriminator*
(`MS0…MS6`, `Version 01…03`). It pays off poorly when the facet is skewed — the
domain split on `SOP` moves 16 candidates to 14, because 14 of the 16 SOPs are
PLM documents. **A domain question is near-useless when one domain dominates the
matches.** A future version should pick the facet by expected reduction, not by a
fixed facet priority.

## Queries that trigger clarification (12 of 60)

`BOM`, `change management`, `work request`, `NPD`, `deployment`, `SOP`,
`user guide`, `Windchill`, `gate`, `chatbot`, `windchill battlecard`,
`java utility deployment for the chatbot`.

The last two are **false positives** — `windchill battlecard` names one document,
and the `java utility` query is procedural in substance.

## Queries that go straight to search (48 of 60)

All 16 procedural cases, the reference cases, the informational cases, every
`short_but_specific` case (`MS3`, `NVH`, `combustion`, `procurement`,
`solidworks`, `Iraje PAM`, `battlecard`), all out-of-corpus cases, and all
empty/invalid input. Notably **`MS3` (4 characters) is correctly not clarified**,
which was the point of that case class: shortness is not ambiguity.

## Examples of correct behaviour

- `how do I create an ECR?` → procedural, `plm`, `Change Management`, no clarification.
- `MS3` → `plm`, `NPD / Project`, ambiguity low, no clarification (one document).
- `procurement` → bare topic term, but exactly one procurement document exists → no clarification.
- `multi-level BOM extraction` → routed to **IT**, top candidate the Bajaj chatbot deployment document, despite containing "BOM".
- `how do I file a travel expense claim?` → no candidates, domain `none`, confidence 0.10, **no clarification menu** — an honest no-match.
- `gate` → 7 candidates → `MS0…MS4` + "Search everything", 7 → 1.
- `chatbot` → 3 candidates → `Version 01/02/03`, 3 → 1.

## Examples of incorrect behaviour

| Query | Expected | Predicted | Root cause |
|---|---|---|---|
| `part` | high / clarify | low / no clarify | **No stemming.** `part` does not match `Parts` or `WTPart`, so only one filename matched. |
| `ECR`, `ECN`, `CRE`, `folder navigation`, `WTPart` | clarify | no clarify | Only 2 candidates each, below the deliberate 3-candidate policy floor. A labelling-vs-policy disagreement, not a crash. |
| `java utility deployment for the chatbot` | procedural, no clarify | unknown, clarify | **Nominalised verbs.** "deployment"/"creation" carry procedural intent with no procedural syntax, so the marker rules miss them — and the intent miss then *propagates* into a spurious clarification. |
| `excel template BOM`, `multi-level BOM extraction` | reference | unknown | Noun-phrase queries naming a document carry no reference marker. |
| `SOP`, `user guide`, `battlecard` | unknown | reference | These *are* document-type words, so the reference-marker rule fires on the whole query. |
| `Windchill` | `plm` | `cross_domain` | Defensible: "Windchill" genuinely appears in IT deployment headings too. The label is arguably the wrong one here. |
| 12 category-set mismatches | one category | 2–4 categories | Unstemmed bag-of-words over-recalls on common words; the *primary* category was still right in 59/60. |

## Limitations caused by using only 36 documents

1. **The label set is self-authored.** The headline constraint; nothing here is validated.
2. **Ambiguity barely exists at this scale.** The largest candidate set is 16 and the median is far smaller, so the clarification-vs-search trade-off is being tuned against candidate sets a real repository would consider trivial. The 3-candidate floor and the 0.5/0.75 score ratios are almost certainly wrong for 855 documents.
3. **Categories were seeded, not discovered.** 10 categories over 36 documents is dense enough that seed terms work; at 855 documents the taxonomy should be derived (clustering, or Windchill attributes) rather than hand-seeded.
4. **PDF structure is missing.** All 22 PDFs produce a single "Document preamble" section, so the heading signal — the middle weight in the whole scheme — is effectively DOCX-only. This weakens candidate scoring for two-thirds of the corpus.
5. **The IT/PLM split is unusually clean.** Only 6 documents are IT. A real repository will have many overlapping domains, and `cross_domain` as a single bucket will not survive that.
6. **No paraphrase pressure.** The corpus vocabulary and the query vocabulary largely coincide, which flatters exact-token matching. Real users will paraphrase.

## What to revisit with the 855-document corpus

1. **Re-label with domain experts.** Replace `queries.json` before quoting any figure. This is a prerequisite, not a nice-to-have.
2. **Re-tune the policy knobs** (`MIN_CANDIDATES_FOR_CLARIFICATION`, `CONTENDER_SCORE_RATIO`, `STRONG_SCORE_RATIO`) against real result-set sizes.
3. **Select facets by expected reduction**, not by fixed priority — the `SOP` 16→14 case is the argument.
4. **Revisit whether an embedding model is now warranted.** The three intent failures are all paraphrase/nominalisation problems that token rules cannot reach. The existing Qwen3-Embedding-0.6B is already in the stack; classifying intent by similarity to labelled exemplars would be the cheapest next experiment — still not a generative LLM.
5. **Add stemming/lemmatisation**, or reuse FTS5's tokenizer, to fix `part`/`parts`/`WTPart`.
6. **Derive the taxonomy** from Windchill attributes or clustering instead of seed terms, and expect the demo categories here to be discarded.
7. **Only then** consider integrating with retrieval, behind an explicit flag and its own evaluation.
