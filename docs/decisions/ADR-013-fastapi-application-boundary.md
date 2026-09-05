# ADR-013: FastAPI Application Boundary

## Status

Accepted

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
exception handling, and generated OpenAPI documentation. Swagger UI at `/docs` is the
initial browser client; a dedicated browser UI remains a separate future client.

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

An injected, small application run service owns the troubleshooting use case. It creates
fixed `CONFIDENTIAL` `TaskRequirements`, invokes `DeterministicModelRouter`, constructs
the already-routed LangGraph execution through explicit Composition, and awaits the
MCP-backed run. FastAPI calls that service but does not call capabilities, retrievers,
MCP tools, routers, model adapters, or Docker services directly.

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
        +--> TaskRequirements -> DeterministicModelRouter
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

## Scope and Non-Decisions

This ADR does not introduce a browser application, SSE or WebSocket streaming, a HITL
resume API, a database, Redis, a durable LangGraph checkpointer, an agent Docker image,
authentication, authorization, TLS, CORS policy, rate limiting, remote production
deployment, or any new model, tool, retrieval, or MCP service.
