# SANITY-01 — Runtime reset-boundary diagnosis — 2026-10-17

## Result

Primary classification: **INCONCLUSIVE**. Initial measured state: **DEGRADED**.
No recovery intervention was performed. SANITY-01 remains **RECURRENT / RELEASE_BLOCKING**;
the historical failures are not reopened or invalidated. The runtime boundary owning
the degraded state remains unknown. Confidence in the timing/token observations is
HIGH; confidence in any boundary/root-cause attribution is LOW. Ready for targeted
production remediation: **NO**.

The mandatory confirmation completed in **19.636073 s**, below the explicit20-second
stop boundary, but native generation remained **8.09 tok/s**, below the independently
defined10-token/s degradation threshold. The experiment stopped before R1 as requested
by the duration rule. This does **not** demonstrate that the defined degraded state
disappeared. Calling it full `TRANSIENT_RECOVERY_BEFORE_INTERVENTION` would conceal the
still-positive throughput criterion. No boundary can be isolated without an intervention;
the permitted INCONCLUSIVE category therefore describes the evidence honestly.

## Source of truth and authoritative sample

All six current reports were read and preserved:

- [Final release sanity](final-release-sanity-2026-10-17.md)
- [Local-provider diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md)
- [GPU/paging diagnosis](sanity01-gpu-paging-diagnosis-2026-10-17.md)
- [Headroom A/B/A](sanity01-gpu-headroom-ab-diagnosis-2026-10-17.md)
- [Production-state soak](sanity01-tail-soak-diagnosis-2026-10-17.md)
- [Normal-operation observation](sanity01-normal-operation-observation-2026-10-17.md)

Authoritative natural failure remains normal-operation **window2**, product-centric-en:
run `b81aeaae-d798-464d-93ee-b381ba91d48e`, execution trace
`9cb6b6ce987acd5f9e8313d024f2e99a`, SDK45.056468919 s,
`APITimeoutError`, matching Ollama HTTP50045.045737263 s. Its canonical API request is
`Show me the production history for P4901.`; the bound product-history read succeeded.
The preceding successful call took11.356151522 s, native35.95 tok/s. Source evidence
was copied to `authoritative-window2-failure.json`; original files are untouched.
The prior observation's383 chat calls,48 SDK failures,48 HTTP500s and11 Agent timeouts
remain valid. None is replaced by the four new direct results.

## Frozen production baseline

- Repository `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD
  `d692e489f469777530e629e29ba05708759be5bc`.
- Preexisting Git differences are staged/unstaged historical review documentation,
  recorded in `baseline-status.txt`; no implementation/test/config differences.
- Windows11 Pro build26300; NVIDIA RTX3070,8192 MiB; driver617.42 /32.0.16.1742;
  current built-in dxdiag confirms NVIDIA **WDDM3.2**.
- Ollama0.33.2, container `1d5de9a37b95a080b775b2cd66ce4e5d561aec02d6aa8ef16e0f6337114eb370`, image `sha256:020e4134285e2ef4d8fd801234176de3b4faadc992a3eb06c8e66a2f9d4c4ba2`.
  Started `2026-10-16T14:46:08.611219707Z`, about **28.225 hours** uptime at baseline;
  host PID **51640**, Linux server PID **1**, process-start tick **3412273**,
  WSL boot ID `47ea0580-bd62-429c-84cc-4d740acc6d26`. Restart count0.
- Persistent model volume `ollama`, mounted at `/root/.ollama`, preserved. Container
  Config hash `3b8c06a6ad85314afcc9f1ffd1eedad799da0960d52b9b7f67c429100d863492` and HostConfig hash
  `f9efb4f878a5c6c9a6fbbc5ae87af2d88ac679f46fc6a40d548d4a1c8afd574a` compare exactly before/during/after. Secret values
  are neither printed nor included in the report.
- Eight Agent/RCA assignments remain MANUAL/local_quality. Chat resolves to
  `qwen3.5:9b`, Q4_K_M, temperature0, context4096, fully GPU. Embedding remains
  `qwen3-embedding:0.6b`, CPU `num_gpu=0`, GPU allocation0. No temporary diagnostic
  model is installed or loaded. Production model tags/digests/show metadata are equal
  before/during/after.
- SDK45 s, max retries0 (`openai_compatible.py`); Agent90 s (`api/app.py` default),
  existing browser/proxy deadlines unchanged. No source/configuration/prompt/budget,
  context/quantization/assignment, Docker resource, retry or concurrency change.
- Initial native NVIDIA usage1911 MiB; VMMEM working set12235563008 bytes before the
  chat cold load. Full initial RAM/commit and GPU state are in the snapshots.
- All20 project services healthy, API `/ready`200 and authenticated Knowledge ready
  before/after. Initial/final normal Knowledge retrieval succeeded in12.130/12.009 s,
  verifying actual CPU embedding residency, GPU bytes0. Chat initially nonresident
  after ordinary idle behavior; there was no artificial chat warmup before D0.

Evidence directory: `D:/Freelance/sanity01-reset-boundary-20261017-205734`.

## Exact frozen request and four executions

Semantic SHA256, verified before **every** request:
`e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
Original nonstream wire SHA256
`4ca98a67fa1e96d1b45f756a78d172086ec39ff8bcb42ebeaa232462491bbfed`;
equivalent SSE wire SHA256
`49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`.
Only the previously validated `stream=true` transport field is added. UTF-8 messages,
two tools/schemas, sampling, reasoning_effort=none, production model and max_tokens192
are unchanged. Full input1104 tokens in every native task; all four outputs158 tokens,
441 characters, zero reasoning, STOP, identical text hash
`2058fc451e29d892a522a08da72a8e6d0ba491d5456d704eb847ac3f6fc2c39c`.
Cached prompt evaluation of4 tokens does not mean truncated1104-token input.

