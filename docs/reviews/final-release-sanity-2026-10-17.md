# Final Release Sanity — 2026-10-17

## Result and scope

Final result: **FAIL**. Overall conclusion: **NO**.

The local Real-Model gate encountered a provider deadline failure and an Ollama HTTP
500. This violates explicit release acceptance regardless of subsequent recovery.
All independent verification was completed without repairs or retries.

This is a clean-build release sanity verification of the committed CERT-01 remediation
and previously certified baseline, not another architecture review. No implementation,
test, configuration, model assignment, prompt or timeout was changed. No repairs,
commits, pushes, external deployments, external model calls or protected real actions
were performed. Only this new report, its ignored local German counterpart and new
verification evidence were created.

## Frozen baseline

| Item | Recorded value |
| --- | --- |
| Repository | `D:/Freelance/industrial-ai-agent` |
| Branch | `main` |
| HEAD | `d692e489f469777530e629e29ba05708759be5bc` |
| Initial index/worktree/untracked status | CLEAN |
| Start | 2026-10-17 09:25:40 Europe/Berlin |
| Versioned file manifest | SHA256 for all 509 original files, outside the repository |
| Python | Configured `.venv`, 3.12.10 |
| Node / npm | 24.19.0 / 11.17.0 |
| Docker / Compose | 29.8.2 / 5.6.0 |
| Ollama / GPU | 0.33.2 / NVIDIA GeForce RTX 3070, 8192 MiB |
| Protected baseline | 100 maintenance tickets; 5 maintenance events; 1 process parameter |

Evidence directory: `D:/Freelance/final-sanity-evidence-20261017-092540`.
Browser product artifacts: `evals/results/browser-e2e/final-sanity-20261017-092540/`.
Historical certification and remediation reports were read but not modified.

## Clean rebuild and readiness

The complete Compose stack was stopped using `docker compose down` without deleting
volumes. PostgreSQL, caches, observability and object-storage volumes were preserved.
The existing standalone local Ollama runtime and storage were preserved.
`docker compose build --no-cache` rebuilt **7/7** application images:

| Application image | Result | Immutable image ID prefix |
| --- | --- | --- |
| agent-api | PASS | `e63929eef30a1280` |
| factory-mcp | PASS | `c87c31e04e1e28b8` |
| knowledge-mcp | PASS | `25fb489393e407b7` |
| hardware-mcp | PASS | `eb2392ba33d13514` |
| runtime-mcp | PASS | `f7e2afcbd3e9d368` |
| observability-mcp | PASS | `21c6e895b1066c12` |
| rca-mcp | PASS | `96a1804a9662738f` |

Full IDs and first build output are in `rebuilt-image-ids.txt` and `build.log`.
`docker compose up -d` completed successfully. API `/ready`, frontend, and all six
required MCP services passed real readiness/protocol checks. ML warmup temporarily
caused healthcheck failures in Knowledge and other CPU-contending services; first
evidence was preserved. Loki initially returned 503, subsequently 200. These recovered
without configuration changes or operator model intervention.

Final: **20/20 services healthy, 0 unexpected restarts**. API and all six required MCPs
pass actual readiness; final HTTP checks are all 200 and the Prometheus scrape target is
up. The standalone Ollama restart count is also zero. Final model snapshot still shows
chat 100% GPU and embedding 100% CPU; ordinary idle expiry is not a model crash.

## Deterministic gates

| Gate | Current result |
| --- | --- |
| Full backend, configured Python `-m pytest tests` | 2083 collected; 2077 PASS, 0 FAIL, 6 SKIP |
| Full `scripts/run-quality-gate.ps1 INTEGRATION` | 279 PASS, 0 FAIL, 5 SKIP |
| Separate opt-in KDEP | 5/5 PASS, 0 SKIP |
| KDEP offline restart | PASS: real authenticated retrieval/provenance after restart; 0 downloads/import failures |
| FAST unit subgate | 1783 PASS, 1 platform SKIP |
| FAST frontend subgate | 338 PASS, 0 FAIL/SKIP |
| FAST Ruff / format / secret scan | PASS / PASS / PASS |
| Combined focused Observability/RCA/Runtime/C01/R01/access suite | 172/172 PASS, including 19 CERT-01 cases |

Backend and integration ran against disposable PostgreSQL. The application role had
`rolsuper=false`, `rolbypassrls=false`. Browser Discovery and KDEP used separate
disposable databases. The six normal-backend skips were five opt-in KDEP cases and the
Windows symlink-creation capability test. The KDEP cases were then executed separately;
the platform skip remains explicitly untested.

