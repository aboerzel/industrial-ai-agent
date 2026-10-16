# Targeted Remediation — 2026-10-15

## Outcome and scope

R06 documentation: **FIXED**.
Station discovery completeness: **FIXED**.
Real-Model E2E session/route harness defects: **FIXED within the requested acceptance contract**.

The final local run attempted all 12 journeys and evaluated all 59 REQUIRED assertions.
Its product-quality gate remains **FAIL**: 4 PASS journeys, 5 PRODUCT_DEFECT and
3 MODEL_VARIANCE. HARNESS_ERROR, SECURITY_DEFECT, provider blocks and infrastructure
errors: 0. Five dependent assertions lack model evidence; they are not certified as
executed or passed.

No production authentication, RLS, egress, approval, model configuration, migrations,
Docker definitions or frontend application code changed. The sole production source
change is deterministic station-inventory presentation in the existing agent.
No independent architecture/security review was started.

## Baseline and evidence

Repository: D:/Freelance/industrial-ai-agent.
Branch: main.
HEAD: 07c55ee184545906de661d8a83fe68e7790df634.
Configured Python: .venv/Scripts/python.exe, Python 3.12.10.

The pre-existing staged docs/reviews/final-clean-verification-2026-10-15.md was preserved.
All 16 pre-existing review/certification reports match their initial SHA-256 hashes.
Working-tree changes below are intentional remediation, not a read-only certification.

Local evidence directory:
C:/Users/Andreas/AppData/Local/Temp/industrial-remediation-20261015-210812.

Original certification artifacts remain unchanged under
evals/results/browser-e2e/final-clean-20261015-195102/.
The representative old-harness reproductions use distinct remediation-original and
remediation-diagnostic run IDs. Their sanitized traces and first failures were preserved.

Final measured run:
evals/results/browser-e2e/remediation-local-certified-20261015-210812/.
preflight.json, journey-*.json and summary.json retain source fingerprints, assertion
plans, HTTP trajectories, tool trajectories, classifications and session setup.
The aggregate accepted the current provenance; preflight is PASS.

## Slice 1 — R06 documentation

Outdated Basic Auth current claims: **NO**.
Outdated clearance-selector current claims: **NO**.
Outdated gateway-token-mapping current claims: **NO**.
Documentation conformance: **14 passed**.

Reproduced current drift in the scenario catalog and two derived guides. Updated
use-cases-and-scenarios, persistent-factory-data and capabilities-and-industrial-value,
plus the current ADR-013 clarification. The removed gateway description is explicitly
historical/superseded. README, overview, current session implementation, frontend auth
and Nginx were compared to the documentation. Historical reviews were not edited.

Current contract: Browser -> Demo Auth endpoints -> server-managed Demo Session ->
HttpOnly/SameSite=Strict cookie scoped to /api/ -> Nginx proxy -> server-side session
resolution -> server-derived SecurityContext. Nginx strips browser Authorization.
Quick switch intentionally selects any configured demo user, including admin.

| Identity | Clearance | MODEL_ADMIN |
| --- | --- | --- |
| demo-public | PUBLIC | No |
| demo-internal | INTERNAL | No |
| demo-confidential | CONFIDENTIAL | No |
| demo-restricted | RESTRICTED | No |
| demo-admin | PUBLIC | Yes |

Small conformance checks compare the documented identity table with the canonical TOML
and verify protocol/currentness markers rather than complete prose snapshots.
All eight changed current English documents have synchronized ignored German companions.
ADR-004 and overview diagrams describe deterministic discovery presentation consistently.

## Slice 2 — Station discovery

Original incomplete Station answer reproduced: **YES**.
FIRST_LOSSY_BOUNDARY: **model output / free-form final narrative**.
Authoritative Station result source: **the current guarded list_stations observation,
validated as StationListResult, originating in PostgreSQL/RLS and Factory MCP**.
Model prose required for completeness: **NO**.
Station Discovery complete: **YES**.
Unauthorized Station leaked: **NO**.
German: **PASS**. English: **PASS**.

