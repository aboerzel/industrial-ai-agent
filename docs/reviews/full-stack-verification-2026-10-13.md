# Full Stack Verification

## Stable baseline

Repository: `D:/Freelance/industrial-ai-agent`. Branch: `main`. HEAD: `7bd09dc73204774e885b5dca9d589819a2ced0b1`. Working tree: DIRTY, 18 tracked modifications + five new regression files + four untracked canonical reports; no staged files. Initial user work was the three earlier local reports, archived without deletion. Ignored German translations and two local E2E credential-value changes are explicit. Runtime versions: Python 3.12.10, Node 24.19.0, npm 11.17.0, Docker 29.8.2, Compose v5.6.0. Environment templates have 46 supported keys in matching order, no duplicates; no values exposed.

Final stable iteration only: iteration 3. Earlier failures, fixes, classifications and restarts are retained in [the stabilization protocol](full-stack-stabilization-2026-10-13.md). Evidence directory: `evals/results/stabilization-2026-10-13/iteration-03/`. The frozen source/test hash manifest is `source-manifest.json`.

## Clean rebuild

`docker compose down` removed only current project containers/network; no `-v`, prune, image deletion or destructive Git operation. Eleven declared active volumes plus one older project-labelled volume retained. Unrelated Ollama untouched. `docker compose build --no-cache --progress plain` succeeded for every project-owned image. Application source was copied afresh; existing third-party base images were retained (`--pull never` on startup). Image IDs are in `runtime-inspect.json` / `phase-c/image-evidence.json`.

| Image | Result | Warnings |
| --- | --- | --- |
| agent-api / industrial-ai-agent-agent-api:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| factory-mcp / industrial-ai-agent-factory-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| hardware-mcp / industrial-ai-agent-hardware-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| knowledge-mcp / industrial-ai-agent-knowledge-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| observability-mcp / industrial-ai-agent-observability-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| rca-mcp / industrial-ai-agent-rca-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |
| runtime-mcp / industrial-ai-agent-runtime-mcp:latest | PASS | pip installation-as-root warning; runtime app user; dependency ranges/base tags remain mutable |

Frontend uses supported `nginx:1.29-alpine` with read-only static mounts; it has no project image to rebuild. PostgreSQL, telemetry and Langfuse components are third-party images. Builds downloaded public dependencies/base metadata; cold Knowledge startup downloaded OCR/reranker artifacts. No repository prompts or classified data were sent to an inference service; external LLM calls were zero. These downloads mean this is not an offline stack certification. No deprecated Compose feature caused failure.

## Stack health

`docker compose up -d --no-build --pull never --wait --wait-timeout 600`, followed by actual HTTP readiness polling and authenticated MCP discovery. Database ready, existing application migration at revision 0024; empty test databases separately exercised all 24 upgrades and upgrade regressions. No restart loop.

| Service | Running | Healthy | Restarts | Notes |
| --- | --- | --- | --- | --- |
| agent-api | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| factory-db | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| factory-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| frontend | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| grafana | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| hardware-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| knowledge-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-clickhouse | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-minio | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-postgres | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-redis | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-web | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| langfuse-worker | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| loki | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| observability-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| otel-collector | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| prometheus | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| rca-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| runtime-mcp | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |
| tempo | YES | YES | 0 | Protocol/HTTP readiness where applicable; config-only checks qualified below |

API `/health` and `/ready`, frontend `/health` and authenticated root, Grafana `/api/health`, Langfuse public health, Tempo/Loki `/ready`, Prometheus `/-/ready` and local Ollama `/api/tags` succeeded. All six MCP services initialized and advertised required tools. Loki required nine readiness polls before smoke. Collector's component check and Loki's config check alone do not certify readiness. Langfuse stores/worker use their own supported healthchecks; no external model inference was started.

Complete per-service build/image, dependency, loopback port, healthcheck, mounts and environment-key inventory: `compose-inventory.json`. Frontend 8080, API 8000, MCP 8001-8006, DB 5432, Grafana 3000, Langfuse 3001, Tempo 3200, Loki 3100, Prometheus 9090 and Minio 9092 are loopback-bound where exposed. OTLP/service traffic remains internal. Host Ollama 11434 is separate local infrastructure. Knowledge artifact loading can contact Hugging Face/ModelScope; telemetry adapters and cloud model adapters have configured network potential, which was not exercised for inference.

## Tests

