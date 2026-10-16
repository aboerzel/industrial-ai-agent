# Local Provider Reliability Diagnosis — 2026-10-16

## Conclusion and Scope

**Diagnostic result: INCONCLUSIVE concerning the cause of the original throughput degradation. The first failing timeout boundaries are established with high confidence. No remediation was implemented or selected for the provider finding.**

Finding: **Repeated local provider / timeout failures in Real-Model E2E**, severity **MEDIUM**. Source changes: **0**. External model calls: **0**. Real protected side effects: **0**.

The original failures were not six received Ollama HTTP-500 responses. All six failing provider spans record **`APITimeoutError`**, without a received provider HTTP status. Four runs failed at the adapter's 45-second SDK/read boundary. Two first exceeded the application's approximately 90-second run budget while another synchronous SDK call was still executing; that call subsequently reached its own 45-second timeout. Ollama logged HTTP 500 as those connections were cancelled. This establishes timeout ownership and ordering, not why the earlier local executions were so slow.

The current, unchanged single-chat-model controls do not reproduce that degradation. Direct HTTP, the authorized adapter, and the current full application/graph all complete. The original co-resident chat/embedding GPU workload was **not recreated**, because this task permits only `local_quality`. GPU capacity/driver/shared-memory pressure is a credible leading hypothesis, not a demonstrated root cause. Increasing timeouts, changing models or reducing prompts would therefore be premature.

Sources: [comprehensive review](final-comprehensive-verification-and-review-2026-10-16-run-120936.md), [cleanup remediation](provider-cleanup-remediation-2026-10-16.md), current source/configuration, original persisted records and local Tempo/Ollama evidence. All historical artifacts remain unchanged.

## 1. Frozen Baseline

| Item | Observed |
| --- | --- |
| Repository | `D:\Freelance\industrial-ai-agent` |
| Branch / HEAD | `main`, `09179245ba699425567884d6508cff40866f87ea`, already one commit ahead of origin before diagnosis |
| Initial working tree | Clean |
| Cleanup fix in current source | **Present**: `_owned_agent_context` and `_run_owned_provider_lifecycle` cover run/start/resume |
| Cleanup fix in running API image | **Absent**: image `sha256:f008bb2387088f645960b83af37dff8b212218bebcd56880290ff2c44ac17151` predates the fix; no rebuild/deployment performed |
| Project services | 20/20 Docker healthy; no restarts; final API `/health`, `/ready`, frontend all HTTP 200 |
| Ollama | Existing container `1d5de9a37b95a080b775b2cd66ce4e5d561aec02d6aa8ef16e0f6337114eb370`, unchanged since 05:17:48 UTC; version 0.33.2 |
| Ollama image | `sha256:020e4134285e2ef4d8fd801234176de3b4faadc992a3eb06c8e66a2f9d4c4ba2` |
| Model | `local_quality` → `qwen3.5:9b`, digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, Q4_K_M |
| Endpoint | Host `http://localhost:11434/v1`; Docker catalog uses the local host bridge, not an external provider |
| Assignment | Agent and RCA: MANUAL `local_quality` at PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED; LOCAL; no fallback |
| Loaded model at initial snapshot | None; first direct request naturally measured a cold load |
| Actual loaded context | 4096; model metadata advertises 262144 maximum, which is not the allocated runtime window |
| Application request options | Temperature 0, maximum output 192, reasoning effort `none`, SDK retries 0; unchanged |

Configuration and assignments were read without exposing credentials. Full-agent controls use **current host source**, actual local authenticated Factory/MCP services, actual persistent assignment reads and the actual FastAPI Demo Session/context path. Diagnostic run records use an isolated in-memory store, so persistent demo runs/tickets are not altered. They exercise the graph/API path, not a new browser certification or a deployed-image certification. No protected action tool was executed.

## 2. Original Failed Journeys: Three Distinct Results

Times below are UTC. Persisted durations include orchestration and cleanup; they are not individual model-call durations. Six failed runs belong to five journeys.

