# Local Provider VRAM / Co-Residency Diagnosis — 2026-10-16

## Result

**Primary classification: CO_RESIDENCY_VRAM_PRESSURE.** Finding: **Repeated local provider / timeout failures in Real-Model E2E**, severity **MEDIUM**. **Diagnostic only; no remediation implemented.**

Keeping the historical embedding model resident materially slows the same chat request on this RTX 3070 workstation, even without simultaneous embedding inference. Direct Ollama median latency increases from **2.844 s to 9.338 s**, and returns to **2.856 s** after embedding unload. Generation falls from approximately **43 tokens/s to 12–14 tokens/s**. The authorized provider adapter reproduces this reversible difference. The actual rebuilt API completes the same two-step journey in **20.20 s versus 105.11 s** of summed request time; both journeys succeed, with individual co-resident model calls reaching **39.03/40.22 s**.

Confidence is **HIGH that co-residency materially causes the measured slowdown**, and **MEDIUM that this accounts for the exact historical failures**. The same historical models and resource-constrained GPU state were recreated, but original per-request memory telemetry is unavailable. Windows GPU committed/shared memory increases with residency; no CPU layer offload or unintended model eviction is observed. Exact driver paging/fault events were not instrumented. This report establishes a credible capacity cause below the application layer, not proof that every historical timeout had one exclusive cause. The MEDIUM finding remains unresolved pending separate remediation and a complete product-gate rerun.

Sources: [comprehensive review](final-comprehensive-verification-and-review-2026-10-16-run-120936.md), [previous diagnosis](local-provider-reliability-diagnosis-2026-10-16.md), [cleanup remediation](provider-cleanup-remediation-2026-10-16.md), current source/configuration, retained local logs, resource samples and Tempo traces. No external research or models were used.

## Baseline and Runtime Alignment

| Item | Evidence |
| --- | --- |
| Repository / branch | `D:\Freelance\industrial-ai-agent`, `main` |
| HEAD | `09179245ba699425567884d6508cff40866f87ea` — `fix(runtime): move provider cleanup off the async event loop` |
| Initial status | Already staged: `A  docs/reviews/local-provider-reliability-diagnosis-2026-10-16.md`; preserved unchanged |
| Cleanup in source | Present in `_owned_agent_context` / `_run_owned_provider_lifecycle` |
| Alignment | Rebuilt **only agent-api**, using existing Compose and retained local-only override; recreated with `--no-deps` |
| Previous API image | `sha256:f008bb2387088f645960b83af37dff8b212218bebcd56880290ff2c44ac17151` |
| New API image | `sha256:7e91aeebe47417bfdaaec5619277319b3b179e29bf0c685e15f892143b4cd0c5` |
| Runtime fix proof | Installed container source contains `_owned_agent_context`; introspection returns `True` |
| Readiness | API `/ready` 200; all 20 project services Docker healthy; all restart counters 0 |
| Other containers | Identities/images unchanged, including Ollama; no Ollama restart or rebuild |
| Ollama | 0.33.2; existing container `1d5de9a37b95`, local OpenAI-compatible endpoint `http://127.0.0.1:11434/v1` |
| Assignment | Agent and RCA: MANUAL `local_quality`, LOCAL, at PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED; unchanged; no fallback |
| Fixed limits | SDK 45 s, retries 0; Agent/API 90 s; context 4096; output maximum 192; temperature 0; reasoning effort `none` |
| Docker capacity | VM approximately 31.27 GiB; API/Ollama per-container memory and swap limits 0; unchanged |

Build command: `docker compose -f compose.yaml -f D:\Freelance\verification-evidence-2026-10-16-120936\local-only.compose.json build agent-api`; normal recreation used `up -d --no-deps --force-recreate agent-api`. This was explicitly requested local runtime alignment, not remediation of provider reliability. No image/configuration change was made to any other service.

## Historical Models and Hardware

| Role | Exact model | Digest prefix | Quantization | Reported resident size | Runtime context |
| --- | --- | --- | --- | ---: | ---: |
| Chat, `local_quality` | `qwen3.5:9b` | `6488c96fa5fa` | Q4_K_M | 5,490,081,790 bytes | 4096 |
| Embedding | `qwen3-embedding:0.6b` | `ac6da0dfba84` | Q8_0 | 2,370,652,077 bytes | 4096 |

