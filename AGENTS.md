# AGENTS.md

## Project

This repository contains the **Industrial AI Agent** learning and portfolio project.

The project is designed to build production-oriented Agentic / Applied AI engineering skills through a realistic industrial use case.

The system should evolve incrementally from simple LLM tool calling toward a distributed architecture with multiple MCP servers, retrieval, persistent state, evaluations, observability, guardrails, and human approval.

The project is both:

* a hands-on learning project
* a production-oriented reference architecture
* a portfolio project for Senior AI / Agentic AI / Applied AI roles

---

## Core Scenario

The system represents an industrial troubleshooting and operations agent.

Typical user requests include:

* Why was product P4711 rejected?
* What is the current status of station S04?
* Are several products failing with the same error?
* Find relevant technical documentation.
* Analyze an inspection result.
* Suggest likely root causes.
* Propose maintenance actions.

The agent may eventually interact with several specialized domains.

Examples:

* Factory / machine data
* Production / product history
* Technical documentation
* Computer Vision
* Maintenance systems

---

## Target Architecture

The project should evolve toward:

```text
User / API
    |
    v
Agent Runtime
    |
    +-- State
    +-- Context Builder
    +-- Policy / Guardrails
    +-- Evals / Tracing
    |
    v
Tool Router / MCP Multiplexer
    |
    +-- Factory MCP
    +-- Production MCP
    +-- Knowledge MCP
    +-- Vision MCP
```

The architecture must be developed incrementally.

Do NOT implement the complete target architecture prematurely.

---

## Development Principle

Prefer the simplest architecture that correctly solves the current problem.

Complexity must earn its place.

Do not introduce:

* multi-agent systems
* planners
* LangGraph
* vector databases
* distributed MCP services
* queues
* Kubernetes
* unnecessary abstractions

unless the current development step genuinely requires them.

Start with explicit Python code and clear interfaces.

Introduce frameworks only when their value is understood and justified.

---

## Hexagonal Architecture Dependency Rules

The system follows Hexagonal Architecture / Ports and Adapters. Dependencies point
inward.

* `domain` must not depend on `agent`, `tools`, `infrastructure`, provider SDKs,
  transport schemas, databases, MCP, or web frameworks.
* Application behavior currently in `agent` or `tools` must depend on inner ports and
  Domain types, never concrete `infrastructure` implementations.
* Ports belong to the Core and must not expose provider-, transport-, or
  persistence-specific types.
* `infrastructure` may depend on the Core and implements its ports; the Core must not
  depend on `infrastructure`.
* Translate external DTOs to internal models at adapter boundaries.
* Wire concrete adapters only at a Composition Root through explicit dependency
  injection. Do not hide Infrastructure construction in Domain, Application, `agent`,
  or `tools`.
* Check import direction and object construction for boundary violations during every
  change.
* Do not add ceremonial layers or directories. Introduce an explicit `application`
  layer or `application/ports` only when growing use cases and ports justify it.

See `docs/decisions/ADR-003-hexagonal-architecture.md`.

---

## Agent Architecture Principles

Use the LLM for judgment and decision-making.

Use deterministic code for guarantees.

Examples of deterministic responsibilities:

* validation
* authorization
* numeric calculations
* filtering
* aggregation
* safety limits
* retries
* timeouts
* state persistence

The LLM must never be treated as a trusted enforcement mechanism.

---

## Troubleshooting Agent Orchestration

The accepted next orchestration strategy is an explicit, bounded, sequential
single-agent tool loop implemented in Python. Until that loop is implemented, keep the
current single-tool-call behavior documented as the actual runtime state.

For the bounded loop:

* the LLM decides between one next tool call and a final answer using prior observations
* deterministic code owns validation, dispatch, execution, limits, and termination
* every run has a finite positive tool-call limit; a call requested after exhaustion is
  not executed and terminates with an explicit deterministic limit failure
* execute at most one tool call per iteration and do not add parallel execution,
  Planner/Executor, multi-agent orchestration, or an agent framework without a new or
  superseding architecture decision
* preserve the provider-independent `LLMClient`, semantic Model Profiles, and the
  existing first-decision eval baseline

See `docs/decisions/ADR-004-agent-orchestration-strategy.md`.

---

## LLM Provider and Model Independence

Agents and use cases must depend on the provider-independent `LLMClient` port and
select models through semantic Model Profiles such as `troubleshooting`.

