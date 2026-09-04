# Local Knowledge Retrieval Baseline

## Purpose

The retrieval slice implements two measurable lexical baselines from ADR-006: simple
term overlap and rarity-aware IDF overlap. Version 2 expands the corpus and evaluation
set before any BM25 implementation so a later strategy comparison cannot shape its own
benchmark. Both existing retrievers remain unchanged and run without an LLM,
embeddings, a vector database, reranking, MCP, query rewriting, or an external
retrieval library. Retrieval remains isolated from `TroubleshootingAgent`.

## Knowledge Base and Ingestion

The repository-local `knowledge_base/` contains seven concise Markdown documents:

* `station_s04.md` describes station S04, its role, fault state, and operational checks.
* `error_codes.md` describes E-STOP-17 and a second quality-related demo code.
* `maintenance.md` describes safe response and return-to-service guidance.
* `station_s02.md` describes press-fit assembly, POS-31, AX-Y2 diagnosis, and recovery.
* `vision_calibration.md` covers CAM-12, CAL-42, calibration, and verification.
* `production_quality.md` covers inspection evidence, lot correlation, and disposition.
* `troubleshooting_service.md` covers recurring faults and service evidence packages.

`load_markdown_chunks()` reads the sorted Markdown files, normalizes line endings and
trailing whitespace, and creates one chunk for each Markdown heading section. The
in-memory retriever indexes those chunks once; runtime searches do not reread the source
files. The expansion increases the corpus from 9 to 25 chunks.

For this baseline, `document_id` is the filename stem and `source` is the path relative
to the knowledge-base directory. A chunk ID has the deterministic form
`<document_id>::chunk-<three-digit-section-position>`, for example
`error_codes::chunk-002`. IDs are stable while the document name and preceding heading
order remain unchanged.

## Port, Capability, and Results

The inner `KnowledgeRetriever` port exposes
`search(query, limit) -> tuple[KnowledgeRetrievalResult, ...]`. The agent-facing
`DocumentationSearchCapability.search_documentation(query)` depends only on that port
and currently requests at most three results.

Each `KnowledgeRetrievalResult` preserves passage content, `document_id`, relative
`source`, stable `chunk_id`, optional `relevance_score`, and metadata. The capability
returns a structured result and does not construct prose. Filesystem access and lexical
ranking remain in Infrastructure.

## Lexical Strategies

Both unchanged strategies use the same tokenizer. It case-folds text and extracts
alphanumeric terms while preserving hyphenated identifiers. Consequently,
`E-STOP-17`, `e-stop-17`, and `E-STOP-17!!!` produce the same identifier token.

### Simple term overlap

For the distinct normalized query-term set `Q` and chunk-term set `C`, the score is:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks with score `0` are omitted. Remaining chunks are sorted by descending score and
then by ascending `chunk_id` for deterministic tie-breaking. There is no stemming,
stop-word removal, synonym expansion, phrase weighting, term-frequency weighting, or
semantic matching.

### Rarity-aware IDF overlap

For `N` indexed chunks and the number `df(t)` of chunks containing term `t`, the
smoothed inverse document frequency is:

```text
idf(t) = ln((N + 1) / (df(t) + 1)) + 1
```

For the distinct query-term set `Q` and chunk-term set `C`, the weighted score is:

```text
score(query, chunk) = sum(idf(t) for t in Q intersect C)
                      / sum(idf(t) for t in Q)
```

This implementation adds no stemming, synonyms, field boosting, query expansion, term
frequency, or semantic signal.

## Retrieval Evaluation Datasets

`evals/datasets/knowledge_retrieval_v1.jsonl` remains byte-for-byte unchanged with its
ten original cases. `knowledge_retrieval_v2.jsonl` contains 28 cases: the ten v1 cases
with unchanged `case_id`, query, and relevance ground truth, plus 18 new cases. Nine v2
cases have multiple relevant chunks.

Each v2 case carries one or more descriptive categories. Categories overlap because a
realistic query can simultaneously contain an exact identifier, be short, and require
multiple documents.

| Category | Cases |
| --- | ---: |
| Exact identifiers | 15 |
| Natural language | 17 |
| Rare terms | 7 |
| Common-term ambiguity | 14 |
| Multi-relevance | 9 |
| Short queries | 5 |
| Longer technical queries | 5 |
| Cross-document ambiguity | 20 |
| Term-frequency-sensitive | 4 |
| Length-sensitive | 6 |

Ground truth was assigned by reading the source chunks and determining which passages
answer each query. All answer-bearing chunks were included; cases with unclear
relevance were excluded. Retriever rankings were not used to create or revise labels.
The deterministic loader rejects empty fields, duplicate case IDs, duplicate queries,
duplicate relevant chunk IDs, duplicate categories, and schema violations. A separate
validation step rejects duplicate corpus chunk IDs and every ground-truth reference
that does not exist in the loaded knowledge base. It does not assert retrieval quality.

