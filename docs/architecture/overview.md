# Architecture Overview

## Current Architecture

The project currently implements its first deterministic vertical slice: retrieving
the production history of a product.

The implemented request flow is:

```text
User Request
    |
    v
ProductHistoryCapability.get_product_history(product_id)
    |
    v
ProductHistoryRepository
    |
    v
InMemoryProductHistoryRepository
```

The capability converts the string input into a `ProductId`, loads a `ProductHistory`
through the domain-owned repository abstraction, and returns a structured
`ProductHistoryResult`. The deterministic demo data includes product `P4711`.

Distributed services and AI frameworks are deliberately not part of this slice.

## Package Responsibilities

### `domain`

Contains industrial domain models and rules.

The current slice defines `ProductId`, `StationId`, `ProductionStep`,
`ProductionStepStatus`, `ProductHistory`, and the `ProductHistoryRepository` protocol.

Must remain independent from:

* LLM SDKs
* MCP
* databases
* HTTP frameworks
* vendor-specific infrastructure

### `tools`

Contains agent-facing capabilities.

Tools should expose meaningful domain operations rather than low-level implementation details.

The current capability is `ProductHistoryCapability.get_product_history(product_id)`.
It returns a Pydantic `ProductHistoryResult`, including a structured not-found result.

### `agent`

Contains agent orchestration logic.

This package is not used by the current deterministic slice.

Later responsibilities may include:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Contains technical integrations and external implementations.

The current implementation is `InMemoryProductHistoryRepository`, which provides a
small deterministic demo data set.

Examples may later include:

* LLM providers
* repositories
* databases
* MCP clients
* observability
* external APIs

## Evolution

The architecture should evolve only when required by implemented capabilities.

Possible later stages include:

```text
Agent Runtime
    |
    +-- State
    +-- Context Builder
    +-- Policy Layer
    |
    v
Tool Router
    |
    v
MCP Multiplexer
    |
    +-- Factory MCP
    +-- Production MCP
    +-- Knowledge MCP
    +-- Vision MCP
```

This is a target direction, not the current implementation.
