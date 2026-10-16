# Final Comprehensive Verification and Review — 2026-10-16

## 1. Executive Summary

**Final result: FAIL.** The complete deterministic backend, integration, FAST, frontend and safe browser suites pass. The tested authorization, RLS, classification, provider-egress, approval-generation and browser-lifecycle boundaries hold; no HIGH or CRITICAL security defect was demonstrated. Nevertheless, the cleanly rebuilt Knowledge image cannot start, preventing normal investigations and complete live discovery. Independently, current reference buttons generate requests rejected by the actual API classification contract. These are two reproducible **MEDIUM** operational/product defects. The implementation cannot currently be certified as reliably meeting its complete documented functional and operational promises. This conclusion does not treat missing infrastructure as model variance or an imperfect model explanation as a security failure.

This is a new measurement of HEAD `457761f8a924e2cd60e0271856cca87f3c41c71b`, not a continuation of an earlier report. The requested unsuffixed report already existed at the freeze. This uniquely named report preserves it and every other historical report. No defect was repaired; no source, assignment or existing configuration was changed. External model calls, real protected side effects, commits and external deployments: **0**.

## 2. Baseline

| Item | Value |
| --- | --- |
| Repository | `D:/Freelance/industrial-ai-agent` |
| Branch | `main` |
| HEAD | `457761f8a924e2cd60e0271856cca87f3c41c71b` |
| Freeze | `2026-10-16T08:16:32.1448462+02:00` |
| Initial Git status | Clean: staged 0, unstaged 0, untracked 0 |
| Python | PyCharm SDK `.venv/Scripts/python.exe`, Python 3.12.10 |
| Node / npm | v24.19.0 / 11.17.0 |
| Docker / Compose | Docker 29.8.2, build 7fc2dff / Compose v5.6.0 |
| Initial runtime | Knowledge unhealthy/restarting, API unhealthy; separate Ollama preserved |
| External evidence root | `D:/Freelance/industrial-ai-agent-verification-20261016-20261016-081632` |

`baseline.json` records the complete original status, staged/unstaged/untracked lists, running containers and image IDs. `versioned-files-before.json` contains SHA-256 hashes of all **481** versioned files, outside the repository. Python environment evidence is separate. Subsequent evidence filenames in this report are relative to that external root unless an explicit repository path is given.

The requirements checklist was established before interpreting results from current README, AGENTS, pyproject, frontend package scripts, Compose/Dockerfiles, overview, ADR-001–020 including supersession and later refinements, quality gates, Demo Auth, demo visibility, browser journeys, scenarios, public schemas and current source. Targeted-remediation and final-clean reports provided context and finding identifiers only. There is no root package.json or `.github/workflows`; current gates are repository scripts. The active contract preserves a single bounded sequential LangGraph agent, server-owned identity and classification, separate authorization/RLS/egress boundaries, generation-bound approvals, trusted complete inventories and fail-closed browser context ownership.

## 3. Clean Docker Rebuild

**Build PASS; complete-stack startup FAIL.** Executed `docker compose stop` and `docker compose build --no-cache`, both exit 0. The supported stack has **20 services and seven project-owned build targets**. All seven were rebuilt. Nginx/frontend and supporting services use third-party images. The historical migration image is not a current Compose build target; Factory startup owns migration and seed bootstrap.

| Service/image | Build | Image ID |
| --- | --- | --- |
| factory-mcp | PASS | `sha256:87a839cdaf1468a5859a1ba116c2c70ab3a0da4a3b50b2584333b7166bf94cd1` |
| runtime-mcp | PASS | `sha256:a6ea4c4c1dd6a111821a96e3a0236df62569a94b7c191e0c0fcc029ed5927d4a` |
| hardware-mcp | PASS | `sha256:b8dbc94153bb9ecac2a31f54014478406e9d7fa6bf4e8497827f72f96157f2df` |
| knowledge-mcp | PASS | `sha256:ab3841c8cd6f095a477df585d39a8773d629c4bcd772d0c35573adc5127712c3` |
| agent-api | PASS | `sha256:d79b11a3ea9440becadf5a3de23573a5a12af01d2e2d4b4a4a41817db8ace744` |
| rca-mcp | PASS | `sha256:c0d7682bc647af5e353e0623c65c788495355c768deeb32e0bf32461ca3849ac` |
| observability-mcp | PASS | `sha256:afe03c8dc455fac67a343bdf03caa56a8ccc6c4cdff543c4e9b7a511b4660360` |