The frozen body is the unchanged prior same-HEAD/demo-safe reconstruction. Historical
full wire bodies were not retained, so cryptographic equality to the natural window2
wire request is not claimed. Exact equality to the specified frozen request is verified.
The raw HTTP observer retains the existing240-second read ceiling; no application SDK
client or production deadline is extended. Four sequential requests, no retries, no
concurrent chat and no extra soak. No production instrumentation was added.

| Request | HTTP | Duration s | TTFT s | Prompt eval s / evaluated tokens | Generation s / tokens | Native tok/s | Longest output-batch pause s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D0-1 | 200 | 59.119280 | 38.897413 | 2.051450 / 1104 | 20.221150 / 158 | 7.76 | 0.602315 |
| D0-2 | 200 | 21.003249 | 0.194501 | 0.169440 / 4 | 20.808390 / 158 | 7.55 | 0.600199 |
| D0-3 | 200 | 19.649265 | 0.212322 | 0.180690 / 4 | 19.436650 / 158 | 8.08 | 0.402077 |
| CONFIRM-1 | 200 | 19.636073 | 0.232481 | 0.201760 / 4 | 19.403010 / 158 | 8.09 | 0.556979 |

Direct request identities are D0-1/2/3 and CONFIRM-1, native task IDs0/162/321/480.
Raw direct requests do not allocate Agent runs or execution traces; run/trace ID is
NOT_APPLICABLE rather than an invented Agent identity. All four HTTP200s match native
task timings. D0-1 exceeds45 s because approximately **36.844 s before runner task
start** is followed by2.051 s prompt evaluation and20.221 s generation. It is a cold
load, not a new warm>45-s reproduction. D0-2/3 still meet the **<10 tok/s** degradation
criterion, independently of that cold-load contribution. Previous severe warm tails
remain established by historical evidence.

D0-3's preceding successful request is D0-2:21.003 s/7.55 tok/s. The immediately preceding
current success before CONFIRM is D0-3:19.649 s/8.08 tok/s. Token-progress logs show
continued generation; no zero-progress stall or runner crash is demonstrated.

## D0 resource and identity comparison

| Request | Peak dedicated GiB | Min dedicated reserve GiB | Peak shared GiB | VMMEM median working set GiB | Available RAM median GiB | GPU / memory-controller median % | SM / memory MHz | Temp °C | Power W | P-state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D0-1 | 7.531 | 0.469 | 1.087 | 17.031 | 18.059 | 57 / 2 | 1935 / 6801 | 61 | 62.506 | P2 |
| D0-2 | 7.530 | 0.470 | 0.913 | 18.320 | 18.548 | 98 / 10 | 1935 / 6801 | 60 | 92.177 | P2 |
| D0-3 | 7.532 | 0.468 | 0.916 | 18.325 | 18.552 | 97 / 15 | 1935 / 6801 | 58 | 93.407 | P2 |
| CONFIRM-1 | 7.532 | 0.468 | 0.914 | 18.318 | 18.590 | 99 / 9 | 1935 / 6801 | 54 | 91.618 | P2 |

Dedicated/shared values are actual Windows adapter counters; VMMEM is VM-level working
set, not exclusive Ollama memory. NVML utilization/clocks/power are vendor samples,
not instruction-level measurements. Output batches are not exact individual tokens;
token rates/counts come from native runner metrics. Raw200-ms PDH/NVML observations,
per-batch timestamps and state snapshots are retained. Ambiguous per-VM GPU-allocation
aggregates are omitted, not interpreted as zero.

