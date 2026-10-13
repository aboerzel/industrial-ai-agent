# ADR-009: Data Classification and Model Egress Policy

## Status

Accepted

The original future-tense design and pre-refinement examples below are historical.
**Initial Egress Matrix**, **Profile Maximum Classification Refinement**, and **Agent Run
Classification Policy Refinement** describe the current security rules. ADR-019 replaces
profile-based routing with `MANUAL`/explicit `AUTO`, forbids provider-failure fallback,
and specifies the implemented embedding boundary; it does not weaken this egress policy.
The original rationale remains intact.

## Context

An agent model request may contain more than the original user text. During a bounded
run it can accumulate system instructions, tool results, production data, retrieved
documentation, and other observations. A request that begins with public information
can therefore become sensitive before a later model call.

ADR-002 keeps provider details out of agent code, and ADR-008 defines deterministic
task-level selection among suitable Model Profiles. Neither model suitability nor a
prompt instruction can authorize data egress. Cost, quality, availability, or fallback
preferences must not decide whether sensitive information may be sent to an external
provider.

The project needs an inner, deterministic security boundary that classifies the
effective model context, permits only explicitly allowed execution zones, and prevents
the provider adapter from being invoked after rejection. This is a project-internal
technical classification. It makes no legal, contractual, or regulatory compliance
claim.

## Decision

### Deterministic Security Boundary

Data classification and model egress are deterministic Application and policy
responsibilities. An LLM must never decide whether sensitive data may be sent to an
external provider.

Before every model call, deterministic code must:

1. determine the effective Data Classification of the complete outbound context,
2. read and validate the selected Model Profile's Execution Zone,
3. apply the explicit egress policy, and
4. invoke the adapter only when the combination is explicitly allowed.

The policy is deny-by-default. Missing, unknown, malformed, or unsupported
classifications and Execution Zones are denied rather than assigned a permissive
default.

This ADR establishes the future boundary and semantics. It introduces no enum, policy
service, profile field, agent-state change, adapter guard, or runtime dependency.

### Initial Data Classification

The initial project classification has four ordered levels:

```text
PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED
```

Their project-internal technical meanings are:

* `PUBLIC`: information approved for processing by public providers, subject to the
  remaining security and operational policy
* `INTERNAL`: internal information that is not approved for public-provider processing
  by default
* `CONFIDENTIAL`: sensitive company or customer information requiring approved trusted
  processing
* `RESTRICTED`: the highest project protection class, permitted only for explicitly
  allowed local processing

These labels do not claim equivalence to any external legal or regulatory
classification standard. Changes to their meaning require a deliberate policy change,
not an LLM interpretation.

### Execution Zones

Model Profiles will conceptually carry a validated Execution Zone. The initial zones
are:

* `LOCAL`: execution in an explicitly configured local environment
* `PUBLIC_CLOUD`: execution through an external public-cloud model service

A local Ollama endpoint is an example of `LOCAL`; an external model API is an example
of `PUBLIC_CLOUD`. These examples do not select providers.

Provider name and Execution Zone are different concepts. A provider string does not
prove where a particular endpoint executes. Zone assignment must be explicit and
validated; a missing or unknown zone must never be interpreted as `LOCAL`.

Additional zones may be introduced only when a real trust or deployment boundary
requires them.

### Initial Egress Matrix

The initial policy explicitly allows only these combinations:

| Data Classification | `LOCAL` | `PUBLIC_CLOUD` |
|---------------------|---------|----------------|
| `PUBLIC`            | Allow   | Allow          |
| `INTERNAL`          | Allow   | Allow with an eligible profile maximum |
| `CONFIDENTIAL`      | Allow   | Allow with an eligible profile maximum |
| `RESTRICTED`        | Allow   | Deny           |

Every unlisted combination is denied. An unknown classification, unknown zone, missing
profile maximum, or incomplete Model Profile is denied. Public-cloud models may process
`INTERNAL` or `CONFIDENTIAL` context only when the selected deployment explicitly
permits that classification; they must never process `RESTRICTED` context.

An `Allow` entry is necessary but not sufficient for a model call: capability,
authentication, availability, task requirements, and other deterministic checks still
apply. This matrix controls model-data egress only.

### Profile Maximum Classification Refinement

