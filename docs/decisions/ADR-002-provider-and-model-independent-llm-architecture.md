# ADR-002: Provider- and Model-Independent LLM Architecture

## Status

Accepted

## Context

The agent runtime and its use cases will need LLM judgment without making the
application dependent on one model or provider. The project must be able to use local
models for private, inexpensive, or offline development and public cloud models when
their quality or managed operation is useful. Different tasks may also benefit from
different models; troubleshooting, vision, planning, and evaluation need not share one
model choice.

Embedding provider names, model identifiers, endpoints, or SDK types in agent code
would couple behavior to infrastructure. It would also make model replacement and
later comparative evaluations unnecessarily invasive. Credentials must not be stored
with ordinary model settings or committed to the repository.

## Decision

Agent code and use cases depend on the provider-independent `LLMClient` port. They
select a semantic Model Profile such as `troubleshooting`, never a concrete provider or
model name. The port owns small request and response models for messages, response
text, tool definitions, returned tool calls, and finish reasons. These types do not
import a provider SDK.

The mapping from a profile to its provider, model, endpoint, temperature, and
authentication mode is external configuration. Authenticated profiles additionally
declare the name of their API-key environment variable. A model can therefore be
changed without modifying agent or use-case code. Ordinary settings live in
`config/model_profiles.toml`; credential values are read only from environment
variables and are never stored in model configuration.

Provider adapters belong to `infrastructure` and translate between the port models and
provider SDKs. The first and currently only adapter targets OpenAI-compatible Chat
Completions APIs. The initial `troubleshooting` profile uses the local Ollama endpoint
with `qwen3.5:9b`, `http://localhost:11434/v1`, temperature `0`, and authentication mode
`none`. It requires no API-key environment variable. If the OpenAI SDK technically
requires a non-empty `api_key` argument, the Infrastructure adapter supplies an
internal, non-secret placeholder. That placeholder is neither a credential nor model
configuration and is invisible to the `LLMClient` port. This initial setup is a
configuration choice, not an architectural commitment to Ollama or that model.

Additional profiles such as `vision`, `planning`, or `evaluation` can be added when a
real capability needs them. Comparative evaluations can later run the same cases with
different profile mappings and record quality, latency, token use, and cost without
changing the evaluated use case.

This decision is a concrete application of the overarching Hexagonal Architecture in
[ADR-003](ADR-003-hexagonal-architecture.md): `LLMClient` is an inner port,
provider-independent request and response types belong to the Core boundary, and
`OpenAICompatibleLLMClient` is an outer Infrastructure adapter. Provider SDK objects
are translated at that adapter boundary and do not enter agent or use-case code.

If a required provider is not OpenAI-compatible, a dedicated infrastructure adapter
can implement the same `LLMClient` port. No provider registry, generic multi-provider
router, fallback chain, or other speculative abstraction is introduced now. Such
routing will be added only when a second incompatible provider creates a concrete
need.

## Alternatives

### Reference provider SDKs directly from agent code

Rejected because SDK types, credentials, endpoints, and concrete model identifiers
would leak into orchestration and use cases. Model replacement and deterministic unit
testing would become harder.

### Put concrete model names in use cases

Rejected because task intent is more stable than model availability. Semantic profiles
keep use cases readable and permit configuration-only model changes.

### Standardize permanently on Ollama and `qwen3.5:9b`

Rejected because local and cloud models have different operational and quality
tradeoffs. The initial local profile is useful for development but is not a permanent
platform choice.

### Build a complete multi-provider routing framework now

Rejected because only one protocol adapter is currently required. A generic provider
registry or fallback framework would encode assumptions that have not yet been tested
by a real second provider.

## Consequences

Positive:

* agent and use-case code stays independent of provider SDKs and model identifiers
* local and cloud endpoints can be selected through configuration
* task-specific models and later comparative model evaluations are supported
* secrets remain outside committed model configuration
* provider-specific translation is isolated and unit-testable without live API calls

Negative:

* the project owns a small set of LLM request and response models
* only the OpenAI-compatible protocol is usable until another adapter is implemented
* configuration errors and missing environment variables for authenticated profiles
  must fail clearly at runtime
* some provider-specific capabilities may require deliberate future extensions to the
  port