| Gate | Passed | Failed | Skipped | Result |
| --- | --- | --- | --- | --- |
| FAST backend unit | 1321 | 0 | 1 | PASS |
| Complete Python suite | 1443 | 0 | 1 | PASS |
| INTEGRATION documented script | 107 | 0 | 0 | PASS |
| Golden deterministic evals (included above) | 15 | 0 | 0 | PASS |
| Frontend complete unit/runner suite | 231 | 0 | 0 | PASS |
| Chromium local HTTP fixtures | 15 | 0 | 0 | PASS |
| Full-stack synthetic/read-only smoke | 29 | 0 | 0 | PASS |
| Factory / Knowledge HTTP smoke | 2 | 0 | 0 | PASS |
| Ruff / format | 2 gates | 0 | 0 | PASS (225 files) |
| JavaScript syntax | 32 files | 0 | 0 | PASS |
| Wheel / pip check / local links / git diff --check | 4 gates | 0 | 0 | PASS |
| Real-model E2E | 0 | 0 | NOT_RUN | NOT_RUN |
| Frontend build/lint/typecheck, Mermaid validation | — | — | NOT_CONFIGURED | NOT_CONFIGURED |

The sole skip is Windows symlink creation unavailable. Python totals include 1,321 unit passes, 107 integration passes and 15 deterministic eval passes. Fresh and upgrade migrations, RLS, ownership/visibility contracts, MCP, permissions, HITL, replay/concurrency, model/embedding egress, RCA and observability are included. INTEGRATION was explicitly executed with an admin URL; its documented skip-to-zero path was not represented as PASS. Isolated database names were verified before terminating their connections and removing only those synthetic databases.

Authoritative discovery covered AGENTS, README, pyproject, package scripts, Compose/Dockerfiles, quality/E2E docs and test configuration. No CI workflow or Makefile added another gate. Aggregate coverage was checked against actual test subtrees; gates were not inferred solely from documentation.

| Gate / command | Scope | Dependencies / external potential | Safe | Executed |
| --- | --- | --- | --- | --- |
| scripts/run-quality-gate.ps1 FAST | Unit, frontend, Ruff, format | Configured venv, local npm; no inference | YES | YES |
| Configured Python -m pytest tests -ra | All unit/integration/eval subtrees | Separate migrated PostgreSQL database; fakes/offline models | YES | YES |
| scripts/run-quality-gate.ps1 INTEGRATION | 107 real-boundary cases | Separate PostgreSQL DB, temporary gateway fixtures | YES | YES, not skipped for missing admin URL |
| npm --prefix frontend run test:e2e:fixtures | Production UI and synthetic loopback HTTP | Installed Chromium/Playwright, no inference | YES | YES |
| node --check | 32 JS/MJS files including new fixtures | Local Node only | YES | YES |
| Python -m pip wheel --no-deps --no-build-isolation --no-index | Python package | Installed build tools only | YES | YES |
| Python -m pip check | Local dependencies | Installed metadata only | YES | YES |
| Documentation/conformance tests; local_links.ps1 | Current contracts, 56 links in 53 tracked docs | Local files; no external URL/anchor validation | YES | YES |
| git diff --check | Tracked changes | Local Git | YES | YES |
| smoke_test_factory_mcp.py --transport http | DB-backed P4711/S04 reads | Rebuilt Factory HTTP MCP | YES | YES |
| smoke_test_knowledge_mcp.py --transport http | Retrieval read | Local Ollama embeddings/reranker; no cloud inference | YES | YES |
| npm run test:e2e / e2e:manual / live model evals | Live model/browser release tier | Would perform inference, configuration interactions, possible action journeys | NO for this run | NOT_RUN |
| LangGraph/API/persistent-HITL live smoke helpers | Real orchestration/action flows | Real model or protected runtime writes | NO for this run | Safely skipped; fake/disposable integration equivalents executed |
| vendor:sync | Asset-generation utility | Writes vendored runtime files | NO during verification | Not a gate; static asset equivalence tests executed |
| Frontend production build/lint/typecheck; Mermaid parser | No such configured command | Static Nginx modules; no parser installed | N/A | NOT_CONFIGURED |

Safe E2E includes runner/auth/status/required-assertion/aggregate/resume regressions, real Chromium fixture DOM, persisted synthetic evidence, actual PDF/download checks and context transitions. Manual gateway identity switching, independent live MCP browser assertions and real protected HITL are NOT_RUN. REAL_MODEL_E2E = NOT_RUN: the local model is present, but the supported release journeys do not meet the guaranteed side-effect-free scope for this unattended task. No NOT_RUN result is labelled PASS.

Build/quality: offline wheel built, local dependency metadata consistent, static assets served, Ruff/format pass, 32 JS modules parse. No frontend compilation, configured lint/typecheck or Mermaid validation tooling exists. Existing links: 56 targets in 53 tracked canonical documents; anchors and external URLs not checked. Final generated-report links/translations are separately checked after writing. No Mermaid contract needed modification: stabilization restored existing boundaries/budget and did not replace architecture.

## Security regression evidence

