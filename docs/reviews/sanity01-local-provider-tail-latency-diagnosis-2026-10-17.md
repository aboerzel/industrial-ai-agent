# SANITY-01 — Local provider tail-latency diagnosis — 2026-10-17

## Result

Finding: **SANITY-01**, severity **MEDIUM**. Diagnostic only; no remediation performed.
The original three Real-Model failures and four reference failures all contain local
provider deadline failures. The original third run reaches the Agent deadline before
its late provider cancellation finishes.

The directly demonstrated mechanism is **VALID_WORKLOAD_EXCEEDS_PROVIDER_TIMEOUT**:
ordinary bounded output can take more than 45 seconds because generation throughput
has fallen dramatically. A warm identical request completed successfully in **49.287 s**;
another completed inference in **65.238 s**, separately from its cold load.
This is not evidence of a crashed provider. The deeper cause of the throughput collapse
is not conclusively isolated. GPU/WDDM memory pressure is the strongest measured
correlate, not a proven driver-level paging cause.

Overall causal confidence: **MEDIUM**; confidence in the deadline/slow-generation
mechanism is HIGH. Recommended remediation class: **FURTHER_DIAGNOSIS**.
Ready for remediation: **NO**. No particular replacement timeout is validated by this run.

## Baseline, preservation and scope

- Repository: `D:/Freelance/industrial-ai-agent`; branch `main`;
  HEAD `d692e489f469777530e629e29ba05708759be5bc`.
- Initial Git status: `AM docs/reviews/final-release-sanity-2026-10-17.md` only.
  This pre-existing report/index state was preserved. No implementation/test/config changes.
- Source of truth: [final release sanity](final-release-sanity-2026-10-17.md).
  This report and all historical reports remain byte-identical to diagnostic start.
- New evidence: `D:/Freelance/sanity01-diagnosis-20261017-105733`. Originals were copied and SHA256-hashed before replays.
  `original-hashes.json` identifies the preserved first failures, complete original
  provider spans, Ollama/API logs, reference matrix and capacity samples.
- Original source evidence remains under
  `D:/Freelance/final-sanity-evidence-20261017-092540` and
  `evals/results/browser-e2e/final-sanity-20261017-092540/`.
- Local Ollama 0.33.2, RTX 3070 8 GiB; `local_quality` → `qwen3.5:9b`,
  Q4_K_M, context 4096, temperature 0. Embedding `qwen3-embedding:0.6b`, `num_gpu=0`.
- No rebuild, retry policy change, model/configuration change, prompt change,
  provider/Agent/proxy deadline change, source change, commit, push or deployment.
  The sole 90-second client was constructed outside the application for the explicitly
  requested diagnostic control. Direct raw HTTP observation used a local 180-second
  capture ceiling; it did not alter the production SDK's 45-second limit.

## Preserved original failures

| Journey | Run ID | Call in run / gate | Terminal state | Raw browser result |
| --- | --- | --- | --- | --- |
| product-centric-en | `ddfa0913-ae59-4d9a-ac44-9d90828e69c9` | 1 / 82 | failed: llm_provider_unavailable | HARNESS_ERROR after reload |
| clearance-boundary-en | `ed737eb0-1a8a-46d8-8443-0b43a8dc16d3` | 2 / 84 | failed: llm_provider_unavailable | BLOCKED_BY_PROVIDER |
| restricted-boundary | `877747e2-7058-4778-b8b1-b793562b27a2` | 4 / 92 | failed: agent_execution_timeout | MODEL_VARIANCE; missing terminal |

| Journey | Provider-span start UTC | Timeout UTC | Ollama HTTP start UTC (derived) | Ollama HTTP 500 UTC | Provider s |
| --- | --- | --- | --- | --- | --- |
| product-centric-en | 07:51:56.777 | 07:52:41.832 | 07:51:56.790 | 07:52:41.834 | 45.055273409 |
| clearance-boundary-en | 07:53:31.422 | 07:54:16.447 | 07:53:31.421 | 07:54:16.449 | 45.025168656 |
| restricted-boundary | 07:56:36.853 | 07:57:21.894 | 07:56:36.853 | 07:57:21.895 | 45.041226608 |

Exact SDK-entry timestamps were not separately instrumented: the table labels the
existing `llm.call` span start, which includes adapter preparation. Ollama request
starts are derived from its logged completion timestamp minus HTTP duration, not
claimed independently measured arrival timestamps. Raw nanoseconds remain in evidence.
The first browser POST is 07:51:56.586 UTC. For the second, the failed execution starts
at 07:53:13.207 UTC; its exact original browser-submit timestamp is unavailable in the
retained last-request observation. The third browser POST is 07:55:19.019 UTC.

