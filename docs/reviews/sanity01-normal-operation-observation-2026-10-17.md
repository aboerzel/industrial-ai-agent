# SANITY-01 — Normal-operation reliability observation — 2026-10-17

## Decision

**RECURRENT**. Recommended release treatment for SANITY-01: **BLOCK**.
Historical timeout evidence remains valid: **YES**. Current root cause known: **NO**.
No production remediation was implemented or validated.

Three separated observation windows executed the existing 12-journey local Real-Model
gate, the original16 supported reference actions, and three normal retrieval→chat
cycles each, sequentially and without retries. Normal workstation applications and
production resources remained untouched. This is observation, not a new architecture
review or unconditional release certification.

## Baseline

Repository `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD
`d692e489f469777530e629e29ba05708759be5bc`. Existing documentation-only Git differences
were preserved; no source/test/config changes. Historical reports were not edited.
Evidence: `D:/Freelance/sanity01-normal-observation-20261017-181856`.

Sources: [original diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md),
[GPU/paging](sanity01-gpu-paging-diagnosis-2026-10-17.md),
[headroom A/B/A](sanity01-gpu-headroom-ab-diagnosis-2026-10-17.md), and
[production soak](sanity01-tail-soak-diagnosis-2026-10-17.md).

Production remained `local_quality` / `qwen3.5:9b` / Q4_K_M, context4096;
embedding `qwen3-embedding:0.6b`, CPU `num_gpu=0`. SDK deadline45 s, Agent deadline90 s,
zero retries, assignments, prompts, output budget and Docker/Ollama configuration unchanged.
No restart/unload/headroom intervention, temporary model, synthetic concurrency or direct soak.

## Separation and ordinary-operation scope

At least15 minutes without diagnostic model requests separated the **end** of each
completed window from the next readiness check. The actual intervals are:

[
  {
    "between": "1/2",
    "seconds": 901.8650779724121,
    "previous_finished": "2026-10-17T16:34:44.9067114Z",
    "next_readiness": "2026-10-17T16:49:46.771789+00:00"
  },
  {
    "between": "2/3",
    "seconds": 914.3096430301666,
    "previous_finished": "2026-10-17T17:24:40.7177350Z",
    "next_readiness": "2026-10-17T17:39:55.027378+00:00"
  }
]

The stack remained available during these real elapsed pauses. Only read-only health
checks and evidence processing occurred. User applications were not controlled; ordinary
idle expiry and natural workload changes were allowed. Separated windows are not proof
of statistical independence, nor proof that a user was actively working throughout.

## Window results

| Window | Model activity UTC | Real-Model | Assertions | References | Retrieval/chat | Calls | Median / p90 / max s | ELEVATED / SLOW / TIMEOUT | SDK / Agent timeout | Ollama500 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-17T16:21:06.088231+00:00 – 2026-10-17T16:34:19.997075+00:00 | 12/12 | 59/59 | 16/16 | 3/3 | 153 | 3.940 / 4.426 / 7.199 | 0 / 0 / 0 | 0 / 0 | 0 |
| 2 | 2026-10-17T16:49:58.814956+00:00 – 2026-10-17T17:24:10.489148+00:00 | 10/12 | 56/59 | 7/16 | 0/3 | 128 | 7.618 / 45.024 / 45.061 | 5 / 9 / 13 | 13 / 0 | 13 |
| 3 | 2026-10-17T17:40:07.130791+00:00 – 2026-10-17T18:45:38.516896+00:00 | 1/12 | 18/59 | 8/16 | 0/3 | 102 | 41.215 / 45.053 / 45.059 | 5 / 41 / 36 | 35 / 11 | 35 |

Latency classes: NORMAL<20 s, ELEVATED20–<30 s, SLOW30–<45 s, TIMEOUT≥45 s or SDK timeout.
SDK errors and Agent deadline errors are additionally counted by their actual trace
classification, not inferred from an aggregate browser duration. p90 uses nearest rank.
Final Agent timeout counts come from authorized reads of persisted run error codes,
saved in `persisted-run-states.json` and the validated aggregate summaries. The initial
span-only summary did not include persisted Agent deadline codes and is not authoritative
for that count. In window3 one successful HTTP200 call lasted45.043 s: it belongs to the
requested >=45-s latency bucket but is not counted as an SDK timeout. SDK and Agent
failure counts may overlap at run level and must not be summed as unique failed runs.

| Window | PRODUCT_DEFECT | MODEL_VARIANCE | HARNESS_ERROR* | SECURITY_DEFECT | BLOCKED_BY_PROVIDER | INFRASTRUCTURE_ERROR |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| 3 | 1 | 1 | 8 | 0 | 1 | 0 |

*Categories above describe executed product journeys. Separate external observation
setup issues in window1 are retained: Docker UTF-8 decoding, an anchored selector
matching zero tests, a Windows ESM import path, and PowerShell date-object conversion
in the gap scheduler. They occurred before the affected action/cycle or model request;
only external observation commands were corrected. No failed product journey/reference
action was repeated. The original logs are preserved. Window1's actual16-action matrix
uses `reference-playwright-actual.json`; its three actual retrieval cycles follow it.
Later windows use the corrected external command from their first execution.

## Gate failures retained

At least one gate did not pass. This observation does not claim a fully green release gate. The raw failure, its initiating cause and provider/Agent outcomes remain separate. The release-treatment recommendation above is scoped to SANITY-01; no failed validation is silently upgraded.

| Window | Journey | Raw category | Required assertions not passed |
| --- | --- | --- | --- |
| 2 | product-centric-en | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:reference: BLOCKED / MODEL_VARIANCE; step-4:reload: FAIL / HARNESS_ERROR |
| 2 | station-discovery | HARNESS_ERROR |  |
| 3 | clearance-boundary-en | BLOCKED_BY_PROVIDER | step-1:typed: FAIL / BLOCKED_BY_PROVIDER |
| 3 | clearance-boundary | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:switch-user: BLOCKED / MODEL_VARIANCE; step-4:switch-user: BLOCKED / MODEL_VARIANCE; step-5:typed: FAIL / BLOCKED_BY_PROVIDER; step-7:typed: FAIL / BLOCKED_BY_PROVIDER; step-8:reload: FAIL / HARNESS_ERROR |
| 3 | documentation | PRODUCT_DEFECT | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:document: BLOCKED / MODEL_VARIANCE; step-3:switch-user: BLOCKED / MODEL_VARIANCE; step-5:switch-user: BLOCKED / MODEL_VARIANCE; step-6:typed: FAIL / MODEL_VARIANCE; step-7:reload: FAIL / PRODUCT_DEFECT; step-8:pdf: FAIL / PRODUCT_DEFECT |
| 3 | healthy-station-de | HARNESS_ERROR | step-2:reference: FAIL / BLOCKED_BY_PROVIDER; step-4:reload: FAIL / HARNESS_ERROR |
| 3 | healthy-station-en | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:typed: FAIL / BLOCKED_BY_PROVIDER; step-3:reference: BLOCKED / MODEL_VARIANCE; step-4:reload: FAIL / HARNESS_ERROR |
| 3 | product-centric-en | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:reference: BLOCKED / MODEL_VARIANCE; step-4:reload: FAIL / HARNESS_ERROR |
| 3 | product-history | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:reference: BLOCKED / MODEL_VARIANCE; step-3:typed: FAIL / BLOCKED_BY_PROVIDER; step-4:reload: FAIL / HARNESS_ERROR |
| 3 | restricted-boundary | MODEL_VARIANCE | step-3:typed: FAIL / MODEL_VARIANCE |
| 3 | s04-investigation-en | HARNESS_ERROR | step-1:typed: FAIL / INFRASTRUCTURE_ERROR; step-2:typed: FAIL / BLOCKED_BY_PROVIDER; step-3:reference: BLOCKED / MODEL_VARIANCE; step-4:reload: FAIL / HARNESS_ERROR |
| 3 | s04-investigation | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:reference: BLOCKED / MODEL_VARIANCE; step-3:document: BLOCKED / MODEL_VARIANCE; step-4:typed: FAIL / BLOCKED_BY_PROVIDER; step-5:reload: FAIL / HARNESS_ERROR |
| 3 | station-discovery | HARNESS_ERROR | step-1:typed: FAIL / BLOCKED_BY_PROVIDER; step-2:reference: BLOCKED / MODEL_VARIANCE; step-3:typed: FAIL / BLOCKED_BY_PROVIDER; step-5:reload: FAIL / HARNESS_ERROR |

Raw journey categories are preserved rather than recast as an independently proven new
defect. Missing references, blocked follow-ups and reload assertions can follow an
unsuccessful preceding run. Provider evidence and persisted run states identify actual
SDK/Agent deadline failures separately; this observation neither repairs the harness
nor claims that all failed assertions share one cause. Every reference test has exactly
one attempt, including failures in its prerequisite. Some such failures prevent the
actual reference action from being sent.

In window2, station-discovery retained a mandatory discovery-inventory smoke failure:
`page.waitForResponse` exceeded its existing30000 ms wait for the demo-internal station
inventory request. The main journey assertions and optional reference step passed.
Raw category **HARNESS_ERROR** remains unchanged. A naturally slow successful provider
request (HTTP200, about25.416 s,86 generated tokens at3.42 tok/s) was preserved with
the surrounding resource observations. Browser wait expiry is not itself an SDK45 s
or Agent90 s timeout. No timeout/test change or repeat was performed. Window2's complete
trace correlation is authoritative for its actual provider/Agent failure counts.

## Authoritative naturally occurring failure

Window2 recurred during the ordinary `product-centric-en` journey, without replay:

- Run `b81aeaae-d798-464d-93ee-b381ba91d48e`, execution trace
  `9cb6b6ce987acd5f9e8313d024f2e99a`.
- Existing canonical API message: `Show me the production history for P4901.`;
  demo-internal, first tool-decision provider call after the bound product-history read.
- SDK span **17:00:40.811789–17:01:25.868258 UTC**, **45.056468919 s**,
  `APITimeoutError`, LOCAL/Ollama/qwen3.5:9b. Request4579 bytes,4 messages,2 tools,
  **1104 input tokens**. Persisted state confirms `llm_provider_unavailable`.
- Matching Ollama HTTP500 at **17:01:25.869091632 UTC**, **45.045737263 s**.
  Automatic first-failure snapshot timestamp **17:01:26.062409 UTC**.
- Nearby existing counter sample: dedicated **8262918144 bytes**, shared
  **1117315072 bytes**; chat fully GPU and embedding CPU-only when resident.
  Raw host CPU/RAM/commit values and previous30-second observations remain available.
- Immediately preceding successful provider call: run
  `c8b2b4a8-8447-485c-9db8-0e28bd2876d2`, **11.356151522 s**,
 1187 input/192 output tokens, native generation **35.95 tok/s**.
- Cancelled-call final token usage and native generation timing/rate were not emitted.
  Runner release at17:01:34.891206 reported context1170 versus prompt1104:66 additional
  context positions by release, after SDK cancellation. This is not exact output usage
  at the deadline and is not substituted for native tokens/s.

Current full raw provider request bodies are not retained by existing privacy-preserving
instrumentation. The exact canonical API request, identity, run/trace, shape and timing
are preserved; a historical frozen shape reference is not claimed as a current wire
capture. No new production logging, longer-timeout replay or synthetic probe was added.
`first-provider-failure-snapshot.json`, `immediate-sdk-timeout-trace.json`,
`first-natural-sample-summary.json`, `authoritative-natural-failure.json` and full
window logs preserve this sample and preceding success. Later failures do not overwrite it.

## Provider evidence

Total local chat provider calls: **383**. Median **4.854 s**,
nearest-rank p90 **45.038 s**,
maximum **45.061 s**. Actual SDK timeouts
**48**; Agent timeouts
**11**; Ollama HTTP500
**48**.

Each `window-N/provider-calls.json` retains timestamp, journey/action/cycle association,
run/trace/call identity, duration/result, SDK-timeout status, input/output tokens where
reported, native generation throughput and timings, matched Ollama HTTP result, model
residency and nearest timestamped dedicated/shared GPU and host-memory/CPU observation.
`execution-spans.json` preserves bounded semantic `agent.run` execution traces, including
reference prerequisites. Ollama logs preserve native prompt/generation timing and token
progress. Resource observations use existing Windows counters and Ollama state; nearby
samples are labeled with their temporal distance and are not claimed as exact per-token
measurements. No new production instrumentation or production prompt, credential or
response logging was added. Authorized browser/API fixture evidence stays local.

All model calls are checked for LOCAL/Ollama routing. Embedding is a separate role;
its CPU residency and existing retrieval/tool evidence are retained. Real-Model browser
artifacts are new ignored directories `sanity01-observation-20261017-181856-w1` through
`-w3`. Reference tests use live mode, one worker, retries0 and exactly indices1–16.
Retrieval/chat cycles use the existing canonical `Investigate QUALITY-09.` prompt and
Demo confidential identity, require successful `search_documentation` evidence and
successful chat completion, and drain before the next cycle.

The provider-call latency tables above count chat calls, consistently with the historical
local-chat diagnostic counts. Separate embedding HTTP requests are also preserved from
the existing logs, not silently included as generated-text token throughput:

| Window | CPU embedding calls | HTTP failures | Median s | Max s |
| --- | --- | --- | --- | --- |
| 1 | 18 | 0 | 0.053 | 1.359 |
| 2 | 16 | 0 | 0.063 | 1.640 |
| 3 | 12 | 0 | 0.063 | 4.914 |

`embedding-provider-evidence.json` stores each existing HTTP status/time/duration,
unique execution-interval association where available, and nearby resource sample.
Missing input-token metadata remains unavailable; output-text tokens/s is not applicable
to embedding vectors. Total observed provider HTTP calls including embedding:
**429**, comprising **383 chat** and
**46 embedding** calls.

## Safety and integrity

[
  {
    "window": 1,
    "chat_samples": 272,
    "chat_not_full_gpu": 0,
    "embedding_samples": 271,
    "embedding_gpu_nonzero": 0,
    "healthy_before": 20,
    "healthy_after": 20,
    "safety_tests": "43 passed",
    "assignments_unchanged": true,
    "model_metadata_unchanged": true,
    "protected_counts_unchanged": true
  },
  {
    "window": 2,
    "chat_samples": 700,
    "chat_not_full_gpu": 0,
    "embedding_samples": 510,
    "embedding_gpu_nonzero": 0,
    "healthy_before": 20,
    "healthy_after": 20,
    "safety_tests": "43 passed",
    "assignments_unchanged": true,
    "model_metadata_unchanged": true,
    "protected_counts_unchanged": true
  },
  {
    "window": 3,
    "chat_samples": 1325,
    "chat_not_full_gpu": 0,
    "embedding_samples": 612,
    "embedding_gpu_nonzero": 0,
    "healthy_before": 20,
    "healthy_after": 20,
    "safety_tests": "43 passed",
    "assignments_unchanged": true,
    "model_metadata_unchanged": true,
    "protected_counts_unchanged": true
  }
]

Every window verifies20/20 services healthy, Agent API readiness200 and Knowledge protocol
readiness. Provider cleanup14 and R0129 tests pass in each window (43 tests/window).
Model assignments and metadata compare exactly before/after and across all windows.
Protected persistent counts remain tickets100, maintenance events5, process parameters1.
Observed MCP capabilities are exclusively `get_machine_status`, `get_product_history`,
`get_product_overview`, `get_station_overview`, `list_products`, `list_stations`, and
`search_documentation`; no protected-action capability was observed.
External model calls0; real protected side effects0. No commit, push or deployment.
Existing file hashes, `.env` and prior English/German review reports remain unchanged.
Final Git status also shows two pre-existing diagnostic reports staged that were initially
untracked; this observation issued no Git staging command. Their bytes remain identical
to the initial hash manifest; this is not recorded as a source/configuration change.
Only this new report and its ignored German counterpart are added inside documentation;
diagnostic evidence remains outside the repository/new ignored browser directories.

## Interpretation and release recommendation

A genuine provider/Agent timeout recurred during ordinary supported operation. Preserve the new naturally occurring sample as authoritative and retain SANITY-01 as an active release blocker. No artificial replay or remediation is authorized by this observation.

The earlier valid>45 s responses and actual SDK failures are not invalidated. Root
cause remains unknown. Observed counts describe only these windows under the recorded
workstation state; they do not prove a permanent fix or guarantee future reliability.
No specific production timeout, model/configuration or resource change has been
validated by this observation. The next targeted diagnostic/remediation decision must
use the captured natural failure rather than assume a cause; no remediation is
implemented here. Recurrence alone does not establish that raising a timeout or
changing the model is the correct remedy.
