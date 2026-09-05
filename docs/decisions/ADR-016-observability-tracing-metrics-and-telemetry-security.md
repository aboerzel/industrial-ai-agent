# ADR-016: Observability, Tracing, Metrics, and Telemetry Security

## Status

Accepted

## Context

The local multi-service Industrial AI Agent needs correlated operational visibility.
Telemetry must not turn prompts, tool results, classified documents, credentials, or
database details into a secondary data channel.

## Decision

OpenTelemetry (OTel) is the vendor-neutral instrumentation standard. OTel SDK usage is
confined to Infrastructure adapters and composition roots; Domain and Application code
do not know OTel SDK types or backend-specific APIs.

The local self-hosted baseline is:

```text
Application -> OTLP -> OpenTelemetry Collector -> Tempo (traces)
                                        -> Prometheus (metrics)
                                        -> Loki (logs)
Grafana -> Tempo + Prometheus + Loki
Application -> shared OTel TracerProvider -> Langfuse (LLM/agent observations)
```

The Collector is the central telemetry boundary. Grafana is the local analysis UI,
Tempo stores distributed traces, Prometheus stores metrics, and Loki stores structured
logs. Docker Compose provisions all configuration. Honeycomb, Grafana Cloud, and other
OTLP-compatible targets are optional future Collector exporters.

Langfuse v4 is a complementary local LLM/agent observability system, not a replacement
for the OTel/Collector/Grafana stack. Its current official self-hosted Compose topology
uses `langfuse-web`, `langfuse-worker`, PostgreSQL, ClickHouse, Redis, and MinIO with
persistent named volumes. The local UI is `http://localhost:3001`; the separate port
avoids Grafana's `3000`. It is configured through non-committed environment variables.

The current Python `langfuse` v4 SDK attaches its `LangfuseSpanProcessor` to the already
owned OTel `TracerProvider`; it neither installs a replacement global provider nor adds
an OTel Collector exporter. A strict SDK `should_export_span` callback permits only the
project-owned `agent.run` span as a Langfuse `agent` observation and its `llm.call` child
as a Langfuse `generation`. HTTP, SQL, persistence, framework, MCP, retrieval, and
other OTel spans remain in Tempo only. The shared OTel trace ID is therefore the
Langfuse trace identifier, while `run_id` is copied to allowlisted Langfuse observation
metadata. This preserves `run_id` -> OTel trace -> Langfuse trace/observation
correlation without turning any identifier into a Prometheus label.

The `ObservedLLMClient` infrastructure decorator is the sole Langfuse data boundary. It
captures profile, configured provider/model, classification, status, call latency, and
only token fields present in an actual provider response. The OpenAI-compatible adapter
maps `prompt_tokens`, `completion_tokens`, and `total_tokens` when supplied; absent or
malformed values remain explicitly `unavailable` and are never estimated. The local
Ollama profiles explicitly configure API monetary cost as USD `0`; that means no billed
model API call, not electricity, hardware, or total cost of ownership. External provider
cost remains unavailable in the application unless a reliable Langfuse model definition
matches it or an explicit profile cost is configured. Langfuse may calculate matching
model-definition costs from ingested usage; it is not an authorization or accounting
enforcement source.

The local stack also has one dedicated `observability_mcp` service. It is a read-only
Infrastructure query adapter, not an observability store and not an agent loop. Its
fixed tools retrieve a run trace, metadata-only trace logs, trace-correlated metric
context, bounded service health, and deterministic evidence aggregation. It uses only
Tempo trace search/by-ID, Loki range query, and Prometheus range-query APIs with
server-constructed queries, fixed known-service names, a 48-hour maximum lookback, and
bounded results. It exposes neither TraceQL, LogQL, PromQL, raw HTTP, nor arbitrary
telemetry attributes. `investigate_run` reports evidence and limitations; it never
claims an unproven root cause. The response boundary repeats the telemetry allowlist,
because stored telemetry remains potentially sensitive. It reuses ADR-015's
server-derived identity and a `READ_OBSERVABILITY` permission; trace context never
establishes identity, clearance, or permission.

