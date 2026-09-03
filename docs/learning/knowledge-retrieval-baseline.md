# Local Knowledge Retrieval Baseline

## Purpose

The first retrieval slice implements the smallest measurable baseline from ADR-006; a
second adapter now provides a controlled rarity-aware lexical comparison. Both search a
small versioned technical knowledge base without an LLM, embeddings, a vector database,
reranking, MCP, or an external retrieval library. Retrieval remains isolated from
`TroubleshootingAgent` so its quality can be measured independently from query
formulation and agent decisions.

## Knowledge Base and Ingestion

The repository-local `knowledge_base/` contains three concise Markdown documents:

* `station_s04.md` describes station S04, its role, fault state, and operational checks.
* `error_codes.md` describes E-STOP-17 and a second quality-related demo code.
* `maintenance.md` describes safe response and return-to-service guidance.

`load_markdown_chunks()` performs one explicit build step. It reads the sorted Markdown
files, normalizes line endings and trailing whitespace, and creates one chunk for each
Markdown heading section. The in-memory retriever then indexes those chunks. Runtime
searches use the prepared index and do not reread or reparse the source files.

For this baseline, `document_id` is the filename stem and `source` is the path relative
to the knowledge-base directory. A chunk ID has the deterministic form
`<document_id>::chunk-<three-digit-section-position>`, for example
`error_codes::chunk-002`. IDs are stable while the document name and preceding heading
order remain unchanged. Content edits or inserted sections may intentionally change
identity or later positions; content-addressed or manifest-managed IDs are not yet
implemented.

## Port, Capability, and Results

The inner `KnowledgeRetriever` port exposes
`search(query, limit) -> tuple[KnowledgeRetrievalResult, ...]`. The agent-facing
`DocumentationSearchCapability.search_documentation(query)` depends only on that port
and currently requests at most three results.

Each `KnowledgeRetrievalResult` preserves:

* passage `content`;
* `document_id`;
* relative `source`;
* stable `chunk_id`;
* optional `relevance_score`; and
* metadata, currently the Markdown section title and format.

The capability returns a structured `DocumentationSearchResult`; it does not construct
prose. Filesystem access and lexical ranking remain in Infrastructure.

## Lexical Strategies

Both strategies use the same tokenizer. It case-folds text and extracts alphanumeric terms while preserving
hyphenated identifiers. Consequently, `E-STOP-17`, `e-stop-17`, and
`E-STOP-17!!!` produce the same identifier token.

### Simple term overlap

For the distinct normalized query-term set `Q` and chunk-term set `C`, the score is:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks with score `0` are omitted. Remaining chunks are sorted by descending score and
then by ascending `chunk_id` for deterministic tie-breaking. This is a transparent
term-overlap baseline, not BM25. It performs no stemming, stop-word removal, synonym
expansion, phrase weighting, term-frequency weighting, or semantic matching.

### Rarity-aware IDF overlap

`InMemoryIdfKnowledgeRetriever` calculates chunk frequency once while building its
index. For `N` indexed chunks and the number `df(t)` of chunks containing term `t`, its
smoothed inverse document frequency is:

```text
idf(t) = ln((N + 1) / (df(t) + 1)) + 1
```

For the distinct query-term set `Q` and chunk-term set `C`, the weighted score is:

```text
score(query, chunk) = sum(idf(t) for t in Q intersect C)
                      / sum(idf(t) for t in Q)
```

Rare matching terms therefore contribute more than terms found in many chunks. The
score remains deterministic, zero-score chunks are omitted, and equal scores are again
ordered by ascending `chunk_id`. The implementation adds no stemming, synonyms, field
boosting, query expansion, term frequency, or semantic signal.

## Retrieval Evaluation

`evals/datasets/knowledge_retrieval_v1.jsonl` contains ten versioned cases with stable
`case_id` values, natural technical queries, and exact
`expected_relevant_chunk_ids`. Three cases have multiple relevant chunks.

The deterministic runner reports:

* **Hit@1:** share of cases whose first result is one of the expected relevant chunks.
* **Hit@k:** share of cases with at least one expected relevant chunk among the first
  `k` results.
* **Recall@k per case:** number of expected relevant chunks found in the first `k`,
  divided by the number of expected relevant chunks.
* **Mean Recall@k:** arithmetic mean of per-case Recall@k values.

The report identifies the selected strategy and lists Hit@1 misses, Hit@k misses,
incomplete-recall cases, and their union as `failed_case_ids`. Every case retains
expected chunk IDs and its actual ranking with scores.

Run the local baseline with:

```powershell
python -m evals.run_retrieval --strategy simple
python -m evals.run_retrieval --strategy idf
```

An alternative dataset, knowledge-base directory, or `k` can be selected explicitly:

```powershell
python -m evals.run_retrieval `
  --dataset evals/datasets/knowledge_retrieval_v1.jsonl `
  --knowledge-base knowledge_base `
  --strategy idf `
  --k 3
```

Generated JSON can be written under the Git-ignored `evals/results/` directory with
`--output`.

## Strategy Comparison

Both implementations were evaluated against the unchanged ten-case
`knowledge_retrieval_v1.jsonl` dataset and the same ground truth:

| Metric | Simple overlap | Rarity-aware IDF |
| --- | ---: | ---: |
| Hit@1 | 0.9 | 1.0 |
| Hit@3 | 1.0 | 1.0 |
| Mean Recall@3 | 0.95 | 0.95 |
| Hit@1 misses | `station_quality_role` | none |
| Hit@3 misses | none | none |
| Incomplete Recall@3 | `product_failure_context_multiple` | `product_failure_context_multiple` |

For the two known problem cases, the Top-3 rankings are:

| Case and strategy | Rank 1 | Rank 2 | Rank 3 |
| --- | --- | --- | --- |
| `station_quality_role`, simple | `error_codes::chunk-003` (0.6250) | `station_s04::chunk-001` (0.6250) | `error_codes::chunk-001` (0.2500) |
| `station_quality_role`, IDF | `station_s04::chunk-001` (0.5504) | `error_codes::chunk-003` (0.4895) | `error_codes::chunk-001` (0.1616) |
| `product_failure_context_multiple`, simple | `station_s04::chunk-002` (0.7000) | `maintenance::chunk-002` (0.4000) | `station_s04::chunk-003` (0.4000) |
| `product_failure_context_multiple`, IDF | `station_s04::chunk-002` (0.5923) | `maintenance::chunk-002` (0.2639) | `station_s04::chunk-003` (0.2639) |

IDF resolves the simple strategy's tie for `station_quality_role` because the relevant
chunk matches the rarer term `final`. It does not recover the second expected chunk for
`product_failure_context_multiple`: the query's rare product-specific terms strongly
favor the product-history passage, while IDF alone adds no relationship or phrase
signal that would promote the error-code passage into the Top 3. No evaluated case
became worse. The dataset, ground truth, and scoring metrics were not changed after the
comparison.

## Known Limits

The tiny corpus and both exact-overlap scores are intentionally easy to understand, but
they are not representative of production scale. IDF only models corpus rarity; it does
not understand synonyms, paraphrases, phrases, or relationships between a product
failure and its error-code reference. Section-position IDs can shift after structural
document edits, and there is no index persistence or freshness management. Final-answer
grounding and agent query quality are not evaluated by this retrieval baseline.
