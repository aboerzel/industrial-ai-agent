# Final Comprehensive Verification and Review — 2026-10-16

## 1. Executive Summary

**Final result: FAIL.** The clean deployment, deterministic backend gates, authorization, RLS, classification, model-egress, approval and inventory boundaries hold in the executed checks. The implementation cannot currently be certified as reliably satisfying **all** promised functional and operational requirements: the current local real-model product gate passes only 7/12 journeys, and a separate deterministic production-path proof demonstrates event-loop blocking during provider cleanup after cancellation. An older registered browser gate also fails its current session/request contract. Findings: **CRITICAL 0, HIGH 0, MEDIUM 2, LOW 1**. This is an operational/product-quality failure, not a finding that the repository is generally insecure.

This is one new verification run; no finding was repaired. The requested unsuffixed report and an earlier same-day run already existed, so this report uses `-run-120936` to preserve them. Its German companion is local and Git-ignored. Evidence, commands, logs, XML, browser attachments and verifier scripts are retained outside the repository at `D:/Freelance/verification-evidence-2026-10-16-120936/`. Current manual journey artifacts are in the ignored `evals/results/browser-e2e/comprehensive-local-20261016-120936/` directory. Historical results were not used as current passes.

## 2. Baseline

| Item | Frozen value |
| --- | --- |
| Repository | `D:/Freelance/industrial-ai-agent` |
| Branch | `main` |
| HEAD | `0e55a379fc6b710d4dfdb78d3e1174ee39c32718` |
| Initial Git status | Clean; upstream `origin/main`, ahead 0 / behind 0 |
| Staged / unstaged / untracked | None / none / none |
| Python / environment | 3.12.10; configured `.venv/Scripts/python.exe`; pip |
| Node / npm | v24.19.0 / 11.17.0 |
| Docker | 29.8.2, build `7fc2dff` |
| Compose | v5.6.0 |
| Initially running | 20 project services and the separate existing `ollama` container |
| Frozen manifest | SHA-256 of all 493 versioned files, outside the repository |

The contract review covered AGENTS, README, package definitions, Compose, the architecture overview, ADR-001–020 with supersession/refinements, current quality/auth/visibility/journey/reference guides, scenarios, public schemas, remediation reports and prior final-clean evidence. Active contracts and current code took precedence over historical mechanisms. No CI workflow is configured. `requirements-and-gates.md` records the gate inventory and promised-behavior checklist.

## 3. Clean Docker Rebuild

**PASS.** `docker compose down` stopped the complete project stack without deleting volumes. Only the independent Ollama runtime remained running before disposable test infrastructure was created. `docker compose build --no-cache` rebuilt every current project-owned application image successfully.

| Image/service | Build | New image ID (`sha256:`) |
| --- | --- | --- |
| agent-api | PASS | `f008bb2387088f645960b83af37dff8b212218bebcd56880290ff2c44ac17151` |
| factory-mcp | PASS | `751c77c3897b307be4d8a448b2c1eccdcd7d3e0a544616ae27cde7c35b5f6950` |
| hardware-mcp | PASS | `6e94f4170cf6e6ca57c0ba6fb9bdd287aea36265aea1f4fb5000d699f9ce818e` |
| knowledge-mcp | PASS | `3d81ff25992db3a31c0573aaccd6fbd49d91f393ccd3e8c524f3909a01fbb3ab` |
| observability-mcp | PASS | `19d433b35e84126c0b9b561f3be02115dc1f22fa5fac05ab7a3c599dc9cb6374` |
| rca-mcp | PASS | `3c03edbdc7a34b267074ca3e02c468cd1a2d3e78f8a58ff9ee97352db853e2bf` |
| runtime-mcp | PASS | `c39e970c3b45ec0e5ce4d3c909f2ae5705719e905f8f48e105c8fadc040eabaf` |

Frontend is a third-party Nginx image with read-only source mounts; supporting services use third-party images. The old auxiliary `factory-db-migrate` image is not a current Compose build target. Current migrations run through Factory startup. Thus seven, not eight, application images are required.

The supported base stack first started successfully. A Knowledge startup Hub-metadata lookup prompted an external safety-only Compose override: cloud keys empty, Hugging Face offline, local-only reranker loading and read-only existing model cache. Final verification uses that override, without changing source or `.env`. Builds resolved software artifacts; no repository inference input was sent to an external model. Evidence: `docker-stop.log`, `docker-build.log/.exit`, `build-image-ids.json`, both startup logs and `local-only.compose.json`.

## 4. Stack Health

Final state: **20/20 running, healthy and ready; all restart counts 0**.

