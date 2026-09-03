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

Two deterministic domain capabilities are implemented: product history lookup through
`ProductHistoryCapability.get_product_history(product_id)` and current machine status
through `MachineStatusCapability.get_machine_status(station_id)`. Both use inner
repository ports with deterministic in-memory adapters. A provider-independent
`LLMClient` port and one OpenAI-compatible infrastructure adapter are also available.
Model selection uses the configured semantic profile `troubleshooting`.
`TroubleshootingAgent` offers exactly the two known tools to the model, validates and
dispatches at most one selected call in deterministic code, and asks the model to
formulate the final answer. There is no general agent or ReAct loop.

A first deterministic evaluation baseline measures the agent's initial LLM tool
selection and argument extraction against twelve versioned cases. It does not execute
tools or evaluate final answers.

No LLM framework, MCP server, vector database, or multi-agent framework is introduced yet.

## Manual Ollama Smoke Tests

The smoke test is deliberately separate from automated tests and calls the configured
local model. Install and start Ollama, make sure `qwen3.5:9b` is available, and run:

```powershell
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
python scripts/smoke_test_troubleshooting_agent.py
```

The first script verifies basic LLM connectivity. The second runs the complete
tool-selection slice and verifies both `get_product_history` for product `P4711` and
`get_machine_status` for station `S12`.

## Manual Tool Selection Eval

Run the versioned tool-selection dataset against the configured semantic profile:

```powershell
python -m evals.run_tool_selection --profile troubleshooting
```

The command prints a structured JSON report with per-case results, Tool Selection
Accuracy, and Argument Accuracy. See
[Tool Selection Evaluation Baseline](docs/learning/tool-selection-evaluation.md) for
metric definitions, interpretation, and optional local result output.

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
