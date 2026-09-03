# Architecture Overview

## Current Architecture

The project currently contains only the structural foundation.

The intended initial architecture is:

```text
User Request
    |
    v
Agent
    |
    v
Domain Tool
    |
    v
Deterministic Domain / Infrastructure Code
```

The first implementation steps will deliberately avoid distributed services and AI frameworks.

## Package Responsibilities

### `domain`

Contains industrial domain models and rules.

Must remain independent from:

* LLM SDKs
* MCP
* databases
* HTTP frameworks
* vendor-specific infrastructure

### `tools`

Contains agent-facing capabilities.

Tools should expose meaningful domain operations rather than low-level implementation details.

### `agent`

Contains agent orchestration logic.

Later responsibilities may include:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Contains technical integrations and external implementations.

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