| Journey | Runner label | Persisted product result / run prefix | Persisted duration | Ollama server result |
| --- | --- | --- | ---: | --- |
| Healthy station DE | BLOCKED_BY_PROVIDER | `87b54ac1`: failed, `llm_provider_unavailable`, PROVIDER_CONNECTION; reference request targets **S05** | 45.190 s | 500 at 10:46:14.743; 45.046596 s |
| S04 investigation EN | HARNESS_ERROR | `b9135609`: failed, provider unavailable; `93155a76`: failed, `agent_execution_timeout`, ORCHESTRATION | 61.419 / 97.605 s | 500 at 10:48:19.765 / 10:49:57.492; 45.046233 / 45.044136 s |
| Product-centric EN | HARNESS_ERROR | `4b63c61a`: failed, provider unavailable, PROVIDER_CONNECTION | 45.189 s | 500 at 10:51:13.916; 45.003958 s |
| Clearance boundary EN | BLOCKED_BY_PROVIDER | `3abccb73`: failed, provider unavailable, PROVIDER_CONNECTION | 45.147 s | 500 at 10:52:30.244; 45.026665 s |
| Restricted information path | MODEL_VARIANCE | `8f89f3b1`: failed, `agent_execution_timeout`, ORCHESTRATION | 125.572 s | 500 at 10:55:19.594; 45.042736 s |

`HARNESS_ERROR` includes downstream missing-reference/reload prerequisites after a real product failure. `MODEL_VARIANCE` is incorrect for the restricted timeout: it is a runner classification problem, not evidence of semantic model variation or the first failing boundary. No unauthorized disclosure or protected side effect was found.

## 3. Timestamped First-Boundary Analysis

Original local Tempo searches recovered 15 trace results; spans were deduplicated and filtered by exact `run.id`. They retain model selection/egress decisions, MCP execution, provider phases, request metadata and **`provider.error_type=APITimeoutError`**. Trace contents and log timestamps were compared, not concatenated log-file order. Docker stdout and stderr are separate streams and were explicitly sorted for analysis.

| Run | Accepted / persisted create | Relevant execution before failure | First established failure | Terminal persistence |
| --- | --- | --- | --- | --- |
| `87b54ac1` | 10:45:29.566 | Auth/context PUBLIC; model ALLOW; bound station overview succeeds; first LLM call waits 45.064 s | SDK/read timeout before the 10:46:14.743 Ollama completion log | 10:46:14.755 |
| `b9135609` | 10:47:18.364 | CONFIDENTIAL; initial evidence/tool work; LLM 1.547 s; further MCP evidence 14.676 s; next LLM 45.050 s | SDK/read timeout before 10:48:19.765 Ollama log | 10:48:19.783 |
| `93155a76` | 10:48:19.890 | LLM 7.497 s and 31.856 s; evidence retrieval 13.070 s; third LLM starts about 10:49:12.44 | Application budget at approximately **10:49:49.9**, while SDK work remains active; SDK reaches 45.050 s later, just before Ollama 500 at 10:49:57.492 | 10:49:57.495 |
| `4b63c61a` | 10:50:28.741 | INTERNAL; product history succeeds; first LLM 45.023 s | SDK/read timeout before 10:51:13.916 Ollama log | 10:51:13.930 |
| `3abccb73` | 10:51:45.111 | INTERNAL; complete station inventory succeeds; first LLM 45.038 s | SDK/read timeout before 10:52:30.244 Ollama log | 10:52:30.258 |
| `8f89f3b1` | 10:53:14.036 | RESTRICTED; LLM 7.201, 30.193, 37.367 s; evidence retrieval 5.619 s; structured call starts 10:54:34.551 | Application budget at approximately **10:54:44.0**; structured SDK call later reaches 45.042 s, just before Ollama 500 at 10:55:19.594 | 10:55:19.608 |

The approximately 90-second instants are calculated from the stored start and configured budget, not invented cancellation trace events. The terminal timeout code confirms the application timeout path; the precise cancellation instruction timestamp is not retained. The four other failures have provider-timeout spans before the API budget could expire. Their provider span completion precedes the matching Ollama completion log by milliseconds; none records a received HTTP-500 status or `APIStatusError`.