KDEP used the newly built production image/command, an internal-only network, cached
real OCR/layout/reranking assets, local CPU embeddings, read-only content/cache mounts,
no cloud credentials and a non-bypass application role. An additional offline restart
became healthy after 153.18 seconds; authenticated retrieval still worked with no
downloads. All disposable containers/network were removed; shared volumes were preserved.

## Browser gates and core smoke

The safe fixture inventory contains **144 cases in seven files**. First invocation:
124 PASS and 20 infrastructure SKIP because the Discovery fixture lacked its disposable
database variable. Only those 20 unexecuted cases were subsequently run with an isolated
seeded database: 20 PASS. Combined case-identity accounting confirms **144 distinct cases
executed exactly once**, 0 duplicate executions, 0 FAIL, 0 unresolved SKIP, 0 FLAKY,
and retries=0. Both original reports and `safe-browser-final-accounting.json` are retained.

Legacy: **5/5 journeys, 30/30 required assertions PASS**, retries=0,
FAIL/BLOCKED/HARNESS_ERROR/NOT_RUN journeys=0. Each fresh context observed unauthenticated
`auth/me` 401 and supported PUBLIC bootstrap. Ten separate MANUAL_ONLY assertions were
not counted as required passes; protected HITL execution was not performed.
Independent real MCP read proofs were collected separately.

All five Demo identities passed live identity, clearance/role separation, Configuration
permission, quick switch, logout/relogin, language and state-purge checks. Exact Factory
inventories, persisted API answers and browser inventories matched the current seed:

| Identity | Exact Station IDs | Products |
| --- | --- | ---: |
| demo-public | S01 S05 | 2 |
| demo-internal | S01 S02 S03 S05 | 4 |
| demo-confidential | S01 S02 S03 S04 S05 S06 | 9 |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | 11 |
| demo-admin | S01 S05 | 2 |

All ten discovery checks passed with exact IDs and no duplicates. Admin remained PUBLIC
with MODEL_ADMIN; restricted remained RESTRICTED without MODEL_ADMIN. Assignment snapshots
were unchanged. `factory-live.json` and `live-browser-completion.json` retain exact product
IDs and API/persistence/browser evidence.

Original live reference-action matrix: **FAIL**, **12/16 PASS, 4 FAIL** (cases 2/3/5/6),
no skips/flakiness/retries. All 16 cases executed once; failures did not suppress later
cases. Fourteen action requests were sent: twelve succeeded with the required first
read/target; two returned `llm_provider_unavailable` (HTTP 200, terminal failed).
Two cases failed their initial investigation prerequisite before the action request.
They are not counted as accepted actions. Evidence: `live-references-final.json`,
`live-reference-counts.json`, `live-references-final/reference-browser-matrix.json`.
No unexpected neutral 404 or Agent API HTTP 500 occurred in the recorded action requests;
provider failures still make the matrix FAIL.

The first anchored Playwright title
filter selected no tests and executed none; its launch error is preserved. A corrected
selection enumerated exactly 16 cases before their single execution. No failed case is
being retried or reclassified as a first-run pass.

## CERT-01 live proof

**PASS.** Safe synthetic run `24807c71-18c2-4c51-aaa4-df6e9493bd5e` produced execution
trace `60cf5e821786b05873a67efbedb64f42`: 86 spans, two LLM spans, one tool span;
`agent.run` duration **10774.297792 ms**. This execution ID was captured before the
read sequence. After three History reads, a status GET and a PDF GET, authenticated
Observability selected that exact execution ID and RCA reported the actual duration
and two generations. The five competing read traces remain separately observable.

The initial proof's fixed 12-second indexing assumption was too early and raised a
harness assertion. It is preserved in `cert01-fresh.log`; no new run/model retry was
used to replace it. Once the same run became searchable, its execution identity was
captured in `cert01-trace-diagnostic.json`, then the required read sequence and actual
Observability/RCA assertions completed in `after-visible-live.json`.

The original historical run `b4bbbbec-30d4-4434-ad53-f9ffa367545b` remains available.
It correctly selects `bad5a392a533e5765d7ce31a5d1d4ea4`, with **8966.823590 ms**
execution duration and two LLM calls (`after-original-live.json`). The original short
History trace is no longer selected. Missing-execution/no-fallback, short-execution,
ordering, duplicate identity and authorization cases passed in the focused suite.
RCA still reports independent unavailable sources explicitly, without inventing evidence.

## Local Real-Model product gate and capacity

**FAIL**: all twelve registered journeys executed once, without resume/retry;
**9 PASS, 3 FAIL**. Of 59 required assertions, **54 PASS, 4 FAIL, 1 BLOCKED**;
58 executed. The runner's local-assignment preflight and read-only drift checks passed.

