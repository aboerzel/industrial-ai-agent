# Final Comprehensive Verification and Review — 2026-10-16

## 1. Executive Summary

**Final result: FAIL.** The deterministic security, authorization, persistence and browser-lifecycle suites pass, and this run found no HIGH/CRITICAL security boundary failure. However, the freshly rebuilt Knowledge MCP image cannot start: its resolved Transformers version imports a module absent from its pinned Torch version. This prevents complete stack readiness and breaks ordinary investigations, including live discovery for most identities. Independently, current UI reference actions generate requests rejected by the current classification contract. These are two reproducible MEDIUM functional/operational findings, not evidence that the repository is generally insecure or that a model merely wrote an imperfect answer. The implementation cannot currently be certified as reliably fulfilling its complete documented product and operational contract.

This was verification only. No finding was repaired; no existing source, configuration, historical report or model assignment was changed. External model calls, real protected side effects, commits and external deployments: **0**.

## 2. Baseline

| Item | Recorded value |
| --- | --- |
| Repository | `D:/Freelance/industrial-ai-agent` |
| Branch | `main` |
| HEAD | `911fd3a09519c539088844bed78e5a7bc6ab44ce` |
| Freeze time | `2026-10-16T07:34:21+02:00` |
| Initial git status | Clean; staged 0, unstaged 0, untracked 0 |
| Python | PyCharm-configured `.venv/Scripts/python.exe`, 3.12.10 |
| Node / npm | v24.19.0 / 11.17.0 |
| Docker | 29.8.2, build 7fc2dff |
| Docker Compose | v5.6.0 |
| Initial project stack | 20 services; initially healthy before rebuilding |
| Separate local model runtime | Existing `ollama` container; preserved |
| External evidence directory | `D:/Freelance/verification-evidence-2026-10-16-073421` |

The external baseline includes complete porcelain-v2 status, staged/unstaged/untracked lists, all existing containers, image IDs, and a SHA-256 manifest of all **480** currently versioned files. `baseline.json` and `versioned-hashes-before.json` preserve the evidence independently of this report.

The authoritative checklist was established from current AGENTS, README, pyproject, frontend package scripts, Compose/Dockerfiles, architecture overview, ADR-001 through ADR-020 with supersession/refinements, quality-gates, Demo Auth, visibility, scenario and browser-journey documentation, public schemas and implementation. The targeted-remediation and final-clean reports were read as historical context only. No root `package.json` or `.github/workflows` exists; the current commands are local repository gates.

Key promises checked: server-owned identity/clearance/roles; RLS and independent related-object visibility; emitted-data classification joins; trusted complete inventories; bounded sequential orchestration; assignment/capability/egress separation; provider authorization and TLS before credentials/SDK/transport; action-bound approval generation and single-use claims; durable results; fail-closed cross-tab/BFCache/request/Blob lifecycle; and actual operational readiness.

## 3. Clean Docker Rebuild

**Image build: PASS. Operational startup after that build: FAIL.** These are separate results.

Executed `docker compose stop`, preserving containers, all named volumes and unrelated resources, followed by `docker compose build --no-cache`. Stop and build both exited 0. All seven current project-owned images were rebuilt; image IDs are recorded below. Frontend is the third-party Nginx image with read-only source mounts. PostgreSQL, telemetry and Langfuse dependencies are third-party images. The older auxiliary migration image is not a current Compose build target; Factory startup owns the supported migration/seed entrypoint.

| Service/image | Build | Image ID |
| --- | --- | --- |
| agent-api | PASS | `sha256:071f9cb79f6fd694d8e119f943e1f518b65e51e02b34b54a2d7a11f40fcbc44f` |
| factory-mcp | PASS | `sha256:fea27ecf034bad9d62ab97e4b7df347473b131b1739b9b7d31721d52ff9182c8` |
| hardware-mcp | PASS | `sha256:1842d21a70eb79cbd9a2290ad36a626b40e064fe7cdde8ca11d8ed6f04f5e67f` |
| knowledge-mcp | PASS | `sha256:4bde4e47d62b52faeb3a5d8eaa7c99bda1fd183f510a47ac32586f0f391cfb6b` |
| runtime-mcp | PASS | `sha256:7161e88168a355b423b52fb10fc26ae677b66e085a61178b5fc09dfca95a1032` |
| observability-mcp | PASS | `sha256:106b3bf25bbd048798dd9965e7fd208af130b51e7e3a1b1de3d0fc753d74fb44` |
| rca-mcp | PASS | `sha256:a896f473699ebaa7fbd131635893c9f21512e5d0923cf56d9e32ec45f0901779` |

Evidence: `stack-before-stop.json`, `stack-after-stop.json`, `compose-stop.log`, `compose-build.log`, `compose-build-exit.txt`, `rebuilt-images.json` in the external directory. Package/base-image dependency downloads during the requested build are not external LLM invocations.

## 4. Stack Health