The original synchronous cleanup defect explains why the two API-timeout responses could finish after 97.6/125.6 seconds while the SDK worker drained. Its fix preserves drain ownership but removes the event-loop stall; it does not shorten provider execution. A 90-second application budget is consequently not a promise of a hard 90-second HTTP response when mandatory drain remains outstanding.

**45_SECOND_OWNER: `_SDK_TIMEOUT_SECONDS = 45.0` in `infrastructure/llm/openai_compatible.py`.** For the two aggregate timeouts, the first boundary is instead the application budget; the later 45-second SDK signature is secondary. No separate configured Ollama generation timeout of 45 seconds was found.

## 4. Timeout Inventory

| Layer | Timeout | Source / applies to |
| --- | --- | --- |
| Provider SDK / effective HTTPX | 45 s for connect/read/write/pool; retries 0 | `openai_compatible.py:57`, SDK construction; observed transport extensions agree |
| Optional provider operation budget | `min(45, request.timeout_seconds)`; unset for these graph calls | Same adapter; RCA deadline transport is a separate path |
| Agent/API execution | 90 s | `api/app.py:160`, `asyncio.wait_for` around run/start/resume; includes all sequential model/tool work |
| LangGraph | No separate wall-clock timeout found | Bounded steps/tool count and recursion limits are termination controls, not time budgets |
| MCP HTTP transport | Connect/write/pool 30 s; SSE read 300 s | Installed `create_mcp_http_client` defaults, used by `factory_mcp_client.py`; no matching failed MCP boundary here |
| Reverse proxy | Connect 5 s; send/read 180 s | `frontend/nginx.conf`; did not cause these 45-second failures |
| Browser API fetch | No separate run wall-clock timer | `frontend/js/api.js`; AbortController follows identity/context invalidation; 60-second Object URL timer is unrelated |
| Preferred journey observer | Busy start 10 s; terminal UI 100 s | `frontend/scripts/run-e2e-journey.mjs:824,834`; can expire before the old 125-second terminal persistence |
| Ollama load stall / keep-alive | Default 5 min / 5 min; no override found | Local `ollama serve --help`, inspected environment; model loading/lifetime, not a 45-second generation limit |
| Tool/JSON-schema generation | No distinct schema timeout | Uses the same 45-second provider boundary |

## 5. Provider and Resource Evidence

Original Ollama logs show cancellation/release around the six failures and no corroborating out-of-memory, CUDA failure, runner crash, allocation failure, context overflow or invalid-schema error. The original SDK trace type identifies a read/deadline failure, not a delivered server-error payload. Error bodies cannot be reconstructed when no response was received.

GPU: **NVIDIA GeForce RTX 3070, 8192 MiB**. Original `ollama ps` showed `qwen3.5:9b` **5.5 GB** and `qwen3-embedding:0.6b` **2.4 GB**, both “100% GPU”, 4096 context. Original Ollama resident host memory was about 9.93 GiB within a 31.27-GiB Docker VM. This is evidence of co-residency, not an original VRAM-pressure measurement. “100% GPU” does not establish sufficient memory.

Current sampling measured approximately **7560–7850 MiB dedicated VRAM** while only the chat model was loaded, with utilization spanning 15–100% during the sampled interval. The initial unloaded baseline was approximately 1.88–2.12 GiB VRAM and 44–46% GPU utilization, showing other GPU activity. One Windows adapter-memory sample recorded about 8.08 GB dedicated and 0.885 GB shared usage; per-process NVML memory is unavailable under this WDDM setup. These current samples cannot establish the exact resource state at the original failures.

The host has approximately 63.84 GiB visible RAM and initially approximately 24.91 GiB available. Ollama and API container-specific memory/swap limits are 0 (no per-container cap); the Docker VM still has its own aggregate limit. No resource limits or GPU settings were changed. Current load reports 34/34 layers offloaded, a 4096 runtime context and approximately 5.49 GB model VRAM. CPU fallback was not demonstrated.

