# Final Release Certification — 2026-10-16

## Executive Summary

**Final result: PASS_WITH_FINDINGS.** The tested committed implementation reliably supports its troubleshooting, security and operational contracts with one specific diagnostic limitation: automatic run-trace lookup can select a later history-read trace instead of the available execution trace. This MEDIUM Observability/RCA defect does not break the tested core troubleshooting or authorization boundaries. CRITICAL 0; HIGH 0; MEDIUM 1; LOW 0.

Seven application images rebuilt without cache; 20 services are healthy and ready. All configured deterministic, browser and local-model gates passed with the explicit skips below. The modern product gate passed 12/12 journeys, 59/59 required assertions and 10/10 additional inventory controls. Its 97 provider spans match 97 Ollama completion requests, maximum 6.169295044 seconds, without provider timeouts or HTTP 500s.

No finding was repaired. No implementation, test, configuration, prompt, timeout, assignment or Docker limit was changed. Commits, pushes and external deployments: 0. Evidence: `D:/Freelance/certification-evidence-20261016-183506/`. Product artifacts: `evals/results/browser-e2e/release-certification-20261016-183506/`. Historical reports were context, never inherited PASS evidence.

## Baseline

| Item | Frozen value |
| --- | --- |
| Repository | `D:/Freelance/industrial-ai-agent` |
| Branch | `main` |
| HEAD | `aeba38ea418bb276a4f58880753524bd031d9827` |
| Initial status / staged / unstaged / untracked | CLEAN / none / none / none |
| Python | 3.12.10; PyCharm `.venv/Scripts/python.exe`; pip |
| Node / npm | v24.19.0 / 11.17.0 |
| Docker / Compose | 29.8.2 (`7fc2dff`) / v5.6.0 |
| Ollama | 0.33.2; existing separate container |
| GPU | RTX 3070, 8192 MiB, driver 617.42 |
| Assignments | Eight `agent`/`rca.reasoning` rows, MANUAL / `local_quality` |
| Initial loaded models | None; Knowledge subsequently loaded CPU embeddings |
| Initial containers / images | 20 project services plus original Ollama; exact image IDs retained externally |
| Integrity baseline | External SHA-256 manifest of 506 versioned files |

All expected remediations are committed: Knowledge (`16c8979`), references (`0e55a37`), cleanup (`0917924`), CPU embeddings (`2e8c1d7`), legacy harness (`aeba38e`). Git cleanliness was checked before certification work.

Contract review covered AGENTS, README, package definitions, Compose/Dockerfiles, architecture overview, ADR-001–020 statuses/refinements, Demo Auth/visibility, Knowledge runtime/capacity, browser/reference guides, scenarios, routing/egress, approval and current remediation documents. Superseded mechanisms remained historical. The external `requirements-and-gates.md` records the requirement matrix. No CI workflow is configured.

## Clean Docker Rebuild

**PASS, 7/7.** `docker compose down` preserved all volumes and original Ollama. `docker compose build --no-cache` rebuilt every current application image from unchanged committed sources. `docker compose up -d` started the complete supported stack with unchanged main-stack configuration.

| Image/service | Result | Image ID |
| --- | --- | --- |
| agent-api | PASS | `sha256:f3ba650521341a3fa32b679483899eaf7e298eee2610ef2c981d6b53cf0aa86c` |
| factory-mcp | PASS | `sha256:a96e5593022b0716b669c0fa85e66f405b2a6a10dfdd4aec4df679c726a218da` |
| knowledge-mcp | PASS | `sha256:0aafbd17c7af57aadd8698868791d4047d16c90fb91d0b25b8589f5f9435de04` |
| hardware-mcp | PASS | `sha256:e3dd6c77b16648f54d66fdaf0a01ab423bc61049617f26a8e1fd2070c18f3b38` |
| runtime-mcp | PASS | `sha256:52fa200e07ad5a460493b6aebde17df4be4a6e286b2459ed147f8fb9f48d560d` |
| observability-mcp | PASS | `sha256:833938e6d51640c1949fb604151d6462424bc21a3aaa55f673cdaea418d830db` |
| rca-mcp | PASS | `sha256:8524b8bb9c7417a496de7dabb267ac6f419aa9b35d7308ccf477991f0f7897e7` |