Every configured deployment-level Model Profile carries a required, validated
`max_data_classification`. It is deny-by-default: a missing, malformed, or unknown value
rejects the profile configuration and is not treated as a permissive default. Router
eligibility and the final pre-provider egress boundary both require:

```text
effective_classification <= profile.max_data_classification
```

For the local demo, public-cloud profiles explicitly permit up to `CONFIDENTIAL` and
local profiles explicitly permit up to `RESTRICTED`. The execution-zone matrix remains
an independent restriction; model maximums do not replace it. The former preference for
public-cloud profiles is historical routing, superseded by ADR-019. Neither `MANUAL`
nor `AUTO` has an unconditional cloud preference. `RESTRICTED` has no eligible
public-cloud model.

### Classification Propagation

The effective classification of an agent run can become stricter as context is added.
Using the order above, the conceptual rule is:

```text
effective_classification = max(
    request_classification,
    tool_result_classifications,
    retrieval_result_classifications,
    other_added_context_classifications,
)
```

Application State must eventually own this propagation. Each new observation may raise
the effective classification but must not silently lower it. Removing text from a
prompt does not by itself prove that declassification is safe; any future declassification
or redaction mechanism requires an explicit, separately justified policy.

Example:

```text
PUBLIC user request with a selected model capped at PUBLIC
  -> get_product_history()
  -> CONFIDENTIAL production data
  -> effective classification = CONFIDENTIAL
  -> the selected PUBLIC-capped model is no longer eligible
```

The strengthened classification applies to every subsequent model call in that run.
Unknown input classification fails closed rather than participating in the ordering.

### Tool Results

Tool results must be able to carry a Data Classification when this policy is
implemented. Different capabilities may produce different classifications. Examples
include:

* public documentation as `PUBLIC`
* internal production data as `CONFIDENTIAL`
* highly sensitive customer data as `RESTRICTED`

These examples are not a classification of every current demo tool. Concrete labels
must be assigned deliberately with the implementation and tested; this documentation
change does not modify existing tool contracts.

### Retrieval Results

Knowledge-retrieval results must also become classifiable. Source and chunk provenance
from ADR-006 provides evidence for applying source-specific classification, but
provenance alone is not an authorization decision.

A `PUBLIC` user request does not make retrieved content public. If retrieval adds
`CONFIDENTIAL` content, the effective classification becomes `CONFIDENTIAL`, and that
content must not be sent to a model whose approved maximum is below `CONFIDENTIAL`.
An explicitly eligible CONFIDENTIAL-capable cloud model remains permitted by the
current matrix; `RESTRICTED` content never does.

### Model Calls and Defense in Depth

Security must not exist only as Model Profile configuration or one router predicate.
The architecture must support two deterministic controls:

* an eligibility filter before ADR-008 model selection
* a final egress check immediately before the provider adapter is called

Both checks use the current effective classification and validated Execution Zone. The
final check protects against stale state, configuration mistakes, incorrect fallback,
or a caller bypassing the normal routing path. A rejected call must not reach the
provider adapter.

This ADR does not require two duplicated policy implementations. One deterministic
policy can serve both enforcement points through explicit Application wiring when the
boundary is implemented.

The rule applies to any future external model role, including an embedding adapter from
ADR-007, without merging the separate `LLMClient` and embedding ports.

### Fallback and Failure

Policy rejection is not a recoverable signal to choose a less trusted zone. Fallback
may consider only profiles that remain explicitly allowed for the current effective
classification.

If no permitted model is available, the operation fails deterministically and the
external adapter is not called. A local outage, timeout, missing profile, or higher cost
must not cause an automatic fallback to `PUBLIC_CLOUD` for sensitive data.

### Logs and Traces

Observability must not bypass egress policy. Prompts, tool results, retrieval passages,
and model responses retain their security relevance when written to logs or traces.
Sensitive content must not be sent without control to external telemetry systems.

The concrete observability security design, field-level capture rules, retention, and
redaction remain future decisions. Until they exist, new tracing integrations must fail
closed or omit sensitive payload content rather than assuming telemetry is trusted.

### Configuration and Secrets

Execution Zone and other security-relevant Model Profile properties may be configured,
but their schema and values must be validated deterministically. Missing, unknown, or
invalid values are rejected. A public endpoint must never become `LOCAL` through a
default value or provider-name inference.

Cloud-provider secrets remain exclusively in environment variables or another approved
secret mechanism under the existing rules. Local unauthenticated providers must not
require artificial user-supplied secrets. Possession of a credential does not authorize
data egress.