Original successful generation near the failures ran around **4.36–5.40 generated tokens/s**. Current comparable generation is substantially faster. Co-resident models, shared-memory pressure, cache effects and other GPU activity are plausible contributors. There is no paired original/current GPU-memory experiment proving which one caused the slowdown.

## 6. Request Profiles and Correlations

Original failed requests are modest, varied shapes, not a single schema/tool signature:

| Run | Phase | Canonical payload bytes | Messages | Tool definitions | Structured schema |
| --- | --- | ---: | ---: | ---: | --- |
| `87b54ac1` | Tool decision after station evidence | 4,985 | 4 | 2 | No |
| `b9135609` | Tool decision after further evidence | 7,922 | 6 | 3 | No |
| `93155a76` | Tool decision | 11,919 | 7 | 12 | No |
| `4b63c61a` | Product-history tool decision | 4,579 | 4 | 2 | No |
| `3abccb73` | Station-inventory tool decision | 6,813 | 4 | 8 | No |
| `8f89f3b1` | Structured response | 9,000 | 2 | 0 | Yes; hash `4a4351dafa383218e869cfcbad8800b6a98b8b428fcfda7cadb13dfcbdc9073b` |

Successful calls in those same original traces include **12,293 bytes / 2,867 input tokens**, larger than failed requests. Failed-request token totals are not returned; nearby server prompt lengths and `truncated=0` provide no context-overflow evidence. An excessive-context hard limit is not demonstrated.

Current replay P3: four messages, 3,349 content characters, two tools, 734 schema characters, 1,101 input tokens. P4: four messages, 3,530 content characters, two tools, 971 schema characters, one prior turn, 1,154 input tokens. Current real structured-response replay: two messages, 3,123 content characters, a 2,563-character response schema, zero tools, 700 input tokens. All use `local_quality`, PUBLIC synthetic evidence, German, temperature 0, output cap 192 and reasoning effort `none`. Body JSON, hashes, evidence/tool messages, reference-bearing tool data and provider token counts are retained locally; character estimates are labeled estimates, not token counts.

P4 is a faithful **representative current request** for the historical canonical S05 action, not a claim to recover the exact original uncaptured provider body. Direct and adapter replay use the same captured body semantics. Original references/evidence counts and original tool-schema character lengths were not instrumented and cannot be invented from byte totals.

Request-size correlation: **INCONCLUSIVE**; larger successes disprove a simple deterministic size-limit explanation. Exclusive tool/schema correlation: **NO**; failures include ordinary tool decisions and structured output, and both shapes succeed now. Language and clearance correlations: **INCONCLUSIVE**. The retained 43-run corpus has failures in DE and EN and all four classification levels; it is not a randomized comparison. PUBLIC: 1/13 failed; INTERNAL: 2/9; CONFIDENTIAL: 2/13; RESTRICTED: 1/8. Language breakdown: DE 1/25, EN 5/18, confounded by journey, execution order and resource state. All levels resolve to the identical model/provider; no authorization or alternate-route defect follows from these rates.

## 7. Controlled Local Executions

All results are retained; failures were not repeated until passing. All production request options remained unchanged.

| Control | Direct Ollama | Authorized provider adapter |
| --- | --- | --- |
| P1 tiny plain, naturally cold | HTTP 200, **25.726 s**, 16 input / 2 output tokens | Not required as a separate cold adapter load |
| Same P1 warm | HTTP 200, **0.400 s** | — |
| P2 small JSON schema | HTTP 200, **0.800 s** | Success, **1.596 s**, same 21/7 tokens |
| P2 actual application tool definition | HTTP 200, **1.466 s**, station-overview tool call | Success, **1.275 s**, 311/31 tokens |
| P3 successful agent shape | HTTP 200, **4.224 s** | Success, **4.926 s** |
| P4 historical failing-action shape | HTTP 200, **3.744 s** | Success, **3.656 s** |
| P4 actual structured-output shape | HTTP 200, **5.727 s** | Success, **5.589 s** |

