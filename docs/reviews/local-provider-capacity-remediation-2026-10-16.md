# Local Provider Capacity Remediation — 2026-10-16

## Result and Scope

**Finding fixed: YES. Selected policy: CPU_EMBEDDING. Ready to commit: YES.** No commit or push was performed.

Finding: **Repeated local provider / timeout failures in Real-Model E2E**, severity **MEDIUM**, confirmed cause **CO_RESIDENCY_VRAM_PRESSURE**. The RTX 3070 deployment now keeps the unchanged `qwen3.5:9b` chat model on GPU and the unchanged embedding weights on CPU. This removes persistent chat/embedding **GPU** co-residency without per-request lifecycle code, disabling retrieval, changing assignments or raising timeouts.

The complete current Real-Model gate passes **12/12 journeys, 59/59 required assertions**, on the first run, without retries. Its **97 correlated provider calls** have a maximum duration of **8.230 s** and no provider errors. Across selected-policy acceptance plus that gate, **122 chat calls** have no duration >30 s, >40 s or >=45 s; the maximum is **12.116 s**, the explicitly cold direct request. Selected-policy Ollama HTTP 500 count is **0**. Independent async work remains responsive and all 14 cleanup regressions pass.

Source of truth: [co-residency diagnosis](local-provider-vram-coresidency-diagnosis-2026-10-16.md). Historical measurements remain unchanged: direct medians **2.844 s chat-only / 9.338 s GPU co-resident / 2.856 s after embedding unload**; representative full Agent flow **20.20 / 105.11 s**. Individual historical timeouts are not retrospectively assigned an exclusive cause.

## Starting State and Safety

| Item | Recorded state |
| --- | --- |
| Repository / branch | `D:\Freelance\industrial-ai-agent`, `main` |
| HEAD | `09179245ba699425567884d6508cff40866f87ea` |
| Initial Git state | The preceding reliability and co-residency diagnosis reports were already staged; both preserved unchanged |
| Cleanup remediation | Present in source and installed Agent API; `_owned_agent_context` verified |
| Stack / readiness | 20/20 project services healthy; API `/ready` 200; authenticated Knowledge MCP initialize/tool-readiness successful |
| Ollama | 0.33.2; original container `1d5de9a37b95`, original image retained |
| Hardware | NVIDIA RTX 3070, 8192 MiB dedicated VRAM, Windows WDDM; initial usage approximately 2342 MiB; unrelated GPU consumers untouched |
| Initially loaded models | None |
| Assignments | Agent and RCA: MANUAL `local_quality` / LOCAL at all four classifications; read-only checks and gate guards confirm no change |
| Unchanged limits | SDK 45 s, retries 0, Agent/API 90 s, runtime context 4096, chat maximum output 192 |

Only local cached models were executed. No model download, cloud provider call, protected ticket, calibration or hardware operation occurred. Synthetic run records were created through the real API. Database gates used separate disposable databases on an isolated PostgreSQL container, application role `factory_app` verified `rolsuper=false`, `rolbypassrls=false`. Persistent demo data, project volumes and the model cache were preserved.

## Candidate Selection Before Production Configuration

All candidates used the same frozen synthetic request from diagnosis, UTF-8 SHA-256 `7e31e9b2c84be81113e89a3926205a07123ed78e41fc8ca93974494f971a5c3a`, model/options/tools unchanged. Successful replay responses retained 1154 input / 113 output tokens. Real workflows used the existing CONFIDENTIAL `Investigate QUALITY-09.` journey, including actual Knowledge evidence, generation and persisted results. Separate PUBLIC MCP reads measured retrieval independently.