Initial supported startup command: `docker compose up -d --no-build --wait --wait-timeout 600`. **Exit 1:** Knowledge MCP became unhealthy, blocking API/frontend dependency startup. The API was subsequently started with `--no-deps`, and the already-configured gateway container was started directly for independent live session/UI checks. This diagnostic start did not make the stack ready or hide the original failure.

External provider key environment values were blanked for the verification API container; `.env`, catalogs and persistent assignments were not changed. All agent and RCA assignments remained `MANUAL / local_quality`; the runner verified Ollama `qwen3.5:9b` in `LOCAL` before invocation.

| Service | Running | Docker healthy | Actual readiness | Restarts |
| --- | --- | --- | --- | --- |
| agent-api | YES | unhealthy | NO: /ready 503 | 0 |
| factory-db | YES | healthy | YES | 0 |
| factory-mcp | YES | healthy | YES | 0 |
| frontend | YES | healthy | YES: gateway only | 0 |
| grafana | YES | healthy | YES | 0 |
| hardware-mcp | YES | healthy | YES | 0 |
| knowledge-mcp | restarting | unhealthy | NO | 71 |
| langfuse-clickhouse | YES | healthy | YES | 0 |
| langfuse-minio | YES | healthy | YES | 0 |
| langfuse-postgres | YES | healthy | YES | 0 |
| langfuse-redis | YES | healthy | YES | 0 |
| langfuse-web | YES | healthy | YES | 0 |
| langfuse-worker | YES | healthy | YES | 0 |
| loki | YES | healthy | YES | 0 |
| observability-mcp | YES | healthy | YES | 0 |
| otel-collector | YES | healthy | YES | 0 |
| prometheus | YES | healthy | YES | 0 |
| rca-mcp | YES | healthy | YES | 0 |
| runtime-mcp | YES | healthy | YES | 0 |
| tempo | YES | healthy | YES | 0 |

Measurement time: `2026-10-16T08:04:15.3887175+02:00`.

**18/20 Docker healthy.** Knowledge MCP is in a persistent import/restart failure; API `/health` is 200 but `/ready` is 503. Gateway `/health` is 200 and is not evidence of a ready agent. Knowledge restart counts continue increasing; the table is a timestamped measurement, not a claim that the loop stopped. All other restart counts are 0.

Readiness evidence goes beyond container state: authenticated MCP initialize/tools-list checks for Factory, Hardware, Runtime, Observability and RCA; real SQL on PostgreSQL; Redis health PONG; ClickHouse `/ping`; MinIO internal readiness; Langfuse web and worker health; Prometheus `/-/ready` and scrape target UP; Tempo `/ready` and search API; Grafana `/api/health`; Collector metrics on its configured **8889** endpoint; and local Ollama model presence. Hardware checks only discover capabilities and do not execute them.

Loki initially returned 503 while its ingester warmed, then returned 200. Early Factory/RCA OTLP DNS/deadline failures recovered after Collector startup; subsequent scrape/metrics evidence is retained. These transients do not explain or excuse Knowledge's persistent failure. External evidence: readiness JSON/text files, `collector-metrics-configured.txt`, `stack-report-snapshot.json`, `stack-leave-running.json` and per-service runtime logs.

## 5. Test Results

| Gate | Exact command/scope | Required | Passed | Failed | Skipped | Result |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Full backend | Configured Python `-m pytest tests -ra --junitxml=<external>/backend.xml` | Yes | 1963 | 0 | 1 | PASS |
| Backend unit subset | Included above | Yes | 1670 | 0 | 1 | PASS |
| Backend integration subset | Included above | Yes | 278 | 0 | 0 | PASS |
| Golden scorer subset | Included above | Yes | 15 | 0 | 0 | PASS |
| Separate integration | `./scripts/run-quality-gate.ps1 INTEGRATION`, with JUnit via PYTEST_ADDOPTS | Yes | 278 | 0 | 0 | PASS |
| FAST backend | `./scripts/run-quality-gate.ps1 FAST`, unit substep | Yes | 1670 | 0 | 1 | PASS |
| FAST/full frontend | FAST runs `npm run test` from `frontend` | Yes | 294 | 0 | 0 | PASS |
| Safe browser fixtures | `npm run test:e2e:fixtures -- --retries=0 --reporter=list,json` | Yes | 105 | 0 | 0 | PASS; flaky 0 |
| Manual real-model wrapper | `npm run e2e:manual -- --run-id comprehensive-local-20261016` | Yes | — | — | — | BLOCKED preflight |
| All registered live journeys | `npm run e2e:journey -- --all --run-id comprehensive-local-20261016`, then manual aggregate | Yes | 0 journeys | 12 journeys | 0 | Gate FAIL; see §11 |

Subset rows are not additional tests to add to the full backend total. FAST ran exactly as currently defined: unit tests, frontend tests, Ruff check, Ruff format check and incremental secret check. All its substeps completed successfully.

