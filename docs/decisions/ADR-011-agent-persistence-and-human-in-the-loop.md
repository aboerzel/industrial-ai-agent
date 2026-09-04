# ADR-011: Agent Persistence and Human-in-the-Loop

## Status

Accepted

## Context

ADR-010 introduced a parallel LangGraph troubleshooting path but deliberately deferred
checkpointing, persistence, durable execution, and human-in-the-loop (HITL). A
troubleshooting agent that proposes a write action needs a deterministic pause before the
action can occur. It must preserve enough orchestration state to resume the same run,
without allowing an LLM, a framework default, or a retry to bypass approval, model
routing, or model egress policy.

This changes long-lived runtime behavior and establishes a future persistence boundary.
It is therefore an architectural decision rather than a local implementation detail.

## Decision

### Native LangGraph Checkpointing

The LangGraph path uses LangGraph's native checkpointer abstraction. Each resumable run
is identified by the native configuration shape:

```python
{
    "configurable": {
        "thread_id": "...",
    },
}
```

The same `thread_id` identifies a continuation of one run; different IDs isolate their
checkpoint histories. The first slice uses `InMemorySaver` only for deterministic tests
and local demonstrations. It loses all state when the process ends and is not a durable
production persistence decision.

No project-specific parallel thread, checkpoint, or polling abstraction is introduced.
Later durable storage remains an Infrastructure choice justified by operational
requirements.

Checkpointed graph state is restricted to serializer-safe primitives and LangChain
message contracts. Project value types are restored only at the agent's public result
boundary, so a checkpointer does not depend on project-specific object deserialization.

### Native Interrupt and Resume

An action requiring human approval pauses a graph node through LangGraph
`interrupt(payload)`. The payload is a JSON-serializable structured request with a
stable `kind`, action name, and only the details necessary for a person to decide.

The caller resumes the same `thread_id` with `Command(resume=...)`. The first slice
accepts only the explicit values `approve` and `reject`; invalid values fail
deterministically and do not execute the action. The agent must not implement its own
waiting loop around approval.

### Deterministic Approval Boundary

Approval requirements are deterministic capability policy, not an LLM judgment:

* Read capabilities `get_product_history` and `get_machine_status` execute normally.
* The action capability `create_maintenance_ticket` always requires approval.

The LLM may propose a known action through its existing tool-choice responsibility, but
it cannot decide whether that action needs approval. The first action is an in-memory
demonstration only; it does not call an external ticketing system or control equipment.

### Side Effects and Idempotency

LangGraph restarts an interrupted node from its beginning when it receives a resume
command. Therefore, code before `interrupt()` must be pure or idempotent. The approval
node only validates and constructs data before interrupting. The write action executes
only in a separate node after an approved resume.

The demonstration action uses the proposed tool-call ID as an idempotency key in its
in-memory repository. Replaying its execution node returns the same ticket rather than
creating a second one. Durable cross-process idempotency guarantees remain a later
production concern.

### Security and Model Routing

ADR-009 remains binding before every model call, including calls made after an approved
action. Checkpoints and resumes do not authorize egress, change data classification, or
create a cloud fallback. Sensitive state is not unnecessarily copied into interrupt
payloads or logs.

ADR-008 remains binding. The Composition Root selects the semantic Model Profile before
constructing a run. The selected profile and run classification are persisted as minimal
run context and must match when resuming. A resume never reroutes or upgrades a model.

### Scope

This ADR does not select a production checkpointer, persistent store, retention policy,
cross-process durability guarantee, web approval UI, external ticketing API, PLC action,
background workflow, LangSmith, MCP, multi-agent topology, subgraphs, or planner.

## Alternatives Considered

### 1. Keep all runs synchronous and do not support HITL

Rejected. It cannot safely demonstrate a meaningful action boundary or continuation.

### 2. Implement a project-specific checkpoint store and approval wait loop

Rejected. It duplicates LangGraph behavior, creates a second lifecycle abstraction, and
would make future framework integration harder to reason about.

### 3. Let the LLM decide whether approval is required

Rejected. Approval is deterministic safety and authorization policy; an LLM is not a
trusted enforcement mechanism.

### 4. Use native LangGraph checkpoints, `interrupt()`, and `Command(resume=...)`

Accepted. It directly expresses pause/resume semantics while retaining project-owned
policy, capabilities, routing, and egress enforcement.

### 5. Introduce a durable database-backed checkpointer immediately

Rejected for this slice. There is no demonstrated operational requirement for a
production storage backend, and choosing one now would prematurely establish persistence
infrastructure.

## Consequences

Positive:

* the graph can pause and continue a single run deterministically
* write actions are separated from read tools and require explicit approval
* action execution cannot occur before approval
* the project gains practical LangGraph checkpoint and interrupt experience
* durable persistence can later replace the in-memory adapter without changing the
  approval semantics

Negative:

* callers must retain and reuse `thread_id` for a continuation
* interrupted graph nodes need careful side-effect placement
* in-memory checkpoints disappear when the process exits
* the parallel LangGraph path gains lifecycle behavior not present in the manual
  reference path

## Relationship to Existing Decisions

ADR-003 keeps persistence adapters outside the Core and requires explicit composition.
ADR-004 continues to govern the bounded sequential tool behavior. ADR-005 requires
deterministic tests for approval, rejection, replay, and isolation. ADR-008 owns initial
deterministic model selection; ADR-009 owns security eligibility and final egress.
ADR-010 owns LangGraph orchestration migration; this ADR implements its deliberately
deferred checkpointing and HITL boundaries for the parallel path only.