Before the production change, 30 deterministic real-PostgreSQL cases failed. Their
trace proved complete SQL/RLS, repository, Factory MCP, raw agent observation,
structured references and model input. Sparse model output first lost inventory IDs;
the sparse answer then survived persistence/API. These first failures remain in
station-before.log/xml and station-first-lossy-boundary.json.

After the change, station-after.xml records each identity/language/model-mode pipeline:
PostgreSQL/RLS -> repository -> MCP -> raw agent tool result -> trusted final result ->
references -> model input -> model output -> durable run -> API. Real Chromium fixtures
attach the browser stage. Sparse, invented and invalid-section/fallback model output
cannot control the inventory. No Station IDs are parsed out of model prose.

The existing allowlisted generic-discovery intent is unchanged. Mixed sensitive
identifiers and arbitrary text remain conservative. A current executed tool-call binding
is required. Authorized IDs/names/status come from typed data; missing status renders
unknown instead of dropping the station. Deduplication preserves inventory order.
The reference cap remains 12 and separate from inventory completeness. The existing
8,000-character answer bound remains explicit for exceptionally large inventories.

Actual persistent PostgreSQL was additionally queried in read-only transactions as
factory_app, with no superuser/BYPASSRLS privilege, at each server-defined clearance.
live-rls-inventories-final.txt confirms the current seed. The final existing
station-discovery journey then verified the exact German prompts for all five identities
against the rebuilt stack, including persisted answers and actual browser answer DOM.

| Identity | Expected IDs | Actual answer / persisted / browser IDs |
| --- | --- | --- |
| demo-public | S01 S05 | S01 S05 |
| demo-internal | S01 S02 S03 S05 | S01 S02 S03 S05 |
| demo-confidential | S01 S02 S03 S04 S05 S06 | S01 S02 S03 S04 S05 S06 |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | S01 S02 S03 S04 S05 S06 S07 S08 |
| demo-admin | S01 S05 | S01 S05 |

SD matrix: 20 focused unit cases, 30 real-RLS/durable-API cases, 10 station Chromium
cases across all identities and DE/EN, existing mixed-sensitive discovery guards,
and unchanged FC03 product tests all pass. Combined discovery/RLS focus: 190 passed.
Station/product Chromium focus: 20 passed. No hidden IDs, names, states, classifications
or aggregate hidden counts are used in station presentation.

### FC03 live product control

Exact prompt: Welche Produkte kennst du?
All rows match real RLS, answer, persisted answer and browser; no duplicates or hidden IDs.

| Identity | Count | Exact IDs |
| --- | ---: | --- |
| demo-public | 2 | P4101 P4102 |
| demo-internal | 4 | P4101 P4102 P4900 P4901 |
| demo-confidential | 9 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 |
| demo-restricted | 11 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 P9001 P9002 |
| demo-admin | 2 | P4101 P4102 |

The ten critical live station/product controls are part of the existing station-discovery
journey, not a separate model runner. All ten passed in the final measured run.

## Slice 3 — Real-Model E2E harness

Original 401 reproduced: **YES**.
Root cause: the strict browser response guard latched the frontend's normal initial
cookie-free GET /api/v1/auth/me 401, even after the app established a valid session.
Fresh anonymous control still returns 401, body: {"detail":"Demo session required."}.
No credential or cookie value was recorded.

Original 404 reproduced: **YES**.
Root cause of stale harness requests: unsupported typed prose such as
"Untersuche Station S04 genauer." remains conservatively RESTRICTED. A lower-clearance
session correctly receives requested_data_unavailable before any run is allocated.
The route is current; this was not a stale route or failed login.

Additional 404 classes are kept separate:

- expected denial of an explicitly protected request, with exact neutral code and no
  fabricated run/investigation: AUTHORIZATION_NEUTRAL_DENIAL / EXPECTED_NON_DISCLOSURE;
