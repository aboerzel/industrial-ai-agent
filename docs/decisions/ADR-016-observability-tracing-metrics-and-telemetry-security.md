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
```

The Collector is the central telemetry boundary. Grafana is the local analysis UI,
Tempo stores distributed traces, Prometheus stores metrics, and Loki stores structured
logs. Docker Compose provisions all configuration. Honeycomb, Grafana Cloud, and other
OTLP-compatible targets are optional future Collector exporters.

Every application run retains its UUID `run_id` as a business identifier. It is a safe
span/log attribute. OTel `trace_id` and `span_id` remain OTel identifiers; neither
replaces `run_id`. FastAPI auto-instrumentation creates inbound request spans.
The current API emits operational spans for `agent.run`, `model.routing`, `llm.call`,
`mcp.discovery`, `mcp.tool`, `retrieval.search`, `approval.resume`,
`maintenance_ticket.create`, and `persistence.run_store`. Future stable owned
boundaries may add `retrieval.embedding`, `retrieval.lexical`, `retrieval.fusion`,
`retrieval.rerank`, `approval.wait`, and checkpoint spans.

The initial API trace covers its own stable boundaries. `retrieval.search` represents a
Knowledge MCP call in the API trace; the current MCP transport does not propagate OTel
context into the separate Knowledge MCP process, so its embedding, lexical, fusion, and
rerank operations are not yet child spans. LangGraph checkpoint load/save are likewise
not instrumented because no stable public boundary exposes those operations without
wrapping framework internals. The explicit run-store boundary remains the durable
persistence measurement.

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

The telemetry span helper disables SDK exception recording and writes only the
allowlisted sanitized error type/code. The Collector also deletes accidental SQL,
source-code-path, exception-stacktrace, and raw/dynamic HTTP request attributes, plus
dynamic `service.instance.id`. Fixed Python logging events retain only event name,
severity, resource service name, trace/span correlation, optional `run.id`, and safe
error code.

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
* Raw prompts and results require a separate classification-governed decision. Langfuse
  is explicitly out of scope for this slice.

## Alternatives Considered

### Direct vendor SDKs or a custom tracing platform

Rejected. Both couple behavior to an analysis backend and duplicate OTel capabilities.

### Grafana Cloud or Honeycomb in the first slice

Deferred. The local self-hosted demonstration needs neither cloud credentials nor
external data egress. The Collector preserves the future OTLP export path.

### Store full prompts and results for debugging

Rejected. It conflicts with classification and data minimization. A later Langfuse slice
may introduce governed prompt/response observability under a dedicated policy.

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
