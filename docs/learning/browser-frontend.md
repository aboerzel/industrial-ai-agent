# Browser Frontend

## Purpose

`frontend/` is a small local demo client for the Industrial AI Agent. It is intentionally
implemented with HTML5, CSS, and ES modules rather than a JavaScript framework or a Node
build system. The repository's technical focus remains the agent, LangGraph, MCP services,
retrieval, and FastAPI.

The answer renderer uses the locally vendored, pinned `marked` GFM parser and DOMPurify.
`frontend/package.json` records their versions and the DOM test dependency. The production
browser never fetches them from a CDN. `npm run vendor:sync` from `frontend/` refreshes the
checked-in vendor assets after an intentional dependency update.

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
    js/markdown.js
    js/vendor/
    package.json
```

`js/api.js` is the only frontend module that knows the development API base URL, route
paths, `fetch`, JSON parsing, and HTTP error handling. It provides `createRun(message)`
and `getRun(runId)`. `js/app.js` owns DOM state and rendering only.
`js/markdown.js` owns rendering of untrusted agent-answer Markdown only; it neither changes
the API response nor any agent behavior.

Completed runs expose the bounded final-output projection `answer`, optional
`investigation_steps`, and optional `next_steps`. `answer` is narrative Markdown only.
`investigation_steps` is the ordered, structured record of completed tool observations:
the system derives each step number and canonical tool name from the actual successful
trajectory, while the bounded finding is finalized only from already-authorized tool
observations. The API persists the projection with the same run and returns it in
investigation history. The UI renders `investigation_steps` as a semantic HTML table; it
never repairs or infers a summary from Markdown.

`next_steps` remains the authoritative follow-up channel. The UI renders those strings as
editable follow-up actions directly and never infers them from Markdown headings or lists.
Selecting one only fills the composer. The subsequent submission remains a new,
independently authorized run. The final agent-output schema bounds both structured lists
and rejects duplicate action or investigation-summary sections in `answer`. Local profiles
that support JSON Schema normalize each successful final response through that schema before
persistence.

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
`POST /api/v1/runs` result, and renders the public run ID, status, narrative answer,
structured investigation summary, structured follow-up prompts, and normalized tool calls.
It does not poll or create a new request per
tool call.

The browser cannot choose a model, provider, execution zone, data classification, MCP
server, tool allowlist, or egress policy. The API continues to assign `CONFIDENTIAL`
server-side, and ADR-009 controls model egress independently from MCP network traffic.
The UI contains no secrets and must be treated as publicly visible client code.

Agent answers are untrusted. The renderer enables GFM features such as tables, permits only
an attribute-free `<br>` raw-HTML token so compact table cells can use line breaks, escapes
all other model-provided raw HTML, and sanitizes the generated result with a narrow DOMPurify
tag and attribute allowlist before it reaches `innerHTML`. Links open in a separate tab with
`noopener noreferrer`.
This UI-only presentation step does not change classifications, clearance, API contracts,
telemetry, model routing, or the agent loop.

When a response is `waiting_for_approval`, the UI renders the action, summary,
arguments, run ID, and status. It disables both decision buttons before calling the
resume API through `frontend/js/api.js`, so a double click cannot issue a second
browser action. The browser still cannot set classification, profile, provider, MCP
server, or egress policy. Streaming and authentication remain future work.
