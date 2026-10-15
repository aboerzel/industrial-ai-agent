# Final Verification — 2026-10-15

## Result

**FAIL.** The clean build and all registered deterministic test gates passed. The
fresh live discovery smoke failed two required product-completeness checks. Independent
review additionally confirmed three other defects. No product, test, configuration,
historical report, migration, or existing script was repaired or changed.

The separate [independent review](final-independent-review-2026-10-15.md) contains the
four findings; the [certification summary](final-certification-summary-2026-10-15.md)
records the final decision.

## Baseline and preservation

| Item | Recorded value |
| --- | --- |
| Repository | `D:\Freelance\industrial-ai-agent` |
| Branch | `main` |
| HEAD | `c1c434b167bdbd0207e29e287cea1ff0dec98b07` |
| Initial working tree | Clean; staged, unstaged, and nonignored untracked lists empty |
| Initial manifest | 2026-10-15 16:13:08 Europe/Berlin; SHA-256 for all 460 versioned files |
| Verified freeze | 2026-10-15 16:27:19 Europe/Berlin; 460 matching hashes, zero changes |
| Python / Node / npm | 3.12.10 / v24.19.0 / 11.17.0 |
| Docker client/server / Compose | 29.8.2 / 29.8.2 / v5.6.0 |
| Initial containers | 20 project services plus the existing unrelated `ollama` container |
| Initial images and volumes | Recorded before build; project volume inventory unchanged afterward |

Evidence is local and unversioned under
`evals/results/final-certification-2026-10-15/`. Important files are
`initial-working-tree-manifest.json`, `verified-working-tree-manifest.json`,
`final-working-tree-manifest.json`, `initial-images.json`, and `final-container-state.txt`.
The initial, freeze, and final manifests use the same original file set.

Historical reports from 2026-10-14 and earlier 2026-10-15 are unchanged. In particular,
`full-verification-2026-10-15.md`, `full-review-2026-10-15.md`,
`post-refactoring-final-summary-2026-10-15.md`, and
`stabilization-repair-log-2026-10-15.md` were preserved. New reports have new names;
their German counterparts are local and ignored. No commit, push, or external
deployment occurred.

## Authoritative gate discovery

Reviewed AGENTS.md, README, pyproject.toml, frontend/package.json, Compose, all seven
Dockerfiles, quality/demo/browser documentation, architecture contracts and the 20 ADRs.
There is no root package.json or checked-in CI workflow in this baseline. FAST omits
integration tests and the 15 deterministic golden-evaluation tests under `tests/evals`.

Commands below run from the repository root unless a frontend working directory is
specified. Python commands used the PyCharm-configured absolute venv executable.

| Gate | Command | Scope | Required | Dependencies | Safe |
| --- | --- | --- | --- | --- | --- |
| Clean build | `docker compose down --timeout 45`; `docker compose build --no-cache` | Complete project, seven application images | Yes | Local Docker, package downloads | Yes; no volume removal |
| Startup | `docker compose up --detach --no-build --wait --wait-timeout 300` | All 20 services | Yes | Preserved volumes, local Ollama | Yes |
| Unit / FAST | `.\scripts\run-quality-gate.ps1 FAST` | Unit, frontend, Ruff, formatting, incremental secrets | Yes | Configured Python/Node | Fakes; no models |
| Full backend | `.venv\Scripts\python.exe -m pytest tests -ra --junitxml=evals/results/final-certification-2026-10-15/full-backend.xml` | Unit + integration + golden scorer tests | Yes | Disposable PostgreSQL, local synthetic MCP/Nginx | No external model |
| Integration | `.\scripts\run-quality-gate.ps1 INTEGRATION` | Every registered integration module | Yes | Explicit disposable admin/app URLs | No external model |
| Frontend | `npm run test` in `frontend` (within FAST) | All Node state, UI, API, harness contracts | Yes | Existing node_modules | Local/fake |
| Safe browser | `npm run test:e2e:fixtures -- --output=../evals/results/final-certification-2026-10-15/browser-artifacts --reporter=json` | Actual registered fixture suite | Yes | Chromium, loopback fixture servers | No model |
| Explicit regressions | `python -m pytest -vv -rs` with the 12 files recorded in `security-regressions.log` | C/R, embeddings, protected actions, demo sessions/discovery | Yes | Fakes/MockTransport | No network inference |
| N01 adversarial probe | Configured Python plus `n01-independent-probe.py` in the evidence directory | Independent mixed relations and physical FK controls | Yes | Disposable real RLS DB | Synthetic only |
| Live smoke | `node .../live-demo-smoke-confirmation.mjs`; configured Python plus `live-readiness-confirmation.py` | Gateway identities, inventory phrases, HTTP/MCP readiness | Yes | Rebuilt stack; preflight-pinned local model | Read-only tools; no resume/assignment writes |
| Quality | Ruff checks in FAST; `node --check` for all tracked JS/MJS; `static_audit.py`; `git diff --check` | Lint/format, syntax, imports, docs, links, secrets | Yes | Local tools | Read-only |
| Wheel | `python -m pip wheel --no-build-isolation --no-deps --no-index --wheel-dir .../wheels .../wheel-source` | Disposable copy of source and pyproject | Yes | Installed build backend | No original build metadata changes |
| Real-model E2E | `npm run e2e:manual` / legacy `test:e2e` | Model-dependent multi-turn journeys | Conditional | Local model, nondeterministic judgments | NOT_RUN under this task's deterministic E2E condition |