| Service | Running | Docker healthy | Actual readiness | Restarts |
| --- | --- | --- | --- | ---: |
| agent-api | Yes | Yes | `/health`, `/ready` 200 | 0 |
| factory-db | Yes | Yes | SQL and application-role/RLS queries | 0 |
| factory-mcp | Yes | Yes | Authenticated initialize/list-tools and inventory reads | 0 |
| frontend | Yes | Yes | Gateway health, browser and session flows | 0 |
| grafana | Yes | Yes | `/api/health` 200 | 0 |
| hardware-mcp | Yes | Yes | Authenticated protocol/required tools; no execution | 0 |
| knowledge-mcp | Yes | Yes | Protocol, real retrieval; independent offline KDEP proof | 0 |
| langfuse-clickhouse | Yes | Yes | `/ping` succeeds | 0 |
| langfuse-minio | Yes | Yes | `/minio/health/ready` succeeds | 0 |
| langfuse-postgres | Yes | Yes | SQL `SELECT 1` | 0 |
| langfuse-redis | Yes | Yes | Authenticated PONG | 0 |
| langfuse-web | Yes | Yes | Public health with database check 200 | 0 |
| langfuse-worker | Yes | Yes | Worker `/api/health` succeeds | 0 |
| loki | Yes | Yes | Actual `/ready` 200 | 0 |
| observability-mcp | Yes | Yes | Authenticated protocol/required tools | 0 |
| otel-collector | Yes | Yes | Live exported metrics and Prometheus target UP | 0 |
| prometheus | Yes | Yes | `/-/ready` 200, target UP without last error | 0 |
| rca-mcp | Yes | Yes | Authenticated dedicated RCA tool discovery | 0 |
| runtime-mcp | Yes | Yes | Authenticated runtime tool discovery | 0 |
| tempo | Yes | Yes | `/ready` and trace search 200 | 0 |

The independent original Ollama container remains running and serves its model catalog; it has no Docker healthcheck. During observed failures, chat and embedding models both reported 100% GPU. Readiness does not certify generation reliability: see M01.

Initial API/Knowledge non-readiness during the safety-override recreation is preserved and later recovered. The disposable Knowledge image briefly became unhealthy during cold initialization, then passed authenticated readiness with zero restarts. Evidence: `readiness-first.json`, `readiness-settled.json`, `readiness-final.json`, stack snapshots, support readiness exits, Prometheus targets and KDEP startup samples.

## 5. Test Results

| Gate | Command/scope | Passed | Failed | Skipped/not run | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Full backend | Configured Python `-m pytest tests -ra --junitxml=...` | 2044 | 0 | 6 | PASS with explicit skips |
| Unit subset of backend | `tests/unit` | 1750 | 0 | 1 | PASS |
| Integration subset of backend | `tests/integration` | 279 | 0 | 5 | PASS with opt-in skips |
| Golden scorer subset | `tests/evals` | 15 | 0 | 0 | PASS |
| Separate INTEGRATION | `scripts/run-quality-gate.ps1 INTEGRATION` | 279 | 0 | 5 | PASS with opt-in skips |
| FAST unit | `scripts/run-quality-gate.ps1 FAST` | 1750 | 0 | 1 | PASS |
| FAST frontend | Same gate | 328 | 0 | 0 | PASS |
| Separate frontend | `npm --prefix frontend test` | 328 | 0 | 0 | PASS |
| Safe browser first run | All 140 registrations; `--retries=0` | 139 | 1 | 0 | First run FAIL |
| Explicit FC04 diagnostic | Only original failed case, no retries | 1 | 0 | 0 | Original case classified FLAKY |
| Current Real-Model E2E | `e2e:manual -- --run-id comprehensive-local-20261016-120936` | 7 journeys | 5 journeys | 0 journeys | FAIL |
| Older browser command | Unmodified `test:e2e`, retries 0 | 0 | 1 | 4 | FAIL / serial abort |
| Explicit KDEP deployment | `test_knowledge_container_runtime.py`, opt-in | 5 | 0 | 0 | PASS |

Subset/repeated-gate rows are not additive. The six normal backend skips are five intentionally opt-in deployment cases, all subsequently executed above, and one unavailable Windows symlink-creation case. Dependency deprecations and JUnit `record_property` compatibility warnings remain visible in logs/XML.

Integration used a labelled disposable PostgreSQL 18.6 tmpfs container and migrated `verification_final`, a non-owning NOSUPERUSER/NOBYPASSRLS application role, real foreign keys and FORCE RLS. No persistent demo data was used for mutation tests. KDEP additionally used an internal network, read-only existing caches and an isolated local embedding runtime. All disposable infrastructure was removed, including an explicit database drop.