`state-D0-active.json` captured the unchanged Ollama server and chat runner **21516**
(start tick13576000) during D0-2. The same chat runner serves all four requests and is
still present in the final snapshot. Its initial creation during natural cold loading
is distinct from an R1 reset. Linux PID21424 before D0-1 was the CPU embedding runner,
not an older chat runner. Embedding is nonresident during part of the chat series;
where resident it is always CPU. No explicit embedding stop was issued.90 observed
chat residencies are fully GPU;15 embedding observations have0 GPU bytes.

## Stop decision and unexecuted recovery steps

The task defines degradation as any duration>=30 s **or generation<10 tok/s**, but
separately directs stopping the ladder when the confirmation finishes<20 s.
CONFIRM-1 satisfies **both** the stop predicate and the degradation predicate.
The more restrictive action rule was honored: **no R1, no R2**. Duration-only threshold
recovery is observed; full healthy throughput recovery is not. This conflict prevents
an honest positive reset-boundary or complete-transient-state classification.

| Step | Performed | Measured comparison | Recovery result |
| --- | --- | --- | --- |
| R1 chat unload/reload only | NO | NOT_RUN | NOT_TESTED |
| R2 Ollama-only restart | NO | NOT_RUN | NOT_TESTED |
| Post-R2 product-centric-en / restricted-boundary | NO | Conditional prerequisite not met | NOT_RUN |
| Three initial healthy-state Agent controls | NO | Initial DEGRADED_STATE branch selected | NOT_RUN |

No reset, warmup-after-reset, automatic retry, application control or below-Ollama reset
was performed. No WSL/Docker Desktop/Windows/driver/user-process intervention. Config,
server identity, storage mount and all20 Compose container IDs remain unchanged. R1/R2
must not be marked failed or recovered when they were not executed. Product SDK calls0,
SDK timeouts0 and Agent timeouts0 mean **not exercised**, not a product reliability pass.
New direct HTTP500s0. Two safe embedding-readiness calls also returned HTTP200.

## Idle unload history and root-cause implication

The previous observation explicitly recorded empty model residency before windows2
and3 after15-minute pauses, yet both later degraded. This run again began without
resident chat and then showed7.55–8.09 tok/s warm throughput. Ordinary unloading does
not establish prevention of later degradation. However, the requested additional
condition **explicit R1 fails to recover immediately** was not tested here. Therefore
the combined argument excluding simple runner state is unavailable. R1, R2 and deeper
host/WSL/GPU boundaries cannot be distinguished. Shared memory/clocks are descriptive
observations, not a new paging or scheduling causal proof.

Recommended next step: in a separately authorized follow-up, make the confirmation
rule consistent about whether<20 s overrides persistent<10 tok/s. Then apply R1/R2 only
under the agreed persistent-degradation criterion, preserving this frozen request.
No further traffic is started here. Timeout change recommended **NO**; production
restart policy **UNDETERMINED**; Ollama runtime remediation **UNDETERMINED**. No upgrade,
watchdog, periodic restart, recycling, model or timeout policy is validated.

## Safety, integrity and evidence

Provider cleanup14 PASS, R0129 PASS: **43 passed**,0 failed/skipped,6.27 s, one existing
Starlette/AnyIO deprecation warning. API readiness PASS, Knowledge readiness/retrieval
PASS, CPU embedding PASS. Final20/20 healthy, all project restart counts0; standalone
Ollama restart count0. Assignments/model metadata/configuration/storage unchanged.
Protected counts before/after **100 maintenance tickets /5 maintenance events /1 process
parameter**. No protected-action capability, approval, real ticket or hardware action
was invoked. External model calls0; protected side effects0; source/test/config changes0.
Commits/pushes/deployments0. No production remediation implemented.

All **551** preexisting versioned/source/test/config/review files,
local review translations and `.env` remain byte-identical. Historical reports were not
edited. `git diff --check` and staged diff check PASS; the old sanity report's LF/CRLF
advisory is preexisting. Only this new report and its ignored DE counterpart are added.
No architecture/diagram behavior changed. The healthy stack is left running.

Authoritative current metrics: `direct-results-final.json`, `analysis-summary-final.json`,
native bounded `ollama-current.log`, per-request event/result files,
`high-frequency-telemetry.jsonl`, `model-residency.jsonl`, initial/D0/final snapshots,
`final-stack.json`, protected counters, safety log and integrity manifest.
Initial per-call `--since` reads returned empty logs; their null-metric files are
preserved. Native metrics were recovered from the retained bounded complete log,
matched by actual request interval/task/input/output. No inference was rerun to obtain
missing metadata. Earlier generic per-VM allocation aggregates are not authoritative;
the final files omit them. This evidence processing changed no production code.

Final conclusion: **INCONCLUSIVE reset boundary; SANITY-01 remains unresolved and
release-blocking; no production remediation is ready from this phase.**
