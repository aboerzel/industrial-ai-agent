# Acceptance Stabilization and Full Rerun

Date: 2026-09-10. Scope: rebuilt local Compose runtime, deterministic seed, and the
German catalogue with explicit `DE` response language. No commit was created.

## Specification Corrections

| UC | Previous problem | Validation evidence | Correction | Reason |
|---|---|---|---|---|
| 14 | Prompt required inspection results | No Agent-facing inspection capability exists | EN/DE use only history, warnings, final error | Remove unsupported requirement. |
| 27-28 | Runtime ticket ID | Seed contains CONFIDENTIAL `MT-S02-20260117` | Use seeded ID | No history dependency. |
| 29-32 | RCA as Agent prompt | RCA MCP exposes `analyze_run` | Agent run, then authenticated RCA MCP | Correct boundary. |

Visibility source of truth: S01/S05 and P4101/P4102 PUBLIC; S02/S03 and P4900/P4901
INTERNAL; S04, P4711, P4801/P4811 and the seeded ticket CONFIDENTIAL; S07/P9001
RESTRICTED. Insufficient-clearance neutral denial is a security PASS.

## Stabilization Verification

`asyncio.wait_for` directly awaits `start`, `run_with_policy`, and HITL `resume`; there
is no detached task or shield. Timeout persists exactly one terminal `failed` state with
`agent_execution_timeout`; provider-limit codes remain separate. Live UC-03 returned
HTTP 504 after 60.046 s; its persisted state stayed failed, with no tool summary or later
mutation. UC-01 then succeeded in 0.916 s without an API restart.

Knowledge MCP was unready during 102 s clean-process warm-up, then healthy. It builds
PUBLIC, INTERNAL, CONFIDENTIAL, and RESTRICTED projections before serving. Docling and
the reranker are shared once per process. Two confidential direct queries returned one
authorized result each in 11.530 s and 10.304 s without reinitialization. Warm-up failure
propagates and prevents readiness.

## Phase 3 Provider Limit Attribution

The OpenAI SDK version in the runtime is 2.54.0 and defaults to two automatic retries.
The adapter previously left that default active, so SDK retry/backoff could consume the
outer 60-second Agent deadline before a normalized provider error reached the API. The
adapter now sets `max_retries=0`; a recognized rate, quota, or availability error reaches
the existing terminal provider-error mapping immediately. The deadline remains unchanged.
The live-only acceptance runner executes each case once and has a configurable two-second
inter-case delay; it does not retry blocked cases.

| UC | Run classification | Trace profile/provider | Bounded evidence | Attribution |
|---|---|---|---|---|
| 03 | RESTRICTED | `local_quality` / Ollama | first model span 103.528 s; terminal 504 at 60.066 s | APPLICATION_TIMEOUT (local path) |
| 09 | RESTRICTED | `local_quality` / Ollama | a model span continued 601.323 s after the terminal 504 | APPLICATION_TIMEOUT (local path) |
| 12 | PUBLIC | `public_fast` / Groq | final model span 70.111 s and `llm_provider_unavailable` | PROVIDER_UNAVAILABLE |
| 15 | CONFIDENTIAL | `public_fast` / Groq | final model span 21.909 s and `llm_provider_unavailable` after prior bounded calls | PROVIDER_UNAVAILABLE |
| 24 | RESTRICTED | `local_quality` / Ollama | first model span 72.234 s; terminal 504 at 60.020 s | APPLICATION_TIMEOUT (local path) |
| 27 | CONFIDENTIAL | `public_fast` / Groq | terminal `llm_rate_limit` in 0.620 s | PROVIDER_RATE_LIMIT |

Historical trace data records one logical provider call, not individual SDK attempts, so
the exact historical retry count is unavailable. The configured SDK default was two;
future interactive runs use zero automatic retries. No RESTRICTED trace used Groq or any
public-cloud profile. UC-15 correctly remains CONFIDENTIAL despite a RESTRICTED caller.

## Corrected Acceptance Run

