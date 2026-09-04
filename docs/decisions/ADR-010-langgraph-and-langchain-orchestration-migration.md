# ADR-010: LangGraph and LangChain Orchestration Migration

## Status

Accepted

## Context

ADR-004 deliberately introduced the troubleshooting loop as explicit Python. That
implementation made tool calling, state progression, deterministic dispatch, loop
limits, termination, and evaluation visible and testable. It has fulfilled that learning
purpose and remains a useful behavioral reference.

Further custom implementation of standard graph orchestration now provides less value
than learning and applying established production-oriented agent tooling. LangGraph
provides explicit state, nodes, edges, conditional routing, and an evolution path toward
durable execution. LangChain provides standard model, message, tool, and structured-data
integration primitives.

Adopting these frameworks changes a long-lived orchestration boundary and introduces
runtime dependencies. It must therefore be governed by an ADR rather than treated as a
local refactoring. The migration must preserve the Hexagonal Architecture, deterministic
security controls, model routing, domain capabilities, and evaluation baselines already
established by ADR-002, ADR-003, ADR-005, ADR-008, and ADR-009.

## Decision

### Incremental Parallel Migration

Troubleshooting orchestration will migrate incrementally to LangGraph. The existing
handwritten `TroubleshootingAgent` remains available as the manual reference path while
a parallel `LangGraphTroubleshootingAgent` is introduced. The manual path is not removed
until deterministic tests and model-dependent evaluations demonstrate sufficient
functional equivalence.

ADR-010 supersedes only ADR-004's choice to keep the orchestration mechanism entirely
handwritten and its deferral of an agent framework. ADR-004's behavioral guarantees
remain binding: one tool call per model decision, deterministic validation and dispatch,
at most three executed tools, one final model decision after the third tool, and no
execution of a requested fourth tool.

### LangGraph Responsibilities

LangGraph may own the parallel path's orchestration mechanics:

* typed graph state
* model and tool nodes
* fixed and conditional edges
* the sequential agent loop
* tool-execution flow
* deterministic termination flow

The first migration slice does not add checkpointing, persistence, durable execution,
human approval, or resume-after-interruption. Those capabilities require later evidence
and, where architectural boundaries change, later decisions.

### LangChain Responsibilities

LangChain Core may be used selectively for:

* chat message representations at the orchestration boundary
* tool definitions and argument schemas
* model/tool-call integration
* structured outputs when an implemented use case requires them

LangChain is not adopted as an application-wide framework. Framework types may exist in
the LangGraph orchestration path and its integration adapters, but must not leak into
Domain models, repository ports, capability contracts, security policy, retrieval ports,
or evaluation ground truth.

### Project-Owned Responsibilities

The following remain custom project architecture and are not delegated to framework
defaults:

* Domain models and invariants
* repository ports
* tool and capability semantics
* tool-name and argument validation
* deterministic sequential-dispatch and limit rules
* `DataClassification` and `ExecutionZone`
* `ModelEgressPolicy` and the final pre-adapter egress boundary
* `TaskRequirements` and `DeterministicModelRouter`
* semantic Model Profiles
* retrieval ports and provenance
* evaluation datasets, ground truth, and deterministic scoring

Framework convenience APIs may be used only when their behavior preserves these rules.
In particular, framework defaults for parallel tool calls, retries, fallback, or error
conversion must not silently weaken ADR-004, ADR-008, or ADR-009.

### Security and Model Routing

ADR-009 remains fully binding. Every model request from the graph must pass through the
existing final egress-controlled `LLMClient` path before any provider adapter call.
LangGraph and LangChain must not construct provider clients directly, select fallback
models, authorize egress, or send sensitive prompts, tool results, retrieval results, or
traces to an unapproved external service.

ADR-008 also remains binding. A Composition Root constructs explicit Task Requirements,
applies security eligibility through `DeterministicModelRouter`, and injects the selected
semantic Model Profile into the graph path. The graph does not construct a router or
choose a concrete provider or model.

### Tool Boundary

The initial graph exposes exactly the existing capabilities:

* `get_product_history`
* `get_machine_status`

LangChain tool objects are adapters over these capabilities. They own no Domain logic,
repositories, provider configuration, or security decisions. Tool arguments remain
validated deterministically before a capability is invoked, and the initial graph
executes at most one requested tool per model step.

