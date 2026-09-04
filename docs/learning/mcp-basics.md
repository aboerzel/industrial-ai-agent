# MCP Basics

## Purpose

The first MCP slice exposes the existing read-only factory capabilities through a local
`factory_mcp` server. The LangGraph read-only path now uses that server through a real
protocol client; the manual direct path remains a behavioral reference.

## Roles

An **MCP host** is the application that manages one or more MCP client connections. An
**MCP client** establishes one connection to a server, initializes the protocol, and
uses the server's advertised features. An **MCP server** publishes interoperable
capabilities. This project currently has a small official-SDK client and one local
server. The LangGraph MCP path is now an MCP host for one factory connection per agent
run; it does not have a multi-server multiplexer.

## Tools, Resources, and Prompts

MCP **tools** are callable operations with discoverable input schemas. `factory_mcp`
currently advertises exactly `get_product_history(product_id)` and
`get_machine_status(station_id)`. Their structured results retain identifiers,
found/not-found state, timestamps, machine states, and error codes.

MCP **resources** are addressable contextual data that a server can expose. MCP
**prompts** are server-provided prompt templates. They are protocol concepts only in
this slice: neither resources nor prompts are implemented.

## Discovery and Transport

The client first initializes an MCP session and lists the tools the server actually
advertises. It does not duplicate a static tool catalogue. The local smoke uses stdio:
the client launches the server as a child process and communicates over standard input
and output. This is a small, port-free local transport. Streamable HTTP is available in
the SDK but is deliberately deferred until remote deployment has a real requirement.

## LangGraph Tool Execution

For one asynchronous LangGraph MCP run, the adapter opens a stdio session, calls
`initialize()`, discovers tools, filters them through the explicit read-only
authorization set, and creates LangChain `StructuredTool` objects. The graph awaits
each tool sequentially through `ainvoke()`, then closes the session after its final
result. There is no `asyncio.run()` inside a graph node or tool handler; the CLI owns the
top-level event loop.

The small `mcp_langchain_tool_provider.py` module is a **TEMPORARY COMPATIBILITY
ADAPTER**. It translates only MCP name, description, input schema, invocation, and
structured result. It must be reviewed and removed when stable
`langchain-mcp-adapters` supports MCP SDK v2.

MCP discovery and agent authorization are separate: discovery observes everything the
server advertises, while the troubleshooting agent receives only its two authorized
read-only factory tools. Existing `create_maintenance_ticket` HITL behavior remains on
the direct path and is not an MCP tool.

## Security Boundary

MCP is not a model-egress boundary. The graph's model node continues to use the selected
profile through `EgressCheckedLLMClient`; ADR-009 still blocks confidential or restricted
context from public-cloud model profiles. The local factory MCP server does not authorize
model calls or cloud egress. Current tool results have no new classification contract in
this slice, so existing classification semantics are unchanged.

## OBSOLETE CANDIDATES AFTER MCP MIGRATION

Do not remove these yet. After the MCP path has replaced all intended direct consumers,
the later cleanup slice must review:

* the read-only closure implementations in
  `LangGraphTroubleshootingAgent._create_direct_tools()`;
* the direct read-only branch of `LangGraphTroubleshootingAgent._tool_node()`;
* direct `ProductHistoryCapability` and `MachineStatusCapability` construction in
  LangGraph-only composition roots.

The capabilities themselves, `factory_mcp`, the manual agent, and the approval action
are not obsolete candidates.

## MCP and Other Concepts

MCP is not a LangChain tool. An MCP server exposes protocol-level tools; a LangChain
adapter can later translate discovered tools into LangChain contracts. The current
`langchain-mcp-adapters` release is incompatible with MCP SDK v2 because it requires
`mcp<2.0`, so no such adapter is installed here.

MCP is not REST. REST commonly exposes application resources over HTTP paths, while MCP
standardizes AI-oriented capability discovery, tool schemas, and multiple transports.
Both can coexist when a system needs them.

MCP is not an agent. It does not select tools, reason about results, route models, or
enforce model egress. Existing capabilities retain their semantics, and ADR-008 and
ADR-009 remain responsible for model routing and security when a later agent integration
is introduced.