Here “success” in the direct/adapter controls means transport/adapter completion. The actual P4 structured replay reaches the unchanged **192-token cap**, returns `finish_reason=length` and incomplete JSON. Small P2 JSON is valid; P2 tool output contains the expected `get_station_overview` call. Thus the larger replay does **not** certify successful schema-conforming generation. The full graph still reaches its existing normal final-result/fallback path. This output-budget observation does not explain the five original non-structured provider-call timeouts and is not promoted to a provider-incompatibility root cause or a remediation in this task.

Cold logs report llama-server startup **23.88–23.94 s**, with about 0.289 s prompt/generation work for P1; remaining elapsed time is loading/setup/transport overhead. Non-streaming requests do not expose a separate first-token time. Cold/warm latency correlation is **YES**, but no cold failure occurred and the original warm failures remain unexplained. No unload, configuration change or restart was used to manufacture a cold state.

Full current FastAPI/agent controls use server-managed `demo-public` sessions and trusted prior-context resolution. The known-successful product-history path has three required turns; the historical healthy path has two required turns, including the **S05** action actually found in the persisted original failure. Optional product clicks are excluded from the provider reliability comparison.

| Sequential path | Preserved first execution | Subsequent controlled sample | Model calls per execution | Total execution durations |
| --- | --- | --- | ---: | --- |
| Known-successful product history | Success, 31.156 s | **3/3 success** | 7 | 29.996 / 29.420 / 30.782 s |
| Historical healthy DE → S05 | Success, 20.685 s | **3/3 success** | 4 | 20.035 / 20.649 / 25.730 s |
| Additional neighboring S01 action | Success, 20.359 s | **3/3 success** | 4 | 19.808 / 19.432 / 20.381 s |

In total: **28 current API runs / 60 model calls, all terminal success**. Tool trajectories and each model-call duration are preserved in `events.jsonl` and `summary.json`; all actions are read-only Factory product/station evidence. This does not retroactively turn the original five failed journeys into PASS or certify the full twelve-journey browser gate.

Concurrency was tested **after** sequential sampling: one P4 request completes in 3.666 s; two simultaneous direct requests both return HTTP 200 in **3.558 / 6.809 s**. Two calls sharing one actual authorized adapter succeed in **4.062 / 7.379 s**, peak active count **2**, final count **0**, one SDK/HTTPX pair, final close true. The longer second request is consistent with queueing; no failure or leak was observed. A following tiny request succeeds in **0.574 s**. This small test does not reproduce the original chat-plus-embedding co-residency.

No fresh spontaneous provider failure was available for a new poisoning/restart experiment. Original evidence nevertheless shows recovery without restart: immediately after `3abccb73` failed, run `5ebe874c` began at 10:52:30.519 and succeeded at 10:52:59.954; its provider calls returned 200 in 8.247 and 21.036 s. Permanent provider poisoning is therefore not supported. Ollama restart control: **NOT_TESTED**, because the permitted sequential/concurrent requests were healthy and a restart would add no failure-recovery comparison.

## 8. Diagnostic Setup Events and Limits

The initial external direct-service trial did not apply the API's trusted prior-context classification to a follow-up. Its follow-up was therefore not a valid application-level comparison. It was stopped once identified; its results remain separate, excluded from repeatability totals. Its deliberate process termination at about 12:07:01 caused a **789-ms Ollama HTTP 500**, followed by explicit task cancellation/release. That is **EXPECTED_DIAGNOSTIC_CANCELLATION**, not an additional spontaneous provider defect. Corrected controls use the actual Demo Session/API path. Early setup failures due to missing bearer configuration/session-mutation marker also remain preserved and made no model calls.

Unbounded historic Docker log retrieval/filtering did not yield a usable current interval. The diagnosis retained the original review logs and explicitly captured a bounded 12,000-line Docker tail, then sorted/filter-selected timestamps. No empty filtered capture was interpreted as proof of no errors. Original completion logs, current intentional cancellation and successful controls are all accounted for.

