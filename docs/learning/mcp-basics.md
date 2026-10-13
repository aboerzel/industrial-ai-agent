# MCP Basics

## Purpose

The normal LangGraph evidence path uses `factory_mcp` and `knowledge_mcp` through protocol
clients. Factory also exposes a protected maintenance action. The dedicated recovery
path uses Hardware MCP; Runtime, Observability, and RCA MCP are separate read-only
diagnostic services. See [ADR-012](../decisions/ADR-012-mcp-integration-architecture.md)
and the [Architecture Overview](../architecture/overview.md).

## Roles

An **MCP host** is the application that manages one or more MCP client connections. An
**MCP client** establishes one connection to a server, initializes the protocol, and
uses the server's advertised features. An **MCP server** publishes interoperable
capabilities. This project has one official-SDK client infrastructure and six deployed
servers. The LangGraph MCP path holds one explicit connection per configured server per
agent run; it is not a generalized multi-server multiplexer or router.

## Tools, Resources, and Prompts

MCP **tools** are callable operations with discoverable input schemas. `factory_mcp`
advertises bounded station/product discovery and overview, product history, machine
status, ticket retrieval, and protected ticket creation. The canonical Factory tool
contracts are listed in ADR-012; do not infer a fixed read-only catalogue from this example.
`knowledge_mcp` advertises exactly
`search_documentation(query, top_k=3)`. Its result preserves the normalized query and
results with a one-based `rank`, stable `chunk_id`, `document_id`, relative `source`,
score, and provenance metadata. No framework document or vector-store object crosses
MCP.

MCP **resources** are addressable contextual data that a server can expose. MCP
**prompts** are server-provided prompt templates. They are protocol concepts only in
this slice: neither resources nor prompts are implemented.

## Discovery, Transport, and Docker

The client first initializes an MCP session and lists the tools the server actually
advertises. It does not duplicate a static tool catalogue. Both servers support the same
tool definitions and protocol semantics through two official SDK v2 transports:

* **stdio** is process-coupled: the client launches the local server as a child process
  and communicates through standard input and output. It stays useful for development
  and deterministic tests because it needs no listener or port configuration.
* **Streamable HTTP** is networked: each server owns a listener and exposes `/mcp`; a
  client connects to its configured URL. It is the deployment path for both services.

The server's Composition Root selects `stdio` or `streamable-http`; the capabilities,
handlers, Domain, and agent orchestration do not contain transport conditionals. The
HTTP client uses the official `streamable_http_client(url)` API together with the same
`ClientSession` used by stdio. For a single agent run it initializes once, discovers
once, performs all sequential calls on that session, and closes it afterwards. This
slice deliberately has no session-per-call behavior or connection pool.

Docker packages each networked server as a reproducible, non-root Python 3.12 service.
The local `compose.yaml` adds PostgreSQL, maps factory port `8001` and knowledge port
`8002`. Factory runs migration/seed bootstrap before opening its MCP listener and Knowledge
waits for its health check; there is no current one-shot migration service. Factory uses PostgreSQL through its
non-superuser application role. Knowledge reads RLS-eligible `document_catalog` rows
and local multi-format assets through Docling before building the unchanged retrieval
pipeline. Knowledge contains no model artifact, uses the host's local Ollama endpoint
for `qwen3-embedding:0.6b`, and uses a persistent named Hugging Face cache volume for
`BAAI/bge-reranker-v2-m3`; CPU is the default. Local in-process execution
can use CUDA, while the Compose demo has no NVIDIA or Ollama-container requirement.
Docker is not MCP: Docker starts and isolates processes, whereas MCP defines discovery,
schemas, messages, and tool-call semantics. Compose already includes internal networking,
Agent API, and the authenticated Nginx browser gateway; TLS and production identity remain deferred.

## LangGraph Tool Execution

For one asynchronous LangGraph MCP run, the adapter opens every selected stdio or HTTP
session, calls `initialize()` and tool discovery once per server, rejects duplicate tool
names, filters tools through the server-owned run/tool policies, and creates LangChain
`StructuredTool` objects. The graph awaits each tool sequentially through `ainvoke()`,
then closes every session after its final result. There is no `asyncio.run()` inside a
graph node or tool handler; the CLI owns the top-level event loop.

The small `mcp_langchain_tool_provider.py` module is a **TEMPORARY COMPATIBILITY
ADAPTER**. It translates only MCP name, description, input schema, invocation, and
structured result. It must be reviewed and removed when stable
`langchain-mcp-adapters` supports MCP SDK v2.

MCP discovery and agent authorization are separate: discovery observes everything the
server advertises, while the troubleshooting agent receives only its fixed authorized
tools. `AgentRunClassificationPolicy` selects the bounded profile's admitted set;
ADR-020 further restricts tools to eligible evidence sources while requirements are
incomplete. `READ`, side-effect-free `PREPARE`, and protected execution are distinct.
A discovered tool is never authorized merely because it is advertised.

