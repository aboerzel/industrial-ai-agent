# Local Knowledge Retrieval Baseline

## Purpose

The productive retrieval slice implements BM25, the semantic baseline described by
ADR-007, rank-fused BM25-plus-semantic hybrid retrieval, and local cross-encoder
reranking. Version 2 expanded and froze the corpus and evaluation set before those
strategies were implemented, so none could shape its own benchmark. The frozen pipeline
is exposed by `knowledge_mcp`, but LangGraph reaches it only through MCP discovery,
never through a direct retriever. The former simple-overlap and IDF implementations were
removed during cleanup; their recorded results below are historical evidence only.

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
`DocumentationSearchCapability.search_documentation(query, top_k=3)` depends only on
that port. `knowledge_mcp` is a thin transport adapter over this capability and adds no
retrieval behavior.

Each `KnowledgeRetrievalResult` preserves passage content, `document_id`, relative
`source`, stable `chunk_id`, optional `relevance_score`, and metadata. The capability
returns a structured result and does not construct prose. Filesystem access and all
ranking implementations remain in Infrastructure.

## Lexical Strategies and Historical Baselines

The current BM25 strategy and the former historical baselines use the same tokenizer. It case-folds text and extracts
alphanumeric terms while preserving hyphenated identifiers. Consequently,
`E-STOP-17`, `e-stop-17`, and `E-STOP-17!!!` produce the same identifier token.

### Simple term overlap (historical, no longer executable)

For the distinct normalized query-term set `Q` and chunk-term set `C`, the score is:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks with score `0` are omitted. Remaining chunks are sorted by descending score and
then by ascending `chunk_id` for deterministic tie-breaking. There is no stemming,
stop-word removal, synonym expansion, phrase weighting, term-frequency weighting, or
semantic matching.

### Rarity-aware IDF overlap (historical, no longer executable)

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

### BM25

BM25 retains the full document token sequence so repeated terms contribute term
frequency `tf(t,d)` and chunk length `|d|`. For corpus size `N`, chunk document
frequency `df(t)`, and average chunk length `avgdl`, this implementation uses:

```text
idf_bm25(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(q, d) = sum(
    idf_bm25(t)
    * (tf(t,d) * (k1 + 1))
      / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
    for each distinct t in q
)
```

`tf(t,d)` rewards repeated evidence with diminishing returns. `idf_bm25(t)` gives rare
terms more influence. `k1` controls term-frequency saturation, while `b` controls
chunk-length normalization relative to `avgdl`. The fixed baseline parameters are
`k1 = 1.5` and `b = 0.75`; they were selected before the first v2 run and were not
tuned against its results. Zero-score chunks are omitted, and equal scores are ordered
by ascending `chunk_id`.

## Semantic Baseline

ADR-007 introduces a separate inner `EmbeddingClient` port with
`embed_query(text)` and `embed_documents(texts)`. It returns only numeric vectors and
does not expose LangChain, Ollama, or provider SDK types. The local
`OllamaEmbeddingClient` adapts LangChain `OllamaEmbeddings` with the baseline model
`qwen3-embedding:0.6b` at `http://localhost:11434`.

`InMemorySemanticKnowledgeRetriever` implements the existing `KnowledgeRetriever` port.
At explicit construction, it sends the unchanged 25 chunks in one batch through the
embedding port and stores the resulting vectors in LangChain Core's
`InMemoryVectorStore`. Query-time retrieval embeds only the query, asks that store for
its top-k vector matches, then maps results back to the original chunks by stable
`chunk_id`. It preserves the existing content and provenance. The score is the vector
store's similarity score and is not numerically comparable to lexical scores.

This is a local-only baseline. No document text or embedding is sent to a cloud provider.
`numpy` is a direct dependency because LangChain's `InMemoryVectorStore` uses it for its
implemented similarity calculation. The store is recreated during explicit adapter
construction; it is neither a persistent vector database nor a project-wide similarity
decision.

