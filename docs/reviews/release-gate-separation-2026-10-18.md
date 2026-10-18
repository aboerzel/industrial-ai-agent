# Release Gate Separation — 2026-10-18

## Result

Software Verification: PASS

Unexplained software skips: 0

Local Runtime Preflight: HEALTHY

Local Runtime Qualification: QUALIFIED

Real provider failures: 0 SDK timeouts; 0 Ollama HTTP 500

Product failures: 0

Security failures: 0

Retries: 0

External runtime exclusions: NONE

Software correctness verified: YES

Runtime qualified: YES

Ready to commit: YES

A software PASS verifies project-owned deterministic contracts. It does not qualify an unhealthy or untested local AI runtime and does not establish that SANITY-01's historical root cause is fixed. Historical timeout evidence remains valid. No production model/runtime remediation was implemented.

## Baseline and evidence

Branch: `main`. HEAD: `d692e489f469777530e629e29ba05708759be5bc`. The working tree already contained staged/unstaged historical review documentation at task start; this implementation is uncommitted. This is verification of the changed harness, not certification of a clean committed HEAD.

Final tested fingerprint: `e5fdb1ec1c0e21b63133532102c7b9db186809f9fc2c8f35a4ee41ca4f7d24a1`. Files remained byte-identical throughout this final run: YES.

Evidence root: `D:/Freelance/release-gate-separation-20261018-1010`. Final commands, JUnit, browser artifacts, image IDs, preflight/native logs and independent outcome documents are in `full-final/`; the run identifier is `release-20261018-130803-f8ba2d33`. Initial status and hash manifests are retained alongside them. Evidence is local and is not staged.

## Audit before implementation

The inventory existed before repository implementation changes: `gate-inventory-before.md`, `assertion-inventory-before.json`, `journey-assertion-inventory-before.json`. It records 4,631 assertion locators, 1,053 Python test definitions, all 12 registered release journeys / 59 REQUIRED assertions, the original 16 and extended 30 reference actions. Parameterized execution counts come from the current runs.

| Existing area | Classification and release disposition |
| --- | --- |
| Backend, integration, frontend, safe browser | SOFTWARE_DETERMINISTIC; all existing contracts retained |
| Agent graph, routing/egress, provider transport/cleanup, auth/RLS, lifecycle | SOFTWARE_DETERMINISTIC through existing fakes/MockTransport and real isolated boundaries |
| Legacy 5, release 12, live reference actions | Previously LOCAL_PROVIDER_DEPENDENT; deterministic equivalents now retain the same assertions and real application paths; native modes retained |
| KDEP import/readiness/offline/provenance/classification | SOFTWARE_DETERMINISTIC deployment with real production image, cached CPU OCR/layout/reranking and deterministic embedding transport |
| Native chat/embedding, retrieval/chat and capacity/residency | LOCAL_PROVIDER_DEPENDENT; real CPU embedding and GPU chat are measured by runtime preflight and real journeys |
| Protected HITL/calibration/ticket execution | PROTECTED/MANUAL_ONLY; never executed on persistent demo state; deterministic approval/replay/idempotency regressions retained |
| Independent MCP browser-only claim | MANUAL_ONLY in browser reporting; actual MCP boundaries covered by deterministic integration, not silently called a browser PASS |

No assertion was removed to make the live model pass. Ad-hoc live reference/retrieval/capacity diagnostic tools remain opt-in native measurements; this run does not claim that every former diagnostic command was executed.

## Gate architecture

[ADR-021](../decisions/ADR-021-release-software-verification-and-local-runtime-qualification.md) defines independent SOFTWARE_VERIFICATION and LOCAL_RUNTIME_QUALIFICATION. [Quality gates](../quality/quality-gates.md) and [browser E2E](../learning/browser-e2e-journeys.md) document the commands and exact decisions.

```powershell
.\scripts\run-quality-gate.ps1 SOFTWARE
.\scripts\run-quality-gate.ps1 LOCAL_RUNTIME
.\scripts\run-quality-gate.ps1 FULL
```

FULL executes software then runtime and writes `release.json` plus `release.md` with separate SOFTWARE VERIFICATION, LOCAL AI RUNTIME QUALIFICATION and OVERALL sections. A nonzero process result never substitutes for reading those outcomes: 1 software failure, 2 runtime product/harness failure, 3 provider-blocked qualification, 4 strict unhealthy-provider skip.