Actual trajectories, in order:

1. `product-centric-en`: bound `get_product_history(P4901)` succeeds in 14.440 ms;
   first `tool_decision` times out. The read contract succeeded before model failure.
2. `clearance-boundary-en`: bound `list_stations` succeeds in 14.050 ms;
   narrative call succeeds in 18.114654 s; `structured_response` times out.
   The failed initial request is “Which stations are available?”. Later independent
   denied QUALITY-09 and successful S02/new-chat controls remain distinct runs.
3. `restricted-boundary`: prior S07 status and station-reference runs succeed.
   The failing follow-up is “What does the active fault mean?”. Its sequence is
   LLM 8.769836 s → `get_machine_status` 10.746 ms → LLM 24.374582 s →
   `search_documentation` 3.220090 s → LLM 41.329295 s → structured LLM timeout 45.041227 s.
   Persisted terminal state is `agent_execution_timeout`; `agent.run` lasts 122.863148 s.

The application Agent deadline is **90 s** (`create_app` default, unoverridden by the
composition root), while the browser's existing terminal wait is 100 s. In the third
run the fourth model call starts about 77.8 s into execution. The Agent deadline occurs
while that call is active; cancellation/owned-provider drain outlasts the browser wait.
The late SDK timeout and Ollama cancellation explain the 122.863-second span. Provider
cleanup is not being reclassified as defective or changed.

Diagnostic label correction only: product-centric's reload HARNESS_ERROR and blocked
reference are downstream of provider failure; restricted's MODEL_VARIANCE is a
deadline/missing-terminal consequence, not demonstrated wording variance. The original
runner artifacts and sanity report were not edited.

## Four failed reference actions

| Case | Type / target / language | Failing run | Bound first read | Outcome |
| --- | --- | --- | --- | --- |
| 2 | station / S01 / DE | `3a2aec43-3a7e-4ee0-a564-7e889628ba4e` | get_station_overview: success 16.824 ms | action: tool_decision timeout 45.038878 s |
| 3 | station / S01 / EN | `95a6b5ff-9050-4dc6-a0ab-34484fde2b34` | get_station_overview: success 16.962 ms | initial prerequisite: tool_decision timeout 45.053562 s; action not sent |
| 5 | station / S04 / DE | `97cce67b-60a4-4a9f-8786-687a31fb51b7` | get_machine_status: success 12.562 ms | initial prerequisite: 13.943885 s success, then structured_response timeout 45.044194 s; action not sent |
| 6 | station / S04 / DE | `49b5c13b-15d9-4d5f-bee0-647fab5540e4` | get_machine_status: success 14.900 ms | action: 12.772779 s success, then structured_response timeout 45.034833 s |

Each failed provider span is `APITimeoutError`; all bound reads succeed with the expected
target. Cases 3 and 5 fail before an action request can be sent. Cases 2 and 6 return
HTTP 200 with a failed terminal result and `llm_provider_unavailable`. These are the
same provider phenomenon, not a demonstrated deterministic reference-contract regression.
The four matching Ollama 500 timestamps are 08:00:12.386, 08:00:59.124,
08:03:57.014 and 08:06:05.526 UTC. Exact traces are preserved per case.

## All-request profiles and measurement limits

All **92** original provider requests across **43** persisted runs are enumerated in
`all-92-call-metadata-enriched.json`; the initial structural inventory is also CSV.
Each row retains journey, run/sequence, timestamps, duration, classification, call type,
message/tool count, payload bytes, actual successful token use, failed prompt token
count and generation lower bounds where available, and linked Ollama task timing.
Authorized API reads recover actual response language, terminal state and prior-turn
metadata for every run. Context-turn count is reconstructed using the current bounded
last-four, classification-eligible context contract; it is not a historical wire capture.

The original privacy-preserving telemetry did **not** retain complete prompts,
context-only characters/bytes, serialized individual tool-schema sizes, accumulated
tool-result bytes, references present at each call, or an authoritative UI-click origin
per request. These fields are explicitly null/“not recorded” unless reconstructed for
the frozen case. Persisted final-reference counts are retained as a separate proxy,
never substituted for references in the original request. No protected prompt content
was added to traces or printed. Retrospective exact values cannot honestly be invented.

