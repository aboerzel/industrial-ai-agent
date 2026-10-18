# SANITY-01 — Event-triggered Runtime Reset Boundary — 2026-10-18

## Result

**DEGRADED_STATE_NOT_CAPTURED.** All four permitted separated windows completed. All 8 measured warm requests were HEALTHY_WARM. No ordinary chat activity occurred during the observation. No D0 trigger, R1 unload, R2 restart, confirmation probe, or post-reset product control was performed. This run identifies no reset ownership boundary. Historical SANITY-01 remains RECURRENT / RELEASE_BLOCKING; non-reproduction does not establish a fix.

## Scope and sources

This was a bounded event-triggered diagnostic, not a soak, remediation, or new release certification. Current source reports were [runtime-reset v2](sanity01-runtime-reset-boundary-v2-diagnosis-2026-10-17.md) and [normal-operation observation](sanity01-normal-operation-observation-2026-10-17.md). The authoritative historical Window 2 sample remains run `b81aeaae-d798-464d-93ee-b381ba91d48e`, trace `9cb6b6ce987acd5f9e8313d024f2e99a`; historical aggregate 48 SDK timeouts / 48 Ollama HTTP 500 / 11 persisted Agent timeouts is unchanged.

## Baseline

- Repository: `D:/Freelance/industrial-ai-agent`; branch `main`; HEAD `d692e489f469777530e629e29ba05708759be5bc`.
- Observation: 08:53:06–09:54:43 CEST, 2026-10-18. The first sparse check followed an initial 15-minute passive-only period; subsequent windows began at least 900 seconds after the preceding window completed.
- Initial tree had pre-existing review documentation changes only, shown below. No implementation/test/config change was present. Existing changes were preserved, not staged or reverted.
- Ollama 0.33.2; container `1d5de9a37b95a080b775b2cd66ce4e5d561aec02d6aa8ef16e0f6337114eb370`; host PID 51640; server Linux PID 1, start tick 3412273; started `2026-10-16T14:46:08.611219707Z`. Identity, uptime origin, image, model storage volume `ollama`, configuration and mounts stayed unchanged.
- WSL boot ID `47ea0580-bd62-429c-84cc-4d740acc6d26` stayed unchanged. GPU: NVIDIA GeForce RTX 3070, 8 GiB, driver 617.42; Windows 11 Pro build 26300. No fresh WDDM-version measurement was needed for this passive observation.
- Initial loaded models: none. Every resident chat sample showed production `qwen3.5:9b` / Q4_K_M / context 4096 / 100% GPU. No temporary or additional chat model appeared. No operator unload/restart was performed; normal five-minute idle expiry was allowed between windows.
- All eight production model assignments stayed `MANUAL` / `local_quality`. Production SDK timeout 45 s and Agent timeout 90 s remained unchanged. Production embeddings retained `qwen3-embedding:0.6b`, CPU `num_gpu=0`.

```text
AM docs/reviews/final-release-sanity-2026-10-17.md
A  docs/reviews/sanity01-gpu-headroom-ab-diagnosis-2026-10-17.md
A  docs/reviews/sanity01-gpu-paging-diagnosis-2026-10-17.md
A  docs/reviews/sanity01-local-provider-tail-latency-diagnosis-2026-10-17.md
A  docs/reviews/sanity01-normal-operation-observation-2026-10-17.md
A  docs/reviews/sanity01-runtime-reset-boundary-diagnosis-2026-10-17.md
A  docs/reviews/sanity01-runtime-reset-boundary-v2-diagnosis-2026-10-17.md
A  docs/reviews/sanity01-tail-soak-diagnosis-2026-10-17.md
```

## Method and trigger

Existing Ollama logs were followed passively, with Windows PDH/NVML resource observations at approximately 200 ms and `/api/ps` residency sampling at approximately two seconds. These requests do not invoke or keep the model resident. Own diagnostic requests were phase-labelled in external evidence only and excluded from natural-activity triggers. Warm native task metrics were required; cold starts never classified health.

HEALTHY_WARM means duration <20 s **and** native generation >=20 tok/s. DEGRADED_WARM means duration >=30 s **or** native generation <15 tok/s **or** SDK/provider timeout / valid direct completion >45 s. The first measured degraded event would immediately freeze D0 and enter R1, without a confirmation request. Recovery would require two consecutive healthy warm requests among three measurements.

Frozen semantic SHA-256: `e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af`, verified before every request. Original payload bytes SHA-256: `4ca98a67fa1e96d1b45f756a78d172086ec39ff8bcb42ebeaa232462491bbfed`. Equivalent streaming wire SHA-256: `49b74c9a9b0380566ed07ea1232e378a7b2e69626d2edddb9bee0727b67c6726`; only streaming transport differs. Messages, exact two tools/schemas, UTF-8, qwen3.5:9b, context 4096, temperature 0, max_tokens 192 and reasoning_effort none stayed unchanged. Native input was 1104 tokens, output 158 tokens on every request; final content hashes matched. No complete prompt/response was added to production telemetry. Direct observation ceiling remained the existing diagnostic 240 s; no application client timeout was changed.