- saved known investigation/PDF after downgrade: expected neutral non-disclosure;
- real UI reference action generating unsupported prose: PRODUCT_DEFECT, while the
  server's conservative neutral-denial security behavior remains correct;
- arbitrary missing-resource 404: cannot satisfy an expected neutral-denial assertion.

Product auth changed: **NO**.
Before: implicit frontend bootstrap plus an incompatible all-success response guard.
After: supported same-origin POST /api/v1/auth/bootstrap through Playwright's shared
cookie jar, verified demo-public, then visible current account quick switch.
Uses server-managed Demo Session: **YES**.
Uses browser-controlled clearance/roles: **NO**.
Browser Authorization headers in final traces: **0**.
Unexpected session HTTP 401: **0**. Redirects: **0**.

The existing separate CLI model-catalog/MCP readiness checks retain their supported
read-only service authentication; no service credential is injected into a browser.
All browser runs, saved resources, documents and PDFs use the real Demo Session cookie.

Typed journey prompts were aligned to existing complete neutral forms and covered by
a deterministic registry/policy contract test. The 12-journey/59-REQUIRED registry is
retained. No product input policy was broadened. All planned checks are attempted;
failed or blocked checks retain their own category and cannot poison unrelated checks.
A missing identity-transition prerequisite remains failed/blocked while the supported
real session is set for subsequent checks. Recovery is recorded separately.
Pre-transition content uses an evidence-bound rendered marker, avoiding false failures
from comparing raw Markdown with DOM text. Actual PDF/document bytes and filenames,
saved-ID authorization and strict unexpected-status checks remain enforced.
The focused browser harness contract suite has 18 passing cases.

Model/profile/zone for every journey: local_quality, MANUAL, Ollama qwen3.5:9b,
Local Qwen 3.5 9B, LOCAL. Assignment snapshots are checked before requests and afterward.
No protected action was approved or resumed.

| Journey | Initial clearance | Category | REQUIRED evaluated | Passed | Failed | Blocked |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| s04-investigation | CONFIDENTIAL | PRODUCT_DEFECT | 6/6 | 5 | 1 | 0 |
| station-discovery | INTERNAL | PRODUCT_DEFECT | 4/4 | 2 | 2 | 0 |
| product-history | PUBLIC | MODEL_VARIANCE | 4/4 | 3 | 0 | 1 |
| documentation | CONFIDENTIAL | MODEL_VARIANCE | 8/8 | 4 | 1 | 3 |
| clearance-boundary | CONFIDENTIAL | PASS | 9/9 | 9 | 0 | 0 |
| station-discovery-de | RESTRICTED | PASS | 4/4 | 4 | 0 | 0 |
| healthy-station-de | PUBLIC | MODEL_VARIANCE | 3/3 | 2 | 0 | 1 |
| healthy-station-en | PUBLIC | PRODUCT_DEFECT | 4/4 | 3 | 1 | 0 |
| s04-investigation-en | CONFIDENTIAL | PRODUCT_DEFECT | 4/4 | 3 | 1 | 0 |
| product-centric-en | INTERNAL | PRODUCT_DEFECT | 3/3 | 2 | 1 | 0 |
| clearance-boundary-en | INTERNAL | PASS | 6/6 | 6 | 0 | 0 |
| restricted-boundary | RESTRICTED | PASS | 4/4 | 4 | 0 | 0 |

Real-model journeys attempted through current authenticated contract: **12/12**.
PASS: **4**. PRODUCT_DEFECT: **5**. MODEL_VARIANCE: **3**.
HARNESS_ERROR: **0**. SECURITY_DEFECT: **0**. BLOCKED_BY_PROVIDER: **0**.
INFRASTRUCTURE_ERROR: **0**.
BLOCKED journey status: **2**, both included in MODEL_VARIANCE above.
REQUIRED assertions evaluated: **59/59**; executed **54/59**;
passed **47**, failed **7**, blocked on missing prerequisites **5**.
The legacy aggregate completed_journeys counter excludes the two BLOCKED outcomes and
therefore reads 10. All twelve have artifacts and completed assertion-evaluation loops.
Aggregate execution_status is BLOCKED and product_quality_gate is FAIL; neither is PASS.