Original `ollama-models-during-failures.txt` records **both models simultaneously**, as 5.5/2.4 decimal GB and “100% GPU.” This is historical evidence, not an inference from current configuration. Current model digests match it. Chat metadata advertises 262144 maximum context and embedding metadata 32768; neither is the allocated runtime context.

The original Knowledge logs explicitly record RapidOCR using **CPU**. Compose sets `KNOWLEDGE_MCP_RERANKER_DEVICE=cpu` for `BAAI/bge-reranker-v2-m3`. There is no evidence of a third resident Ollama model or a historical GPU reranker/OCR workload in these artifacts.

GPU is **NVIDIA GeForce RTX 3070, 8192 MiB dedicated VRAM**, driver 617.42, Windows WDDM. Initial unloaded usage was about **1619 MiB**, GPU utilization 33%; another nearby baseline measured 1671 MiB / 46%. Host visible RAM is approximately **63.85 GiB**; approximately 23 GiB was initially available. Other GPU consumers were left running: DWM, Brave, Fork, Edge/WebViews, IDE, desktop/overlay applications. One co-resident snapshot attributes approximately 6.18 GiB dedicated and 770 MiB shared to a VM worker GPU allocation, alongside roughly 450 MiB Fork, 406 MiB Brave and 525 MiB DWM dedicated usage. Counters are snapshots, not historical attribution of individual allocations.

## Fixed Request and Measurement Method

The representative request is the previously retained **synthetic S05 reference-read request shape**, `P4-historical-failure-shape.json`; the original failed wire body was not retained. The frozen UTF-8 file SHA-256 is **`7e31e9b2c84be81113e89a3926205a07123ed78e41fc8ca93974494f971a5c3a`**. It has four messages, 3530 content characters, two tool definitions with 971 serialized schema characters, no response schema, German language and PUBLIC synthetic evidence. Every authoritative direct/adapter success reports **1154 input / 113 output tokens**. All nine captured adapter bodies are canonically identical to this frozen body and to one another. No production prompt, tool schema, model option or expectation was changed.

The tiny control is the fixed `Reply with OK.` request, with 16 input / 2 output tokens and otherwise the same chat options. B2 uses one synthetic supported embedding query of 13 tokens, starting approximately 200 ms after chat submission; no load flood is used. Authorization is checked before local embedding transport. Adapter controls retain actual `ModelEgressAuthorization` through `EgressCheckedLLMClient` and the production client.

Direct controls use the same local OpenAI-compatible endpoint, HTTPX read timeout **45 s**, no proxies, redirects or retries. GPU dedicated memory/utilization, memory-controller utilization and `/api/ps` are sampled approximately every **0.5 s**; host RAM and Linux process RSS approximately every **3 s**. Windows adapter shared/committed memory is sampled approximately every **1 s**, with occasional scheduler gaps. Residency is checked before and after requests. Reported peaks are sampled peaks, not guaranteed absolute maxima.

OpenAI responses expose usage counts, not native `load_duration`/`eval_duration`. Prompt/generation times and rates below come from timestamp-correlated Ollama runner logs. Embedding native responses supply their actual load/total durations. Warm prompt caching evaluates **four remaining tokens**, not all 1154 input tokens; prompt rates describe that cached suffix. Cold evaluation separately processes all 1154 tokens. Overlapping requests retain task-level raw logs; no ambiguous per-request concurrent phase attribution is claimed.

**Preserved measurement correction:** an initial external diagnostic loader used the Windows default encoding for the UTF-8 artifact. Four extra characters / nine extra input tokens resulted from misdecoded umlauts. Its internally identical A/B/C controls already showed 3.188 / 13.732 / 3.185 s medians, one client read timeout at 45.171 s, and a subsequent Ollama 500 at 12:52:35.804 UTC after the abort. Adapter controls reached 40.118 s. These are retained as **preliminary, different-input evidence**, not pooled into the authoritative counts below. The entire direct matrix and nine adapter controls were explicitly repeated with UTF-8 decoding. This corrected only the new external diagnostic loader; no repository harness or product code changed. An earlier console Unicode error occurred before any chat request and is retained separately. The actual API journey used correct Unicode from the outset and required no repeat. No failure was automatically retried or erased.

## Direct Ollama Matrix — Authoritative UTF-8 Series

