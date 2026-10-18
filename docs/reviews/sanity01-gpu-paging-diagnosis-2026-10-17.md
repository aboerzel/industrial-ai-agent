# SANITY-01 — GPU/WDDM memory-pressure diagnosis — 2026-10-17

## Decision

Finding: **SANITY-01**. Diagnostic only. Primary classification: **INCONCLUSIVE**.
PAGING_SIGNATURE: **INCONCLUSIVE**. Overall causal confidence: **MEDIUM**.

The proposed complete chain
`WDDM memory pressure → page migration → severe throughput collapse → >45 s`
is **neither proved nor globally falsified** by this phase. Memory pressure and lower
throughput remain strongly associated, and identical requests show natural degradation
and recovery. However, no warm request exceeds 30 seconds in this phase, no provider
timeout occurs, and the permitted counters do not directly identify page migration.
The only SLOW request is an expected cold load with fast generation afterward.

No production change is recommended from this evidence alone. Recommended class:
**FURTHER_DIAGNOSIS / controlled GPU-headroom comparison**. Ready for targeted
remediation: **NO**. A timeout increase is **not** recommended as the primary fix.
Historical SANITY-01 failures remain open; current successful replays do not certify
the previous release as reliable or erase its failures.

Source of truth read: [previous provider diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md).
It and all earlier reports were preserved unchanged.

## Frozen state and safety

| Item | Observed |
| --- | --- |
| Repository / branch | `D:/Freelance/industrial-ai-agent` / `main` |
| HEAD | `d692e489f469777530e629e29ba05708759be5bc` |
| Initial Git status | `AM docs/reviews/final-release-sanity-2026-10-17.md`; untracked previous provider-diagnosis report; no implementation/test/config differences |
| Windows | Windows 11 Pro, build 26300 |
| GPU / driver | RTX 3070, 8192 MiB; NVIDIA 617.42 / Windows driver 32.0.16.1742 |
| Driver model | **WDDM 3.2**, recorded by built-in dxdiag |
| Ollama | 0.33.2, existing local Docker container |
| Chat | `local_quality` → `qwen3.5:9b`, Q4_K_M, context 4096, temperature 0 |
| Embedding | `qwen3-embedding:0.6b`, context 4096, persisted `num_gpu=0` |
| Models initially resident | None, following ordinary idle expiry |
| Initial NVIDIA VRAM usage | 1864 MiB before model load |
| Initial OS RAM | 66945652 KiB visible, approximately 22 million KiB available |
| Evidence | `D:/Freelance/sanity01-gpu-20261017-113733` |

The CPU embedding model was verified by authenticated local Knowledge retrieval before
measurement: 100% CPU, 0 GPU bytes. The first frozen chat request then loaded chat on
GPU; subsequent residency samples show size_vram == size, 5490081790 bytes. No model
other than these two appears. During measurement chat context remains 4096.

All significant Windows GPU consumers were recorded by PID/name and memory counters.
Examples include Desktop Window Manager, SnippingTool, Fork, Brave, WebView and
CrealityPrint. They were **not** terminated, suspended or reconfigured. The browser
runner creates and normally closes only its own diagnostic Chromium sessions. No
GPU stress load, user-application headroom intervention or unrelated-resource change
was introduced. Windows per-process allocations can alias shared surfaces and must
not be naively summed as independent physical GPU allocations.

No source/test/config/prompt/model/quantization/context/output-budget/assignment/placement/
concurrency/retry setting was changed. Production provider 45 s, Agent 90 s and proxy
timeouts were unchanged. Direct raw HTTP used a separate 240-second observation ceiling
to allow natural completion, not a modified SDK or production deadline. No external
provider, approval, ticket creation, hardware action, commit, push or deployment.

## Exact request and streaming equivalence

