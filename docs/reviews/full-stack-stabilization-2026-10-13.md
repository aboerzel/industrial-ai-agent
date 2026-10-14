# Full Stack Stabilization

## Iterations

### Iteration 1

Baseline: `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD `7bd09dc73204774e885b5dca9d589819a2ced0b1`. Initially no staged or tracked modifications; three untracked review reports and ignored translations from the earlier review were retained under `evals/results/stabilization-2026-10-13/iteration-01/historical-review/`.

Python 3.12.10 (configured PyCharm SDK), Node 24.19.0, npm 11.17.0, Docker 29.8.2, Compose v5.6.0. Environment keys only inspected; `.env` and `.env.example` remain structurally synchronized. Secrets are omitted.

Rebuild: all seven project images built with `docker compose build --no-cache --progress plain`; 20 services reached healthy state. Only project containers and the Compose network were removed, retaining all 11 named volumes and the unrelated Ollama container.

Tests: FAST passed (1,306 backend unit tests, one Windows symlink skip; 228 frontend tests; Ruff and format). Fourteen Chromium fixtures passed. Full isolated-database suite: 1,405 passed, 20 failed, one skipped. Original failure XML and sanitized command logs remain in iteration-01. Wheel build, dependency check and local links passed. Real-model E2E was NOT_RUN.

Failures and safe synthetic evidence:

| ID | Severity | Category | Root cause | Action |
| --- | --- | --- | --- | --- |
| S01 | HIGH | PRODUCT_DEFECT / egress | Local catalog zone did not constrain effective endpoint, redirects or environment proxies | Validate resolved local destination before SDK access; disable proxies/redirects |
| S02 | HIGH | PRODUCT_DEFECT / documents | Active MIME accepted; Blob preview executed same-origin script | Passive MIME allowlist, inert fallback, response CSP/nosniff/no-store, browser guard |
| S03 | MEDIUM | PRODUCT_DEFECT / persistence | Hidden investigation append and concurrent MAX+1 sequence allocation | Visible-parent requirement, transaction advisory lock, neutral fail-closed conflict |
| S04 | MEDIUM | PRODUCT_DEFECT / idempotency | Model action ID reused as globally unique ticket request ID across runs | Hash authoritative run/action tuple; retain original action approval binding; project stored station |
| S05 | MEDIUM | PRODUCT_DEFECT / composition | Default PostgreSQL stdio Factory passed approval port to wrong constructor | Inject port into executing MaintenanceTicketCapability |
| S06 | MEDIUM | TEST_DEFECT / provenance | Historical PASS artifacts aggregated without baseline binding or preflight | Bind HEAD/product/harness/run/model/assignments and require matching preflight |
| S07 | MEDIUM | PRODUCT_DEFECT / concurrency | Synchronous optional reasoning blocked async RCA handler | Offload reasoning to worker thread |
| S08 | MEDIUM | PRODUCT_DEFECT / projection | Runtime vocabulary omitted hardware actions and ticket reads | Extend bounded tool/action projections and persistence names |
| S09 | MEDIUM | TEST_DEFECT / acceptance | Long untrusted free text classified RESTRICTED but test principal CONFIDENTIAL | Use supported neutral S04 request; retain ten-run evidence assertions |
| S10 | MEDIUM | PRODUCT_DEFECT / logging | Embedded Alembic fileConfig disabled pre-existing failure loggers | Preserve existing loggers; real migration regression |
| S11 | MEDIUM | PRODUCT_DEFECT / limits | Automatic recovery preparation exceeded four-tool budget | Reserve preparation/execution capacity and guard resumed execution |
| S12 | MEDIUM | CONFIGURATION | E2E local passwords disagreed with gateway users | Synchronize two ignored .env values from existing local credential file |

Seventeen original failures share S05, one S09, two S10. Synthetic mock/local browser/database probes confirm S01-S08 and S11. No external inference, protected runtime write or real hardware action was performed. Temporary synthetic databases were removed by verified exact name.

Fixes and regression files: `tests/unit/test_stabilization_regressions.py`, `tests/integration/test_stabilization_database.py`, `tests/frontend/stabilization.test.mjs`, existing provider-contract and integration tests. All source changes belong to this stabilization, not pre-existing local work. Detailed final file manifest follows once verification completes.

Focused development failures are preserved separately: incomplete synthetic fixture fields, missing mocked browser event constructor and exact SDK argument expectations were corrected without weakening product assertions. A copied browser evidence script initially had an incorrect relative import; one path-corrected reproduction succeeded. These are TEST_DEFECT/artifact issues, not flakiness. Reproduction output is retained separately from the first failure.

Reason restart is required: production/configuration and regression-test changes were made. Focused successes cannot establish the baseline; a full clean rebuild and complete gates must run again.

### Additional fixture corrections in iteration 1

S13 — MEDIUM / TEST_DEFECT: the Factory integration fixtures still described the pre-approval execution schema. They omitted `run_id` and authoritative approval. The repaired stdio composition exposed this independently reproduced stale contract. The positive fixture now persists, approves and consumes the exact synthetic action; required schema assertions include run_id. The persistent-HITL free-text fixture was also narrowed to a supported neutral product request; approval/replay/concurrency assertions remain intact. Post-refactoring idempotency assertions now query the exact run/action hash. Twenty focused live-boundary tests, fifteen new unit regressions and fifteen Chromium fixtures passed. The actual aggregate CLI regression passed after its synthetic assertions included their required corresponding steps.

New browser test development failures concerned popup lifecycle assumptions: Chromium may download an inert Blob without a usable popup. The final regression asserts the actual Blob Content-Type at publication and fetch, before navigation, using the production API client. It does not claim a universal popup lifecycle.

### Iteration 2

Baseline: same main/HEAD; DIRTY with the explicit stabilization source/test manifest in `evals/results/stabilization-2026-10-13/iteration-02/modified.txt` and `untracked.txt`. Staged files remain empty. Ignored .env changes are limited to E2E_FRONTEND_PASSWORD and E2E_MODEL_ADMIN_PASSWORD; values omitted. All previous local reports retained. Full clean verification restarted; results pending.

### Iteration 2 outcome and stabilization refinement

Seven rebuilt images succeeded; all 20 services became healthy. Backend: 1,443 passed, one Windows symlink skip. Documented INTEGRATION script: 107 passed in a separately migrated disposable database. Chromium fixtures: 15 passed. FAST unit portion: 1,321 passed, one skip; frontend: 224 passed, seven failures; Ruff/format in FAST were consequently not reached. Independent checks were continued (syntax 32 files, wheel, dependencies, local links, diff).

The seven failures shared S06: five fixtures lacked the newly required current provenance, while two negative artifacts lost their explicit negative status. A focused correction preserves FAIL/HARNESS_ERROR/MISSING and supplies matching synthetic preflight metadata to positive fixtures. Resume also loads current assignments and requires a passing matching preflight before reusing measurements. Forty-four harness tests and the actual CLI aggregate/resume regression passed; security assertions were retained. These are refinements of S06, not new independent findings.

First stack smoke: 28/29 passed; Loki /ready initially returned 503 although its config-only healthcheck passed. Original smoke JSON preserved as stack-smoke-first.json. Logs and later direct /ready=200 justified one control check: 29/29 passed. Classification ENVIRONMENT / transient startup; the config-only healthcheck limitation is LOW and documented. Factory and Knowledge HTTP reads passed. Artifact download HEAD 429 and startup telemetry connection failures recovered; no external inference was invoked. Runtime errors and benign warnings are retained in sanitized logs.

Restart required because S06 production/harness refinements changed the baseline. No Phase-C review has started.

### Iteration 3

Baseline: `main`, `7bd09dc73204774e885b5dca9d589819a2ced0b1`, DIRTY. The source/test manifest contains 23 files: 18 tracked modifications and five new regression files. Four canonical review reports are untracked; four local German counterparts are ignored. There are no staged files. `.env` has only the two documented local E2E password-value changes. Python 3.12.10, Node 24.19.0, npm 11.17.0, Docker 29.8.2, Compose v5.6.0.

All seven project images rebuilt without application cache. All 20 supported services healthy, restart sum zero. Actual HTTP readiness succeeded before stack smoke; Loki required nine readiness polls (not test reruns). Backend: 1,443 passed / zero failed / one platform skip. INTEGRATION: 107 passed. FAST: 1,321 unit passes / one skip, 231 frontend passes, Ruff and format (225 files). Chromium: 15 passed. Stack smoke: 29 passed; Factory and Knowledge HTTP smoke passed. JavaScript syntax: 32 files; offline wheel, dependency consistency, local links and diff checks passed. Real-model E2E: NOT_RUN.

Runtime log review found no unresolved MEDIUM/HIGH/CRITICAL fault. Startup telemetry failures, config-only readiness limitations and optional Grafana provisioning warnings remain LOW; constraint violations and deliberate auth denials are EXPECTED_NEGATIVE_TEST. The local verification-artifact PowerShell parser failure occurred before execution and was corrected once; it changed no product file. All original evidence remains separate from corrected runs.

No stabilization fix was needed in this iteration. The source/test SHA-256 manifest was frozen at entry to Phase C. No source/test changes occurred during Phase C.

## Final stable iteration

Iteration 3: STABLE, with explicit LOW issues and NOT_RUN/manual coverage. Full verification is in [the verification report](full-stack-verification-2026-10-13.md). New independent findings are assessed separately in [the review](full-review-2026-10-13.md); they were not remediated or folded into the stabilization counts.

## Defects fixed automatically

CRITICAL: 0 found / 0 fixed. HIGH: 2 / 2 (S01-S02). MEDIUM: 11 / 11 (S03-S13). Thirteen concrete defects were addressed. S06 refinements in iteration 2 are counted once. Focused fixture-development mistakes are separately preserved, not counted as additional product defects.

| ID | Files changed | Regression / evidence |
| --- | --- | --- |
| S01 | infrastructure/llm/openai_compatible.py; provider tests | Actual SDK mock redirect stops; valid-request independent endpoint denials; C03 explicitly qualifies the three vacuous new cases |
| S02 | persistence/postgres.py; api/app.py; frontend/js/api.js | Passive MIME unit/Node/Chromium tests; response security headers; old active-content proof retained |
| S03 | api/app.py; api/postgres_run_store.py | Unknown/hidden append denial; four concurrent sequences; hidden later sequence fails closed |
| S04 | tools/maintenance_ticket.py; persistence/postgres.py; persistent-HITL assertions | Two approved runs with same action ID create distinct tickets; original action-ID claim unchanged; stored station projection |
| S05 | factory_mcp_server.py | Default PostgreSQL composition and real stdio integration; authoritative port retained |
| S06 | run-e2e-journey.mjs; manual-e2e-runner-core.mjs; E2E runner tests | Actual CLI missing-preflight/stale-artifact/resume checks; negative-status precedence |
| S07 | rca_mcp_server.py | Blocked optional explanation does not block an independent request; C01 concerns separate evidence/API paths |
| S08 | runtime_mcp_server.py; api/postgres_run_store.py | Hardware action/trajectory and ticket lookup projections |
| S09 | deterministic S04 acceptance fixture | Ten preserved HTTP/LangGraph/MCP/persistence evidence runs |
| S10 | migrations/env.py | Real embedded migration leaves diagnostic loggers enabled; complete-suite logging assertions pass |
| S11 | langgraph_troubleshooting_agent.py | Automatic preparation reserves execution capacity; resumed execution guard; two bounded fake recovery regressions |
| S12 | ignored .env, two values only | Configured credentials now give authenticated frontend 200; no secret recorded |
| S13 | Factory and persistent-HITL integration fixtures | Persisted synthetic approval and required run_id; positive/replay/concurrent assertions retained |

Complete source/test file manifest (all introduced by this task; initial local reports retained):

- `frontend/js/api.js`
- `frontend/scripts/manual-e2e-runner-core.mjs`
- `frontend/scripts/run-e2e-journey.mjs`
- `migrations/env.py`
- `src/industrial_ai_agent/agent/langgraph_troubleshooting_agent.py`
- `src/industrial_ai_agent/infrastructure/api/app.py`
- `src/industrial_ai_agent/infrastructure/api/postgres_run_store.py`
- `src/industrial_ai_agent/infrastructure/factory_mcp_server.py`
- `src/industrial_ai_agent/infrastructure/llm/openai_compatible.py`
- `src/industrial_ai_agent/infrastructure/persistence/postgres.py`
- `src/industrial_ai_agent/infrastructure/rca_mcp_server.py`
- `src/industrial_ai_agent/infrastructure/runtime_mcp_server.py`
- `src/industrial_ai_agent/tools/maintenance_ticket.py`
- `tests/e2e/fixtures/document-mime.spec.mjs`
- `tests/frontend/e2e-http-security.test.mjs`
- `tests/frontend/stabilization-aggregate.test.mjs`
- `tests/frontend/stabilization.test.mjs`
- `tests/integration/test_deterministic_s04_acceptance.py`
- `tests/integration/test_factory_mcp.py`
- `tests/integration/test_persistent_hitl_api.py`
- `tests/integration/test_stabilization_database.py`
- `tests/unit/test_openai_compatible_llm_client.py`
- `tests/unit/test_stabilization_regressions.py`

## Remaining LOW issues

L01: raw API access logs can retain query text. L02: Loki and Collector healthchecks validate config/components, not full readiness; explicit HTTP checks compensate locally. L03: MCP startup precedes Collector availability, producing transient export errors and possible lost startup telemetry. L04: Grafana reports missing optional plugin/alerting provisioning directories. These are four remaining baseline LOW issue groups, not new independent findings. Dependency deprecations, cold model-artifact downloads and historical Tempo WAL repair are recorded warnings/residual risks. The known filename defect is listed separately as a pre-existing product issue.

## Blocking unresolved issues

None at completion of Phase A/B. Historical finding-ID provenance and manual/live-model coverage limitations are explicitly qualified, not represented as full certification.

## Final result

STABLE. No commit, push or deployment. Eleven declared active volumes plus the unrelated legacy project volume `industrial-ai-agent_postgres-data` were retained (12 project-labelled volumes total); nothing was pruned. The unrelated Ollama container remains untouched. The final healthy stack stays running.

Final report checks: four ignored German counterparts, 16 valid local report links, zero secret matches, zero source/test deviations since Phase-C freeze and no staged files. Generated checker/proof fixture failures were diagnosed and preserved without product changes. C06 is a separate Phase-C intra-run approval-generation finding and was not fixed; stabilization counts refer to the reproduced Phase-A/B defect scopes.