Each journey JSON records method/path, expected session mechanism, cookie/header presence,
status/code, redirects, current identities, tool trajectory, terminal result and
classification. An unsuccessful run can terminate through HTTP 200 with a normalized
product/tool error; it is not mislabeled an HTTP/session harness failure.

### Preserved iterations and remaining findings

The first post-fix complete run remediation-local-20261015-210812 is retained. It exposed
the identity-prerequisite and Markdown-comparison harness defects corrected above.
The intermediate remediation-local-final-20261015-210812 run was explicitly interrupted
after those findings, with only its identified runner/browser process tree terminated.
second-iteration-interruption.json records this; it is not a passing measurement.
The final certified-named run ID identifies a measurement, not an all-green certification.
No rerun result erases a prior failure or turns a flaky first failure into a clean PASS.

Remaining findings, deliberately not repaired under this task:

1. Existing real UI reference actions can generate prompts outside the current narrow
   neutral forms. Five journeys retain PRODUCT_DEFECT; conservative server 404 behavior
   was preserved. Discovery inventory controls themselves all pass.
2. Product-history and healthy-station-de lack an expected model-selected tool call.
3. Documentation initially returns tool_execution_failed with no useful document
   evidence; dependent document/protected-pre-state checks remain blocked. The harness
   labels this MODEL_VARIANCE/evidence failure; the underlying tool-error cause is not
   proven by this remediation and is retained for follow-up, not attributed to auth.
   Subsequent actual session changes, neutral denial and independent recovery checks run.

## Gates

| Gate | Command / scope | Final result |
| --- | --- | --- |
| Full backend | .venv/Scripts/python.exe -m pytest tests, disposable PostgreSQL | 1963 passed, 0 failed, 1 skipped |
| Integration | scripts/run-quality-gate.ps1 INTEGRATION, disposable PostgreSQL | 278 passed, 0 failed, 0 skipped |
| FAST | scripts/run-quality-gate.ps1 FAST | PASS: 1670 unit passed, 1 skipped; 294 frontend passed; Ruff, format, secret scan |
| Full frontend | npm run test, fully executed by FAST | 294 passed, 0 failed/skipped |
| Safe browser | full registered playwright.fixtures.config.mjs, no retries | 105 passed, 0 failed/skipped/flaky |
| Documentation conformance | tests/unit/test_documentation_conformance.py | 14 passed |
| Ruff | ruff check src tests scripts | PASS |
| Format | ruff format --check src tests scripts | PASS, 257 files |
| JS syntax | node --check frontend/test JS modules | PASS |
| Secret scan | scripts/check-demo-secrets.py | PASS |
| Local links / ADR references | local documentation audit | PASS |
| Changed EN/DE documents / diagrams | synchronized local translations | PASS |
| Compose validation | docker compose config --quiet | PASS |
| Whitespace | git diff --check | PASS |

The one backend/FAST skip is Windows symlink creation unavailable, in
test_document_content_storage; it is not reported as PASS.

Earlier validation failures remain in the evidence directory: the station reproduction,
one old incomplete fake DTO adjusted to the real list_stations contract, a literal
synthetic password rejected by the existing secret scanner, and first browser failures
from an obsolete comma-prose assertion plus concurrent fixture writes in the same
disposable database. The browser now has its own seeded database and compares exact IDs.
Scanner rules and production contracts were not weakened. Final complete gates above
use the corrected tests/harness and isolated databases.

## Neighbor regressions