The only backend/FAST skip is `tests/unit/test_document_content_storage.py:47`: Windows symlink creation unavailable. Full backend: 35 warnings, principally 30 JUnit `record_property` warnings plus dependency deprecations. Integration: 31 warnings. These are not failed assertions.

All database-changing deterministic tests used a separate PostgreSQL 18.6 container `industrial-verification-20261016`, loopback port 55436, tmpfs storage and database `verification_comprehensive_20261016`. Separate admin and `factory_app` roles were configured; application proofs used neither superuser nor BYPASSRLS. Migrations reached 0025; upgrade, foreign-key, FORCE RLS, missing-clearance, replay, concurrency and seed-preservation assertions ran. The isolated database/container was removed after tests, with its identity label checked and database inventory preserved. No deterministic test targeted persistent demo data.

The safe browser registry was listed before execution: **105 cases in six specs**. Every case ran once, with zero retries/skips/flakes. Coverage includes five identities, session bootstrap, account/configuration/Monitoring/language, logout, failed auth refresh, stale JSON/download/PDF, cross-tab, actual BFCache/pagehide, approval generations, MIME and filename handling, document/server/transcript PDFs, complete DE/EN inventories backed by disposable RLS, and actual retained Object URL revocation. Test reports and FC03/SD/FC04 attachments remain in `browser-fixtures.json` externally.

## 6. Quality Gates

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Ruff | PASS | `ruff check src tests scripts`, FAST |
| Format | PASS | `ruff format --check src tests scripts`; 257 files |
| JavaScript syntax | PASS | `node --check`, 44 tracked non-vendor JS/MJS files |
| JS lint / static typecheck / frontend bundler build | NOT_CONFIGURED | No such package scripts or configured gate; static frontend served by Nginx |
| Documentation conformance | PASS | 14 current deterministic checks in full backend/FAST |
| EN/DE companions and Mermaid counts | PASS | 60 existing technical Markdown files, no missing companion or mismatched diagram count |
| Local Markdown paths | PASS | 72 tracked Markdown files; no broken local path links; external URLs/anchor semantics not certified |
| ADR validation | PASS | ADR-001–020 index/references and active refinements inspected; no new architectural change introduced |
| Environment structure | PASS | Same 43 keys, same order, no duplicates in `.env` / `.env.example`; values not disclosed |
| Secret scan | PASS | Repository-defined incremental `check-demo-secrets.py`; not an exhaustive historic/dependency vulnerability scan |
| Wheel | PASS | Offline `pip wheel --no-build-isolation --no-deps --no-index` from external copied pyproject/src; no repository build modifications |
| Docker Compose config | PASS | `docker compose config --quiet` |
| Whitespace | PASS | `git diff --check` |

EN/DE synchronization includes technical content review of current authentication, visibility, discovery and architecture descriptions, not just filename counts. No current Basic gateway or browser clearance-selector contract was found. Historical/superseded ADR context and the explicitly historical README screenshot were not treated as current instructions. Existing diagrams required no edits because this run changes no implementation or architecture.

Verifier setup errors are retained separately: an initial custom auth smoke compared whitespace literally; a subsequent version assumed language survived logout/reload; the reference-admission proof initially omitted `X-Demo-Session`; and the first Collector probe used unconfigured port 8888 before checking configured 8889. These evidence-only helpers were corrected outside the repository, with original logs preserved. They are not product flakes, and no registered browser fixture was retried.

## 7. Demo Auth

Live rebuilt API/Nginx/Chromium smoke confirms fresh `demo-public`, no Basic challenge, header order Monitoring → Configuration → Account and toolbar PDF → New Chat. No obsolete clearance selector exists. Session cookie: HttpOnly, SameSite=Strict, path `/api/`. Browser `Authorization` is stripped by Nginx; API session identity is authoritative. Cookie-authenticated requests reject caller-supplied clearance.

| Identity | Clearance | Roles | Configuration API/UI | Switch, logout, explicit login |
| --- | --- | --- | --- | --- |
| demo-public | PUBLIC | none | 403 / disabled | PASS |
| demo-internal | INTERNAL | none | 403 / disabled | PASS |
| demo-confidential | CONFIDENTIAL | none | 403 / disabled | PASS |
| demo-restricted | RESTRICTED | none | 403 / disabled | PASS |
| demo-admin | PUBLIC | MODEL_ADMIN | 200 / enabled | PASS |

Quick switching is intentionally permitted in demo mode; it is not a bypass finding. Logout remains logged out after refresh. Language survives user switching; a fresh logout/reload resets the empty workspace language to EN, recorded as an observation rather than a material defect. Ordinary language/refresh behavior is also covered by the fixture suite.

Live same-tab and cross-tab downgrade proofs used synthetic confidential transcript content and the real session/gateway/UI. A captured PDF Blob URL was readable before downgrade, then directly unreadable afterward; protected DOM was cleared and export disabled. `live-blob-lifecycle.json` records both original URLs and direct fetch results. Synthetic run requests were intercepted before dispatch; no model or protected action was used for this proof. Failed-refresh, pending requests, late publication, BFCache and stale approval behavior have additional first-run Chromium coverage.