The software test composition injects scripted responses only at the real OpenAI-compatible SDK HTTP transport. Real API/service, model capability/egress guards, LangGraph, tool dispatch/results, structured response handling, MCP, PostgreSQL RLS, run/checkpoint persistence, shipped UI and document routes remain active. No final API response is mocked for the deterministic twelve journeys or reference matrix. Knowledge uses a test-only lexical retrieval composition over the real RLS catalog; KDEP separately tests the production retrieval image with deterministic embedding wire responses.

## SOFTWARE VERIFICATION

| Gate | Result | Evidence / denominator |
| --- | --- | --- |
| backend | PASS | 2131/2137 passed, 0 failed, 6 documented skips |
| clean_build | PASS | 7/7 images, --no-cache |
| deterministic_agent_e2e | PASS | 12/12 journeys; 59/59 REQUIRED |
| fast | PASS | 1837 unit passes; one platform skip; frontend + Ruff + format + secret scan |
| frontend | PASS | 339/339 |
| historical_findings | PASS | C01-C06, R01-R06, N01, FC01-FC04, CERT-01: current deterministic regressions |
| integration | PASS | 279/284 passed, 0 failed, 5 documented skips |
| kdep | PASS | 5/5 passed, 0 failed, 0 documented skips; offline restart 1/1; isolated deterministic embedding transport |
| legacy_browser | PASS | 5/5 journeys; 30/30 REQUIRED; NOT_RUN=0 |
| reference_contracts | PASS | original 16/16; extended 30/30; actual API/MCP/RLS/persistence |
| safe_browser | PASS | 144 passed; 0 failed; 0 skipped; 0 flaky |

Result: **PASS**.

The five explicit KDEP opt-in skips in each broad backend/integration run are discharged by the separate 5/5 deployment execution plus successful offline restart. The Windows symlink capability limitation appears once in backend and once in FAST; it is not called PASS. Unexplained software skips: 0. Protected MANUAL_ONLY browser claims remain NOT_RUN and outside automatic PASS denominators.

The current complete regression suites cover C01-C06, R01-R06, N01, FC01-FC04 and CERT-01; status is derived from the current tests rather than inherited from historical reports. SANITY-01 is a runtime qualification risk and is not closed by deterministic test results.

## LOCAL AI RUNTIME QUALIFICATION

Provider: Ollama

Model: qwen3.5:9b / Q4_K_M / local_quality / context 4096

Preflight: HEALTHY

Reason code: NONE

Real-model gate: PASS

Result: QUALIFIED

Provider calls: 100 (preflight 3, qualification 97)

Provider timeouts: 0

Ollama HTTP 500: 0

Maximum provider duration: 16.691153000021586

Product failures: 0

Security failures: 0

| Call | Seconds | Native tok/s | HTTP | SDK error | Health denominator |
| --- | --- | --- | --- | --- | --- |
| warmup | 16.691 | 44.49 | 200 | NONE | EXCLUDED warmup |
| measured-1 | 3.528 | 45.95 | 200 | NONE | MEASURED |
| measured-2 | 3.557 | 45.63 | 200 | NONE | MEASURED |

| Journey | Outcome | REQUIRED passed/planned |
| --- | --- | --- |
| s04-investigation | PASS | 6/6 |
| station-discovery | PASS | 4/4 |
| product-history | PASS | 4/4 |
| documentation | PASS | 8/8 |
| clearance-boundary | PASS | 9/9 |
| station-discovery-de | PASS | 4/4 |
| healthy-station-de | PASS | 3/3 |
| healthy-station-en | PASS | 4/4 |
| s04-investigation-en | PASS | 4/4 |
| product-centric-en | PASS | 3/3 |
| clearance-boundary-en | PASS | 6/6 |
| restricted-boundary | PASS | 4/4 |

Warm calls must BOTH finish in <20 s AND generate >=20 native tok/s. GPU chat, context 4096, CPU embedding with zero GPU bytes, expected resident models, valid LOCAL model assignments and admin-boundary denial/authorized access are checked before a runtime skip can be granted. Demo anonymous 403 and unauthenticated 401 are both valid denials; 200 is rejected. Missing evidence and generic exceptions cannot trigger a provider skip.

A valid unhealthy preflight yields only `SKIPPED_EXTERNAL_RUNTIME_UNHEALTHY` with reason `EXTERNAL_LOCAL_PROVIDER_UNHEALTHY`, never software failure or model PASS. After healthy preflight, a test becomes `BLOCKED_BY_LOCAL_PROVIDER` only with its owned execution trace/run/span, SDK APITimeoutError, unique matching Ollama HTTP 500 latency and cancellation, and no preceding application exception. Independent tool/target, persistence, response, inventory, lifecycle or security defects remain FAIL_PRODUCT. Raw failed/blocked assertions remain unchanged and are never upgraded to PASS. Independent journeys continue once each; resume and retry-to-pass are not used.