## Hybrid Baseline

`HybridKnowledgeRetriever` is another Infrastructure implementation of the unchanged
`KnowledgeRetriever` port. It composes the existing BM25 and semantic retrievers; it
does not alter either component's tokenizer, index, ranking algorithm, or score. For
this small frozen corpus, it asks each component for all 25 chunks and then applies
equal-weight Reciprocal Rank Fusion (RRF) using one-based ranks:

```text
rrf_score(d) = sum(1 / (60 + rank_i(d)))
               for each component ranking i containing d
```

The rank constant is fixed at `60` before the first hybrid v2 run. BM25 and vector-store
scores are intentionally never added, normalized, or otherwise compared: they are on
incompatible scales. A chunk occurring in both rankings receives both rank
contributions; a chunk occurring in only one ranking remains eligible. Equal fused
scores use ascending `chunk_id` as the deterministic tie-breaker. The installed
`langchain-core`, `langchain-ollama`, and `langgraph` versions contain no stable
Ensemble/RRF retriever component, so this narrow deterministic function is local rather
than introducing an additional LangChain package or a generic fusion framework.

## Reranking Baseline

Retrieval and reranking have different jobs. BM25 and the semantic bi-encoder retrieve
candidate passages efficiently from the corpus; a cross-encoder receives the query and
one candidate passage together, so it can model their direct relation more precisely.
That joint inference is more expensive, which is why it runs only after candidate
generation instead of over every chunk.

The provider-neutral inner `Reranker` port accepts `rerank(query, candidates)` and
returns the same structured candidates in a new order. It exposes no Torch,
Transformers, Hugging Face, or Sentence Transformers types. The local
`SentenceTransformersCrossEncoderReranker` adapts `sentence_transformers.CrossEncoder`
with `BAAI/bge-reranker-v2-m3`. `RerankedKnowledgeRetriever` composes the existing
hybrid retriever and that port, validates that the reranker returns exactly the supplied
candidate IDs, and keeps the original content and provenance. Its generic
`relevance_score` is the reranker result; no framework-specific score type reaches the
Core.

The fixed pipeline parameters, selected before the first reranked v2 run, are BM25
candidate depth `10`, semantic candidate depth `10`, RRF rank constant `60`, fused
candidate depth `10`, and final eval `top_k=3`. The reranker cannot introduce chunks
outside those ten fused candidates. `HybridKnowledgeRetriever` retains its original
full-corpus default; only the reranked composition explicitly supplies the candidate
depth.

Inference is local-only. The adapter loads from the local Hugging Face cache with
`local_files_only=True`, so runtime cannot send queries, chunks, embeddings, or scores
to a cloud service. Cache the public model artifact explicitly before a first local run:

```powershell
hf download BAAI/bge-reranker-v2-m3
```

The adapter selects `cuda` when `torch.cuda.is_available()` and otherwise falls back to
`cpu`; neither behavior leaks into Core code. On the RTX 3070 used for this baseline,
the cached model loaded in roughly 33 seconds and the complete 28-case eval, including
model initialization, took roughly 18 seconds. These are local observations, not a
performance target.

## Knowledge MCP Deployment Boundary

