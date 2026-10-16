# Final Clean Verification — 2026-10-15

## Baseline

Repository: D:\Freelance\industrial-ai-agent  
Branch: main  
HEAD: 07c55ee184545906de661d8a83fe68e7790df634  
Working tree at freeze: CLEAN; staged/unstaged/untracked files: 0/0/0.  
Python: 3.12.10, PyCharm-configured .venv/Scripts/python.exe  
Node: v24.19.0; npm: 11.17.0  
Docker client/server: 29.8.2; Compose: v5.6.0  
Local evidence: C:\Users\Andreas\AppData\Local\Temp\industrial-final-verification-20261015-195102

Read-only source certification with the explicitly requested local rebuild/start and isolated test data. No repairs, production/test/configuration/migration/Docker edits, commits, pushes, external deployment, real hardware actions or real protected maintenance writes. Only new reports and generated verification artifacts were written. Earlier reports were not overwritten.

Initial-container and image inventories are retained in initial-containers.txt and initial-images.txt. At freeze all 20 project services were healthy. The independent running ollama container and unrelated exited NVIDIA container remained untouched. Initial SHA-256 manifest covers 472 versioned files.

## Authoritative gates

Inspected current AGENTS, README, pyproject, frontend/package.json, Playwright configs, quality script, Compose/seven Dockerfiles, quality/demo/browser documentation, architecture overview and ADR inventory through ADR-020. There is no .github workflow directory or root package.json; frontend/package.json defines JavaScript gates.

All Python commands used the configured interpreter. Tests requiring database writes used a separately labeled PostgreSQL 18.6 container, loopback port 55432, tmpfs storage, database verification_final, separate admin and nonprivileged factory_app roles, and synthetic credentials. Repository metadata/document paths were explicitly supplied. No test wrote to persistent demo data.

