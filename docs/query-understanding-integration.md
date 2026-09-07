# Query understanding in front of search (Phase 16)

The Phase 13 experiment is now an **optional decision layer** ahead of the
existing search. It answers one question — *is asking the user one question
worth the round trip?* — and nothing else.

```
query -> analyze -> worth asking? --no--> search (unchanged)
                          |
                         yes
                          |
                    one question -> user answers -> search, scoped to that answer
                                         |
                                    "Search all documents" -> search (unchanged)
```

It is **not** a chatbot and generates no answers. Retrieval is untouched: the
same Qwen embeddings, the same FAISS index, the same similarity and the same
ordering. Lexical search, hybrid search, ingestion, OCR and chunking are never
called from this layer.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `QUERY_UNDERSTANDING_ENABLED` | `true` | Set to `false` to restore exact pre-Phase-16 behaviour |
| `QUERY_UNDERSTANDING_MIN_REDUCTION` | `0.5` | Smallest worst-case candidate reduction that justifies asking |

Default-on is deliberate: this is the customer-facing flow, the layer only
speaks up for genuinely ambiguous queries, and every failure path falls back to
plain search. One variable turns it off.

## When a question is asked

The analyzer (unchanged) proposes a clarification only when a facet partitions
its candidate documents into strict, non-empty subsets. The integration layer
then applies one further test, reusing the analyzer's own reported numbers:

```
reduction = 1 - largest_option_candidates / candidates_before
ask only if reduction >= QUERY_UNDERSTANDING_MIN_REDUCTION
```

**Worst case, not average.** This is the point of the threshold. `gate` removes
6 of 7 candidates whichever gate you pick, and is asked; a facet whose least
helpful answer barely narrows anything is not.

The threshold alone is not enough, because *which* facet is measured matters.
The analyzer therefore ranks the semantic facets it can build — by coverage
first, then by worst-case split, with the ladder order breaking ties — instead
of taking the first one that merely works. Two things follow:

- `bom` matches six documents that domain splits 5/1 (17%, not worth asking) but
  document type splits 3/3 (50%). Ranking finds the second, so `bom` now asks.
- `sop` matches sixteen documents whose document-type facet posts an 81%
  reduction only because its dominant bucket covered all sixteen and was
  dropped, leaving options that reach just 5 of them. Coverage ranking rejects
  that in favour of the category facet: full coverage, 75% reduction, six
  meaningful topic options.

The 0.5 default means *a question must at least halve the work*. It was chosen
as a round, explainable rule, **not** fitted to the frozen 60-query labels —
those labels score the analyzer's own `needs_clarification`, which this layer
does not change. The Phase 13 evaluation output is byte-identical before and
after this integration.

## How the options are produced

Entirely by the analyzer, from the corpus — nothing is hard-coded. It tries
facets in order of discriminating power: domain, then category, then document
type, then a distinguishing filename token. Whichever first yields at least two
narrowing options wins, so the question the user sees differs by query:

| Query | Question | Options |
|---|---|---|
| `gate` | Which one do you need? | MS0, MS1, MS2, MS3, MS4 |
| `chatbot` | Which one do you need? | Version 01, Version 02, Version 03 |
| `change management` | What kind of document do you need? | SOP / Work Instruction, User Guide / Manual |
| `user guide` | What are you looking for? | Change Management, NPD / Project, Windchill Navigation & Admin |

The UI always adds **Search all documents** and **Change query** itself, so the
escape route exists regardless of what the analyzer returns.

## API

`POST /query-understanding` — the decision. Carries no intent, confidence,
ambiguity or candidate counts; those are internal.

```json
{"query": "gate", "needs_clarification": true,
 "question": "Which one do you need?",
 "options": [{"label": "MS0", "value": "MS0"}]}
```

```json
{"query": "how do I create an ECR?", "needs_clarification": false,
 "question": null, "options": []}
```

`POST /search` — unchanged, plus one optional field:

```json
{"query": "gate", "limit": 5, "clarification": "MS3"}
```

Omit `clarification` (or send `null`) and the request behaves exactly as it did
before this phase. The analyzer is deterministic, so the client sends back only
the label it was shown and the server re-derives which documents that answer
selects.