## 8. Station Visibility

Exact prompt: `welche stationen kennst du`. Current persistent seed was checked first with read-only SQL as `factory_app`, then separately through authenticated Factory MCP for every identity.

| Identity | Exact live SQL and Factory MCP IDs | Isolated RLS → agent → durable API → browser, DE/EN | Live rebuilt answer/persisted/browser |
| --- | --- | --- | --- |
| demo-public | S01 S05 | PASS | FAIL: required MCP service unavailable |
| demo-internal | S01 S02 S03 S05 | PASS | FAIL: required MCP service unavailable |
| demo-confidential | S01 S02 S03 S04 S05 S06 | PASS | FAIL: required MCP service unavailable |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | PASS | PASS: all three exact sets match |
| demo-admin | S01 S05 | PASS | FAIL: required MCP service unavailable |

Live complete station discovery is **not certified for all identities**. The restricted inventory uses a bounded path that can operate without Knowledge and passed within the registered live inventory smoke. No observed successful inventory contains hidden IDs or duplicates. The other rows returned failed runs, not incomplete successful inventories. Deterministic tests prove model omissions/inventions/fallback cannot change the typed inventory when execution succeeds: 20 station unit cases, 30 real-RLS/durable API cases and 10 station Chromium cases.

## 9. Product Visibility

Exact prompt: `Welche Produkte kennst du?`.

| Identity | Count | Exact live SQL and Factory MCP IDs | Isolated pipeline, DE/EN | Live rebuilt answer/persisted/browser |
| --- | ---: | --- | --- | --- |
| demo-public | 2 | P4101 P4102 | PASS | FAIL: required MCP service unavailable |
| demo-internal | 4 | P4101 P4102 P4900 P4901 | PASS | FAIL: required MCP service unavailable |
| demo-confidential | 9 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 | PASS | FAIL: required MCP service unavailable |
| demo-restricted | 11 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 P9001 P9002 | PASS | FAIL: required MCP service unavailable |
| demo-admin | 2 | P4101 P4102 | PASS | FAIL: required MCP service unavailable |

Factory inventory and deterministic completeness pass; live product discovery does not. FC03 has 14 unit, 30 real-RLS/durable API and 10 Chromium cases. Those use intentionally sparse/invented/fallback fake model output and prove complete, unique, authorized inventory, separate reference budget ≤12 and no prose-derived additions. The documented 8,000-character answer limit explicitly marks oversized inventories partial; none of the current seed sets approaches that limit.

Evidence: `live-factory-inventory.json`, integration XML, browser attachments and `journey-station-discovery.json` → `inventory_smoke`. The live ten-row smoke passed **1/10**, not 10/10. It preserves failures rather than substituting the successful isolated fixture matrix.

## 10. Security / Regression Status

`CLOSED` below certifies the named tested boundary, not the entire live product or a crash-proof execution guarantee. Every status uses current execution and source review, never historical closure alone.

| ID | Current status | Current evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 async-I/O unit cases: off-loop evidence/document I/O, progress/context/cancellation ownership |
| C02 | CLOSED | 19 provider lifecycle cases: capacity, deadlines, cancellation, drain |
| C03 | CLOSED | 25 stabilization cases include real guard spies, zero denied boundary counters and positive MockTransport controls |
| C04 | CLOSED | 31 transport-security cases: PUBLIC_CLOUD HTTP denied before credentials/SDK/transport, redirect/proxy controls |
| C05 | CLOSED | 14 current documentation/conformance cases plus current ADR/index/dependency review |
| C06 | CLOSED | 20 unit + 9 real PostgreSQL generation cases, row-lock single use and distinct generations |
| R01 | CLOSED | 29 raw-adapter authorization cases, denied counters zero, authorized local/TLS controls |
| R02 | CLOSED | 25 unit + 2 PostgreSQL ticket-I/O cases, owned work and no unsafe retry |
| R03 | CLOSED | 18 unit + 6 PostgreSQL + 5 Chromium approval cases; stale approve/reject cannot approve B with A's token |
| R04 | CLOSED | Frontend and Chromium cross-tab/failed-refresh/late JSON/binary/BFCache cases; additional live Blob proofs |
| R05 | CLOSED | 19 client-ownership cases, concurrent cold callers, cleanup/close/drain races |
| R06 | CLOSED | Current auth docs/conformance and live session harness verified; no obsolete Basic/header-clearance setup. Overall journey failure is separately recorded. |
| N01 | CLOSED | 21 real-RLS/FK cases: visible product retained; hidden event/station metadata omitted; chronological visible history |
| FC01 | CLOSED | 29 real-RLS cases: visible ticket with hidden station is neutral unavailable, no crash/hidden metadata/ref |
| FC02 | CLOSED | 37 real-RLS cases: projection label joins emitted protected data; corrected label reaches egress guard |
| FC03 | PARTIAL | Deterministic complete-inventory regression closed; all five live product checks fail because of V01 |
| FC04 | CLOSED | 15 real Chromium retained-URL cases, frontend coverage and two live gateway Blob proofs |