No JS lint or static typecheck command is configured. These are **NOT_CONFIGURED**,
not invented passing gates. Model-dependent evaluation/smoke commands that could run
inference or protected actions were not substituted for deterministic checks.

## Clean rebuild

The complete project stack was stopped and its containers/network removed by scoped
Compose down. All named volumes, model caches, factory documents, PostgreSQL and
observability storage were preserved. No global prune, volume deletion, or unrelated
container removal was used. `ollama` remained running.

| Service | Image | Clean rebuild | Result |
| --- | --- | --- | --- |
| agent-api | industrial-ai-agent-agent-api | No cache | PASS |
| factory-mcp | industrial-ai-agent-factory-mcp | No cache | PASS |
| knowledge-mcp | industrial-ai-agent-knowledge-mcp | No cache | PASS |
| hardware-mcp | industrial-ai-agent-hardware-mcp | No cache | PASS |
| runtime-mcp | industrial-ai-agent-runtime-mcp | No cache | PASS |
| observability-mcp | industrial-ai-agent-observability-mcp | No cache | PASS |
| rca-mcp | industrial-ai-agent-rca-mcp | No cache | PASS |
| frontend and third-party dependencies | Existing upstream images | No project build applicable | Preserved/recreated |

`docker-clean-build.log` records the first build through exit 0. Full old/new image IDs
are retained. Knowledge startup downloaded OCR/model assets from upstream artifact
hosts; package installation also used package registries. These were dependency
downloads, not external model inference or repository/prompt uploads.

## Stack and readiness

Final state: **20/20 healthy, all restart counts 0**. The stack remains running.

| Service | Running | Healthy | Ready evidence | Restarts |
| --- | --- | --- | --- | --- |
| agent-api | Yes | Yes | HTTP `/ready` 200 | 0 |
| frontend | Yes | Yes | HTTP `/health` 200; live browser | 0 |
| factory-db | Yes | Yes | pg_isready; authoritative seed SELECT | 0 |
| factory-mcp | Yes | Yes | MCP initialize/discovery; exact list calls | 0 |
| knowledge-mcp | Yes | Yes | MCP initialize/discovery | 0 |
| hardware-mcp | Yes | Yes | MCP initialize/discovery; no execution | 0 |
| runtime-mcp | Yes | Yes | MCP initialize/discovery | 0 |
| observability-mcp | Yes | Yes | MCP initialize/discovery | 0 |
| rca-mcp | Yes | Yes | MCP initialize/discovery; no reasoning call | 0 |
| otel-collector | Yes | Yes | Active Prometheus scrape `up=1`; recent traces | 0 |
| prometheus | Yes | Yes | HTTP `/-/ready` 200; current application series | 0 |
| loki | Yes | Yes | HTTP `/ready` 200 on confirmation | 0 |
| tempo | Yes | Yes | HTTP `/ready` 200; trace search 200 | 0 |
| grafana | Yes | Yes | HTTP health and configured datasource API 200 | 0 |
| langfuse-web | Yes | Yes | Public health with database check 200 | 0 |
| langfuse-worker | Yes | Yes | Configured HTTP worker healthcheck | 0 |
| langfuse-postgres | Yes | Yes | Configured pg_isready | 0 |
| langfuse-clickhouse | Yes | Yes | Configured HTTP ping | 0 |
| langfuse-redis | Yes | Yes | Configured authenticated Redis ping | 0 |
| langfuse-minio | Yes | Yes | mc readiness and HTTP readiness 200 | 0 |

The separate local Ollama `/api/tags` probe returned 200. Initial Loki `/ready` was 503
although its configuration-only Docker healthcheck was green; the first failure is
preserved in `live-readiness.json`. Confirmation returned 200 without intervention.
MCP readiness uses protocol initialization and tool discovery, not a listening port.