All durations are seconds, in execution order. A was warmed once; B contains a resident but idle embedding model; C follows normal `ollama stop qwen3-embedding:0.6b`. Both models were verified resident throughout B/B2. No service restart was used.

| Scenario | Sequential durations | Min / median / max | HTTP 200 | >30 s / >40 s / 45 s timeout |
| --- | --- | --- | --- | --- |
| A: chat only | 2.858, 2.839, 2.820, 2.899, 2.844 | 2.820 / 2.844 / 2.899 | 5/5 | 0 / 0 / 0 |
| B: chat + idle embedding | 10.082, 9.252, 9.819, 9.031, 9.338 | 9.031 / 9.338 / 10.082 | 5/5 | 0 / 0 / 0 |
| C: after embedding unload | 5.647, 3.064, 2.856, 2.752, 2.733 | 2.733 / 2.856 / 5.647 | 5/5 | 0 / 0 / 0 |
| B2: concurrent embedding | 11.249, 13.223, 14.358 | 11.249 / 13.223 / 14.358 | 3/3 | 0 / 0 / 0 |

The small-sample maximum is reported instead of an unjustified population p95. The UTF-8 representative request does **not** itself approach 45 s in this series. Tiny A/B/C controls are **0.415 / 0.544 / 0.454 s**, all 200; a tiny health-like prompt alone would miss the generation throughput problem.

| Scenario | Prompt evaluation durations | Generation durations | Ollama generation tokens/s |
| --- | --- | --- | --- |
| A | .118, .105, .109, .112, .114 | 2.576, 2.581, 2.557, 2.622, 2.569 | 43.48, 43.40, 43.80, 42.72, 43.59 |
| B | 1.772, .132, .145, .151, .139 | 8.141, 8.957, 9.509, 8.724, 9.033 | 13.76, 12.50, 11.78, 12.84, 12.40 |
| C | .144, .111, .099, .102, .109 | 5.348, 2.798, 2.585, 2.475, 2.470 | 20.94, 40.03, 43.33, 45.25, 45.35 |
| B2 | .160, 4.333, 4.493 | 8.941, 8.679, 9.665 | 12.53, 12.90, 11.59 |

Cached-suffix prompt rates span approximately **33.8–38.1 / 2.26–30.38 / 27.73–40.56 / 0.89–25.06 tokens/s** for A/B/C/B2. The first C call remains slower while memory settles, but later calls return to baseline without restarting either service. B2 embedding requests take **.225 / 1.999 / 1.996 s**; native totals **.033 / 1.803 / 1.812 s**, native load durations **.00075 / .00089 / .00105 s**. This is warm inference, not repeated embedding loads.

**D — cold chat control:** after explicit normal chat unload, `/api/ps` is empty. The fixed request completes **200 in 10.857 s**: runner startup approximately **6.28–6.34 s**, prompt evaluation **.755 s / 1154 tokens / 1527.63 tokens/s**, generation **2.517 s / 113 tokens / 44.49 tokens/s**. Startup is a log-measured phase, not a fabricated native `load_duration`. Subsequent warm call is **2.860 s**, prompt .120 s, generation 2.582 s, 43.37 tokens/s. This is a cold model process with potentially warm filesystem cache, not a cold workstation. Neither times out; cold latency is excluded from warm statistics.

**Two simultaneous chat HTTP requests:** chat only **2.917 / 5.613 s**, co-resident **8.605 / 17.989 s**; all 200, no >30/>40/45-second result. Ollama runs a single chat slot (`-np 1`): the second request queues; this does not demonstrate two parallel GPU decoding slots. Co-residency already slows one request and therefore does not require chat concurrency to be causal.

## Resource Correlation and Model Lifetime

The following ranges summarize sampled direct scenario windows. Memory values are MiB; host memory is GiB available. GPU committed memory is a Windows accounting value, not physical VRAM consumed.

| Scenario | Dedicated NVIDIA | Windows shared | Windows committed | Host available | Median GPU / memory-controller utilization |
| --- | --- | --- | --- | --- | --- |
| A | 7483 | 813.4–813.6 | 9841.2 | 22.36–22.50 | 85.5% / 66.5% |
| B | 7716–7722 | 933.2–1055.7 | 12400.3–12400.6 | 18.45–20.23 | 96% / 17% |
| C | 7125–7249 | 813.5–873.5 | 9755.4–9755.5 | 20.96–21.08 | 89% / 55% |
| B2 | 7592–7726 | 936.2–1119.3 | 12314.6–12400.8 | 18.26–19.25 | 96% / 17% |

