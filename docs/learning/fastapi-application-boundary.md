# FastAPI Application Boundary

## Purpose

FastAPI is the external HTTP Application Boundary for the local/demo Industrial AI
Agent. It publishes the versioned public contract and generated OpenAPI without becoming
an agent framework, an MCP client, a model router, or an authorization decision maker.
Swagger UI is at `/docs` and OpenAPI is at `/openapi.json`.

The browser UI in `frontend/` is a separate static HTTP/JSON client. It neither imports
backend code nor selects a provider, model, MCP identity, classification, or permission.
The clearance selector is a demo simulation of an authenticated user's clearance. It is
not production identity-bound authorization: `user_clearance` supplies a demo context
only; a production adapter must derive `SecurityContext` from a verified identity.

## Current API Surface

The API intentionally exposes task and configuration boundaries, not underlying
capabilities or MCP tools:

| Route group | Current architectural purpose |
| --- | --- |
| `GET /health` | Process-local API liveness. Compose readiness remains a deployment concern. |
| `POST /api/v1/runs` | Create a server-classified free-form troubleshooting or recovery run. |
| `POST /api/v1/diagnostics` | Start the bounded, read-only INTERNAL diagnostic entry point. |
| `GET /api/v1/runs/{run_id}` | Retrieve one persisted run only when visible to the supplied demo clearance. |
| `GET /api/v1/investigations/{investigation_id}` | Retrieve the authorized visible history of an investigation. |
| `GET /api/v1/investigations/{investigation_id}/pdf` | Export that already authorized visible history as a PDF. |
| `GET /api/v1/documents/{document_id}` and `/download` | Open or download one currently authorized cataloged document. |
| `POST /api/v1/runs/{run_id}/resume` | Approve or reject a pending protected action and continue its persisted thread. |
| `GET /api/v1/models`, `/model-consumers`, `/model-assignments`; `PUT /api/v1/model-assignments` | Read catalog/configuration metadata and persist an operator model assignment. |

This is an architectural surface, not a replacement for generated OpenAPI. All public
schemas are Pydantic models with strict validation and project public projections rather
than LangGraph state, LangChain messages, MCP SDK values, provider SDK values, prompts,
raw tool payloads, or exceptions.

## Run and Investigation Lifecycle

```text
Browser or API client
  -> POST /api/v1/runs
  -> server-authoritative classification and security context
  -> persistent run/investigation record
  -> consumer + classification model resolution
  -> bounded LangGraph workflow and authorized MCP tools
  -> terminal public run projection, or waiting_for_approval
  -> authorized retrieval, investigation history, or PDF projection
```

Runs persist in the application lifecycle store; an investigation is an ordered grouping
of those runs, not a new authorization scope. A contextual, identifierless follow-up may
inherit only trusted, visible persisted context monotonically. An explicit higher target
escalates classification. Inaccessible prior context cannot be inherited, and unknown or
untrusted context falls back conservatively. Neither the user nor the model can lower
classification.

Direct run retrieval, investigation retrieval, PDF export, and document access evaluate
the current clearance before projection. Protected content is not made visible merely
because it was present in an earlier turn. PDF rendering receives the authorized persisted
investigation projection; it does not query broader data again. It preserves per-turn
language and user severity, renders trusted structured references, excludes inaccessible
higher-classification content, and sanitizes technical error details.

## Model Configuration and Egress

`config/model_catalog.toml` defines stable `model_id` values and model metadata. PostgreSQL
persists one assignment for each `(consumer_id, DataClassification)`. `MANUAL` assigns one
stable model ID. `AUTO` persists a ranking policy (`QUALITY_FIRST` or `COST_FIRST`) and
selects only among statically available, capability-compatible, security-eligible catalog
candidates before invocation. Both modes use the same hard guards.

```text
trusted DataClassification + consumer_id
  -> persistent MANUAL assignment or AUTO ranking policy
  -> ModelResolutionService and catalog lookup
  -> per-call capability validation
  -> security/egress authorization
  -> final provider-boundary capability and egress guard
  -> provider adapter
```

An assignment is configuration, never authorization. Missing compatible assignments,
capability mismatches, and security denials fail closed. Defaults create only missing
compatible assignments; explicit operator choices persist across restart and upgrade.
Provider availability, rate limits, timeouts, cost, and failures never cause automatic
provider fallback. The implemented specialized consumer is `rca.reasoning`; future
consumers must declare their call-level requirements. In particular, a `vision.vlm`
consumer requiring `VISION` is not compatible with `local_quality` unless the catalog
actually declares that capability.

## Durable HITL and Recovery

The official LangGraph PostgreSQL checkpointer persists a run's thread. A protected
maintenance or physical recovery action interrupts the graph and returns
`waiting_for_approval`. `POST /api/v1/runs/{run_id}/resume` accepts only `approve` or
`reject`; it checks authorization before atomically claiming the pending action, then
resumes the same thread with its persisted model and classification binding. A rejected
action never executes. Hardware recovery additionally performs deterministic fresh
precondition checks and post-action verification through `ClosedLoopRecoveryService`.

The demo records the approval clearance used for attribution, not a real authenticated
user identity. This is deliberately not production approval attribution. Authentication,
identity-bound authorization, TLS, and rate limiting remain production integration work.

## User Severity

`SUCCESS`, `ATTENTION`, and `FAILURE` are turn-local presentation semantics, separate
from HTTP status and persisted run status/error codes.

| Severity | Meaning |
| --- | --- |
| `SUCCESS` | A normally completed task. |
| `ATTENTION` | A bounded operational limitation, for example insufficient clearance, unavailable requested data, rate limiting, or unavailable/incomplete evidence. |
| `FAILURE` | A technical malfunction, for example an internal error, invalid model output, execution timeout, or MCP/protocol/database failure. |

Internal lifecycle states and error codes remain diagnostic evidence. They must not be
presented as an equivalent UX severity.

## Deployment and MCP Dependencies

The normal Compose stack is started from the repository root with:

```powershell
docker compose up --build -d
```

Core agent runtime dependencies are Factory MCP, Knowledge MCP, and Hardware MCP when a
recovery profile requires it. `agent-api` does not consume Runtime MCP, Observability MCP,
or RCA MCP. Runtime and Observability MCP are diagnostic/development services. RCA MCP is
a read-only development consumer surface (`analyze_run`), not an `agent-api` dependency
or an additional troubleshooting path.

Every deployed MCP readiness check is protocol-aware: it establishes a Streamable HTTP
session, performs MCP `initialize`, authenticates the session, calls `tools/list`, and
requires the service's declared bounded tools to be visible. It is not a TCP-port check.
Compose exposes the browser at `http://localhost:8080`, API/Swagger at
`http://localhost:8000/docs`, Grafana at `http://localhost:3000`, Langfuse at
`http://localhost:3001`, and Prometheus at `http://localhost:9090`.

## Validation

From the repository root, run backend tests with the configured project interpreter. For
frontend unit tests use `npm --prefix frontend test`. The expensive browser real-model
workflow is documented in [Browser E2E Journeys](browser-e2e-journeys.md); it is manual
regression work, not the normal development gate.

See [ADR-013](../decisions/ADR-013-fastapi-application-boundary.md) for the enduring
outer-adapter decision and its explicit current-state refinement.