Critical invariant spot checks were concretely exercised: visible product/hidden station and visible ticket/hidden station with real FK/RLS; PUBLIC parent plus emitted CONFIDENTIAL relation raises the projection to CONFIDENTIAL; RESTRICTED caller plus PUBLIC-only emitted data stays PUBLIC; stale generation A cannot decide B; unauthorized raw provider calls and PUBLIC_CLOUD HTTP have zero credential/SDK/transport access; and directly retained protected Blob URLs become unreadable after same-tab/cross-tab downgrade. Approval and protected-write tests use synthetic/disposable state, never real actions.

## 11. Real-Model Product Quality

Run directory: `evals/results/browser-e2e/comprehensive-local-20261016/`. The current wrapper performed the real preflight and correctly blocked on Knowledge MCP. All twelve journeys were then explicitly attempted once with the documented repository individual runner `--all`; its per-journey LOCAL-only assignment guard remained active. No failed preflight was rewritten as PASS. The aggregate retains `execution_status=BLOCKED`, `preflight_status=BLOCKED`, `product_quality_gate=FAIL` and 12 completed journey artifacts.

| Journey | Artifact status/category | Reviewed category | Required | Passed | Failed | Blocked |
| --- | --- | --- | --- | --- | --- | --- |
| clearance-boundary-en | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 6 | 3 | 3 | 0 |
| clearance-boundary | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 9 | 3 | 4 | 2 |
| documentation | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 8 | 2 | 3 | 3 |
| healthy-station-de | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 3 | 0 | 2 | 1 |
| healthy-station-en | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| product-centric-en | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 3 | 0 | 2 | 1 |
| product-history | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| restricted-boundary | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 2 | 2 | 0 |
| s04-investigation-en | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| s04-investigation | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 6 | 1 | 3 | 2 |
| station-discovery-de | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 2 | 2 | 0 |
| station-discovery | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |

The table preserves the runner's actual `FAIL / HARNESS_ERROR` labels. Independent readback of its persisted run IDs found **21 failed terminal results with `mcp_service_unavailable`, failure origin MCP, and 4 successful terminal results**. Every journey has an infrastructure-caused failed run. Reload timeouts and absent references/documents follow those failures. The review therefore classifies the dominant failure of each journey as **INFRASTRUCTURE_ERROR**, rather than incorrectly attributing missing evidence to model variance or a model-provider outage. No entire journey passed.

Required assertions: **59 evaluated, 46 executed, 13 passed, 33 failed, 13 blocked/not-run**. Evaluated does not mean executed. Optional/manual-only assertions remain separate. The station journey's extra live inventory smoke is 1 passed / 9 failed. A few restricted station/status turns successfully used the configured real local model; no general semantic-quality result can be inferred from this incomplete infrastructure baseline.

Security defects observed in these live attempts: 0. External provider calls recorded: 0. Protected proposals approved/resumed: 0. Independently reproduced reference-action admission failures are V02; the broken infrastructure prevents claiming that all historical model-quality issues were retested or resolved. Raw artifacts are retained even where their automatic category is less precise than the verified cause.

## 12. Runtime / Logs

Logs from **all 20 Compose services** were collected after test execution and searched for ERROR/CRITICAL/FATAL/Traceback/Exception/panic/restart/connection refused/timeout/401/403/404/RLS/migration/provider/worker/session/approval/database/OTel. Counts are retained as search evidence, not defect counts.

| Meaningful entry | Classification | Assessment |
| --- | --- | --- |
| Knowledge `torch.distributed.checkpoint.hf_storage` import failure and restart loop | PRODUCT_DEFECT / MEDIUM | Persistent V01; reproduced offline in the fresh image |
| API `/ready` 503 and `mcp_service_unavailable` terminal results | PRODUCT_DEFECT / MEDIUM | Consequence of V01; not an additional finding |
| Fresh anonymous `/auth/me` and logged-out reads 401; non-admin Configuration 403; intended protected-resource 404 | EXPECTED_NEGATIVE_TEST | Correct denial, not a bypass or runtime defect |
| Real UI-generated unsupported reference prompts 404 | PRODUCT_DEFECT / MEDIUM | V02 when reproduced with a valid authorized session and matching prior context |
| Factory/RCA OTLP DNS/UNAVAILABLE/deadline messages before Collector startup | EXPECTED_STARTUP_WARNING | Later configured metrics scrape succeeds; current Collector readiness confirmed |
| Loki empty ring / initial readiness 503 | EXPECTED_STARTUP_WARNING | Recovered to 200 |
| Tempo single-binary worker auto-configuration / disabled optional metrics-generator; Grafana playlist-authorizer warning | BENIGN_WARNING | Supported queried interfaces ready; no demonstrated application authorization defect |
| Tempo removes one pre-existing incomplete WAL entry lacking `meta.json` at startup | OBSERVATION | Current search ready; completeness of historical trace retention not certified |
| Routine Langfuse propagation/backfill workers, PostgreSQL checkpoints/migration startup, MCP session creation/termination | BENIGN_WARNING / routine information | No persistent independent fault found; no browser cookie or service credential exposed in this report |