Frontend uses third-party Nginx and read-only source mounts. Other supporting images are third-party, not additional project build targets. Before/after container, image and volume inventories and complete build logs are external.

## Stack Readiness

**20/20 running, Docker healthy and actually ready; unexpected restarts 0.** Cold main/KDEP Knowledge initialization briefly exhausted healthcheck deadlines; Loki initially returned 503. First evidence is preserved. Readiness recovered without repair, changed limits or restart loops.

| Service | Running | Docker Healthy | Actual Ready | Restarts |
| --- | --- | --- | --- | ---: |
| agent-api | Yes | Yes | `/health`, `/ready` 200 | 0 |
| frontend | Yes | Yes | Gateway 200 and live browser flows | 0 |
| factory-db | Yes | Yes | SQL and non-bypass application-role RLS | 0 |
| factory-mcp | Yes | Yes | Authenticated protocol, inventories/reference reads | 0 |
| knowledge-mcp | Yes | Yes | Protocol and real retrieval | 0 |
| hardware-mcp | Yes | Yes | Protocol and read-only position status | 0 |
| runtime-mcp | Yes | Yes | Authorized persisted-run read | 0 |
| observability-mcp | Yes | Yes | Read operational; CERT-01 selection limitation | 0 |
| rca-mcp | Yes | Yes | Analysis with reasoning `none`; CERT-01 | 0 |
| otel-collector | Yes | Yes | Exported traces; collector scrape UP | 0 |
| prometheus | Yes | Yes | Readiness 200, target UP/no last error | 0 |
| loki | Yes | Yes | Actual readiness 200 after warmup | 0 |
| tempo | Yes | Yes | Readiness, search and trace retrieval 200 | 0 |
| grafana | Yes | Yes | `/api/health` 200 | 0 |
| langfuse-web | Yes | Yes | Health including database check 200 | 0 |
| langfuse-worker | Yes | Yes | Worker health succeeds | 0 |
| langfuse-postgres | Yes | Yes | SQL `SELECT 1` | 0 |
| langfuse-clickhouse | Yes | Yes | `/ping` succeeds | 0 |
| langfuse-redis | Yes | Yes | Authenticated PONG | 0 |
| langfuse-minio | Yes | Yes | Actual readiness 200 | 0 |

The separate original Ollama identity, start lifetime and storage were preserved. Post-test stability: **185.844 s observation**, **184.074 s between first/last samples**, twelve samples, no unhealthy services, readiness failures or unexpected restarts. CPU policy remains `num_gpu=0`; normal idle expiry is permitted.

## Test Inventory

Python means the configured interpreter; XML/log destinations are external.

| Gate | Command | Required | Scope |
| --- | --- | --- | --- |
| Full backend | Python `-m pytest tests -ra --junitxml=<evidence>/backend.xml` | Yes | Unit, integration, deterministic eval/scorer tests |
| Unit / FAST | `scripts/run-quality-gate.ps1 FAST` | Yes | Full unit/frontend, Ruff, format, secrets |
| Integration | `scripts/run-quality-gate.ps1 INTEGRATION` | Yes | Full integration, disposable PostgreSQL |
| KDEP | Python `-m pytest tests/integration/test_knowledge_container_runtime.py -v -ra` | Yes, opt-in | Clean image, isolated offline real models |
| Frontend | `npm --prefix frontend test` | Yes | Complete Node suite |
| Safe browser | `npm --prefix frontend run test:e2e:fixtures -- --retries=0` | Yes | All 144 registrations, once |
| Legacy browser | `npm --prefix frontend run test:e2e -- --retries=0` | Yes | Five independent sequential journeys |
| Live references | Fixture command selecting `reference-actions.spec.mjs`, live URL, retries 0 | Yes | 35 real-stack cases |
| Local real model | `npm --prefix frontend run e2e:manual -- --run-id release-certification-20261016-183506` | Yes | Twelve journeys, current unchanged plan, no resume/retry |
| Quality/build | Ruff/format/secrets, JS syntax, docs, dependencies, wheel, Compose, diff | Yes | Detailed below |