### State Boundary

Graph state contains orchestration data only: conversation messages, executed-tool
count, normalized executed-tool records, run status, and final answer state. The selected
profile may be injected through the graph object or explicit invocation context rather
than serializing provider configuration into state. Domain entities and Infrastructure
SDK objects are not stored in graph state merely for convenience.

### Model Integration Boundary

The graph path continues to use the provider-independent `LLMClient`. A small
LangChain-compatible adapter may translate LangChain messages and tool contracts to the
existing internal `LLMRequest`/`LLMResponse` models. It belongs at the orchestration and
Infrastructure integration boundary and must call the injected egress-checked client.

The graph must not instantiate `ChatOpenAI`, Ollama, Groq, or another provider-specific
client directly. There is one Model Profile configuration and one egress policy, not a
parallel framework-specific configuration system.

### Evaluation and Removal Gate

ADR-005 applies. Both paths use the same versioned first-decision and trajectory
datasets and the same deterministic scorers. Internal framework message identity is not
part of equivalence. Relevant comparisons are:

* selected tool and arguments
* executed-tool sequence
* tool-call count
* result status and termination
* presence of a final answer
* identical security and egress enforcement

The manual orchestration may be removed only in a separate change after:

* deterministic unit tests pass for both paths
* first-decision evaluations show no unacceptable regression
* trajectory evaluations show no unacceptable regression
* relevant local and explicitly public smoke tests pass
* a denied model request cannot reach the provider adapter in either path
* tool sequences, limits, and termination are sufficiently equivalent

### Scope and Non-Decisions

This ADR does not select or introduce:

* a LangGraph persistence or checkpoint backend
* an external state store
* LangSmith or another tracing platform
* MCP
* multi-agent orchestration
* Planner/Executor architecture
* distributed execution or queues
* dynamic tool discovery
* semantic or hybrid retrieval integration
* graph subgraphs
* automatic model routing, escalation, retry, or fallback

## Alternatives

### 1. Keep the handwritten loop indefinitely

Rejected as the sole forward path. It preserves transparency but continues to spend
project effort on standard orchestration mechanics and does not build practical
LangGraph/LangChain experience.

### 2. Replace the manual path immediately

Rejected. A big-bang replacement would remove the behavioral reference before tests and
evaluations demonstrate equivalence and would make framework-specific regressions harder
to isolate.

### 3. Introduce a parallel LangGraph path with narrow LangChain use

Accepted. It permits direct comparison, keeps deterministic policies project-owned, and
allows framework adoption to be validated before removal of the reference path.

### 4. Use a high-level prebuilt agent for all orchestration

Rejected for the initial migration. Framework defaults may permit parallel calls,
retries, or termination behavior that differs from ADR-004, and could hide the security
and routing boundaries that must remain explicit.

### 5. Move Domain, tools, routing, and security into LangChain abstractions

Rejected. It would let integration technology dominate the Domain and Application
architecture, weaken provider independence, and make critical deterministic policies
dependent on framework behavior.

## Consequences

Positive:

* the project gains practical LangGraph and LangChain experience on an already measured
  use case
* graph state and control flow become explicit framework concepts without obscuring
  project security or domain semantics
* manual and graph paths can be compared using unchanged evaluations
* future checkpointing and interruption support have a compatible orchestration base
* provider, routing, and egress boundaries remain reusable

Negative:

* both orchestration paths must be maintained temporarily
* LangGraph and LangChain Core become runtime dependencies
* message and tool conversion introduces an additional adapter boundary
* framework upgrades can affect orchestration behavior and require regression testing
* equivalence is behavioral rather than equality of internal state representations

## Relationship to Existing Decisions

ADR-002 remains valid: graph orchestration uses `LLMClient` and semantic Model Profiles,
not concrete provider clients. ADR-003 remains valid: framework integration stays out of
Domain and Infrastructure is injected at Composition Roots. ADR-005 supplies the tests
and unchanged evaluation baselines. ADR-008 owns deterministic model routing. ADR-009
owns security eligibility and final pre-adapter egress enforcement.

ADR-010 partially supersedes ADR-004 only for the chosen orchestration technology. The
bounded sequential behavior and deterministic guarantees of ADR-004 remain the required
contract during migration.