| Candidate | Installed-version proof and measured behavior | Decision |
| --- | --- | --- |
| A — CPU embeddings | `num_gpu=0` is honored by Ollama 0.33.2: 100% CPU, `size_vram=0`, CPU model/context buffers; chat stays 100% GPU. Five warm direct calls: 3.292, 3.156, 2.998, 2.908, 3.154 s. Five complete retrieval/Agent cycles: 28.852, 27.104, 29.338, 29.776, 28.149 s; all successful. Warm query embeddings approximately .19–.25 s. | **Selected:** stable chat residency, fast embeddings, correct retrieval and acceptable host RAM; avoids recurring GPU model swaps. |
| B — `OLLAMA_MAX_LOADED_MODELS=1` | Explicitly advertised by local `ollama serve --help`; runtime observations confirm at most one GPU model loaded. Two complete cycles succeed in 45.442 / 39.855 s. Initial embedding HTTP 42.309 s includes native load 30.093 s. Planned first chat switch reaches ReadTimeout at 45.138 s; second planned call returns in 26.952 s. | Rejected: expensive swaps and poor initial timing margin compared with A. |
| C — short residency | Native embedding `keep_alive` exists, but embedding-only configuration is not exposed by current composition. Tested the supported global `OLLAMA_KEEP_ALIVE=0` alternative with actual MCP/Agent calls; models unload automatically. Two complete cycles succeed in 57.365 / 47.807 s. Direct calls: 45.174 s timeout, then 45.015 s HTTP 200. | Rejected: repeated cold execution/lifecycle costs and loss of useful chat residency. No adapter code added to implement a separate embedding-only mechanism. |

B and C were tested in temporary containers using the **same immutable Ollama image, GPU access and existing model volume**, with only the respective environment control added. The original container was preserved stopped, then restored with its original environment; both temporary containers were removed without deleting volumes. The embedding model's original GPU manifest was restored for those comparisons. Only A remains applied.

Cold server/runner effects are not presented as steady generation throughput. B's second request follows a cancelled first request and can include residual queue/cache work: runner logs show 8.436 s prompt evaluation and 2.664 s generation, not 26.952 s of decoding. C's second cold request contains approximately 6.84 s runner startup, **34.000 s prompt evaluation** and **2.953 s generation**. These rejected-policy failures remain in evidence; they are excluded only from the explicitly separate selected-policy acceptance counters, not erased or relabeled PASS.

An initial external diagnostic used an unsupported free-form documentation request under PUBLIC and received the expected neutral 404. No provider call was admitted for it. The subsequent policy comparison used the existing appropriately authorized CONFIDENTIAL journey. Production prompts, classification and harness expectations were not changed.

## Implemented Policy

The production change is configuration/bootstrap only:

- [`config/ollama/Modelfile.embedding-cpu`](../../config/ollama/Modelfile.embedding-cpu): existing embedding model plus `PARAMETER num_gpu 0`.
- [`scripts/configure-local-embedding-cpu.ps1`](../../scripts/configure-local-embedding-cpu.ps1): requires the cached model, performs no pull, applies the Modelfile, verifies the persisted parameter and releases a previous embedding instance during bootstrap.
- [Local capacity documentation](../learning/local-model-capacity.md), README and Architecture Overview explain placement, provisioning, offline restart and verification. Relevant embedding diagram labels were updated in English and local German.

The existing application embedding tag remains `qwen3-embedding:0.6b`, because current composition uses that tag. Its manifest changes from `ac6da0dfba84` to `0834d81cc588` solely for the CPU placement parameter. Generated Modelfile comparison shows unchanged weights blob `06507c7b4268...`, template and defaults, with only `PARAMETER num_gpu 0` added. Quantization stays Q8_0 and observed context stays 4096. Chat digest `6488c96fa5fa`, Q4_K_M, model assignment and context are unchanged.

The bootstrap script was executed twice; the same manifest digest confirms idempotence. It is run before client work, not per request. CPU/GPU models can remain resident simultaneously in different memory pools. No manual stop is needed between retrieval and chat. The local original embedding tag backup remains available as a rollback artifact, not an active model or alternate policy.

No `src/` or test source was modified. No environment key, Compose limit, retry, timeout, model catalog, security rule or Agent orchestration change was introduced. Ollama's global one-model and zero-keepalive alternatives are not enabled. No architectural boundary changed; a new ADR was unnecessary.

