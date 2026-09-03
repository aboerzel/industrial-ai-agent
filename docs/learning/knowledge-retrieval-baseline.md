# Local Knowledge Retrieval Baseline

## Purpose

The first retrieval slice implements the smallest measurable baseline from ADR-006. It
searches a small versioned technical knowledge base without an LLM, embeddings, a vector
database, reranking, MCP, or an external retrieval library. Retrieval remains isolated
from `TroubleshootingAgent` so its quality can be measured independently from query
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

## Lexical Scoring

The baseline tokenizer case-folds text and extracts alphanumeric terms while preserving
hyphenated identifiers. Consequently, `E-STOP-17`, `e-stop-17`, and
`E-STOP-17!!!` produce the same identifier token.

For the distinct normalized query-term set `Q` and chunk-term set `C`, the score is:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks with score `0` are omitted. Remaining chunks are sorted by descending score and
then by ascending `chunk_id` for deterministic tie-breaking. This is a transparent
term-overlap baseline, not BM25. It performs no stemming, stop-word removal, synonym
expansion, phrase weighting, term-frequency weighting, or semantic matching.

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

The report lists Hit@1 misses, Hit@k misses, incomplete-recall cases, and their union as
`failed_case_ids`. Every case retains expected and actual chunk IDs.

Run the local baseline with:

```powershell
python -m evals.run_retrieval
```

An alternative dataset, knowledge-base directory, or `k` can be selected explicitly:

```powershell
python -m evals.run_retrieval `
  --dataset evals/datasets/knowledge_retrieval_v1.jsonl `
  --knowledge-base knowledge_base `
  --k 3
```

Generated JSON can be written under the Git-ignored `evals/results/` directory with
`--output`.

## Initial Baseline Result

The first versioned dataset and implementation produce:

* 10 cases;
* Hit@1 `0.9`;
* Hit@3 `1.0`; and
* Mean Recall@3 `0.95`.

`station_quality_role` finds the expected `station_s04::chunk-001` at rank 2 instead of
rank 1. `product_failure_context_multiple` retrieves
`station_s04::chunk-002` but misses `error_codes::chunk-002` within the first three
results, yielding Recall@3 `0.5`. The dataset and ground truth remain unchanged; these
failures are the comparison baseline for later retrieval improvements.

## Known Limits

The tiny corpus and exact term-overlap score are intentionally easy to understand, but
they are not representative of production scale. Common words can outrank a more useful
passage, synonyms and paraphrases are not understood, all query terms have equal
weight, section-position IDs can shift after structural document edits, and there is no
index persistence or freshness management. Final-answer grounding and agent query
quality are not evaluated by this retrieval baseline.