## Complete verification counts

| Measurement | Passed | Failed | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Complete unit suite, FAST | 1,631 | 0 | 1 | PASS with explicit platform skip |
| Full backend, `pytest tests` | 1,798 | 0 | 1 | PASS; includes 152 integration and 15 golden tests |
| INTEGRATION gate | 152 | 0 | 0 | PASS |
| Frontend suite, FAST | 276 | 0 | 0 | PASS |
| Safe browser fixtures | 66 | 0 | 0 | PASS; 0 flaky, actual registry 66 |
| Explicit security regression rerun | 581 | 0 | 0 | PASS; subset, not additional unique coverage |
| Independent N01 controls | 120 assertions / 24 projection cases | 0 | 0 | PASS |
| Post-freeze independent provider/embedding controls | 25 | 0 | 0 | PASS |
| Post-freeze mixed discovery classification controls | 16 | 0 | 0 | PASS |
| Live gateway station discoveries | 5 | 0 | 0 | PASS |
| Live gateway product discoveries | 3 | 2 | 0 | FAIL |

FAST completed with exit 0. Ruff lint passed; 248 files passed Ruff format checking.
All 40 tracked JS/MJS files passed syntax checking. Compose validation and wheel build
passed. AST dependency inspection found no prohibited outward imports. All 20 ADR
files were inventoried; current ADR references and documentation conformance tests
passed. Local Markdown path validation found no unresolved candidates. The ten
Markdown files without German companions are synthetic document/retrieval corpus
inputs, rather than current technical documentation; relevant technical documents
have companions and matching Mermaid diagram counts.

The configured incremental credential gate passed. A supplementary full tracked-file
scan found no high-signal secrets; 17 heuristic candidates were reviewed as synthetic
test values, environment substitutions, or the non-secret SDK placeholder. This is not
a claim of exhaustive third-party secret-scanner coverage. No dependency installation
or source formatting was performed on the host.

The one unit skip is `test_catalog_content_path_rejects_symlink_escape_and_missing_storage`:
Windows did not allow creation of its symlink. This path was not counted as passed.
The five full-backend warnings are upstream Starlette/AnyIO and OTel deprecations.

Integration used `iaa-final-cert-postgres-20261015`, a loopback-only, tmpfs PostgreSQL
18.6 container, distinct from the persistent demo database. Separate `verification_`
databases enabled the tests' explicit write-safety guards. Fresh migrations reached
`0025_approval_generation_identity`; upgrade/bootstrap tests created further isolated
databases and cleaned them. All disposable databases and the labeled disposable
container were removed after review. Persistent demo data was not used as a test fixture.

## Explicit C01–C06, R01–R06 and N01 certification

| ID | Status | Current executed evidence and inspection |
| --- | --- | --- |
| C01 | CLOSED | 18 event-controlled evidence/document I/O cases; progress, context and cancellation ownership inspected |
| C02 | CLOSED | 19 capacity, total-deadline, timeout, cancellation and shutdown/drain cases; worker admission/lifecycle inspected |
| C03 | CLOSED | Valid constructed requests reach actual destination guards; spies and authorized real-SDK MockTransport positive controls succeed |
| C04 | CLOSED | 31 transport cases; HTTP cloud denied before credentials/SDK, HTTPS plus authorization positive control, proxy/redirect/userinfo protections |
| C05 | CLOSED | ADR-001–020 index/current contracts, supersession notes, architecture facts and EN/DE diagrams consistent in reviewed scope |
| C06 | CLOSED | 20 unit + 9 PostgreSQL generation cases; unique server UUID, same-generation retry, distinct generations, replay, concurrency, legacy denial |
| R01 | CLOSED | 29 dedicated cases and fresh post-freeze missing/copied/wrong-request/model/zone/ceiling controls; denied counters all zero; authorized MockTransport succeeds |
| R02 | CLOSED | 25 unit + 2 PostgreSQL slow-I/O cases; claim-before-write, owned worker/cancellation, no automatic retry, replay/concurrency and thread-owned sessions |
| R03 | CLOSED | 18 unit + 6 PostgreSQL cases and real-browser fixtures: stale approve/reject conflicts, B unchanged, repeated model IDs, restart, multi-tab/BFCache/switch |
| R04 | PARTIAL | Registered sender/receiver failure, late-response and BFCache cases pass; new FC04 exposes the separately implemented transcript-only PDF Blob lifecycle |
| R05 | CLOSED | 19 ownership cases: cold 2/8 callers, failure cleanup/retry, repeated close, close/init race, warm overlap and worker drain before adapter close |
| R06 | CLOSED | Current session/Nginx docs and actual 66-case fixture registry agree; Basic-auth references are historical or explicitly negated |
| N01 | CLOSED | 21 registered real-RLS tests plus fresh independent 120 assertions: mixed visible/hidden events/stations, order, empty projection, no hidden identifiers, no bypass, high-clearance control and valid physical FK |

