# ADR-013: FastAPI Application Boundary

## Status

Accepted, refined by implementation and ADR-019

The original decision and rationale below are retained as historical context. The
**Implementation Evolution / Current Refinement** section is authoritative for the
current executable boundary where it differs from the initial slice.

## Context

The troubleshooting path already has explicit Composition Roots, deterministic
task-level model routing, final model-egress enforcement, LangGraph orchestration, and
runtime-discovered MCP tools. CLI and smoke scripts invoke that path for development,
but do not provide a stable external application contract for another client.

The first HTTP boundary must expose agent runs without moving orchestration, MCP tool
semantics, model routing, classification, or egress policy into a web framework. It also
needs a stable run identity that can later support status, human approval, streaming,
and durable persistence without selecting those capabilities now.

## Decision

FastAPI is the external HTTP Application Boundary for the Industrial AI Agent. It uses
versioned `/api/v1` routes, Pydantic request and response schemas, FastAPI validation,
exception handling, and generated OpenAPI documentation. In the initial slice, Swagger
UI at `/docs` was the browser client and a dedicated browser UI was deferred.

The first API exposes a shallow run contract:

* `GET /health` reports only process-local API liveness.
* `POST /api/v1/runs` synchronously starts one troubleshooting run and returns its
  generated UUID, public status, final answer when available, and normalized tool calls.
* `GET /api/v1/runs/{run_id}` returns the durable public record or `404`, including a
  public approval request while the run is waiting.
* `POST /api/v1/runs/{run_id}/resume` accepts a Pydantic-validated `approve` or
  `reject` decision and resumes the persisted LangGraph thread without rerouting.

The API uses public Pydantic schemas. It must not expose LangChain messages, LangGraph
state, MCP SDK objects, provider SDK objects, prompts, or raw tool-result payloads. The
API owns conversion from project-owned `AgentRunResult` contracts to its public schema.

In the original slice, an injected small application run service owned the
troubleshooting use case. It created fixed `CONFIDENTIAL` `TaskRequirements`, invoked
`DeterministicModelRouter`, constructed the then-routed LangGraph execution through
explicit Composition, and awaited the MCP-backed run. That implementation is no longer
active; it is retained to explain the decision's starting point. FastAPI still does not
call capabilities, retrievers, MCP tools, model adapters, or Docker services directly.

The initial request does not accept a model, provider, profile, execution zone, or data
classification. Troubleshooting requests are conservatively classified as
`CONFIDENTIAL` server-side. ADR-009 remains fully binding before routing and immediately
before every provider-adapter call. API transport does not grant permission for public
model egress.

Each API run receives a UUID generated at the API boundary and uses it unchanged as its
LangGraph `thread_id`. The production composition requires PostgreSQL for the official
checkpoint store and the RLS-protected application run record; the in-memory store is
restricted to isolated API unit tests. The lifecycle includes `RUNNING`,
`WAITING_FOR_APPROVAL`, `SUCCESS`, `LIMIT_REACHED`, and `FAILED`.

Endpoints are asynchronous and await the application service and its LangGraph/MCP path.
They must not use `asyncio.run()` or create nested event loops. The existing
provider-independent LLM port remains synchronous until a separately justified change;
that fact does not permit the HTTP boundary to duplicate or bypass it.

The API returns no secrets, prompts, raw tool payloads, or stack traces. Validation uses
FastAPI's normal `422` contract. Unknown run IDs return `404`; no eligible model, MCP
unavailability, egress denial, and unexpected failures are mapped to stable sanitized
API errors. The local/demo API deliberately has no CORS wildcard, authentication,
authorization, TLS, or rate limiting. Any remotely reachable or production deployment
requires those controls in a future decision.

## Dependency Boundaries

```text
FastAPI routes and public schemas
        |
        v
Application run service / Composition Root
        |
        +--> [historical initial slice] TaskRequirements -> DeterministicModelRouter
        +--> LangGraphTroubleshootingAgent
                    |
                    v
              MCP Tool Provider -> Factory MCP / Knowledge MCP
```

FastAPI is an outer adapter. Domain models, capabilities, retrieval ports, agent
orchestration, routing policy, and egress policy must not depend on FastAPI. The API
schema is an external contract and is deliberately separate from LangGraph and MCP types.

## Alternatives Considered

### 1. Keep CLI and smoke entry points only

Rejected. They do not provide a versioned, discoverable HTTP contract for API clients or
a clean place for public request and response validation.

### 2. Expose capabilities or MCP tools as REST routes

Rejected. That would duplicate the MCP service boundary and allow a web client to bypass
the LangGraph troubleshooting path.

### 3. Put routing and egress policy in FastAPI dependencies

Rejected. They are deterministic Application policies that must remain usable and
enforced outside HTTP.

### 4. Add a browser application first

Rejected. Swagger/OpenAPI provides a suitable initial client without introducing a UI
stack or CORS policy before a concrete browser-client requirement exists.

### 5. Use FastAPI as a thin outer boundary over an application run service

