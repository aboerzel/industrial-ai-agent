# Golden Regression and Semantic Evaluation Strategy

## Purpose

Generative Agent output must be assessed through more than manual chat inspection.
The project therefore combines versioned Golden scenario contracts with conventional
tests and later semantic evaluation. Each mechanism has a distinct role:

* deterministic tests protect validation, authorization, RLS, egress, tool dispatch,
  persistence, limits, and structured-output invariants;
* Golden regression evaluates bounded, externally meaningful Agent-run artifacts
  against a reproducible scenario contract;
* future semantic evaluation assesses qualities that cannot be established reliably by
  deterministic matching;
* traces and metrics explain individual or aggregate runtime behavior, but do not
  replace quality evaluation.

The strategy implements ADR-005 and does not alter Agent execution behavior.

## Golden Dataset v1

The source-controlled dataset is [Golden Regression Dataset v1](../../evals/golden/v1/README.md).
It uses the same synthetic `FACTORY-DEMO-01` seed, classification matrix, bounded MCP
catalogue, and public non-disclosure contract as the acceptance catalogue. Each case has
a stable ID, request, response language, clearance, tags, and structured expected
projection.

The default CI path uses sanitized fake run artifacts. It requires no network, provider
credential, local model, database, or MCP service. This makes it a deterministic
contract-regression suite rather than a claim that model inference is bit-for-bit
reproducible.

```text
versioned Golden case
        + sanitized Agent-run artifact
        -> deterministic checks
        -> attributable case/check report
```

The runner validates terminal outcome/error code, response language, admitted tool
trajectory, structured investigation steps, identifiers, documents, selected known
facts, bounded next steps, DE/EN deterministic projection parity, and expected neutral
non-disclosure. It does not compare a whole answer with one fixed Golden response.

## Security Is a Hard Gate

Insufficient-clearance requests are expected successes when they produce the established
neutral `requested_data_unavailable` result. The Golden contract verifies that such a
result has no executed tool, structured identifier, document metadata, protected ID, or
classification hint. A protected-data or existence leak is a critical failure, never a
model-quality warning.

Golden evaluation complements, rather than replaces, the existing lowest-layer RLS,
security-context, identifier/document-derivation, and API normalization tests.

## Deterministic and Semantic Boundaries

v1 deliberately checks only robust contracts. Literal facts such as canonical IDs,
error codes, statuses, document IDs, and an explicitly known contradictory claim can be
checked deterministically without asserting a complete prose answer. It does not use
keyword heuristics to declare a response useful or causally correct.

The following dimensions are reserved for Phase 2 semantic evaluation:

* grounding and faithfulness beyond exact structured facts;
* observation-versus-inference quality and causal qualification;
* usefulness of findings and next steps;
* document/reference relevance;
* DE/EN semantic parity beyond tool, identifier, document, and outcome projections.

A later judge must use a provider-neutral interface, be calibrated against reviewed
human examples, report its rubric and provenance, and remain optional. It can never be
the sole authorization, non-disclosure, RLS, egress, or safety gate. Langfuse may track
optional experiment metadata, but it is not required for deterministic Golden CI.

## Regression Policy

Run the relevant Golden cases before accepting material changes to prompts, model
profiles, tool schemas, orchestration, retrieval, or context building. Add a regression
case when acceptance or evaluation identifies a meaningful scenario-level defect;
implement the lowest dependable guard first, then add the Golden scenario where it
protects an end-to-end contract.

Run the deterministic suite with:

```powershell
pytest tests/evals/
```

Validate the reviewable dataset shape without an Agent or provider call with:

```powershell
python -m evals.golden
```

The same runner can evaluate an externally supplied, sanitized JSON artifact map with
`--artifacts`; the runner never accepts raw prompts, tool payloads, document content,
or provider responses as part of that contract.
