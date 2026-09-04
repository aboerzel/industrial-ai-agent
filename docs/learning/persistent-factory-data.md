# Persistent Factory Data and Classification

## Structured and Unstructured Sources

`FACTORY-DEMO-01` separates structured operational data from unstructured documents.
PostgreSQL persists factory, station, product, production, machine, alarm, quality,
maintenance, process-parameter, and `document_catalog` records. The catalog is the
metadata source of truth for local PDF, DOCX, PPTX, XLSX, and image assets; a directory
name never grants or lowers classification.

The deterministic seed covers P4711's S02 `POSITION-ENC-02` warning and S04
`QUALITY-09` rejection, repeated S02 warnings for P4801/P4802/P4805/P4811, maintenance
steps, and an S03 restricted process parameter. All data is synthetic.

## Three Different Security Questions

* **Classification** is the sensitivity of information: `PUBLIC < INTERNAL <
  CONFIDENTIAL < RESTRICTED`.
* **Authorization** answers whether a subject may see it. `SecurityContext` carries a
  provider-independent subject ID, roles, clearance, and authentication state.
* **Egress** answers whether the accumulated context may leave an execution zone.
  ADR-009 makes confidential and restricted data local-model-only.

These questions must not be delegated to an LLM or collapsed into a single Boolean.

## PostgreSQL RLS

Migrations create `factory_migration_owner` and the non-superuser, no-`BYPASSRLS`
`factory_app` role. Each classified table enables and forces RLS. Application repository
transactions call parameterized PostgreSQL `set_config` to set a transaction-local
`app.clearance`; the RLS policy returns only records at or below that value. The migration
service uses the separate admin path. Python filtering is defense in depth, not the sole
database boundary.

## Local Document Ingestion

Knowledge MCP reads RLS-eligible catalog records, verifies file checksums, normalizes
each file through Docling, chunks normalized content with stable
`document_id::chunk-NNN` IDs, and hands those chunks to the existing BM25 + semantic +
RRF + local cross-encoder pipeline. Classification and provenance are copied from the
catalog record into every parsed document, chunk, and structured retrieval result. The
security filter runs before parsing, embeddings, and reranking.

Docling and the reranker operate locally. The Compose cache volume is outside the image
so no model artifact is baked into it. Fetching an initial public model artifact is
separate from data egress: document content, queries, chunks, embeddings, and reranker
inputs do not leave the local services.

## Effective Run Classification

LangGraph begins with server-owned task requirements. On each tool observation, its
effective classification is the maximum of previous and observed values. It can rise but
cannot silently decrease. Before every later provider call, `EgressCheckedLLMClient`
applies ADR-009 again. Consequently a confidential factory result blocks a public-cloud
profile even if the original request was public.

Authentication is intentionally not implemented. A later FastAPI JWT/OIDC adapter will
construct the same `SecurityContext`; the agent itself will not own identity handling.