Raw logs and readiness recovery evidence remain external. Persistent Knowledge failure was not dismissed as startup noise.

## 13. Overall Architecture / Security Review

The fresh source review followed completion of all test commands. It traced the public API/session, run classification, model resolution/provider boundary, MCP delegation, PostgreSQL projections, approvals and browser invalidation paths, then compared them to active ADRs and measured outcomes.

**Architecture and orchestration.** Domain and capabilities depend on inner contracts, with concrete persistence/provider/transport construction in Infrastructure composition. No forbidden inward Infrastructure import was found in Domain/Application/agent/tools. LangGraph remains the sole troubleshooting loop. The current graph preserves one executed tool per iteration, the four-tool budget, deterministic argument/admission checks, the discovery first-read exception and evidence-based completion. LangChain/MCP integration delegates to existing capabilities; diagnostic MCP services do not become unrestricted agent tools. The inventory functions consume current guarded typed observations, not model prose or the reference list. No framework fallback or parallel action path was found.

**Authentication and authorization.** DemoSessions is explicitly process-local and bounded, maps fixed users to authoritative SecurityContext, revokes prior tokens on switch/logout and exposes only safe metadata. Nginx forwards cookies and strips browser Authorization. Admin is orthogonal to clearance. Browser caller-supplied clearance is rejected; direct bearer compatibility only narrows an already-authorized context. Classification-shared investigation reads, rather than private per-user tenancy, match the documented contract. Demo quick-switch and loopback HTTP are deliberate scope, not findings.

**RLS, relationships and documents.** App transactions parameterize transaction-local clearance; classified records use forced RLS and non-owning/non-bypass roles. Product events are filtered independently from the parent, including independently invisible stations; visible products remain with null latest fields when no eligible event exists. Hidden mandatory ticket stations return neutral unavailable. Labels join the protected values actually emitted, not caller clearance or privileged hidden relations. Catalog reads authorize before file access, constrain resolved paths to the configured root, check checksums, sanitize server filenames/MIME and return no-store/sandbox/nosniff responses. PDF export reauthorizes its source investigation. Real-RLS regression evidence supports these paths.

**Model boundary.** Persistent assignment is configuration, not authorization. AUTO performs credential-availability, capability and security hard filters before ranking; provider errors never trigger reselection. The final request-bound egress decision precedes raw adapter access. Effective destination validation precedes credential lookup and SDK/transport construction, requires PUBLIC_CLOUD HTTPS, constrains LOCAL destinations and disables proxies/redirects. Embeddings remain a separate classified port with stricter approved local destination checks before SDK access. Both query and batch paths fail closed without trusted classification. Current negative tests prove those boundaries without external network calls.

**HITL and concurrency.** The UI sends its displayed `approval_execution_id`; store row locks compare that generation atomically with the pending proposal. Execution separately checks the persisted exact action/profile/run/target/decision/clearance binding and claims the generation once. Ticket idempotency combines run and generation with a unique database key; authorized consumed-generation reads cannot create a missing result again. Blocking ticket I/O stays owned through cancellation and completion. This is at-most-once claimed execution plus idempotent result recovery, not a transactional outbox or crash-proof exactly-once guarantee. That documented consumption-to-write failure window remains explicit. Physical recovery still requires independent post-action verification and industrial safety systems; this run performed no real action.

**Browser lifecycle.** One generation/AbortController and a context-owned Object URL registry protect JSON, documents, server PDFs and transcript PDFs. Invalidations purge before session mutation and broadcast independently of identity refresh. Stale responses cannot republish old context. Pagehide revokes URLs; BFCache restoration reads authoritative identity again. Approval conflicts require a new explicit decision. First-run fixtures and live retained-URL proofs support these claims. The real user-facing integration defect is the mismatch between reference-generated prose and conservative request admission, V02.

**Observability, runtime and documentation.** Allowlisted telemetry, disabled exception-content recording and Collector sanitization keep business payloads out of the inspected application telemetry paths; read-only diagnostic capabilities check runtime visibility before querying protected telemetry. Current runtime backends are ready apart from the independently identified Knowledge/API dependency chain. The clean image's incompatible dependency set is a real reproducibility/operability problem; a successful `pip install` and host suite do not prove image importability. Current docs describe sessions and deterministic inventories accurately at the design level, but the demonstrated current deployment cannot deliver all of that behavior. No speculative scalability, naming or cosmetic findings were added.

