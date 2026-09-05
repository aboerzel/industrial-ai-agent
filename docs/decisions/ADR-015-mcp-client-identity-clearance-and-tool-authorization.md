# ADR-015: MCP Client Identity, Clearance, and Tool Authorization

## Status

Accepted

## Context

The Factory and Knowledge HTTP MCP composition previously injected one fixed,
unauthenticated `demo-engineer` `SecurityContext` with `CONFIDENTIAL` clearance.
Consequently, any client that could reach the local HTTP endpoint received the same
data visibility. Codex development access needs `INTERNAL` read-only access, while the
Industrial Agent retains `CONFIDENTIAL` read and approval-gated write access.

Identity, clearance, and permission answer different questions:

* Identity: who has been authenticated, for example `industrial-agent` or
  `codex-development`.
* Clearance: which data classification that identity may read, for example `INTERNAL`
  or `CONFIDENTIAL`.
* Permission: which MCP operation it may use, for example `READ_FACTORY`,
  `READ_KNOWLEDGE`, `READ_OBSERVABILITY`, or `CREATE_MAINTENANCE_TICKET`.

## Decision

The application Core defines transport-independent `McpClientIdentity`,
`McpPermission`, `McpAccessContext`, and `McpClientContextResolver`. An access context
contains a verified identity, the existing `SecurityContext`, and immutable server-owned
permissions. Clients never submit or select clearance or permissions.

The HTTP adapter authenticates the local demo with opaque bearer tokens from environment
variables. It maps the verified token to a fixed server-side identity and then resolves
identity to clearance and permissions. Missing, malformed, and unknown tokens fail
closed without returning token or identity details. `X-Client`, `X-Clearance`,
`X-Permissions`, and equivalent headers are not supported as authorization input.

Every HTTP MCP request resolves its own `McpAccessContext`. Tool discovery filters tools
by permission, and dispatch checks permission again before the handler executes.
Handlers create PostgreSQL repository adapters from the request-derived
`SecurityContext`; RLS remains the authoritative data boundary. The Factory composition
uses no mutable current-user state.

Knowledge retrieval builds a distinct pipeline cache entry for each complete
`SecurityContext`. Catalog retrieval and clearance filtering happen before document
parsing, embedding, indexing, reranking, and result construction. A higher-clearance
pipeline is never reused for a lower-clearance request.

The demo registrations are:

| Identity | Clearance | Permissions |
|---|---|---|
| `industrial-agent` | `CONFIDENTIAL` | `READ_FACTORY`, `READ_KNOWLEDGE`, `READ_OBSERVABILITY`, `READ_AGENT_RUNTIME`, `CREATE_MAINTENANCE_TICKET` |
| `codex-development` | `INTERNAL` | `READ_FACTORY`, `READ_KNOWLEDGE`, `READ_OBSERVABILITY`, `READ_AGENT_RUNTIME` |

MCP permission authorizes a client to invoke a tool. It does not replace the Industrial
Agent's `ToolPolicy` or LangGraph approval interrupt: maintenance-ticket execution still
requires an explicit approved resume after the model proposes the action.

Opaque bearer tokens are only the local demo authentication mechanism. A future
JWT/OIDC, mTLS, or workload-identity adapter may establish `McpClientIdentity` and use
the same resolver without changing Domain types, capabilities, repositories, RLS,
LangGraph, or HITL.

## Alternatives Considered

### Caller-provided identity or clearance headers

Rejected. A caller could claim `CONFIDENTIAL` or impersonate the Industrial Agent.

### Client-only Codex tool filtering

Rejected. Codex `enabled_tools` improves ergonomics but cannot stop a manually crafted
MCP `tools/call` request.

### Separate unauthenticated HTTP endpoints

Rejected for the current shared localhost topology. They are safe only when network
isolation makes the confidential endpoint unreachable to Codex.

### Full JWT/OIDC now

Deferred. It exceeds the current local-demo requirement. The resolver boundary makes it
a replaceable future adapter.

## Consequences

* HTTP MCP requires configured local tokens; stdio test composition remains explicit.
* Tokens are environment-only, are never persisted, logged, or included in errors.
* Codex can later receive only `INTERNAL` tools and data, even when it directly invokes
  MCP protocol methods.
* Observability MCP tool discovery and dispatch use the same server-derived permission
  model. Trace headers and telemetry fields remain unrelated to identity, clearance,
  and permissions.
* The local-demo token remains a shared-secret mechanism. A client able to obtain the
  Industrial Agent token can impersonate it; production requires stronger identity,
  secret distribution, TLS, and deployment isolation.

ADR-009 remains the model-egress policy, ADR-011 remains the HITL authority, ADR-012
remains the MCP transport decision, and ADR-014 remains the RLS and classification
authority.

## Runtime MCP Refinement

The read-only `runtime_mcp` uses the same request-scoped authentication, identity
resolution, permission filtering, dispatch authorization, and PostgreSQL RLS boundary.
`READ_AGENT_RUNTIME` authorizes its fixed read-only inspection tools. The local demo
grants it to `industrial-agent` at `CONFIDENTIAL` clearance and to
`codex-development` at `INTERNAL` clearance. Runtime-record classification remains
enforced by PostgreSQL RLS; neither an MCP argument nor a trace header can select a
clearance, identity, or permission. The server applies a separate output allowlist over
the RLS-filtered record, so access to a record never authorizes prompt, answer, tool
payload, approval payload, exception, or checkpoint disclosure.