MANUAL_ONLY: `mcp_transport` and `hitl_execution`, two per journey (24 in the modern runner). **SAFE_TO_RUN:** independent read-only MCP discovery/result inspection, executed against Factory, Knowledge, Runtime, Observability, RCA and Hardware. Per-journey manual ledger entries remain NOT_RUN; independent evidence was not backfilled as automatic PASS. **UNSAFE_SIDE_EFFECT:** live HITL execution/approval/calibration, NOT_RUN; mechanisms tested only with fakes/disposable data. No further NOT_APPLICABLE or EXTERNAL_DEPENDENCY MANUAL_ONLY assertion type is registered. Historical standalone learning/benchmark commands are not additional current release-tier gates; external-provider benchmarks were forbidden.

## Backend

**2064 collected, 2058 passed, 0 failed/errors, 6 skipped**, 225.56 s. Includes 1764 unit, 279 integration and 15 deterministic eval/scorer passes. Separate gate executions below overlap these counts.

Five skips are explicit KDEP opt-ins, separately executed 5/5 PASS. `tests/unit/test_document_content_storage.py:47` cannot create a Windows symlink under current privileges: SKIPPED, never PASS.

All writes used labelled tmpfs PostgreSQL on loopback 55439 and disposable `verification_*` databases. `factory_app`: `rolsuper=false`, `rolbypassrls=false`. Admin access was confined to synthetic setup/migrations/fixtures. Disposable databases/container/network were removed; persistent demo data was never used for test writes.

Initial verifier setup errors are retained: container-only host seed path and a malformed JUnit argument that collected zero tests. Correct external harness arguments/host fixture path enabled the first actual complete execution above, without source/test/config repair. A Windows-escaped integration XML filename was moved outside the repository as new evidence.

## Integration

**279 passed, 0 failed, 5 KDEP opt-in skips**, 207.56 s, exact INTEGRATION script and disposable PostgreSQL. Migration/upgrade, sessions/RLS, MCP HTTP, persistent HITL/generation/replay, slow ticket I/O, relations, classification and discovery are covered. Original skips remain recorded despite separate KDEP success.

## KDEP

**5/5 PASS, 0 skipped**, 48.58 s. Real production imports, Docling/OCR/layout, embedding/CrossEncoder initialization, MCP readiness, retrieval provenance/classification and offline isolation passed. The rebuilt immutable image used its unmodified production command/healthcheck, existing read-only model/content caches, disposable PostgreSQL and separate local Ollama on an internal Docker network without cloud keys.

An additional actual offline restart reached healthy readiness: **zero download/import-error matches**, no internet route, no protected operation. Isolated resources were removed; original caches/Ollama remained intact.

## FAST

**PASS:** 1764 unit passes/one Windows skip; 338 frontend passes/no skips; Ruff lint PASS; format PASS (262 files formatted already); incremental secret scan PASS. No real-model calls.

## Frontend

Standalone suite: **338 passed, 0 failed/skipped**. Current cases cover auth/account/bootstrap/logout/login/switch/language/Monitoring/admin permissions, investigations/continuations/references/discovery, documents/filenames, server/transcript PDF, protected URLs, cross-tab/stale JSON/download/PDF, BFCache/pagehide, approvals and responsive/static behavior.

## Safe Browser

**144 PASS, FAIL/SKIP/FLAKY 0, retries 0.** Enumerated before execution; all cases ran once.

| Specification | Cases |
| --- | ---: |
| demo-auth | 50 |
| document-mime | 1 |
| fc03-discovery | 20 |
| fc04-transcript-blob | 15 |
| journey-evidence | 18 |
| r03-approval | 5 |
| reference-actions | 35 |

Safe synthetic/local fixtures include separately seeded disposable RLS infrastructure. They do not certify model semantics or live protected execution.

## Legacy Browser Gate

**5 PASS; FAIL/BLOCKED/HARNESS_ERROR/NOT_RUN/FLAKY 0; retries 0; 30/30 required assertions.** Every fresh context measured `/auth/me` 401, supported bootstrap and independently verified `demo-public`. Journeys A–E all executed. Frontend harness regressions additionally prove one failed worker cannot suppress subsequent journeys. Artifact: `evals/results/browser-e2e/legacy-2026-10-16T16-47-49-866Z/journeys.json`.

## Demo Auth