## Restart and Offline Behavior

After applying the selected policy, the original Ollama container, Knowledge MCP and Agent API were normally restarted. Knowledge restart began at approximately **14:46:12 UTC**; API readiness succeeded at **14:48:11.876 UTC**. Its initial 503/unhealthy state while Knowledge warmed is retained as a startup observation, followed by healthy recovery without another intervention. All 20 services recovered healthy, restart counters 0.

The existing cached reranker/Docling/OCR assets were used with the retained offline flags and read-only Hugging Face cache. No dependency/model download was substituted for an offline proof. Knowledge rebuilt its real clearance projections and embeddings on CPU before readiness. The placement persisted through restart automatically. Five further acceptance cycles then completed without operator model controls.

Model manifests live in the persistent Ollama cache. A fresh cache needs initial provisioning; pulling the upstream embedding tag again replaces its local placement, so documented bootstrap must be reapplied after a model update. Ordinary service/container restart does not require that step. The selected policy does not claim capacity for arbitrary additional GPU applications/models beyond the measured local profile.

## Selected-Policy Acceptance

### Frozen direct request and authorized adapter

| Measurement | Result |
| --- | --- |
| Before, direct | 2.844 s chat-only median; 9.338 s GPU co-resident median |
| Selected, before restart | Five warm direct requests, median **3.154 s**, all 200 |
| Selected, after restart | Cold **12.116 s**, followed by **3.329 / 3.359 / 3.351 / 3.371 s**; warm median **3.355 s**, all 200 |
| Cold phase separation | Runner startup 6.03–6.09 s; full prompt .854 s / 1154 tokens; generation 3.221 s / 113 tokens / 34.77 tokens/s |
| Warm phases | Cached suffix .108–.123 s; generation 3.036–3.099 s / 113 tokens / 36.14–36.89 tokens/s |
| Adapter before | Diagnosis medians: 2.857 s chat-only / 8.529 s GPU co-resident |
| Adapter selected | **4.608 / 3.335 / 3.310 s**, median **3.335 s**, valid R01 authorization, same result, no error |

Raw payloads and per-request metrics are retained. Phase logs are matched with a 50-ms timestamp tolerance for host/container logging skew; phases themselves are Ollama's measured values. Cached suffix rates do not represent full-context prefill throughput. No context/prompt/schema simplification was used.

### Five realistic post-restart cycles

Each cycle measures a direct embedding query, an authorized PUBLIC Knowledge read, then a real CONFIDENTIAL Agent request that obtains its own `QUALITY-09` documentation evidence and generates/persists the answer through the existing graph. This preserves actual retrieval-to-generation coupling rather than supplying invented evidence. No protected action is proposed or approved.

| Cycle | Embedding HTTP | Separate Knowledge read | Actual document-backed Agent | Total cycle |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1.812 s | 3.304 s | 25.517 s | 31.522 s |
| 2 | .243 s | 3.039 s | 23.686 s | 27.152 s |
| 3 | .280 s | 3.665 s | 25.499 s | 29.585 s |
| 4 | .247 s | 3.402 s | 23.474 s | 27.277 s |
| 5 | .274 s | 3.129 s | 23.454 s | 27.060 s |

Cycle 1 includes a native embedding load of **1.567 s**; later query loads are about **.001 s**, with native total inference approximately **.091–.101 s**. Its reload is recorded, not hidden as warm inference. Later cycles need no repeating GPU swaps. Actual Agent model calls are **5.439–7.052 s**. Total investigation duration includes retrieval, reranking and persistence and is not a provider-call duration.

Knowledge returns the expected Factory Overview for PUBLIC packaging queries. For the same `QUALITY-09` query, PUBLIC emits only classification 0 and excludes `doc-s04quality09procedure`; CONFIDENTIAL includes that expected document. Source, chunk ID, document ID and checksum are present. PUBLIC/CONFIDENTIAL isolation, retrieval and provenance assertions pass.

### Representative original Agent flow and concurrency

