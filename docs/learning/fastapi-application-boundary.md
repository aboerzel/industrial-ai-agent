# FastAPI Application Boundary

## Purpose

FastAPI is the external HTTP Application Boundary for the local/demo Industrial AI Agent.
It provides a versioned API contract and generated OpenAPI documentation without becoming
an agent framework, tool protocol, routing policy, or security control.

Swagger UI at `/docs` remains the generated contract explorer. The separate static
browser UI in `frontend/` is an HTTP/JSON client of this API, not a FastAPI template or
an agent-runtime component.

## Responsibilities

FastAPI owns:

* HTTP routing, input validation, response serialization, and sanitized error responses.
* Public Pydantic API schemas.
* UUID generation for API run IDs.
* Delegation to a focused PostgreSQL-backed application run lifecycle store.
* OpenAPI and Swagger UI publication.
* A locally configured explicit CORS allowlist for the separate browser development
  origin.

FastAPI does not own:

* tool discovery or direct tool calls;
* factory or knowledge capabilities, repositories, retrieval, embeddings, or reranking;
* model/provider selection, model names, execution zones, or egress authorization;
* LangGraph state, tool-loop limits, checkpoint semantics, or HITL decisions;
* browser rendering, templates, static asset hosting, or frontend UI logic;
* Docker lifecycle or MCP service deployment.

## Request Lifecycle

```text
POST /api/v1/runs
    -> FastAPI validates CreateRunRequest
    -> UUID + PostgreSqlAgentRunStore record in agent_runtime
    -> TroubleshootingRunService
    -> CONFIDENTIAL TaskRequirements
    -> DeterministicModelRouter
    -> LangGraphTroubleshootingAgent
    -> MCP Tool Provider
    -> Factory MCP + Knowledge MCP
    -> EgressCheckedLLMClient
    -> AgentRunResult
    -> public RunResponse
```

The endpoint is `async` and awaits the application service and the existing
LangGraph/MCP path. It does not call `asyncio.run()` or create a nested event loop.
The currently provider-independent `LLMClient` has a synchronous provider call; that
existing inner boundary remains unchanged in this slice.

## Public Contract

The initial routes are:

| Route | Purpose |
| --- | --- |
| `GET /health` | Process-local API liveness. |
| `POST /api/v1/runs` | Start one confidential troubleshooting run. |
| `GET /api/v1/runs/{run_id}` | Read a persistent lifecycle record. |

`CreateRunRequest` accepts exactly one required non-empty `message`. It deliberately
does not accept model, provider, semantic profile, execution zone, or data
classification. The service sets troubleshooting requests to `CONFIDENTIAL`
server-side, so a client cannot downgrade the security context.

`RunResponse` exposes only `run_id`, public `status`, optional `answer`, and
normalized `tool_calls`. It excludes internal LangChain messages, LangGraph state, MCP
SDK values, provider SDK values, prompts, and raw tool-result payloads.

## Run Store and Future HITL

`PostgreSqlAgentRunStore` keeps `running`, `waiting_for_approval`, `success`,
`limit_reached`, or `failed` records in `agent_runtime.agent_runs`. It is a narrow
SQLAlchemy 2.x adapter and not a generic repository platform. The row persists the
run/thread UUID, effective classification, selected model profile, normalized tool-call
summary, sanitized errors, and lifecycle timestamps. PostgreSQL RLS remains the database
boundary; the ORM is mapping/query composition, not authorization enforcement.

The UUID and lifecycle model permit a later `POST /api/v1/runs/{run_id}/resume` endpoint
for ADR-011 approval flows. LangGraph checkpoints are persisted separately with the
official `AsyncPostgresSaver` in its framework-managed schema. This slice does not yet
publish a resume, streaming, or approval HTTP endpoint.

## Auth-ready Classification Context

ADR-014 introduces a provider-independent `SecurityContext` with `subject_id`, roles,
clearance, and `authenticated`. The current API still injects the unauthenticated local
`demo-engineer` context server-side; no request field can lower its clearance or choose
a model. A future JWT/OIDC boundary belongs in FastAPI and must translate a verified
identity into this existing structure before application, MCP, and PostgreSQL access.
The LangGraph agent remains unaware of authentication mechanics.

## Error and Security Boundary

FastAPI preserves deterministic inner policy decisions:

* invalid request schemas use FastAPI/Pydantic `422`;
* unknown runs return a sanitized `404`;
* `NoEligibleModelError` returns `503`;
* `ModelEgressDeniedError` returns `403` and does not authorize a fallback;
* unavailable MCP services return `503`;
* unexpected failures return a generic `500`.

Public errors contain a stable code and safe message only. They do not expose stack
traces, secrets, prompts, or raw tool results.

MCP's local network transport is independent from model egress. Factory and Knowledge
MCP may run in Docker, while ADR-009 still requires the final local-only egress check for
a confidential troubleshooting run. The API uses no CORS wildcard. Its local entry point
permits only `http://localhost:8080` by default; `AGENT_FRONTEND_ORIGIN` can provide one
explicit replacement origin for a changed local deployment. Production origin policy
must be configured with the real browser client and its authentication, authorization,
TLS, and rate-limiting controls. The API remains local/demo only and has no
authentication, authorization, TLS, rate limiting, remote deployment, or agent container
in this slice.

## OpenAPI

FastAPI derives OpenAPI and Swagger UI from the public Pydantic schemas and route
declarations. The contract is available at `/openapi.json`; Swagger UI is at `/docs`.
Tests assert that this schema exposes the public run models rather than internal agent or
MCP types.

## Local Usage

Start the two MCP services, then run:

```powershell
python -m industrial_ai_agent.infrastructure.agent_api
```

The default API address is `http://127.0.0.1:8000`. The Composition Root defaults to
Streamable HTTP MCP endpoints at ports `8001` and `8002`; `AGENT_MCP_TRANSPORT=stdio`
retains the development/test transport.

For the separate browser client, run:

```powershell
python -m http.server 8080 --directory frontend
```

Then open `http://localhost:8080`. The frontend sends only public run requests and reads
public run responses; it cannot select a model, provider, MCP server, or data
classification.

See [ADR-013](../decisions/ADR-013-fastapi-application-boundary.md) for the durable
boundary decision.

## Durable Resume Contract

`RunResponse` represents `waiting_for_approval` with a public approval request.
`POST /api/v1/runs/{run_id}/resume` accepts a Pydantic-validated
`ResumeRunRequest { decision: approve | reject }`. Invalid decisions receive `422`,
unknown IDs receive `404`, and a run that is no longer waiting receives `409`.

## Strict Public Projection

All public request, response, approval, and normalized tool-call contracts are Pydantic
v2 models with `extra="forbid"`. FastAPI therefore rejects unknown request fields and
invalid `ResumeDecision` values with its normal `422` response before a run is started
or resumed. The public request cannot name a model, provider, profile, execution zone,
classification, tool, or idempotency key.

Successful responses are also a security boundary. The API projects only the public
run ID, lifecycle status, final text, normalized executed calls, and a pending approval
summary. It never serializes LangGraph checkpoints, message state, MCP objects, raw tool
payloads, prompts, or exceptions. Before projection, strings resembling stack traces,
database URLs, credential assignments, local paths, or checkpoint data are replaced by a
safe generic result. This is defense in depth; inner failures already map to stable API
errors.