Five live identities PASS: metadata, clearance/roles, Configuration, switch, logout, logged-out refresh and explicit relogin. `demo-restricted`: RESTRICTED/no MODEL_ADMIN; `demo-admin`: PUBLIC/MODEL_ADMIN. No clearance selector, native Basic challenge, browser token injection or caller authority. Cookie: HttpOnly, SameSite=Strict, `/api/`. Language-only change preserves identity/context; logout/reload may reset the preference as documented.

## Station Visibility

Seed, non-bypass SQL/RLS, five Factory MCP inventories, live API/persisted/browser answers and modern-runner controls agree exactly:

| Identity | Stations |
| --- | --- |
| demo-public | S01 S05 |
| demo-internal | S01 S02 S03 S05 |
| demo-confidential | S01 S02 S03 S04 S05 S06 |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 |
| demo-admin | S01 S05 |

DE/EN controls pass without duplicates/hidden IDs. Deterministic real-RLS pipeline cases also inspect typed observations/model input under sparse, invented and fallback model output. Visibility is not inferred solely from prose.

## Product Visibility

Exact SQL/RLS, Factory MCP, API/persisted/browser inventories:

| Identity | Count | Products |
| --- | ---: | --- |
| demo-public | 2 | P4101 P4102 |
| demo-internal | 4 | P4101 P4102 P4900 P4901 |
| demo-confidential | 9 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 |
| demo-restricted | 11 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 P9001 P9002 |
| demo-admin | 2 | P4101 P4102 |

No duplicate/hidden IDs; completeness is independent of prose and the twelve-reference budget. Both extra EN inventory checks executed and passed. Their external helper's final assignment check received expected 403 because its PUBLIC session overrode the admin bearer: retained HARNESS_ERROR, not an inventory/product failure. Independent cookiefree admin reads confirm eight unchanged assignments; no EN model check was retried.

## Reference Actions

**Original 16/16; extended live 35/35 PASS:** 30 actions and five document/security/lifecycle controls. Each action returned 200/success, exact target, correct first read and persisted investigation binding. Unexpected neutral 404/HTTP 500: **0/0**. Includes DE/EN stations/products/faults/tickets, document Open/Download filenames, unknown/insufficient-clearance denials, reload and cross-tab. Reference origin grants no privilege.

## Real-Model E2E

**12/12 PASS, 59/59 required assertions evaluated/executed/passed, failed/blocked 0.** Additional inventory controls 10/10; three optional assertions also passed. All 24 MANUAL_ONLY ledger assertions remain NOT_RUN and excluded. No automatic retry/resume, external model or protected action.

| Journey | Required PASS | Category | Maximum provider seconds |
| --- | ---: | --- | ---: |
| clearance-boundary-en | 6/6 | PASS | 5.425 |
| clearance-boundary | 9/9 | PASS | 5.985 |
| documentation | 8/8 | PASS | 6.169 |
| healthy-station-de | 3/3 | PASS | 5.442 |
| healthy-station-en | 4/4 | PASS | 5.673 |
| product-centric-en | 3/3 | PASS | 5.537 |
| product-history | 4/4 | PASS | 5.495 |
| restricted-boundary | 4/4 | PASS | 5.904 |
| s04-investigation-en | 4/4 | PASS | 6.044 |
| s04-investigation | 6/6 | PASS | 5.976 |
| station-discovery-de | 4/4 | PASS | 4.885 |
| station-discovery | 4/4 | PASS | 5.650 |

PRODUCT_DEFECT, MODEL_VARIANCE, HARNESS_ERROR, SECURITY_DEFECT, BLOCKED_BY_PROVIDER and INFRASTRUCTURE_ERROR: **0**. Preflight records clean certified HEAD and harness fingerprint `c71286d8706360a4cba7c120df69938cbb9d5547405e286350dcc5ea942b1146`.

## Local Model Capacity

Chat `local_quality`/`qwen3.5:9b`: **100% GPU**, Q4_K_M/context 4096. Embedding `qwen3-embedding:0.6b`: **100% CPU**, persisted `num_gpu=0`, Q8_0/context 4096. No provisioning/unload/configuration intervention.

