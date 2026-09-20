# ADR-019: Model Catalog, Assignments, and Execution Policy

## Status

Accepted

This decision supersedes the routing-oriented Model Profile selection in ADR-002 and
ADR-008. It does not supersede ADR-009: the existing data-classification and model-egress
policy remains authoritative and unchanged.

## Context

The first model-selection implementation combined deployment configuration, model
metadata, security eligibility, capability filtering, quality/cost preferences, and
automatic selection in Model Profiles. That was useful while proving deterministic
routing, but it made a configured preference look too much like authorization and made
the effective model depend on runtime availability.

The system now needs persistent operator configuration, future specialized model slots,
and an auditable decision for every model attempt. These concerns must remain separate.
The effective `DataClassification` is trusted server-side run state. Neither a prompt,
tool argument, MCP argument, document, database record, nor downstream model may replace
or lower it. Derived information retains that classification until a future explicitly
trusted declassification mechanism exists.

## Decision

### Catalog and identity

`config/model_catalog.toml` is the pure catalog of configured models. A stable `model_id`
is the canonical identity in code, persistence, configuration references, API mutation
payloads, and telemetry correlation. `display_name` is mutable presentation metadata and
is used only by user-facing UI and dashboards. The catalog records provider configuration,
execution zone, the existing per-model maximum-classification security constraint,
cost/quality classes, an extensible individual capability set, and optional
per-invocation incompatible-capability combinations; it contains no
classification routing, task routing, priority, automatic-routing flag, or default.

### Consumers, assignments, and requirements

A `ModelConsumerId` is an extensible stable string. Phase 1 implements the `agent`
consumer and permits future specialized slots such as `vision.vlm`,
`vision.object_detection`, `vision.segmentation`, and `knowledge.embedding` without a
closed enum.

PostgreSQL stores one assignment per `(consumer_id, data_classification)` and refers only
to a catalog `model_id`. Assignment is configuration and never grants authorization.
Consumer capability requirements are application policy separate from catalog metadata.
They describe one concrete provider invocation, not the union of capabilities used
somewhere in a workflow. The implemented `agent` uses `text` + `tool_calling` for each
tool-decision call, `text` + `structured_output` for its separate optional final-output
normalization call, and `text` for a plain-text call. The already implemented MCP-side
RCA explanation uses the specialized `rca.reasoning` consumer and requires `text` +
`structured_output` in its one structured invocation. Future specialized requirements
are added only with their workflow.

A catalog entry states whether a model/provider supports each individual capability.
When an integration cannot use two otherwise supported capabilities in one request, it
declares `incompatible_capability_combinations`. The constraint applies only to one
provider invocation. For example, a model that supports Tool Calling and Structured
Output individually but not together remains compatible with an agent run that performs
one tool-decision request followed by one separate structured-output request.

Migration seeds `agent` assignments only where the previous effective intent is unique:
PUBLIC, INTERNAL, and CONFIDENTIAL use `nvidia_quality`. It does not seed RESTRICTED,
because the old router selected `local_fast` for restricted information and
`local_quality` for restricted troubleshooting. Inventing one would silently change one
path. Restricted execution therefore fails closed with `MODEL_NOT_CONFIGURED` until an
operator makes an explicit assignment. The existing RCA reasoning choice is unambiguous,
so migration also seeds `rca.reasoning` with `nvidia_quality` through CONFIDENTIAL and
`local_fast` for RESTRICTED.

### Resolution and execution

The central resolution sequence is:

```text
trusted effective DataClassification + consumer_id
    -> persistent assignment
    -> catalog model
    -> capability validation
    -> ADR-009 security authorization
    -> provider-boundary security authorization
    -> invocation
```

Missing assignments, unavailable providers, missing credentials, capability mismatch,
rate limits, cost, and latency never select another model. No automatic fallback exists.
Capability mismatch denies with `CAPABILITY_MISMATCH`. The existing egress policy denies
with `EGRESS_DENIED`. Missing configuration denies with `MODEL_NOT_CONFIGURED`.