`stack-before-stop.json`, `stack-after-stop.json`, `compose-stop.log`, `compose-build.log`, exit files and `rebuilt-images.json` retain exact evidence. No volume deletion, pruning, reset or clean command ran. Persistent PostgreSQL, model cache, telemetry volumes and unrelated resources were preserved. Package/base-image acquisition during the requested build is distinct from model inference; external LLM calls remained zero.

For runtime safety only, an **external** `local-only.compose.json` blanks public provider credentials in API/RCA and forces Knowledge to use cached model files offline. Repository Compose, `.env`, catalogs and persistent assignments remain unchanged. The same Knowledge failure is independently reproducible with `--network none`; it is not caused by the offline safeguard.

## 4. Stack Health

Supported startup: `docker compose -f compose.yaml -f <external>/local-only.compose.json up -d --no-build --wait --wait-timeout 300`. Exit **1**, because Knowledge becomes unhealthy. For independent diagnostics, the existing API and other services were started with `--no-deps`; the gateway container was started directly. This is not a passing startup or a repaired deployment.

| Service | Running | Docker healthy | Actual readiness | Restarts |
| --- | --- | --- | --- | ---: |
| agent-api | YES | unhealthy | NO: /ready 503 | 0 |
| factory-db | YES | healthy | YES | 0 |
| factory-mcp | YES | healthy | YES | 0 |
| frontend | YES | healthy | YES: gateway only | 0 |
| grafana | YES | healthy | YES | 0 |
| hardware-mcp | YES | healthy | YES | 0 |
| knowledge-mcp | RESTARTING | unhealthy | NO: import failure | 48 |
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

Snapshot time: `2026-10-16T08:39:09.6197753+02:00`.

**18/20 Docker healthy.** Knowledge remains in a persistent import/restart loop; API `/health` is 200 but `/ready` is 503. Gateway 200 certifies the gateway only. Knowledge's restart count continues increasing; every other service has zero restarts in the snapshot.

Actual readiness includes authenticated MCP initialize/tools-list for Factory, Runtime, Observability, RCA and Hardware; PostgreSQL SQL queries; Redis PONG; ClickHouse `/ping`; MinIO internal readiness; Langfuse web/worker health; Prometheus readiness and Collector target `up`; Collector metrics on configured port 8889; Tempo readiness/search; Grafana health; and local Ollama tags including `qwen3.5:9b`. Hardware readiness only discovers capabilities. Loki initially returned 503, later 200 (`loki-recovered.json`). Startup OTLP errors ceased after Collector became available. `readiness.json`, individual dependency readiness files and `collector-metrics.txt` retain these distinctions.

## 5. Test Results

| Gate | Current command / scope | Required | Passed | Failed | Skipped |
| --- | --- | --- | ---: | ---: | ---: |
| Entire backend | Configured Python `-m pytest tests -ra --junitxml=<external>/backend.xml` | Yes | 1963 | 0 | 1 |
| Unit subset of backend | `tests/unit` | Yes | 1670 | 0 | 1 |
| Integration subset of backend | `tests/integration` | Yes | 278 | 0 | 0 |
| Eval-scorer subset of backend | `tests/evals` | Yes | 15 | 0 | 0 |
| Separate INTEGRATION | `./scripts/run-quality-gate.ps1 INTEGRATION` | Yes | 278 | 0 | 0 |
| FAST backend | `./scripts/run-quality-gate.ps1 FAST`, unit substep | Yes | 1670 | 0 | 1 |
| Full frontend | `npm run test`, executed by FAST | Yes | 294 | 0 | 0 |
| Safe browser fixtures | `npm run test:e2e:fixtures -- --retries=0 --reporter=list,json --output <external>` | Yes | 105 | 0 | 0 |
| Real-model milestone | Current manual preflight plus all 12 journey attempts | Yes | 0 journeys | 12 journeys | 0 journeys |

Subset rows are not additional tests to add to the backend total. Backend collected 1964 tests, 35 warnings; integration had 31 warnings. The sole backend/FAST skip is Windows symlink creation unavailable in `tests/unit/test_document_content_storage.py:47`. Warnings are principally dependency deprecations and 30 JUnit `record_property` warnings; none is a failed assertion. Frontend was fully executed by FAST, with no cancellation or todo; it was not rerun to inflate totals.

