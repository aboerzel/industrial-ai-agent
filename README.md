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
Model selection uses explicit task requirements and the deterministic model router.
The handwritten `TroubleshootingAgent` reference and the parallel
`LangGraphTroubleshootingAgent` offer exactly the same two known tools. Both preserve
the bounded sequential semantics: one validated and dispatched call per LLM decision,
preserve structured observations in the current conversation context, and allow at
most three successfully executed tools per run. A final model answer returns structured
`SUCCESS`; a further tool request after the third result returns `LIMIT_REACHED` without
executing that call or invoking the LLM again. The LangGraph path uses LangChain Core
messages and tool contracts through a narrow adapter to the existing security-checked
`LLMClient`. Its local/test HITL demonstration uses an injected in-memory checkpointer;
there is no dynamic tool registry, durable persistence backend, LangSmith integration,
or context compression.

Two deterministic evaluation baselines are available. The first measures the agent's
initial LLM tool selection and argument extraction against twelve versioned cases
without executing tools. The second executes ten complete agent runs and compares the
actual bounded trajectories and termination statuses with structured ground truth.
Neither baseline evaluates natural-language final-answer quality.

An isolated `DocumentationSearchCapability.search_documentation(query)` now searches a
small versioned local technical knowledge base through an inner `KnowledgeRetriever`
port. Three deterministic in-memory lexical adapters provide simple term-overlap,
rarity-aware IDF, and BM25 ranking. Results retain document, source, chunk, score, and
metadata provenance. Retrieval is intentionally not yet exposed as a
`TroubleshootingAgent` tool.

A first read-only `factory_mcp` server now adapts the two existing capabilities through
the official MCP SDK v2. stdio remains available for process-coupled development and
tests; the same server runs through Streamable HTTP at `/mcp` as a local Docker service.
The asynchronous read-only LangGraph path discovers its two authorized tools and calls
them through one stdio or HTTP session per agent run. The direct LangChain tool path
remains as a reference; there is no MCP routing, Knowledge MCP, or MCP write action.

## Manual MCP Smoke Test

Run the local stdio client and server without an LLM or external service:

```powershell
python scripts/smoke_test_factory_mcp.py
python scripts/smoke_test_langgraph.py --confidential-troubleshooting --mcp
```

The smoke prints the server identity, negotiated protocol version, discovered tool
names, and structured results for `get_product_history(P4711)` and
`get_machine_status(S04)`. The LangGraph smoke uses only `local_quality` for its
confidential MCP run and prints MCP session discovery plus the final trajectory.

To run the networked deployment path, build and start only the local factory service:

```powershell
docker compose up --build -d factory-mcp
python scripts/smoke_test_factory_mcp.py --transport http
python scripts/smoke_test_langgraph.py --confidential-troubleshooting --mcp --mcp-transport http
```

The container defaults to `0.0.0.0:8001` and its SDK-managed endpoint is
`http://127.0.0.1:8001/mcp`. It contains no `.env`, secrets, LLM, or embedding model and
runs as a non-root user. One HTTP MCP session covers discovery and all sequential tool
calls in an agent run; it is closed after the run. Docker provides repeatable service
deployment, while MCP provides the tool protocol and discovery. The unauthenticated
HTTP endpoint is accepted only for this local demo; a remote or production deployment
requires explicit MCP authentication and transport security. MCP network transport does
not authorize model egress: confidential troubleshooting still uses the local profile
under ADR-009 and never sends factory results to `public_fast`.

The current stable `langchain-mcp-adapters` release remains incompatible with MCP SDK
v2, so the temporary project-owned bridge is intentionally retained.

## Manual Model Profile Smoke Tests

