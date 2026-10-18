# SANITY-01 — Runtime reset-boundary v2 diagnosis — 2026-10-17

## Decision

**DEGRADED_STATE_NOT_CURRENTLY_ACTIVE.** Initial measured warm state: **HEALTHY**.
Both required measured warm requests satisfy the corrected criteria:
**5.544124 s /29.18 tok/s** and **4.760319 s /34.02 tok/s**.
The mandatory stop branch was taken. No third measurement, degraded D0, R1, R2 or
post-reset Agent control was performed. This is a measured absence of active degradation
at task start, **not** a successful reset or permanent resolution of SANITY-01.
Confidence HIGH in this bounded warm-state result; runtime ownership remains unknown.
Ready for targeted production remediation: **NO**.

Sources read and preserved:

- [Previous reset-boundary diagnosis](sanity01-runtime-reset-boundary-diagnosis-2026-10-17.md).
- [Normal-operation observation](sanity01-normal-operation-observation-2026-10-17.md).
- [Local-provider tail-latency diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md).

Historical SANITY-01 remains **RECURRENT / RELEASE_BLOCKING**: the prior383 chat calls,
48 SDK timeouts,48 Ollama HTTP500s and11 persisted Agent timeouts remain valid. The
authoritative window2 failure remains run `b81aeaae-d798-464d-93ee-b381ba91d48e`, trace
`9cb6b6ce987acd5f9e8313d024f2e99a`, SDK45.056468919 s. Its evidence copy is preserved
outside the repository. This small successful sample does not downgrade the finding.

## Frozen production state

- Repository `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD
  `d692e489f469777530e629e29ba05708759be5bc`. Initial Git changes are preexisting
  review documentation only, recorded in `baseline-status.txt`; no source/test/config dirt.
- Ollama0.33.2, container `1d5de9a37b95a080b775b2cd66ce4e5d561aec02d6aa8ef16e0f6337114eb370`; image `sha256:020e4134285e2ef4d8fd801234176de3b4faadc992a3eb06c8e66a2f9d4c4ba2`.
  Server host PID51640, Linux PID1/start tick3412273; container start
  `2026-10-16T14:46:08.611219707Z`, baseline uptime **30.311 h**, restart count0.
  WSL boot ID `47ea0580-bd62-429c-84cc-4d740acc6d26`, unchanged before/after.
- Windows11 Pro build26300; RTX3070/8192 MiB; NVIDIA617.42 /32.0.16.1742;
  current built-in dxdiag confirms NVIDIA WDDM3.2. Initial native GPU memory1931 MiB.
  Full initial dedicated/shared GPU memory, VMMEM and host RAM are retained in snapshots.
- Chat initially **not resident**. An ordinary Knowledge read first verified embedding
  `qwen3-embedding:0.6b` actually resident on CPU, **0 GPU bytes**. One required chat
  warmup then loaded `qwen3.5:9b`, Q4_K_M, context4096, fully GPU, runner **21811**
  (start tick14327197). This normal initial loading is not an R1 unload/reload intervention.
  The prior CPU embedding runner21717 is not an older chat runner.
- Eight Agent/RCA assignments remain MANUAL/local_quality; source model catalog,
  output budget, prompts, sampling, weights, quantization and context unchanged.
  Production SDK45 s, Agent90 s, retries0, browser/proxy limits unchanged.
- Config hash `3b8c06a6ad85314afcc9f1ffd1eedad799da0960d52b9b7f67c429100d863492`; HostConfig hash
  `f9efb4f878a5c6c9a6fbbc5ae87af2d88ac679f46fc6a40d548d4a1c8afd574a`; persistent volume `ollama` at `/root/.ollama`.
  Container identity/config/resources/mount, production model tags/digests/show metadata,
  assignments, WSL boot and all20 project container identities compare equal before/after.
  No temporary diagnostic model installed or loaded; no user application changed.

Evidence: `D:/Freelance/sanity01-reset-boundary-v2-20261017-230411`.

## Authoritative v2 decision logic

Only measured **warm** requests determine state. All warmups are excluded.

- HEALTHY_WARM: duration<20 s **and** native generation>=20 tok/s.
- DEGRADED_WARM: duration>=30 s **or** native generation<15 tok/s **or** provider timeout;
  a valid direct completion>45 s is also degraded.
- INTERMEDIATE_WARM: neither category.
- Recovery after an intervention requires at least **two consecutive measured warm**
  HEALTHY_WARM results; one short request is insufficient.

The measured requests are both HEALTHY_WARM. Therefore section5's immediate stop applies.
No intermediate-state third request, manufactured load, confirmation request or soak.
There is no active degraded D0 permitting R1. Product controls are conditional on an
actual R1/R2 recovery, so all three registered journeys remain **NOT_RUN**, not PASS.

## Exact frozen request

Semantic SHA256 checked before every direct request:
`e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
Original wire SHA256 `4ca98a67fa1e96d1b45f756a78d172086ec39ff8bcb42ebeaa232462491bbfed`;
equivalent SSE wire SHA256 `49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`.
Only the previously validated `stream=true` transport addition is used. Identical
UTF-8 messages, two tools/schemas,1104 full input tokens, max_tokens192, temperature0,
reasoning_effort=none and production qwen3.5 model. Context4096 throughout.
Cached prompt evaluation of4 tokens is not input truncation.