All database-changing deterministic tests used a separate PostgreSQL 18.6 container `industrial-verification-20261016-081632`, port 55437, tmpfs storage and database `verification_comprehensive_20261016_081632`. Its application role is nonsuperuser/NOBYPASSRLS and does not own classified tables. Tests exercised real FK behavior, FORCE RLS, missing-clearance denial, migrations to 0025, upgrade preservation, seeds, durable runs, approval decisions/claims, idempotency and concurrency. No deterministic test targeted persistent demo data. After integration and browser completion, the explicitly labelled disposable container was validated, stopped and removed without deleting project volumes. Cleanup identity/database evidence is retained.

The fixture registry was listed before execution: **105 tests in six specs**. All ran once, **retries 0, flaky 0**: Demo Auth 46, MIME 1, discovery 20, transcript Blob 15, journey evidence 18, approval 5. Coverage includes all identities, account/configuration/Monitoring/language, logout, failed refresh, cross-tab invalidation, BFCache/pagehide, late JSON/error/download/PDF, actual retained Object URLs, filenames, document/server/transcript PDFs, stale approvals and complete DE/EN RLS-backed inventories. Registry, per-case status, JSON report and pipeline attachments are external.

The command inventory is `gate-inventory.json`. The older five-journey `npm run test:e2e` is documented as the older browser path, not the current twelve-journey milestone; the current manual runner was used. Optional model/provider evaluation CLIs are not deterministic gates and were not used to invoke external models. No configured JS lint, typecheck or frontend bundler build command exists.

## 6. Quality Gates

| Check | Result / evidence |
| --- | --- |
| FAST unit substep | PASS: 1670 passed, 1 explicit skip |
| FAST frontend substep | PASS: 294 passed |
| FAST Ruff | PASS: `ruff check src tests scripts` |
| FAST format | PASS: `ruff format --check src tests scripts`, 257 files |
| FAST secret scan | PASS: `scripts/check-demo-secrets.py` |
| JavaScript syntax | PASS: 44 tracked non-vendor JS/MJS files, `node --check` |
| Documentation conformance | PASS: 14 current deterministic cases in backend/FAST |
| EN/DE / diagrams | PASS for companion structure and Mermaid counts across 61 existing technical Markdown files; current auth/discovery/model/architecture translations spot-reviewed; this report fully paired |
| Local links | PASS: no broken local path among 73 tracked Markdown files; external URLs and anchor semantics not certified |
| ADRs | ADR-001–020 references/status/refinements inspected; no architecture change introduced |
| Environment structure | PASS: same 43 keys/order in `.env` and `.env.example`, no duplicates; values not exposed |
| Package wheel | PASS: offline `pip wheel --no-deps --no-build-isolation --no-index` from external source copy |
| Compose config | PASS: `docker compose config --quiet` |
| Whitespace | PASS: `git diff --check` |
| JS lint / typecheck / frontend build | NOT_CONFIGURED; static frontend served by Nginx |

The secret check is the configured incremental high-signal scanner, not an exhaustive history or dependency-vulnerability scan. No implementation or existing diagram changed, so no architecture diagram required editing. Final report integrity, translations, paths and secret checks were also verified after writing.

Verifier setup issues are not product findings: the first pytest command collected zero tests because of its JUnit argument; the first disposable seed invocation lacked `FACTORY_DATA_ROOT`; PYTEST_ADDOPTS backslash processing placed two XML artifacts temporarily in an untracked repository directory; and an extra document probe initially expected JSON from the actual binary inline route. These were corrected only in external evidence setup. Original failed logs are retained. The two XML files were explicitly relocated outside the repository and their empty directory removed; no user/source file was deleted or reverted. Registered browser fixtures were never retried. Early journey metadata honestly records the temporary JUnit dirty path; product/harness fingerprints match and final aggregation accepts current provenance.

## 7. Demo Auth

Live rebuilt API/Nginx/Chromium smoke: fresh `demo-public`; HttpOnly/SameSite=Strict cookie scoped to `/api/`; no Basic challenge or obsolete clearance selector. Header order is Monitoring → Configuration → Account; investigation toolbar PDF → New Chat. Cookie identity/roles are authoritative; Nginx strips browser Authorization. Direct-bearer narrowing is separate and cannot increase authority.

| Identity | Clearance | Roles | Configuration API / UI | Switch, logout, login |
| --- | --- | --- | --- | --- |
| demo-public | PUBLIC | none | 403 / disabled | PASS |
| demo-internal | INTERNAL | none | 403 / disabled | PASS |
| demo-confidential | CONFIDENTIAL | none | 403 / disabled | PASS |
| demo-restricted | RESTRICTED | none | 403 / disabled | PASS |
| demo-admin | PUBLIC | MODEL_ADMIN | 200 / enabled | PASS |