The smoke test is deliberately separate from automated tests. Its default invocation
calls only the configured local models. Install and start Ollama, make sure both models
are available, and run:

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
python scripts/smoke_test_ollama.py --profile local_fast
python scripts/smoke_test_ollama.py --profile local_quality
python scripts/smoke_test_model_routing.py
python scripts/smoke_test_troubleshooting_agent.py
python scripts/smoke_test_langgraph.py --profile local_fast
python scripts/smoke_test_langgraph.py --profile local_quality
python scripts/smoke_test_langgraph.py --confidential-troubleshooting
python scripts/smoke_test_langgraph_hitl.py --approval approve
python scripts/smoke_test_langgraph_hitl.py --approval reject
```

Without `--profile`, the first script calls `local_fast` and `local_quality` sequentially.
The explicit invocations test either semantic profile separately and report its
configured model with the response. The router smoke deterministically verifies a
cost-focused public selection, a high-quality confidential local selection, and a
fail-closed confidential selection when only `public_fast` is available. The
troubleshooting script creates explicit confidential task requirements, currently
selects the compatible local `local_quality` profile, runs a multi-step request, and
structurally verifies the sequential calls
`get_product_history(P4711)` and `get_machine_status(S04)` before a successful final
answer.

The HITL smoke runs the LangGraph path with a confidential local profile and an
in-memory checkpointer. It shows the structured approval request for the harmless
`create_maintenance_ticket` demonstration action, then resumes the same thread with the
chosen explicit result. It never calls an external ticket system or performs a machine
action.

The `public_fast` profile uses Groq through the same `OpenAICompatibleLLMClient`. Set
`GROQ_API_KEY` in the unversioned local `.env` file and invoke it only explicitly:

```powershell
python scripts/smoke_test_ollama.py --profile public_fast
python scripts/smoke_test_langgraph.py --profile public_fast
```

Executable entry points load the project-root `.env` explicitly as local runtime
configuration. Existing process Environment Variables take precedence and are never
overridden by `.env` values.

This public-cloud smoke path sends only the synthetic prompt
`Reply exactly with PUBLIC_LLM_OK` and explicitly classifies it as `PUBLIC`. The
deterministic ADR-009 egress check validates the profile's `PUBLIC_CLOUD` Execution Zone
before the provider adapter is called. `public_fast` is not selected automatically and
is not a fallback profile.

## Manual Tool Selection Eval

Run the unchanged versioned tool-selection dataset against either orchestration path:

```powershell
python -m evals.run_tool_selection --agent-path manual --profile troubleshooting
python -m evals.run_tool_selection --agent-path langgraph --profile troubleshooting
python -m evals.run_tool_selection --agent-path langgraph --tool-transport mcp --profile troubleshooting
```

The command prints a structured JSON report with per-case results, Tool Selection
Accuracy, and Argument Accuracy. See
[Tool Selection Evaluation Baseline](docs/learning/tool-selection-evaluation.md) for
metric definitions, interpretation, and optional local result output.

## Manual Trajectory Eval

Run the unchanged versioned multi-step dataset through either complete bounded agent path:

```powershell
python -m evals.run_trajectory --agent-path manual --profile troubleshooting
python -m evals.run_trajectory --agent-path langgraph --profile troubleshooting
python -m evals.run_trajectory --agent-path langgraph --tool-transport mcp --profile troubleshooting
```

The JSON report contains per-case expected and actual trajectories, tool-call counts,
Task Success Rate, Exact Trajectory Accuracy, Tool Call Accuracy, and Termination
Accuracy. See
[Troubleshooting Trajectory Evaluation](docs/learning/trajectory-evaluation.md) for the
exact scoring formulas and interpretation.

## Manual Retrieval Eval

Run the frozen v2 retrieval baseline against all six local strategies:

```powershell
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy simple
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy idf
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy bm25
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy semantic
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy hybrid
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy reranked
python scripts/smoke_test_semantic_retrieval.py
python scripts/smoke_test_reranked_retrieval.py
```

The JSON report contains Hit@1, Hit@3, Mean Recall@3, per-case expected and actual
chunk IDs, explicit failure lists, and category-level metrics. The original v1 dataset
remains available by selecting `knowledge_retrieval_v1.jsonl` explicitly. See
[Local Knowledge Retrieval Baseline](docs/learning/knowledge-retrieval-baseline.md) for
the chunking and scoring formulas, v1/v2 comparison, semantic, hybrid, and reranked
baselines, freeze rule, and known limitations.

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

knowledge_base/
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
