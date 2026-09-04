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
* A focused in-memory run lifecycle store for the local process.
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
    -> UUID + InMemoryAgentRunStore record
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
| `GET /api/v1/runs/{run_id}` | Read a local lifecycle record. |

`CreateRunRequest` accepts exactly one required non-empty `message`. It deliberately
does not accept model, provider, semantic profile, execution zone, or data
classification. The service sets troubleshooting requests to `CONFIDENTIAL`
server-side, so a client cannot downgrade the security context.

`RunResponse` exposes only `run_id`, public `status`, optional `answer`, and
normalized `tool_calls`. It excludes internal LangChain messages, LangGraph state, MCP
SDK values, provider SDK values, prompts, and raw tool-result payloads.

## Run Store and Future HITL

`InMemoryAgentRunStore` keeps `running`, `success`, `limit_reached`, or
`failed` records in the API process. It is intentionally not durable and loses every
record at process restart. It is neither a generic repository platform nor a production
persistence choice.

The UUID and lifecycle model permit a later `POST /api/v1/runs/{run_id}/resume` endpoint
for ADR-011 approval flows. This slice does not implement resume, streaming, database
persistence, or a durable checkpointer.

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
