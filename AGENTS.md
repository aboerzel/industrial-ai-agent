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

Every meaningful agent capability should eventually have automated evaluation.

Prefer deterministic evaluation whenever possible.

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

Important architectural decisions should be documented under:

```text
docs/decisions/
```

Use short ADR-style documents.

Examples:

```text
ADR-001-python-project-structure.md
ADR-002-tool-design.md
ADR-003-state-model.md
```

An ADR should contain:

* Context
* Decision
* Alternatives
* Consequences

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
4. links and file references remain valid in both versions where applicable.