Observed ranges: input **481–2866 tokens**, payload **2001–12251 bytes**,
**2–7 messages**, **0–12 tools**, successful output **20–192 tokens**.
Successful token usage exists for 89/92 calls; timeout output counts are censored.
The failed prompts contain **1104 / 693 / 1568 tokens**, rather than input-size maxima.
All requests use a catalog default of **192 output tokens**, with no Agent override.
41/89 successful calls consume all 192 tokens; many others finish earlier.
The shared structured response-format object is **2363 canonical UTF-8 bytes**
(reconstructed from this unchanged HEAD; schema hash matches the retained format).

| Failure | Payload bytes | Messages | Tools | Prompt tokens | Last generated lower bound | Last live token/s |
| --- | --- | --- | --- | --- | --- | --- |
| product-centric-en | 4579 | 4 | 2 | 1104 | 148 | 3.6 |
| clearance-boundary-en | 5827 | 2 | 0 | 693 | 149 | 3.8 |
| restricted-boundary | 9263 | 2 | 0 | 1568 | 175 | 4.57 |

Comparison: FAST <10 s: **82 calls**, median 5.553201 s; NORMAL 10–30 s:
**5 calls**, median 18.114654 s; SLOW 30–45 s: **2 calls**, median 37.868700 s;
TIMEOUT: **3 calls**, median 45.041227 s. Completed-request correlations exclude the
three censored timeouts and must not be treated as a causal experiment.

| Dimension | Evidence | Assessment |
| --- | --- | --- |
| Input tokens | Pearson duration r=0.130, n=89; failed prompts below 2866-token maximum | No strong input-size explanation |
| Payload size | r=0.241, n=89; timeout payloads 4579/5827/9263 bytes, maximum 12251 | No exceptional request explosion |
| Actual output tokens | r=0.242, n=89; identical 158-token replay varies from 19.684 to 101.688 s | Weak association; throughput dominates tail; censored failures limit inference |
| Output budget | Constant 192 across all call types | Cannot explain timing regime change by budget variation |
| Tool count | r=0.038, n=89; timeouts have 2/0/0 tools | Not a tool-count outlier |
| Tool-schema size | Historical per-call size absent; frozen case 691 bytes | Inconclusive as independent variable |
| Evidence/result size | Historical per-call size absent; frozen tool result 286 bytes | No large frozen evidence; full historical correlation unavailable |
| Message count/depth | Message r=0.055; prior-turn buckets 0:52 calls/2 timeouts, 1:17/0, 2:21/1, 3:2/0 | No monotonic depth relationship |
| Language | DE 51 calls/0 original timeouts, EN 41/3; all three late in time; reference failures include DE | Language causality unproven and time-confounded |
| Classification | PUBLIC 28/0, INTERNAL 18/2, CONFIDENTIAL 32/0, RESTRICTED 14/1; later reference PUBLIC/CONFIDENTIAL timeouts | No classification-specific mechanism established |
| Journey | Final three journeys fail after throughput drops; same product journey later both passes and fails | Environment/time confounding; no unique journey contract defect proven |
| Call sequence | Failures at in-run calls 1/2/4; both initial and later calls fail | Not restricted to accumulated history |
| Structured output | 55 tool-decision calls/1 timeout, 37 structured/2; direct non-structured request exceeds 45 s | Not necessary for failure; independent contribution unproven |
| Reference-follow-up | Initial typed requests and follow-ups fail after successful reads | Not specific to reference navigation |
| Thinking | Explicit reasoning_effort=none; direct completions contain zero reasoning characters | No observed thinking explanation |

## Generation, throughput and reasoning

Before chronological call 81, median completed-generation throughput is **34.287 token/s**;
from call 81 onward it is **4.354 token/s**. One 192-token successful call already slows
to 29.141 s immediately before the first timeout. Later successful controls include
137 tokens in 32.357 s generation (34.408 s provider) and 163 tokens in 36.307 s
generation (41.329 s provider). The original canceled tasks continue logging token
progress: approximately 3.6, 3.8 and 4.57 token/s near cancellation.

At 3.6 token/s, 158 tokens alone require about **43.9 s**, before prompt/transport work;
at 3.8 token/s, 192 tokens require about **50.5 s**; at 4.57 token/s, 192 tokens require
about **42.0 s** plus several seconds of prefill/adapter work. These are ordinary
bounded outputs, not huge output requests. The direct warm replay provides the actual
successful >45-second proof rather than relying only on this estimate.