### Testing (Original Pre-Refinement Plan)

The original test list below predates the profile-maximum refinement. Current tests
require `CONFIDENTIAL -> PUBLIC_CLOUD` to allow only with an explicitly eligible model
maximum and to deny otherwise. `RESTRICTED -> PUBLIC_CLOUD`, missing/invalid labels,
and unknown zones always deny before provider access. The legacy blanket confidential
denial below is historical, not an instruction to change current security semantics.

ADR-005 applies. The later implementation must include deterministic tests covering at
least:

* `PUBLIC` to `LOCAL` is allowed
* `PUBLIC` to `PUBLIC_CLOUD` is allowed by the initial policy
* `CONFIDENTIAL` to `LOCAL` is allowed
* `CONFIDENTIAL` to `PUBLIC_CLOUD` is denied
* `RESTRICTED` to `PUBLIC_CLOUD` is denied
* an unknown classification is denied
* an unknown Execution Zone is denied
* a more sensitive tool result raises the effective classification
* policy rejection cannot trigger cloud fallback
* the adapter is not called after egress rejection

Additional tests must cover configuration validation, monotonic propagation, retrieval
classification, and the final pre-adapter check when those slices are implemented. No
unit test requires a real cloud call.

### Hexagonal Architecture

Classification semantics, propagation, egress policy, and enforcement decisions belong
to the inner Application or policy side. Provider adapters and provider-specific DTOs
remain in Infrastructure. Infrastructure must not weaken, bypass, or reinterpret an
inner policy decision.

The Composition Root supplies validated profile configuration and explicit policy
dependencies. Agent, Domain, and tools must not import provider SDK types to enforce
egress. The exact package and port layout is deferred until implementation demonstrates
the smallest coherent shape.

### Relationship to Existing Decisions

ADR-002 remains valid. Model Profiles continue to hide concrete provider and model
details from agent code; ADR-009 adds explicit Execution Zone metadata and an egress
boundary when implemented. Secrets remain outside ordinary configuration.

ADR-003 governs dependency direction. Security policy is inner; concrete model adapters
are outer and may be invoked only after an allow decision.

ADR-004 remains valid. Effective classification becomes deterministic Application
State across the bounded run, while the LLM remains responsible only for contextual
judgment and cannot authorize egress.

ADR-005 governs deterministic policy tests. Security behavior is an exact guarantee,
not an LLM evaluation metric.

ADR-006 remains valid. Retrieval provenance supports classification evidence, and
retrieved content must participate in effective-classification propagation.

ADR-007 remains valid. Embeddings remain a separate model role and port, while the same
egress policy constrains any future external embedding calls.

ADR-008 is constrained by this decision. Security eligibility runs before task-level
routing, and the selected profile is checked again immediately before egress.

### Scope and Non-Decisions

This ADR does not select or introduce:

* an external data-loss-prevention platform
* encryption key management
* a regulatory classification standard
* an identity and access management system
* a tenant-specific policy engine
* an external policy-as-code platform
* automatic data classification by an LLM
* a redaction or anonymization pipeline
* a concrete observability platform
* production policy code, enums, profile fields, or runtime dependencies

These choices remain deferred until real requirements justify them.

## Alternatives

### 1. Enforce security only through prompt instructions

Rejected. A prompt cannot provide a deterministic guarantee, may be ignored or
misinterpreted by a model, and acts only after data may already have left the trusted
boundary.

### 2. Store security only in Model Profile configuration

Rejected. Configuration describes a profile but does not determine the effective
classification of dynamic context or guarantee enforcement immediately before a call.
A routing or configuration mistake could bypass the intended restriction.

### 3. Let the LLM classify data and decide egress

Rejected. Classification and authorization are security guarantees, not probabilistic
model judgments. The decision would be vulnerable to ambiguity, model error, and prompt
injection.

### 4. Use deterministic Data Classification and an egress policy

Accepted. Explicit ordered classifications, validated Execution Zones, deny-by-default
rules, monotonic propagation, and pre-adapter enforcement make the boundary testable and
independent of model behavior.

### 5. Introduce an enterprise DLP or policy platform immediately

Rejected for the current stage. Such a platform may later support broader organizational
requirements, but it would add integration, policy-language, deployment, and operational
complexity before the small local project needs it. The inner policy boundary remains
necessary even if an external enforcement adapter is added later.

