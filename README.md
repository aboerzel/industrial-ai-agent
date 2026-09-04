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
through `MachineStatusCapability.get_machine_status(station_id)`. Production and Docker
compositions use PostgreSQL repository adapters; deterministic in-memory adapters remain
focused unit-test doubles. A provider-independent
`LLMClient` port and one OpenAI-compatible infrastructure adapter are also available.
Model selection uses explicit task requirements and the deterministic model router.
`LangGraphTroubleshootingAgent` is the sole troubleshooting loop. It receives only
runtime-discovered, authorized MCP tools and preserves the bounded sequential semantics:
one validated and dispatched call per LLM decision, structured observations in the
current conversation context, and at most three successfully executed tools per run. A
final model answer returns structured `SUCCESS`; a further tool request after the third
result returns `LIMIT_REACHED` without executing that call or invoking the LLM again.
LangGraph uses LangChain Core messages and tool contracts through a narrow adapter to
the existing security-checked `LLMClient`. Its local/test HITL demonstration remains an
action-only graph with an injected in-memory checkpointer; there is no dynamic tool
registry, durable persistence backend, LangSmith integration, or context compression.

Two deterministic evaluation baselines are available. The first measures the agent's
initial LLM tool selection and argument extraction against twelve versioned cases
without executing tools. The second executes ten complete agent runs and compares the
actual bounded trajectories and termination statuses with structured ground truth.
Neither baseline evaluates natural-language final-answer quality.

An isolated `DocumentationSearchCapability.search_documentation(query, top_k=3)` now searches a
small versioned local technical knowledge base through an inner `KnowledgeRetriever`
port. Three deterministic in-memory lexical adapters provide simple term-overlap,
rarity-aware IDF, and BM25 ranking. Results retain document, source, chunk, score, and
metadata provenance. LangGraph receives retrieval only through `knowledge_mcp`, never
through direct retriever injection.

Two read-only MCP services adapt existing capabilities through the official MCP SDK v2.
`factory_mcp` exposes `get_product_history` and `get_machine_status`; `knowledge_mcp`
exposes `search_documentation`. Both support process-coupled stdio for development/tests
and Streamable HTTP at `/mcp` for deployment. The asynchronous LangGraph path discovers
and authorizes all configured server tools, rejects duplicate tool names, opens one
session per server for the run, and calls tools sequentially. There is no generalized
MCP router or MCP write action.

## Local FastAPI API

FastAPI is the local/demo HTTP Application Boundary, not an agent, MCP, routing, or
egress replacement. It delegates each run to `TroubleshootingRunService`, which fixes
the first API use case to `CONFIDENTIAL`, selects an eligible semantic model profile
through the existing deterministic router, and invokes the LangGraph multi-MCP path.
The API never accepts a model, provider, profile, execution zone, or client-controlled
data classification.

Start Factory and Knowledge MCP over HTTP first, then start the API locally:

```powershell
docker compose up --build -d factory-mcp knowledge-mcp
python -m industrial_ai_agent.infrastructure.agent_api
```

The API listens on `127.0.0.1:8000` by default. Open `http://127.0.0.1:8000/docs` for
Swagger UI, or submit one run directly:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/runs `
  -ContentType 'application/json' `
  -Body '{"message":"P4711 failed during production. Investigate what happened and check the current status of the relevant station. Then consult the local technical documentation for the relevant fault and provide a final diagnosis."}'