## All windows, requests and resources

Warmups are retained below and excluded from classification. Stream batches are not treated as exact tokens; throughput uses native Ollama counters. Dedicated/shared measurements refer to the Windows discrete GPU adapter, not exclusively Ollama. VMMEM is VM-wide memory, not a per-model allocation.

| Window | Start CEST | End CEST | Separation (s) | Excluded warmup (s) | Measured warm |
|---|---|---|---:|---:|---|
| 1 | 09:08:06 | 09:08:30 | 900.111 | 12.024 | 4.270 s / 38.20 tok/s; 4.289 s / 37.83 tok/s |
| 2 | 09:23:30 | 09:23:54 | 900.188 | 11.355 | 4.349 s / 37.37 tok/s; 4.243 s / 38.54 tok/s |
| 3 | 09:38:55 | 09:39:19 | 900.181 | 11.674 | 4.168 s / 39.10 tok/s; 4.222 s / 38.46 tok/s |
| 4 | 09:54:19 | 09:54:43 | 900.165 | 11.554 | 4.138 s / 39.25 tok/s; 4.131 s / 39.38 tok/s |

| Request | Start CEST | Duration (s) | TTFT (s) | Prompt eval (s) | Generation (s) | Output tokens | Native tok/s | Longest batch pause (s) | HTTP | State |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| W1_WARMUP | 09:08:06 | 12.024 | 7.865 | 0.804 | 4.159 | 158 | 37.75 | 0.085 | 200 | WARMUP_EXCLUDED |
| W1_M1 | 09:08:19 | 4.270 | 0.160 | 0.119 | 4.109 | 158 | 38.20 | 0.082 | 200 | HEALTHY_WARM |
| W1_M2 | 09:08:25 | 4.289 | 0.139 | 0.119 | 4.150 | 158 | 37.83 | 0.088 | 200 | HEALTHY_WARM |
| W2_WARMUP | 09:23:31 | 11.355 | 7.323 | 0.813 | 4.032 | 158 | 38.94 | 0.084 | 200 | WARMUP_EXCLUDED |
| W2_M1 | 09:23:43 | 4.349 | 0.150 | 0.122 | 4.201 | 158 | 37.37 | 0.087 | 200 | HEALTHY_WARM |
| W2_M2 | 09:23:49 | 4.243 | 0.170 | 0.130 | 4.073 | 158 | 38.54 | 0.082 | 200 | HEALTHY_WARM |
| W3_WARMUP | 09:38:55 | 11.674 | 7.532 | 0.786 | 4.141 | 158 | 37.91 | 0.085 | 200 | WARMUP_EXCLUDED |
| W3_M1 | 09:39:08 | 4.168 | 0.152 | 0.128 | 4.015 | 158 | 39.10 | 0.083 | 200 | HEALTHY_WARM |
| W3_M2 | 09:39:13 | 4.222 | 0.139 | 0.119 | 4.082 | 158 | 38.46 | 0.081 | 200 | HEALTHY_WARM |
| W4_WARMUP | 09:54:19 | 11.554 | 7.563 | 0.800 | 3.990 | 158 | 39.34 | 0.076 | 200 | WARMUP_EXCLUDED |
| W4_M1 | 09:54:32 | 4.138 | 0.138 | 0.118 | 4.000 | 158 | 39.25 | 0.082 | 200 | HEALTHY_WARM |
| W4_M2 | 09:54:37 | 4.131 | 0.145 | 0.121 | 3.987 | 158 | 39.38 | 0.082 | 200 | HEALTHY_WARM |

| Request | Runner PID | Peak dedicated (GiB) | Peak shared (GiB) | Median VMMEM (GiB) | Min available host RAM (GiB) | Median GPU (%) | Median SM clock (MHz) | Max temp (C) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| W1_WARMUP | 22023 | 7.393 | 0.808 | 18.258 | 18.059 | 88.0 | 1920 | 58 |
| W1_M1 | 22023 | 7.393 | 0.808 | 18.259 | 18.024 | 88.0 | 1935 | 59 |
| W1_M2 | 22023 | 7.393 | 0.808 | 18.261 | 18.040 | 87.0 | 1935 | 59 |
| W2_WARMUP | 22173 | 7.393 | 0.803 | 18.030 | 18.513 | 93.0 | 1920 | 64 |
| W2_M1 | 22173 | 7.393 | 0.803 | 18.030 | 18.521 | 87.0 | 1920 | 64 |
| W2_M2 | 22173 | 7.393 | 0.803 | 18.029 | 18.481 | 90.0 | 1920 | 64 |
| W3_WARMUP | 22324 | 7.393 | 0.803 | 18.105 | 18.385 | 83.0 | 1950 | 58 |
| W3_M1 | 22324 | 7.393 | 0.803 | 18.106 | 18.345 | 95.0 | 1935 | 59 |
| W3_M2 | 22324 | 7.393 | 0.803 | 18.107 | 18.380 | 87.0 | 1935 | 60 |
| W4_WARMUP | 22475 | 7.393 | 0.803 | 18.133 | 18.393 | 87.0 | 1950 | 58 |
| W4_M1 | 22475 | 7.393 | 0.803 | 18.135 | 18.379 | 88.0 | 1935 | 59 |
| W4_M2 | 22475 | 7.393 | 0.803 | 18.135 | 18.401 | 86.0 | 1935 | 60 |


