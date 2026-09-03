# Architecture Overview

## Current Architecture

The project currently implements product-history retrieval, current machine-status
retrieval, a provider-independent LLM integration boundary, and one bounded
two-tool-selection slice. There is no general agent or ReAct loop.

The implemented request flow is:

```mermaid
flowchart LR
    subgraph Core["Application Core"]
        PHC["ProductHistoryCapability"]
        MSC["MachineStatusCapability"]
    end

    subgraph Ports["Domain-owned ports"]
        PHR["ProductHistoryRepository"]
        MSR["MachineStatusRepository"]
    end

    subgraph Infrastructure["Infrastructure adapters"]
        PHM["InMemoryProductHistoryRepository"]
        MSM["InMemoryMachineStatusRepository"]
    end

    PHC -->|"ProductId"| PHR
    MSC -->|"StationId"| MSR
    PHM -.->|"implements"| PHR
    MSM -.->|"implements"| MSR

    classDef core fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef port fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef adapter fill:#ecfdf5,stroke:#059669,color:#022c22
    class PHC,MSC core
    class PHR,MSR port
    class PHM,MSM adapter
```

Each capability converts its string identifier into the appropriate Domain Value
Object, loads through a domain-owned repository abstraction, and returns a structured
result. The deterministic demo data includes product `P4711` and stations `S04` and
`S12`.

Distributed services and AI frameworks are deliberately not part of this slice.

The implemented LLM boundary is:

```mermaid
flowchart LR
    A["Agent / Use Case"] -->|"semantic ModelProfile + LLMRequest"| P["LLMClient port"]
    C["OpenAICompatibleLLMClient"] -.->|"implements"| P
    TOML["config/model_profiles.toml<br/>provider, model, base URL, temperature, auth mode"] --> C
    ENV["Environment variables<br/>API keys for authenticated profiles only"] -.-> C
    C -->|"provider-specific request"| E["Configured OpenAI-compatible endpoint"]

    subgraph Core["Application Core"]
        A
        P
    end

    subgraph Infrastructure["Infrastructure"]
        C
        TOML
        ENV
    end

    subgraph External["External system"]
        E
    end

    classDef core fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef adapter fill:#ecfdf5,stroke:#059669,color:#022c22
    classDef external fill:#fff7ed,stroke:#ea580c,color:#431407
    class A,P core
    class C,TOML,ENV adapter
    class E external
```

`config/model_profiles.toml` currently maps `troubleshooting` to Ollama,
`qwen3.5:9b`, `http://localhost:11434/v1`, and temperature `0`. This is the first local
configuration, not a commitment to that provider or model. The profile mapping can be
changed without changing agent or use-case code.

The implemented tool-calling flow is:

```mermaid
sequenceDiagram
    actor User
    participant Agent as TroubleshootingAgent
    participant LLM as LLMClient<br/>(troubleshooting profile)
    participant Product as ProductHistoryCapability
    participant Machine as MachineStatusCapability

    User->>Agent: Natural-language request
    Agent->>LLM: LLMRequest + exactly two tool definitions

    alt Direct answer
        LLM-->>Agent: Response text without a tool call
    else One tool call
        LLM-->>Agent: LLMToolCall
        Note over Agent: Deterministically validate call count,<br/>tool name, and tool-specific arguments
        alt get_product_history
            Agent->>Product: get_product_history(product_id)
            Product-->>Agent: ProductHistoryResult
        else get_machine_status
            Agent->>Machine: get_machine_status(station_id)
            Machine-->>Agent: MachineStatusResult
        end
        Agent->>LLM: Structured tool result, no tools offered
        LLM-->>Agent: Final response text
    end

    Agent-->>User: Final answer
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

```mermaid
flowchart TD
    U["User / API"] --> AR["Agent Runtime"]

    subgraph Runtime["Potential future runtime capabilities"]
        AR
        State["State"]
        Context["Context Builder"]
        Policy["Policy / Guardrails"]
        Observability["Evals / Tracing"]
        AR --- State
        AR --- Context
        AR --- Policy
        AR --- Observability
    end

    AR --> Router["Tool Router"]
    Router --> Multiplexer["MCP Multiplexer"]
    Multiplexer --> Factory["Factory MCP"]
    Multiplexer --> Production["Production MCP"]
    Multiplexer --> Knowledge["Knowledge MCP"]
    Multiplexer --> Vision["Vision MCP"]

    classDef runtime fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef routing fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef service fill:#fff7ed,stroke:#ea580c,color:#431407
    class AR,State,Context,Policy,Observability runtime
    class Router,Multiplexer routing
    class Factory,Production,Knowledge,Vision service
```

This is a target direction, not the current implementation.

Model profiles such as `vision`, `planning`, or `evaluation` can be added through
configuration when their capabilities are implemented. A non-OpenAI-compatible
provider will require another infrastructure adapter behind the same `LLMClient` port;
no speculative multi-provider router exists today. See
[ADR-002](../decisions/ADR-002-provider-and-model-independent-llm-architecture.md) for
the decision and its tradeoffs.