Do not place concrete provider names, model identifiers, endpoints, API keys, or
provider SDK types in agent or use-case code.

The mapping from Model Profiles to providers, models, and endpoints belongs in normal
configuration. API-key values must come exclusively from environment variables.
Unauthenticated local profiles must not require user-configured API keys; an
Infrastructure adapter may encapsulate a non-secret SDK placeholder when technically
necessary.

Provider adapters belong to `infrastructure`. Add abstractions for multiple or
non-OpenAI-compatible providers only when an implemented capability requires them.

See `docs/decisions/ADR-002-provider-and-model-independent-llm-architecture.md`.

---

## Tool Design

Agent-facing tools should represent meaningful domain capabilities.

Prefer:

```text
get_machine_status(station_id)
get_product_history(product_id)
get_station_failure_history(...)
search_documentation(...)
analyze_product_inspection(...)
```

Avoid very low-level tool exposure such as:

```text
get_axis_x()
get_axis_y()
load_image()
crop_image()
run_model()
```

unless implementing a specialized lower-level agent.

Avoid generic mega-tools such as:

```text
factory_query(operation, ...)
```

Tool schemas should:

* use explicit types
* use enums / Literal where appropriate
* make invalid actions structurally difficult
* return structured data
* avoid unnecessary prose

---

## State and Context

Application state is the source of truth.

LLM context is only a task-specific projection of that state.

Do not rely on conversation history as persistent application state.

Persistent raw observations should be retained independently from summarized LLM context.

---

## RAG Principles

Retrieval should be treated as a separate subsystem.

Preferred production direction:

```text
Parsing
-> Structure-aware chunking
-> Metadata
-> Embeddings
-> Hybrid retrieval
-> Reranking
-> Context selection
```

For technical documentation, exact identifiers such as error codes, component IDs, station names, and part numbers are important.

Therefore, semantic search alone is generally insufficient.

Evaluate retrieval separately from final answer quality.

---

## Evaluation

Keep deterministic tests and AI / Agent evaluations as separate quality mechanisms.

* Use deterministic automated tests for guarantees such as Domain invariants,
  validation, dispatch, mappings, limits, termination, configuration, error handling,
  and eval scoring. Unit tests must not require real LLM, network, database, or MCP
  calls; substitute ports with fakes or stubs.
* Use versioned datasets with stable case IDs, structured ground truth, and explicit
  metrics for behavior that inherently depends on model judgment.
* Do not replace normal software tests with LLM-based evaluation. Do not use
  LLM-as-a-Judge when an objective deterministic check is possible.
* Keep live integration and smoke tests explicitly identifiable and outside the normal
  unit-test gate.
* Before material changes to prompts, models, Model Profiles, tool schemas,
  orchestration, retrieval, reranking, or context building, rerun the relevant existing
  evals and compare them with the baseline.
* Keep generated eval reports unversioned by default and record enough provenance to
  interpret deliberately retained results without exposing secrets.

Every meaningful model-dependent agent capability should eventually have automated
evaluation when the corresponding behavior and metric exist.

Possible metrics include:

* task success
* root-cause correctness
* tool-selection accuracy
* tool-argument accuracy
* retrieval recall
* grounding
* unsupported claims
* unnecessary tool calls
* latency
* token usage
* cost
* safety violations

Do not judge quality only through manual chat testing.

See `docs/decisions/ADR-005-testing-and-evaluation-strategy.md`.

---

## Observability

Agent runs should eventually be traceable.

A trace should make it possible to inspect:

* LLM calls
* tool calls
* arguments
* tool results
* retrieval
* reranking
* model
* prompt version
* token usage
* latency
* failures

OpenTelemetry-compatible instrumentation is preferred when distributed components are introduced.

---

## Safety

Read and write tools must be treated differently.

Examples:

Read-only:

* machine status
* product history
* documentation search
* inspection results

Actions:

* restart station
* change parameter
* move axis
* create maintenance ticket

High-risk actions require deterministic authorization and policy checks.

Human approval must be supported where appropriate.

Industrial safety must remain enforced by machine / PLC / safety systems independently of the LLM.

---

## Security

Never commit:

* API keys
* passwords
* private SSH keys
* customer credentials
* secrets
* production tokens

Use `.env` locally and maintain `.env.example`.