Measured warm duration median 4.232 s, maximum 4.349 s; native throughput minimum 37.37 tok/s. There were 12 direct requests total (4 excluded warmups + 8 measured); 0 ordinary requests; all chat HTTP responses were 200. SDK timeouts and Agent timeouts were not exercised because no post-reset Agent control was permitted. No request was retried.

## Reset boundary and product controls

| Item | Result |
|---|---|
| D0 / first degraded warm trigger | NOT_CAPTURED |
| R1 model-only unload/reload | NOT_RUN |
| R1 unchanged server / new runner proof | NOT_APPLICABLE |
| R1 recovery | NOT_RUN |
| R2 Ollama-only restart | NOT_RUN |
| R2 recovery | NOT_RUN |
| Post-reset product-centric-en | NOT_RUN — no reset/recovery occurred |
| Post-reset clearance-boundary-en | NOT_RUN — no reset/recovery occurred |
| Post-reset restricted-boundary | NOT_RUN — no reset/recovery occurred |

Historical idle unloading did not permanently prevent later degraded windows. The natural idle unloads in this healthy observation do not substitute for controlled R1 applied to an active degraded state. There is no evidence here to choose model runner, Ollama process, or deeper WSL/host ownership. No paging or contention causal claim follows from healthy resource samples.

## Safety and integrity

- Provider cleanup: PASS, 14 tests. R01: PASS, 29 tests. Combined command: `.venv/Scripts/python.exe -m pytest tests/unit/test_provider_cleanup_async.py tests/unit/test_r01_provider_authorization.py -q --tb=short`; 43 passed, zero failures; existing warning retained in evidence.
- Final Agent `/ready`: 200; Knowledge MCP initialization/tool discovery and one safe INTERNAL retrieval: PASS. Retrieval duration 10.681 s, no protected write. This final embedding verification occurred after observation and did not add a chat request.
- Final project stack: 20/20 Docker healthy with unchanged project container identities. Ollama remained ready. Actual loaded embedding GPU bytes: 0; CPU placement and policy confirmed.
- Production assignments, model metadata/tags, configuration hashes, model storage and WSL boot identity unchanged. External model calls: 0. Protected side effects: 0.
- Protected counters unchanged: `100|5|1` = maintenance_ticket / maintenance_event / process_parameter.
- All 555 baseline file hashes, including existing source, tests, config, `.env`, and historical reports/local translations, unchanged. `git diff --check` and cached diff check: PASS. No commit, push, index change, or deployment. Only this new report, its ignored DE counterpart and external diagnostic evidence were created.

## Interpretation and next step

Confidence is HIGH that no eligible degradation was captured within these four bounded windows; ownership confidence is LOW because the reset ladder was correctly not exercised. The sample is eight healthy warm direct requests, not evidence that the historical product failure has disappeared. Do not clear the release blocker or claim permanent recovery.

Recommended next step: retain the naturally occurring Window 2 failure and apply the already authorized evidence-first reset ladder only when a future ordinary supported warm request meets the trigger, under a separate observation task. Do not manufacture load. Timeout increase: NO. Production restart policy: UNDETERMINED. Ollama runtime remediation: UNDETERMINED. Ready for targeted remediation: NO.

Evidence root: `D:/Freelance/sanity01-event-reset-20261018-085306`. Primary files: `controller-result.json`, `window-1.json` through `window-4.json`, `direct-results.jsonl`, per-request native logs and output-batch timelines, `passive-events.jsonl`, `ollama-live.log`, `ollama-final-complete.log`, `high-frequency-telemetry.jsonl`, `model-residency.jsonl`, `request-profiles.json`, `analysis-summary.json`, `state-initial.json`, `state-final.json`, protected counter snapshots, `safety-tests.log`, and integrity snapshots. An external log-reader setup correction before any inference is retained in `observer-setup-correction.json`; no production process or setting was altered by it.
