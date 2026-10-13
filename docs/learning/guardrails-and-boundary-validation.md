# Guardrails and Boundary Validation

## Purpose

This slice hardens the existing FastAPI to LangGraph to MCP path without adding a
planner, agent, database, retrieval subsystem, or service boundary. A guardrail lives
at the boundary that owns the guarantee.

```mermaid
flowchart TD
    Input["INPUT: FastAPI/Pydantic"] --> Tool["TOOL INPUT: MCP SDK/Pydantic"]
    Tool --> Domain["DOMAIN: Value Objects and capabilities"]
    Domain --> Access["DATA ACCESS: PostgreSQL RLS + clearance"]
    Access --> Context["MODEL CONTEXT: classification defense in depth"]
    Context --> Egress["MODEL EGRESS: EgressCheckedLLMClient"]
    Proposal["Protected proposal"] --> HITL["LangGraph interrupt + persisted human decision"]
    HITL --> Guard["EXECUTION GUARD: permission + RLS + action/profile<br/>atomic bound single-use approval claim"]
    Tool --> Guard
    Guard -->|"ALLOW only"| SideEffect["Protected side effect"]
    Guard -->|"DENY"| Stop["No side effect"]
    Egress --> Output["OUTPUT: public response schema + sanitization"]
```

## Framework and Project Responsibilities

| Rule | Mechanism | Owner |
| --- | --- | --- |
| Unknown HTTP fields and enum values | FastAPI and Pydantic v2 `extra="forbid"` | Framework |
| MCP required fields, types, bounds, and extras | MCP SDK generated Pydantic argument models, configured strict | Framework configured at adapter boundary |
| Domain identifier validity | `ProductId` and `StationId` Value Objects | Project domain rule |
| Tool availability and read/write behavior | fixed `ToolPolicy` allowlist | Project authorization policy |
| Four executed calls maximum | LangGraph node routing plus `MAX_TOOL_CALLS` | Project orchestration policy required by ADR-004 |
| Protected execution | Shared capability guard: permission, resource clearance, action/profile, persisted single-use bound approval | Project execution boundary; graph and direct MCP |
| Approval UX and idempotency | LangGraph `interrupt()` plus server-injected run/action IDs | Framework plus project side-effect policy |
| Classified record visibility | PostgreSQL RLS and transaction-local clearance | Database |
| No over-clearance model context | classified result check before `ToolMessage`, then egress check | Defense in depth policy |
| Provider egress | `EgressCheckedLLMClient` | Project policy required by ADR-009 |
| Public response shape | FastAPI response model | Framework |
| Diagnostic leakage | public projection sanitizer | Project transport policy |

The MCP SDK has no public hook in version 2.1 for configuring the decorator-generated
argument model. The adapter therefore changes only that SDK Pydantic model's config and
republished JSON Schema. It does not implement a separate JSON-schema validator.

## Structured Output

Tool calls are already the structured model-decision contract: a name, call ID, and
schema-bound arguments. The graph admits one call and validates it before dispatch. No
second JSON planner is introduced.

The current final-output path supports a separate bounded structured normalization call
using `text` + `structured_output`; tool decisions use `text` + `tool_calling` separately.
ADR-019 validates capabilities per invocation, including incompatible combinations.
The API projects narrative `answer`, structured `investigation_steps`, and `next_steps`
alongside lifecycle and actual tool calls. Trusted observations and the ADR-020 evidence
ledger, not model prose, establish findings and evidence completeness. Structured output
does not authorize tools or replace deterministic output validation.

## Injection Boundary

Retrieved text can be useful evidence but has no authority. It reaches the model only as
a `ToolMessage` after a fixed system message and never becomes a system or developer
message. It cannot modify tool allowlists, operation metadata, classifications, model
profiles, providers, approval, limits, or RLS. The confidential synthetic service
comment `doc-1f0a9e2d8c4b7a61` demonstrates this with an instruction-like sentence: it
can be retrieved, but a ticket can only remain a proposal until an explicit resume with
`approve`.
