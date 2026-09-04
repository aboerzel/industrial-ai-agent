# MCP Basics

## Purpose

The first MCP slice exposes the existing read-only factory capabilities through a local
`factory_mcp` server. It demonstrates a real protocol client discovering and invoking
tools without involving an LLM or agent.

## Roles

An **MCP host** is the application that manages one or more MCP client connections. An
**MCP client** establishes one connection to a server, initializes the protocol, and
uses the server's advertised features. An **MCP server** publishes interoperable
capabilities. This project currently has a small official-SDK client and one local
server; it does not yet have an agent host or multi-server multiplexer.

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
