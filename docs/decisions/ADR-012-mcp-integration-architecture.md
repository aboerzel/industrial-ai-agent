# ADR-012: MCP Integration Architecture

**Status:** Accepted

## Context

The project has two established, read-only application capabilities:
`ProductHistoryCapability.get_product_history(product_id)` and
`MachineStatusCapability.get_machine_status(station_id)`. They currently run through
direct in-process calls. The target architecture anticipates independently exposed
factory, production, knowledge, and vision integrations. The initial implementation
used process-coupled stdio for local development and tests. The first independently
deployable service needs a network transport and a narrow container lifecycle without
changing the tool semantics.

Model Context Protocol (MCP) is a long-lived interoperability and service-boundary
decision. It affects how capabilities are advertised, discovered, transported, tested,
and later consumed by an agent. It therefore needs an ADR before the first server is
introduced.

## Decision

Use the official MCP Python SDK v2 as the MCP protocol implementation. Do not implement
the protocol, discovery, schemas, or transports manually.

Each MCP server is an Infrastructure adapter over one bounded, cohesive capability
area. The first two servers are `factory_mcp` and `knowledge_mcp`. `factory_mcp`
exposes these cohesive factory tools:

* `get_product_history(product_id)` for historical production information.
* `get_machine_status(station_id)` for the current state of a station.
* `create_maintenance_ticket(station_id, summary, request_id)` for an approved,
  idempotent local maintenance action.

`knowledge_mcp` exposes exactly `search_documentation(query, top_k=3)`. It delegates
to the existing documentation-search capability and its `KnowledgeRetriever` port; the
MCP handler does not own ingestion, chunking, embedding, fusion, or reranking logic.

Tool handlers delegate to injected existing capabilities. Domain models, repository
ports, repositories, and capability semantics remain the source of truth; no business
logic or repository access is copied into MCP handlers. Tool responses use MCP's
structured-content support and preserve the capability result semantics, including IDs,
found/not-found status, timestamps, states, and error codes.

Clients must discover tools from the MCP server through the protocol. They must not keep
a separate static tool catalogue. A small official-SDK client demonstrates initialization,
tool listing, and calls.

Every MCP server supports two official-SDK v2 transports over the same server instance
and tool definitions:

* stdio is retained for process-coupled local development and deterministic tests.
* Streamable HTTP is the deployment transport. The server runs at an externally
  configured host and port and exposes the SDK-managed `/mcp` endpoint.

Transport selection belongs only to a server or client Composition Root. Capabilities,
tool handlers, Domain models, agent orchestration, and tool contracts do not branch on a
transport. An HTTP client opens one stateful Streamable HTTP session for one agent run,
initializes it, discovers tools once, makes the sequential calls, and closes it after the
run. It does not create a session per tool call or add a connection pool.

The first deployable variants are slim Python 3.12 Docker images that contain only their
server runtime dependencies, run as non-root users, and start Streamable HTTP by
default. The local Compose demo maps a host port to each service. Docker is a deployment
and process-isolation mechanism, not part of MCP or a replacement for its protocol
semantics. Internal Docker networking, a reverse proxy, TLS, and an agent container
remain future work.

`langchain-mcp-adapters` may adapt discovered MCP tools to LangChain tool contracts.
That adapter is an integration edge only. Until it has a stable MCP SDK v2-compatible
release, the project-owned compatibility adapter remains the single bridge. It opens
every explicitly configured MCP client once per agent run, discovers each server's
advertised tools, and exposes only discovered, explicitly authorized tools to LangGraph.
Tool names must be unique across the configured servers; any duplicate name fails closed
before a tool is bound. The graph has no Docker, host, port, retriever, embedding-model,
or reranker knowledge.

MCP is transport and integration technology, not an authorization, egress, routing, or
agent framework. ADR-009 remains the authoritative model-egress boundary. An HTTP MCP
connection to a local container is service-network transport, not permission to send
tool data to a public model. The initial tools are read-only and do not make public-cloud
calls. Authentication is deliberately absent only for the local Docker demo; every
remote or production deployment requires an explicit authentication and transport
security design before exposure.

## Dependency Boundaries

```text
Domain repository ports and models
        ^
Application capabilities
        ^
factory_mcp / knowledge_mcp Infrastructure server adapters
        ^
MCP clients / LangChain MCP adapter
```

Concrete repositories and capabilities are assembled at an explicit Composition Root
and injected into the MCP server. MCP SDK and LangChain MCP types must not enter Domain,
repository ports, or capability result types.

## Alternatives Considered

### 1. Keep direct in-process capability calls only

This is the simplest current path but does not provide protocol-level discovery or an
interoperable service boundary for later clients.

### 2. Implement a bespoke JSON-RPC or HTTP protocol

This duplicates mature protocol, schema, discovery, and transport concerns while
reducing interoperability. It is rejected.

### 3. Expose REST endpoints first

REST is viable for application APIs, but MCP directly models discoverable AI tool
contracts and has compatible clients. It would add a second integration contract for
this use case.

### 4. Adopt the official MCP SDK v2 with a small server adapter

Chosen. It provides standardized tools, discovery, structured content, and supported
local transports while keeping the existing application capabilities intact.

### 5. Let LangGraph or LangChain own the server and tool semantics

Rejected. Framework tool objects cannot replace the capability boundary and would make
MCP availability dependent on a particular agent runtime.

## Consequences

* MCP becomes the standard external tool transport for deliberately exposed project
  capabilities.
* Each server remains an Infrastructure adapter over a bounded set of existing
  capabilities. Explicitly configured multi-server discovery is supported; generalized
  routing, multiplexing, and dynamic server selection remain incremental decisions.
* Server and client lifecycle, protocol compatibility, schemas, structured results, and
  stdio-to-HTTP transport equivalence receive focused deterministic integration tests.
* A Docker build and container smoke remain explicit local deployment checks rather than
  prerequisites for the regular unit-test suite.
* LangGraph integration uses the same discovered MCP tool path through an injected
  provider; it neither constructs a container nor bypasses egress control.
* Generalized multi-server routing, MCP authentication beyond the local demo, remote
  production deployment, write tools, resources, prompts, and MCP-based HITL remain out
  of scope.
* A later agent integration must still apply ADR-008 routing and the final ADR-009
  egress check before any model call; MCP does not weaken those controls.