All three completions: HTTP200, STOP,158 output tokens,441 content characters,
zero reasoning characters, identical text digest
`2058fc451e29d892a522a08da72a8e6d0ba491d5456d704eb847ac3f6fc2c39c`.
The frozen body is the existing same-HEAD/demo-safe reconstruction; historical full
wire bodies were not logged, so byte-identity with the historical window2 request is
not claimed. Exact identity to the specified frozen body is verified.
The direct raw HTTP observer retains its separate240-second read ceiling; no longer-
timeout production client is created. No production instrumentation or response/prompt
logging was added. Native tokens/s comes from matched runner timings, not SSE batch counts.

## Required before/after table

| Phase | Run | Duration s | tok/s | Runner PID | Ollama server | Dedicated VRAM GiB | Shared GPU GiB | VMMEM GiB |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| Initial warmup — excluded | 1 | 16.166336 | 38.35 | 21811 | host51640 / Linux1 | 7.701 | 0.859 | 18.816 |
| Initial measured warm baseline | 1 | 5.544124 | 29.18 | 21811 | host51640 / Linux1 | 7.506 | 0.809 | 18.811 |
| Initial measured warm baseline | 2 | 4.760319 | 34.02 | 21811 | host51640 / Linux1 | 7.506 | 0.810 | 18.811 |
| D0 degraded baseline | NOT_RUN | — | — | — | unchanged | — | — | — |
| R1 warmup | NOT_RUN | — | — | — | unchanged | — | — | — |
| R1 measured | NOT_RUN | — | — | — | unchanged | — | — | — |
| R2 warmup | NOT_RUN | — | — | — | unchanged | — | — | — |
| R2 measured | NOT_RUN | — | — | — | unchanged | — | — | — |

The rows for unexecuted phases explicitly document conditional scope; dashes are not
zero-duration successful tests. Dedicated/shared columns are per-request adapter peaks;
VMMEM is median VM working set, not exclusive Ollama RAM. Actual initial request files
use phase name `D0` for baseline sequencing, but both are healthy and **no degraded D0
was created**. Runner21811 serves warmup and both measurements without restart.

| Request | UTC start | HTTP | TTFT s | Prompt eval s / evaluated tokens | Generation s / output tokens | Longest output-batch pause s | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| INITIAL_WARMUP-1 | 2026-10-17T21:05:10.406216+00:00 | 200 | 12.072619 | 0.819610 / 1104 | 4.093380 / 158 | 0.101447 | WARMUP_EXCLUDED |
| D0-1 | 2026-10-17T21:05:51.740469+00:00 | 200 | 0.163423 | 0.134190 / 4 | 5.380990 / 158 | 0.114028 | HEALTHY_WARM |
| D0-2 | 2026-10-17T21:05:58.400700+00:00 | 200 | 0.145444 | 0.121550 / 4 | 4.614760 / 158 | 0.100261 | HEALTHY_WARM |