Language DE survives quick switching for all five users. Logout persists across refresh; after explicit login plus reload, empty-workspace language is EN. That limited language observation is not a security or material product defect. Protected state is purged on identity changes. Live same-tab and cross-tab proofs capture a confidential synthetic transcript PDF URL, verify it is readable before downgrade, then directly fetch that same URL after PUBLIC downgrade: unreadable, marker absent, protected DOM cleared and export disabled. Synthetic run submission is intercepted, so this proof uses no model or real action (`live-blob-lifecycle.json`).

## 8. Station Visibility

Prompt: `welche stationen kennst du`. Current seed was checked through read-only SQL as `factory_app`, then authenticated Factory MCP independently for every identity.

| Identity | Exact SQL / Factory MCP IDs | Isolated trusted result → persisted API → browser DE/EN | Fresh-stack API / persistence / browser |
| --- | --- | --- | --- |
| demo-public | S01 S05 | PASS | Failed run: MCP unavailable |
| demo-internal | S01 S02 S03 S05 | PASS | Failed run: MCP unavailable |
| demo-confidential | S01 S02 S03 S04 S05 S06 | PASS | Failed run: MCP unavailable |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | PASS | PASS: all exact sets match |
| demo-admin | S01 S05 | PASS | Failed run: MCP unavailable |

Live **1/5**, not complete certification. No hidden IDs or duplicates appear in the successful inventory. Current unit, real-RLS/durable-API and first-run Chromium cases prove that sparse, invented or fallback model narratives cannot alter typed inventory completeness. References remain independently bounded; status absence does not drop a station.

## 9. Product Visibility

Prompt: `Welche Produkte kennst du?`.

| Identity | Count | Exact SQL / Factory MCP IDs | Isolated trusted/persisted/API/browser | Fresh-stack final result |
| --- | ---: | --- | --- | --- |
| demo-public | 2 | P4101 P4102 | PASS | Failed run: MCP unavailable |
| demo-internal | 4 | P4101 P4102 P4900 P4901 | PASS | Failed run: MCP unavailable |
| demo-confidential | 9 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 | PASS | Failed run: MCP unavailable |
| demo-restricted | 11 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 P9001 P9002 | PASS | Failed run: MCP unavailable |
| demo-admin | 2 | P4101 P4102 | PASS | Failed run: MCP unavailable |

Live **0/5**. The combined ten-row inventory smoke passes 1/10. Read-only persistent run inspection confirms the exact discovery requests failed with `mcp_service_unavailable`, not successful incomplete answers. Isolated proofs retain all authorized products, reject model inventions, survive narrative fallback and keep the 12-reference budget separate from inventory. The existing 8000-character answer bound explicitly declares partialness beyond its limit. Evidence: `live-factory-inventory.json`, `live-inventory-smoke.json`, `live-persisted-inventories-v2.json`, integration XML and Chromium pipeline attachments.

## 10. Security / Regression Status

Each status uses this run's actual tests and fresh source review. CLOSED applies to the named invariant, not universal product availability.

| ID | Status | Current evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 async-I/O cases: blocking work off event loop, context/cancellation ownership |
| C02 | CLOSED | 19 provider lifecycle cases: capacity, deadlines, cancellation and drain |
| C03 | CLOSED | 25 stabilization regressions plus real guard spies/MockTransport positive controls |
| C04 | CLOSED | 31 provider transport cases: HTTPS before credentials/SDK/transport, no proxies/redirects |
| C05 | CLOSED | 14 current documentation conformance cases; ADR and dependency review |
| C06 | CLOSED | 20 unit + 9 PostgreSQL approval-generation cases, immutable binding and atomic consumption |
| R01 | CLOSED | 29 raw-provider authorization cases; denied credential/SDK/serialization/transport counters all zero |
| R02 | CLOSED | 25 unit + 2 PostgreSQL ticket-I/O cases, owned completion and fail-closed retry |
| R03 | CLOSED | 18 unit + 6 PostgreSQL + 5 Chromium approval cases; old approve/reject cannot decide new generation |
| R04 | CLOSED | Cross-tab, failed refresh, late JSON/binary, BFCache/pagehide and live Blob proofs |
| R05 | CLOSED | 19 provider-client ownership cases: concurrent cold creation, close/drain/cleanup |
| R06 | CLOSED | Current session docs/harness and live five-user authentication; no current Basic/clearance-header model |
| N01 | CLOSED | 21 real RLS/FK cases; visible product retained, hidden event/station fields and counts omitted |
| FC01 | CLOSED | 29 real-RLS cases; ticket with hidden station returns neutral unavailable without crash or leak |
| FC02 | CLOSED | 37 real-RLS cases; emitted-data classification joins reach final egress boundary |
| FC03 | PARTIAL | Deterministic completeness regression closed; deployed live product inventory blocked 5/5 by V01 |
| FC04 | CLOSED | 15 first-run retained-URL Chromium cases plus live same-tab/cross-tab direct fetch proofs |

