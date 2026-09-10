# Phase 18 — "Partial-but-meaningful" clarification: experiment and decision

**Outcome: DO NOT IMPLEMENT.** Production behaviour is unchanged. The
diagnostic and the candidate policies are committed as an isolated experiment so
the evidence is reproducible, and so a future attempt starts from measurements
rather than from the same intuition.

    python evaluation/query_understanding/phase18_partial_branch.py            # the table below
    python evaluation/query_understanding/phase18_partial_branch.py --compare  # current vs candidate decisions

## The question

Phase 17 asks a clarification only when a facet partitions the **whole**
candidate set well enough: the least helpful answer must still remove at least
`QUERY_UNDERSTANDING_MIN_REDUCTION` (0.5) of the candidates. Queries whose facets
have one dominant branch therefore go to direct search even when the *other*
branches narrow sharply — `work request` (3 of 5 in one branch) and `NPD` (7 of
8) are the documented cases.

So: should a clarification expose only the genuinely useful branches?

    candidate set
      |-- dominant branch  (drags the whole facet below the bar)
      |-- useful branch A
      +-- useful branch B      ->  offer only A and B?

## What the corpus says

Measured on the real 36-document index (`data/document_finder.sqlite3`).
`Verdict` is computed per branch, not assigned: `= Search all` selects every
candidate, `duplicate` selects the same documents as a branch already listed,
`weak` narrows by less than 50%, `useful` narrows by 50% or more. `Useful-only
coverage` is the share of candidates still reachable if the weak and dominant
branches were dropped — the number the whole proposal turns on.

Facets with no narrowing branch at all have no worst case; those cells read 0%
because the metric is undefined, and such a facet is never viable.

### `ECR` — 2 candidates, production: **direct**

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `document_type` | Process Document | 2 | 0% | = Search all | 50% | 50% | 50% |
|  | SOP / Work Instruction | 1 | 50% | useful |  |  |  |
| `distinguishing_term` | ECN | 2 | 0% | = Search all | 100% | 50% | 100% |
|  | ACN | 1 | 50% | useful |  |  |  |
|  | Change | 1 | 50% | useful |  |  |  |
|  | Management | 1 | 50% | duplicate |  |  |  |
|  | PR | 1 | 50% | duplicate |  |  |  |
|  | PRR | 1 | 50% | duplicate |  |  |  |

### `work request` — 5 candidates, production: **direct** (facet `category`, worst case 40%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `category` | Work Request | 3 | 40% | weak | 100% | 40% | 40% |
|  | NPD / Project | 1 | 80% | useful |  |  |  |
|  | Part / WTPart / CAD | 1 | 80% | useful |  |  |  |
| `document_type` | Process Document | 3 | 40% | weak | 100% | 40% | 40% |
|  | SOP / Work Instruction | 2 | 60% | useful |  |  |  |
|  | User Guide / Manual | 1 | 80% | useful |  |  |  |
| `distinguishing_term` | CRE | 2 | 60% | useful | 100% | 60% | 100% |
|  | CAD | 1 | 80% | useful |  |  |  |
|  | Combustion | 1 | 80% | useful |  |  |  |
|  | Creation | 1 | 80% | useful |  |  |  |
|  | Koel | 1 | 80% | useful |  |  |  |
|  | Manual | 1 | 80% | duplicate |  |  |  |
|  | _… 7 more filename tokens_ |  |  |  |  |  |  |

### `NPD` — 8 candidates, production: **direct** (facet `document_type`, worst case 12%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `document_type` | Process Document | 7 | 12% | weak | 100% | 12% | 12% |
|  | SOP / Work Instruction | 1 | 88% | useful |  |  |  |
|  | User Guide / Manual | 1 | 88% | duplicate |  |  |  |
| `distinguishing_term` | Gate | 7 | 12% | weak | 100% | 12% | 100% |
|  | MS | 7 | 12% | duplicate |  |  |  |
|  | PLM | 7 | 12% | duplicate |  |  |  |
|  | Creation | 1 | 88% | useful |  |  |  |
|  | MS0 | 1 | 88% | useful |  |  |  |
|  | MS1 | 1 | 88% | useful |  |  |  |
|  | _… 8 more filename tokens_ |  |  |  |  |  |  |