Every application run retains its UUID `run_id` as a business identifier. It is a safe
span/log attribute. OTel `trace_id` and `span_id` remain OTel identifiers; neither
replaces `run_id`. FastAPI auto-instrumentation creates inbound request spans.
The current API emits operational spans for `agent.run`, `model.routing`, `llm.call`,
`mcp.discovery`, `mcp.tool`, `retrieval.search`, `approval.resume`,
`maintenance_ticket.create`, and `persistence.run_store`. Future stable owned
boundaries may add `retrieval.embedding`, `retrieval.lexical`, `retrieval.fusion`,
`retrieval.rerank`, `approval.wait`, and checkpoint spans.

The API trace spans MCP process boundaries through standard W3C `traceparent` and
`tracestate` propagation on Streamable HTTP requests. The Infrastructure client attaches
the global OTel propagator through the public `httpx2` request-hook API, and each MCP
process adds maintained OTel ASGI middleware to its public Starlette app. This establishes
the remote parent before the MCP SDK dispatches a request. Factory emits `factory.tool`;
Knowledge emits `knowledge.search` with `retrieval.embedding`, `retrieval.lexical`,
`retrieval.semantic`, `retrieval.fusion`, and `retrieval.rerank` beneath it where those
stable owned boundaries exist. The service names are `industrial-ai-agent`,
`factory-mcp`, and `knowledge-mcp`. Bearer authentication remains an independent
ADR-015 concern: trace headers neither establish identity nor influence clearance or
permissions. Missing or malformed context starts a valid independent server trace and
never fails an MCP business request.

The MCP SDK also emits its own protocol-level request spans. They are correlated through
the ASGI server parent but are not treated as the project-owned operational boundary.
LangGraph checkpoint load/save remain uninstrumented because no stable public boundary
exposes those operations without wrapping framework internals. The explicit run-store
boundary remains the durable persistence measurement.

Logs, metrics, and traces use different models. Logs retain sanitized structured events
and trace/span/run correlation. Metrics use bounded labels and aggregate signals.
Traces capture bounded timing and safe metadata. `run_id`, `trace_id`, `span_id`,
product IDs, user text, prompts, and document content MUST NOT be Prometheus labels.

Telemetry is classified metadata, not an alternate data channel. The allowlist covers
operation names, `run_id`, status, classification, model profile/name, execution zone,
MCP server/tool/operation, bounded result counts, durations, provider-supplied token
counts, sanitized error type/code, and OTel correlation identifiers. Prompts, model
response text, tool-result content, document chunks, authorization headers, bearer
tokens, database URLs, SQL parameters, secret paths, and arbitrary exception payloads
are forbidden by default. `RESTRICTED` runs emit metadata-level telemetry only. The
Collector adds an attribute deletion policy. OTel does not bypass ADR-009 model egress,
ADR-014 RLS, MCP authorization, or HITL. Exporter failure is non-fatal when telemetry is
optional.

Langfuse starts metadata-only. Its allowed data is `run.id`, model profile/provider/name,
classification, success/failure, latency, provider-reported token counts, and an
explicit API-cost status/value when configured. It receives no prompts, model outputs,
tool arguments/results, retrieval content/chunks, SQL, credentials, authorization
headers, database URLs, stack traces, or arbitrary exception messages. The same Python
allowlist builds its Langfuse GenAI/metadata attributes, so Langfuse cannot bypass the
ADR-016 privacy boundary. Langfuse unavailability, incomplete credentials, processor
initialization failure, flush failure, or backend export failure fails open for business
execution.

The telemetry span helper disables SDK exception recording and writes only the
allowlisted sanitized error type/code. The Collector also deletes accidental SQL,
source-code-path, exception-stacktrace, and raw/dynamic HTTP request attributes, plus
dynamic `service.instance.id`. Fixed Python logging events retain only event name,
severity, resource service name, trace/span correlation, optional `run.id`, and safe
error code. Factory and Knowledge use the fixed `mcp.server.completed` and
`mcp.server.failed` events; their resource `service.name` lets Loki distinguish the
emitting service without payload logging.