Critical spot proofs A–E were exercised directly: genuine FK/RLS combinations for visible Product/Event with hidden Station and visible Ticket with hidden Station; PUBLIC parent plus emitted CONFIDENTIAL relation yields at least CONFIDENTIAL, while RESTRICTED caller plus PUBLIC-only output stays PUBLIC; stale displayed generation A cannot approve generation B; unauthorized raw adapters and PUBLIC_CLOUD HTTP reach no credentials/SDK/transport; confidential DOM/retained PDF URL cannot survive PUBLIC downgrade. Protected execution tests use synthetic/disposable state only. Embedding egress has 278 deterministic cases, including absent/invalid labels, query/batch paths and local-destination constraints. Exact executed test names are retained in XML and `critical-direct-proofs.json`.

## 11. Real-Model Product Quality

Repository artifacts: `evals/results/browser-e2e/comprehensive-local-20261016-081632/`. Manual wrapper preflight correctly BLOCKED on Knowledge. The current individual runner then attempted all twelve journeys once using `--all`, retaining its LOCAL-only assignment guard and real Demo Session flow. No caller clearance headers were synthesized, no assignment was mutated and no protected action was approved. Aggregation: **12/12 artifacts, preflight BLOCKED, execution BLOCKED, product quality FAIL**.

| Journey | Actual artifact | Reviewed category | Required | Passed | Failed | Blocked/not-run |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| S04 fault investigation | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 6 | 1 | 3 | 2 |
| Station discovery | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| Product history | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| Documentation chain | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 8 | 2 | 3 | 3 |
| Clearance boundary and continuation | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 9 | 3 | 4 | 2 |
| Station discovery DE | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 2 | 2 | 0 |
| Healthy station investigation DE | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 3 | 0 | 2 | 1 |
| Healthy station investigation EN | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| S04 fault investigation EN | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 0 | 3 | 1 |
| Product-centric EN | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 3 | 0 | 2 | 1 |
| Clearance boundary EN | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 6 | 3 | 3 | 0 |
| Restricted information path | FAIL / HARNESS_ERROR | INFRASTRUCTURE_ERROR | 4 | 2 | 2 | 0 |

All **59 required assertions were evaluated**; 46 executed, 13 passed, 33 failed, 13 blocked/not-run. Evaluated is not executed or passed. Optional and manual-only claims remain separate. Additional critical inventory smoke: 1 passed, 9 failed.

Independent persisted API readback finds **21 failed terminal results**, all `mcp_service_unavailable` / MCP, and **4 successful terminal results**. Every journey contains an infrastructure-caused failed run. The raw runner label `HARNESS_ERROR` is preserved; reload timeouts and missing references often determine that aggregate label. The reviewed dominant category for each journey is therefore INFRASTRUCTURE_ERROR. No entire journey passed; general semantic model quality is **not certified** on this baseline. This is neither proof that the model provider is unavailable nor evidence that the repository is generally insecure. V02 is separately deterministic and does not depend on Knowledge availability.

## 12. Runtime / Logs

Logs from all **20 services** were collected after the journeys and searched for ERROR, CRITICAL, FATAL, Traceback, Exception, panic, restart, connection refused, timeout, 401, 403, 404, RLS, migration, provider, worker, session, approval, database and OTel. Keyword hits are not defect counts.

| Meaningful entry | Classification | Assessment |
| --- | --- | --- |
| Knowledge missing `torch.distributed.checkpoint.hf_storage`, repeated exits | PRODUCT_DEFECT / MEDIUM | Persistent V01, reproduced network-free |
| API readiness 503 / failed MCP terminal results | PRODUCT_DEFECT / MEDIUM | Consequence of V01, not another finding |
| Anonymous/logout 401, non-admin config 403, protected/missing-resource 404 | EXPECTED_NEGATIVE_TEST | Correct denial |
| Unsupported UI reference prompt 404 under valid authorized session | PRODUCT_DEFECT / MEDIUM | Independently reproduced V02 |
| Factory/RCA OTLP DNS/UNAVAILABLE/deadline errors before Collector startup | EXPECTED_STARTUP_WARNING | Later metrics export and scrape succeed |
| Loki empty ring / initial 503 | EXPECTED_STARTUP_WARNING | Recovered to readiness 200 |
| Tempo single-binary worker/optional metrics-generator notices; Grafana API-authorizer notices and absent optional plugin/alerting provisioning directories | BENIGN_WARNING | Current configured services/dashboards ready; no promised plugin/alert failure demonstrated |
| Tempo removes one old incomplete WAL entry with missing meta.json at startup | OBSERVATION | Current search works; historical trace completeness not certified |
| Langfuse workers, PostgreSQL checkpoints, MCP session lifecycle | Routine / benign | No additional persistent application error identified |