### `BOM` — 6 candidates, production: **clarify** (facet `document_type`, worst case 50%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `domain` | Manufacturing / PLM process documentation | 5 | 17% | weak | 100% | 17% | 17% |
|  | Internal IT (deployment, infrastructure, operations) | 1 | 83% | useful |  |  |  |
| `category` | BOM / EBOM | 4 | 33% | weak | 100% | 33% | 50% |
|  | Change Management | 1 | 83% | useful |  |  |  |
|  | IT Deployment | 1 | 83% | useful |  |  |  |
|  | Part / WTPart / CAD | 1 | 83% | useful |  |  |  |
| `document_type` | Process Document | 3 | 50% | useful | 100% | 50% | 100% |
|  | SOP / Work Instruction | 3 | 50% | useful |  |  |  |
| `distinguishing_term` | Creation | 3 | 50% | useful | 100% | 50% | 100% |
|  | Code | 2 | 67% | useful |  |  |  |
|  | Copy | 2 | 67% | useful |  |  |  |
|  | FG | 2 | 67% | duplicate |  |  |  |
|  | Using | 2 | 67% | useful |  |  |  |
|  | Bajaj | 1 | 83% | useful |  |  |  |
|  | _… 18 more filename tokens_ |  |  |  |  |  |  |

### `SOP` — 16 candidates, production: **clarify** (facet `category`, worst case 75%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `domain` | Manufacturing / PLM process documentation | 14 | 12% | weak | 100% | 12% | 12% |
|  | Internal IT (deployment, infrastructure, operations) | 2 | 88% | useful |  |  |  |
| `category` | Windchill Navigation & Admin | 4 | 75% | useful | 100% | 75% | 100% |
|  | BOM / EBOM | 3 | 81% | useful |  |  |  |
|  | Part / WTPart / CAD | 3 | 81% | useful |  |  |  |
|  | Change Management | 2 | 88% | useful |  |  |  |
|  | IT Infrastructure & Operations | 2 | 88% | useful |  |  |  |
|  | NPD / Project | 2 | 88% | useful |  |  |  |
| `document_type` | SOP / Work Instruction | 16 | 0% | = Search all | 31% | 81% | 31% |
|  | User Guide / Manual | 3 | 81% | useful |  |  |  |
|  | Process Document | 2 | 88% | useful |  |  |  |
| `distinguishing_term` | Creation | 5 | 69% | useful | 100% | 69% | 100% |
|  | BOM | 4 | 75% | useful |  |  |  |
|  | User | 4 | 75% | useful |  |  |  |
|  | Manual | 3 | 81% | useful |  |  |  |
|  | CAD | 2 | 88% | useful |  |  |  |
|  | Change | 2 | 88% | useful |  |  |  |
|  | _… 52 more filename tokens_ |  |  |  |  |  |  |

### `gate` — 7 candidates, production: **clarify** (facet `distinguishing_term`, worst case 86%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `document_type` | Process Document | 7 | 0% | = Search all | 0% | 0% | 0% |
| `distinguishing_term` | MS | 7 | 0% | = Search all | 100% | 86% | 100% |
|  | NPD | 7 | 0% | = Search all |  |  |  |
|  | PLM | 7 | 0% | = Search all |  |  |  |
|  | MS0 | 1 | 86% | useful |  |  |  |
|  | MS1 | 1 | 86% | useful |  |  |  |
|  | MS2 | 1 | 86% | useful |  |  |  |
|  | _… 4 more filename tokens_ |  |  |  |  |  |  |

### `chatbot` — 3 candidates, production: **clarify** (facet `distinguishing_term`, worst case 67%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `document_type` | Process Document | 3 | 0% | = Search all | 0% | 0% | 0% |
| `distinguishing_term` | Bajaj | 3 | 0% | = Search all | 100% | 67% | 100% |
|  | Deployment | 3 | 0% | = Search all |  |  |  |
|  | Version | 3 | 0% | = Search all |  |  |  |
|  | Version 01 | 1 | 67% | useful |  |  |  |
|  | Version 02 | 1 | 67% | useful |  |  |  |
|  | Version 03 | 1 | 67% | useful |  |  |  |

### `change management` — 4 candidates, production: **clarify** (facet `document_type`, worst case 50%)

| Facet | Option | n | Reduction | Verdict | Facet coverage | Facet worst case | Useful-only coverage |
|---|---|---:|---:|---|---:|---:|---:|
| `document_type` | Process Document | 4 | 0% | = Search all | 75% | 50% | 75% |
|  | SOP / Work Instruction | 2 | 50% | useful |  |  |  |
|  | User Guide / Manual | 1 | 75% | useful |  |  |  |
| `distinguishing_term` | Activity | 1 | 75% | useful | 75% | 75% | 75% |
|  | Company | 1 | 75% | useful |  |  |  |
|  | Deletion | 1 | 75% | duplicate |  |  |  |
|  | ECN | 1 | 75% | useful |  |  |  |
|  | ECR | 1 | 75% | duplicate |  |  |  |
|  | Guide | 1 | 75% | duplicate |  |  |  |
|  | _… 6 more filename tokens_ |  |  |  |  |  |  |

## What the table shows