Linux process RSS, host RAM and all residency samples are retained in JSONL; host RAM is not exhausted. Summed sampled Ollama-container process RSS is **1494–1495 MiB in A, 2208–2211 MiB in B, 1647–1665 MiB in C, 2264–2267 MiB in B2**. The Ollama server itself uses approximately **42–62 MiB**; runners account for most process RSS. These values exclude container page cache and are not GPU allocation sizes. The two model allocations alone total approximately **7496 MiB**, before the existing desktop/VM GPU consumers. Physical capacity is only 8192 MiB. Co-residency adds approximately **2559 MiB GPU committed memory** in the authoritative direct series, raises shared usage and sharply lowers generation throughput. After unload, commitment and throughput return toward A. Dedicated usage alone does not show all committed allocation residency or driver movement.

Ollama still reports “100% GPU”; logs show **34/34 chat layers and 29/29 embedding layers** placed on GPU. **CPU model offload: not observed. Shared GPU memory: observed**, including a VM worker allocation; exact paging traffic for particular tensors is not established. There are no corroborating CUDA allocation errors, OOM messages or runner crashes in the experimental windows.

There is **no unintended eviction/reload churn** during warm A/B/C or adapter comparisons. Runner changes match deliberate lifecycle controls: embedding loads for B, embedding stop for C, and chat stop/reload for D. Initial embedding load is separately captured at **3.377 s HTTP / 3.066 s native load** in the authoritative series. Cold/load time is not counted as slow generation. Ollama was never restarted.

H1 is supported: **idle residency alone** gives approximately **3.28×** median direct latency. H2 adds a smaller observed penalty: B2 median is approximately **1.42× B**, concentrated partly in prompt evaluation and query inference; three samples do not establish a production tail distribution. Background GPU applications were not stopped, and their exact workload was not held constant. Repeated A/B/C reversibility across direct and adapter paths makes an unrelated one-off background spike an insufficient explanation for the persistent residency effect.

## Authorized Provider Adapter and Full API Confirmation

| Adapter state | Durations | Result |
| --- | --- | --- |
| A, chat only | 4.015, 2.837, 2.857 s | 3/3 success |
| B, co-resident | 10.184, 7.877, 8.529 s | 3/3 success |
| C, embedding unloaded | 5.661, 3.091, 3.147 s | 3/3 success |

Same input, tools, options, result and 1154/113 tokens; all canonical adapter payloads match the direct frozen body. SDK timeout stays 45 s. No adapter-specific failure, alternative route or authorization bypass appears. Adapter close traces finish with active count zero and closed state; no orphan cleanup is introduced.

The full-agent confirmation uses the **actual rebuilt API**, a fresh server-managed `demo-public` session per scenario, and the same German two-step journey: `Untersuche Station S01.` then `Prüfe den aktuellen Status von Station S05.` Each run executes exactly one read-only `get_station_overview` with the matching target, followed by two model calls. No embedding retrieval is invoked by this journey, so B tests resident-but-idle embedding. Synthetic diagnostic runs are persisted normally; no tickets, approvals, calibration or hardware commands are executed.

| Scenario / step | Run ID | Model call durations | API duration | Terminal |
| --- | --- | --- | --- | --- |
| A / S01 | `9d4e275f-af59-40dc-8749-cec9995f8c65` | 4.453 / 5.740 s | 10.531 s | success |
| A / S05 | `9713df78-0efd-4ef3-bcf7-4c03be15dbc1` | 3.619 / 5.706 s | 9.670 s | success |
| B / S01 | `c5e03213-968c-4252-959a-6b053e50ab02` | 15.371 / 39.029 s | 54.599 s | success |
| B / S05 | `58302124-3174-4726-9b79-392596ad969b` | 10.118 / 40.218 s | 50.509 s | success |

Local Tempo traces establish individual call durations and identical corresponding input token counts: **1151/724** for S01, **1154/697** for S05, in both residency states. Journey request-time sums are **20.200 / 105.109 s**; end-to-end spans including inter-request handling are approximately **20.385 / 105.302 s**, excluding preloading/bootstrap. Each separate API run remains under its 90-second budget. The two long B calls leave only **5.97 / 4.78 s** to the unchanged SDK limit; one exceeds 40 s, both exceed 30 s. None times out in this actual API sample. The original aggregate Agent timeouts remain credible under similarly degraded multi-call work, but were not reproduced as new terminal failures here.

