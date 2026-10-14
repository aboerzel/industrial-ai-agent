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
    -> Nginx same-origin /api/ gateway: proxy session cookie
    -> FastAPI /api/v1: canonical session identity -> clearance and roles
    -> TroubleshootingRunService
    -> model routing and egress policy
    -> LangGraph
    -> Factory MCP + Knowledge MCP
```

The frontend has no Python imports and no dependency on LangGraph, LangChain, MCP,
capabilities, repositories, model assignments, providers, Ollama, retrieval, or Docker.
FastAPI likewise does not render templates, host frontend assets, or contain UI logic.
This allows a later React, Vue, or other browser client to replace `frontend/` without
changing the agent backend.

## Structure

```text
frontend/
    index.html
    css/app.css
    js/api.js
    js/demo-auth.js
    js/app.js
    js/transcript-pdf.js
    js/markdown.js
    js/vendor/
    nginx.conf
    package.json
```

`js/api.js` owns investigation/document HTTP contracts and security-context generation.
`js/demo-auth.js` owns demo session requests and safe identity metadata; `js/app.js` owns
DOM rendering. Nginx proxies cookies and strips Authorization, never injecting secrets.
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

Set `DEMO_AUTH_MODE=true` in `.env`, then start `docker compose up --build -d` and open
`http://localhost:8080`. A fresh browser automatically starts as `demo-public`; existing
sessions survive refresh. The header account button always shows the current username.
Its menu shows clearance and roles, language selection, Switch user and Logout.
Switching and the user selection after logout never require typing a password.
Explicit credential testing remains available through the existing login API.
The separate header Configuration button is visible but disabled without MODEL_ADMIN,
with a permission explanation. Header controls are ordered Monitoring, Configuration,
Account. The Investigation toolbar contains only PDF and New Chat. Changing language preserves the session, investigation and existing
language preference; account labels follow the selected language. The menu closes on
outside click or Escape and supports keyboard opening and normal Tab navigation.
There is no Basic challenge or htpasswd provisioning. Disabled demo mode provides no
browser login/switch mechanism; direct authenticated bearer APIs remain available.

See [Demo Users and session security](demo-authentication.md) for the complete credential
table and intentional demo trust model. This is a loopback learning/demo system, not
production authentication. Switching to admin is intentionally permitted in demo mode;
admin still has PUBLIC clearance and cannot read restricted data through its role.

## Credential Ownership

| Credential/configuration | Owner and purpose | Browser visibility |
| --- | --- | --- |
| `DEMO_AUTH_MODE` | API enables the explicit local browser demo | Safe mode flag |
| `config/demo-users.toml` | Canonical predefined demo identities; intentionally public demo credentials | Only safe username/clearance/role metadata from auth APIs |
| Demo session cookie | API-owned bounded session registry | HttpOnly; no session ID in JSON/storage |
| `AGENT_API_MODEL_ADMIN_TOKEN` | Direct bearer API administration | Never in browser assets or gateway configuration |
| MCP bearer tokens, database/provider/telemetry credentials | Server-to-server infrastructure authentication | Never exposed |

DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION. The browser
credential exception applies only to the predefined identities; all other credentials
remain secret. Nginx strips incoming Authorization and proxies session cookies. Service
bearer clients use the direct API; browser identity is resolved server-side per request.

## Run Lifecycle and Security

Submitting a request disables the button, displays `Running`, waits for the synchronous
`POST /api/v1/runs` result, and renders the public run ID, status, narrative answer,
structured investigation summary, structured follow-up prompts, and normalized tool calls.
It does not poll or create a new request per
tool call.

The browser cannot choose a runtime model, provider, execution zone, data classification,
MCP server, tool allowlist, or egress policy. The Model Configuration dialog is a separate
administrative configuration surface: it loads the catalog, supported consumers, and
persisted assignments from the API. It displays catalog `display_name` values, while its
mutation payload uses only stable `model_id` values. Agent and currently supported
specialized consumers each show all four classifications. Security-ineligible models stay
visible but disabled; capability mismatches are warnings and never cause a fallback.

Saving creates an explicit persistent assignment only. The server remains authoritative and
rejects assignments forbidden by egress policy. Fresh-install bootstrap assigns local
`local_quality` to `agent` and `rca.reasoning` at all classifications; existing operator
choices persist (ADR-019). Missing
catalog references remain visibly unconfigured rather than being replaced. The API
continues to establish run classification server-side, and ADR-009 controls model egress
independently from MCP network traffic. The UI contains no secrets and must be treated as
publicly visible client code.

The PDF button is enabled exactly when visible exportable conversation content exists.
Persisted investigations continue to use the authorized server PDF route. When a request
fails before an investigation exists, the browser creates a transcript-only PDF locally.
That report contains only the visible user request and public agent or error text, and
explicitly states that no persisted Investigation ID exists. It does not infer or include
classification, tool calls, findings, recovery data, or other server-side metadata.

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
browser action. Browser requests remain same-origin and carry an HttpOnly demo session cookie, never a
service bearer token. Nginx strips Authorization and proxies cookies; FastAPI resolves
the canonical username, clearance and roles. The browser supplies no clearance input.
Quick switch intentionally selects any configured demo identity only in Demo Auth Mode;
MODEL_ADMIN remains orthogonal to data visibility. Identity switch/logout invalidates
request generations, aborts old requests, clears conversation/export/dialog state and
revokes Blob URLs before updating the session. A new principal starts a new investigation;
refresh/BFCache restores a saved reference only after matching the server identity and
reauthorizing it. Cross-tab session notifications contain no credentials and trigger the
same purge. Client cleanup complements backend authorization. Streaming and production
federated authentication remain outside this local demo.