## Strict Tool Contracts and Write Proposals

The MCP SDK validates tool inputs with its generated Pydantic models before a capability
is called. SDK 2.1 exposes no public decorator parameter for that model configuration,
so the Infrastructure adapter configures the generated model as strict and
`extra="forbid"` and republishes its JSON Schema. The published schema therefore uses
`additionalProperties: false`, required fields, strict primitive types, and supported
constraints. The temporary LangChain bridge rejects a discovered schema that is not an
object with `additionalProperties: false`; it retains only the supported Pydantic
constraints instead of implementing a second JSON-schema validator.

`create_maintenance_ticket` has two deliberately different contracts. Its published MCP
execution schema requires `station_id`, `summary`, `request_id`, and `run_id`. The model receives
only the proposal schema (`station_id`, `summary`), so it cannot supply or replace the
idempotency key. After a native LangGraph approval resume, the execution node injects
the actual tool-call ID as `request_id` and the persisted `run_id`. The executing capability
validates and atomically consumes its authoritative approval before any side effect;
direct authenticated MCP calls reach the same guard. IDs are references, not proof of approval.

## Security Boundary

MCP is not a model-egress boundary. The graph's model node continues to use the selected
profile through `EgressCheckedLLMClient`; ADR-009 still blocks confidential or restricted
context from disallowed public-cloud models. A local HTTP connection to either container is
MCP service-network transport, not authorization to send factory or knowledge results to
the selected egress-eligible cloud profile. Knowledge MCP's documents, chunks, queries,
embeddings, and reranker
inputs stay local: Ollama is local and the cross-encoder loads only from its local cache.
MCP does not authorize model calls or cloud egress. ADR-014 additionally propagates
classification from PostgreSQL rows and catalog documents to chunks and structured MCP
results. Retrieval filters above-clearance catalog entries before parsing, embedding, or
reranking; PostgreSQL RLS independently enforces the same row-level limit for the
application database role.

At first container startup, Docling/RapidOCR and the reranker can fetch their public
model artifacts into local runtime caches. This bootstrap is not factory-data egress:
no document content, query, chunk, embedding, or reranker input is uploaded. A
deployment with fully pre-provisioned artifacts can disable that initial network need.

Current HTTP MCP authenticates environment-only opaque bearer tokens and resolves a
server-side identity, clearance, and capability permission (ADR-015). Discovery and
invocation both enforce permissions, with RLS/run visibility and protected-action claims
additionally applied at resource/execution boundaries. PUBLIC principals are read-only.
stdio development/tests inject explicit contexts; they do not establish HTTP authority.
Loopback binding is deployment isolation, not authentication. Remote/production exposure
still requires stronger identity, TLS, and secret distribution.

Query text has no authoritative classification in the current Knowledge MCP arguments.
HTTP and stdio therefore use conservative `RESTRICTED`, independently of caller clearance.
Document batches inherit their maximum authoritative chunk classification. Both reach
the embedding provider guard before SDK access, with only explicitly approved local
Ollama destinations and no environment proxy/redirect forwarding (ADR-019). DENY makes
zero provider calls.

## OBSOLETE CANDIDATES AFTER MCP MIGRATION

The cleanup classification is:

* **REMOVED:** the handwritten `TroubleshootingAgent`, direct Factory closures, the
  direct read-only LangGraph branch, and their composition roots, tests, eval switches,
  and smoke script. The LangGraph MCP path replaces them.
* **REMOVED:** direct Knowledge tool closures and direct retriever injection in
  LangGraph composition roots. Knowledge retrieval remains behind `knowledge_mcp`.
* **KEEP TEMPORARILY:** stdio-only helpers; stdio remains an intentional development/test
  transport, not historical code.
* **KEEP FOR UNIT TESTS / DEVELOPMENT FALLBACK:** the in-memory Factory repositories.
  Production and integration composition roots use PostgreSQL; the in-memory adapters
  keep deterministic unit tests and local stdio development independent of PostgreSQL.
* **BLOCKED BY FRAMEWORK:** `mcp_langchain_tool_provider.py`; it is the single temporary
  MCP SDK v2 to LangChain bridge until a stable compatible adapter exists.

## MCP and Other Concepts

MCP is not a LangChain tool. An MCP server exposes protocol-level tools; a LangChain
adapter can later translate discovered tools into LangChain contracts. The current stable
`langchain-mcp-adapters` release is `0.3.2` and requires `mcp<2.0.0`. The project uses
MCP SDK v2, so it retains one narrow compatibility bridge.

MCP is not REST. REST commonly exposes application resources over HTTP paths, while MCP
standardizes AI-oriented capability discovery, tool schemas, and multiple transports.
Both can coexist when a system needs them.

MCP is not an agent. It does not select tools, reason about results, route models, or
enforce model egress. Existing capabilities retain their semantics; ADR-019 governs
current model selection and ADR-009 governs security. ADR-008's profile router is historical.