| Gate | Command | Required | Scope | Dependencies |
| --- | --- | --- | --- | --- |
| Clean build | docker compose build --no-cache --progress plain | Yes | Seven own application images | Docker and dependency downloads |
| Complete stack | docker compose up -d --no-build --wait --wait-timeout 600 | Yes | All 20 services | Preserved volumes, local Ollama |
| Backend | Configured Python: -m pytest tests -ra --junitxml=<evidence>/backend-suite.xml | Yes | Unit, integration, golden scorer | Fakes and isolated PostgreSQL |
| Integration | ./scripts/run-quality-gate.ps1 INTEGRATION | Yes | Every integration module | Isolated app/admin URLs |
| FAST | ./scripts/run-quality-gate.ps1 FAST | Yes | Unit, frontend, Ruff, format, secrets | Python/Node; no models |
| Frontend | npm run test, executed within FAST | Yes | All tests/frontend/*.test.mjs | Node/jsdom |
| Browser list | npm run test:e2e:fixtures -- --list | Yes | Current registry | Playwright |
| Browser run | npm run test:e2e:fixtures -- --retries=0 --reporter=list,json | Yes | All 91 cases / six specs | Chromium, fixtures, isolated PostgreSQL |
| Live smoke | New evidence-only Chromium scripts | Yes | Five identities and exact inventories | Rebuilt gateway/API/MCP and verified LOCAL model |
| Quality | Ruff/format/secrets in FAST; node --check; static audit; git diff --check; docker compose config --quiet | Yes | Source/config/docs | Existing local tools |
| Wheel | Configured Python: -m pip wheel --no-build-isolation --no-deps --no-index --wheel-dir <evidence>/wheels <evidence>/wheel-source | Yes | Disposable copied pyproject/src | Installed setuptools |
| Real model | npm run e2e:journey -- --preflight --run-id final-clean-20261015-195102; then --all; then --aggregate with same run ID | Conditional; eligible and executed | Twelve read-only journeys | Verified local_quality / LOCAL Ollama Qwen 3.5 9B |

First evidence is preserved even for verifier setup errors: initial disposable seed lacked FACTORY_DATA_ROOT, then succeeded with the documented external path; an initial PowerShell JUnit argument error collected zero tests, then the correctly formed invocation ran the entire suite. These are HARNESS_SETUP_ERROR, not hidden product passes or changed product files. Original logs: disposable-migration.log and backend.log; completed measurements use separate files.

## Docker rebuild

**PASS**, exit 0. Scoped docker compose down removed project containers/network without -v. All persistent project/model/observability volumes remain. No global prune, unrelated-resource alteration or destructive Git command occurred.

All seven own application images were rebuilt without cache. Frontend uses third-party Nginx with read-only source mounts and has no own image build. Database/observability/Langfuse dependencies use third-party images. An older auxiliary migration image is not a current Compose build target; migrations run through the rebuilt Factory entrypoint.

| Service | Image | Rebuilt | Result | Final image ID |
| --- | --- | --- | --- | --- |
| agent-api | industrial-ai-agent-agent-api | Yes | PASS | sha256:cf796e36fdbd78f0c6097360f163a81be0fbc8f9963f73ab0f163e6a7187f19c |
| factory-mcp | industrial-ai-agent-factory-mcp | Yes | PASS | sha256:45a75572660c4ff445b8f3d2c480343e4a0752fd3c778de42539e5a20737b3a2 |
| hardware-mcp | industrial-ai-agent-hardware-mcp | Yes | PASS | sha256:ccaee7f28e69a8af95754a061f55ecbbbaf0047cee04fca63e416174cb9318e7 |
| knowledge-mcp | industrial-ai-agent-knowledge-mcp | Yes | PASS | sha256:eeedd48521d8429b162d60fd46f6226fd5bcabff9f43b97d9a34c1c2b710f552 |
| runtime-mcp | industrial-ai-agent-runtime-mcp | Yes | PASS | sha256:075da6eeef47cecdcfc5c3768e624feea165c0fd41fe4484c02aff508d3b1edb |
| observability-mcp | industrial-ai-agent-observability-mcp | Yes | PASS | sha256:91562ade167e6bb82430b6c50795d521e4e85dddf44a5de416c28b0a64d37257 |
| rca-mcp | industrial-ai-agent-rca-mcp | Yes | PASS | sha256:1da5b9867d44f8890e2250c4aa235caf58912a84c9e22c52dc6e98bd41f1cb4b |

Evidence: docker-build.log, docker-build.exit, rebuilt-images.txt.

## Stack

| Service | Running | Healthy | Ready | Restarts |
| --- | --- | --- | --- | --- |
| agent-api | Yes | healthy | Yes | 0 |
| factory-db | Yes | healthy | Yes | 0 |
| factory-mcp | Yes | healthy | Yes | 0 |
| frontend | Yes | healthy | Yes | 0 |
| grafana | Yes | healthy | Yes | 0 |
| hardware-mcp | Yes | healthy | Yes | 0 |
| knowledge-mcp | Yes | healthy | Yes | 0 |
| langfuse-clickhouse | Yes | healthy | Yes | 0 |
| langfuse-minio | Yes | healthy | Yes | 0 |
| langfuse-postgres | Yes | healthy | Yes | 0 |
| langfuse-redis | Yes | healthy | Yes | 0 |
| langfuse-web | Yes | healthy | Yes | 0 |
| langfuse-worker | Yes | healthy | Yes | 0 |
| loki | Yes | healthy | Yes | 0 |
| observability-mcp | Yes | healthy | Yes | 0 |
| otel-collector | Yes | healthy | Yes | 0 |
| prometheus | Yes | healthy | Yes | 0 |
| rca-mcp | Yes | healthy | Yes | 0 |
| runtime-mcp | Yes | healthy | Yes | 0 |
| tempo | Yes | healthy | Yes | 0 |

20/20 healthy; all restarts 0. MCP healthchecks establish authenticated initialization, tools/list and required-tool presence; Hardware readiness does not execute actions. API /ready, gateway /health, Prometheus /-/ready, Tempo /ready and /api/search, Grafana /api/health, Langfuse web/worker health, MinIO readiness and ClickHouse /ping succeeded. PostgreSQL served SQL and Redis health returned PONG. Local Ollama tags and the required model were reachable.

Configuration-only healthchecks received additional live checks: Loki initially returned /ready 503, then independently recovered to 200. Collector HTTP metrics were reachable, Prometheus scrape was UP, and exported Factory/RCA metrics demonstrated recovery after startup DNS/OTLP errors. Grafana exposes six project dashboards. Exact startup times/image IDs are in stack-state.json; readiness/recovery evidence is in http-readiness.json, observability-ready.json, loki-ready-recovered.json, prometheus-targets.json and collector-recovery-metrics.txt.

## Test totals

| Gate | Passed | Failed | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Entire backend | 1908 | 0 | 1 | PASS |
| Backend unit subset | 1645 | 0 | 1 | PASS |
| Backend integration subset | 248 | 0 | 0 | PASS |
| Backend golden-scorer subset | 15 | 0 | 0 | PASS |
| Separate INTEGRATION gate | 248 | 0 | 0 | PASS |
| FAST backend | 1645 | 0 | 1 | PASS |
| FAST frontend / full frontend suite | 288 | 0 | 0 | PASS |
| Safe Chromium fixtures | 91 | 0 | 0 | PASS |

Integration/golden rows are already included in the backend total. One skip: test_document_content_storage.py:47, Windows symlink creation unavailable. Five backend dependency deprecations; one separate-integration deprecation. These deterministic suites used no real/external model.

Backend coverage includes API/auth/session/SecurityContext/roles, RLS, migrations/seed/idempotency/persistence, all six MCP boundaries, HITL/protected-action fakes, approval generations/replay/concurrency/exactly-once, ticket persistence/projections, classification propagation, model/embedding egress, lifecycle/TLS/endpoint guards, document/PDF/discovery, golden scoring and harness/smoke tests.

All 91 browser fixtures ran once with zero retries, no skips or flakes. Coverage includes all identities, responsive UI, account/language/Monitoring/Configuration, station/product discovery, stale JSON/download/PDF, cross-tab invalidation, R03 generations, real BFCache/pagehide, FC03 and actual FC04 Blob reads/revocation. Browser filename assertions compare real bytes and authoritative response filenames, with an intentionally wrong-filename negative control.

Evidence: backend-suite.xml/log, integration.log, fast.log, browser-fixture-list.log, browser-fixtures.json/log. Fixture success does not certify the separate live gate.

## Quality gates

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Ruff | PASS | src tests scripts, via FAST |
| Format | PASS | 254 files already formatted |
| JS syntax | PASS | 43 JS/MJS files, zero failures |
| JS lint / static typecheck | NOT_CONFIGURED | No declared lint/typecheck gate |
| Deterministic documentation conformance | PASS | Ten current contract checks |
| Current documentation truthfulness | FAIL | R06: current demo guide still describes Basic Auth, token mapping, clearance selector and an obsolete station count |
| EN/DE companions / Mermaid counts | PASS with limits | 59 technical companions present; matching diagram counts; ten synthetic corpus documents excluded |
| Technical EN/DE spot checks | PASS | FC03/FC04/auth agree; 13 codeblock differences reviewed as translated explanation or commands with workdir established in German prose |
| Local Markdown paths | PASS | No broken local path links in 69 tracked Markdown files; no claim about web links/anchor semantics |
| ADR references/current index | PASS | ADR-001 through ADR-020; no unresolved references; later refinements/supersession respected |
| Environment structure | PASS | Same 43 keys/order in .env/.env.example; no duplicates; values not printed |
| Secret scan | PASS | Repository-defined incremental credential check; not exhaustive historical scanning |
| Wheel | PASS | Offline wheel from external copied source |
| Compose config | PASS | docker compose config --quiet |
| Git whitespace | PASS | git diff --check |

Existing docs and diagrams were not changed. Green documentation tests do not erase the stale R06 statements.

## Demo Auth

Fresh Chromium starts demo-public. Header order: Monitoring → Configuration → Account/current user. Investigation actions: PDF → New Chat. No Demo Clearance selector, Basic challenge or old standalone auth controls. Tested metadata, DE/EN, quick switch, logout through refresh, draft/export purge and read-only admin Configuration opening; no assignment PUT.

| Identity | Clearance | Roles | Configuration |
| --- | --- | --- | --- |
| demo-public | PUBLIC | none | denied |
| demo-internal | INTERNAL | none | denied |
| demo-confidential | CONFIDENTIAL | none | denied |
| demo-restricted | RESTRICTED | none | denied |
| demo-admin | PUBLIC | MODEL_ADMIN | allowed |

Custom live auth: **FLAKY / HARNESS**, not an unqualified PASS. The first script advanced immediately after reload's initially disabled composer, before the logged-out chooser finished rendering: 3 passes / 2 helper timeouts before identity assertions. A separate completion script waited for the documented chooser and verified all five identities. Both original and completion evidence remain (live-browser.json, live-auth-supplement.json). No repository helper was changed. Registered auth fixtures passed first run.

## Station visibility

Exact prompt: "welche stationen kennst du". Expectations derive from actual rebuilt-stack station rows/classifications.

| Identity | Exact authorized set in persisted references and rendered UI |
| --- | --- |
| demo-public | S01, S05 |
| demo-internal | S01, S02, S03, S05 |
| demo-confidential | S01, S02, S03, S04, S05, S06 |
| demo-restricted | S01, S02, S03, S04, S05, S06, S07, S08 |
| demo-admin | S01, S05 |

All five visible sets match exactly without hidden IDs. Four original successful runs were reopened using authorized saved-investigation UI restoration; only the previously unmeasured PUBLIC request was submitted separately. No model retry replaced measured results. Evidence: live-seed-before.txt, live-stations-supplement.json.

**PARTIAL for complete answer quality:** original CONFIDENTIAL prose mentioned only S04; RESTRICTED prose contained no station IDs. Their structured references/UI nevertheless contained all six/eight stations. Original narrative omissions and the initial custom PUBLIC harness failure remain recorded, not converted to clean first-run answer passes. No station authorization leak was observed.

## Product visibility

Exact prompt: "Welche Produkte kennst du?". All five first product measurements passed.

| Identity | Count | Exact IDs | Answer / persisted / browser |
| --- | ---: | --- | --- |
| demo-public | 2 | P4101, P4102 | PASS |
| demo-internal | 4 | P4101, P4102, P4900, P4901 | PASS |
| demo-confidential | 9 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901 | PASS |
| demo-restricted | 11 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901, P9001, P9002 | PASS |
| demo-admin | 2 | P4101, P4102 | PASS |

Live answer rows are complete, ordered, duplicate-free and exclude hidden products. Persisted answers and actual .agent-answer DOM retain all IDs, including nine CONFIDENTIAL and eleven RESTRICTED products. References stay independently capped at 12. Assignment snapshots were checked before calls and unchanged afterward; every Agent assignment was MANUAL/local_quality, LOCAL zone. Evidence: live-browser.json.

## Regression status

| Item | Status | Executed evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 unit cases: sync evidence/document I/O off loop, progress/context/cancellation ownership |
| C02 | CLOSED | 19 unit cases: bounded provider capacity, deadlines, cancellation, retained slots and drain |
| C03 | CLOSED | Actual guard spies, valid requests, schema-only control, bypass-detection and positive MockTransport controls in 25 stabilization cases |
| C04 | CLOSED | 31 TLS/destination cases plus stabilization: PUBLIC_CLOUD HTTP denied before credentials/SDK/transport |
| C05 | CLOSED | Current ADR index, architectural facts, dependency/refinement conformance; separate derived-document R06 defect |
| C06 | CLOSED | 20 unit + 9 PostgreSQL generation cases: identity/binding/replay/concurrency/atomic exactly-once |
| R01 | CLOSED | 29 raw-adapter authorization regressions; denied boundary counters zero; valid local/TLS controls |
| R02 | CLOSED | 25 unit + 2 PostgreSQL slow ticket cases; event loop progress, owned completion and no unsafe retry |
| R03 | CLOSED | 18 unit + 6 PostgreSQL cases and five Chromium approval fixtures; stale approve/reject cannot affect new generation |
| R04 | CLOSED | Frontend/Chromium failed-refresh, late-response, cross-tab/logout/pagehide/BFCache and actual FC04 URL revocation |
| R05 | CLOSED | 19 lifecycle/ownership cases, two/eight concurrent cold callers, cleanup and close/drain races |
| R06 | REGRESSED | docs/demo/use-cases-and-scenarios.md still instructs old Basic/token/clearance UI; live harness fails current session/HTTP expectations |
| N01 | CLOSED | 21 real-RLS cases: visible product retained; hidden relations/IDs/fault references omitted; valid FK and higher-clearance controls |
| FC01 | CLOSED | 29 real-RLS cases: visible ticket + hidden station gives neutral RESOURCE_UNAVAILABLE semantics, no crash/hidden metadata/reference; FK/control valid |
| FC02 | CLOSED | 37 real-RLS cases: Machine/Ticket/Document label joins all emitted data; public-only stays PUBLIC for RESTRICTED reader; hidden relation does not leak; corrected label reaches tool/model guards before SDK |
| FC03 | CLOSED | 14 unit + 30 durable PostgreSQL/API + 10 Chromium cases and live 5/5 exact inventories; sparse/invented/fallback model output cannot limit inventory |
| FC04 | CLOSED | 12 frontend + 15 real Chromium cases: captured confidential-marker URL readable before purge, unreadable/no marker after same/cross-tab downgrade, failed auth/me, logout/ambiguous logout, BFCache/pagehide/late publication; normal export/document controls pass |

Filename bug: CLOSED by actual browser bytes/filename and negative control. Demo Auth/UI core invariants pass registered tests; custom live smoke remains qualified above. Discovery authorization correct; station narrative completeness partial. No repair occurred.

## Runtime logs

All 20 service logs were captured locally with secret-value/credential redaction and searched for the requested error, connection, timeout, authorization, RLS, migration, provider, worker, session, approval, OTel and database terms. Routine successful MCP sessions/migrations/workers are informational.

| Classification | Observation | Recovery / impact |
| --- | --- | --- |
| EXPECTED_NEGATIVE_TEST | Explicit denied model/identity/resource checks | Expected bounded 401/403/404 without leaks |
| EXPECTED_STARTUP_WARNING | Factory/RCA OTLP DNS/unavailable/deadline before Collector start | Stops recurring; later live Factory/RCA metrics and Prometheus UP prove recovery |
| EXPECTED_STARTUP_WARNING | Loki empty ring and initial real readiness 503 | Later 200, no persistent error |
| BENIGN_WARNING | Grafana optional plugin/alerting provisioning dirs absent; third-party feature warnings | Required data sources and six dashboards loaded; health 200 |
| BENIGN_WARNING | Tempo single-binary worker, optional metrics generator; disabled Loki ruler | Optional configuration; readiness/query succeed |
| LOW | Tempo discarded one old incomplete WAL block missing meta.json at startup | Evidence retained; no manual deletion, later search 200; historical trace completeness not certified |
| MEDIUM | Live real-model gate HTTP mismatch | Eight run POSTs returned neutral 404; four other journeys failed runner HTTP 401 expectations; all twelve fail certification |

No continuing server traceback, application 5xx, restart loop, persistent DB/RLS failure or post-startup OTLP failure observed. Live-gate HTTP mismatches remain failures, not passing negative tests. No HIGH/CRITICAL incident observed. Evidence: logs-*.txt, log-hits-*.json, final-runtime-error-hits.json.

## Real-model E2E

**FAIL**, executed once without retries; not NOT_RUN. Repository preflight passed: local Ollama Qwen 3.5 9B, MANUAL/local_quality at all classifications, LOCAL catalog, real Factory/Knowledge readiness, read-only assignment snapshots. No cloud selection/fallback.

Run ID final-clean-20261015-195102. All twelve journeys completed with HARNESS_ERROR and nonzero aggregate exit. Required assertions: 59 planned, 4 executed/passed, 55 blocked/not run. Eight journeys first fail on unexpected run HTTP 404; four retain a passed typed assertion but fail on HTTP 401 recorded by the runner. No retry/harness repair. These are measured boundary/harness failures; no untested root cause is asserted.

Original per-journey and aggregate artifacts remain in evals/results/browser-e2e/final-clean-20261015-195102/. External evidence: real-model-preflight.log, real-model-e2e.log, real-model-aggregate.log, real-model-summary.json, real-model-totals.json. All independent deterministic verification continued.

## External calls

External model calls: **0**. Verification did not send repository payloads to external models/services. Build/start downloaded package/model artifacts; this is distinct from inference egress. Actual inference used repository-defined local Ollama only. Safe fixtures restricted browser requests to their loopback server.

## Side effects

Real protected side effects: **0**. Real hardware actions: **0**. Persistent tickets: **100 before / 100 after**. No real-stack approval/resume. Integration writes used fakes or isolated PostgreSQL only. Live read investigations, demo sessions and normal telemetry were created as expected; zero refers to protected operational side effects.

verification_final was explicitly dropped; its labeled transient container stopped/removed. Test migration databases were cleaned; only postgres and verification_final existed before final disposal. All project volumes and unrelated containers preserved. Commits/pushes/deployments: 0.

## File integrity

**PASS**: SHA-256 matches for all **472 versioned files**; branch/HEAD unchanged. Existing production/test/config/migration/Docker/documentation changes caused by verification: **0**. Only this new English report, its Git-ignored German companion and generated evidence/results were added. No silent reverts. German report remains outside the index.

Evidence: initial-manifest.json, final-manifest.json, file-integrity.json, volumes-preserved.json, cleanup.json. Final whitespace/Compose checks pass. The healthy rebuilt 20-service stack remains running; independent Ollama untouched.

## Final result

**FAIL**.

Clean rebuild, deterministic backend/integration/FAST/frontend/browser suites and core C/N/FC regressions pass. Complete certification is blocked by the failed twelve-journey live gate and R06 stale current documentation. Station narrative omissions and custom live-harness flakes remain explicitly recorded. No fixes. Commits: 0. Deployments: 0.