The runner reports Hit@1, Hit@3, per-case Recall@3, and Mean Recall@3. It lists Hit@1
misses, Hit@3 misses, incomplete-recall cases, and their union as `failed_case_ids`.
Every case retains expected chunk IDs and its actual ranking with scores. For v2, the
same metrics and failure lists are aggregated by category with direct runner logic.

Run the frozen v2 baseline with:

```powershell
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy simple
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy idf
```

The original v1 dataset remains selectable with `--dataset
evals/datasets/knowledge_retrieval_v1.jsonl`. Generated JSON can be written under the
Git-ignored `evals/results/` directory with `--output`.

## Freeze Rule

The seven-document corpus and v2 ground truth were frozen on 2026-09-04 before the
first v2 retrieval run. The dataset SHA-256 at freeze is
`E535816185D90DA816C5FD2033865094BD430E3752AE19632647E82309A46EA6`.
Neither v2 queries nor relevance labels may be changed in response to later BM25
results. Corpus wording and chunking used for that comparison are frozen as well. A
necessary correction must be explicit and versioned as a later dataset rather than
silently rewriting v2.

## v1 and v2 Baselines

The v1 values are the historical three-document baseline recorded before corpus
expansion. The v2 values use the frozen seven-document, 25-chunk corpus.

| Dataset | Metric | Simple overlap | Rarity-aware IDF |
| --- | --- | ---: | ---: |
| v1 (10 cases) | Hit@1 | 0.9000 | 1.0000 |
| v1 (10 cases) | Hit@3 | 1.0000 | 1.0000 |
| v1 (10 cases) | Mean Recall@3 | 0.9500 | 0.9500 |
| v2 (28 cases) | Hit@1 | 0.7857 | 0.8571 |
| v2 (28 cases) | Hit@3 | 0.8929 | 0.9286 |
| v2 (28 cases) | Mean Recall@3 | 0.8155 | 0.8452 |

An optional v1 regression run against the expanded 25-chunk corpus reproduced the same
v1 metrics and failure lists for both strategies.

The v2 failure lists are:

| Failure | Simple overlap | Rarity-aware IDF |
| --- | --- | --- |
| Hit@1 misses | `station_quality_role`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_invalid_after_work`, `calibration_procedure`, `qv1_role_short` | `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` |
| Hit@3 misses | `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `s02_recovery_verification`, `calibration_procedure` |
| Incomplete Recall@3 | `product_failure_context_multiple`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `calibration_procedure`, `service_evidence_multiple`, `vision_recovery_multiple` |

## v2 Results by Category

| Category (n) | Simple H@1 | Simple H@3 | Simple MR@3 | IDF H@1 | IDF H@3 | IDF MR@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exact identifiers (15) | 0.8667 | 0.8667 | 0.7889 | 0.8667 | 0.9333 | 0.8444 |
| Natural language (17) | 0.7059 | 0.8824 | 0.8235 | 0.8235 | 0.8824 | 0.8235 |
| Rare terms (7) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9286 |
| Common-term ambiguity (14) | 0.7143 | 0.7857 | 0.7857 | 0.7857 | 0.8571 | 0.8571 |
| Multi-relevance (9) | 0.8889 | 1.0000 | 0.7593 | 0.8889 | 1.0000 | 0.7407 |
| Short queries (5) | 0.8000 | 0.8000 | 0.8000 | 0.8000 | 1.0000 | 0.9000 |
| Longer technical queries (5) | 1.0000 | 1.0000 | 0.6667 | 1.0000 | 1.0000 | 0.7333 |
| Cross-document ambiguity (20) | 0.7500 | 0.9000 | 0.7917 | 0.8500 | 0.9500 | 0.8333 |
| Term-frequency-sensitive (4) | 0.5000 | 0.7500 | 0.6250 | 0.5000 | 0.7500 | 0.6250 |
| Length-sensitive (6) | 0.8333 | 1.0000 | 0.7222 | 0.8333 | 1.0000 | 0.7778 |

## Known Failure Patterns

Both strategies miss paraphrases and morphological variants because they have no
stemming or semantic signal. This is visible in `s02_recovery_verification` and
`calibration_procedure`. Common vocabulary and deterministic chunk-ID tie-breaking can
outrank the intended passage, especially for short queries such as `qv1_role_short`.
Multi-relevance cases often retrieve one correct chunk but lose a complementary passage
to a partially matching competitor; IDF improves aggregate v2 scores but slightly
reduces Mean Recall@3 for the multi-relevance category. Both strategies reduce chunks
to term sets, so repeated central terms provide no term-frequency signal. Neither score
normalizes for chunk length.

These measured gaps make BM25 a useful next comparison: it can add term-frequency
saturation and length normalization without changing the established lexical boundary.
That comparison must use the frozen v2 corpus and ground truth unchanged.

## Known Limits

The corpus remains intentionally small and manually inspectable rather than production
scale. Section-position IDs can shift after structural document edits, and there is no
index persistence or freshness management. Final-answer grounding and agent query
quality are not evaluated by this retrieval baseline.