Independent API `/health` requests remain responsive: A maximum **16.9 ms**; B maximum **9.0 ms**, 210/192 successful samples during the two B runs. No new persistent API error is observed. This separates GPU latency from the already-fixed event-loop cleanup defect.

## Classification, Remaining Uncertainty and Next Task

**Root cause supported by this phase:** the current shared workstation has insufficient comfortable dedicated GPU headroom for the historical chat and embedding allocations plus existing GPU consumers. Keeping both allocations resident introduces a reproducible, reversible generation slowdown below Agent/adapter orchestration, with increased Windows committed/shared memory. Concurrent embedding adds measurable contention; reload churn is not the cause of the warm slowdown.

The previous diagnosis's first-boundary conclusion remains intact: historical SDK read deadlines fire before the matching Ollama abort/500 logs; some longer runs first exhaust the Agent budget. This phase does not identify a new independent Ollama 45-second server limit. It does not justify calling HTTP 500 “model variance.”

Remaining uncertainty is specific: no original GPU memory time series, no tensor/page migration trace, an uncontrolled desktop workload, a small sample and a reconstructed historical request shape. The authoritative UTF-8 direct/adapter series has **zero new timeouts**; the one new timeout belongs to the separately retained preliminary misdecoded input. Valid full-agent calls nevertheless reproduce approximately 40-second provider latency under co-residency. This supports material historical contribution without claiming deterministic timeout on every representative request or exclusive causality for every original failure.

**Separate remediation task recommended:** qualify and implement a local model-residency/capacity policy that leaves sufficient dedicated GPU headroom for chat, embeddings and the normal desktop workload, then rerun the complete 12-journey product gate and realistic embedding/chat overlap. Evaluate residency scheduling/device placement or dedicated capacity as alternatives before selecting a change; no concrete model/configuration setting is selected or applied here. Do not mask the capacity signal by increasing timeouts or adding retries. No Agent/provider code defect was identified that presently requires a code change. Configuration/capacity remediation is justified; the exact implementation requires a separate task. **Ready for remediation: YES.**

## Safety, Regression and Integrity

**43 focused tests passed, 0 failed/skipped**: 14 `test_provider_cleanup_async.py` cases and 29 `test_r01_provider_authorization.py` cases. Heartbeat/drain tests retain the 150-ms responsiveness bound for 350/750-ms residual work; independent API work, repeated cancellation, owned cleanup, active counts and final closure remain covered. One existing Starlette/AnyIO deprecation warning is not a failure. API `/ready` is 200; Knowledge MCP authenticated initialize/tool-readiness succeeds. `git diff --check` passes.

All initial tracked-file SHA-256 hashes match after diagnostics, including the already-staged previous diagnosis and historical reviews. New additions are this canonical report and its Git-ignored German translation. Product/provider/configuration source changes **0**; historical reports modified **NO**; existing staged state preserved. No commits, pushes or external deployments. Only the explicitly requested API runtime alignment and normal model lifecycle controls changed runtime state. At completion the embedding model is unloaded, project services remain healthy, and all owned measurement workers have completed.

External model calls **0**. Real protected side effects **0**. No timeout/retry, assignment, prompt, context, quantization, Ollama configuration, Docker limit or production harness expectation was changed. No full-suite certification or remediation is claimed.

## Evidence Protocol

New external evidence root: `D:\Freelance\local-provider-vram-evidence-2026-10-16`. Authoritative corrected direct/adapter series: **`verified-utf8\`**. Original diagnostic artifacts and previous reviews remain intact.

Key evidence: `initial-manifest.json`, initial/aligned/final container identities, `agent-api-build.txt`, `agent-api-recreate.txt`, `snapshot-aligned.json`, assignments, model metadata, preliminary and `verified-utf8\matrix-events.jsonl`, `shared-memory.jsonl`, fixed payload/profile, response bodies, phase-correlated Ollama logs, `analysis.json`, `final-summary.json`, adapter HTTP payloads/lifecycle events, `confirmation-span-summary.json`, raw local traces, four API response artifacts, `focused-tests.txt/.xml`, and Knowledge readiness exit status. Times are UTC. Sensitive credentials are excluded from reports/output; payloads use synthetic authorized demo data.