Backend scopes include all six MCP boundaries, API/session/role authorization, migrations, seeds, persistence, protected-action fakes, generation/replay/concurrency, ticket I/O, document/PDF, classification/egress, inventories, evidence requirements and reference admission. Registered browser coverage includes all identities, auth refresh/cross-tab/BFCache/pagehide, configuration/monitoring, stale JSON/download/PDF, approvals, discovery, filenames and actual Object URL reads/revocation.

The original FC04 normal-logout failure was `net::ERR_CONNECTION_FAILED` reaching the synthetic loopback server, before its security assertion. Its single executed diagnostic passed. **Browser certification remains 139 PASS / 1 FLAKY, not 140 clean first-run passes.** No automatic retries occurred. An initial diagnostic filter selected zero cases; that setup error is retained separately.

The older browser harness was copied byte-for-byte externally because its report destinations are fixed. All 13 copied files match original hashes; only its node_modules location is a junction to installed local dependencies. This preserves historical generated reports without modifying the tested assertions. Evidence: XML/logs, fixture JSON/attachments, `legacy-harness-byte-integrity.json` and journey artifacts.

## 6. Quality Gates

| Check | Result / evidence |
| --- | --- |
| Ruff | PASS via complete FAST, `src tests scripts` |
| Format | PASS; 261 files already formatted |
| Incremental credential scan | PASS; repository-defined scope, not a historical secret-scan claim |
| JavaScript syntax | PASS; all 48 tracked JS/MJS files |
| JS lint / typecheck / frontend compilation | NOT_CONFIGURED; no such package scripts |
| Documentation conformance | 14 deterministic current-contract tests pass; does not erase L01 |
| English/German companions | All relevant tracked technical companions present |
| Mermaid | Matching companion counts; inspected architecture flows remain applicable; no existing diagram changed |
| Local Markdown paths / ADR index | No broken checked local paths; ADR-001–020 present; remote URLs/anchor semantics not tested |
| Environment structure | Same 43 keys/order, no duplicates; secret values not printed |
| Wheel | PASS, offline/no-dependency build from external tracked-source copy |
| Compose config / Git whitespace | PASS / PASS |
| Automated boundary scan | 121 Python modules, 56 Core modules; no forbidden imports or syntax errors |

Import scans, matching diagram counts and green conformance tests are supporting evidence, not formal proof of architecture, translation or operational behavior. Source review and M02 demonstrate that distinction.

## 7. Demo Auth

Live fresh Chromium starts `demo-public`. Header order is Monitoring → Configuration → Account; investigation controls are PDF → New Chat. Four Monitoring links remain. No obsolete clearance selector, password input, Basic challenge or gateway token mapping appears. Session cookie metadata is HttpOnly, SameSite=Strict, path `/api/`; no cookie values are retained in the report.

| Identity | Server clearance | Roles | Configuration | Live auth smoke |
| --- | --- | --- | --- | --- |
| demo-public | PUBLIC | none | denied | PASS |
| demo-internal | INTERNAL | none | denied | PASS |
| demo-confidential | CONFIDENTIAL | none | denied | PASS |
| demo-restricted | RESTRICTED | none | denied | PASS |
| demo-admin | PUBLIC | MODEL_ADMIN | allowed | PASS |

Each identity was checked through UI and `/auth/me`, account metadata, quick switching, draft purge, configuration authorization, logout, logged-out reload and login/switch back. Language survives quick switch. After explicit logout and reload of the empty workspace, language resets to EN; see observations. Configuration reads never became assignment writes. Read-only snapshots verify unchanged assignments.

The first custom smoke stopped on an overly literal whitespace assertion before identity measurements. Its completion measured all five identities and ten inventories successfully. A separate initial lifecycle setup incorrectly tried to restore storage across pagehide and mixed a session cookie with bearer-admin reads; those verifier failures remain preserved. The independent completed lifecycle proof uses actual UI state and cookie-free administrative snapshot reads. They are not hidden product failures or retroactive passes.

## 8. Station Visibility

Exact prompt: **`welche stationen kennst du`**. Live seed classifications were verified first.

| Identity | Exact IDs | Factory MCP | Persisted/API/browser answer |
| --- | --- | --- | --- |
| demo-public | S01, S05 | PASS | PASS |
| demo-internal | S01, S02, S03, S05 | PASS | PASS |
| demo-confidential | S01, S02, S03, S04, S05, S06 | PASS | PASS |
| demo-restricted | S01, S02, S03, S04, S05, S06, S07, S08 | PASS | PASS |
| demo-admin | S01, S05 | PASS | PASS |

