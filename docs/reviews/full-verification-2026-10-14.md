# Full Verification — 2026-10-14

## Baseline

Repository `D:/Freelance/industrial-ai-agent`; branch `main`; HEAD
`67c35b91e853cbd334c9be4c7c1dbe480d78ca1a`. Entry working tree clean, zero staged
files. Existing tracked source, tests, configuration, migrations and documentation
remain byte-identical. Only the four requested canonical reports and ignored German
translations/evidence are added. Python 3.12.10 (PyCharm configured venv), Node 24.19.0,
npm 11.17.0, Docker 29.8.2, Compose v5.6.0. Initial manifests include image/container
IDs and all running resources; evidence root `evals/results/stabilization-2026-10-14/` is Git-ignored.

## Stabilization iterations

1 baseline stabilization iteration, no product repair iterations; one separate final
clean cycle (Phase C). Both cycles execute all safe gates. No authoritative test failed,
no flaky rerun, no weakened assertions. A Windows symlink permission skip is explicit.

## Repairs performed

| ID | Severity | Root cause | Fix | Regression | Final status |
| --- | --- | --- | --- | --- | --- |
| — | — | No reproduced blocking defect | No source change required | Existing full suites | PASS |

## Unresolved defects

| ID | Attempts | Impact | Reason unresolved |
| --- | --- | --- | --- |
| — | 0 | None | No UNRESOLVED_AFTER_3_ATTEMPTS blocker |

See [repair log](stabilization-repair-log-2026-10-14.md) for helper corrections and first
startup observations, which are not product repair attempts.

## Docker rebuild

| Service | Image | Rebuild | Result |
| --- | --- | --- | --- |
| agent-api | industrial-ai-agent-agent-api:latest | YES, no-cache | PASS |
| factory-mcp | industrial-ai-agent-factory-mcp:latest | YES, no-cache | PASS |
| knowledge-mcp | industrial-ai-agent-knowledge-mcp:latest | YES, no-cache | PASS |
| hardware-mcp | industrial-ai-agent-hardware-mcp:latest | YES, no-cache | PASS |
| runtime-mcp | industrial-ai-agent-runtime-mcp:latest | YES, no-cache | PASS |
| observability-mcp | industrial-ai-agent-observability-mcp:latest | YES, no-cache | PASS |
| rca-mcp | industrial-ai-agent-rca-mcp:latest | YES, no-cache | PASS |

All application images built from current source twice without stale layers. Third-party
images reused; frontend is Nginx with read-only static mounts and has no project build.
Pip-as-root is a build warning; application runtime uses `app`. Image IDs and exact
running-image comparisons are archived. Twelve project-labelled volumes retained in
both cycles: factory DB, older postgres-data, HF cache, Grafana, Loki, Tempo, Prometheus,
and Langfuse PostgreSQL/Redis/MinIO/ClickHouse data/logs. Unrelated Ollama untouched.
No global prune, image/volume deletion, destructive Git, commit, push or deployment.

## Stack

| Service | Running | Healthy | Ready | Restarts |
| --- | --- | --- | --- | --- |
| agent-api | YES | YES | YES | 0 |
| factory-db | YES | YES | YES | 0 |
| factory-mcp | YES | YES | YES | 0 |
| frontend | YES | YES | YES | 0 |
| grafana | YES | YES | YES | 0 |
| hardware-mcp | YES | YES | YES | 0 |
| knowledge-mcp | YES | YES | YES | 0 |
| langfuse-clickhouse | YES | YES | YES | 0 |
| langfuse-minio | YES | YES | YES | 0 |
| langfuse-postgres | YES | YES | YES | 0 |
| langfuse-redis | YES | YES | YES | 0 |
| langfuse-web | YES | YES | YES | 0 |
| langfuse-worker | YES | YES | YES | 0 |
| loki | YES | YES | YES | 0 |
| observability-mcp | YES | YES | YES | 0 |
| otel-collector | YES | YES | YES | 0 |
| prometheus | YES | YES | YES | 0 |
| rca-mcp | YES | YES | YES | 0 |
| runtime-mcp | YES | YES | YES | 0 |
| tempo | YES | YES | YES | 0 |