Avoid exposing sensitive production data in traces or logs.

---

## Python

Target Python version:

```text
Python 3.12+
```

Use:

* type hints
* Pydantic models for structured boundaries
* pytest
* Ruff
* clear domain types
* small focused modules

Avoid unnecessary global state.

Prefer explicit dependency injection over hidden service locators.

---

## Package Structure

Primary package:

```text
src/industrial_ai_agent/
```

Current architectural areas:

```text
domain/
agent/
tools/
infrastructure/
```

General intent:

### domain

Business and industrial concepts.

Must not depend on LLM SDKs, MCP implementations, databases, or web frameworks.

### tools

Agent-facing domain capabilities and tool contracts.

### agent

Agent orchestration, state, context construction, routing, execution loops.

### infrastructure

External implementations such as:

* LLM providers
* MCP clients
* persistence
* databases
* HTTP integrations
* observability

---

## Tests

Use:

```text
tests/unit/
tests/integration/
```

Unit tests should not require live LLM APIs.

Prefer deterministic fake implementations for core agent tests.

Integration tests may use external services but must be explicitly identifiable.

---

## Coding Workflow

For every non-trivial change:

1. Understand the current architecture.
2. Explain the intended change briefly.
3. Implement the smallest coherent step.
4. Add or update tests.
5. Run relevant tests.
6. Run Ruff.
7. Update documentation if architecture or behavior changed.
8. Summarize what changed and why.

Avoid large unrelated refactorings.

Do not silently change architecture.

---

## Learning Mode

This repository is explicitly a learning project.

When introducing a new concept, library, framework, or architectural pattern:

* explain why it is needed
* explain what problem it solves
* explain the alternative
* keep the implementation understandable
* do not hide important mechanics behind frameworks too early

When possible, implement important agent primitives manually before replacing them with frameworks.

Examples:

* basic tool loop before LangGraph
* explicit state before persistence framework
* simple retrieval before advanced agentic RAG

---

## Architecture Decisions

Important architectural decisions must be documented as Architecture Decision Records
under:

```text
docs/decisions/
```

ADRs capture decisions that establish long-lived architectural constraints or influence
multiple future capabilities. They document not only what was decided, but also why the
decision was made and which alternatives were considered.

### When an ADR is Required

Before introducing a significant architectural concept or changing an existing
architectural boundary, determine whether the decision should be captured as an ADR.

Create or update an ADR before implementation when a decision:

* establishes a long-lived architectural constraint
* introduces or changes an architectural pattern
* introduces a significant subsystem or integration strategy
* changes dependency boundaries or dependency direction
* affects multiple current or future capabilities
* defines an important cross-cutting concern
* represents a significant trade-off between viable alternatives
* changes or supersedes an existing architectural decision

Examples include:

* architectural layering and dependency rules
* LLM provider and model abstraction
* agent orchestration strategies
* state, context, and memory architecture
* retrieval / RAG architecture
* MCP integration and routing
* persistence strategies
* evaluation architecture
* observability architecture
* authorization and human-approval boundaries

### When an ADR is Not Required

Do not create ADRs for:

* ordinary implementation details
* local refactorings that do not change architectural boundaries
* naming decisions
* minor library usage
* temporary experiments
* speculative architecture that is not yet required
* decisions that are still exploratory and have not been validated sufficiently

Avoid creating architecture merely to satisfy an ADR and avoid creating ADRs for
hypothetical future complexity.

### ADR Timing

Prefer making and documenting architectural decisions just in time.

The normal sequence is:

```text
Requirement / Problem
        |
        v
Explore the smallest viable solution
        |
        v
Identify a long-lived architectural decision
        |
        v
Create or update the ADR
        |
        v
Implement
        |
        v
Validate through tests / evaluations
```

For decisions that establish architectural boundaries before implementation, create the
ADR before introducing the corresponding production code.

For exploratory work, gather enough evidence first and record the decision once it is
stable enough to become an architectural constraint.

### ADR Content

Use short, focused ADR-style documents.

An ADR should normally contain:

* Status
* Context
* Decision
* Alternatives considered
* Consequences

Where useful, also document:

* dependency rules
* architectural boundaries
* configuration implications
* testing implications
* security implications
* migration or evolution considerations

The ADR must describe the actual decision precisely enough that future implementation
work can be checked against it.

### ADR Consistency