| Request | Available RAM GiB | Host commit GiB | GPU / memory-controller % | SM / memory MHz | Temp °C | Power W | P-state |
| --- | --- | --- | --- | --- | --- | --- | --- |
| INITIAL_WARMUP-1 | 18.139 | 67.647 | 58.5 / 1 | 1935 / 6801 | 57 | 59.650 | P2 |
| D0-1 | 17.537 | 68.931 | 91 / 45 | 1935 / 6801 | 57.5 | 139.403 | P2 |
| D0-2 | 17.575 | 68.902 | 89 / 51.5 | 1935 / 6801 | 59 | 154.552 | P2 |

Warmup16.166336 s is retained and excluded entirely from state classification. The
only measured warm native tasks are162 and321; warmup is task0. Per-batch timing,
prompt-eval/generation durations, model residency and runner/server identities are
retained per request. Native output counts are158, not139 SSE delivery batches.
Global PDH/NVML samples target200 ms. VMMEM is a shared VM scope, and clocks/utilization
are vendor samples. No paging, thermal, host or scheduling cause is inferred from
these descriptive resource observations. Missing/ambiguous per-VM GPU attribution is
omitted instead of treated as zero.

## Unexecuted resets and historical idle-unload control

R1 performed **NO**, R1 recovery **NOT_RUN**; R2 performed **NO**, R2 recovery **NOT_RUN**.
No explicit model stop, container/service restart, Docker Desktop/WSL/Windows/driver
reset, unrelated-process termination, watchdog, retry or automatic recycling.
The same server, container and boot identity existed before and after this phase.
The standalone Ollama restart count remains0; all project restart counts remain0.

Earlier15-minute idle windows naturally unloaded models before windows2/3, yet severe
degradation later recurred. Ordinary idle unloading therefore did not permanently
prevent SANITY-01. Today's normal new runner is fast, but no matched degraded-before /
explicit-R1-after comparison exists. Natural elapsed time, model/cache history and
workstation state are not held constant against the previous task. This does not prove
that runner state caused the historical failures, nor that R1 or R2 would recover them.
The corrected criteria are now executable without the previous contradiction; their
healthy-state stop branch is the one actually reached.

Production restart policy **UNDETERMINED**, Ollama runtime remediation **UNDETERMINED**,
timeout change **NO**. No production remediation is justified or implemented by this
phase. Preserve the historical finding and capture a naturally active DEGRADED_WARM
state before a separately authorized recovery-ladder attempt; do not manufacture it.

## Safety and integrity

Provider cleanup14 PASS, R0129 PASS: **43 passed**,0 failed/skipped,6.30 s, one existing
Starlette/AnyIO deprecation warning. API `/ready`200; authenticated Knowledge discovery
and normal retrieval PASS before/after (10.645/11.145 s). Embedding CPU/GPU0 before/after;
46 sampled chat residencies fully GPU and18 embedding observations CPU-only.
Only production chat and embedding appear. Final20/20 services healthy,0 project restarts.

Protected counts unchanged: **100 maintenance tickets /5 maintenance events /1 process
parameter**. Normal read-only Knowledge probes only; no protected approval/action,
ticket creation or hardware command. External model calls0, protected side effects0.
Production SDK calls0, SDK/provider timeouts0, Agent timeouts0: product paths were
**not exercised**, not passed. Exactly3 chat HTTP requests (1 excluded warmup+2 measured)
and2 safe embedding HTTP requests, all200,0 Ollama500. No diagnostic retries or concurrency.

All **553** preexisting source/test/config/versioned/review files,
local review translations and `.env` remain byte-identical. Historical reports unchanged.
`git diff --check` and staged diff check PASS; the old sanity report's LF/CRLF advisory
is preexisting. New repository documentation only: this report and its ignored DE
counterpart; helpers/raw evidence remain outside. No architecture/diagram changes,
commits, pushes or deployments. The healthy local stack remains running.

Evidence index: `analysis-summary.json`, `request-profiles.json`, exact frozen payload,
three original result/event/log sets, `high-frequency-telemetry.jsonl`,
`model-residency.jsonl`, `state-initial.json`, `state-final.json`, `dxdiag.txt`,
`ollama-final-complete.log`, `ollama-http-events.json`, `safety-tests.log`,
`final-stack.json`, protected counters and file-hash/integrity manifests.

Final conclusion: **DEGRADED_STATE_NOT_CURRENTLY_ACTIVE; runtime ownership unresolved;
SANITY-01 historical release blocker retained; no remediation implemented.**