FastAPI uses maintained OTel instrumentation. SQLAlchemy auto-instrumentation remains
disabled because statement capture would add avoidable RLS and sensitive-data exposure
risk. Explicit persistence-boundary spans are used instead. Custom metrics cover business
signals missing from framework instrumentation:
runs, errors, LLM calls, MCP calls, retrieval calls, and approvals.

## Consequences

* Local developers get reproducible dashboards, traces, metrics, logs, and versioned
  Grafana provisioning after `docker compose up`.
* Infrastructure decorators at existing client/provider boundaries replace a custom
  tracing platform or a second agent loop.
* Collector/backend outages do not fail valid business work but degrade observability.
* Each MCP service configures the same optional bootstrap with its own stable resource
  service name and exports its bounded metrics through the Collector.
* `observability_mcp` has stable resource service name `observability-mcp`; observing
  its own calls is permitted, but its fixed tools never recursively initiate RCA.
* Langfuse enables local LLM usage/cost exploration and later dataset/evaluation links,
  while versioned repository eval datasets and deterministic scoring remain unchanged.
  A later slice may connect a curated, classification-governed subset to Langfuse
  datasets/experiments; it must not migrate or weaken the existing eval framework.
* Langfuse's model API cost is distinct from infrastructure cost and total cost of
  ownership. A Cost MCP remains unimplemented until real consumption requirements show
  that Langfuse's usage/cost source is insufficient.

## Alternatives Considered

### Direct vendor SDKs or a custom tracing platform

Rejected. Both couple behavior to an analysis backend and duplicate OTel capabilities.

### Grafana Cloud or Honeycomb in the first slice

Deferred. The local self-hosted demonstration needs neither cloud credentials nor
external data egress. The Collector preserves the future OTLP export path.

### Store full prompts and results for debugging

Rejected. It conflicts with classification and data minimization. Langfuse remains
metadata-only until a separate governed prompt/response decision is accepted.

### Isolated Langfuse TracerProvider

Rejected. The current SDK documents that isolated providers can create incomplete or
orphaned trees when sharing OTel context. Attaching a strictly filtered processor to the
existing owned provider preserves the agent/generation hierarchy and avoids exporting
infrastructure spans to Langfuse.

### Use only logs or only traces

Rejected. Logs, metrics, and traces answer different operational questions and need
correlation, not conflation.

## Relationship to Existing Decisions

ADR-003 keeps OTel implementations in Infrastructure. ADR-008 and ADR-009 remain the
authoritative model-routing and egress controls. ADR-010 and ADR-011 retain the sole
LangGraph loop and approval semantics. ADR-012 retains MCP discovery and transport
boundaries. ADR-013 retains FastAPI as the public boundary. ADR-014 retains PostgreSQL
and RLS as persistent-data and authorization enforcement; observability never replaces
or weakens those controls.

## Runtime MCP Refinement

The independent `runtime-mcp` service instruments only its bounded read operations:
`runtime.run.lookup`, `runtime.run.list`, `runtime.trajectory.lookup`,
`runtime.approval.lookup`, and `runtime.failure.lookup`. It uses the same telemetry
allowlist and optional failure behavior as the other MCP services. A run UUID may be a
span and log correlation attribute, never a metric label. Runtime projections and
database values are not exported as telemetry. Runtime MCP and Observability MCP remain
independent read adapters: the former reports persisted application facts; the latter
reports distributed telemetry; a client such as Codex performs any evidence correlation.

## Agent Run Profile Refinement

Agent, persistence, MCP-discovery, MCP-tool, retrieval, and model-routing telemetry
uses the resolved run classification and bounded `run.profile` attribute rather than a
hard-coded confidential value. The attribute is allowlisted for traces and bounded
metrics. It never changes identity, clearance, authorization, egress, or payload
capture, and `run_id` remains excluded from metric labels.