ADRs, the Architecture Overview, `AGENTS.md`, and the implementation must remain
consistent.

When implementing a change:

1. Check whether an existing ADR governs the affected architecture.
2. Do not silently violate or bypass an accepted ADR.
3. If the intended implementation conflicts with an existing ADR, stop and make the
   architectural conflict explicit before changing the implementation.
4. Update or supersede the ADR when the architectural decision itself changes.
5. Update the Architecture Overview when the current system structure or responsibilities
   change.
6. Add durable implementation rules to `AGENTS.md` when future coding agents must
   consistently enforce them.

An ADR is not a substitute for implementation documentation, and `AGENTS.md` is not a
substitute for explaining architectural rationale in an ADR.

### Current Architecture Decisions

The currently accepted architecture decisions include:

```text
ADR-001  Project foundation
ADR-002  Provider- and model-independent LLM architecture
ADR-003  Hexagonal Architecture
ADR-004  Agent orchestration strategy
ADR-005  Testing and evaluation strategy
```

Future ADRs should be introduced only when the corresponding architectural decision
becomes necessary and sufficiently concrete.

---

## Documentation

Use:

```text
docs/architecture/
docs/decisions/
docs/learning/
```

### architecture

Current architecture and component responsibilities.

### decisions

Architecture Decision Records.

### learning

Short notes explaining important Agentic AI concepts implemented in the project.

Documentation should reflect the actual implementation, not hypothetical future features.

### Architecture Diagrams

For every change, check whether any Mermaid diagram under `docs/` is affected by the
changed behavior, component responsibilities, dependencies, runtime flow, or target
architecture.

When a diagram is affected:

* update it in the same change as the implementation or documentation change
* keep it consistent with the current code and accepted ADRs
* preserve the distinction between implemented architecture and future target direction
* update both the canonical English document and its German `.de.md` counterpart

Do not leave architecture diagrams stale when the surrounding prose is updated.

---

## Git

Keep commits focused.

Prefer descriptive commit messages.

Examples:

```text
feat: add product history tool
test: add agent tool selection cases
docs: document agent state model
refactor: separate domain and infrastructure models
```

Do not commit generated secrets or `.env`.

---

## Definition of Done

A development step is complete when:

* implementation works
* relevant tests pass
* Ruff passes
* public interfaces are typed
* architecture remains coherent
* documentation is updated when needed
* no secrets are committed

## Language and Documentation Policy

### Communication

Communicate with the repository owner in **German**.

Explanations of implementations, architecture decisions, reviews, and learning concepts should be written in German unless explicitly requested otherwise.

### Code

All source code must use English, including:

* identifiers
* class names
* function names
* variable names
* comments
* docstrings
* log messages
* exception messages
* test names

### Primary Documentation

The canonical technical documentation is written in English.

This includes:

* `README.md`
* architecture documentation
* Architecture Decision Records
* learning documentation
* other repository Markdown documentation

### German Documentation

For every English Markdown documentation file other than `AGENTS.md`, maintain a corresponding German version for the repository owner's personal use.

`AGENTS.md` is an explicit exception: it is maintained in English only, and `AGENTS.de.md` must not be created.

Naming convention:

```text id="i8g9qs"
README.md
README.de.md

docs/architecture/overview.md
docs/architecture/overview.de.md

docs/decisions/ADR-001-project-foundation.md
docs/decisions/ADR-001-project-foundation.de.md
```

The English version remains the canonical technical document.

The German version should be a faithful technical translation, but may use natural German wording where this improves comprehension.

Do not translate:

* source code
* identifiers
* API names
* class/function names
* technology names
* file paths
* commands

### Synchronization Requirement

English and German documentation covered by this policy must remain synchronized.

Whenever an English documentation file other than `AGENTS.md` is:

* created
* modified
* renamed
* moved
* deleted

the corresponding `.de.md` file must be handled in the same change.

Likewise, if a German documentation file is changed in a way that affects technical content, ensure that the canonical English document reflects the same information.

A documentation change is not complete until both language variants are consistent.

### Definition of Done Addition

Before completing a task that changes documentation, verify:

1. the English documentation is correct,
2. the corresponding German `.de.md` exists when required by this policy,
3. both versions describe the same technical state when a language pair is required,
4. links and file references remain valid in both versions where applicable,
5. affected Mermaid diagrams are updated and technically consistent in both versions.
