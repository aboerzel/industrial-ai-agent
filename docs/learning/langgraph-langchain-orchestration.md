# LangGraph and LangChain Orchestration

## Historical Migration Note

The handwritten `TroubleshootingAgent` described below was a temporary learning and
migration reference. ADR-010's removal gate is complete: the implementation has been
removed, while its versioned evaluation datasets remain regression evidence for the
current LangGraph MCP path.

## Why Introduce the Frameworks Now?

The handwritten `TroubleshootingAgent` made the essential mechanics visible: model tool
calling, state progression, deterministic validation and dispatch, bounded iteration,
termination, and trajectory evaluation. Reimplementing more standard orchestration
infrastructure would now add less value than learning a production-relevant graph model.

[ADR-010](../decisions/ADR-010-langgraph-and-langchain-orchestration-migration.md)
therefore selected `LangGraphTroubleshootingAgent` as the final orchestration path after
deterministic tests, unchanged eval datasets, and live smokes demonstrated sufficient
equivalence.

## Graph State

`TroubleshootingGraphState` contains orchestration data only:

* LangChain conversation messages
* the number of successfully executed tools
* normalized executed tool calls
* the run status
* an optional final answer
* an optional pending action and its approval result
* the selected profile name and explicit run classification for resumable runs

Domain entities and repositories do not become graph state. A checkpointed local/test
run additionally uses LangGraph's native `InMemorySaver`; it is not durable persistence.

## Nodes and Edges

The read-only path uses two nodes:

1. The **model node** invokes the already selected model through the controlled client.
2. The **tool node** validates one requested call, invokes one discovered MCP tool, and
   appends a structured observation.

`START` enters the model node. A conditional edge routes a final answer, deterministic
error, or exhausted budget to `END`; exactly one valid tool request goes to the tool
node. The tool node returns to the model node. This edge cycle is the agent loop.

For the Factory-MCP `create_maintenance_ticket` write tool, the graph adds four focused
nodes. The action-preparation node validates and records a pending request without a
side effect. The approval node calls `interrupt()` with a JSON-serializable
`action_approval` payload. An approved resume reaches the MCP action-execution node;
rejection reaches the cancellation node and ends the run without executing the action.

## Tool Execution and Termination

LangChain `StructuredTool` instances are created from discovered, explicitly authorized
MCP schemas. They are transport adapters, not new homes for Domain logic. A custom tool
node is intentionally used to retain one-call validation and sequential dispatch.

`MAX_TOOL_CALLS = 4` applies to the remaining LangGraph agent. Four tools may execute,
including the approved maintenance action. The next model step may return a final
answer; a fifth request produces `LIMIT_REACHED`, is not executed, and causes no
further model call. If a local OpenAI-compatible provider returns multiple calls despite
`parallel_tool_calls=false`, the bounded loop admits only the first and discards the
rest before dispatch. Unknown tools and invalid arguments remain deterministic errors.

The MCP SDK's strict generated Pydantic schemas reject required-field, type, and unknown
additional-argument violations before a capability is invoked. LangChain's
`BaseTool.ainvoke()` performs the matching framework validation at the graph boundary;
the agent translates validation failures into its project-safe public error.

## What LangChain Provides

This slice depends directly on `langchain-core` for message and tool contracts. The
small `LLMClientChatModel` Infrastructure adapter translates those contracts to the
existing provider-independent `LLMClient` request and response models. It does not
create a provider, select a profile, or define security policy.

The full LangChain application framework is not adopted. Structured output may be used
later when an implemented capability needs it.

## What Remains Project-Owned

The project continues to own:

* Domain models, invariants, repositories, and capability semantics
* `DataClassification`, `ExecutionZone`, and `ModelEgressPolicy`
* the final `EgressCheckedLLMClient` boundary
* `TaskRequirements`, profile metadata, and `DeterministicModelRouter`
* tool budgets, argument validation, dispatch, and termination guarantees
* retrieval ports, eval datasets, ground truth, and deterministic scoring

The Composition Root performs security eligibility and task-level routing before it
constructs the graph path. It injects the selected `ModelProfile` and an
egress-controlled client. LangGraph performs neither autonomous model routing nor
fallback. The final pre-adapter egress check remains active for every model call.

## Checkpointing and Human Approval

[ADR-011](../decisions/ADR-011-agent-persistence-and-human-in-the-loop.md) adds a
bounded checkpoint and human-in-the-loop flow to the LangGraph MCP path. Production
uses LangGraph's official `AsyncPostgresSaver`; deterministic unit tests use native
`InMemorySaver`. A resumable invocation uses `{"configurable": {"thread_id": "..."}}`.
The `thread_id` identifies one graph run; the same identifier is required for
`Command(resume="approve")` or `Command(resume="reject")`.

`InMemorySaver` is restricted to deterministic tests. The FastAPI application runtime
uses `run_id == thread_id`, `AsyncPostgresSaver`, and a separate application/audit run
record, so a pending approval survives application recreation.

The stored graph representation contains only serializer-safe primitives and LangChain
messages. The agent restores project-owned result types at its public boundary, avoiding
checkpoint deserialization of project-specific Python objects.

The approval requirement is deterministic: read tools never interrupt, while
`create_maintenance_ticket` always requires approval. The LLM can propose an action but
cannot decide whether approval is required. Resume accepts only `approve` or `reject`.
An invalid resume is rejected before the action executes.

LangGraph may restart an interrupted node from its beginning on resume. Consequently,
code before `interrupt()` is side-effect-free, and the Factory-MCP call is in a separate
post-approval node. The MCP request receives the original model tool-call ID as its
idempotency key, and PostgreSQL protects against replay.

The checkpoint retains the already selected profile name and explicit classification.
Resume does not reroute, change classification, or introduce a cloud fallback. The
same final `EgressCheckedLLMClient` remains the model boundary.

## Manual Loop Compared with the Graph

The manual path expresses progression with a Python loop and explicit message-list
updates. The graph path represents progression as typed state, nodes, edges, and a
conditional route. Their internal message structures differ, so equivalence tests
compare observable behavior: status, executed tools and arguments, tool count, and final
answer presence.

The same first-decision and trajectory datasets run against both paths. Framework
migration does not justify changing their ground truth.

## Deliberately Deferred

The production graph discovers Factory and Knowledge MCP tools, normalizes a
`create_maintenance_ticket` proposal, and pauses with `interrupt()` before its first
side-effecting node. Resume uses the same checkpointed thread and an MCP request ID
derived from the original model tool-call ID. PostgreSQL unique constraints protect
replay. The former action-only graph and its direct capability injection have been
removed; MCP-Fake and PostgreSQL integration tests cover the retained guarantees.