The complete original Findings 1-12 text is unavailable. Available commits establish the authentication, egress, HITL, UI, E2E/docs/RCA repairs; rows 2-8 remain a provisional crosswalk. FULL means the available concrete property was exercised, never per-user tenancy or undocumented original coverage. No observed CRITICAL/HIGH/MEDIUM regression in those exercised historical boundaries. Exact closure of all twelve cannot honestly be certified.

| Finding | Evidence | Coverage | Result |
| --- | --- | --- | --- |
| 1 | Gateway: 19 isolated Nginx/API tests; anonymous denial, authenticated Basic 200, admin separation; original full statement absent | PARTIAL | PASS for exercised property |
| 2 | Server-owned API/MCP principals and clearance ceilings; API/gateway auth tests; original ID mapping unavailable | PARTIAL | PASS for exercised property |
| 3 | PostgreSQL FORCE RLS; 14 factory and 14 runtime integration cases; hidden/unknown append denial; shared demo, no tenant-ownership certification | PARTIAL | PASS for exercised property |
| 4 | Monotonic request/evidence classification and model-egress tests; original ID mapping unavailable | PARTIAL | PASS for exercised property |
| 5 | Direct protected MCP permission/profile/approval denials, action/run/target binding, public read-only surface | PARTIAL | PASS for exercised property |
| 6 | Persisted single-use approval, replay and concurrent exactly-once tests; cross-run ticket regression | PARTIAL | PASS for exercised property |
| 7 | 278 embedding-egress cases plus model-egress cases; local retrieval smoke; three endpoint regression cases qualified by C03 | PARTIAL | PASS for exercised property |
| 8 | Frontend generation purge, ignored abort/stale responses, Blob revocation, downgrade/upgrade and model-dialog tests | PARTIAL | PASS for exercised property |
| 9 | Authenticated actual CLI fixtures and unexpected HTTP-status regressions; live safe denial/read smoke | FULL | PASS for exercised property |
| 10 | Required assertion/step binding, missing IDs/tools/security evidence, wrong PDF, NOT_RUN rejection; actual CLI aggregate/resume provenance | FULL | PASS for exercised property |
| 11 | Documentation conformance, 56 existing local links, ADR status/implementation comparison; C05 index drift | PARTIAL | PASS for exercised property |
| 12 | Deterministic RCA remains available on optional timeout/provider/schema/semantic/finish-reason failure; complete-suite diagnostic logging passes | FULL | PASS for exercised property |

## Runtime logs

All 20 service logs collected and scanned for ERROR/CRITICAL, tracebacks/exceptions, fatal/panic, restart, connection refusal, authorization, database/migration failures, timeout, malformed/provider failures, retries and deprecations. Full sanitized logs/matches are retained; no errors were suppressed.

Unexpected persistent errors: none after readiness. Startup Factory/RCA OTLP DNS/deadline/export errors precede Collector availability and stop after startup (LOW). Grafana optional provisioning-directory warnings are LOW. Loki empty-ring/start delay recovers; Tempo repaired an old incomplete WAL entry in its retained volume (historical data-gap risk, no manual deletion). Pip-as-root is build-only; application containers run as app. AnyIO/OTel deprecations and Node color warnings are benign warnings. Knowledge cold artifact downloads are external dependency traffic, not inference; a prior iteration HEAD 429 recovered.

EXPECTED_NEGATIVE_TEST: unauthenticated/unauthorized 401/403 and deliberate hidden/missing 404; PostgreSQL invalid run-profile/approval-action and hidden-sequence unique violations from disposable test databases. They match passing rejection assertions. No application migration failure, ongoing provider error or restart loop was found. Final iteration tests had no failures or flakiness retries. Earlier deterministic/product/test/configuration failures and the single startup control check remain in the stabilization report.

## Remaining known LOW issues

Four baseline groups: raw API query logging; config/component-only Loki/Collector healthchecks; startup telemetry ordering; optional Grafana provisioning directories. They remain documented. Dependency pinning, artifact-download availability and historical trace retention are residual risks.

## Known product issues

`frontend/js/api.js` document download still uses `document.filename` rather than `responseDocument.filename`. The existing fixture explicitly detects the product defect and passes its negative assertion. It did not fail an authoritative stabilization gate, so the instructed known baseline issue remains unchanged and is not a new independent finding.

## Overall

PASS_WITH_LOW_ISSUES. Ready for independent review: YES, at the frozen entry to Phase C. Phase-C findings, including C03's newly discovered vacuous tests, are separate assessment results and were not fixed or hidden. This is a verified local demo baseline, not production/real-model certification.

Final report checks: four ignored German counterparts, 16 valid local report links, zero secret matches, zero source/test deviations since Phase-C freeze and no staged files. Generated checker/proof fixture failures were diagnosed and preserved without product changes. C06 is a separate Phase-C intra-run approval-generation finding and was not fixed; stabilization counts refer to the reproduced Phase-A/B defect scopes.