Raw service logs, keyword counts and recovery evidence are external. No expected denial was counted as a security defect.

## 13. Overall Architecture / Security Review

The fresh source review started **after all test/journey execution**, at the time recorded in `fresh-review-start.txt`. It traced the public API through identity, classification, model resolution/provider guards, MCP, repositories, persistence and final browser projection. A tracked-source AST scan covered 120 Python modules, including 55 Core modules, with no prohibited inward Infrastructure/SDK import or syntax error. This is supporting evidence, not a claim of formal verification of dependencies.

**Architecture/orchestration:** Concrete adapters are assembled at outer composition roots. Domain/capabilities use inner types and ports. LangGraph remains the sole troubleshooting loop, executes at most one admitted tool per iteration, retains the four-tool bound and deterministic first inventory read, and separates approval from execution. Evidence-ledger finalization depends on authorized typed observations and eligible source capabilities, not model claims. The MCP compatibility adapter discovers tools, intersects explicit permissions and delegates to existing capabilities; diagnostic MCPs do not expose unrestricted agent queries.

**Identity/authorization:** DemoSessions owns opaque random bounded process-local sessions, revokes prior tokens on switch/logout and emits only safe metadata. Disabled mode does not install convenience mutations. Same-origin mutation checks and HttpOnly/Strict cookies protect the intended loopback demo flow. Admin role and clearance remain orthogonal. Shared investigation visibility by classification is the explicit contract, not private per-user tenancy. Browser-controlled clearance cannot expand authority.

**RLS/projections/documents:** Each application transaction sets parameterized transaction-local clearance. Non-owning, non-bypass roles and FORCE RLS protect classified rows. Product event/station visibility is independent from the product; hidden relations do not leak IDs, counts or classifications. Missing mandatory ticket-station visibility gives neutral unavailable. Projection labels join emitted protected values, not caller clearance. Document access authorizes before resolving a root-constrained catalog path, checks checksum, sanitizes MIME/filename and serves no-store/nosniff/sandbox responses. Live authorized document bytes match downloads for all five identities; hidden and unknown documents have identical neutral responses. Server PDFs reauthorize their source investigation.

**Model boundary/lifecycle:** Persistent assignments configure selection but do not authorize it. MANUAL uses exactly its stable model ID; AUTO filters availability/capability/security before ranking. Provider failures do not reselect. Request-bound authorization is checked before adapter serialization/client access; effective destination validation precedes credentials/SDK/transport and requires HTTPS for PUBLIC_CLOUD. Proxies and redirects are disabled. Embeddings retain a separate explicitly classified local-only boundary. Provider clients serialize cold creation, own in-flight calls through drain, close resources and enforce bounded deadlines; tests cover cancellation and concurrent ownership.

**HITL/persistence/recovery:** The displayed UUID binds proposal, decision, execution claim and idempotency. PostgreSQL row locks reject stale generations before decision updates. Executing capabilities additionally require current clearance, exact run/profile/action/target, approved history and atomic single use, including direct MCP calls. Ticket uniqueness and authorized existing-result lookup prevent duplicate creation. Owned blocking I/O completes before cancellation propagates. This is not crash-proof exactly once: approval consumption and ticket write are separate transactions, and a consumed generation with no result fails closed rather than retrying the side effect, as ADR-011 explicitly states. Recovery additionally requires independent post-action observation/verification; no live action was exercised here.

**Frontend/error handling:** Generation checks and abort ownership guard JSON/binary publication; one Object URL registry covers document, server PDF and transcript PDF. Identity invalidation purges before session mutation, broadcasts independently of refresh success, and remains empty on unknown identity. Pagehide revokes/purges; BFCache restoration revalidates. Stale approval conflicts require another explicit decision. First-run browser and direct retained-URL proofs support these paths. The reproducible navigation defect is the reference-template/request-contract mismatch, V02.

