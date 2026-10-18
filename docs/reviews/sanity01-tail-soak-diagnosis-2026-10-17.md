# SANITY-01 — Production-state tail-latency soak diagnosis — 2026-10-17

## Result

Primary classification: **TAIL_NOT_REPRODUCED**. Confidence **HIGH** in this observed
result; the cause of the historical failures remains unresolved. **Ready for production
remediation: NO.** No production behavior or configuration was changed.

All **75 measured identical direct requests** completed in **2.964–3.118 s** and all
**15 historical Agent journeys passed**, with **65/65 required assertions** and
**80/80 local provider calls below 10 s**. No provider deadline, Agent deadline,
Ollama HTTP 500, runner crash, unexpected chat reload or tail trigger occurred.
The earlier SANITY-01 failures remain real and open; this bounded successful sample
does not recertify the release or identify their cause.

Sources read and preserved:
[provider diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md),
[GPU/paging diagnosis](sanity01-gpu-paging-diagnosis-2026-10-17.md), and
[headroom A/B/A](sanity01-gpu-headroom-ab-diagnosis-2026-10-17.md).

## Baseline and unchanged production state

- Repository `D:/Freelance/industrial-ai-agent`; `main`;
  HEAD `d692e489f469777530e629e29ba05708759be5bc`.
- Initial status: `AM docs/reviews/final-release-sanity-2026-10-17.md`;
  `A docs/reviews/sanity01-gpu-paging-diagnosis-2026-10-17.md`;
  `A docs/reviews/sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md`;
  untracked `docs/reviews/sanity01-gpu-headroom-ab-diagnosis-2026-10-17.md`.
  All are preexisting documentation states. No implementation/test/config changes.
- Windows 11 Pro 10.0.26300; RTX 3070 8192 MiB; NVIDIA 617.42/WDDM.
  Initial dedicated usage 1873 MiB. Ollama remains the existing local 0.33.2 service.
- `local_quality` → `qwen3.5:9b`, Q4_K_M, runtime context **4096**.
  All eight Agent/RCA assignments and production model metadata compare equal before/after.
  No temporary diagnostic models remain installed or resident; none were created in this phase.
- Embedding `qwen3-embedding:0.6b`, CPU policy `num_gpu=0`, context4096.
  Real Knowledge retrieval verifies CPU allocation before/after; every observed
  embedding residency has **0 GPU bytes**. Idle/nonresident embedding is not GPU placement.
- SDK deadline **45 s**, max retries **0**; Agent deadline **90 s**, unchanged.
  No proxy, model, weights, quantization, prompt, output budget, assignments, concurrency,
  Docker/resource or Ollama configuration change, restart or model-unload intervention.
- **20/20 Compose services healthy** before and after; final restart counts all **0**.
  API readiness 200, authenticated Knowledge discovery/retrieval succeeds.
  No unrelated user application was terminated, suspended or reconfigured.
- Evidence: `D:/Freelance/sanity01-tail-soak-20261017-175229`.

## Exact frozen request and protocol

