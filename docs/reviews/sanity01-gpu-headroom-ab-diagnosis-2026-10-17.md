# SANITY-01 — Controlled GPU-headroom A/B/A diagnosis — 2026-10-17

## Decision

Primary result: **INCONCLUSIVE**. Confidence: **HIGH** in the measured A/B tradeoff;
**LOW** in any new causal attribution of the historical >45-second failures.
Ready for production remediation: **NO**.

All 30 measured requests and all three warmups were FAST (<30 s). Consequently the
predefined decision rule requires INCONCLUSIVE. The historical tail-latency state was
not reproduced. A material GPU-headroom increase was achieved, but partial offload
made this currently fast request substantially slower. This neither proves nor
falsifies WDDM paging as the explanation of the earlier incidents. SANITY-01 remains open.

Authoritative context read and preserved:
[provider diagnosis](sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md) and
[GPU/paging diagnosis](sanity01-gpu-paging-diagnosis-2026-10-17.md).
No production remediation was implemented.

## Frozen state

- Repository `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD
  `d692e489f469777530e629e29ba05708759be5bc`.
- Initial Git status: `AM docs/reviews/final-release-sanity-2026-10-17.md`,
  `A docs/reviews/sanity01-gpu-paging-diagnosis-2026-10-17.md`,
  `A docs/reviews/sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md`.
  These are preexisting documentation states, retained exactly. No source/test/config dirt.
- Windows 11 Pro 10.0.26300, RTX 3070 8192 MiB, NVIDIA 617.42; WDDM 3.2
  as established by the preceding built-in dxdiag capture. Ollama 0.33.2 in the existing container.
- Production `local_quality` is a catalog ID, mapped to `qwen3.5:9b`, Q4_K_M,
  context 4096. All eight Agent/RCA classification assignments remain MANUAL/local_quality.
- Production embedding `qwen3-embedding:0.6b`, context 4096, CPU policy `num_gpu=0`.
  Real authenticated Knowledge reads before and after measurement verify GPU allocation 0.
- Initially no models resident after ordinary idle expiration; production chat was then
  loaded and confirmed 100% GPU. Only the selected chat variant and, when resident,
  the CPU embedding model appear during measurement. Other cached model tags were not loaded.
- Initial NVIDIA VRAM 1906 MiB; host visible RAM 66945652 KiB, free RAM 24233536 KiB.
  Phase host-commit medians were 68.008 / 66.142 / 67.830 GiB (A1/B/A2).
- User GPU applications were recorded and left untouched: examples include DWM,
  SnippingTool, Fork, PyCharm and CrealityPrint. No GPU stress workload or user-load intervention.
- Evidence directory: `D:/Freelance/sanity01-headroom-20261017-125333`.

## Frozen request and context requirement

Semantic SHA256: `e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`.
Original reconstructed nonstream wire SHA256:
`4ca98a67fa1e96d1b45f756a78d172086ec39ff8bcb42ebeaa232462491bbfed`.
Production SSE wire SHA256:
`49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`.
B SSE wire SHA256:
`d9ac34071ef7525486768b3b93f8d3eb482964b349328850038426b357db756a`.

Every call rereads and verifies the frozen semantic hash. SSE adds only `stream=true`;
B additionally substitutes its explicit temporary model routing name. Removing the stream
field and normalizing only that routing name reproduces the exact original semantic hash.
Messages, tools, schemas and their UTF-8 content remain identical. Model weights, template,
system and inherited sampling parameters were verified equal. No prompt simplification.

Exact nonstream usage before the experiment: **1104 input tokens**, including rendered
tools/protocol metadata; output budget **192**. Required total 1296, plus an explicit
128-token guard = 1424. Context 2048 would leave 752 tokens beyond input+maximum output;
both 2048 and 4096 safely fit without truncation. Four messages, two tools, temperature 0,
reasoning_effort=none. Every A/B/A result has prompt length 1104, output 158 tokens,
441 characters, zero reasoning characters, STOP and the identical output hash
`2058fc451e29d892a522a08da72a8e6d0ba491d5456d704eb847ac3f6fc2c39c`.

## Headroom controls and residency

A material threshold of **256 MiB** for both model GPU savings and measured Windows
dedicated reserve gain was declared before probing. Six-second idle windows used ~30 samples.

1. Temporary context-only `local_quality_diag_headroom_20261017_125333`:
   context 2048, same source weights. Logical GPU saving 69206016 bytes (**66 MiB**);
   measured dedicated reserve gain 177004544 bytes (**168.8 MiB**).
   Both are below threshold; it was not used as B and no latency series was claimed for it.
2. The single permitted second control, `local_quality_diag_offload_20261017_125333`:
   **context 4096**, `num_gpu=24`, actual **36%/64% CPU/GPU** split. Context stays
   identical to production, so the selected comparison changes placement only.
   Model GPU allocation falls 5490081790 → 3909217157 bytes, saving **1.472 GiB**.
   Measured adapter dedicated usage falls 7873908736 → 5225664512 bytes;
   reserve rises 716025856 → 3364270080 bytes, **+2.467 GiB**, above threshold.
   Idle shared allocation rises 850112512 → 2160066560 bytes; it does not fall.
   Logical CPU model allocation rises by 2213848021 bytes (**2.062 GiB**);
   Linux runner RSS rises 1139044 → 3442932 KiB (**2.197 GiB**).

Both variants were created locally from installed weights, with no download. Normal
unload/load established one chat runner per phase. Each phase loaded afresh, performed
one identical warmup, then ten sequential measured requests, with no concurrent chat.
All 30 measurements count, no retries or exclusions. Warmups also count separately:
A1 5.061 s, B 21.321 s, A2 5.107 s, all valid. One preceding token-count control
completed in 11.868 s: **34 frozen-request completions total**, 30 in the comparison.

## A1/B/A2 results

| Phase | n | FAST / SLOW / OVER | Median / max (s) | SD (s) | Median / min tok/s | Headroom median / min (GiB) | Shared median / peak (GiB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 10 | 10 / 0 / 0 | 5.563 / 5.743 | 0.477 | 29.00 / 28.09 | 0.661 / 0.661 | 0.792 / 0.793 |
| B | 10 | 10 / 0 / 0 | 17.800 / 18.296 | 0.230 | 8.93 / 8.70 | 3.138 / 3.127 | 2.017 / 2.018 |
| A2 | 10 | 10 / 0 / 0 | 4.417 / 5.298 | 0.269 | 36.62 / 30.46 | 0.672 / 0.672 | 0.799 / 0.800 |

Median B latency is **3.20× A1** and **4.03× A2**. Median generation throughput is
69.2% lower than A1 and 75.6% lower than A2. Its smaller absolute duration standard
deviation is not evidence of tail improvement: all phases have zero SLOW/OVER_BUDGET
requests, and its minimum throughput is substantially worse. Dedicated reserve increases
by about 2.47 GiB, while shared allocation increases by about 1.22 GiB.

A2 again runs quickly. **The requested beneficial A1-slow → B-fast → A2-slow reversal
was not observed.** The reversible cost of partial CPU execution was observed instead.
These data do not justify a production context/model/placement or timeout change.

Full-Agent A/B: **NOT_RUN**. The prerequisite of material direct stability improvement
was not met; running it would add model traffic without satisfying the stated condition.
No SDK call is made in this phase; observed provider timeouts and HTTP 500s: **0**.
The production SDK deadline remains 45 s. Direct completion observation retained the
previous separate HTTP observation ceiling; no longer production-timeout control was used.

## Telemetry and per-request evidence

3795 Windows PDH/NVML samples: median interval 200.480 ms, p95 200.777 ms,
maximum 224.857 ms. GPU dedicated/shared, per-process memory, engines, host commit,
available RAM, working set/private bytes, utilization, clocks, power, temperature and
P-state are retained. Counter registration errors: none. GPU utilization is the
vendor's averaged sample, not a claim of independent instantaneous measurements.

Measured phase median GPU utilization 92 / 47 / 89.5%; memory-controller utilization
46 / 13 / 57.25%; SM clocks 1935 / 1935 / 1920 MHz; temperatures 58.5 / 54 / 63.5 °C;
P2 throughout; power 139.84 / 78.12 / 163.63 W. Lower B throughput coincides with
partial CPU placement, not elevated temperature or reduced SM clocks. No queue, runner
crash or unexpected model reload was observed. Expected phase unload/load is explicit.

SSE measures response batches, not individually tokenized delivery: 139 nonempty batches
for 158 tokens. Generation duration/count/rate comes from matching runner task logs,
not from dividing browser time. TTFT and pauses come from timestamped direct SSE.
Prompt-evaluation timings below can reflect prompt-cache reuse; full input remains 1104.
Resource columns are per-request peaks/minima, remaining telemetry columns are medians.

| Phase/run | Duration s | TTFT s | Prompt eval s* | Generation s | Output tokens | tok/s | Longest batch pause s | Peak dedicated GiB | Min headroom GiB | Peak shared GiB | Host commit GiB | GPU / MC % | SM MHz | °C | P-state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1/warmup | 5.061 | 0.812 | 0.796 | 4.249 | 158 | 36.95 | 0.095 | 7.339 | 0.661 | 0.792 | 68.146 | 90 / 59 | 1942.5 | 54 | 2 |
| A1/1 | 5.498 | 0.144 | 0.126 | 5.354 | 158 | 29.32 | 0.115 | 7.339 | 0.661 | 0.792 | 67.998 | 92 / 46 | 1935 | 55 | 2 |
| A1/2 | 5.547 | 0.148 | 0.130 | 5.400 | 158 | 29.07 | 0.110 | 7.339 | 0.661 | 0.792 | 68.003 | 92 / 46 | 1935 | 56 | 2 |
| A1/3 | 5.562 | 0.150 | 0.132 | 5.413 | 158 | 29.01 | 0.109 | 7.339 | 0.661 | 0.793 | 68.008 | 90 / 43 | 1935 | 57 | 2 |
| A1/4 | 5.729 | 0.155 | 0.138 | 5.573 | 158 | 28.17 | 0.109 | 7.339 | 0.661 | 0.793 | 67.998 | 95 / 47 | 1935 | 57 | 2 |
| A1/5 | 5.743 | 0.153 | 0.133 | 5.589 | 158 | 28.09 | 0.106 | 7.339 | 0.661 | 0.793 | 68.003 | 94 / 45 | 1935 | 58 | 2 |
| A1/6 | 5.719 | 0.160 | 0.136 | 5.559 | 158 | 28.24 | 0.114 | 7.339 | 0.661 | 0.791 | 68.008 | 93.5 / 44 | 1935 | 59 | 2 |
| A1/7 | 5.717 | 0.150 | 0.133 | 5.567 | 158 | 28.20 | 0.119 | 7.339 | 0.661 | 0.791 | 68.008 | 93 / 46 | 1935 | 59 | 2 |
| A1/8 | 5.564 | 0.147 | 0.129 | 5.416 | 158 | 28.99 | 0.116 | 7.339 | 0.661 | 0.791 | 68.013 | 92 / 46 | 1920 | 60 | 2 |
| A1/9 | 4.499 | 0.152 | 0.134 | 4.347 | 158 | 36.12 | 0.089 | 7.339 | 0.661 | 0.792 | 68.053 | 90 / 55 | 1920 | 62 | 2 |
| A1/10 | 4.427 | 0.135 | 0.118 | 4.292 | 158 | 36.58 | 0.085 | 7.339 | 0.661 | 0.792 | 68.014 | 88 / 55 | 1920 | 63 | 2 |
| B/warmup | 21.321 | 3.490 | 3.473 | 17.831 | 158 | 8.80 | 0.356 | 4.873 | 3.127 | 2.011 | 66.297 | 47 / 13 | 1935 | 55.5 | 2 |
| B/1 | 18.138 | 0.233 | 0.215 | 17.906 | 158 | 8.77 | 0.375 | 4.873 | 3.127 | 2.010 | 66.307 | 47 / 13 | 1935 | 55 | 2 |
| B/2 | 17.974 | 0.223 | 0.204 | 17.751 | 158 | 8.84 | 0.393 | 4.873 | 3.127 | 2.011 | 66.258 | 47 / 13 | 1935 | 54 | 2 |
| B/3 | 18.102 | 0.229 | 0.214 | 17.873 | 158 | 8.78 | 0.345 | 4.873 | 3.127 | 2.011 | 66.250 | 47 / 13 | 1935 | 54 | 2 |
| B/4 | 17.779 | 0.227 | 0.209 | 17.552 | 158 | 8.94 | 0.489 | 4.873 | 3.127 | 2.016 | 66.250 | 47 / 13 | 1935 | 54 | 2 |
| B/5 | 17.778 | 0.200 | 0.186 | 17.578 | 158 | 8.93 | 0.371 | 4.862 | 3.138 | 2.017 | 66.144 | 45 / 12 | 1935 | 53 | 2 |
| B/6 | 17.730 | 0.226 | 0.206 | 17.504 | 158 | 8.97 | 0.371 | 4.862 | 3.138 | 2.017 | 66.140 | 45 / 13 | 1935 | 54 | 2 |
| B/7 | 17.821 | 0.241 | 0.222 | 17.580 | 158 | 8.93 | 0.381 | 4.862 | 3.138 | 2.018 | 66.133 | 47 / 13 | 1935 | 53 | 2 |
| B/8 | 18.296 | 0.244 | 0.222 | 18.052 | 158 | 8.70 | 0.365 | 4.862 | 3.138 | 2.018 | 66.092 | 47 / 13 | 1935 | 53 | 2 |
| B/9 | 17.526 | 0.265 | 0.242 | 17.262 | 158 | 9.09 | 0.357 | 4.862 | 3.138 | 2.018 | 66.086 | 46 / 13 | 1935 | 53 | 2 |
| B/10 | 17.638 | 0.206 | 0.189 | 17.433 | 158 | 9.01 | 0.365 | 4.862 | 3.138 | 2.018 | 66.077 | 46 / 13 | 1935 | 54 | 2 |
| A2/warmup | 5.107 | 0.811 | 0.795 | 4.296 | 158 | 36.55 | 0.087 | 7.328 | 0.672 | 0.799 | 67.881 | 88 / 54 | 1935 | 59 | 2 |
| A2/1 | 4.389 | 0.131 | 0.115 | 4.258 | 158 | 36.87 | 0.092 | 7.328 | 0.672 | 0.799 | 67.819 | 91.5 / 60 | 1935 | 61 | 2 |
| A2/2 | 4.365 | 0.132 | 0.117 | 4.232 | 158 | 37.10 | 0.091 | 7.328 | 0.672 | 0.799 | 67.815 | 91 / 60 | 1920 | 62 | 2 |
| A2/3 | 4.497 | 0.149 | 0.126 | 4.348 | 158 | 36.11 | 0.091 | 7.328 | 0.672 | 0.800 | 67.855 | 85 / 52 | 1920 | 62 | 2 |
| A2/4 | 5.298 | 0.144 | 0.128 | 5.154 | 158 | 30.46 | 0.116 | 7.328 | 0.672 | 0.800 | 67.821 | 91 / 46.5 | 1920 | 62 | 2 |
| A2/5 | 4.389 | 0.139 | 0.123 | 4.250 | 158 | 36.94 | 0.092 | 7.328 | 0.672 | 0.800 | 67.876 | 89 / 57.5 | 1920 | 63 | 2 |
| A2/6 | 4.483 | 0.129 | 0.112 | 4.354 | 158 | 36.06 | 0.083 | 7.328 | 0.672 | 0.800 | 67.827 | 88 / 58 | 1920 | 64 | 2 |
| A2/7 | 4.446 | 0.129 | 0.115 | 4.317 | 158 | 36.37 | 0.097 | 7.328 | 0.672 | 0.800 | 67.859 | 90 / 57 | 1920 | 64 | 2 |
| A2/8 | 4.371 | 0.150 | 0.133 | 4.221 | 158 | 37.20 | 0.086 | 7.328 | 0.672 | 0.799 | 67.830 | 93 / 60.5 | 1920 | 65 | 2 |
| A2/9 | 4.360 | 0.131 | 0.114 | 4.230 | 158 | 37.12 | 0.091 | 7.328 | 0.672 | 0.799 | 67.832 | 88 / 56.5 | 1920 | 65.5 | 2 |
| A2/10 | 4.454 | 0.123 | 0.108 | 4.331 | 158 | 36.25 | 0.094 | 7.328 | 0.672 | 0.799 | 67.829 | 89 / 57 | 1920 | 66 | 2 |

Raw reproducibility evidence: `frozen-provider-payload.json`, `models.py`, `aba_replay.py`,
`context-budget.json`, probe JSONs and decisions, `aba-results.jsonl`, per-call token
delivery files, `aba-request-profiles.json`, `aba-summary.json`, runner tasks and
`ollama-current.log`, high-frequency telemetry and model-residency JSONL.
Payload content remains outside the repository; this report includes only safe metadata.

## Interpretation and next step

This experiment successfully changes memory reserve but does not reproduce the failure
state. Partial offload also changes the compute path and increases CPU/shared allocations;
it cannot isolate a pure WDDM-memory effect. Shared allocation alone cannot establish
page migration. The data establish an unfavorable fast-state performance tradeoff for
this one placement, not that GPU headroom can never help under pressure. No unbounded
tuning matrix, user-process termination, quantization or model-family change was performed.

Recommended next step: reproduce the historical slow state with this exact frozen request
and telemetry, then repeat a predeclared matched headroom comparison in that state. Require
improved tail/minimum throughput and a meaningful reversal before selecting a production
change. Production timeout change: **UNDETERMINED**; GPU/model configuration change:
**UNDETERMINED**. Neither is justified by this phase. Timeout increase is not established
as a primary remedy. No readiness for production remediation is claimed.

## Safety, cleanup and integrity

- Provider cleanup **PASS (14)**; R01 **PASS (29)**: **43 passed**, 0 failed/0 skipped,
  one existing Starlette/AnyIO deprecation warning, 6.37 s.
- API `/ready` **200**. Authenticated Knowledge tool discovery and real retrieval
  **PASS**, final retrieval 10.500 s. Embedding GPU allocation **0**, CPU policy intact.
  Final residency: production chat 100% GPU/context4096 and embedding 100% CPU/context4096.
- Only the two newly created temporary aliases were deleted. Installed production model
  tags/digests/metadata and all persistent assignments compare equal before/after;
  no production cache removed, no Ollama configuration or server restart.
- Protected persistent counts unchanged: maintenance tickets **100**, maintenance
  events **5**, process parameters **1**. Protected side effects **0**; external models **0**.
- `git diff --check` and staged diff check **PASS**. The existing sanity report emits
  an LF/CRLF advisory only; it was not rewritten. All **544** originally hashed files
  (including preexisting historical reports/local translations) remain byte-identical.
- New files only: this report and its ignored German counterpart. Production source,
  tests, configuration and existing documentation changes **0**. No commit/push/deploy.
- No architecture behavior changed; architecture diagrams are unaffected.

Final conclusion: **INCONCLUSIVE**, SANITY-01 open, production unchanged.
