# Browser Frontend

## Purpose

`frontend/` is a small, dependency-free local demo client for the Industrial AI Agent.
It is intentionally implemented with HTML5, CSS, and ES modules rather than a JavaScript
framework or a Node build system. The repository's technical focus remains the agent,
LangGraph, MCP services, retrieval, and FastAPI.

## Boundary

The browser is an untrusted external client. Its only integration is the versioned public
HTTP/JSON contract:

```text
Browser frontend
    -> FastAPI /api/v1
    -> TroubleshootingRunService
    -> model routing and egress policy
    -> LangGraph
    -> Factory MCP + Knowledge MCP
```

The frontend has no Python imports and no dependency on LangGraph, LangChain, MCP,
capabilities, repositories, model profiles, providers, Ollama, retrieval, or Docker.
FastAPI likewise does not render templates, host frontend assets, or contain UI logic.
This allows a later React, Vue, or other browser client to replace `frontend/` without
changing the agent backend.

## Structure

```text
frontend/
    index.html
    css/app.css
    js/api.js
    js/app.js
```

`js/api.js` is the only frontend module that knows the development API base URL, route
paths, `fetch`, JSON parsing, and HTTP error handling. It provides `createRun(message)`
and `getRun(runId)`. `js/app.js` owns DOM state and rendering only.

## Local Development

Start the MCP Docker services and local FastAPI API, then serve the frontend from a
separate origin:

```powershell
docker compose up --build -d factory-mcp knowledge-mcp
python -m industrial_ai_agent.infrastructure.agent_api
python -m http.server 8080 --directory frontend
```

Open `http://localhost:8080`. The default FastAPI entry point permits exactly this
development origin through CORS. Set `AGENT_FRONTEND_ORIGIN` when changing the local
frontend origin. Do not use a CORS wildcard; deployment-specific production origins need
an explicit security design.

## Run Lifecycle and Security

Submitting a request disables the button, displays `Running`, waits for the synchronous
`POST /api/v1/runs` result, and renders the public run ID, status, final answer, and
normalized tool calls. It does not poll or create a new request per tool call.

The browser cannot choose a model, provider, execution zone, data classification, MCP
server, tool allowlist, or egress policy. The API continues to assign `CONFIDENTIAL`
server-side, and ADR-009 controls model egress independently from MCP network traffic.
The UI contains no secrets and must be treated as publicly visible client code.

Future work may add streaming, HITL approval/resume, persistence, authentication, and a
production deployment only through separate scoped decisions.
