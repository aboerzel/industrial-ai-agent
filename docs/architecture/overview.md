# Architecture Overview

## Current Architecture

The project currently implements product-history retrieval, current machine-status
retrieval, a provider-independent LLM integration boundary, and one bounded
two-tool-selection slice. There is no general agent or ReAct loop.

The implemented request flow is:

```text
ProductHistoryCapability                 MachineStatusCapability
        |                                         |
        v                                         v
ProductHistoryRepository                 MachineStatusRepository
        |                                         |
        v                                         v
InMemoryProductHistoryRepository         InMemoryMachineStatusRepository
```

Each capability converts its string identifier into the appropriate Domain Value
Object, loads through a domain-owned repository abstraction, and returns a structured
result. The deterministic demo data includes product `P4711` and stations `S04` and
`S12`.

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

The implemented tool-calling flow is:

```text
Natural-language request
    |
    v
TroubleshootingAgent
    |
    | LLMRequest + exactly two tool definitions
    v
LLMClient (troubleshooting profile)
    |
    +-- direct text response ----------------------------+
    |
    +-- one validated tool call                           |
            |                                             |
            v                                             |
    fixed dispatch to ProductHistoryCapability           |
    or MachineStatusCapability                           |
            |                                             |
            | structured tool result                      |
            v                                             |
    LLMClient final response                              |
            |                                             |
            +---------------------------------------------+
                                  |
                                  v
                            Final answer
```

The LLM chooses whether to request `get_product_history`, request
`get_machine_status`, or answer directly, and it formulates the final answer.
Deterministic Python code validates the selected name against those two known tools,
validates the tool-specific `product_id` or `station_id`, rejects more than one tool
call, uses a fixed dispatch to the corresponding capability, and serializes its
structured result. After one tool call, no tools are offered to the final LLM request;
a further returned tool call is rejected rather than starting a loop.

## Package Responsibilities

### `domain`

Contains industrial domain models and rules.

The current slices define `ProductId`, the shared `StationId`, `ProductionStep`,
`ProductionStepStatus`, `ProductHistory`, `MachineState`, and `MachineStatus`. The
domain-owned ports are `ProductHistoryRepository` and `MachineStatusRepository`.

Must remain independent from:

* LLM SDKs
* MCP
* databases
* HTTP frameworks
* vendor-specific infrastructure

### `tools`

Contains agent-facing capabilities.

Tools should expose meaningful domain operations rather than low-level implementation details.

The current capabilities are
`ProductHistoryCapability.get_product_history(product_id)` and
`MachineStatusCapability.get_machine_status(station_id)`. They return Pydantic
`ProductHistoryResult` and `MachineStatusResult` models, including structured not-found
results.

### `agent`

Contains provider-independent LLM contracts and, later, agent orchestration logic.

The current implementation defines `LLMClient`, semantic `ModelProfile` selection,
small request and response models, and `TroubleshootingAgent`. The agent contains the
bounded orchestration and fixed two-tool dispatch. It does not import the OpenAI SDK or
name a concrete provider or model.

Later responsibilities may include:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Contains technical integrations and external implementations.

The current implementations are `InMemoryProductHistoryRepository` and
`InMemoryMachineStatusRepository`, which provide small deterministic demo data sets,
and `OpenAICompatibleLLMClient`, which translates the provider-independent LLM contract
to an OpenAI-compatible Chat Completions API.

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