`knowledge_mcp` composes this exact frozen pipeline once at process startup and exposes
only `search_documentation(query, top_k=3)`. It supports stdio for development/test and
Streamable HTTP for Docker deployment. Its Docker image contains source and the knowledge
base but no Ollama or Hugging Face model artifact. Compose connects to local host Ollama
and mounts a pre-populated Hugging Face cache read-only; CPU is portable default, while
in-process development can retain CUDA. MCP network transport is separate from model
egress: documents, chunks, queries, embeddings, and reranker inputs remain local under
ADR-009 and never reach a public provider.

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
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy bm25
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy semantic
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy hybrid
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy reranked
python scripts/smoke_test_semantic_retrieval.py
python scripts/smoke_test_reranked_retrieval.py
```

The original v1 dataset remains selectable with `--dataset
evals/datasets/knowledge_retrieval_v1.jsonl`. Generated JSON can be written under the
Git-ignored `evals/results/` directory with `--output`.

## Freeze Rule

The seven-document corpus and v2 ground truth were frozen on 2026-09-04 before the
first v2 retrieval run. The dataset SHA-256 at freeze is
`E535816185D90DA816C5FD2033865094BD430E3752AE19632647E82309A46EA6`.
Neither v2 queries nor relevance labels may be changed in response to later BM25,
semantic, hybrid, or reranked-retrieval results. Corpus wording and chunking used for that
comparison are frozen as well. A necessary correction must be explicit and versioned as
a later dataset rather than silently rewriting v2.

## v1 and v2 Baselines

The v1 values are the historical three-document baseline recorded before corpus
expansion. The v2 values use the frozen seven-document, 25-chunk corpus.

| Dataset | Metric | Simple overlap | Rarity-aware IDF | BM25 | Semantic | Hybrid RRF | Hybrid + reranker |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 (10 cases) | Hit@1 | 0.9000 | 1.0000 | 0.9000 | not measured | not measured | not measured |
| v1 (10 cases) | Hit@3 | 1.0000 | 1.0000 | 1.0000 | not measured | not measured | not measured |
| v1 (10 cases) | Mean Recall@3 | 0.9500 | 0.9500 | 0.9500 | not measured | not measured | not measured |
| v2 (28 cases) | Hit@1 | 0.7857 | 0.8571 | 0.7857 | 0.8571 | 0.7857 | 0.8214 |
| v2 (28 cases) | Hit@3 | 0.8929 | 0.9286 | 0.9643 | 0.9643 | 0.9643 | 1.0000 |
| v2 (28 cases) | Mean Recall@3 | 0.8155 | 0.8452 | 0.8810 | 0.8810 | 0.8988 | 0.9881 |

The v1 regression against the expanded 25-chunk corpus reproduced the existing simple
and IDF values. BM25 reached `0.9000 / 1.0000 / 0.9500`; its only Hit@1 miss was
`error_code_exact`, and `product_failure_context_multiple` retained incomplete
Recall@3.

The v2 failure lists are:

| Failure | Simple overlap | Rarity-aware IDF | BM25 | Semantic | Hybrid RRF | Hybrid + reranker |
| --- | --- | --- | --- | --- | --- | --- |
| Hit@1 misses | `station_quality_role`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_invalid_after_work`, `calibration_procedure`, `qv1_role_short` | `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `error_code_exact`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple` | `station_current_fault`, `axis_encoder_short`, `qv1_role_short`, `vision_recovery_multiple` | `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `s02_operator_diagnosis`, `s02_recovery_verification`, `calibration_procedure`, `service_evidence_multiple`, `vision_recovery_multiple` |
| Hit@3 misses | `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `s02_recovery_verification`, `calibration_procedure` | `s02_recovery_verification` | `qv1_role_short` | `s02_recovery_verification` | none |
| Incomplete Recall@3 | `product_failure_context_multiple`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `calibration_procedure`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `service_evidence_multiple`, `vision_recovery_multiple` | `positioning_causes_natural`, `axis_encoder_short`, `positioning_long_diagnosis`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `service_evidence_multiple`, `vision_recovery_multiple` | `vision_recovery_multiple` |

## v2 Results by Category