For canceled historical requests, native final `load_duration`, `prompt_eval_duration`,
`eval_duration` and exact generated-token totals are unavailable: the client cancellation
prevents a final response/timing summary. Logged intermediate generation establishes
progress, not a zero-token stall or runner crash. Exact full prefill timings cannot be
deduced solely from sampler initialization. For completed requests the retained runner
`print_timing` provides prompt-eval count/duration/rate and generation count/duration/rate.
The exact-shape OpenAI endpoint returns token usage but not Ollama-native duration fields;
the report uses runner timings and measured HTTP wall time, explicitly labeled.

Qwen advertises thinking capability; current requests explicitly send supported OpenAI
`reasoning_effort="none"`. Runner initialization says `thinking = 0`; all five direct
responses have zero reasoning characters. No reasoning setting was changed. Timeout
responses cannot reveal hidden token counters retrospectively, but no positive evidence
links reasoning to these failures.

## Frozen-request replays

The current graph and real authorized read-only MCP discovery/read reconstruct the
first failed product request, stopping at a fake SDK boundary before making a model
call. The frozen file contains only demo-safe request data, outside the repository.
Stable semantic JSON SHA256:
`e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
Shape matches historical telemetry and Ollama tokenization: **4579 bytes, 4 messages,
2 tools, 1104 prompt tokens**, 192 max_tokens, temperature 0, reasoning none.
Context is 3366 characters / 3375 UTF-8 bytes; tool-schema array 691 bytes;
authorized tool-result content 286 bytes; no prior conversation turns.
The historical complete wire payload was deliberately not logged, so byte-identity with
the historical request cannot be cryptographically proven; this is a same-HEAD,
same-demo-read reconstruction with matching measured shape, not an invented large prompt.

| Phase | Attempt | Result | Wall s | Prompt evaluation s / evaluated tokens | Generation s / tokens | Generation token/s |
| --- | --- | --- | --- | --- | --- | --- |
| DIRECT | 1 | PASS | 101.688 | 2.516 / 1104 | 62.722 / 158 | 2.5 |
| DIRECT | 2 | PASS | 49.287 | 0.366 / 4 | 48.887 / 158 | 3.21 |
| DIRECT | 3 | PASS | 24.492 | 0.149 / 4 | 24.319 / 158 | 6.46 |
| DIRECT | 4 | PASS | 19.684 | 0.138 / 4 | 19.525 / 158 | 8.04 |
| DIRECT | 5 | PASS | 21.013 | 0.193 / 4 | 20.801 / 158 | 7.55 |
| ADAPTER | 1 | PASS | 28.441 | 0.161 / 4 | 27.616 / 158 | 5.69 |
| ADAPTER | 2 | PASS | 25.442 | 0.147 / 4 | 25.266 / 158 | 6.21 |
| ADAPTER | 3 | PASS | 22.760 | 0.156 / 4 | 22.582 / 158 | 6.95 |
| ADAPTER | 4 | PASS | 21.688 | 0.186 / 4 | 21.480 / 158 | 7.31 |
| ADAPTER | 5 | PASS | 22.497 | 0.176 / 4 | 22.299 / 158 | 7.04 |
| CONTROL90 | 1 | PASS | 27.927 | 0.175 / 4 | 27.593 / 158 | 5.69 |

All direct responses are HTTP 200, STOP, nonempty narrative, 158 completion tokens,
441 content characters, zero reasoning characters, and the same output digest. This
validates provider completion, not every product-level browser assertion. Direct #1
starts after normal idle expiry: approximately **36.446 s** before runner task start,
then **65.238 s** runner work (2.516 s prompt, 62.722 s generation). It is separately
identified as a cold-start case. Direct #2 is warm: **0.366 s** prompt work and
**48.887 s** generation; load time cannot explain its **49.287 s** completion.

Direct 5-run result: **5/5 completed**, **3/5 within 45 s**. Duration buckets:
<30 s **3**, 30–40 s **0**, 40–45 s **0**, >45 s **2** (one cold, one warm).
Adapter result: **5/5 PASS**, unchanged SDK timeout 45 s. The measurements occurred in
different throughput conditions and are not randomized paired A/B trials; they do not
prove the adapter makes inference faster or that the original defect disappeared.

The **only** 90-second diagnostic client completes in **27.926606 s**, HTTP 200,
158 tokens, valid STOP response. It did not itself cross 45 s and therefore does not
validate 90 s as a tail-latency solution. Valid >45 s responses are demonstrated by
direct #1/#2, not falsely attributed to this control. No second long-timeout control
was performed after the subsequent slowdowns.

## Full Agent replay: all five outcomes

Each execution uses a new browser/run artifact directory, demo-internal, the unchanged
registered `product-centric-en` journey, current model assignment and CPU embedding
policy. No retries/resume, no simultaneous diagnostic model traffic; provider drain
was verified before starting the next journey. Labels are
`sanity01-diagnostic-20261017-agent-1` through `-5` under the existing ignored browser
evidence directory. No original journey artifact was overwritten.

| Attempt | Journey | Required assertions | Optional station action | Elapsed s incl. browser | Diagnostic cause |
| --- | --- | --- | --- | --- | --- |
| 1 | PASS | 3/3 | PASS | 140.500 | none |
| 2 | FAIL | 2/3 | FAIL | 194.176 | provider timeout at optional station normalization; reload secondary |
| 3 | FAIL | 0/3 | NOT_RUN | 77.967 | first provider timeout; missing references/reload secondary |
| 4 | FAIL | 0/3 | NOT_RUN | 78.755 | first provider timeout; missing references/reload secondary |
| 5 | FAIL | 0/3 | NOT_RUN | 78.075 | first provider timeout; missing references/reload secondary |

Strict full-journey reliability: **1/5**. Initial product typed-run reliability is
**2/5**, a different narrower metric. Fifteen actual Agent provider calls match the
remaining fifteen chat HTTP requests after the eleven frozen/control calls.
All four failed calls have APITimeoutError and matching Ollama HTTP 500 cancellation;
raw journey HARNESS_ERROR is secondary to provider failure/reload.
New failing runs:

- Attempt 2: `bb38656d-9b33-41bb-a887-7d78c69acc55`, station finalizer 45.041 s;
- Attempt 3: `073c985b-c44d-49d6-b5b2-991b148c6835`, initial product call 45.021 s;
- Attempt 4: `26fa5d3c-7ccd-4b7b-bbd6-00f1704451cf`, initial product call 45.054 s;
- Attempt 5: `c8693a9b-59f6-45fe-b68d-e49c8fc0aeb3`, initial product call 45.049 s.

Some later canceled tasks contain only tens of generated tokens (e.g. station task
3320: prompt 482, released context 522; product task 3364: prompt 1104, released 1135).
These context differences are partial-progress indicators, not authoritative completion
usage counters. Progress logging begins at 100 generated tokens, so those calls lack
fine-grained progress logs. Short within-request pauses cannot be excluded. A confirmed
zero-progress model stall is not demonstrated; importantly, uniformly healthy throughput
is also not demonstrated. A modest universal deadline increase is therefore unvalidated.

## Queueing, residency and GPU telemetry

Original provider-span overlap: **0**. None of the three original failed chat calls
overlaps an embedding HTTP request. Ollama task admission is roughly a quarter-second
after HTTP start for the original failures, not 45 s spent waiting in a queue.
During the replays the chat HTTP accounting is exact: **26** = 5 direct + 5 adapter +
1 control + 15 Agent calls; **4** new HTTP 500s, all attributed. No unexplained background
chat traffic or queue contention is demonstrated. `api/ps`/health polling does not make
inference requests. The final Knowledge embedding probe occurs after all five journeys.

Chat is loaded once after normal idle expiry; thereafter no unexpected unload/reload,
runner restart, reallocation, CUDA/OOM or crash is observed. Loaded-model size and
digest remain unchanged. **443** active-chat samples all show
`size_vram == size` (5490081790 bytes). Embedding is inactive during isolated chat replays;
its stored parameter remains `num_gpu=0`. The final authenticated Knowledge retrieval
actually loads it on CPU and succeeds, with **0 GPU bytes**, while chat remains GPU.

There are **462** telemetry samples. While chat is resident, dedicated GPU
usage is **7.155–7.719 GiB**;
shared usage **0.921–1.118 GiB**.
Free host RAM is **14.027–19.884 GiB**.
NVIDIA utilization, memory-controller utilization, temperature and power are recorded
continuously, plus Windows per-process GPU-memory counters. Other observed consumers
include Brave, Fork, SnippingTool, Desktop Window Manager, WebView, CrealityPrint and
the diagnostic Chromium/CEF process; none was modified or closed.

The original gate showed shared GPU usage rising from about 0.83 GiB to 1.61–1.63 GiB
as throughput collapsed. Across 86 completed calls with paired samples, generation
throughput versus peak shared memory has **r=-0.8766**; duration versus shared memory
has **r=0.7378**. This is the strongest measured correlate, but time and background
desktop activity are confounded. Later diagnostic failures also occur near 1.0 GiB
shared usage, so no single shared-memory threshold predicts failure.

GPU resource pressure is observed even without embedding GPU allocation. Ollama's
logical “100% GPU” placement does not constitute a measured proof of every WDDM page's
physical residency. Per-process Windows GPU counters must not simply be summed as
independent physical allocations. Driver paging/eviction was not directly traced;
the specific responsible application or a driver bottleneck is unproven.
Sampled clocks are 1935 MHz SM / 6801 MHz memory, P2, PCIe gen3 x4; sampled thermal
and software-power throttle flags are not active. Later timeouts can show GPU 96–100%
with memory-controller utilization around 1–3%; this is recorded, not equated with
healthy inference throughput or a proved hardware cause.

## Root cause decision and recommendation — not implemented

The first failed boundary in original failures 1 and 2 is the **45-second provider
deadline**, not read dispatch/RLS or reference binding. Failure 3 additionally reaches
the **90-second Agent deadline** during a later slow provider call. The HTTP 500s occur
at client cancellation and are not independent proof of internal runner crashes.

Established: normal-size requests continue generating too slowly for the configured
deadlines; a warm valid completion naturally needs >45 s. Rejected as demonstrated
primary explanations: GPU embedding co-residency, oversized input/tool catalog,
enabled reasoning, backend request overlap, unexpected model reload and runner crash.
Unresolved: what causes the large and sometimes sub-1-token/s throughput excursions.
GPU/WDDM residency/desktop pressure is a credible candidate with strong association,
but no causal isolation was permitted/performed by changing other applications.

Do **not** infer that changing 45 to 90 s alone is an adequate fix: the single 90-second
control was fast; later calls show much worse partial progress; Agent 90 s and browser
100 s already interact with provider drain. Request bounding or changing model/thinking
parameters is not justified by the available size/reasoning evidence.

Concrete next step for a separately authorized task: capture driver-level GPU residency,
eviction/paging and per-step token progress during the frozen slow request; compare an
explicitly controlled desktop-GPU baseline. Then decide a coordinated provider/Agent/
browser deadline policy using measured warm and cold latency distributions and cleanup
drain, preserving current authorization, placement and lifecycle guarantees. No timeout,
model setting, application or background-process change is made by this diagnosis.

Production code change: **UNDETERMINED**. Timeout change: **UNDETERMINED**.
Model/config change currently recommended: **NO**. No code/config remediation is ready
to be selected solely from these observations.

## Focused safety, integrity and final state

`python -m pytest tests/unit/test_provider_cleanup_async.py
tests/unit/test_r01_provider_authorization.py -q --tb=short`: **43 PASS** in 7.06 s,
0 FAIL/SKIP (14 cleanup, 29 R01); one existing AnyIO deprecation warning.
API `/ready` **200**; authenticated Knowledge readiness **PASS**; final local Knowledge
CPU-embedding retrieval **PASS** (32.743 s including idle model load). Embedding GPU
allocation **0**; chat still fully GPU. `git diff --check` **PASS**.

All **510** files present in the initial Git tracked-file inventory remain byte-identical,
including the pre-existing staged/unstaged sanity report. Protected persistent counters
remain **100 maintenance tickets / 5 maintenance events / 1 process parameter**, before
and after. Real protected side effects **0**; external model calls **0**; source changes
**0**; historical reports modified **NO**; commits/pushes/deployments **0/0/0**.
Only this new report, its ignored local German counterpart and new diagnostic evidence
are added. Final Compose state remains **20/20 healthy**, Ollama running, no product
restart performed. The stack is left running.

Key evidence: `original-92-request-profiles.json`, `all-92-call-metadata-enriched.json`,
`persisted-run-metadata.json`, `failed-reference-traces.json`, `provider-replays.jsonl`,
`provider-replay-timings.json`, `agent-replays.jsonl`, `diagnostic-agent-spans.json`,
`all-replay-ollama.log`, `replay-telemetry.jsonl`, `focused-safety-tests.log`,
`focused-readiness.json`, `final-file-integrity.json` and `final-diagnostic-metrics.json`.

SANITY-01 remains open. This diagnosis is not a new release certification or a repair.