## 14. Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

#### V01 — Clean Knowledge image cannot import its runtime dependencies

- **Severity / category:** MEDIUM / operational reliability, reproducible clean deployment failure.
- **Affected paths:** `Dockerfile.knowledge-mcp:23`, `pyproject.toml`, `src/industrial_ai_agent/infrastructure/sentence_transformers_reranker.py:4`; Compose Knowledge → API → frontend readiness chain.
- **Evidence:** `compose-build.log` exit 0; `compose-up.log` exit 1; `knowledge-first-start.log`; `knowledge-installed-versions.txt`; network-disabled `knowledge-offline-import-proof.log` exit 1; stack and terminal-result JSON.
- **Expected:** Every supported project image starts after the repository-supported clean build; required MCP tools are available; API readiness and ordinary investigations succeed.
- **Observed:** Image installs Torch `2.7.1+cpu`, Torchvision `0.22.1+cpu`, Transformers `5.20.0`, Sentence Transformers `5.7.0`. Importing CrossEncoder imports `PreTrainedModel`, which needs nonexistent `torch.distributed.checkpoint.hf_storage`. The service repeatedly exits; Knowledge never becomes ready; API remains 503-ready and most live runs fail `mcp_service_unavailable`. The offline proof rules out a missing model download or transient remote service as the cause.
- **Impact:** Complete local stack startup fails; documentation/retrieval and ordinary investigations/discovery are unavailable. A reduced restricted station path still works. No demonstrated disclosure or unauthorized action follows from the failure.
- **Reproduction:** `docker compose build --no-cache`; `docker compose up -d --no-build --wait --wait-timeout 600`. Minimal independent proof: `docker run --rm --network none --entrypoint python industrial-ai-agent-knowledge-mcp -c "from sentence_transformers import CrossEncoder"`.
- **Why tests did/did not catch it:** The host environment uses Torch `2.14.0+cu126`, Torchvision `0.29.0`, Transformers `5.16.1`; its passing tests do not execute this fresh Linux dependency set. The clean image/startup verification caught it. Existing readiness correctly fails closed.
- **Recommended remediation:** Establish and constrain a compatible CPU Torch/Transformers/Sentence Transformers dependency set, then verify imports and authenticated readiness from a new clean image. Add a small network-free built-image import check alongside the operational build gate. No remediation was applied.

#### V02 — Reference buttons generate requests the API rejects

- **Severity / category:** MEDIUM / promised user-visible navigation and request-contract integration.
- **Affected paths:** `frontend/js/app.js:662` (`identifierActions`), `src/industrial_ai_agent/agent/run_classification_policy.py`, API create-run classification boundary.
- **Evidence:** `reference-prompts.json` extracts 16 actual DE/EN action templates from the current function. `reference-admission-proof-v3.json` submits them through the real FastAPI/DemoSessions/classification code with an existing authorized investigation and a synthetic run service. **13/16 are rejected before execution**; three supported German actions succeed. No LLM or real protected side effect is involved.
- **Expected:** A UI action for a currently authorized station/product/fault submits an admitted semantic request at the same authorized context, preserving conservative classification of arbitrary free text.
- **Observed:** Examples: PUBLIC S01 “Check current status” sends `Check the current status of station S01.` and gets 404 `requested_data_unavailable`; CONFIDENTIAL S04 “Station untersuchen” sends `Untersuche Station S04 genauer.` and gets the same denial; INTERNAL P4901 “Show product history” sends `Show the product history for P4901.` and is denied. German `Prüfe den aktuellen Status von Station S01.` and `Zeige die Produkthistorie von P4901.` are successful controls. Fault investigation/search templates also fail in the checked CONFIDENTIAL context. Existing investigation context does not cure the mismatch.
- **Impact:** Common promised reference-navigation actions fail even with authorized visible data and healthy services. Classification correctly denies unsupported prose; this is a product integration defect, not a reason to relax authorization or label the system insecure.
- **Reproduction:** Establish the corresponding demo session; start the documented admitted neutral request for S01/S04/P4901/QUALITY-09; take its investigation ID; submit the exact current reference-generated prompt with that ID, response language and `X-Demo-Session: 1`. The isolated proof substitutes only execution, retaining the real request/security boundary, so V01 cannot cause these denials.
- **Why tests did/did not catch it:** Frontend template/render tests and synthetic HTTP fixtures cover each side separately but do not uniformly run all emitted action prose through the real classifier. Current typed-journey contract tests validate typed registry prompts, not every UI template. The new external cross-boundary proof catches the actual incompatibility; historical live failures alone were not used as proof.
- **Recommended remediation:** Align emitted reference prompts with the supported neutral request contract or introduce a bounded typed reference-action request. Preserve unknown-text classification and all existing clearance/egress checks. Add deterministic template-to-real-API admission coverage for DE/EN and relevant identities. No remediation was applied.

### LOW

None.

### Observations