| # | Use Case | Interface | Clearance | Observed bounded evidence | Result |
|---:|---|---|---|---|---|
| 01 | Public stations | API | PUBLIC | 200; `list_stations` | PASS |
| 02 | Internal stations | API | INTERNAL | 200; `list_stations` | PASS_WITH_FINDINGS |
| 03 | Restricted stations | API | RESTRICTED | 504; local `local_quality` call exceeded deadline | FAIL (`APPLICATION_TIMEOUT`) |
| 04 | Public products | API | PUBLIC | 404 before Agent | FAIL (`APPLICATION_DEFECT`) |
| 05 | Internal products | API | INTERNAL | 404 before Agent | FAIL (`APPLICATION_DEFECT`) |
| 06 | S02 orientation | API | INTERNAL | 200; overview | PASS |
| 07 | P4801 orientation | API | CONFIDENTIAL | 404 before Agent | FAIL (`APPLICATION_DEFECT`) |
| 08 | Available stations | API | INTERNAL | 200; `list_stations` | PASS |
| 09 | S07 status | API | RESTRICTED | 504; local `local_quality` call exceeded deadline | FAIL (`APPLICATION_TIMEOUT`) |
| 10 | Recent failures | API | CONFIDENTIAL | 404 before Agent | FAIL (`APPLICATION_DEFECT`) |
| 11 | Products at S04 | API | CONFIDENTIAL | 500 `internal_error` | FAIL (`APPLICATION_DEFECT`) |
| 12 | P4101 history | API | PUBLIC | 404 before Agent | FAIL (`APPLICATION_DEFECT`) |
| 13 | P4901 failure | API | INTERNAL | 200; overview/history | PASS |
| 14 | P4711 history | API | CONFIDENTIAL | 200; history | PASS |
| 15 | Higher user/lower run | API | RESTRICTED | historical 504 followed Groq `llm_provider_unavailable` | BLOCKED_BY_PROVIDER |
| 16 | P4711 denial | API | INTERNAL | neutral 404; no model data | PASS (EXPECTED_NON_DISCLOSURE) |
| 17 | Warning relevance | API | CONFIDENTIAL | 200; no causal certainty | PASS_WITH_FINDINGS |
| 18 | QUALITY-09 lookup | API | CONFIDENTIAL | 200; documentation | PASS |
| 19 | Positioning procedure | API | CONFIDENTIAL | 200; documentation | PASS |
| 20 | S04 documents | API | CONFIDENTIAL | 200; documentation | PASS_WITH_FINDINGS |
| 21 | Restricted documentation | API | CONFIDENTIAL | neutral 404 | PASS (EXPECTED_NON_DISCLOSURE) |
| 22 | History plus knowledge | API | CONFIDENTIAL | 200; history/docs | PASS_WITH_FINDINGS |
| 23 | Warning plus state | API | CONFIDENTIAL | 200; no S04-success/causal overclaim | PASS |
| 24 | Restricted cross-source | API | RESTRICTED | 504; local `local_quality` call exceeded deadline | FAIL (`APPLICATION_TIMEOUT`) |
| 25 | P9001 non-leakage | API | CONFIDENTIAL | neutral 404 | PASS (EXPECTED_NON_DISCLOSURE) |
| 26 | S07 non-leakage | API | CONFIDENTIAL | neutral 404 | PASS (EXPECTED_NON_DISCLOSURE) |
| 27 | Seeded ticket authorized | API | CONFIDENTIAL | 500 `internal_error` | FAIL (`APPLICATION_DEFECT`) |
| 28 | Seeded ticket denial | API | INTERNAL | 500, not neutral | FAIL (`SECURITY_DEFECT`) |
| 29 | RCA overview | authenticated RCA MCP | INTERNAL | partial runtime projection; no payload/cause | PASS_WITH_FINDINGS |
| 30 | RCA failure focus | authenticated RCA MCP | INTERNAL | partial; no confirmed cause | PASS_WITH_FINDINGS |
| 31 | RCA performance | authenticated RCA MCP | INTERNAL | partial; no attributable timing | PASS_WITH_FINDINGS |
| 32 | Confidential RCA boundary | authenticated RCA MCP | INTERNAL | no identifier/classification/clearance hint | PASS (EXPECTED_NON_DISCLOSURE) |

Totals: PASS 13 (including 5 expected non-disclosures); PASS_WITH_FINDINGS 7; FAIL 12;
BLOCKED_BY_PROVIDER 0; NOT_EXECUTED 0.

## Security Hard Gates