N01's product fix remains valid. FC01 and FC02 concern different adapters/relationships;
they do not reclassify the successfully retested product defect as closed by assumption.

## Demo Auth and visibility

All five live users returned exact expected username, clearance and roles. Every
identity switch purged investigation context. Logout returned `/auth/me` 401 and
cleared the UI. Configuration was enabled only for demo-admin. Header/toolbar order,
account keyboard behavior, language, responsive UI, approvals, downloads/filename,
MIME handling and PDF controls passed the registered browser/frontend tests.

The live preflight read all persistent assignments and verified every Agent assignment
was `MANUAL/local_quality`, resolving to LOCAL. The assignment snapshot was unchanged
afterward. No assignment PUT or approval resume was allowed by the smoke harness.

| User | Clearance / roles | Exact station set | Exact product set at MCP | Live product presentation |
| --- | --- | --- | --- | --- |
| demo-public | PUBLIC / none | S01 S05 | P4101 P4102 | PASS |
| demo-internal | INTERNAL / none | S01 S02 S03 S05 | P4101 P4102 P4900 P4901 | PASS |
| demo-confidential | CONFIDENTIAL / none | S01 S02 S03 S04 S05 S06 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 | FAIL: only first six products presented |
| demo-restricted | RESTRICTED / none | S01 S02 S03 S04 S05 S06 S07 S08 | Previous nine plus P9001 P9002 | FAIL: only first six products presented |
| demo-admin | PUBLIC / MODEL_ADMIN | S01 S05 | P4101 P4102 | PASS |

The actual persistent seed and current authoritative visibility document agree.
The exact phrase `welche stationen kennst du` passed for all five identities;
`Welche Produkte kennst du?` failed completeness for two. Both responses nevertheless
reported success. The shared 12-reference budget includes secondary stations/faults,
dropping later product references; a generic safe narrative provides no complete
alternative list. FC03 includes a deterministic reproduction without model inference.
No above-clearance station or product was disclosed in the inventory smoke.

The first new smoke harness opened the account panel before New Chat and read a
nonexistent `final_answer` response property. Its seven failures are preserved in
`live-demo-smoke.json`/`.log`. Only a separate new evidence harness was corrected;
its independent confirmation still found the two real product failures. No existing
test, fixture, or assertion was weakened.

## Runtime logs, external calls and side effects

Collected sanitized logs for all 20 project services, both initially and in
`runtime-final/`. `runtime-log-reviewed.json` classifies every final keyword hit:
67 EXPECTED_STARTUP_WARNING, 1,536 BENIGN_WARNING, 5 EXPECTED_NEGATIVE_TEST;
no unresolved HIGH/CRITICAL or unexpected persistent application error.

Startup OTel DNS/deadline failures stopped after collector readiness. Current scrape
`up=1`, application LLM/MCP metrics and recent trace search demonstrate recovery.
Loki's empty-ring startup error and initial 503 recovered. Tempo discarded an incomplete
pre-existing WAL block and serves current traces; historical WAL completeness is not
certified. Grafana optional plugin/provisioning/usage-stat messages do not block the
configured local datasources, whose API returned 200. No service restarted.

Real-model E2E: **NOT_RUN**. The repository's model-dependent journey suite does not
provide deterministic outcomes, so it was not run or called PASS. The separately
requested live inventory smoke used only the preflight-verified local model and
read-only tools. Deterministic backend/browser gates used fakes/MockTransport.

External model calls: **0**. Real protected side effects: **0**. Persistent maintenance
ticket count was 100 before and after the live smoke. Synthetic ticket/approval writes
occurred only in disposable test infrastructure. Artifact/package downloads and normal
third-party update checks are not classified as model inference. No network packet
capture was used; the inference conclusion rests on the explicit invocations,
assignment/zone preflight, local metrics and inspected execution paths.

## Final frozen baseline

The end-of-run comparison against both original manifests records **zero changed or
missing original versioned files**. The Git index and HEAD are unchanged. Only new
certification reports, their ignored German companions and disposable evidence/results
were added. Existing historical evidence was not overwritten. The temporary database
container is gone; all persistent project volumes remain and the healthy stack is left
running. The failed live product checks and four review findings remain unrepaired.
