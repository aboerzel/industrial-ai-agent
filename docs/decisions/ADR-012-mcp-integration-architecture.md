# ADR-012: MCP Integration Architecture

**Status:** Accepted

## Context

The project has two established, read-only application capabilities:
`ProductHistoryCapability.get_product_history(product_id)` and
`MachineStatusCapability.get_machine_status(station_id)`. They currently run through
direct in-process calls. The target architecture anticipates independently exposed
factory, production, knowledge, and vision integrations, but no transport boundary has
yet been selected or implemented.

Model Context Protocol (MCP) is a long-lived interoperability and service-boundary
decision. It affects how capabilities are advertised, discovered, transported, tested,
and later consumed by an agent. It therefore needs an ADR before the first server is
introduced.

## Decision

Use the official MCP Python SDK v2 as the MCP protocol implementation. Do not implement
the protocol, discovery, schemas, or transports manually.

The first `factory_mcp` server is an Infrastructure adapter. It exposes exactly these
read-only tools:

* `get_product_history(product_id)` for historical production information.
* `get_machine_status(station_id)` for the current state of a station.

Tool handlers delegate to injected existing capabilities. Domain models, repository
ports, repositories, and capability semantics remain the source of truth; no business
logic or repository access is copied into MCP handlers. Tool responses use MCP's
structured-content support and preserve the capability result semantics, including IDs,
found/not-found status, timestamps, states, and error codes.

Clients must discover tools from the MCP server through the protocol. They must not keep
a separate static tool catalogue. A small official-SDK client demonstrates initialization,
tool listing, and calls. Tests use the SDK's in-process or in-memory test path where
available. The manual local smoke uses stdio, because it requires no listening port,
reverse proxy, or deployment configuration. Streamable HTTP remains a future deployment
choice, not a decision in this ADR.

`langchain-mcp-adapters` may adapt discovered MCP tools to LangChain tool contracts.
That adapter is an integration edge only. This slice does not connect MCP tools to
LangGraph, an LLM, or an agent.

MCP is transport and integration technology, not an authorization, egress, routing, or
agent framework. ADR-009 remains the authoritative model-egress boundary. The initial
tools are read-only and do not make public-cloud calls.

## Dependency Boundaries

```text
Domain repository ports and models
        ^
Application capabilities
        ^
factory_mcp Infrastructure server adapter
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
* Each future server remains an Infrastructure adapter over a bounded set of existing
  capabilities; service topology and deployment remain incremental decisions.
* Server and client lifecycle, protocol compatibility, and tool schemas receive focused
  deterministic integration tests.
* LangGraph integration, multi-server routing, Knowledge MCP, MCP authentication,
  remote deployment, write tools, resources, prompts, and MCP-based HITL are not
  decided or implemented by this ADR.
* A later agent integration must still apply ADR-008 routing and the final ADR-009
  egress check before any model call; MCP does not weaken those controls.