Accepted. It adds a stable external contract while preserving established orchestration,
tool, routing, and security boundaries.

## Consequences

### Guardrail Clarification

Public API request, response, approval, and tool-call models forbid unknown fields.
FastAPI supplies the normal `422` contract for malformed requests and unknown resume
decisions. The response projection additionally sanitizes successful external text so
stack traces, connection strings, credentials, local paths, internal exception
representations, and checkpoint data cannot escape the public boundary.

Positive:

* API clients receive a versioned, validated, documented run contract.
* OpenAPI and Swagger UI offer immediate contract visibility and local interaction.
* A run UUID establishes a future-compatible handle for status, HITL, streaming, and
  persistence without selecting their implementations now.
* HTTP integration remains replaceable without changing LangGraph, MCP, Domain, or
  policy code.

Negative:

* Public schemas and error mappings require focused contract tests.
* In-memory records disappear when the API process ends and cannot support multi-worker
  or durable operation.
* A synchronous request/response endpoint cannot provide progress streaming or complete
  an interrupted HITL workflow yet.

## Relationship to Existing Decisions

ADR-003 governs the outer-adapter dependency direction. ADR-008 continues to own
deterministic model routing and ADR-009 owns classification and final egress enforcement.
ADR-010 keeps LangGraph as the sole troubleshooting loop, and ADR-011 remains the owner
of native checkpoint and interrupt semantics. ADR-012 keeps MCP as the discoverable tool
and service boundary; FastAPI neither replaces nor invokes MCP tools directly.

## Original Scope and Non-Decisions

The initial slice did not introduce a browser application, SSE or WebSocket streaming, a HITL
resume API, a database, Redis, a durable LangGraph checkpointer, an agent Docker image,
authentication, authorization, TLS, CORS policy, rate limiting, remote production
deployment, or any new model, tool, retrieval, or MCP service.

## Structured Internal Diagnostic Refinement

`POST /api/v1/runs` remains the original free-form contract and always resolves to the
server-owned `CONFIDENTIAL_TROUBLESHOOTING` profile. It accepts no classification,
clearance, profile, model, identity, or permission field.

`POST /api/v1/diagnostics` is a separate strictly structured contract with bounded
`product_id` and `station_id` identifiers and no free-form prompt. A deterministic
server policy verifies the target under INTERNAL RLS before it may resolve
`INTERNAL_DIAGNOSTIC`; unavailable targets receive a neutral response. FastAPI still
delegates to the application service and never selects an MCP credential itself.

## Implementation Evolution / Current Refinement

The externally visible FastAPI boundary remains an outer adapter, but the system now has
a static browser UI, PostgreSQL-backed run and investigation persistence, an official
LangGraph PostgreSQL checkpointer, and a protected resume endpoint. The public API also
serves authorized investigation retrieval, PDF export, cataloged-document access, and
model-catalog/assignment configuration. It remains intentionally distinct from MCP tool
transport and from provider adapters.

The historical `TaskRequirements -> DeterministicModelRouter` path is not the active
implementation. The current model execution flow is:

```text
request
  -> authoritative DataClassification / run classification policy
  -> persistent consumer + classification assignment
  -> MANUAL stable model_id or AUTO ranking policy
  -> ModelResolutionService and catalog lookup
  -> call-level capability guard
  -> security/egress guard
  -> final provider-boundary guard
  -> provider adapter
```

Model catalog, persistent assignments, consumer requirements, capability validation,
and egress authorization are distinct controls. An assignment never grants
authorization. `MANUAL` resolves the assigned stable `model_id`; `AUTO` ranks only
statically available, capability-compatible, egress-eligible candidates according to
its persisted policy. Neither mode falls back after provider unavailability, rate limits,
timeouts, or failures. Missing/incompatible assignments fail closed. Bootstrap defaults
create only missing compatible assignments, so explicit operator assignments survive
restart and upgrade. ADR-019 supersedes the routing-oriented selection design of ADR-008;
ADR-009 remains authoritative for classification and final egress authorization.

`POST /api/v1/runs` resolves classification server-side. Trusted visible persisted context
may be inherited monotonically for an identifierless follow-up; inaccessible context
cannot be inherited, an explicit higher target escalates, and unknown context remains
conservative. Direct run retrieval, investigation retrieval, PDF/document visibility,
and resume authorization all enforce the supplied demo clearance. Resume checks
authorization before `claim_resume`, then continues the same checkpointed thread with
the persisted model and classification binding. The demo records approval clearance, not
a real authenticated identity; production identity-bound authorization remains absent.

The deployed runtime uses Factory and Knowledge MCP for general troubleshooting and
Hardware MCP for the bounded recovery profile. Runtime and Observability MCP are
diagnostic/development services; RCA MCP is a read-only development consumer surface and
is not an `agent-api` dependency. Deployed MCP readiness is protocol-aware: authenticated
session establishment, `initialize`, `tools/list`, and required-tool visibility are all
required, rather than TCP reachability alone.
