# Industrial AI Agent

Production-oriented learning and portfolio project for Agentic / Applied AI in an industrial setting.

The project starts with simple, explicit Python building blocks and evolves incrementally toward:

* LLM tool calling
* agent state and context management
* retrieval-augmented generation
* evaluations
* observability and tracing
* guardrails and human approval
* MCP-based integrations
* a multi-service industrial AI architecture

## Current Stage

The first deterministic vertical slice is implemented: product history lookup through
the agent-facing `ProductHistoryCapability.get_product_history(product_id)` capability,
backed by an in-memory repository. A provider-independent `LLMClient` port and one
OpenAI-compatible infrastructure adapter are also available. Model selection uses the
configured semantic profile `troubleshooting`; there is no agent loop yet.

No LLM framework, MCP server, vector database, or multi-agent framework is introduced yet.

## Manual Ollama Smoke Test

The smoke test is deliberately separate from automated tests and calls the configured
local model. Install and start Ollama, make sure `qwen3.5:9b` is available, and run:

```powershell
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
```

The committed model configuration is in `config/model_profiles.toml`. The local Ollama
profile requires no API key. Authenticated profiles must read credential values from
environment variables or the ignored local `.env` file; `.env.example` contains no
secret values.

## Development Principles

* Prefer simple explicit code.
* Use deterministic code for guarantees.
* Use LLMs for judgment and decision-making.
* Introduce frameworks only when they solve a concrete problem.
* Keep tests and documentation close to implementation.
* Treat this repository as both a learning project and a professional reference project.

## Project Structure

```text
src/industrial_ai_agent/
├── agent/
├── domain/
├── infrastructure/
└── tools/

tests/
├── unit/
└── integration/

docs/
├── architecture/
├── decisions/
└── learning/

evals/
├── datasets/
└── results/
```

## Python

Python 3.12+

## Quality

Development should include:

* type hints
* Pydantic at system boundaries
* pytest
* Ruff
* focused commits
* architecture decision records for significant choices