The allowed single-model experiment cannot directly adjudicate original multi-model GPU pressure. No model settings, assignments, timeout/retry values, production schemas/prompts, harness expectations, Docker limits or product/provider source were changed. Temporary passive instrumentation records local metadata and captures synthetic request bodies; its destination/model guard permits only the existing local endpoint and `qwen3.5:9b`. It does not weaken `ModelEgressAuthorization`.

## 9. Timeout Semantics, Regression and Integrity

**43 focused tests passed**: 14 provider-cleanup tests plus 29 R01 guards. They prove safe cancellation/timeout drain, no terminal overwrite, multiple active-call accounting, bounded cleanup capacity, ownership under repeated cancellation and authorization before SDK/transport. Cancellation regressions retain approximately **32 ms** maximum heartbeat gaps at 350/750-ms residual work.

Current real-provider API work retained one stable terminal record per run, zero leaked provider calls and prompt independent health responses: maximum sampled health latency **3.86 ms**. The largest real-run heartbeat gap was **164 ms** during the initial API workload, without a provider drain in progress; other samples and the focused cancellation tests do not show a delay tracking the 350/750-ms provider remainder. This observation is retained, not relabeled a provider cleanup failure. A fresh real-provider timeout did not occur, so current real-timeout semantics are supported by deterministic regression and unchanged historical terminal records, not an invented new reproduction.

Final source/hash comparison covers all initially tracked files. Expected additions are only this new English report and its ignored German counterpart. Historical reports and original journey artifacts remain unchanged. Git whitespace check passes; no full suite was necessary for a documentation-only diagnostic result. Current stack remains running; no deployment was performed, and the existing deployed API image remains older than the source cleanup fix.

## 10. Primary Classification and Next Step

**Primary classification: INCONCLUSIVE. Confidence: MEDIUM overall; HIGH for timeout ownership/first boundary, LOW for the underlying original throughput-degradation cause.**

Established: the client/app time budgets expired while local generation was still executing; four SDK deadlines and two aggregate API deadlines are the first evidenced failures. Ollama's six later 500 completion entries do not establish an independent server crash or structured-output incompatibility. The preferred runner also mislabeled a persisted timeout as MODEL_VARIANCE and lost downstream prerequisites after real product failures.

Unresolved: why the original warm model ran several times slower, and whether co-resident model memory, shared GPU memory/cache behavior or other contention caused that degradation. Current single-model success is insufficient to choose LOCAL_PROVIDER_DEFECT, LOCAL_PROVIDER_CAPACITY or TIMEOUT_CONFIGURATION_MISMATCH as a proven root cause. Different timeout scopes alone are not proof that their values are wrong.

**Recommended remediation: none selected for the provider finding yet.** The next useful task is a separately scoped diagnostic comparison of the original co-resident workload with simultaneous dedicated/shared VRAM and generation-throughput measurement, if use of that additional existing local embedding workload is explicitly allowed. Do not increase timeouts, add retries or alter model settings based on this report. A separate runner-classification correction is supported for known timeout evidence; changing its success expectations is not supported.

| Required disposition | Result |
| --- | --- |
| Product code change recommended | UNDETERMINED |
| Ollama/config change recommended | UNDETERMINED |
| Harness change recommended | YES, timeout/error classification and correlation only; no expectation change selected |
| Ready for provider remediation task | **NO**; underlying slowdown needs an additional controlled diagnosis |
| Historical reports modified | NO |
| Source changes / external model calls / real protected side effects | **0 / 0 / 0** |
| Commits / pushes / deployments | **0 / 0 / 0** |

Evidence root: `D:\Freelance\local-provider-diagnosis-2026-10-16`. Key artifacts: initial/final hashes and assignments; `original-journeys.json`, `original-timelines.json`, `original-records-readonly.json`, `original-traces.json`, `original-span-summary.json`; `events.jsonl`, `payloads/`, `summary.json`, `resources.jsonl`, sorted original/current Ollama logs, cold/warm and controlled-run logs, `safety.xml`, readiness and integrity results. Sensitive credentials/cookies are not included in this report.