All answer inventory rows contain each authorized ID exactly once, with no hidden IDs. A second independent ten-inventory control belongs to the current manual runner and also passes. Model omissions/inventions/fallback independence is additionally proven through 20 unit, 30 durable integration and ten DE/EN browser cases. Those full-pipeline tests inspect trusted agent/model-input observations; live checks separately measure the actual MCP, stored result, public API and rendered answer.

## 9. Product Visibility

Exact prompt: **`Welche Produkte kennst du?`**.

| Identity | Count | Exact IDs | Factory / persisted / API / browser |
| --- | ---: | --- | --- |
| demo-public | 2 | P4101, P4102 | PASS |
| demo-internal | 4 | P4101, P4102, P4900, P4901 | PASS |
| demo-confidential | 9 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901 | PASS |
| demo-restricted | 11 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901, P9001, P9002 | PASS |
| demo-admin | 2 | P4101, P4102 | PASS |

No duplicates or unauthorized IDs occur. The answer inventory is independent of the separately bounded 12-reference presentation. Fourteen unit and 30 real-RLS/durable integration cases exercise sparse, invented and fallback model output; ten DE/EN browser cases verify the complete pipeline. Live first measurements and the manual runner's separate critical inventory smoke both pass. Evidence: `factory-live.json`, `factory-inventory-matrix.json`, `live-browser-completion.json` and browser pipeline attachments.

## 10. Security / Regression Status

Statuses describe the named defect's actual boundary; they are not a blanket certification of every neighboring behavior.

| Item | Status | Fresh evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 document/evidence async-I/O regressions; original paths remain off-loop. New provider-cleanup integration defect M02 is separately reported. |
| C02 | CLOSED | 19 bounded RCA provider-worker/deadline/cancellation/drain cases |
| C03 | CLOSED | 25 stabilization cases; actual destination-guard spies, bypass-detection and positive SDK MockTransport controls |
| C04 | CLOSED | 31 transport cases; PUBLIC_CLOUD HTTP denied before credentials/SDK/transport |
| C05 | CLOSED | 14 current documentation/conformance tests, active ADR/refinement review and boundary scan; L01 remains a separate registered-harness problem |
| C06 | CLOSED | 20 unit + 9 PostgreSQL approval-generation cases |
| R01 | CLOSED | 29 raw-provider authorization/binding regressions |
| R02 | CLOSED | 25 unit + 2 real-PostgreSQL owned ticket-I/O cases |
| R03 | CLOSED | 18 unit + 6 PostgreSQL generation/race cases and browser stale-decision coverage |
| R04 | CLOSED | Failed refresh, cross-tab, stale JSON/download/PDF, logout, pagehide/BFCache coverage plus direct live purge |
| R05 | CLOSED | 19 cold-client/cache/close ownership cases; M02 identifies an uncovered asynchronous caller integration |
| R06 | PARTIAL | Current docs and preferred twelve-journey session flow are corrected; older still-registered browser gate remains incompatible, L01 |
| N01 | CLOSED | 21 real-FK/RLS product/hidden-station cases |
| FC01 | CLOSED | 29 real-FK/RLS ticket/hidden-station/authorized consumed-result cases |
| FC02 | CLOSED | 37 emitted-classification/provenance/egress cases |
| FC03 | CLOSED | 14 unit + 30 durable product cases, browser and exact five-user live inventory |
| FC04 | CLOSED | Frontend/browser URL ownership plus direct live unreadability and late-publication proof; original fixture connection flake remains qualified |

Critical direct proofs include PUBLIC parent plus emitted CONFIDENTIAL station → CONFIDENTIAL; RESTRICTED reader plus PUBLIC-only projection → PUBLIC; visible product retained despite hidden event-station relations; visible ticket with hidden mandatory station → neutral unavailable; stale generation A cannot decide B; raw/forged provider authorization and PUBLIC_CLOUD HTTP → zero credential/SDK/transport access. These are executed cases, not copied historical conclusions. `critical-direct-proofs.json` retains exact names/counts.

The live lifecycle proof restored no synthetic API response: a CONFIDENTIAL investigation produced a real 39,946-byte server PDF containing S04. Its captured Object URL was readable before a cross-tab PUBLIC switch and unreadable afterwards. Three genuinely authorized responses were held after fetch and released after downgrade: JSON, document download and PDF all ended with `SecurityContextChangedError`, created no new URL, and the old investigation returned 404. Evidence: `live-lifecycle.json`.

## 11. Real-Model Product Quality

Current preferred gate: **FAIL**, exit 1. All twelve journeys were attempted once. **59 required assertions evaluated; 57 executed; 49 passed; 8 failed; 2 blocked/not run.** The additional ten live inventory controls passed. Optional checks and 24 MANUAL_ONLY transport/protected-execution claims remain separate and do not count as automatic passes.