Semantic SHA256: `e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
SSE wire SHA256: `49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`.
Both are checked before every request. Same production model, unchanged UTF-8 messages,
two tools/schemas, temperature0, max_tokens192, reasoning_effort=none. The only transport
addition to the frozen original body is `stream=true`, as validated in earlier phases.
Exact rendered input **1104 tokens**; every completion **158 tokens**, **441 characters**,
zero reasoning characters, STOP, identical text digest
`2058fc451e29d892a522a08da72a8e6d0ba491d5456d704eb847ac3f6fc2c39c`.

One explicit warmup completed in **12.642 s**, including ordinary cold model loading;
it is excluded from the 75 measurements and retained separately. No extra load/restart
was introduced. The original UTF-8 file was initially read using the Windows default
encoding by the external observer; the hash guard rejected that setup **before any
model request**. `direct-soak.log` preserves that setup failure. Only the external
reader was corrected to explicit UTF-8; no measurement was retried or discarded.

The direct raw HTTP observer permits natural completion beyond45 s using the same
separate observation ceiling as preceding streaming diagnostics. It does not instantiate
or alter a longer-timeout SDK client. All actual Agent SDK calls retain45 s; no60/75/90 s
timeout control was performed. A direct >45 s completion would be OVER_BUDGET, not a
claimed SDK timeout. This distinction matters for the denominator below.

## Direct soak and stopping rule

Measured interval: **15:55:43.549–15:59:31.509 UTC**, **227.960 s**.
75 sequential requests, no concurrency, retries, unload, restart or configuration change.
The early-stop predicate required at least three SLOW/OVER_BUDGET events and at least
five further requests after the first event. It never became eligible; all75 completed.

| Measure | Result |
| --- | --- |
| FAST / SLOW / OVER_BUDGET | **75 / 0 / 0** |
| Median / nearest-rank p90 / max wall s | **3.021 / 3.082 / 3.118** |
| Median / minimum native generation tok/s | **53.83 / 52.07** |
| Median prompt eval / generation s | **0.08914 / 2.91644** |
| Evaluated prompt tokens after cache reuse | **4**; full input remains1104 |
| Maximum TTFT / output-batch pause | **0.11814 / 0.06635 s** |
| Valid complete outputs | **75/75**, same hash |
| First tail / natural recovery | **None / NOT_APPLICABLE** |

| Wall-duration bucket | Direct measured | Agent provider calls | Warmup, separate |
| --- | --- | --- | --- |
| <10 s | 75 | 80 | 0 |
| 10–20 s | 0 | 0 | 1 |
| 20–30 s | 0 | 0 | 0 |
| 30–40 s | 0 | 0 | 0 |
| 40–45 s | 0 | 0 | 0 |
| >45 s | 0 | 0 | 0 |

SSE has **139 nonempty delivery batches**, not158 individually observed tokens.
Exact output counts, prompt-eval durations/counts and generation durations/rates are
matched from Ollama runner logs for **all156 calls**, including warmup. Native
`tg_3s` rolling rates exist for25 sufficiently long calls; minimum **51.15 tok/s**.
For shorter calls rolling native rate is **NOT_AVAILABLE**, never fabricated from
batch counts. Per-batch timestamps, TTFT and longest pause are retained for direct calls;
Agent calls remain production nonstreaming, so Agent token-by-token timing is unavailable.

## Historical Agent reliability phase

All three current registered journeys ran five times sequentially, grouped by type,
with unchanged prompts, Demo identities, local model selection and assertions.
Each uses fresh browser/run artifacts; no retry/resume. Preflight verifies local-only
routing. Every journey drained provider work before the next one. All raw statuses,
assertion outcomes and diagnostic initiating-failure classifications are preserved.

| # | Journey | Repeat | Raw / primary | Provider calls | Max provider s | Journey wall s* | Required assertions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | product-centric-en | 1 | PASS / PASS | 6 | 4.216 | 24.395 | 3/3 |
| 2 | product-centric-en | 2 | PASS / PASS | 6 | 4.043 | 22.339 | 3/3 |
| 3 | product-centric-en | 3 | PASS / PASS | 6 | 4.265 | 23.383 | 3/3 |
| 4 | product-centric-en | 4 | PASS / PASS | 6 | 4.130 | 23.112 | 3/3 |
| 5 | product-centric-en | 5 | PASS / PASS | 6 | 4.110 | 22.331 | 3/3 |
| 6 | clearance-boundary-en | 1 | PASS / PASS | 4 | 4.048 | 13.856 | 6/6 |
| 7 | clearance-boundary-en | 2 | PASS / PASS | 4 | 3.899 | 12.747 | 6/6 |
| 8 | clearance-boundary-en | 3 | PASS / PASS | 4 | 3.734 | 12.442 | 6/6 |
| 9 | clearance-boundary-en | 4 | PASS / PASS | 4 | 3.849 | 12.777 | 6/6 |
| 10 | clearance-boundary-en | 5 | PASS / PASS | 4 | 3.886 | 12.956 | 6/6 |
| 11 | restricted-boundary | 1 | PASS / PASS | 6 | 4.629 | 23.043 | 4/4 |
| 12 | restricted-boundary | 2 | PASS / PASS | 6 | 4.204 | 18.491 | 4/4 |
| 13 | restricted-boundary | 3 | PASS / PASS | 6 | 4.239 | 18.279 | 4/4 |
| 14 | restricted-boundary | 4 | PASS / PASS | 6 | 4.247 | 18.456 | 4/4 |
| 15 | restricted-boundary | 5 | PASS / PASS | 6 | 4.275 | 18.495 | 4/4 |

*Journey wall includes existing preflight, browser and drain; exact execution durations
for each persisted Agent run are in trace evidence. Product/clearance/restricted
required assertions are **15/15**, **30/30**, **20/20** respectively. Raw harness errors,
provider timeouts, Agent timeouts and OTHER_PRODUCT_FAILURE are each **0**.

The bounded Tempo query returned40 execution traces, all matching the40 UUID run IDs
in these browser artifacts, with **0 missing**. No arbitrary history trace was selected.
All80 `llm.call` spans identify LOCAL/Ollama/qwen3.5:9b. Per-call sequence within its
run, global phase sequence, duration/result, SDK-timeout flag, token metadata, native
runner metrics and contemporaneous resources are retained. Agent provider median/p90/max:
**2.501 / 4.177 / 4.629 s**, median/min generation **52.105 / 46.54 tok/s**.
Inputs482–2491 tokens, outputs21–192. Successful usage is provider-reported.
Sensitive prompts/responses/credentials are not added to trace capture.

## Process, host and model observations

**3548 PDH/NVML samples**, median interval **200.442 ms**, p95 **200.697 ms**,
maximum **213.538 ms**; counter-registration errors **0**. Capture includes adapter
and process dedicated/shared allocations, engine/PID activity, GPU utilization,
clocks, memory clock, power, temperature, P-state, host CPU/commit/available RAM,
process CPU/memory/faults/I/O, memory fault/input/read rates and disk bytes/queue/time.
Linux process/memory/CPU/pressure/fault observations run at approximately1 s.

Raw PID/name/engine information distinguishes Ollama's WSL/VM host, DWM, Brave/Chrome,
IDE, WebView, SnippingTool, Fork and other visible consumers. NVIDIA-adapter engine
rates below0.05 are filtered as inactive; missing low rates are not proof of zero work.
Aggregated engine percentages are **sums of engine-time percentage points**, not a
physical GPU occupancy percentage; engines may overlap. WSL GPU engines are attributed
to its Windows VM process, not claimed as individually attributable Linux Ollama kernels.
Memory allocations may alias/shared-map surfaces and are not naively summed as physical VRAM.

Windows' formatted Process CPU percentage can cap at100, so it is excluded from
quantitative VMMEM CPU attribution. The supplementary native CPU-time observer has
null CPU times for protected VMMEM/VMWP processes; these are **NOT_AVAILABLE**, not0.
It starts during direct run21, preserving its limited coverage. Linux `/proc/stat`
instead supplies aggregate WSL CPU utilization at ~1 s, explicitly a different scope.
Four very short Agent calls have no Linux sample within the call and remain unavailable.
The first analysis incorrectly converted inaccessible supplemental CPU times to0;
its files remain preserved for provenance. **Only `*-validated.json` and
`provider-request-metadata-validated.csv` are authoritative.**

Measured FAST-state resource medians, direct / Agent:

- External GPU engine sum **0.062 / 0.285** percentage points; highest per-call medians
  **1.024 / 1.356**. DWM peak within a call at most0.505 /3.900 points. Browser median
  engine activity is below the retained threshold on this NVIDIA adapter; it is not
  evidence that browser/desktop work never occurred elsewhere.
- Host CPU **45.29 /43.65%**, Linux/WSL CPU **37.86 /34.74%**; host commit approximately
  **67.87 /68.26 GiB**, with substantial available physical RAM. VMMEM working set
  approximately **18.12 /17.95 GiB**.
- Shared GPU allocation **0.772 /0.771 GiB**, median minimum dedicated reserve
  **0.395 /0.427 GiB**; smallest observed per-request reserves **0.324 /0.332 GiB**.
- Median SM clock **1905 /1905 MHz**. Direct phase request-median temperatures65–75°C,
  P2, median power213.16 W. Short Agent calls can include idle clock/P-state transitions;
  their counters are not interpreted as sustained inference throttling.
- Windows disk/input bursts occurred while requests stayed fast; these are global
  counters, not proof of Ollama or GPU page migration. Linux pgmajfault, pswpin and
  pswpout deltas during model traffic were each **0**. Historical parent-process swap
  is not mistaken for new paging; chat runner swap remains0 in the observations.

**253** residency samples across the measured model-traffic window confirm chat
resident at context4096, size_vram==size==5490081790. The same chat runner **PID9769**
is present throughout **511** Linux snapshots. All42 observed embedding residencies
are CPU-only. Only production chat and embedding appear; normal embedding cache/idle
residency changes are separate from chat continuity. No unexpected chat reload,
runner restart/crash, second chat model, sustained queue or co-residency pressure.

## Correlations and causal limits

Pearson correlations use **native generation tokens/s**, separately for the identical
direct request and heterogeneous Agent calls. Agent correlations are additionally
confounded by call type/input/output and short-call sampling. N/A means no variation
or unavailable values, never an assumed zero relationship.

| Metric vs generation tok/s | Direct n / Pearson r | Agent n / Pearson r |
| --- | --- | --- |
| External GPU engine sum | 75 / -0.790 | 80 / -0.538 |
| DWM GPU engine sum | 75 / -0.821 | 80 / -0.461 |
| Browser GPU engine sum | 75 / N/A | 80 / N/A |
| WebView GPU engine sum | 75 / N/A | 80 / N/A |
| IDE GPU engine sum | 75 / N/A | 80 / N/A |
| Ollama/WSL GPU engine sum | 75 / -0.677 | 80 / 0.022 |
| Windows VMMEM CPU (uncapped) | 0 / N/A | 0 / N/A |
| Linux/WSL aggregate CPU | 75 / -0.244 | 76 / 0.292 |
| VMMEM working set | 75 / -0.112 | 80 / -0.207 |
| Host committed memory | 75 / -0.012 | 80 / -0.066 |
| Host CPU | 75 / -0.377 | 80 / -0.013 |
| Shared GPU allocation | 75 / -0.132 | 80 / 0.134 |
| Minimum dedicated headroom | 75 / 0.316 | 80 / -0.243 |
| GPU SM clock | 75 / -0.247 | 80 / 0.303 |
| Global GPU utilization | 75 / -0.048 | 80 / 0.169 |
| Windows pages input/s | 75 / N/A | 80 / N/A |
| Disk bytes/s | 75 / 0.093 | 80 / -0.047 |

There are **no SLOW/OVER_BUDGET samples** to contrast with FAST. The relatively large
direct external/DWM correlations occur across a narrow52.07–54-range fast throughput
and low external engine activity. They do not demonstrate substantial contention or
explain a historical collapse to~4 tok/s. No repeatable tail signature, natural
degradation/recovery transition or causal process intervention was captured. Windows
scheduling preemption/page migration and individual GPU tensor faults are not directly
observable from these counters. No kernel tooling, workload manufacturing or user-process
termination was used. The earlier headroom experiment is not overturned.

## Observed reliability and next decision

- **155 measured provider requests** =75 raw direct +80 production Agent SDK calls;
  **156 total** including the separate warmup. Ollama HTTP log count matches156.
- Direct45-second budget exceedances **0/75**; actual SDK provider timeouts **0/80**;
  observed combined budget-failure count **0/155 (0%)**; warmup also below45 s.
- Agent timeout journeys **0/15**; journey failures **0/15**. No downstream harness
  error is hidden or relabeled as a pass.
- Measured direct window is only3.80 minutes; entire measured model-traffic window
  **511.825 s (8.53 minutes)**. Sequential warm requests share prompt-cache state;
  observations are time-correlated. These are observed rates, not a population guarantee
  or a statistically justified upper bound on historical failure frequency.

Recommended next step: further **passive/event-triggered observation across separate
normal workstation-use windows**, retaining the same frozen request and selected
journeys, is justified by the earlier clustered failures. Capture a genuinely slow
state before selecting an intervention. Do not manufacture load or extend production
timeouts on speculation. Production timeout change **NO on this evidence**;
operational resource change **NO on this evidence**; provider/model configuration
change **NO on this evidence**. Underlying cause remains unknown; readiness for
production remediation **NO**. This phase did not validate a timeout-policy fix.

## Safety, integrity and evidence inventory

Provider cleanup **14 PASS**, R01 **29 PASS**:43 passed,0 failed,0 skipped,
one existing Starlette/AnyIO deprecation warning,6.98 s. Final API `/ready`200;
Knowledge discovery and genuine local retrieval PASS (8.196 s), embedding GPU allocation0.
Stack stays running,20/20 healthy,0 service restarts. All assignments/model metadata
unchanged; protected counters unchanged: maintenance tickets100, maintenance events5,
process parameters1. Protected side effects0, external model calls0, commits/pushes/deploys0.

All **546** initially hashed tracked files and existing review/translation files remain
byte-identical, including all prior reports. New files only: this English report and
its ignored local German translation. Source/test/config changes0. `git diff --check`
and staged diff check PASS; the preexisting sanity report has only an LF/CRLF advisory.
No architecture change or affected diagram. Diagnostic helpers and raw evidence are
outside the repository; browser artifacts use new ignored run directories.

Authoritative evidence: `analysis-summary-validated.json`,
`direct-request-profiles-validated.json`, `agent-call-profiles-validated.json`,
`agent-journey-analysis-validated.json`, `provider-request-metadata-validated.csv`,
`token-progress-metrics.json`, `token-progress-summary.json`, `evidence-checks.json`,
all per-request batch files, original direct results, Ollama logs, raw PDH/NVML/Linux/
process-CPU/residency JSONL, owned execution-span metadata, browser artifacts,
production-invariant snapshots, protected counters and file-hash manifest.

No20-second snapshot or TAIL_STATE_ACTIVE trigger fired; therefore no triggered
before/after30-second bundle was needed. Continuous telemetry covers both phases.

Final conclusion: **TAIL_NOT_REPRODUCED; SANITY-01 unresolved; production unchanged.**