Three sequential embedding → Knowledge retrieval → local chat cycles PASS. Embedding **1.632/0.310/0.306 s**; retrieval **2.824/2.804/2.972 s**; complete API **9.043/8.448/8.400 s**. Six correlated provider calls: maximum **5.546 s**.

Product gate: **97 spans = 97 completion HTTP requests**, maximum **6.169295044 s**; calls >=45 s, SDK timeouts, capacity-related provider-unavailable/execution-timeout, Ollama HTTP 500: **all 0**. All **263** placement samples show full GPU chat and embedding `size_vram=0`; GPU co-residency 0. Global dedicated GPU memory **7.555–7.564 GiB**, shared **0.796–0.803 GiB**, including desktop/driver. Provider/API deadlines remain 45/90 s, retries 0.

## Regression Certification

All statuses are freshly measured; counts overlap broader suites.

| ID | Status | Current evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 async evidence/config/document I/O cases |
| C02 | CLOSED | 19 bounded provider/deadline/drain cases |
| C03 | CLOSED | 25 stabilization cases, guard spies/MockTransport |
| C04 | CLOSED | 31 TLS/destination cases; denied boundary counters zero |
| C05 | CLOSED | 14 documentation cases; active ADR/dependency review |
| C06 | CLOSED | 20 unit + 9 PostgreSQL generation cases |
| R01 | CLOSED | 29 raw provider authorization cases |
| R02 | CLOSED | 25 unit + 2 PostgreSQL owned ticket-I/O cases |
| R03 | CLOSED | 18 unit + 6 PostgreSQL + 5 browser generation cases |
| R04 | CLOSED | Failed-refresh/cross-tab/BFCache/stale fixtures and live proof |
| R05 | CLOSED | 19 client ownership/concurrent initialization/drain cases |
| R06 | CLOSED | Current auth docs/conformance, live sessions/legacy gate |
| N01 | CLOSED | 21 real-RLS hidden-station product relation cases |
| FC01 | CLOSED | 29 real-RLS ticket/hidden mandatory station cases |
| FC02 | CLOSED | 37 actual emitted-label projection cases |
| FC03 | CLOSED | 14 unit + 30 PostgreSQL/API, browser and live inventories |
| FC04 | CLOSED | 15 browser Blob cases, frontend and live downgrade proof |
| Knowledge dependency fix | CLOSED | Clean build; five real offline KDEP proofs |
| Reference fix | CLOSED | Original 16 and extended 35 live tests |
| Async cleanup fix | CLOSED | 14 current PCLEAN regressions |
| Capacity fix | CLOSED | Three cycles, 97 reliable calls, 263 samples |
| Legacy harness fix | CLOSED | Five journeys/30 assertions, no serial suppression |

Direct proofs: visible Product/Event with hidden Station retains the product and omits hidden relations (N01); visible Ticket/hidden Station returns neutral unavailable without metadata/reference/crash (FC01). Emitted CONFIDENTIAL relationships raise PUBLIC parent projections; PUBLIC-only data remains PUBLIC for RESTRICTED callers (FC02). Old approve/reject generation A cannot change B (R03/C06). Raw untrusted provider calls and PUBLIC_CLOUD HTTP endpoints fail before credentials/SDK/transport (R01/C04).

Live R04/FC04: captured CONFIDENTIAL PDF URL readable before PUBLIC switch, unreadable afterwards. Three delayed JSON/download/PDF completions reject with `SecurityContextChangedError`; no new URL is created. Cleanup **14/14 PASS** includes 350/750-ms residual work, heartbeat/independent API below 150 ms, off-loop closure, duplicate cancellation, active-call drain, bounded capacity and complete resource closure. All run/start/resume entrypoints use that owned lifecycle.

## Runtime Logs

Every project service and original Ollama was collected for the certification window, redacted and searched for requested error/auth/database/provider/session/approval/CUDA/OOM/OTel terms. Keyword hits are not defects. CERT-01 is a semantic correlation defect, not a runtime exception.