| Journey | Required passed/total | Raw runner category | Reviewed status / material issue |
| --- | ---: | --- | --- |
| S04 fault investigation | 6/6 | PASS | PASS |
| Station discovery | 4/4 | PASS | PASS; critical inventory smoke passes |
| Product history | 4/4 | PASS | PASS |
| Documentation chain | 8/8 | PASS | PASS |
| Clearance boundary and continuation | 9/9 | PASS | PASS |
| Station discovery DE | 4/4 | PASS | PASS |
| Healthy station investigation DE | 2/3 | BLOCKED_BY_PROVIDER | BLOCKED_BY_PROVIDER; station-reference run unavailable |
| Healthy station investigation EN | 4/4 | PASS | PASS |
| S04 fault investigation EN | 0/4 | HARNESS_ERROR | INFRASTRUCTURE_ERROR; provider unavailable, run timeout, then reload/reference prerequisites fail |
| Product-centric EN | 0/3 | HARNESS_ERROR | BLOCKED_BY_PROVIDER; provider unavailable, then missing prerequisites/reload timeout |
| Clearance boundary EN | 5/6 | BLOCKED_BY_PROVIDER | BLOCKED_BY_PROVIDER; initial station-list run unavailable |
| Restricted information path | 3/4 | MODEL_VARIANCE | INFRASTRUCTURE_ERROR; observed request has persisted agent execution timeout, no terminal UI within measurement |

Four persisted runs have `llm_provider_unavailable / PROVIDER_CONNECTION`; two have `agent_execution_timeout / ORCHESTRATION`. Ollama logs contain six HTTP 500 completions at approximately 45 seconds, including cancelled requests around run timeouts. The adapter limit is 45 seconds; the current API default is 90 seconds. GPU execution was observed. The root cause of every failed generation is not established; CPU fallback, semantic model error or authorization failure must not be invented as explanations.

Raw labels remain unchanged in original artifacts. Reviewed categories use persisted evidence and do not convert failures into passes. No failed journey was retried. The cleanup defect M02 can independently delay event-loop responsiveness; causation for every provider 500 is not claimed. This gate does not certify complete semantic answer quality or physical recovery.

## 12. Runtime / Logs

Logs from all 20 project services and the original local model runtime were captured and searched for the requested error, authorization, RLS, database, session, approval, provider and OTel terms. Keyword hits are not defect counts. Logs were redacted before external evidence storage; no credential values appear here.

| Meaningful entry | Classification | Assessment |
| --- | --- | --- |
| Four API provider-failure events, six local completion HTTP 500s, two persisted run timeouts | PRODUCT_DEFECT / MEDIUM | Current operational quality issue M01; no cloud fallback |
| Initial Factory OTLP DNS/unavailable/deadline before Collector | EXPECTED_STARTUP_WARNING | Later metrics export and scrape UP prove recovery |
| Loki startup empty ring | EXPECTED_STARTUP_WARNING | Final actual readiness 200 |
| Knowledge/API warmup/recreation and disposable cold-start health transition | EXPECTED_STARTUP_WARNING | Later protocol/functional readiness passes, no restarts |
| Cookie-free/logged-out 401; non-admin 403; protected/unknown neutral 404 | EXPECTED_NEGATIVE_TEST | Correct application denials; old harness's wrong expectations remain L01 |
| Verifier's initial nonexistent `station_code` SQL column and incorrect Redis environment-name probe | BENIGN_WARNING / verifier setup | Corrected read-only commands; no source/database repair |
| Idle MCP session expiry | BENIGN_WARNING | Normal bounded session lifetime |
| Grafana optional plugin/alert provisioning directories absent | BENIGN_WARNING | Required health/dashboards unaffected |
| Tempo removed one old incomplete WAL block lacking `meta.json` | OBSERVATION | Current trace search works; full historical trace retention not certified |

ClickHouse's “Logging errors to …” is a log-destination notice, not an error occurrence. No persistent DB/RLS/migration/import failure or container restart loop was found. Expected denials were not counted as security defects.

## 13. Overall Architecture / Security Review

The fresh source review began after the required suites and journeys finished. It then added a narrowly scoped, synthetic review proof to resolve the cleanup concern rather than report a hypothetical race. Import scanning and source tracing cover the API → policy/model resolution → graph → MCP/capability → repository → public projection paths.

**Architecture/orchestration.** Core ports and Domain types remain independent of Infrastructure/provider SDKs. Concrete adapters are wired at outer composition roots. LangGraph is the sole bounded sequential troubleshooting loop. First inventory/reference reads use the normal guard and preserve exact targets; later model decisions cannot replace them. Four-tool and evidence-ledger bounds remain deterministic. The bridge discovers tools and delegates capabilities rather than owning Domain logic. No planner, parallel agent or alternative loop was introduced.