| Category (n) | Simple H@1/H@3/MR@3 | IDF H@1/H@3/MR@3 | BM25 H@1/H@3/MR@3 | Semantic H@1/H@3/MR@3 | Hybrid H@1/H@3/MR@3 | Reranked H@1/H@3/MR@3 |
| --- | --- | --- | --- | --- | --- | --- |
| Exact identifiers (15) | 0.8667 / 0.8667 / 0.7889 | 0.8667 / 0.9333 / 0.8444 | 0.8000 / 1.0000 / 0.9111 | 0.7333 / 0.9333 / 0.8444 | 0.8000 / 1.0000 / 0.9444 | 0.8000 / 1.0000 / 0.9778 |
| Natural language (17) | 0.7059 / 0.8824 / 0.8235 | 0.8235 / 0.8824 / 0.8235 | 0.7647 / 0.9412 / 0.8824 | 0.9412 / 1.0000 / 0.9412 | 0.7647 / 0.9412 / 0.8824 | 0.7647 / 1.0000 / 1.0000 |
| Rare terms (7) | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 0.9286 | 0.8571 / 1.0000 / 0.9286 | 0.8571 / 1.0000 / 0.9286 | 1.0000 / 1.0000 / 0.9286 | 1.0000 / 1.0000 / 1.0000 |
| Common-term ambiguity (14) | 0.7143 / 0.7857 / 0.7857 | 0.7857 / 0.8571 / 0.8571 | 0.7857 / 0.9286 / 0.9286 | 0.8571 / 0.9286 / 0.9286 | 0.7857 / 0.9286 / 0.9286 | 0.7857 / 1.0000 / 1.0000 |
| Multi-relevance (9) | 0.8889 / 1.0000 / 0.7593 | 0.8889 / 1.0000 / 0.7407 | 0.7778 / 1.0000 / 0.7407 | 0.7778 / 1.0000 / 0.7407 | 0.6667 / 1.0000 / 0.7963 | 0.7778 / 1.0000 / 0.9630 |
| Short queries (5) | 0.8000 / 0.8000 / 0.8000 | 0.8000 / 1.0000 / 0.9000 | 0.8000 / 1.0000 / 0.9000 | 0.6000 / 0.8000 / 0.7000 | 0.8000 / 1.0000 / 0.9000 | 1.0000 / 1.0000 / 1.0000 |
| Longer technical queries (5) | 1.0000 / 1.0000 / 0.6667 | 1.0000 / 1.0000 / 0.7333 | 0.8000 / 1.0000 / 0.7333 | 0.8000 / 1.0000 / 0.7333 | 0.6000 / 1.0000 / 0.8333 | 0.6000 / 1.0000 / 0.9333 |
| Cross-document ambiguity (20) | 0.7500 / 0.9000 / 0.7917 | 0.8500 / 0.9500 / 0.8333 | 0.8000 / 0.9500 / 0.8333 | 0.8500 / 0.9500 / 0.8333 | 0.7500 / 0.9500 / 0.8583 | 0.8000 / 1.0000 / 0.9833 |
| Term-frequency-sensitive (4) | 0.5000 / 0.7500 / 0.6250 | 0.5000 / 0.7500 / 0.6250 | 0.5000 / 1.0000 / 0.8750 | 1.0000 / 1.0000 / 0.7500 | 0.5000 / 1.0000 / 0.8750 | 0.7500 / 1.0000 / 1.0000 |
| Length-sensitive (6) | 0.8333 / 1.0000 / 0.7222 | 0.8333 / 1.0000 / 0.7778 | 0.6667 / 1.0000 / 0.7778 | 0.8333 / 1.0000 / 0.6944 | 0.5000 / 1.0000 / 0.7778 | 0.6667 / 1.0000 / 0.9444 |

## Ranking Differences and Interpretation

Selected BM25 Top-3 rankings show where the new signals help and where lexical overlap
still dominates incorrectly:

| Case | BM25 rank 1 | BM25 rank 2 | BM25 rank 3 |
| --- | --- | --- | --- |
| `error_code_exact` | `station_s04::chunk-002` (6.2842) | `error_codes::chunk-002` (5.5117) | `error_codes::chunk-001` (3.9496) |
| `positioning_causes_natural` | `station_s02::chunk-001` (8.5921) | `station_s02::chunk-002` (5.6584) | `maintenance::chunk-002` (2.7372) |
| `s02_recovery_verification` | `station_s02::chunk-003` (4.7327) | `troubleshooting_service::chunk-002` (4.5982) | `maintenance::chunk-002` (4.4223) |
| `calibration_procedure` | `vision_calibration::chunk-002` (5.7888) | `vision_calibration::chunk-003` (4.8377) | `vision_calibration::chunk-004` (4.5653) |
| `qv1_role_short` | `production_quality::chunk-002` (3.1451) | `vision_calibration::chunk-001` (2.3338) | `station_s04::chunk-001` (1.5720) |
| `service_evidence_multiple` | `troubleshooting_service::chunk-002` (8.5692) | `production_quality::chunk-003` (8.3476) | `maintenance::chunk-003` (5.4675) |
| `vision_recovery_multiple` | `troubleshooting_service::chunk-003` (13.0595) | `vision_calibration::chunk-001` (9.4296) | `vision_calibration::chunk-004` (8.8271) |

BM25's main gain is recall depth. `calibration_procedure` moves from a Hit@3 miss under
simple and IDF to rank 2 because repeated matching terms and length normalization make
the procedure passage competitive. `qv1_role_short` remains wrong at rank 1 but is a
Hit@3, as under IDF. `vision_recovery_multiple` retains IDF's two of three relevant
chunks, improving over simple's one. The term-frequency-sensitive category improves
strongly at Hit@3 and Mean Recall@3, consistent with the intended TF saturation and
length normalization signals.

The trade-off is weaker rank-1 precision. `error_code_exact` changes from a correct IDF
rank 1 to rank 2 because the shorter station passage repeats the matching identifier
and receives a stronger normalized contribution. `service_evidence_multiple` keeps
Recall@3 at 0.5 but loses Hit@1 when the recurring-failure passage accumulates more
matching terms than the expected evidence passages. BM25 does not improve aggregate
Multi-Relevance recall over IDF and reduces its Hit@1.

`positioning_causes_natural` and `s02_recovery_verification` are fundamentally hard for
these lexical strategies: phrases such as "commanded location" versus "target
position", and "prove ... ready after repair" versus "confirm homing, run one dry
cycle, and inspect", share too little discriminating vocabulary. BM25 cannot create
missing synonym or semantic relationships. `qv1_role_short` is also lexically
underspecified, so a more specific outcome passage matches better than the intended
overview. Several remaining incomplete Multi-Relevance cases express multiple intents
whose complementary passages compete for only three result positions.

### Semantic Comparison

The semantic baseline improves the natural-language category materially: `0.9412 /
1.0000 / 0.9412`, compared with BM25's `0.7647 / 0.9412 / 0.8824`. Its improvements are
consistent with different wording rather than a changed corpus: `positioning_causes_natural`
places the expected `station_s02::chunk-002` first (0.6968),
`s02_recovery_verification` places `station_s02::chunk-004` first (0.5760), and
`calibration_procedure` places `vision_calibration::chunk-003` first (0.6519). BM25
places those expected chunks at ranks 2, outside Top-3, and 2 respectively.

| Case | Expected chunk(s) | Semantic Top-3 | BM25 Top-3 |
| --- | --- | --- | --- |
| `positioning_causes_natural` | `station_s02::chunk-002`, `troubleshooting_service::chunk-002` | `station_s02::chunk-002` (0.6968), `station_s02::chunk-001` (0.6228), `station_s02::chunk-003` (0.6038) | `station_s02::chunk-001` (8.5921), `station_s02::chunk-002` (5.6584), `maintenance::chunk-002` (2.7372) |
| `s02_recovery_verification` | `station_s02::chunk-004` | `station_s02::chunk-004` (0.5760), `station_s02::chunk-001` (0.5430), `station_s02::chunk-002` (0.5113) | `station_s02::chunk-003` (4.7327), `troubleshooting_service::chunk-002` (4.5982), `maintenance::chunk-002` (4.4223) |
| `qv1_role_short` | `vision_calibration::chunk-001` | `error_codes::chunk-003` (0.5685), `station_s04::chunk-001` (0.5537), `production_quality::chunk-002` (0.5486) | `production_quality::chunk-002` (3.1451), `vision_calibration::chunk-001` (2.3338), `station_s04::chunk-001` (1.5720) |
| `calibration_procedure` | `vision_calibration::chunk-003` | `vision_calibration::chunk-003` (0.6519), `vision_calibration::chunk-002` (0.6496), `vision_calibration::chunk-004` (0.5898) | `vision_calibration::chunk-002` (5.7888), `vision_calibration::chunk-003` (4.8377), `vision_calibration::chunk-004` (4.5653) |

