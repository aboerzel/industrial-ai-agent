# MCP Basics

## Purpose

The MCP slices expose two read-only capability areas: `factory_mcp` for factory evidence
and `knowledge_mcp` for documentation retrieval. The LangGraph read-only path uses both
through real protocol clients; there is no direct read-only agent path.

## Roles

An **MCP host** is the application that manages one or more MCP client connections. An
**MCP client** establishes one connection to a server, initializes the protocol, and
uses the server's advertised features. An **MCP server** publishes interoperable
capabilities. This project has one official-SDK client infrastructure and two local
servers. The LangGraph MCP path holds one explicit connection per configured server per
agent run; it is not a generalized multi-server multiplexer or router.

## Tools, Resources, and Prompts

MCP **tools** are callable operations with discoverable input schemas. `factory_mcp`
currently advertises exactly `get_product_history(product_id)` and
`get_machine_status(station_id)`. `knowledge_mcp` advertises exactly
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
`8002`, and uses a one-shot migration/seed service. Factory uses PostgreSQL through its
non-superuser application role. Knowledge reads RLS-eligible `document_catalog` rows
and local multi-format assets through Docling before building the unchanged retrieval
pipeline. Knowledge contains no model artifact, uses the host's local Ollama endpoint
for `qwen3-embedding:0.6b`, and uses a persistent named Hugging Face cache volume for
`BAAI/bge-reranker-v2-m3`; CPU is the default. Local in-process execution
can use CUDA, while the Compose demo has no NVIDIA or Ollama-container requirement.
Docker is not MCP: Docker starts and isolates processes, whereas MCP defines discovery,
schemas, messages, and tool-call semantics. Internal Docker networking, an agent
container, TLS, and a reverse proxy are deferred.

## LangGraph Tool Execution

For one asynchronous LangGraph MCP run, the adapter opens every selected stdio or HTTP
session, calls `initialize()` and tool discovery once per server, rejects duplicate tool
names, filters tools through explicit read-only authorization sets, and creates LangChain
`StructuredTool` objects. The graph awaits each tool sequentially through `ainvoke()`,
then closes every session after its final result. There is no `asyncio.run()` inside a
graph node or tool handler; the CLI owns the top-level event loop.

The small `mcp_langchain_tool_provider.py` module is a **TEMPORARY COMPATIBILITY
ADAPTER**. It translates only MCP name, description, input schema, invocation, and
structured result. It must be reviewed and removed when stable
`langchain-mcp-adapters` supports MCP SDK v2.

MCP discovery and agent authorization are separate: discovery observes everything the
server advertises, while the troubleshooting agent receives only its authorized
read-only factory and knowledge tools. Existing `create_maintenance_ticket` HITL behavior
is action-only and is not an MCP tool.

## Security Boundary

MCP is not a model-egress boundary. The graph's model node continues to use the selected
profile through `EgressCheckedLLMClient`; ADR-009 still blocks confidential or restricted
context from public-cloud model profiles. A local HTTP connection to either container is
MCP service-network transport, not authorization to send factory or knowledge results to
`public_fast`. Knowledge MCP's documents, chunks, queries, embeddings, and reranker
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

The first Docker demo deliberately has no MCP authentication because it binds a local
host port for development. That is not a remote-deployment security model. Authentication
and transport security are required design work before any remote or production exposure.

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
enforce model egress. Existing capabilities retain their semantics, and ADR-008 and
ADR-009 remain responsible for model routing and security when a later agent integration
is introduced.