**Auth/RLS/classification.** DemoSessions owns bounded opaque expiring sessions; mutations revoke prior tokens and require same-origin handling. Clearance and administration remain orthogonal. An invalid cookie cannot elevate through a bearer fallback. Direct bearer narrowing remains separate. Transactions set parameterized local clearance; FORCE RLS and non-owning/non-bypass roles are authoritative. Related stations require their own visibility. Product projections omit hidden relations but retain visible products; mandatory hidden ticket relations return neutral unavailability. Labels join actually emitted classified data, not the caller's clearance.

**Models/egress.** MANUAL resolves exactly the persisted stable ID; AUTO applies availability/capability/security hard filters before ranking and repeats final validation. Neither mode reselects after provider failure. Issued request-bound authorization precedes provider serialization/client access. Destination/TLS checks precede secret lookup/SDK creation; PUBLIC_CLOUD requires HTTPS, local destinations are constrained, proxies and redirects disabled. Embeddings use a separate classified local-only boundary and conservative RESTRICTED query context when no authoritative query label exists. Current failures do not weaken these controls.

**HITL/persistence.** API authorization precedes row-locked generation comparison/decision; executing capabilities independently require exact approved run/action/profile/target binding and atomic single use. Ticket retries authorize only the existing bound result. UUID generation identity differs from model correlation. The claim-to-side-effect crash window remains explicitly fail-closed under ADR-011, not crash-proof exactly once. Slow ticket I/O retains ownership/cancellation handling. M02 concerns provider cleanup at the asynchronous service integration, not ticket or approval idempotency.

**Browser/documents.** Generations, AbortController ownership and a shared URL registry protect JSON/binary publication. Purge occurs before session mutations and broadcasts independently of identity-refresh success. Unknown identity stays empty; pagehide/BFCache revalidate. Documents authorize before root-constrained checksum-verified reads; server-sanitized filename/MIME and no-store/nosniff/sandbox headers remain authoritative. Server PDFs use the authorized investigation projection. Live URL/pending-response checks agree with deterministic coverage.

**Runtime/observability/docs.** The clean Knowledge image now imports and performs real offline retrieval. Metadata allowlists and run visibility before diagnostic backends remain intact. Readiness is protocol-aware and supporting backends are operational. Nevertheless readiness is insufficient to certify local model completion quality, and synchronous cancellation cleanup can freeze the single event loop. Current documentation describes the active identity/security model correctly; the older executable E2E command remains misleadingly available as a working gate. No cosmetic or speculative issue was promoted to a finding.

## 14. Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

#### M01 — Current local real-model product gate is materially unreliable

- **Category:** Operational reliability / product-quality acceptance.
- **Affected path:** Local Ollama `local_quality` integration; `infrastructure/llm/openai_compatible.py:57`, `infrastructure/api/app.py:161`, current catalog and `frontend/scripts/run-e2e-journey.mjs` measurement path.
- **Evidence:** Preferred gate passes 7/12 journeys and 49/59 required assertions. Four persisted provider-unavailable runs and two execution timeouts; six local completion HTTP 500s near 45 seconds. All stack services remain healthy; both models report GPU execution. Original artifacts and six failed run IDs are retained in `manual-persisted-results.json` and service/model logs.
- **Expected:** The documented local product journeys complete reliably enough for the current release/milestone gate, or the measured baseline remains explicitly uncertified.
- **Observed:** Supported station/reference/product/fault flows intermittently fail or do not expose a terminal result within the harness window. Dependent assertions then fail or remain unmeasured.
- **Impact:** Full live product-quality certification fails despite green deterministic tests and service readiness. No unauthorized egress or protected action occurred.
- **Reproduction:** Use the recorded immutable images, unchanged assignments and current manual command/run ID. Inspect healthy-DE station reference, S04-EN, product-centric-EN, clearance-EN and restricted follow-up artifacts. This run intentionally did not retry them; no claim of deterministic semantic failure is made.
- **Why tests did/did not catch it:** FAST/INTEGRATION use fake models and validate failure handling, not live provider latency/availability. The manual quality gate correctly prevents PASS. Some aggregate labels obscure the dominant persisted cause.
- **Recommended remediation:** Investigate generation/transport timing using these exact run correlations and qualify a supported local configuration across all journeys. Validate the complete provider/agent/gateway timing chain. Preserve routing, authorization and no-fallback policy; do not simply suppress failed assertions. **Not implemented.**