**The dominant branch is the on-topic branch.** This is the finding that decides
the phase, and it is structural rather than a property of these 36 documents:
candidates are selected *because* they match the query, so the branch grouping
the documents the query is about is normally the largest one. Dropping "the
branch that narrows too little" therefore means dropping the documents the user
asked for:

| Query | Branch the proposal drops | What it contains |
|---|---|---|
| `work request` | `Work Request` (3 of 5) | the three documents named "Work Request" |
| `BOM` | `BOM / EBOM` (4 of 6) | the three BOM SOPs and the EBOM process |
| `NPD` | `Process Document` (7 of 8) | every MS0–MS6 gate document |
| `SOP` | `SOP / Work Instruction` (16 of 16) | all sixteen candidates |

In each case what remains is the complement: the documents that merely
*collided* with the query. `work request` would be answered with
"NPD / Project" and "Part / WTPart / CAD" — the two documents that are not work
requests — with the three that are hidden behind "Search everything".

**`ECR` is not a threshold problem.** Two documents name ECR. Domain and
category cover both, which is identical to searching everything; the
document-type facet has exactly one narrowing branch. There is no second choice
to offer at any threshold, and no policy tested asks about it. Forcing a
question would require the filename-token facet, whose branches are PR, PRR,
ACN, Change and Management — and those five labels collapse to just two distinct
selections, one per document. The question would be "document one or document
two", labelled by whichever fragment sorted first. Listing both is better.