## Harness regression tests and first evidence

54 focused Python cases pass, plus the frontend security-priority test. They cover A-H: software failure, healthy qualification, strict unhealthy skip, later positively correlated provider block, independent product failure, security precedence, generic exceptions and no retry. Additional controls cover incomplete plans, duplicate IDs, missing/ambiguous telemetry, 19 s with 8 tok/s, actual Ollama log decoding/trace correlation, preceding application errors, inventory-smoke failure stages, anonymous admin denial, inherited effective context and preceding embedding telemetry.

Development failures were retained, not relabelled: isolated fixture wiring/Windows event-loop setup, KDEP allowlisted hostname/protocol options, legacy worker-directory aggregation and PowerShell child execution policy were corrected only in the harness. The first complete `full-current/` run had SOFTWARE PASS but an invalid preflight before any chat request: the harness assumed anonymous 401 and stored num_ctx instead of the current demo 403 and effective loaded context. Its NOT_QUALIFIED report remains intact. The final `full-final/` run is a new explicit run after those harness corrections; failed real-model journeys were not retried. No production timeout/model/application change was made.

The intermediate `full-verified/` run also passed every software gate. Its three real chat calls all succeeded (cold warmup 40.391 s; measured warm 3.557 s / 45.65 tok/s and 3.608 s / 45.20 tok/s). It then remained NOT_QUALIFIED with StopIteration because the harness incorrectly required the CPU embedding model to remain resident after a later chat cold-load. No native journey ran. The correction records actual CPU/zero-GPU placement immediately after embedding inference, permits a subsequent normal unload, and rejects any resident embedding GPU allocation. No provider failure was retried or relabelled. These three earlier native calls are additional to the final-run counts above and remain preserved.

## Safety and integrity

Project stack: 20/20 healthy; unexpected restarts: 0; Agent API /ready: 200. Knowledge readiness is included in protocol-aware container health and API readiness. Protected ticket/event/parameter counters: `100|5|1` before and `100|5|1` after. Protected real side effects: 0. External model calls: 0.

Production source/config changes from task baseline: 0. Previous reports modified: NO. Production assignments, prompts, model tags, timeouts (SDK 45 s / Agent 90 s), CPU embedding policy, Docker resources and retries are unchanged. Disposable labelled test containers/databases are cleaned up; persistent project volumes/model caches are preserved. Git diff --check, Ruff, formatting and incremental secret scan pass. Commits: 0. Pushes: 0. No external deployment.

## Files changed

- `scripts/run-quality-gate.ps1`, `scripts/run_release_gate.py`, `scripts/release_contract.py`, `scripts/release_support.py`, `scripts/release_runtime.py`, `scripts/local_runtime_preflight.py`, `scripts/local_provider_evidence.py`
- `frontend/scripts/release-plan.mjs`, `frontend/scripts/run-e2e-journey.mjs`, `frontend/scripts/manual-e2e-runner-core.mjs`, `frontend/scripts/journey-execution.mjs`
- `tests/e2e/software-server.py`, `tests/e2e/software-knowledge-server.py`, `tests/e2e/fixtures/reference-actions.spec.mjs`
- `tests/fixtures/release_provider.py`, `tests/fixtures/release-embedding-server.py`, `tests/fixtures/local-runtime-preflight.json`
- `tests/unit/test_release_gate_separation.py`, `tests/frontend/release-gate-security.test.mjs`
- `AGENTS.md`, `README.md`, `docs/architecture/overview.md`, `docs/quality/quality-gates.md`, `docs/learning/browser-e2e-journeys.md`, `docs/learning/knowledge-runtime-dependencies.md`, `docs/decisions/ADR-021-release-software-verification-and-local-runtime-qualification.md`, this new review and matching ignored German documentation (except AGENTS).

Preexisting dirty review reports are not task changes. The complete changed-harness fingerprint and initial/final manifests provide the exact file list and integrity evidence.

## Overall

Software correctness verified: **YES**.

Local model runtime qualified: **YES**.

This separates software proof from runtime qualification; it is not a remediation or permanent closure of SANITY-01. Ready to commit the gate architecture: **YES**. Nothing was committed.