The unchanged two-step PUBLIC flow `Untersuche Station S01.` then `Prüfe den aktuellen Status von Station S05.` succeeds in **10.385 + 11.493 = 21.879 s**, compared with **20.20 s chat-only / 105.11 s GPU co-resident** previously. Its four model calls are **3.544 / 6.620 / 4.451 / 6.852 s**; one correct read-only station-overview call per run, no approvals/actions.

Two simultaneous chat HTTP requests complete in **3.261 / 6.251 s**. Chat with a concurrent CPU embedding query completes in **3.183 s**; embedding takes **.288 s**. All return successfully, with no timeout, deadlock or event-loop stall. Independent API `/health` requests during the representative Agent runs complete within **94.1 ms** maximum. Ollama's single chat slot queues the second chat; no extra parallel graph execution was introduced.

### Resources and timeout margin

Across selected acceptance and subsequent sampled operation: dedicated VRAM **1550–7963 MiB**, shared GPU memory **169–978 MiB**, host RAM available **18.38–21.37 GiB**. These include cold/idle transitions and are sampled ranges, not absolute guaranteed peaks. During steady acceptance, GPU committed memory is around **9940 MiB**, versus approximately **12400 MiB** in the diagnosed co-resident series. Windows committed/shared accounting is not physical VRAM or a tensor paging trace.

Embedding GPU allocation is **0 in every selected-policy model-residency sample**; chat remains GPU-backed. Shared GPU memory is not claimed to be zero: desktop/driver use remains. The important capacity change is removal of the embedding GPU allocation and restoration of throughput. CPU embedding RAM is acceptable on this approximately 63.85-GiB host. No unrelated GPU consumer was stopped.

Selected acceptance plus Real-Model gate: **122 chat calls** = 8 direct/concurrency + 3 adapter + 14 acceptance API provider calls + 97 product-gate provider calls. Maximum **12.116 s** including cold client wall time; counts **>30 s: 0; >40 s: 0; >=45 s: 0**. SDK timeout remains **45.0 s**. Failed B/C candidate requests are separately preserved and do not count as selected-policy acceptance.

## Complete Current Real-Model Product Gate

Command: `npm run e2e:manual -- --run-id capacity-remediation-2026-10-16-first` from `frontend`. New ignored artifacts were used; historical results were not overwritten. Every journey executed once, no resume/retry. All four assignments were checked read-only before and during the gate.

| Journey | Required assertions | Result / classification | Maximum correlated provider call |
| --- | ---: | --- | ---: |
| s04-investigation | 6/6 | PASS | 8.230 s |
| station-discovery | 4/4 | PASS | 7.170 s |
| product-history | 4/4 | PASS | 5.905 s |
| documentation | 8/8 | PASS | 6.260 s |
| clearance-boundary | 9/9 | PASS | 6.375 s |
| station-discovery-de | 4/4 | PASS | 5.890 s |
| healthy-station-de | 3/3 | PASS | 6.850 s |
| healthy-station-en | 4/4 | PASS | 7.127 s |
| s04-investigation-en | 4/4 | PASS | 8.121 s |
| product-centric-en | 3/3 | PASS | 5.600 s |
| clearance-boundary-en | 6/6 | PASS | 5.586 s |
| restricted-boundary | 4/4 | PASS | 6.078 s |

**12/12 PASS; 59/59 required assertions.** All 62 recorded steps pass their plans, including three expected ATTENTION observations. The discovery journey also exercises its declared inventory smoke, accounting for additional provider calls. Local Tempo correlation deduplicates run/span IDs and recovers **97 `llm.call` spans**, maximum **8.229814 s**, no provider errors. Browser persisted-result assertions and provider traces agree. Counts: **PRODUCT_DEFECT 0, MODEL_VARIANCE 0, HARNESS_ERROR 0, SECURITY_DEFECT 0, BLOCKED_BY_PROVIDER 0, INFRASTRUCTURE_ERROR 0**.