`UNAUTHORIZED-ENTITY-NON-DISCLOSURE: PASS` (UC-16/25/26/32).
`CLASSIFICATION-NON-DISCLOSURE: PASS`.
`DOCUMENT-NON-DISCLOSURE: PASS` (UC-21 exposes no title, metadata, or count).
`TICKET-NON-DISCLOSURE: FAIL` (UC-28 is HTTP 500, not neutral denial).
`RLS-BOUNDARY: PASS` for exercised entity/document/RCA projections.
`RESTRICTED-MODEL-EGRESS: PASS` by deterministic tests and trace attribution; live
RESTRICTED runs used only `local_quality`/Ollama and emitted no data.
`HITL-BOUNDARY: PASS` by deterministic tests.

## Confirmed Defects and Regression Coverage

P1 German request classification denies visible product cases UC-04/05/07/10/12. Add
resolver unit and API authorized-visibility integration tests.

P1 UC-11 turns an authorized S04 request into 500. Add a deterministic Agent/MCP
trajectory test for a bounded S04 projection.

P1 UC-03/09/24 exceed the bounded deadline on the local RESTRICTED path. Trace evidence
proves this is not Groq rate limiting; a separate local execution/cancellation diagnosis
is still required. UC-12 and UC-15 are historical provider-unavailable blocks, not
Agent-performance findings; adapter retry handling is now bounded to zero SDK retries.

UC-27's latest recorded Phase-2 result is a provider-rate-limit block, not evidence of a
ticket-recognition regression. Ticket parser and anti-enumeration coverage remain
required independently of provider availability.

P2 Semantic golden coverage remains incomplete. This run found no UC-23 S04-success or
causal overclaim; add versioned golden checks for UC-02/17/20/22 facts, relevance,
causality, and structured `next_steps`.

Added: timeout cancellation/history, warm-up failure, four-projection, single-flight,
shared-reranker, and shared-Docling tests. Existing security/RLS/egress/HITL tests pass.

## Acceptance Findings Remediation

Implement only the four P1 groups and the P2 golden checks. Preserve every expected
neutral denial. Do not change UC-14, cold-start readiness, or RCA interface. Add low-layer
tests first; live E2E remains representative only. Acceptance requires visible authorized
fixtures, UC-28 indistinguishable from unknown ticket, terminal restricted runs without
process poisoning, and golden rejection of invented identifiers/causal certainty/S04 pass.

## Verdict

`RUNS-ALWAYS-TERMINATE: YES`
`POST-TIMEOUT-SERVICE-USABLE: YES`
`KNOWLEDGE-READINESS-LIVE-VERIFIED: YES`
`UC14-SPEC-CONSISTENT: YES`
`FULL-TEST-SUITE: PASS`
`FULL-CATALOGUE-EXECUTED: YES`
`NOT-EXECUTED-COUNT: 0`
`SECURITY-HARD-GATE: FAIL`
`CORE-GOLDEN-REGRESSION-COVERAGE: INSUFFICIENT`
`ACCEPTANCE: FAIL`

## Phase 4 Targeted Local-Execution Revalidation

The historical full-catalogue rows above remain evidence of that run. The targeted
Phase 4 revalidation supersedes only the local-execution attribution for UC-03, UC-09,
and UC-24:

| UC | Current result | Bounded evidence | Classification |
| --- | --- | --- | --- |
| UC-03 | PASS | `RESTRICTED_INFORMATION`, local `local_fast`, one Factory tool, terminal success in 42.953 s | Resolved simple restricted-information latency |
| UC-09 | PASS | `RESTRICTED_INFORMATION`, local `local_fast`, one Factory tool, terminal success in 49.564 s | Resolved station-status tool-catalogue latency |
| UC-24 | FAIL | `RESTRICTED_TROUBLESHOOTING`, local `local_quality`, terminal `agent_execution_timeout` at 60.023 s before a tool call | APPLICATION_TIMEOUT, complex local workflow |

UC-03 and UC-09 now use the bounded RESTRICTED information profile: a local fast
tool-capable model, only Factory station capabilities, disabled local thinking, a
192-token output ceiling, and deterministic structured trajectory projection. The
RESTRICTED quality path remains local-only. UC-24 showed a 29.39 s 9B model load and
45.48 s CPU prompt evaluation for its 1,353-token initial context. Ollama reported GPU
initialization/NVML access failures and `size_vram=0`; no RESTRICTED data was sent to a
public provider. This host-level GPU-runtime issue must be resolved before a quality
cross-source run can reliably meet the 60-second boundary.