Readiness: API /health and /ready; frontend root/health; all six authenticated MCP
initialize/list-tools exchanges; Grafana /api/health; Langfuse public database health;
Tempo/Loki /ready; Prometheus /-/ready; host Ollama /api/tags. Collector component checks
are supplemented by successful service/export behavior; Loki's config-only healthcheck
is supplemented by actual HTTP readiness. Databases/Redis/MinIO/ClickHouse/worker use
their native healthchecks. Factory migration is `0025_approval_generation_identity`.
App and migration-owner roles are non-superuser/non-BYPASSRLS. Disposable test databases
were removed after each suite; live demo data was not reset.

## Authoritative gate matrix

| Gate | Command | Scope | Dependencies | Safe | Required |
| --- | --- | --- | --- | --- | --- |
| Clean Docker | docker compose down; docker compose --progress plain build --no-cache; docker compose up -d --no-build --pull never --wait --wait-timeout 600 | 7 builds, 20 services | local Docker; public package/artifact downloads | YES | YES |
| FAST | scripts/run-quality-gate.ps1 FAST | unit, frontend, Ruff/format, secrets | PyCharm venv, local Node | YES | YES |
| Full Python | configured Python -m pytest tests -ra | all tests subtrees | fresh isolated PostgreSQL; fake models | YES | YES |
| INTEGRATION | scripts/run-quality-gate.ps1 INTEGRATION | real DB/MCP/HTTP boundaries | separate freshly migrated seeded test DB | YES | YES |
| Browser | npm --prefix frontend run test:e2e:fixtures | real Chromium + real API/synthetic evidence | local loopback fixtures | YES | YES |
| Runtime smoke | stack_smoke.py, live-ui.mjs, smoke_test_factory_mcp.py --transport http | read-only identity, UI, discovery and protocol | rebuilt stack | YES | YES |
| Quality/build | node --check, pip wheel --no-deps --no-build-isolation --no-index, pip check, docker compose config --quiet, git diff --check | syntax/package/config | installed local tools | YES | YES |
| Documentation/secrets | check-artifacts.ps1, full_secrets.py, conformance tests | local files; secret values never printed | local repo and ignored .env | YES | YES |
| Real-model/manual smoke | npm run e2e:manual / live agent helpers | live inference or action-capable journeys | local model; not guaranteed deterministic action-free | NO for this task | NOT_RUN |

AGENTS, README, pyproject, frontend package/configs, Compose/Dockerfiles, quality/demo/E2E
docs and scripts were inspected. No additional CI/Makefile gate is present. FAST does
not subsume browser, integration, complete Python eval subtree or Docker readiness.

## Test results

| Gate | Passed | Failed | Skipped | Blocked | Result |
| --- | --- | --- | --- | --- | --- |
| FAST backend | 1525 | 0 | 1 | 0 | PASS |
| Full backend (unit + integration + deterministic evals) | 1663 | 0 | 1 | 0 | PASS |
| INTEGRATION script | 123 | 0 | 0 | 0 | PASS |
| Frontend | 252 | 0 | 0 | 0 | PASS |
| Browser E2E, synthetic Chromium | 41 | 0 | 0 | 0 | PASS |
| RLS/Auth evidence group | 181 | 0 | 0 | 0 | PASS |
| MCP evidence group | 154 | 0 | 0 | 0 | PASS |
| HITL/action evidence group | 117 | 0 | 0 | 0 | PASS |
| Model/embedding egress evidence group | 399 | 0 | 0 | 0 | PASS |
| RCA/C01/C02 evidence group | 132 | 0 | 0 | 0 | PASS |
| Migration upgrade cases | 3 | 0 | 0 | 0 | PASS |
| Documentation/architecture cases | 18 | 0 | 0 | 0 | PASS |
| Golden deterministic evals | 15 | 0 | 0 | 0 | PASS |
| Ruff lint + format | 2 gates / 239 files | 0 | 0 | 0 | PASS |
| JavaScript syntax | 38 files | 0 | 0 | 0 | PASS |
| Secret scans | incremental + all tracked actual secrets + evidence | 0 matches | 0 | 0 | PASS |
| Offline wheel + pip check | 2 gates | 0 | 0 | 0 | PASS |
| Compose config + diff check | 2 gates | 0 | 0 | 0 | PASS |
| Local links/translation presence | 48 canonical docs / 73 links | 0 | 0 | 0 | PASS |
| Real-model E2E | 0 | 0 | NOT_RUN | 0 | NOT_RUN |
| Frontend build/lint/typecheck/formatter | — | — | NOT_CONFIGURED | — | NOT_CONFIGURED |