## Consequences

### Guardrail Clarification

PostgreSQL RLS and retrieval clearance remain the primary data-access controls. As
defense in depth, the troubleshooting graph requires a valid classification on every
read observation when a run classification is present and rejects an observation above
that run clearance before it becomes a `ToolMessage` or later model context. This check
does not replace RLS, authorization, or the final egress check before every provider
call. Classification found in retrieved text has no authority to modify policy.

Positive:

* sensitive-data egress is governed by deterministic, testable rules
* security eligibility cannot be overridden by routing optimization or fallback
* classification follows tool and retrieval observations across a run
* unknown or incomplete security metadata fails closed
* final pre-adapter enforcement provides defense in depth
* provider and model replacement does not change classification semantics

Negative:

* future tool, retrieval, context, and Model Profile contracts need classification and
  zone metadata
* Application State must maintain monotonic effective classification
* conservative denial can reduce availability when classification or zone metadata is
  missing
* logging and tracing integrations require their own controlled egress treatment
* later declassification, redaction, tenant policy, or additional zones will require
  deliberate follow-up decisions

## Agent Run Classification Policy Refinement

The FastAPI run boundary separates target/profile resolution from effective request
classification. A server-owned `AgentRunProfile` defines domain behavior and the bounded
tool/MCP data scope; it does not classify the complete user message. A PUBLIC target
can retain its PUBLIC information behavior while its run is classified RESTRICTED.

Effective classification is the monotonic maximum of the profile minimum, every exact
recognized identifier, all authorized persisted investigation context, complete-request
content classification, and action/recovery requirements. All identifiers contribute;
their order cannot change this maximum. Partial identifiers are not trusted evidence.
Neither a known target nor discovery wording can suppress additional free text.

The bounded demo content policy accepts only explicitly supported neutral request forms
and canonical identifiers. Unrecognized content (including unknown identifiers and
arbitrary customer text) remains RESTRICTED, even alongside a PUBLIC identifier. This
is a conservative deterministic demo policy, not a general sensitivity detector or an
LLM judgment. Genuine identifierless follow-ups may inherit already-authorized persisted
context; lower-classified targets never lower that context minimum. Authenticated
clearance bounds authorization and identifierless discovery scope, not free-text safety.

The effective classification is persisted and used for model assignment, security
eligibility, final pre-adapter egress enforcement, and run visibility. MCP/RLS clearance
and allowed tools remain bounded by the resolved target profile: adding sensitive prose
must not grant broader factory access. Restoring a persisted policy accepts a higher
effective classification than the profile minimum but rejects any downgrade below it.

Authoritative classification signals at this boundary:

| Signal | Target/profile resolution | Effective classification |
| --- | --- | --- |
| Seeded product, station, and fault/error identifiers | Yes | Every recognized ID's seed classification |
| Syntactically valid maintenance-ticket identifiers | Ticket lookup profile | At least CONFIDENTIAL; unknown tickets remain indistinguishable |
| Server-owned run profile | Domain behavior and tool scope | Profile minimum |
| Authorized persisted investigation records | Identifierless genuine follow-up scope | Minimum from all authorized records |
| Complete message content | No | Unrecognized free text requires RESTRICTED |
| S04 position-reference recovery request | Dedicated recovery profile | At least CONFIDENTIAL, composed with all other signals |
| Authenticated discovery clearance | Identifierless discovery profile | Selected discovery scope minimum; never overrides content |
| Structured diagnostic target validation | Separate bounded diagnostic profile | INTERNAL only after trusted target validation |
| Classified tool/retrieval observations | No initial target decision | Runtime boundary checks before context/model use |

No LLM output, client classification label, or model assignment is classification
authority. PostgreSQL record classifications and RLS remain authoritative for source
data access; this demo resolver does not replace them.

The structured `INTERNAL_DIAGNOSTIC` endpoint uses a separate bounded target contract.
It contains validated resource identifiers and no free-form task text. The server
constructs its prompt and verifies the required target projections using an INTERNAL
RLS context. Missing, inaccessible, malformed, or higher-classified target evidence
returns neutral unavailable semantics and never causes a confidential retry or a
clearance increase. This structured diagnostic run remains INTERNAL for its complete
lifetime; dynamic classification escalation is explicitly out of scope for that path.