**Observability/runtime/docs:** Metadata allowlists, bounded metric labels and sanitized diagnostic projections preserve the reviewed telemetry boundary. Run-scoped diagnostic reads check persisted visibility before backend access. Current docs and local translations describe the active session, inventory, model and approval contracts consistently at the inspected boundaries; superseded ADR mechanisms remain historical. The material operational inconsistency is deployment behavior: successful package resolution/build does not produce an importable Knowledge runtime. No cosmetic naming, speculative scale or unreachable race was promoted to a finding.

## 14. Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

#### V01 — Fresh Knowledge image cannot start

- **Severity/category:** MEDIUM; deployment reliability and core investigation availability.
- **Affected path:** `Dockerfile.knowledge-mcp:18`, dependency installation at line 24; `src/industrial_ai_agent/infrastructure/sentence_transformers_reranker.py:4`; Knowledge startup composition.
- **Evidence:** Clean no-cache build succeeds. Fresh image resolves Torch `2.7.1+cpu`, torchvision `0.22.1+cpu`, Transformers `5.20.0`, Sentence Transformers `5.7.0`, Docling `2.125.0`. Importing the repository reranker fails because Transformers imports `torch.distributed.checkpoint.hf_storage`, absent from that Torch. `knowledge-offline-import-proof.log` reproduces it in a disposable `--network none` container. Stack readiness, runtime logs and failed persisted runs agree.
- **Expected:** Every built project image starts; authenticated Knowledge readiness and dependent API readiness succeed; supported investigations/discovery can execute.
- **Observed:** Persistent Knowledge restart loop, API `/ready` 503, 21 sampled failed terminal results with MCP origin; live inventories pass only 1/10.
- **Impact:** Ordinary troubleshooting, documentation retrieval and most inventory flows are unavailable. No unauthorized disclosure or protected execution was demonstrated.
- **Reproduction:** `docker compose build --no-cache`; supported startup; inspect Knowledge logs/readiness. Independently run the built image with `--network none --entrypoint python`, offline model flags and import `industrial_ai_agent.infrastructure.sentence_transformers_reranker`.
- **Why tests did/did not catch it:** Host tests exercise the installed host environment and fakes; they do not resolve/import the fresh Docker ML dependency set. This run's image startup and network-free import proof catch it; readiness itself correctly fails closed.
- **Recommended remediation:** Establish a compatible constrained CPU Torch/Transformers/Sentence Transformers set and add a small built-image import/readiness check. Validate it with another deliberate clean build. **Not implemented here.**

#### V02 — Reference buttons submit unsupported request forms

- **Severity/category:** MEDIUM; promised reference navigation / frontend-to-API integration.
- **Affected path:** `frontend/js/app.js:662` (`identifierActions`); `src/industrial_ai_agent/agent/run_classification_policy.py:159` and API request admission.
- **Evidence:** `reference-prompts.json` extracts 16 current station/product/fault DE/EN action templates. `reference-admission-proof.json` sends them through real DemoSessions/FastAPI/classification with an existing authorized investigation, substituting only execution: **13/16 receive 404 `requested_data_unavailable`; 3 supported German controls succeed**. No model or real action is used.
- **Expected:** An action offered for an authorized reference creates an admitted same-context request while arbitrary free text retains conservative classification.
- **Observed:** PUBLIC S01 `Check the current status of station S01.`, CONFIDENTIAL S04 `Untersuche Station S04 genauer.`, and INTERNAL P4901 `Show the product history for P4901.` are rejected before execution. German `Prüfe den aktuellen Status von Station S01.` and `Zeige die Produkthistorie von P4901.` pass. Fault investigation/search actions also fail in the checked context.
- **Impact:** Common visible reference actions fail reproducibly even when the target is authorized and execution is healthy. The security boundary correctly rejects the unsupported prose; relaxing it is not the remedy.
- **Reproduction:** Establish the corresponding Demo Session; create the documented admitted initial station/product/fault request; submit its exact UI-generated action text with its investigation ID, language and same-origin session header.
- **Why tests did/did not catch it:** Frontend rendering/template tests and synthetic HTTP fixtures do not uniformly run emitted reference templates through the actual classifier. Typed-journey contract tests cover registry prompts rather than every action template. The cross-boundary probe exposes the mismatch independently from V01.
- **Recommended remediation:** Align emitted prompts with admitted neutral forms or introduce a bounded typed reference-action contract, preserving unknown-text classification. Add deterministic DE/EN template-to-API admission tests for relevant identities. **Not implemented here.**

### LOW

None.

### Observations