Semantic ranking is weaker for exact identifiers (`0.7333` Hit@1 versus BM25's `0.8000`)
and short queries (`0.6000 / 0.8000 / 0.7000` versus `0.8000 / 1.0000 / 0.9000`).
`qv1_role_short` becomes a semantic Hit@3 miss, whereas BM25 retains it at rank 2. The
semantic model also does not improve aggregate Multi-Relevance recall, because
complementary relevant chunks still compete for three places. The score scales differ,
so they support ranking inspection only, not direct cross-strategy comparison.

### Hybrid Comparison

The fixed RRF hybrid reaches `0.7857 / 0.9643 / 0.8988` for Hit@1, Hit@3, and Mean
Recall@3. Thus it retains the best Hit@3 while increasing recall depth by `0.0179` over
each individual BM25 and semantic baseline. This is most visible for exact identifiers
(`0.9444` Mean Recall@3), multi-relevance (`0.7963`), longer technical queries
(`0.8333`), and cross-document ambiguity (`0.8583`). It does not improve rank-one
precision: BM25's lexical evidence can demote semantically correct first results, and
the deterministic `chunk_id` tie-breaker resolves equal fused scores without semantic
preference.

| Case | Expected chunk(s) | BM25 Top-3 | Semantic Top-3 | Hybrid Top-3 (RRF) |
| --- | --- | --- | --- | --- |
| `positioning_causes_natural` | `station_s02::chunk-002`, `troubleshooting_service::chunk-002` | `station_s02::chunk-001` (8.5921), `station_s02::chunk-002` (5.6584), `maintenance::chunk-002` (2.7372) | `station_s02::chunk-002` (0.6968), `station_s02::chunk-001` (0.6228), `station_s02::chunk-003` (0.6038) | `station_s02::chunk-001` (0.032522), `station_s02::chunk-002` (0.032522), `station_s02::chunk-003` (0.030798) |
| `s02_recovery_verification` | `station_s02::chunk-004` | `station_s02::chunk-003` (4.7327), `troubleshooting_service::chunk-002` (4.5982), `maintenance::chunk-002` (4.4223) | `station_s02::chunk-004` (0.5760), `station_s02::chunk-001` (0.5430), `station_s02::chunk-002` (0.5113) | `station_s02::chunk-003` (0.032018), `station_s02::chunk-002` (0.031498), `station_s02::chunk-001` (0.031281) |
| `qv1_role_short` | `vision_calibration::chunk-001` | `production_quality::chunk-002` (3.1451), `vision_calibration::chunk-001` (2.3338), `station_s04::chunk-001` (1.5720) | `error_codes::chunk-003` (0.5685), `station_s04::chunk-001` (0.5537), `production_quality::chunk-002` (0.5486) | `production_quality::chunk-002` (0.032266), `station_s04::chunk-001` (0.032002), `vision_calibration::chunk-001` (0.031754) |
| `calibration_procedure` | `vision_calibration::chunk-003` | `vision_calibration::chunk-002` (5.7888), `vision_calibration::chunk-003` (4.8377), `vision_calibration::chunk-004` (4.5653) | `vision_calibration::chunk-003` (0.6519), `vision_calibration::chunk-002` (0.6496), `vision_calibration::chunk-004` (0.5898) | `vision_calibration::chunk-002` (0.032522), `vision_calibration::chunk-003` (0.032522), `vision_calibration::chunk-004` (0.031746) |
| `error_code_exact` | `error_codes::chunk-002` | `station_s04::chunk-002` (6.2842), `error_codes::chunk-002` (5.5117), `error_codes::chunk-001` (3.9496) | `error_codes::chunk-002` (0.8045), `station_s04::chunk-002` (0.7444), `maintenance::chunk-002` (0.6557) | `error_codes::chunk-002` (0.032522), `station_s04::chunk-002` (0.032522), `error_codes::chunk-001` (0.031258) |
| `service_evidence_multiple` | `production_quality::chunk-003`, `troubleshooting_service::chunk-004` | `troubleshooting_service::chunk-002` (8.5692), `production_quality::chunk-003` (8.3476), `maintenance::chunk-003` (5.4675) | `troubleshooting_service::chunk-004` (0.6593), `troubleshooting_service::chunk-001` (0.6158), `maintenance::chunk-003` (0.5190) | `troubleshooting_service::chunk-002` (0.032018), `maintenance::chunk-003` (0.031746), `troubleshooting_service::chunk-004` (0.031545) |

The comparison exposes complementary evidence but not a universal rank-one solution.
For `error_code_exact`, the equal RRF score is resolved toward the expected error-code
chunk. For `qv1_role_short`, hybrid restores a Top-3 hit that semantic retrieval misses,
but ranks it below BM25's position. Conversely, `s02_recovery_verification` is a hybrid
Hit@3 miss even though semantic retrieval alone ranks the expected verification chunk
first: the lexical top ranks crowd it out. `positioning_causes_natural` still lacks the
second relevant service passage, and `service_evidence_multiple` still retrieves only
one of its two expected passages. These are remaining depth and intent-disambiguation
limits, not grounds for changing v2 labels or the frozen corpus.

### Reranking Comparison

`Hybrid + reranker` reaches `0.8214 / 1.0000 / 0.9881` for Hit@1, Hit@3, and Mean
Recall@3 on v2, compared with hybrid's `0.7857 / 0.9643 / 0.8988`. It removes every
Hit@3 miss; only `vision_recovery_multiple` retains incomplete Recall@3. By category,
it reaches complete recall for natural language, rare terms, common-term ambiguity,
short queries, and term-frequency-sensitive cases; multi-relevance rises to
`0.7778 / 1.0000 / 0.9630`.

`positioning_causes_natural` moves `station_s02::chunk-002` from hybrid rank 2 to rank
1 (0.688441) and also raises the relevant `troubleshooting_service::chunk-002` to rank
3. `qv1_role_short` places `vision_calibration::chunk-001` first (0.914100). For
`s02_recovery_verification`, `station_s02::chunk-004` moves from hybrid rank 7 to rank
3 (0.001280), fixing Hit@3 but not Hit@1. `calibration_procedure` retains
`vision_calibration::chunk-003` at rank 3 (0.144749), and
`service_evidence_multiple` retains `troubleshooting_service::chunk-002` first rather
than an expected passage. Reranker scores are meaningful only for sorting candidates of
the same query.

The local smoke for "How do I verify that S02 is ready again after repair?" moved
`station_s02::chunk-004` from hybrid rank 2 to reranker rank 1 (0.714973), while
preserving complete source and chunk provenance.

## Known Limits

The corpus remains intentionally small and manually inspectable rather than production
scale. BM25 still has no stemming, synonyms, phrase model, query expansion, or semantic
understanding. The semantic baseline is local-only, and the fixed hybrid has no
identifier boost or learned weights. The first local reranker has no ensemble, second
model variant, query rewriting, persistent index, freshness management, or
embedding-routing policy. `InMemoryVectorStore` is recreated at construction and is not
a vector-database decision. Section-position IDs can shift after structural document
edits. Final-answer grounding and agent query quality are not evaluated by this
retrieval baseline.