## Soft vs hard narrowing

When an answer is supplied, results are **scoped to the documents that answer
selects**. This is a restriction over document identity, not a change to
retrieval, and it is deliberate rather than blind:

- the options are *defined* as subsets of the analyzer's candidate documents, so
  restricting to one is precisely the choice the user made — picking "MS3" and
  still seeing MS0–MS6 would make the question pointless
- retrieval, embeddings, scoring and ordering are untouched; only the presented
  set is filtered, and ordering within it is unchanged
- retrieval goes deeper first (4× the requested limit, capped at 40) so the
  scoped set is filled from the same ranking rather than from whatever fitted in
  the top few rows
- if scoping would empty the results, the unscoped results are shown instead
- an unknown or stale answer narrows nothing rather than failing
- **Search all documents** always bypasses it

## Failure behaviour

The layer can never break the product:

| Failure | Result |
|---|---|
| Layer disabled | plain search |
| No index / unreadable database | plain search |
| Exception anywhere in the analyzer | plain search |
| `/query-understanding` unreachable from the browser | frontend searches anyway |
| Unknown clarification value | plain search |
| Scoping empties the results | unscoped results shown |

## Observed behaviour on the 36-document corpus

Decisions below are from the real production index. **Recorded, not tuned** —
the threshold was not adjusted to change any of these outcomes.

| Query | Decision | Candidates | Worst case | Reduction |
|---|---|---:|---:|---:|
| `gate` | **clarify** | 7 | 1 | 86% |
| `chatbot` | **clarify** | 3 | 1 | 67% |
| `user guide` | **clarify** | 5 | 2 | 60% |
| `change management` | **clarify** | 4 | 2 | 50% |
| `sop` | **clarify** | 16 | 4 | 75% |
| `bom` | **clarify** | 6 | 3 | 50% |
| `windchill` | **clarify** | 4 | 2 | 50% |
| `work request` | direct | 5 | 3 | 40% |
| `deployment` | direct | 4 | 3 | 25% |
| `NPD` | direct | 8 | 7 | 12% |
| `ECR` | direct | — | — | analyzer offered no facet (only 2 documents name ECR) |
| `how do I create an ECR?` | direct | — | — | procedural intent |
| `add BOM structure` | direct | — | — | resolves to one document |
| `procurement` | direct | — | — | one procurement document exists |
| `how do I create a procurement kit?` | direct | — | — | procedural intent |
| `engine 37 hp 2900 rpm` | direct | — | — | no corpus match |
| `travel expense claim` | direct | — | — | no corpus match; normal no-results handles it |

Narrowing was verified end-to-end on a copy of the real corpus: `gate` went from
20 results to exactly 1 per gate option, `chatbot` to 1 per version,
`change management` to 2 (SOP) and 1 (user guide), `user guide` to 1/2/2 per
category — and every narrowed document opened byte-exactly from the configured
corpus root.

## Limitations

1. **`ECR` does not clarify**, though it is the phase's motivating example. Only
   two documents name ECR in a filename or heading, which is below the
   analyzer's 3-candidate floor, so no facet is offered at all. Not a threshold
   problem, and not tuned around.
2. **`work request` and `NPD` do not clarify.** Every facet available to them has
   one dominant branch (3 of 5, 7 of 8), so the worst case falls below the bar
   even though the *other* branches narrow sharply. A per-option decision — offer
   only the branches that genuinely narrow — would handle these, and is the
   natural next step.
3. **At most five options** are offered for a filename-token facet, so `gate`
   shows MS0–MS4 and omits MS5/MS6; those remain reachable only via
   "Search all documents".
4. **Retrieval quality was not re-measured.** `torch`/`transformers` are
   unavailable in this environment, so the retrieval evaluations could not run
   and the end-to-end narrowing validation used a stub embedder. What is
   demonstrated is the plumbing, not any ranking improvement — and no ranking
   improvement is claimed.
5. **The analyzer is still the Phase 13 experiment**, with self-authored labels
   and a demo taxonomy derived from these 36 documents. Its accuracy figures
   remain a consistency check, not validation.
6. Each answer is one step; there is no chaining of two clarifications, by design.