| Journey | Result | Required passed/total | Evidence-based failure classification |
| --- | --- | ---: | --- |
| s04-investigation | PASS | 6/6 | — |
| station-discovery | PASS | 4/4 | — |
| product-history | PASS | 4/4 | — |
| documentation | PASS | 8/8 | — |
| clearance-boundary | PASS | 9/9 | — |
| station-discovery-de | PASS | 4/4 | — |
| healthy-station-de | PASS | 3/3 | — |
| healthy-station-en | PASS | 4/4 | — |
| s04-investigation-en | PASS | 4/4 | — |
| product-centric-en | FAIL | 0/3 | BLOCKED_BY_PROVIDER; raw runner HARNESS_ERROR after secondary reload failure |
| clearance-boundary-en | FAIL | 5/6 | BLOCKED_BY_PROVIDER |
| restricted-boundary | FAIL | 3/4 | INFRASTRUCTURE_ERROR: persisted agent_execution_timeout, with a late provider timeout; raw runner MODEL_VARIANCE |

Primary execution-evidence classification: BLOCKED_BY_PROVIDER **2**, INFRASTRUCTURE_ERROR **1**;
PRODUCT_DEFECT/MODEL_VARIANCE/HARNESS_ERROR/SECURITY_DEFECT **0**
as separate primary causes. Raw journey categories remain preserved unchanged:
HARNESS_ERROR **1**, BLOCKED_BY_PROVIDER **1**, MODEL_VARIANCE **1**. These are two
different classifications, not extra journeys. In particular, the last failure is
not demonstrated stochastic wording variance.

The gate's executions made **92 provider calls**, independently matched to **92 Ollama
chat HTTP calls**. Maximum provider span **45.055273409 s**; **3** explicit
`provider.error_type=APITimeoutError` spans; **3** attributed Ollama HTTP 500s; **0**
external/unverified provider spans. One provider call completed after the browser gate
ended. Its execution-owned trace and delayed HTTP 500 are included, not lost by cutting
logs at browser cleanup. The original strict browser-window log (two 500s) is retained
alongside the completion-tail log. Metrics are scoped to these executions; later
reference-gate failures are additionally recorded in the runtime section.

Continuous `/api/ps` and Windows GPU-memory samples are retained in
`capacity-monitor.jsonl`. The unchanged `qwen3-embedding:0.6b` model parameter is
`num_gpu=0`. Observed chat `qwen3.5:9b`: 100% GPU; embedding: 100% CPU, zero GPU allocation.
Across **420** browser-gate placement samples, chat was fully on GPU, embedding had
**0 bytes GPU allocation**, and chat/embedding GPU co-residency occurred **0** times.
Dedicated GPU memory ranged **7.399–7.784 GiB**, shared GPU memory **0.825–1.635 GiB**.
The placement policy passed; the independent provider reliability acceptance failed.

## Historical finding sanity

Statuses are based on this run's existing regression tests and browser/live proofs,
not inherited solely from old reports. No new architecture review was performed.

| Finding | Current evidence | Status |
| --- | --- | --- |
| C01 | 18 async RCA/I/O cases | CLOSED |
| C02 | 19 provider lifecycle cases | CLOSED |
| C03 | 25 stabilization cases | CLOSED |
| C04 | 31 provider TLS/destination cases | CLOSED |
| C05 | 14 documentation conformance cases; unchanged existing docs | CLOSED |
| C06 | 20 unit + 9 PostgreSQL approval-generation cases | CLOSED |
| R01 | 29 provider authorization cases | CLOSED |
| R02 | 25 unit + 2 PostgreSQL ticket-I/O cases | CLOSED |
| R03 | 18 unit + 6 PostgreSQL cases and safe browser generation cases | CLOSED |
| R04 | Current cross-tab/BFCache/stale-request/Blob fixture and frontend cases | CLOSED |
| R05 | 19 provider ownership cases | CLOSED |
| R06 | Current Demo Auth/conformance tests, five live identities, legacy bootstrap | CLOSED |
| N01 | 21 actual PostgreSQL relation-visibility cases | CLOSED |
| FC01 | 29 ticket/hidden-station cases | CLOSED |
| FC02 | 37 classification-projection cases | CLOSED |
| FC03 | 14 unit + 30 integration cases, all discovery fixtures and live inventories | CLOSED |
| FC04 | Current protected Blob/PDF lifecycle browser and frontend cases | CLOSED |
| CERT-01 | 19 focused cases; fresh and original live execution selection | CLOSED |

## Runtime, stability and integrity

### SANITY-01 — Local provider and execution deadline failures