The live harness's automatic category can be misleading under missing infrastructure: reload timeouts turn these journeys into `HARNESS_ERROR`, and some `mcp_service_unavailable` steps are labeled `MODEL_VARIANCE`. Raw classifications are preserved; verified terminal results establish infrastructure as the dominant cause. No separate correctness/security finding is inferred from the label alone. The pre-existing incomplete Tempo WAL entry also limits claims about historical telemetry retention. Neither observation inflates the finding count.

## 15. Requirement Confidence Matrix

| Requirement | Current evidence | Confidence | Status |
| --- | --- | --- | --- |
| Demo Auth | Current session tests + real rebuilt five-user gateway smoke | High | PASS |
| Cross-tab purge | First-run R04/FC04 Chromium + real gateway captured Blob proof | High | PASS |
| RLS isolation | Non-bypass app role, FORCE RLS, missing-clearance, real PostgreSQL tests and live read-only SQL | High | PASS |
| Related-object visibility | N01 21 + FC01 29 real-RLS/FK cases, source projections | High | PASS |
| Classification propagation | FC02 37 real-RLS cases, model guard controls, source joins | High | PASS |
| Station Discovery | 20 unit + 30 durable API + 10 Chromium + live Factory exact matrix | High for algorithm; limited for deployment | PARTIAL: live 1/5 |
| Product Discovery | 14 unit + 30 durable API + 10 Chromium + live Factory exact matrix | High for algorithm; limited for deployment | PARTIAL: live 0/5 |
| Model egress | R01/C03/embedding tests, exact request-bound authorization, source review | High | PASS |
| PUBLIC_CLOUD TLS | 31 transport tests + raw-adapter controls | High | PASS |
| Approval generation | C06/R03 unit + PostgreSQL locks + 5 Chromium cases | High | PASS |
| Replay/idempotency | Synthetic/disposable claim, unique-key and concurrency tests | High within documented failure model | PASS; not crash-proof exactly once |
| Ticket persistence | PostgreSQL persistence/FK/idempotency + R02 owned slow-I/O tests | High | PASS with synthetic state |
| Document access | Current RLS/path/checksum/MIME/filename tests; Chromium downloads | High for boundary; live retrieval blocked | PARTIAL operationally |
| PDF/blob lifecycle | Backend PDF tests, real document/PDF fixtures, FC04 and live URL fetch proofs | High | PASS |
| Observability | Source allowlists/visibility tests, actual backends and metrics ready | High for current operation | PASS; old WAL completeness unverified |
| Docker/runtime | Seven clean builds; 20-service real readiness; offline import proof | High | FAIL: V01 |
| Reference navigation | Actual UI templates through real API with prior context | High | FAIL: V02 |
| Real-model product quality | All 12 attempts and 59 evaluated requirements retained | Low for semantic quality | NOT CERTIFIED; infrastructure-dominated FAIL |

## 16. File Integrity

After tests, all **480 versioned file hashes matched** the external starting manifest; git status remained clean. Existing historical review files were included in that comparison. No existing source or configuration was silently modified or reverted. Final recomputation after creating both reports confirms all 480 existing versioned files unchanged, nothing staged, only the new English report untracked and the German companion ignored. `final-integrity.json` retains status and hash comparison; the final incremental secret check and `git diff --check` also pass.

Allowed new report: `docs/reviews/final-comprehensive-verification-and-review-2026-10-16.md`. Matching `.de.md` is local and Git-ignored; it is not staged. Generated test artifacts remain ignored or external. Disposable test infrastructure was removed. Persistent volumes/model cache and unrelated containers were preserved. No reset, clean, prune or volume deletion was run.

## 17. Remaining Risks

The fresh dependency set remains non-operational until V01 is deliberately repaired outside this run. Complete live document retrieval, ordinary multi-turn investigation and semantic model quality cannot be certified on that baseline. Reference navigation remains predictably broken for the demonstrated actions until V02 is addressed. Synthetic/disposable approval proofs do not claim live physical recovery or crash-proof execution across the documented claim/write window. Historical telemetry completeness is uncertain for the one discarded pre-existing WAL entry. These limits are concrete and bounded; no speculative production-scale concerns are added.

## 18. Final Conclusion

**Can this implementation currently be considered to reliably satisfy its documented and promised functional, authorization, security and operational requirements? NO.**

The tested security and lifecycle boundaries hold, but clean-stack operability and meaningful reference-navigation behavior do not. Therefore the result is **FAIL**, based on reproducible core operational/product behavior rather than model wording or cosmetic concerns. CRITICAL 0; HIGH 0; MEDIUM 2; LOW 0.

The existing stack is left running for inspection, with 18/20 services healthy. Leaving a fully healthy stack would require repairing V01 or replacing the fresh image, contrary to the explicit no-repair instruction; neither was done. External model calls 0; real protected side effects 0; unexpected existing repository changes 0; commits 0; external deployments 0. This protocol ends the requested review.