- Frozen semantic SHA256: `e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
- Original nonstreaming UTF-8 wire SHA256: `4ca98a67fa1e96d1b45f756a78d172086ec39ff8bcb42ebeaa232462491bbfed`.
- Streaming UTF-8 wire SHA256: `49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`.
- The original wire serialization is reconstructed from the previously frozen JSON
  using unchanged HTTPX; it is not a newly recovered historical raw-wire capture.
- Original body 4579 bytes; streaming body 4593 bytes. The **only** added field is
  `stream=true`, appended to the original wire representation. Removing that field
  reproduces the frozen semantic bytes exactly. All twenty streaming requests use
  identical wire bytes, verified before each measurement. All three original-transport
  controls verify both original wire hash and semantic hash before measurement.
- Messages, tools, schemas, model, temperature, `max_tokens=192`, reasoning_effort=none
  and context configuration are unchanged. Input is 1104 tokens; every completed
  frozen response has 158 output tokens, STOP, 441 characters and no reasoning content.
- The three original-transport completions reproduce the **exact previous full-message
  digest** `2c9154dfe6a05fcc026b7892b55d51a49d9b972a42e9db910570970f639f5cdb`.
  Their text digest equals all twenty streaming texts:
  `2058fc451e29d892a522a08da72a8e6d0ba491d5456d704eb847ac3f6fc2c39c`.
  Thus no material inference-semantic change was observed from streaming. Transport
  and resource state still must not be confounded in performance comparisons.

No protected prompt text is included in this report or added to production traces.
The frozen demo-safe body and evidence reside outside the repository.

## Telemetry and token-delivery method

Read-only existing Windows PDH and NVIDIA NVML APIs sampled at a 200 ms target;
**2611 samples**, median interval **200.447 ms**,
p95 **200.741 ms**, maximum **209.531 ms**.
Median collection work **8.016 ms**. No counter failed to register.
Utilization sensors can internally average over longer periods; polling every 200 ms
does not imply independent hardware-utilization measurements at 5 Hz.

Captured for every direct and Agent provider-call window:

- Windows GPU Adapter Memory dedicated/shared usage; GPU Process Memory dedicated/shared
  usage per PID; active GPU Engine instances; host committed bytes, commit limit,
  available bytes and CPU load; GPU-owning process working set/private bytes.
  Engine entries at or below 0.05% utilization are omitted from the retained active list.
- NVML framebuffer usage, GPU-kernel utilization, memory-controller utilization, SM and
  memory clocks, power, temperature and performance state. NVML utilization is not an
  instruction-level CUDA occupancy measurement. The WSL GPU work appears under the VM's
  exposed 3D engine; separate Copy/Compute activity was not observed in those counters.
- `/api/ps` model placement/digest/context snapshots every approximately two seconds;
  actual `ollama ps` before each first-series direct request. Both model roles are
  independently checked again at the end.
- Supplemental Linux `/proc` RSS, anonymous/data/virtual memory, private clean/dirty
  pages and swap for Ollama/llama-server at approximately one second. This observer
  starts after streaming run 3; Windows VM counters cover all requests. A distinct
  native Windows Ollama working set does not exist for the container: `vmwp` GPU memory
  and `vmmemWSL` process memory are VM-level proxies, not exclusive Ollama allocations.

The SSE client timestamps request send, headers, first SSE/content event, every
nonempty output batch and completion. All responses deliver **139 nonempty batches**,
not 158 individual tokens. Actual generation counts/rates come from matched Ollama
runner `print_timing`, corroborated by usage in original-transport controls. Per-batch
and rolling one-second delivery rates are recorded; the additional token-equivalent
rolling curve is explicitly an estimate calibrated by the final 158-token count.
Longest pauses are **client output-batch delivery gaps**, not individually observed
model-token gaps. No browser timing is substituted for token progress.

## Every direct outcome

Two bounded ten-request streaming series plus three original-transport equivalence
controls: **23/23 valid completions**. All outcomes count, with no automatic retries.
The second streaming series follows the three Agent journeys to observe the same
transport again after resource state changed. This is a fixed additional series,
not retry-until-pass or a request-shape change.

| Run | Mode | Class | Duration s | Generation token/s | Peak shared GiB | Min dedicated headroom GiB | Longest delivery pause s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SSE | SLOW | 32.327 | 48.56 | 0.824 | 0.530 | 0.063 |
| 2 | SSE | FAST | 3.370 | 48.48 | 0.823 | 0.459 | 0.063 |
| 3 | SSE | FAST | 3.322 | 49.08 | 0.822 | 0.463 | 0.062 |
| 4 | SSE | FAST | 3.295 | 49.49 | 0.823 | 0.530 | 0.062 |
| 5 | SSE | FAST | 3.347 | 48.55 | 0.824 | 0.474 | 0.064 |
| 6 | SSE | FAST | 3.329 | 49.03 | 0.823 | 0.435 | 0.061 |
| 7 | SSE | FAST | 3.366 | 48.4 | 0.829 | 0.380 | 0.069 |
| 8 | SSE | FAST | 3.363 | 48.47 | 0.825 | 0.385 | 0.063 |
| 9 | SSE | FAST | 3.346 | 48.73 | 0.824 | 0.380 | 0.065 |
| 10 | SSE | FAST | 3.434 | 47.5 | 0.825 | 0.380 | 0.076 |
| 11 | SSE | FAST | 5.758 | 28.86 | 0.995 | 0.293 | 0.204 |
| 12 | SSE | FAST | 5.574 | 28.76 | 0.993 | 0.289 | 0.149 |
| 13 | SSE | FAST | 4.478 | 35.94 | 0.992 | 0.329 | 0.098 |
| 14 | SSE | FAST | 5.514 | 29.06 | 1.001 | 0.338 | 0.168 |
| 15 | SSE | FAST | 16.508 | 9.67 | 1.101 | 0.261 | 3.124 |
| 16 | SSE | FAST | 9.410 | 16.92 | 1.099 | 0.277 | 1.770 |
| 17 | SSE | FAST | 5.197 | 30.9 | 1.017 | 0.400 | 0.157 |
| 18 | SSE | FAST | 6.370 | 25.11 | 1.080 | 0.305 | 0.846 |
| 19 | SSE | FAST | 13.648 | 11.6 | 1.124 | 0.251 | 2.760 |
| 20 | SSE | FAST | 4.415 | 36.57 | 1.086 | 0.280 | 0.191 |
| 1 | original HTTP | FAST | 8.993 | 17.75 | 1.052 | 0.287 | N/A |
| 2 | original HTTP | FAST | 10.103 | 15.71 | 1.054 | 0.270 | N/A |
| 3 | original HTTP | FAST | 8.394 | 18.97 | 1.087 | 0.299 | N/A |

FAST: **22**, median **4.837282 s**, median generation **33.42 token/s**.
SLOW: **1**, **32.326875 s**, generation **48.56 token/s** — **cold load only**.
OVER_BUDGET: **0**. No warm SLOW/OVER_BUDGET population exists in this phase.

The cold request has **28.405929 s before runner task execution**, followed by
**3.917770 s runner processing**, of which **3.233280 s generation**. TTFT is
**29.095940 s**. It must not be presented as paging-induced slow inference.
Warm streaming TTFTs and per-batch pauses are retained per request; the maximum warm
delivery pause is **3.123740 s** (run 15), compared with **0.063169 s** during the cold
request's subsequent fast generation. Initial model load is separate from inter-batch pause.

FAST median per-request peak shared memory: **0.993942 GiB**; median minimum dedicated
headroom **0.333364 GiB**. Cold SLOW peak shared: **0.823635 GiB**, minimum dedicated
headroom **0.529911 GiB**. These classification aggregates must not be interpreted as
a warm fast-vs-slow paging experiment. Full initial/peak dedicated, initial/peak/minimum/
median shared, shared delta, utilization, host commit, clocks and PID memory fields for
every request are in `request-resource-profiles.json` and `.csv`.

## Correlations, transition and recovery

The causal comparison uses **19 warm streaming requests**, identical transport and
wire hash, excluding the cold load and three nonstreaming controls. The sample size is
19 requests, not thousands of independent sensor samples. It is an observational,
time-confounded series, not a randomized or isolated headroom experiment.

| Generation token/s versus | Pearson r | Interpretation |
| --- | --- | --- |
| Peak shared GPU memory | -0.9345 | Strong inverse association; does not measure page faults |
| Median shared GPU memory | -0.9061 | Same association persists with median instead of peak |
| Minimum dedicated VRAM headroom | 0.8257 | More headroom accompanies higher throughput |
| Host committed bytes | -0.7774 | A competing covariate also changes with time |
| Median SM clock | -0.7928 | Slower runs have slightly higher clocks; not evidence of clock throttling |
| Median temperature | 0.9606 | Faster runs are hotter, opposite a simple thermal-collapse explanation |
| Median power draw | 0.9967 | Power tracks useful work; correlation is not a power-limit diagnosis |
| P-state | Not estimable | All warm request medians are P2 |

Warm request median clocks are **1920–1935 MHz SM**, memory **6801 MHz**, P2 throughout;
request median temperatures **60–69 °C**. Median GPU utilization ranges **79–100%**,
memory-controller utilization **2–78%**, power approximately **84–202 W**. Lower-throughput
runs can report 100% GPU utilization with only 2–4% memory-controller utilization.
These values do not prove either productive compute saturation or actual PCIe paging.
No evidence supports GPU_THERMAL_OR_POWER_THROTTLING as the primary classification.
Host request-median committed memory spans about **67.6–68.6 GiB**, with approximately
**18.2–19.5 GiB** physical RAM available; commit pressure and physical available RAM
are distinct measurements.

Immediately adjacent identical-wire transitions are captured:

- **14 → 15** (0.241 s gap): 29.06 → 9.67 token/s; peak shared 1.000866 → 1.100628 GiB;
  minimum dedicated headroom 0.337822 → 0.261173 GiB. Both retain model/context;
  median SM clock stays 1935 MHz. Run 15 shows a 3.124-second delivery pause.
- **15 → 16 → 17**, with approximately 0.2-second gaps and no restart/configuration
  change: 9.67 → 16.92 → 30.90 token/s. Shared state falls overall, reaching initial
  1.014748 / median 1.016579 GiB in run 17 versus initial 1.067226 / median 1.051926
  GiB in run 16. The lower allocation is present at the start of run 17; per-page
  residency and exact migration ordering remain unobserved.
- **18 → 19**: 25.11 → 11.60 token/s, peak shared 1.080315 → 1.124329 GiB;
  run 19 has a 2.760-second delivery pause.
- **19 → 20**, 0.185 s gap: **11.60 → 36.57 token/s**, while median shared allocation
  is effectively unchanged: **1.085312 → 1.085060 GiB**. Peak shared falls somewhat
  (1.124329 → 1.086174 GiB), but initial shared is actually higher in run 20.
  Recovery therefore does **not** require a clear preceding fall in shared allocation.
  The amount of shared allocation alone does not uniquely determine performance.

The earlier stream 10 → 11 comparison includes three original-transport controls and
three complete Agent journeys between them; it is **not** an immediately adjacent
transition and is not used as an isolated causal proof.

Natural throughput degradation and recovery are observed without intervention, but all
these warm requests remain FAST by the user's <30-second definition. The historical
approximately 4-token/s, >45-second state is not reproduced in this phase.

## Paging signature and causal chain

| Link or discriminator | Result |
| --- | --- |
| Near-full dedicated VRAM, changing shared allocation | Observed |
| Identical wire/model/context, variable throughput and bursty delivery | Observed; approximately 49.49 down to 9.67 token/s |
| Shared allocation predicts throughput reliably by itself | No; recovery example 19 → 20 disproves that stronger claim |
| Normal clocks / stable model / no queue / no runner crash | Observed |
| Increased exposed Copy-engine activity | Not observed; WSL workload is exposed under VM 3D accounting |
| Actual page migration / tensor page faults | Not directly observable from the collected counters |
| Three clearly slow warm inference cases | Not captured |
| Warm request >45 s under this signature | Not captured |
| Previous valid request >45 s | Established by the prior report, not a new causal proof here |

**PAGING_SIGNATURE: INCONCLUSIVE.** The partial pattern is consistent with WDDM residency
pressure, but allocation is not migration. GPU copies could also reflect other runtime
work; no such specific migration attribution is available. Desktop activity, recent
Agent/cache history and host committed memory were not independently held constant.
Neither WDDM_GPU_PAGING_PRESSURE nor OLLAMA_PROCESS_DEGRADATION meets its decision rule.
MODEL_INFERENCE_VARIABILITY is also not justified: resource state materially changes,
and a system-level explanation remains credible. MULTIPLE_CONTRIBUTING_CAUSES would
require separately demonstrated causes; correlations are insufficient.

## Optional controls deliberately not performed

Ollama restart: **NOT_RUN**. The prerequisite of enough warm fast/slow evidence was
not met; the only SLOW call is cold loading. There was no reason to clear the process
state and mistake that intervention for causal proof. Ollama restart count remains 0.

GPU-headroom intervention: **NOT_RUN**. Significant unrelated consumers were reported
but not terminated. No independent repository-owned GPU stress/diagnostic load exists
whose removal would constitute a clean headroom control. Normal cleanup of the
required browser journeys is not relabeled as a deliberate controlled experiment.

## Full-Agent correlation

The unchanged registered `product-centric-en` journey ran **3 times sequentially**,
demo-internal, unchanged local assignment and CPU-embedding policy, no retries/resume.
Artifacts: `evals/results/browser-e2e/sanity01-gpu-20261017-agent-1/` through `-3/`.
Provider drain was confirmed between journeys. All three journeys **PASS**, **9/9**
required assertions; **18/18** provider calls succeed, maximum **11.942031 s**.
All 41 chat HTTP requests in this phase are accounted for: 23 direct + 18 Agent;
**0 Ollama HTTP 500**, **0 provider timeouts**, **0 unexplained model traffic**.

| Journey | Run ID | Call | Type | Duration s | Generation token/s | Peak shared GiB | Terminal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `6dfa47b7-2d1a-4d8f-a416-7b6c6ca0edfa` | 1 | tool_decision | 11.942 | 13.52 | 1.046 | success |
| 1 | `6dfa47b7-2d1a-4d8f-a416-7b6c6ca0edfa` | 2 | structured_response | 9.149 | 22.41 | 1.017 | success |
| 1 | `625a4e62-8329-4b0c-a76b-da315df1e65f` | 1 | tool_decision | 7.630 | 21.46 | 1.017 | success |
| 1 | `625a4e62-8329-4b0c-a76b-da315df1e65f` | 2 | structured_response | 8.541 | 23.1 | 1.022 | success |
| 1 | `b5b3c5c5-d2f6-47bd-84f2-a1a6fa0497b8` | 1 | tool_decision | 1.498 | 29.12 | 1.017 | success |
| 1 | `b5b3c5c5-d2f6-47bd-84f2-a1a6fa0497b8` | 2 | structured_response | 4.596 | 26.06 | 1.019 | success |
| 2 | `15acf821-e7a6-42ea-89ed-8104192f1304` | 1 | tool_decision | 10.251 | 16.14 | 1.135 | success |
| 2 | `15acf821-e7a6-42ea-89ed-8104192f1304` | 2 | structured_response | 6.565 | 31.42 | 1.001 | success |
| 2 | `fcc8ab89-b0d0-41ad-979f-bd6f0e5ae5d1` | 1 | tool_decision | 4.719 | 35.58 | 0.991 | success |
| 2 | `fcc8ab89-b0d0-41ad-979f-bd6f0e5ae5d1` | 2 | structured_response | 5.632 | 35.93 | 0.992 | success |
| 2 | `7805e195-eee2-4f2d-8892-11c353112c89` | 1 | tool_decision | 0.828 | 38.83 | 1.009 | success |
| 2 | `7805e195-eee2-4f2d-8892-11c353112c89` | 2 | structured_response | 3.191 | 38.66 | 1.005 | success |
| 3 | `3032980d-f4a6-4906-a47c-e87832ea4019` | 1 | tool_decision | 5.250 | 32.26 | 0.994 | success |
| 3 | `3032980d-f4a6-4906-a47c-e87832ea4019` | 2 | structured_response | 6.789 | 30.58 | 0.995 | success |
| 3 | `7fd54e73-f693-4a32-b6ce-e3c209a7cc9b` | 1 | tool_decision | 5.424 | 30.66 | 0.996 | success |
| 3 | `7fd54e73-f693-4a32-b6ce-e3c209a7cc9b` | 2 | structured_response | 5.754 | 34.89 | 0.996 | success |
| 3 | `5f3a0bc5-eb19-49b2-be42-899b21198f7e` | 1 | tool_decision | 0.789 | 38.63 | 0.996 | success |
| 3 | `5f3a0bc5-eb19-49b2-be42-899b21198f7e` | 2 | structured_response | 3.383 | 36.26 | 0.996 | success |

`agent-call-resource-profiles.json` includes per-call initial/peak memory, utilization,
token usage, matched runner generation/progress and terminal outcome. No browser
latency is treated as token progress. No Agent timeout occurs under the measured
resource states, so this phase cannot establish that an Agent timeout has the same
paging signature. The original 1/5 replay and historical release failures remain valid.

## Remediation decision

Primary classification: **INCONCLUSIVE**. Confidence: **MEDIUM**.
Measured resource pressure plausibly affects throughput; direct WDDM paging attribution
and its causal responsibility for the historical 45-second boundary are unproven.
The complete causal hypothesis remains open, not disproven by a currently faster period.

Recommended class: **FURTHER_DIAGNOSIS**, specifically passive capture of the existing
frozen request during a naturally recurring warm over-budget state and a separately
authorized paired GPU-headroom comparison. That comparison would require the owner to
control unrelated applications explicitly; it was not authorized as an automatic
termination in this phase. Preserve the same input, transport, context and model.
Do not select smaller model/quantization, reduced context, partial CPU placement or
an application change without measuring the candidate's impact in that separate task.

**Timeout increase as primary fix: NO.** Normal warm completions are 3.3–16.5 s here,
not a stable 45–55 s workload at normal throughput. A larger timeout neither explains
the observed throughput swings nor establishes removal of their underlying cause.
No model/configuration/source remediation is implemented. Ready for targeted remediation:
**NO**. Stop diagnostic work after this report; no new comprehensive review.

## Safety, integrity and final state

- Focused cleanup/R01: **43 PASS**, 0 FAIL/SKIP, 5.96 s: 14 provider-cleanup and 29 R01.
  One existing AnyIO deprecation warning; production cleanup/lifecycle unchanged.
- Agent API `/ready` **200**; authenticated Knowledge readiness **PASS**. Final local
  retrieval **PASS**, embedding actually resident with **0 GPU bytes**, chat GPU.
  Across 260 model samples: no wrong placement, no third model;
  no chat-residency gaps after initial load while requests were active. Embedding's
  normal idle expiry/reload for the final check is separate from chat residency.
- `git diff --check` **PASS**. All **542** unique pre-existing files
  covered by the tracked/review manifest remain byte-identical, including both previous
  reports and local translations. Only this new report, its ignored local DE variant
  and new evidence were created. No source changes, commits, pushes or deployments.
- Protected persistent counters before/after: **100 tickets / 5 maintenance events /
  1 process parameter**. Protected side effects **0**. External model calls **0**.
- The local stack remains running. No project container or user process was restarted
  as an intervention. No remediation and no historical-report edits.

Evidence index: `request-hashes.json`, `direct-results.jsonl`, `bridge-results.jsonl`,
`direct-*-token-delivery.json`, `direct-*-rolling-progress.json`,
`high-frequency-telemetry.jsonl`, `linux-process-memory.jsonl`, `model-residency.jsonl`,
`request-resource-profiles.json`, `.csv`, `agent-call-resource-profiles.json`,
`final-analysis-summary.json`, `ollama-current.log`, `dxdiag.txt`, `focused-safety.log`,
`focused-readiness-final.json`, `file-integrity.json` and the external frozen-body copies.