**MEDIUM, operational reliability.** Three independent registered journeys encountered
local provider timeouts; two returned provider-unavailable and one persisted an agent
execution timeout. None was retried. The precise internal performance cause is unproven.
The registered `product-centric-en` journey's initial read-only INTERNAL request failed
for run `ddfa0913-ae59-4d9a-ac44-9d90828e69c9` on its first and only execution.
The API returned HTTP 200 with terminal status `failed` and
`error_code=llm_provider_unavailable`. At 2026-10-17 07:52:41 UTC, Ollama logged
HTTP **500** for `/v1/chat/completions` after **45.043346415 seconds**, followed by
task cancellation. The existing deadline was not changed.

The first required typed assertion failed; the required reference assertion was blocked;
the reload assertion subsequently timed out. The raw runner category is `HARNESS_ERROR`
because it also records the secondary reload failure. The observed initiating failure is
the local provider deadline, not stochastic wording or missing reference rendering alone.
Expected: successful product investigation, zero provider timeouts and zero Ollama 500s.
Impact: this normal read journey cannot complete. The precise internal reason for the
long provider execution is unproven; GPU co-residency must not be inferred from a timeout.

First evidence: `first-real-model-failure-product-centric-en.json`,
`first-provider-failure-ollama.log`, the immutable journey artifact, and current-window
Agent API logs. No journey retry, repair, model change or timeout adjustment was attempted.

The second provider failure belongs to `ed737eb0-1a8a-46d8-8443-0b43a8dc16d3`
(`clearance-boundary-en`), with an APITimeoutError span of **45.025168656 s**.
The third belongs to `877747e2-7058-4778-b8b1-b793562b27a2`
(`restricted-boundary`), with a **45.041226608-s** structured-response APITimeoutError.
The latter execution lasted **122.863147722 s** and persisted `agent_execution_timeout`;
the browser saw no terminal result within its existing wait. Its API-authorized History
read confirms the failed persisted turn. This is not an unsupported model-wording finding.
First artifacts for both additional failures and safe trace evidence are preserved.
The separate reference matrix additionally failed cases 2/3/5/6. Its two recorded failed
action responses explicitly report `llm_provider_unavailable`; the other two failed
their initial-run prerequisite. These failures remain failed and support the same
operational reliability limitation. No reference code repair was attempted.

All 20 project-service logs and standalone Ollama logs were collected only for this
sanity window and redacted. **7 Ollama HTTP 500s** occurred: three belong to Real-Model
executions (including their completion tail), four to the separate reference gate.
Agent API logs contain six provider-unavailable events; the remaining Real-Model failure
persisted an orchestration timeout. These are correlated views of failures, not additional
independent findings. No CUDA/OOM, fatal crash, unexpected restart or restart loop was found.

| Log classification | Evidence and interpretation |
| --- | --- |
| RELIABILITY_DEFECT | SANITY-01, provider/execution deadlines and seven Ollama 500s |
| EXPECTED_AUTH_DENIAL | Fresh unauthenticated `auth/me`; denied non-admin configuration and hidden-resource reads |
| EXPECTED_STARTUP_WARNING | ML warmup probes, OTel exporter DNS/deadline startup failures, initial Loki empty ring/503; recovered |
| BENIGN_WARNING | Optional unused Grafana plugin/alert provisioning directories; ordinary cache/reprocessing and library warnings |
| OBSERVATION | Tempo replay removed a WAL block with absent metadata and later logged one tenant-poll race. Current execution evidence, all 92 product-gate provider spans and the historical CERT-01 trace were retrieved; loss of these tested traces is not demonstrated. No repair attempted. |

After the final reference gate, the stack was observed for **186.161 s** across **12**
samples spanning **183.684 s** between first and last sample. Every sample had 20 healthy
running services, API/Ollama 200, and zero unexpected restarts. Final authenticated
Knowledge and all other MCP readiness checks passed. Evidence: `stability.jsonl`,
`stability-summary.json`, `final-runtime-stability-counts.json`, `readiness-final.json`.

Protected persistent counters remained **100 / 5 / 1**, identical to baseline; real
protected side effects **0**. Normal investigation records were created as explicitly
required by the product gates. All 509 originally versioned file hashes and the frozen
HEAD remain unchanged. Only the new report and ignored local/generated evidence are
additional repository artifacts. Existing certification/remediation reports are unchanged;
the local German report remains ignored and was not added to the index by this run.

Final conclusion: **NO**. Clean rebuild and deterministic/security/CERT-01 gates pass,
but the required Real-Model gate and live reference matrix fail, with material unresolved
local execution reliability. This is not a cosmetic wording rejection. The healthy local
Docker stack is left running. Commits/pushes/external deployments: **0/0/0**.