| Entries | Classification / assessment |
| --- | --- |
| Deliberate 401/403/neutral 404, hidden-run MCP LookupError stacks | EXPECTED_AUTH_DENIAL / EXPECTED_NEGATIVE_TEST |
| Cold health timeouts, Loki ring/503, early OTLP DNS/deadlines | EXPECTED_STARTUP_WARNING; recovered, no restart loop |
| Optional Grafana provisioning directories, Torch padding, idle MCP expiry, NO_COLOR | BENIGN_WARNING; required operation unaffected |
| Tempo removes incomplete older WAL block without `meta.json` | OBSERVATION; historical completeness unknown |
| ClickHouse “Logging errors to …”, Tempo `error=null` | Informational, not actual failures |
| Provider timeout/500/OOM/runner crash/persistent DB/RLS/migration error | No unexpected occurrence |

Unbounded Docker log pulls initially produced empty auxiliary files, preserved. Explicit bounded backlog/timestamp filtering recovered the window and matched 97 completions. An external diagnostic's first attempt assumed public-DTO timestamps and raised KeyError; preserved, followed by a read-only proof using actual Runtime metadata. No product repair.

## Quality Gates

| Gate | Result |
| --- | --- |
| Ruff / format | PASS / PASS |
| JS syntax | PASS, all 51 tracked JS/MJS files |
| Frontend lint/typecheck/build | NOT_CONFIGURED; static frontend |
| Docs conformance / ADRs | PASS; 14 cases, ADR-001–020/refinements checked |
| Local Markdown links | PASS, no broken local paths |
| EN/DE | Companions present, Mermaid counts consistent; security/capacity/reference semantics spot-checked; report translated locally |
| Environment structure | PASS, 43 keys once in both files, same key order |
| Configured incremental secret scan | PASS, including new report |
| Other CI/security/typecheck gates | NOT_CONFIGURED; no invented scanner claimed |
| Python / frontend dependencies | PASS, `pip check` / `npm ls --all`; optional macOS fsevents absent as expected |
| Wheel | PASS, external copied source, offline/no-deps/no-build-isolation |
| Compose / git diff --check | PASS / PASS |
| Imports | 121 source modules parsed, 56 Core modules; no denied imports; composition hot paths reviewed |

No formatter mutation, vendor sync, dependency installation/update or configuration rewrite. This report changes no architecture/behavior, so existing diagrams need no modification.

## Persistent Side Effects

Before/after: tickets **100/100**, stations **8/8**, products **11/11**, events **29/29**, maintenance events **5/5**, process parameters **1/1**. New approval requests/decisions **0/0**, assignment updates **0**, all eight assignments unchanged. Read investigations/sessions/telemetry were generated. Real protected side effects **0**, external model calls **0**.

## File Integrity

All **506 originally versioned files remain SHA-256 identical**, branch/HEAD unchanged. No existing source/test/config/document changed or was silently reverted. Initial and pre-report Git status clean. Only this new English report and its ignored German companion are added, none staged. Final manifests/status/index evidence is external. Persistent volume names and original Ollama lifetime remain intact; only labelled disposable resources were removed.

## Fresh Overall Review

Performed after functional gates and stability. Reviewed ports/composition/imports, session/admin/clearance, RLS/relations/classification, discovery/references, sole bounded sequential LangGraph/evidence path, routing/egress/TLS, owned provider/ticket I/O, locked approval generations/replay, browser generations/URLs/BFCache, document/PDF authorization, Knowledge provenance/cache/CPU placement, telemetry/backend selection, Docker and active docs.

The measured security boundaries and five remediations hold. One material supporting-feature defect was independently demonstrated below. No style, harmless duplication, wording preference, hypothetical race or future scaling concern was promoted to a finding.

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

#### CERT-01 — Run-trace lookup can select a history read instead of execution