The provider adapter boundary receives the trusted effective classification and repeats
authorization through the same policy service before serializing or sending protected
content. This applies transitively to models reached through tools or MCP and to future
vision, embedding, or specialized models. Tool/MCP data can raise effective
classification monotonically but cannot lower it. Model selection never changes database
RLS, document, retrieval, MCP, tool, hardware, or persisted-investigation access.

### Deterministic automatic selection

An assignment has an explicit selection mode. `MANUAL` preserves the assigned `model_id`
resolution described above. `AUTO` persists only `QUALITY_FIRST` or `COST_FIRST`; the
concrete model selected for a run is execution evidence, never configuration state. The
migration marks every existing assignment as `MANUAL`.

For `AUTO`, the resolver first filters the loaded runtime catalog by static availability:
an API-key-authenticated model is eligible only when its configured key environment
variable is non-empty. Local catalog entries represent configured local runtime endpoints;
the filter does not actively probe provider or model health. It then filters the remaining
entries by every call-level capability requirement and applies the authoritative ADR-009 security/egress
authorization to every capable candidate.
Security denial removes a candidate; it is never a weighted score or ranking penalty. If
no capable candidate exists the outcome is `CAPABILITY_MISMATCH`; if capable candidates
exist but all are denied it is `EGRESS_DENIED`; a missing or malformed automatic policy is
`MODEL_NOT_CONFIGURED`. `QUALITY_FIRST` orders highest quality, then lowest cost, then
stable `model_id`; `COST_FIRST` orders lowest cost, then highest quality, then stable
`model_id`. The selected candidate receives the same final capability and egress checks
and provider-boundary guard as a manual assignment.

Static unavailability is traceable as `runtime_unavailable` candidate metadata and is
separate from capability and egress decisions. Provider rate limits, timeouts, connection
errors, and temporary provider outages occur after selection and never cause reselection
or cross-provider fallback. Automatic candidate reasoning is emitted as
metadata-only trace spans; bounded metrics carry only selection mode and policy, not
candidate lists or protected model input.

### API and observability

The Phase 1 API exposes catalog reads, assignment reads, and assignment upsert by
`model_id`. It rejects unknown consumers/models and assignments whose execution zone can
never process the assigned classification under ADR-009. Capability mismatch may be
stored for experimentation but deterministically denies execution.

Each resolution emits a metadata-only `model.decision` trace with run/trace correlation,
consumer ID, model ID when known, classification, zone, provider, required capabilities,
capability and egress decisions, final outcome, sanitized error code, and timing. Provider
token usage remains on the existing LLM span. Prompts, documents, images, tool payloads,
and model responses are never copied into decision telemetry. Outcomes remain separately
queryable as `EXECUTED`, `EGRESS_DENIED`, `CAPABILITY_MISMATCH`, and
`MODEL_NOT_CONFIGURED`.

## Alternatives Considered

### Keep ranked Model Profiles

Rejected. Availability and cost/quality ranking make selection implicit and blur the
difference between operator preference and authorization.

### Store display names in assignments

Rejected. Presentation changes would invalidate configuration and historical correlation.

### Let assignment authorize egress

Rejected. Configuration mistakes would become security grants and bypass ADR-009.

### Automatically select another suitable model

Rejected for execution failure. Deterministic `AUTO` selection before invocation is
permitted because it applies capability and security hard filters and records the entire
decision. Fallback after a provider failure remains prohibited because it can cross
execution zones or providers and makes decisions harder to audit.

### Reject every capability-mismatched assignment

Not selected. Keeping it assignable supports controlled experiments, while execution still
fails deterministically and observably before provider access.

## Consequences

Model choice becomes explicit, persistent, stable, and auditable. Security remains a
separate fail-closed boundary and is checked twice without duplicating policy rules.
Deployments must run the PostgreSQL migration and explicitly configure ambiguous
assignments. Provider availability no longer changes model identity, so a configured but
unavailable provider produces an observable provider error rather than fallback.

Phase 2 can build UI controls over the narrow API without treating labels as identifiers.
Phase 3 can map stable model IDs to current display names in Grafana without rewriting
historical correlation.
