# Architecture Overview

## Current Architecture

The project currently implements its first deterministic vertical slice, retrieving
the production history of a product, and its first provider-independent LLM integration
boundary. There is no agent loop yet.

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

The implemented LLM boundary is:

```text
Agent / Use Case
    |
    | semantic profile + LLMRequest
    v
LLMClient port
    |
    v
OpenAICompatibleLLMClient
    |
    | profile configuration + credentials when required
    v
Configured OpenAI-compatible endpoint
```

`config/model_profiles.toml` currently maps `troubleshooting` to Ollama,
`qwen3.5:9b`, `http://localhost:11434/v1`, and temperature `0`. This is the first local
configuration, not a commitment to that provider or model. The profile mapping can be
changed without changing agent or use-case code.

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

Contains provider-independent LLM contracts and, later, agent orchestration logic.

The current implementation defines `LLMClient`, semantic `ModelProfile` selection, and
small request and response models. It does not import the OpenAI SDK or name a concrete
provider or model.

Later responsibilities may include:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Contains technical integrations and external implementations.

The current implementations are `InMemoryProductHistoryRepository`, which provides a
small deterministic demo data set, and `OpenAICompatibleLLMClient`, which translates
the provider-independent LLM contract to an OpenAI-compatible Chat Completions API.

Normal model settings and secret values are separate. Configuration explicitly marks a
profile as unauthenticated or API-key authenticated. An authenticated profile stores
only the name of the required environment variable; its credential value remains in
the environment. The initial local Ollama profile is unauthenticated and requires no
user-configured API key. The adapter encapsulates the non-secret technical placeholder
required by the OpenAI SDK.

Examples may later include:

* additional LLM provider adapters when concrete requirements justify them
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

Model profiles such as `vision`, `planning`, or `evaluation` can be added through
configuration when their capabilities are implemented. A non-OpenAI-compatible
provider will require another infrastructure adapter behind the same `LLMClient` port;
no speculative multi-provider router exists today. See
[ADR-002](../decisions/ADR-002-provider-and-model-independent-llm-architecture.md) for
the decision and its tradeoffs.