```

`GET /health` reports API process liveness. `POST /api/v1/runs` returns a UUID,
`success` or `limit_reached` status, the final answer when available, and normalized
tool calls. `GET /api/v1/runs/{run_id}` reads the local in-memory run record. Records
are lost at process restart and are not production persistence. Errors are sanitized:
unknown IDs return `404`, policy denial returns `403`, and unavailable models or MCP
services return `503`.

The API is local/demo only: it has no authentication, authorization, TLS, rate limiting,
streaming, durable persistence, or HITL resume endpoint. A remotely reachable deployment
requires those controls in a later slice. See
[FastAPI Application Boundary](docs/learning/fastapi-application-boundary.md).

## Persistent Factory Demo Data

ADR-014 makes PostgreSQL the persistent source of truth for structured
`FACTORY-DEMO-01` data and `document_catalog` metadata. Synthetic records cover P4711's
S02 positioning warning and S04 `QUALITY-09` rejection, recurring S02 failures, S02
maintenance, and an explicitly `RESTRICTED` S03 process parameter. The accompanying
local `demo_factory/` assets are real PDF, DOCX, PPTX, XLSX, and PNG files. Their
cataloged checksum and classification, rather than folder names, govern ingestion.

Copy `.env.example` to a local unversioned `.env` and replace the two PostgreSQL demo
password placeholders. Then start the persistent services:

```powershell
docker compose up --build -d factory-db factory-mcp knowledge-mcp
```

For the local single-instance demo, `factory-mcp` waits for `factory-db` health, runs
idempotent Alembic migration and deterministic seed bootstrap, drops the admin URL from
its runtime environment, and only then starts MCP. `knowledge-mcp` waits for the healthy
Factory service, so it never reads a partial catalog. A multi-replica or production
deployment should use a separate migration job again. Runtime MCP services use the
non-superuser `factory_app` database role. Each transaction sets a
parameterized, transaction-local `app.clearance`, and PostgreSQL Row-Level Security
filters classified rows independently of Python repository code. The server-injected
demo `SecurityContext` is `demo-engineer` with `CONFIDENTIAL` clearance; there is no
authentication yet. A future FastAPI JWT/OIDC adapter can construct the same context.

Knowledge MCP reads only RLS-eligible catalog rows before Docling parses, chunks,
embeds, or reranks documents. Classification propagates unchanged from catalog document
to parsed document, chunk, MCP result, and the run's effective classification. That
classification may rise but never silently fall; ADR-009 then rejects a public-cloud
model for confidential or restricted context. MCP network traffic is not model egress.

The named Hugging Face cache volume is intentionally outside the Knowledge image and is
writable for an initial local model-cache population. No model artifact, document, query,
chunk, embedding, or reranker input is baked into or sent outside the service. The
standard Compose Knowledge service is CPU-capable; host in-process use may select CUDA.
See [Persistent Factory Data](docs/learning/persistent-factory-data.md).

With both MCP containers and local Ollama running, execute the sequential real smoke:

```powershell
python scripts/smoke_test_fastapi.py
```

## Local Browser Demo

`frontend/` is a separate static browser client. It only knows the public JSON API; it
does not import Python code or know LangGraph, MCP, model routing, providers, or
retrieval. Start it independently of the API:

```powershell
python -m http.server 8080 --directory frontend
```

Open `http://localhost:8080`. The local FastAPI entry point explicitly allows only this
development origin by default. Set `AGENT_FRONTEND_ORIGIN` to the actual browser-client
origin when the local deployment changes; production requires a separately designed
origin, authentication, authorization, TLS, and rate-limiting configuration. The UI
submits `POST /api/v1/runs` and displays the public run ID, status, answer, and
normalized executed tool calls.

See [Browser Frontend](docs/learning/browser-frontend.md).

## Manual MCP Smoke Test

Run the local stdio client and server without an LLM or external service:

```powershell
python scripts/smoke_test_factory_mcp.py
python scripts/smoke_test_knowledge_mcp.py
python scripts/smoke_test_langgraph.py --confidential-troubleshooting
```

The server smokes print discovery and structured results. The LangGraph smoke uses only
`local_quality` for its confidential run and verifies
`get_product_history(P4711) -> get_machine_status(S04) -> search_documentation(...)`.

To run the networked deployment path, build and start both local services:

```powershell
docker compose up --build -d factory-mcp knowledge-mcp
python scripts/smoke_test_factory_mcp.py --transport http
python scripts/smoke_test_knowledge_mcp.py --transport http
python scripts/smoke_test_langgraph.py --confidential-troubleshooting --mcp-transport http
```

Factory defaults to `0.0.0.0:8001` and Knowledge to `0.0.0.0:8002`; their SDK-managed
endpoints are `http://127.0.0.1:8001/mcp` and `http://127.0.0.1:8002/mcp`. Both images
run as non-root and contain neither `.env` nor secrets. The Knowledge image contains no
model artifact: Compose uses the host Ollama endpoint for `qwen3-embedding:0.6b`, defaults
the reranker to CPU, and uses a persistent named Hugging Face cache volume for local
model artifacts; local in-process execution still selects CUDA when available. Docker deploys processes, while
MCP provides tool protocol and discovery. The unauthenticated HTTP endpoints are accepted
only for this local demo; remote or production deployment requires MCP authentication and
transport security. MCP network transport does not authorize model egress: confidential
troubleshooting uses the local profile under ADR-009, and Knowledge queries, chunks,
embeddings, and reranker inputs never reach `public_fast` or a public provider.

The current stable `langchain-mcp-adapters` release (`0.3.2`) still requires `mcp<2.0.0`,
so the temporary project-owned MCP SDK v2 compatibility bridge is intentionally retained.

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

## Tool Selection Eval

Run the unchanged versioned tool-selection dataset through the LangGraph MCP path:

```powershell
python -m evals.run_tool_selection --profile troubleshooting --mcp-transport stdio
```

The command prints a structured JSON report with per-case results, Tool Selection
Accuracy, and Argument Accuracy. See
[Tool Selection Evaluation Baseline](docs/learning/tool-selection-evaluation.md) for
metric definitions, interpretation, and optional local result output.

## Trajectory Eval

Run the unchanged versioned multi-step dataset through the LangGraph MCP path:

```powershell
python -m evals.run_trajectory --profile troubleshooting --mcp-transport stdio
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