- **Severity/category:** MEDIUM; Observability/RCA correctness, limited diagnostic feature.
- **Requirement:** ADR-016 run-correlated agent/model/tool observability; ADR-017 analysis of available execution evidence.
- **Source:** `src/industrial_ai_agent/infrastructure/observability_backends.py:138`, `TempoAdapter.get_run_trace`, shared by Observability/RCA.
- **Evidence:** External `live-mcp-read-proofs.json`, `trace-selection-review-proof.json`, `rca-selected-trace-impact.json`. Original live read and independent subsequent reproduction agree.
- **Reproduction:** Run an authorized INTERNAL investigation, read its history, then invoke authenticated `get_run_trace`. Compare the selected trace with available run-owned execution spans in that time window. Diagnostic proof is read-only, without new model calls.
- **Observed:** Run `b4bbbbec-30d4-4434-ad53-f9ffa367545b` returns trace `5190a7e936a8e28ce5939b17f64a8fd7`, **7.469 ms**, containing a history GET/persistence and no agent/LLM execution.
- **Expected/available:** Trace `bad5a392a533e5765d7ce31a5d1d4ea4` contains the same run's **8.966824-s `agent.run`**, MCP work and **3.355216/5.487585-s LLM calls**.
- **Cause:** Lookup matches any `span.run.id`, requests `limit=1` and chooses `traces[0]`, without anchoring execution ownership. Later reads also carry the run ID. RCA consumes that trace and correlates downstream sources to it; the live result was partial and omitted available execution evidence.
- **Impact:** Automatic performance/failure/LLM diagnosis after normal navigation can be incomplete or misleading. Core troubleshooting/access controls hold; execution telemetry exists. This is not provider failure or absent instrumentation.
- **Coverage gap:** Adapter fixtures supply one matching trace, not competing execution/history traces. Green gates do not close this new correlation defect.
- **Recommended remediation:** Select/bind the execution-owning trace deterministically and add a multiple-trace regression covering downstream RCA. **Not implemented; tests unchanged.**

### LOW

None.

### OBSERVATIONS

- **O01:** Cold startup warnings recovered; stable readiness and zero restart loops, no operator repair.
- **O02:** Verifier seed/JUnit mistakes, EN session-dominant 403, empty unbounded logs and first diagnostic DTO assumption remain HARNESS_ERROR/setup evidence. None was silently upgraded to product PASS; independent valid checks establish results.
- **O03:** One incomplete older Tempo WAL block was discarded. Current 97-call evidence is available; affected historical completeness is unknown.

## Requirement Confidence Matrix

| Requirement | Confidence / result |
| --- | --- |
| Demo Auth | High; five live users/backend/browser; PASS |
| Roles vs clearance | High; PUBLIC admin/restricted non-admin/server guards; PASS |
| Cross-tab purge | High; failed-refresh/BFCache and direct proof; PASS |
| RLS | High; real non-superuser/non-bypass role; PASS |
| Relation visibility | High; N01 21/FC01 29; PASS |
| Classification propagation | High; FC02 37/egress; PASS |
| Station discovery | High; exact SQL/MCP/API/persistence/browser DE/EN; PASS |
| Product discovery | High; 2/4/9/11/2 and sparse-model controls; PASS |
| Reference actions | High; original 16/extended 35; PASS |
| Model egress | High; R01/C03/278 embedding cases; PASS |
| PUBLIC_CLOUD TLS | High; 31 transport cases; PASS |
| Approval generation | High; C06/R03/real DB/browser; PASS |
| Replay/idempotency | High within ADR-011 failure model; PASS |
| Provider cleanup | High; 14 production-path synthetic proofs; PASS |
| Local capacity | High for measured deployment; 97 calls/263 samples; PASS |
| Knowledge retrieval | High; real retrieval/offline KDEP; PASS |
| Document authorization | High; RLS/path/checksum/MIME/live denial; PASS |
| PDF/Blob lifecycle | High; browser bytes/filename/revocation/stale proof; PASS |
| Observability | High confidence in limitation; **PARTIAL, CERT-01** |
| Docker/runtime | High; seven images/20 ready/>180-s stability; PASS |

## Remaining Risks

CERT-01 limits automatic execution-trace correlation after history reads; direct use of the known execution trace remains possible. The older discarded WAL block leaves historical completeness uncertain. Windows symlink creation remains untested. Live protected HITL/hardware execution is intentionally uncertified; deterministic/disposable proofs cover guards. ADR-011 retains its documented fail-closed claim-to-side-effect crash window, without crash-proof exactly-once claims. No speculative risk added.

## Final Conclusion

**YES, WITH SPECIFIC LIMITATIONS**

**PASS_WITH_FINDINGS:** core/security, deployment, deterministic gates and local-provider reliability pass. CERT-01 is one limited MEDIUM diagnostic defect; no HIGH/CRITICAL or capacity regression. Healthy rebuilt stack left running. Commits/pushes/external deployments **0/0/0**. No finding repaired; no further review started.