Counts from XML; thematic evidence groups overlap and must not be added together.
Full Python consists of 1,525 unit passes, 123 integration passes and 15 deterministic
eval passes. Migration tests also exercise fresh installation and all upgrades to HEAD.
The single skip is Windows symlink creation. There are no xfails. Local docs checks
validate file targets and translation presence/ignored status, not external URLs or
anchors; semantic conformance has separate tests and independent-review inspection.
Full actual-secret scan covers all 430 tracked/report text files at that checkpoint;
final reports are rescanned separately. No frontend production compilation, lint,
typecheck or formatter command is configured. Static modules are the production assets.

## Demo Auth Matrix

| Identity | Clearance | Roles | Model configuration | Result |
| --- | --- | --- | --- | --- |
| demo-public | PUBLIC | — | denied | PASS |
| demo-internal | INTERNAL | — | denied | PASS |
| demo-confidential | CONFIDENTIAL | — | denied | PASS |
| demo-restricted | RESTRICTED | — | denied | PASS |
| demo-admin | PUBLIC | MODEL_ADMIN | allowed | PASS |

Fresh live browser starts PUBLIC. Live header order is Monitoring, Configuration,
Account/current user; investigation toolbar contains PDF, New Chat. No clearance selector
or Basic challenge. Five live identities, role/clearance display, quick switch,
configuration states, language and persistent logout pass; HTTP probe verifies login
after logout. Synthetic browser coverage independently checks stale protected JSON,
downloads, Blob cleanup, BFCache/back navigation, shared tabs, upgrade/downgrade and
protected document denial. Disabled demo mode and forged context are deterministic
backend/integration regressions. Real classified live UI investigations are not created.

## Demo Visibility Matrix

| Identity | Stations | Products | Result |
| --- | --- | --- | --- |
| demo-public | S01, S05 | P4101, P4102 | PASS |
| demo-internal | S01, S02, S03, S05 | P4101, P4102, P4900, P4901 | PASS |
| demo-confidential | S01, S02, S03, S04, S05, S06 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901 | PASS |
| demo-restricted | S01, S02, S03, S04, S05, S06, S07, S08 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901, P9001, P9002 | PASS |
| demo-admin | S01, S05 | P4101, P4102 | PASS |

Seed SQL and demo_seed.py confirm PUBLIC S01/S05, INTERNAL S02/S03, CONFIDENTIAL S04/S06,
RESTRICTED S07/S08. On rebuilt Factory MCP the four principal ceilings return exact
station/product sets via RLS. Admin shares PUBLIC ceiling. The exact prompts
“welche stationen kennst du” and “Welche Produkte kennst du?” run through real server
sessions, policy, LangGraph, capabilities and PostgreSQL in the disposable integration
fixture, with exactly one discovery call and fake final model. Live cloud/local chat
inference is deliberately not invoked. Browser station prompt coverage uses the real
API/graph with synthetic repository. Unknown/mixed prose, S07 in discovery wording and
sensitive context fail conservatively; forbidden identifiers are absent.

## Runtime logs

All 20 service logs and keyword matches archived after readiness and tests. Expected
negative tests: denied auth/models/documents and intentional PostgreSQL check/uniqueness
violations in isolated databases. Expected startup warnings: Factory/RCA OTel collector
DNS/export deadlines before collector starts, Loki empty-ring/readiness delay, OCR/model
artifact downloads, torch/AnyIO/OTel deprecations. Export errors cease after readiness.
LOW known warnings: optional Grafana plugins/alerting provisioning directories absent;
Tempo replay removes an incomplete old WAL segment from retained storage. No persistent
unexpected error, failed migration, worker restart loop or unhealthy service observed.
Retained historical telemetry integrity is not certified. No logs/secrets suppressed
to obtain green; redaction removes credential values only.

## Real model status

REAL_MODEL_E2E: NOT_RUN. Local inference readiness does not certify model behavior.
The supported live release journeys are not needed for these deterministic gates and
are not claimed as PASS. No real protected write or industrial action was performed.

## External calls

External model calls: 0. External dependency/package/model-artifact downloads occurred
during clean builds/startup; these are not repository-data inference. No repository
payload was sent by a verification probe to an external AI service. Local model
infrastructure remained available. Commits 0, deployments 0, hardware side effects 0.

## Final verification result

PASS for the complete applicable safe gate matrix. REAL_MODEL_E2E remains NOT_RUN.

## Ready for independent review

YES. Baseline frozen after final clean verification. The subsequent read-only review
is recorded separately in [full review](full-review-2026-10-14.md); its findings are
not stabilization repairs. Healthy Docker stack remains running.