#### M02 — Provider cleanup blocks the event loop when a run is cancelled

- **Category:** Deterministic asynchronous application availability.
- **Affected path:** `agent/troubleshooting_run_service.py` synchronous `with open_agent(...)` in async run/start/resume; `infrastructure/troubleshooting_run_composition.py` provider context lifetime; `infrastructure/llm/openai_compatible.py:193` synchronous `close()` waiting for active requests.
- **Evidence:** `async-provider-close-proof.py/.json` executes the actual application service, production factory, LangGraph, authorization wrappers and actual OpenAI SDK. Only model resolution, empty MCP tools and HTTP MockTransport are synthetic. No-cancellation control: maximum event-loop heartbeat gap about **31 ms**. Cancel while SDK remains active for 350/750 ms: gaps about **375/765 ms**, with all clients ultimately closed and active count zero.
- **Expected:** Cancellation/deadline cleanup retains request ownership and drains resources without blocking unrelated asynchronous API/auth/readiness work.
- **Observed:** The service exits a synchronous provider context on the event-loop thread. `close()` waits on its condition until the SDK worker finishes, freezing the loop for the remaining request duration.
- **Impact:** One cancelled/timed-out model run can stall unrelated clients, auth reconciliation and health handling. This is a reachable production lifecycle path, independent of model semantics. Security claims and single ownership remain intact.
- **Reproduction:** Run the retained external proof with the configured interpreter. It starts a real graph SDK request through MockTransport, cancels the service task and releases the transport from a timer thread. Delay-scaled heartbeat stalls reproduce without network, database or protected actions.
- **Why tests did/did not catch it:** Provider ownership tests close/drain from controlled threads; RCA worker tests cover their separate execution boundary. Current service tests do not combine asynchronous cancellation, an active real adapter and production context cleanup. The review proof crosses that missing seam.
- **Recommended remediation:** Drain/close off the event loop through an owned asynchronous lifecycle boundary, retaining cancellation safety, no abandoned requests and exactly-once resource closure. Add a deterministic service/HTTP cancellation regression. **Not implemented.**

### LOW

#### L01 — Older registered browser gate is incompatible with current sessions/requests

- **Category:** Verification reliability / current executable documentation.
- **Affected path:** `tests/e2e/investigation-journeys.spec.mjs:38`, `openChat`, `typedStep`; `frontend/playwright.config.mjs`; current browser-journey command documentation.
- **Evidence:** Unchanged `npm run test:e2e -- --retries=0` selects five cases; Journey A fails after 180 seconds, four cases do not run under serial configuration. It records unexpected initial `/auth/me` HTTP 401 and waits for an investigation GET that never arrives. Direct current-policy proof classifies `Untersuche Station S04 genauer.` as RESTRICTED, while the canonical `Untersuche Station S04.` is CONFIDENTIAL (`legacy-prompt-proof.json`). Its CONFIDENTIAL journey therefore uses an inadmissible longer form. The unchanged external copy has 13/13 matching file hashes.
- **Expected:** A still-registered/documented live gate establishes the current demo session, sends admitted requests and applies the correct expected HTTP statuses.
- **Observed:** Unlike the preferred twelve-journey runner, it opens the fresh page before establishing the session and retains obsolete request/wait assumptions.
- **Impact:** The older command cannot provide its advertised five-journey evidence; four declared cases remain untested. The application correctly fails closed. The preferred runner's separate provider failures are not caused by this older harness.
- **Reproduction:** Execute the registered command against the rebuilt healthy demo; retain its original first-run output. No retry was performed.
- **Why tests did/did not catch it:** Current deterministic journey contracts emphasize the preferred registry; generic command-presence/documentation checks and synthetic helper tests do not execute every older specification through real admission/session startup.
- **Recommended remediation:** Align the older executable specification with the supported session and neutral-prompt helpers, or retire its command and documentation explicitly. **Not implemented.**

### Observations

- **O01 — Browser fixture flake:** Original FC04 normal-logout case failed to connect before exercising its assertion; one explicit diagnostic passed. Retained as FLAKY, not PASS.
- **O02 — Failure attribution:** Raw HARNESS_ERROR and MODEL_VARIANCE labels can mask persisted provider/timeout causes. Both raw and reviewed categories are retained; no semantic model variance is asserted without evidence.
- **O03 — Historical telemetry:** Tempo discarded one pre-existing incomplete WAL block; current queries work, complete historical retention is not certified.
- **O04 — Language preference:** Quick switching preserves DE. Explicit logout plus empty-workspace reload resets EN. The current contract permits language to survive but does not promise durable post-logout preferences; no defect is inferred.
- **O05 — Verifier handling:** Early custom-smoke, SQL/Redis/filter and proof-startup setup errors remain preserved. They were corrected only in external verifier code/commands. The first full `docker ps` tool output included expanded Redis start arguments; subsequent snapshots omit commands, stored logs are redacted, and no credential value is reproduced here. No product repair or credential rotation occurred.

