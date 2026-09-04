# ADR-014: Persistent Factory Data and Classification Enforcement

## Status

Accepted

## Context

The initial Factory and Knowledge MCP services use synthetic in-memory repositories and
a small Markdown-only retrieval corpus. They are useful for deterministic learning and
transport tests, but do not represent a persistent factory data boundary, classified
records, multi-format operational documentation, or database-enforced access control.

The next increment needs structured production data, unstructured documents, and
deterministic classification handling without moving authorization, persistence, or
ingestion behavior into the LangGraph agent, MCP handlers, or LLM prompts.

## Decision

PostgreSQL is the persistent source of truth for structured `FACTORY-DEMO-01` data and
for document-catalog metadata. The catalog records document identity, checksum, source,
MIME type, version, factory/station association, and explicit classification. The source
documents themselves remain versioned file assets; their directory names are only for
human readability and never determine classification.

Every classified record uses the existing ordered taxonomy:

```text
PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED
```

Classification is information sensitivity. Authorization answers whether a subject may
see information. Model egress answers whether the effective information context may
enter an execution zone. These are separate deterministic responsibilities. No `SECRET`
class is introduced and this project taxonomy is technical rather than regulatory.

A provider-independent `SecurityContext` contains `subject_id`, roles, clearance, and
an `authenticated` flag. The local/demo composition injects the unauthenticated
`demo-engineer` context with `CONFIDENTIAL` clearance. It prepares FastAPI to translate
a future verified identity into the same structure, but does not implement identity
handling, JWT, OIDC, or login.

Classification propagates monotonically. Document classification is copied into parsed
documents, chunks, retrieval results, and tool results. A run's effective classification
is the maximum of its initial classification and each observed classified result; it may
increase but never silently decrease. ADR-009 remains the independent final egress
boundary before every model invocation.

PostgreSQL Row-Level Security is enabled and forced for classified runtime tables. The
non-superuser application role has neither `BYPASSRLS` nor ownership privileges. It sets
the validated clearance only with parameterized `SET LOCAL app.clearance` in each
transaction. Policies admit only rows whose stored classification rank is at or below
the transaction clearance. Repository-side predicates are retained as defense in depth,
but are not the sole access boundary. A separate migration/owner role initializes the
schema and seed data; Factory and Knowledge MCP runtime connections use only the
application role.

SQLAlchemy 2.x and Psycopg 3 implement PostgreSQL adapters. Alembic owns migrations;
there is no project-specific migration system. Reproducible synthetic seed data supports
Factory MCP and document-catalog integration tests. In-memory factory repositories remain
for focused unit tests and become cleanup candidates after the persistent composition is
validated.

Docling performs local ingestion for PDF, DOCX, PPTX, XLSX, and image assets into one
normalized representation. The pipeline is explicit:

```text
Document catalog -> file -> Docling -> normalized document -> chunking
                 -> classification propagation -> retrieval index
```

Retrieval applies clearance filtering before BM25, semantic retrieval, RRF, and
reranking. The agent continues to see only `search_documentation`; neither it nor the
MCP handler knows files, Docling, PostgreSQL, or retrieval storage details.

Factory MCP continues to expose only `get_product_history` and `get_machine_status`.
Knowledge MCP continues to expose only `search_documentation`. Their production
composition roots use the persistent adapters while stdio remains a valid local/test MCP
transport.

All demo records and documents are synthetic. No real company, customer, credential, or
production data may enter the repository.

## Consequences

Positive:

* Factory and document metadata survive process restarts and are queryable consistently.
* RLS prevents accidental higher-classification reads even if an application predicate
  is omitted.
* Classification follows actual data across repository, retrieval, MCP, and model use.
* Multi-format ingestion is local and replaceable behind the existing retrieval port.
* A future authenticated API can translate identity at its outer boundary without
  moving identity logic into LangGraph or MCP.

Negative:

* Local development needs a PostgreSQL service and explicit migration/seed lifecycle.
* The new document corpus is not comparable to the frozen Markdown v2 retrieval corpus;
  v2 remains historical evidence and a separately frozen v3 dataset is required for the
  persistent corpus.
* RLS policies, roles, transaction context, and operational migration order require
  focused integration tests.

## Alternatives Considered

### Keep in-memory repositories and path-based document labels

Rejected. They do not provide persistence, reliable metadata, or a database-enforced
classification boundary.

### Filter classified records only in Python

Rejected. It creates a single bypassable enforcement point. Python filtering remains
defense in depth, while PostgreSQL RLS enforces row visibility independently.

### Make authorization an LLM or prompt concern

Rejected. LLMs are not trusted enforcement mechanisms.

### Store documents themselves as generic database blobs

Rejected for this slice. Files are the appropriate source assets, while PostgreSQL
catalogs their governed metadata. Blob retention and object storage are separate future
decisions.

### Build custom parsers per format

Rejected. Docling provides a local unified parser for the required formats.

## Relationship to Existing Decisions

ADR-003 keeps SQLAlchemy, PostgreSQL, Docling, and MCP as outer adapters. ADR-006 and
ADR-007 retain the retrieval and embedding ports; only their persistent classified input
changes. ADR-008 and ADR-009 remain the authorities for deterministic model routing and
model egress. ADR-010 and ADR-011 retain LangGraph orchestration and HITL ownership.
ADR-012 retains MCP as the discoverable service boundary, and ADR-013 retains FastAPI as
the external application boundary. This ADR introduces neither authentication nor a
durable agent checkpoint store.