**`NPD`'s useful branches are a duplicate pair.** `BEL_SOP_NPD Request Creation
User Manual` is both an SOP and a user manual, so "SOP / Work Instruction" and
"User Guide / Manual" are one choice shown twice, and together they reach 1 of 8
candidates. The only sharply-narrowing alternative is the filename-token facet,
which answers with `Creation, MS0, MS1, MS2, MS3` — a fragment mixed into an
incomplete family, with MS4–MS6 unreachable. That is the brief's own bad
example, produced from the corpus.

## Strategies compared

Five readings of the proposal, each run against the production decision for 65
queries (the 8 probes, the Phase 16/17 regression probes, and the frozen
60-query dataset). Every threshold is inherited from an existing constant, not
chosen for this experiment: the useful-branch bar is
`config.DEFAULT_MIN_CLARIFICATION_REDUCTION` (0.5), the coverage guard is
`analyzer.MIN_OPTION_COVERAGE` (0.5), the option cap is the analyzer's existing
filename-token cap (5), and the minimum branch size is 1 because `gate`'s
MS0–MS6 options each select a single document.

| Strategy | Differs on | Required-preserved probes broken | Verdict |
|---|---:|---|---|
| `naive` — drop weak branches, no coverage guard | 7 | `work request`, `NPD`, `BOM`, `SOP`, `deployment` | harmful |
| `guarded` — drop weak branches, coverage as a hard floor | 6 | `work request`, `NPD`, `BOM`, `deployment` | harmful |
| `phase17_ranked` — drop weak branches, coverage as Phase 17's rank bucket | 6 | `work request`, `NPD`, `BOM`, `deployment` | harmful |
| `semantic_only` — never answer with filename tokens | 4 | `BOM`, `gate`, `chatbot` | harmful |
| `keep_dominant` — keep every branch, relax the *question* rule | 2 | none | no gain over an existing knob |

Specifics:

- **`naive` reintroduces the exact defect Phase 17 fixed.** `SOP`'s
  document-type facet posts an 81% split while reaching 31% of candidates;
  without the coverage guard it wins again.
- **`guarded` still regresses `BOM`.** Its retained category branches cover
  exactly 50% — precisely at the guard, so the guard does not catch it — and the
  question becomes "Change Management / IT Deployment / Part / WTPart / CAD" for
  a user who typed BOM.
- **`phase17_ranked` closes the last variant.** Porting the existing ranking
  faithfully — coverage as a bucket, so a thin facet loses to a better one
  instead of being discarded — changes nothing: `BOM`'s two facets both clear
  the bucket, the better split wins, and the split is better precisely because
  the on-topic branch was dropped.
- **`semantic_only` deletes the two best questions in the corpus.** MS0–MS6 and
  Version 01–03 are filename tokens; banning that facet loses `gate` and
  `chatbot`.
- **`keep_dominant` is not partial branching.** It keeps every branch and instead
  asks whenever at least two branches are individually useful, no branch is a
  duplicate, and coverage is fair. It finds exactly one new question worth
  asking.

## The one improvement found, and why it is not shipped

`keep_dominant` turns `work request` into a complete, honest partition:

> **What are you looking for?**
> `Work Request` (3) · `NPD / Project` (1) · `Part / WTPart / CAD` (1)

Every label is a corpus-derived class, all five candidates stay reachable,
nothing is synthesised, and two of the three answers narrow by 80%. It is the
opposite of the proposal: the dominant branch stays on the list.

It also needs **no new code**. The analyzer already builds this exact question
and the decision layer already declines it for one reason — its worst case is
40%, below the 0.5 bar. Setting `QUERY_UNDERSTANDING_MIN_REDUCTION=0.4` produces
it today, and across all 65 queries changes nothing else:

| Threshold | Queries clarified (of 65) | Change from default |
|---:|---:|---|
| 0.5 (default) | 8 | — |
| 0.45 | 8 | none |
| **0.4** | **9** | **`work request` only** |
| 0.35 | 9 | none further |
| 0.3 | 10 | adds `windchill battlecard` (3 candidates) |
| 0.25 | 12 | adds `deployment` and a fully specific natural-language query |

Changing the default from 0.5 to 0.4 would be picking a threshold to make one
query clarify — the thing this phase's brief explicitly rules out, and the
reason 0.5 was chosen as "a question must at least halve the work" rather than
fitted. So the knob is documented, not moved. A customer who wants that question
can set the variable; the shipped default stays 0.5.

## Latent finding, recorded not fixed

`analyzer._finalize` keeps every branch selecting a strict, non-empty subset
without noticing that two branches may select the *same* subset. Three queries
(`NPD`, `deployment`, `java utility deployment for the chatbot`) build
clarifications containing duplicate options.

**No user can see this**: all three are declined by the reduction bar before
they are asked, so production never presents a duplicate option on this corpus.
Fixing it would be a production change with no observable effect, so it is
characterised by a test
(`test_analyzer_can_build_duplicate_options_but_never_asks_them`) that fails if
that stops being true, rather than repaired here.

## What was and was not verified

- **Full test suite: 165 passed** (119 before this phase, 46 added).
- **Phase 13 evaluation output is byte-identical** to the pre-Phase-18 baseline:
  domain 0.967, intent 0.900, ambiguity 0.833, needs_clarification 0.867,
  primary category 0.983, 36/60 fully correct. The frozen dataset and its
  self-authored labels were not touched, and remain a consistency check rather
  than validation.
- **Production source is byte-unchanged.** `analyzer.py`, `understanding.py`,
  `config.py`, `api/`, `search/`, `ingestion/`, `storage/`, `embeddings/`,
  `sources/`, `corpus.py` and `frontend/` carry no diff this phase. The only
  edit to an existing file is a test: the experiment-isolation check now covers
  the new prototype module too.
- **End-to-end was verified for the candidate behaviour**, so the decision rests
  on the UX evidence and not on unproven plumbing. On a temporary indexed corpus
  shaped like `work request`, with the 0.4 override: question → option →
  scoped search → `document_id` → original file opened byte-exactly, for all
  three options; "Search all documents" is identical to plain search; changing
  the query re-decides from scratch; two same-named documents in different
  folders stay two distinct results and each opens its own file; disabling the
  layer suppresses the question; and with the default restored, `work request`
  goes back to direct search.
- **Vector retrieval quality was NOT measured.** `torch`/`transformers` are not
  installed in this environment, so `evaluation/evaluate.py --mode vector` and
  `--mode hybrid` fail by design. No retrieval metric is claimed, and none is
  needed: no retrieval code was touched. The end-to-end check used a stub
  embedder, as the Phase 16 tests do.

## Recommendation

**DO NOT IMPLEMENT.** The current system is preferable because:

1. Every drop-the-dominant-branch policy hides the documents the query is about,
   because the dominant branch is the on-topic one. That is a structural
   consequence of how candidates are selected, not a corpus accident, so it will
   not improve with a larger corpus.
2. The guard that makes the strategy safe (coverage) is also the guard that
   removes its benefit — and it is still not tight enough to protect `BOM`.
3. The three motivating queries are not fixed by it: `ECR` has no second choice
   at any threshold, `NPD` gains only a fragment-plus-family question, and
   `work request`'s only good question comes from keeping the dominant branch,
   which the existing configuration already reaches.
4. Nothing here needed new production code, so nothing was added to production.

### What would change the answer

- A corpus where a facet's dominant branch is genuinely *off*-topic — a real
  ambiguity rather than the query's own subject. None of the 65 queries tested
  produces one; that is the evidence a future attempt should look for first.
- Real usage data on which option users actually pick. Every argument above
  about "the most likely answer" is inferred from corpus structure, not
  observed. Click-through on the eight questions production already asks would
  settle whether a 40%-worst-case question is worth a round trip — the single
  most valuable missing measurement.
- A larger repository where direct search returns enough results that even a
  weak narrowing pays for itself. The 3-candidate floor and the 0.5 bar were
  both set against a 36-document corpus and are explicitly marked as policy
  knobs to re-tune at scale.