## Phase 5 GPU Runtime Revalidation

Docker Desktop's initial WSL GPU-PV state exposed `/dev/dxg` but rejected both the
standard CUDA-container check and NVML access. A complete Docker Desktop restart
reinitialized the WSL GPU runtime. The existing external Ollama container already had a
modern `gpu` device request, so no repository Compose change was required. The isolated
CUDA check then showed the RTX 3070 and 8 GiB VRAM inside a container.

Ollama 0.33.2 verified `qwen3.5:4b` at 3.1 GiB and `qwen3.5:9b` at 5.5 GiB, both
`100% GPU` with nonzero host VRAM usage. The 9B representative first decision changed
from the CPU baseline of 29.39 s load plus 45.48 s prompt evaluation to 4.83 s load,
0.776 s prompt evaluation, and 5.108 s generation. A subsequent warm 9B request
completed in 4.216 s model time. This preserves the LOCAL execution zone; no RESTRICTED
payload was sent to a public provider.

| UC | Current result | Bounded evidence | Classification |
| --- | --- | --- | --- |
| UC-03 | PASS | `RESTRICTED_INFORMATION`, `local_fast`, `list_stations`, terminal success in 11.260 s | GPU control passed |
| UC-09 | PASS | `RESTRICTED_INFORMATION`, `local_fast`, `get_machine_status`, terminal success in 4.719 s | GPU control passed |
| UC-24 | FAIL | `RESTRICTED_TROUBLESHOOTING`, local 9B first model call completed below the deadline; terminal `invalid_structured_final_output` before a tool call in 12.180 s | Existing structured-final-output defect, not a performance timeout |

The existing terminal-timeout regression remains unchanged. CPU fallback is still local
and supported, but complex `local_quality` work may exceed the interactive deadline when
GPU-PV is unavailable.

## Phase 6 UC-24 Structured-Output Correction

Phase 6 reproduced UC-24 once with a fresh RESTRICTED run before the correction. The
first divergence was not before MCP execution: the bounded graph executed
`get_product_history`, `get_machine_status`, and `search_documentation`, then the final
answer path received an empty visible response and raised
`invalid_structured_final_output`. No raw prompt, model text, tool payload, or document
content was retained in this diagnosis.

The initial decision node has only bound tools and no final response-format schema. The
finalizer separately binds no tools and applies the strict `FinalAgentOutput` JSON schema.
The contracts were therefore not combined. The actual defect was the Ollama
OpenAI-compatible adapter mapping local `reasoning_effort=none` to native
`extra_body.think=false`. On this endpoint that setting did not disable Qwen thinking;
the final response could finish at its output limit with reasoning metadata but no visible
JSON content. A bounded direct contract probe confirmed that the unchanged full final
schema validates when the documented OpenAI-compatible `reasoning_effort="none"` field
is sent.

The minimal Infrastructure-only correction sends `reasoning_effort` for every profile
that declares the capability. It does not change the Agent graph, the final schema,
timeout handling, model routing, or egress policy. The adapter contract regression now
asserts that local structured-output requests send `reasoning_effort` and never send
`extra_body.think`. A new deterministic RESTRICTED cross-source trajectory test proves
that three intermediate tool calls execute before only the separate finalizer receives
the strict output contract; existing invalid-finalizer-shape tests retain strict handling.

| UC | Current result | Bounded evidence | Classification |
| --- | --- | --- | --- |
| UC-24 | PASS | RESTRICTED `local_quality` / Ollama; 5 local model calls (3.030 s, 0.832 s, 1.460 s, 11.904 s, 9.920 s); 3 authorized MCP tools; terminal success in 38.620 s | Structured-output adapter defect resolved |

The successful run used `qwen3.5:9b` with GPU residency and no public-provider egress.
The Knowledge tool took 11.131 s; Factory tool calls took 46.40 ms and 11.70 ms. The
structured result contains three investigation steps, zero next steps, three identifiers,
and four authorized documents. The 60-second timeout was not involved. RLS, MCP
authorization, and neutral non-disclosure behavior remain unchanged.