| Item | Status | Executed regression evidence |
| --- | --- | --- |
| C01 | CLOSED | Sync evidence/document I/O off loop; full backend |
| C02 | CLOSED | Capacity, deadlines, cancellation, retained worker/drain ownership |
| C03 | CLOSED | Real endpoint guard spies and positive/negative controls |
| C04 | CLOSED | PUBLIC_CLOUD TLS enforcement before credentials/SDK |
| C05 | CLOSED | ADR/index and current architecture conformance |
| C06 | CLOSED | Approval identity/generation, replay, concurrency, exactly-once; real PostgreSQL |
| R01 | CLOSED | Raw provider authorization and final egress fail closed |
| R02 | CLOSED | Slow ticket write does not block event loop; real PostgreSQL |
| R03 | CLOSED | Stale approval/reject generation; backend/PostgreSQL/Chromium |
| R04 | CLOSED | Cross-tab, failed auth/me, stale responses, logout/BFCache/pagehide |
| R05 | CLOSED | Concurrent cold client initialization and lifecycle ownership |
| R06 | CLOSED | Current cookie/session docs, identities, browser/harness contract |
| N01 | CLOSED | Real-RLS hidden Station relation retains visible product safely |
| FC01 | CLOSED | Real-RLS hidden Ticket station gives neutral unavailable result |
| FC02 | CLOSED | Machine/Ticket/Document emitted classification joins; model boundary |
| FC03 | CLOSED | Complete product discovery despite model omission/invention; 5/5 live |
| FC04 | CLOSED | Real Chromium captured Blob unreadability after purge; cross-tab, failed refresh, BFCache/pagehide/late PDF and positive controls |

## Docker, safety and file scope

docker compose build agent-api: **PASS**.
docker compose up -d --no-deps --no-build --wait --wait-timeout 180 agent-api: **PASS**.
Only the affected application image was rebuilt. Frontend production assets and other
service images did not change. All **20/20 services are healthy**, **0 restarts**;
the rebuilt API's real /ready endpoint returns HTTP 200. The healthy stack remains running.

External provider calls: **0**.
Real protected side effects: **0**. Real hardware actions: **0**.
Persistent maintenance tickets: **100 before / 100 after**.
Local read investigations, demo sessions and ordinary telemetry were created.
All disposable databases and both labeled verification containers were removed.
No persistent or unrelated Docker volume was deleted; cleanup volume comparisons are empty.

Files changed: 27 repository files including this new report, plus nine ignored local
German documents. The 26 implementation/documentation/test files are:

- src/industrial_ai_agent/agent/langgraph_troubleshooting_agent.py;
- docs/architecture/capabilities-and-industrial-value.md, overview.md;
- docs/decisions/ADR-004-agent-orchestration-strategy.md,
  ADR-013-fastapi-application-boundary.md;
- docs/demo/demo-user-visibility.md, use-cases-and-scenarios.md;
- docs/learning/browser-e2e-journeys.md, persistent-factory-data.md;
- frontend/scripts/browser-journey-checks.mjs, e2e-http.mjs,
  journey-assertions.mjs, journey-execution.mjs, journey-http-trace.mjs,
  run-e2e-journey.mjs;
- tests/e2e/fixtures/demo-auth.spec.mjs, fc03-discovery.spec.mjs,
  journey-evidence.spec.mjs;
- tests/frontend/journey-assertions.test.mjs, journey-session-contract.test.mjs;
- tests/integration/fc03_discovery_support.py, test_station_discovery_completeness.py;
- tests/unit/test_documentation_conformance.py, test_langgraph_evidence_requirements.py,
  test_real_model_journey_contract.py, test_station_discovery_inventory.py.

Historical review/certification reports modified: **NO**.
Unexpected production-auth/configuration/migration/Docker file changes: **0**.
Commits: **0**. Pushes: **0**. External deployments: **0**.

Ready to commit: **YES for this targeted remediation, with the recorded remaining
product/model findings**. The live product-quality gate remains FAIL; this report does
not certify all twelve model journeys as passing. No commit was made.