## 15. Requirement Confidence Matrix

| Requirement | Evidence | Confidence | Status |
| --- | --- | --- | --- |
| Demo Auth | Session/API tests and five-user live smoke | High | PASS |
| Cross-tab purge | R04/FC04 browser cases plus live three-response/URL proof | High | PASS |
| RLS isolation | FORCE RLS, real application role, missing-clearance controls | High | PASS |
| Related-object visibility | N01 21 / FC01 29 real FK/RLS cases and source | High | PASS |
| Classification propagation | FC02 37, tool/model guard cases | High | PASS |
| Station Discovery | 20 unit / 30 integration, DE/EN browser, exact five-user live matrices | High | PASS |
| Product Discovery | 14 unit / 30 integration, browser and exact live matrices | High | PASS |
| Model egress | R01/C03, request-bound authorizer and 278 embedding cases | High | PASS |
| PUBLIC_CLOUD TLS | 31 transport cases with zero denied boundary counters | High | PASS |
| Approval generation | C06/R03 unit, PostgreSQL row locks/races and browser controls | High | PASS |
| Replay/idempotency | Claim binding/unique request IDs and concurrency tests | High within ADR-011 failure model | PASS |
| Ticket persistence | Real PostgreSQL and owned I/O tests; no live write | High | PASS on synthetic/disposable state |
| Document access | RLS/path/checksum/MIME tests and real KDEP retrieval | High | PASS |
| PDF/blob lifecycle | Browser bytes/filename checks and retained live URL unreadability | High | PASS, fixture flake recorded |
| Async availability under cancellation | Production service/factory/graph/SDK MockTransport proof | High | FAIL, M02 |
| Observability | All backend readiness, live metrics target UP, visibility/allowlist tests | High current operation | PASS; historical WAL limitation |
| Docker/runtime | Seven clean images, 20 ready services, five offline KDEP cases | High | PASS readiness/build; M01 generation reliability separate |
| Live product quality | All twelve current journeys, 59 evaluated required assertions | High measurement / incomplete quality | FAIL, M01 |
| Older browser gate | Exact unmodified command, preserved serial skip evidence | High | FAIL, L01 |

## 16. File Integrity

SHA-256 matches for **all 493 original versioned files** after required tests, after review and after the external deterministic proof. HEAD/branch remain unchanged. Before report creation Git status was clean. Only this new English report and its Git-ignored German companion are added; no existing production, test, configuration, migration, Docker, source or historical review file is changed. Automatic staging of the new report during creation was removed from the index without changing its contents; at handover no files are staged.

No destructive Git command, global Docker cleanup or volume deletion was performed. Temporary PostgreSQL was explicitly dropped and its labelled containers/network removed. Original volume names and the original Ollama identity/start lifetime are preserved. Persistent maintenance tickets remain **100 before / 100 after**. Normal synthetic read investigations, sessions and telemetry were created; these are distinct from protected operational side effects.

Final hash/status/volume/cleanup evidence is external. Generated evaluation artifacts are ignored. The local German report remains outside the index. The original unsuffixed report is part of the matching starting manifest.

## 17. Remaining Risks

M01 prevents a clean current live product-quality certification. M02 can freeze unrelated asynchronous handling during model cancellation cleanup. L01 leaves the older five-case gate unusable. The single browser connection flake limits first-run gate confidence. The Windows symlink case remains skipped, and historical Tempo trace completeness is uncertain after the discarded block. Physical execution and crash-proof exactly-once recovery were not claimed or tested; existing ADR-011 limits remain explicit. No speculative future-scale or cosmetic risks are added.

## 18. Final Conclusion

**Can this implementation currently be considered to reliably satisfy its documented and promised functional, authorization, security and operational requirements? NO.**

The measured authorization, RLS, classification, egress, approval, discovery and protected-browser-state guarantees hold. Clean build and 20-service readiness pass. Full operational certification fails because of demonstrated local product-gate unreliability and synchronous provider cleanup blocking the event loop; the older gate adds a limited verification defect. Final result: **FAIL — 2 MEDIUM, 1 LOW; no HIGH/CRITICAL security finding.**

External model calls: **0**. Real protected side effects/hardware operations: **0**. Unexpected existing repository changes: **0**. Commits/pushes/external deployments: **0**. The healthy rebuilt local stack remains running. No finding was repaired; this protocol completes the requested single run.