O01: Automatic journey labels obscure the infrastructure cause; raw labels and corrected review categories are both retained. No passing gate is manufactured from that correction. O02: Tempo discarded one pre-existing incomplete WAL entry, limiting historical trace-retention confidence. O03: Language survives quick switch but resets to EN after explicit logout/login plus reload of the empty workspace. These observations do not inflate the formal finding count.

## 15. Requirement Confidence Matrix

| Requirement | Current evidence | Confidence | Status |
| --- | --- | --- | --- |
| Demo Auth | Session tests + live five-user rebuilt gateway smoke | High | PASS |
| Cross-tab purge | R04/FC04 first-run Chromium + live retained URL proof | High | PASS |
| RLS isolation | Real application role, FORCE RLS, missing-clearance controls, live SQL | High | PASS |
| Related-object visibility | N01 21 / FC01 29 real FK/RLS cases and projection review | High | PASS |
| Classification propagation | FC02 37 cases; emitted-data join and egress controls | High | PASS |
| Station Discovery | 20 unit + 30 integration + 10 Chromium, live Factory exact matrix | High algorithm / limited deployment | PARTIAL: live 1/5 |
| Product Discovery | 14 unit + 30 integration + 10 Chromium, live Factory exact matrix | High algorithm / limited deployment | PARTIAL: live 0/5 |
| Model egress | R01/C03, request-bound authorization and embedding tests | High | PASS |
| PUBLIC_CLOUD TLS | 31 transport cases, zero denied boundary counters | High | PASS |
| Approval generation | C06/R03 unit, real PostgreSQL locks, five Chromium cases | High | PASS |
| Replay/idempotency | Synthetic/disposable claims, unique constraints and concurrency | High within documented failure model | PASS; no crash-proof exactly-once claim |
| Ticket persistence | Real PostgreSQL persistence plus owned I/O/cancellation | High | PASS with synthetic state |
| Document access | RLS/path/checksum/MIME/filename tests + live five-user direct reads | High boundary / limited retrieval | PASS access; live search blocked |
| PDF/blob lifecycle | Backend PDF, browser exports and live captured-URL fetches | High | PASS |
| Observability | Visibility/allowlist tests, ready backends, Collector scrape UP | High current operation | PASS; old WAL retention uncertain |
| Docker/runtime | Seven clean images; readiness and offline import proof | High | FAIL: V01 |
| Reference navigation | Actual templates through real admission with prior context | High | FAIL: V02 |
| Real-model product quality | 12 artifacts / 59 evaluated required assertions | Limited by infrastructure | NOT CERTIFIED / FAIL |

## 16. File Integrity

All **481 original versioned files** match the external starting hash manifest after tests and after the fresh review. Before report creation, Git status was clean. Final verification after report creation confirms the same original-file hashes, no staged files, only this new English report untracked and its German companion ignored. Historical reports, existing source/configuration and local user changes were neither overwritten nor reverted. The unsuffixed historical report remains included in the matching manifest.

Allowed additions are this new report and its ignored `.de.md` companion. Generated test/evidence artifacts remain external or ignored. The two temporary untracked JUnit artifacts were recorded and moved out, leaving no unexpected existing-file modification or extra repository artifact. `integrity-after-review.json`, final manifest and integrity/status evidence retain this distinction. No reset/clean/prune/volume deletion, commit, push or external deployment occurred.

## 17. Remaining Risks

V01 prevents reliable operation of the clean deployment until a separate authorized repair. Semantic model quality and complete live document-search/multi-turn behavior cannot be inferred from infrastructure-dominated failures. V02 blocks demonstrated reference navigation. HITL guarantees retain ADR-011's explicit consumption-to-write crash window; tests do not certify real physical recovery. Tempo's discarded old WAL entry prevents certifying complete historical trace retention. No hypothetical future scalability or cosmetic concern is added.

## 18. Final Conclusion

**Can this implementation currently be considered to reliably satisfy its documented and promised functional, authorization, security and operational requirements? NO.**

The tested security and lifecycle guarantees hold, but clean-stack operability and important reference navigation do not. Final result **FAIL**; **CRITICAL 0, HIGH 0, MEDIUM 2, LOW 0**. This decision follows reproducible promised behavior, not wording preferences or ordinary model variance.

The stack remains running for inspection, with 18/20 services healthy. A fully healthy stack would require repairing V01 or replacing the verified fresh image, contrary to the no-repair instruction. Neither was done. External model calls 0; real protected side effects 0; unexpected existing repository modifications 0; commits 0; external deployments 0. This report completes the single requested run.
