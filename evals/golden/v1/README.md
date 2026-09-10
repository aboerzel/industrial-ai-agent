# Golden Regression Dataset v1

`cases.json` is a versioned, reviewable set of deterministic scenario contracts for
synthetic `FACTORY-DEMO-01`. It deliberately references the same seeded fixtures,
classifications, tool catalogue, and non-disclosure policy as the demo acceptance
catalogue. It does not create a parallel fixture universe.

Run the default deterministic suite with:

```powershell
pytest tests/evals/
```

Validate the dataset shape without invoking a model with:

```powershell
python -m evals.golden
```

Evaluate a sanitized JSON object keyed by case ID with:

```powershell
python -m evals.golden --artifacts path/to/artifacts.json
```

## What v1 checks

The contract runner evaluates sanitized Agent-run artifacts: terminal outcome and error
code, response language, admitted tool trajectory, structured investigation steps,
authorized identifiers/documents, bounded next steps, selected exact observation facts,
and neutral non-disclosure. It allows normal narrative variation and never compares a
complete answer against a fixed golden string.

Security denials are successful cases. An insufficient-clearance caller must receive a
neutral `requested_data_unavailable` outcome without a tool call, structured artifact,
or protected identifier/document in the answer.

## Scope

The v1 runner is provider-independent. Its CI tests consume fake, sanitized run
artifacts and do not require a cloud provider, local model, network, or database. An
optional caller may provide the same sanitized artifact shape from a controlled
integration harness. It therefore verifies deterministic contracts only; existing
Agent, RLS, MCP, structured output, and provider-error tests remain the lowest-layer
guarantees.

Semantic questions such as grounding completeness, causal qualification, next-step
usefulness, reference relevance, and DE/EN semantic parity beyond deterministic
projections are reserved for Phase 2. A future judge must be provider-neutral,
calibrated against human examples, optional, and never a security gate.