There is no selected-policy `llm_provider_unavailable`, `agent_execution_timeout` or Ollama HTTP 500 after SDK timeout. Expected authorization denials are not defects. This gate does not certify physical side effects or HITL execution; those remain deliberately unexecuted here.

## Deterministic Gates, Runtime and Integrity

| Gate | Result |
| --- | --- |
| Full backend, `pytest tests -q -ra` | **2058 passed, 6 skipped, 0 failed** |
| Repository INTEGRATION | **279 passed, 5 skipped, 0 failed** |
| Exact repository FAST | **PASS:** 1764 unit passed, 1 skipped; 328 frontend passed; Ruff/format/secret scan pass |
| Safe browser fixtures, `--retries=0` | **140/140 passed**, 0 failed/skipped/flaky; all seven registered files |
| Provider cleanup | **14 passed**; 350/750-ms residual heartbeat maxima **32/47 ms**, active counts return to 0 |
| R01 / R05 / C02 | **29 / 19 / 19 passed**; model egress 25 passed; routing/assignments covered by full suites and live read-only checks |
| Compose configuration | `docker compose config --quiet` passes |
| Operational configuration | PowerShell parser passes; cached Modelfile creation, idempotence and real restart verified |
| Ruff / format | PASS; 262 Python files already formatted; no Python source change |
| Secret scan / `git diff --check` | PASS |

Five backend/integration skips are opt-in KDEP clean-image/isolated deployment cases, not silently counted as passed. The sixth backend skip is Windows symlink creation. Actual cached offline Knowledge restart/retrieval was exercised separately. Existing deprecation warnings are retained.

The first backend attempt had **2056 passed, 2 failed, 6 skipped** because the external `PCLEAN_EVIDENCE_DIR` had not been created. Creating that evidence directory fixed only verifier setup; the full rerun above is green and the first log/XML remain preserved. Initial disposable seeding required the explicit host `FACTORY_DATA_ROOT`; the failed setup log is retained. Two JUnit files affected by Windows `PYTEST_ADDOPTS` path quoting were moved from their generated workspace directory to external evidence. No product/test source was changed to obtain green gates.

After all runtime tests, the disposable PostgreSQL container/tmpfs was removed without touching persistent volumes. Stack observation spans **184.689 s**, with all samples **20/20 healthy**, all restart counters **0**, API and Ollama readiness **200**. Relevant API, Knowledge and Ollama logs were retained. Selected-period Ollama logs contain **0 HTTP 500, 0 OOM/CUDA/runner-crash errors**. No repeated unexpected load/crash loop or persistent provider/API error remains. Normal idle expiry and deliberate candidate/startup loads are distinguished from failures. Measurement workers completed and the healthy stack remains running.

Hash comparison finds only the intended existing tracked-file changes, **README.md and docs/architecture/overview.md**; `src/`, tests, model catalogs, Compose and historical reports match baseline. New remediation files are the Modelfile, bootstrap script, capacity learning document and this report; relevant local German versions are present and Git-ignored. Existing staged historical reports remain unchanged. No commits, pushes or external deployments; external model calls **0**, real protected side effects **0**.

## Evidence and Final Conclusion

External evidence: `D:\Freelance\local-provider-capacity-remediation-evidence-2026-10-16`. It retains initial hashes/status, candidate logs/telemetry, original/selected Modelfiles, restart readiness, five-cycle acceptance, raw adapter payloads, API and product-gate Tempo traces, exact gate logs/XML, browser inventory/results, final runtime logs and stability samples. `capacity-summary.json` and `final-protocol.json` provide machine-readable totals. Real-model artifacts remain under ignored `evals/results/browser-e2e/capacity-remediation-2026-10-16-first/`.

**The selected CPU_EMBEDDING policy satisfies the operating guarantee on the tested RTX 3070 profile.** Retrieval and provenance remain correct, GPU chat retains ample timeout margin, all twelve journeys pass, and no authorization/lifecycle boundary was changed. The confirmed capacity finding is fixed; no further remediation or overall review was started.
