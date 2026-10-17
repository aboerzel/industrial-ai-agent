# CERT-01 Observability Trace Remediation — 2026-10-17

## Scope and authoritative finding

**CERT-01 — Run-trace lookup can select a history read instead of execution.**
Severity/category: **MEDIUM; Observability/RCA correctness, limited diagnostic feature.**
The authoritative finding is in [the original certification](final-release-certification-2026-10-16.md#medium).
It requires ADR-016 run-correlated agent/model/tool observability and ADR-017 analysis
of available execution evidence. The affected component is
`TempoAdapter.get_run_trace` in `infrastructure/observability_backends.py`, shared by
Observability and RCA. The original report remains unchanged.

The prescribed reproduction is an authorized INTERNAL investigation, a History read,
then authenticated `get_run_trace`, comparing selection against available execution
spans. The original recommendation is to bind the execution-owning trace deterministically
and add multiple-trace regression coverage through downstream RCA. This remediation
implements that recommendation only.

Baseline: `main`, HEAD `aeba38ea418bb276a4f58880753524bd031d9827`.
The historical certification report was already staged at the start. Python 3.12.10
uses the configured `.venv`. No commits, pushes, external model calls, protected actions,
authentication/RLS/model/provider changes, or tracing instrumentation changes occurred.

## Pre-fix reproduction and preserved first evidence

Reproduction: **YES**, independently through the real authenticated Observability MCP
and real Tempo backend, before production code changed. The existing synthetic demo
investigation `b4bbbbec-30d4-4434-ad53-f9ffa367545b` was read three more times through
the actual History API. The selected trace was again
`5190a7e936a8e28ce5939b17f64a8fd7`, while execution trace
`bad5a392a533e5765d7ce31a5d1d4ea4` still existed.

| Associated trace ID | Root service / operation | Envelope ms | Spans | LLM | Tool |
| --- | --- | ---: | ---: | ---: | ---: |
| `b38aa1d1c3ed2bbb391a43f4f08a9048` | industrial-ai-agent / History GET | 4.429001 | 5 | 0 | 0 |
| `3b54e51bb3289e042692a32363e743f9` | industrial-ai-agent / History GET | 5.009015 | 5 | 0 | 0 |
| `6bb8b6fe092ad72fcd7da1d0193b47b7` | industrial-ai-agent / History GET | 5.846334 | 5 | 0 | 0 |
| `84fd8d64333b5e7f00ca176a4a55fa39` | rca-mcp / POST /mcp | 262.964940 | 9 | 0 | 0 |
| `7f65ab500ecb87a42978f9a86c55f585` | runtime-mcp / POST /mcp | 58.190803 | 8 | 0 | 0 |
| `5190a7e936a8e28ce5939b17f64a8fd7` | industrial-ai-agent / History GET, selected | 7.468754 | 5 | 0 | 0 |
| `75f4aa32b436af46deb43b4d15676bfb` | industrial-ai-agent / Run GET | 8.215879 | 5 | 0 | 0 |
| `bad5a392a533e5765d7ce31a5d1d4ea4` | industrial-ai-agent / POST /api/v1/runs | 8986.077901 | 86 | 2 | 1 |

History GET means `GET /api/v1/investigations/{investigation_id}`; Run GET means
`GET /api/v1/runs/{run_id}`. The execution's **agent.run duration is 8966.823590 ms**;
the HTTP envelope includes additional work. Its LLM spans last approximately
3355.216 and 5487.585 ms, matching certification evidence. All eight matching traces
at that snapshot were recorded, including per-span service/operation, parent ID,
start/end Unix-nanosecond timestamps, span kind, and exact `run.id` correlation.
Only safe trace metadata was retained, with no prompts, outputs, cookies, tokens or secrets.

Evidence directory outside the repository:
`D:/Freelance/cert01-remediation-evidence-20261017-091500`.
`before-original-live.json` is the complete metadata inventory and MCP/RCA result.
`prefix-regression.log` records the deterministic pre-fix result: **13 failed, 5 passed**.
The deterministic fixtures replay competing traces through the real Tempo adapter,
including certification timings and backend result-order permutations.

An earlier new read-only local investigation selected its execution even before the
fix; that first observation is preserved in `before-live.json` and
`before-read-control-live.json`. This demonstrates dependence on backend order rather
than guaranteed failure on every invocation. The original certification case reproduced
the wrong selection exactly. The first noncanonical discovery prompt returned a neutral
404; its harness log is preserved and was not counted as a passing reproduction.

## Root cause and exact selection contract

Before remediation, the adapter validated the run UUID, searched the preceding 48 hours
using `{ span.run.id = "<run UUID>" }`, requested `limit=1` and `spss=1`, took
`traces[0].traceID`, fetched that trace by ID, and attached the requested run UUID.
There was no execution-operation/service check or persisted trace binding. History and
other read spans legitimately carry `run.id`. Backend result order therefore decided
which operation became the supposed execution. RCA then correlated downstream sources
to that wrong trace. Duration and missing LLM spans were symptoms, not identity rules.

The run store/schema has no authoritative persisted execution trace ID. Existing
instrumentation already provides a stable identity: **same span** named `agent.run`,
resource service `industrial-ai-agent`, exact `run.id`. The new server-constructed query:

```text
{ resource.service.name = "industrial-ai-agent" && name = "agent.run" && span.run.id = "<run UUID>" }
```

The 48-hour bound, backend timeout, and span projection limit remain unchanged. Search
requests at most two matching traces, not a corpus scan. One distinct validated trace
ID is required. Duplicate rows with that same ID are harmless; multiple distinct
execution IDs are explicitly ambiguous/malformed. Missing execution is not found.
The fetched trace must independently contain the same semantic marker; a stale or
misbound read trace is rejected. No duration, span-count, earliest/latest, LLM-count,
or backend-order heuristic is used. **"Longest trace wins": NO.**

Investigation follow-ups use a new run UUID (`_start_run`); each is looked up separately.
HITL resumes keep their run UUID but use the existing `approval.resume` operation rather
than a second `agent.run`. The singular lookup identifies the initial execution; it
does not invent aggregation or claim cross-phase completeness. Multiple contradictory
initial-execution identities fail closed instead of choosing a generation arbitrarily.
This boundary is clarified in ADR-016 and the architecture overview. No architecture
diagram changes are needed: services, dependencies and telemetry flow are unchanged.

Authorization still resolves the persisted run through trusted `SecurityContext` and
RLS before telemetry. Trace identity never grants authority. Missing/ambiguous telemetry
uses existing partial/insufficient RCA semantics; read tracing remains intact. No
sensitive correlation attribute or new instrumentation was introduced.

## Required regression matrix

| Case | Proof | Result |
| --- | --- | --- |
| CERT01-01 | Certification timing reproduction, History first | PASS |
| CERT01-02 | Execution plus one History trace | PASS |
| CERT01-03 | Execution plus three History traces | PASS |
| CERT01-04 | All six execution/History/RCA result-order permutations | PASS |
| CERT01-05 | Returned execution retains two LLM spans and one tool span | PASS |
| CERT01-06 | 1-ms execution versus 90-second unrelated read | PASS |
| CERT01-07 | Missing execution: no read fallback; RCA source missing | PASS |
| CERT01-08 | Hidden run denied before any backend call | PASS |
| CERT01-09 | Real RCA collector/analyzer reports actual execution; missing-source control | PASS |
| CERT01-10 | Separate follow-up run identity; resume cannot replace initial execution | PASS |

Additional cases cover distinct duplicate execution IDs, duplicate backend rows for one
ID, and a backend returning a misbound read despite the semantic query. Together these
are **19 focused tests**, all passing. Existing authorized/hidden/unknown run tests and
disposable PostgreSQL HTTP tests cover neutral visibility and RLS behavior.

## Live local proof after remediation

The affected Observability, RCA and Agent API images were rebuilt. Agent API also embeds
the adapter. No model/configuration changes were made. Nginx required a configuration
reload after container recreation to resolve the replaced API container; the initial
502 is preserved as an operational/harness event. One diagnostic script initially
expected a trace ID in the intentionally bounded RCA MCP projection; its KeyError is
preserved. The corrected proof validates the public measurements and deterministic
adapter/collector binding instead, without expanding the API.

For the original run, `after-original-live.json` now records selection of
`bad5a392a533e5765d7ce31a5d1d4ea4`. RCA reports **8966.823590 ms**, **two LLM generations**,
and available Langfuse metadata, replacing the pre-fix History-only evidence.

A fresh safe local investigation `67f06883-7844-47b8-a53f-e52fb62ac35f` used the canonical
station-discovery request and the unchanged local Ollama assignment. Its execution ID
was captured **before** subsequent reads:
`21c5ca201a9d0e8307340cce669a7c50`, 88 spans, two LLM spans, one tool span;
agent.run **16514.194558 ms**, HTTP envelope **16542.752075 ms**.
Three History GETs, a status GET, and a PDF GET followed. Authenticated Observability
still selected the exact recorded execution ID. RCA reported two generations and
the actual run duration, including LLM and MCP timing evidence.
`after-create-live.json` preserves this inventory and all assertion inputs.

A subsequent round after the RCA/Observability reads again retained the same execution
(`after-final-reads-live.json`). History/read traces remain present and independently
observable. No ticket creation, approval, calibration or hardware execution was requested.

RCA correctly retains independent source limitations: Loki data was missing, and the
original historical run's Prometheus projection was malformed both before and after
the fix. The fresh run has usable metric evidence. These sources were not repaired or
silently called complete. CERT-01 does not promise availability beyond retention or
aggregate separate approval-resume traces.

## Validation

| Gate | Result |
| --- | --- |
| Focused CERT-01 | 19 passed |
| Combined focused Observability/RCA/Runtime/C01/R01/security | 172 passed |
| Full backend: configured Python `-m pytest tests` | 2083 collected; 2077 passed, 0 failed, 6 skipped |
| INTEGRATION: `scripts/run-quality-gate.ps1 INTEGRATION` | 279 passed, 0 failed, 5 KDEP skips |
| FAST: `scripts/run-quality-gate.ps1 FAST` | PASS: 1783 unit passed, 1 platform skip; 338 frontend passed; all subgates passed |
| Ruff / format / secret scan | PASS / PASS (263 files) / PASS |
| `git diff --check` | PASS |
| Local affected images | Rebuilt from final formatted source; 20/20 stack services healthy, 0 restarts |

C01: **18 passed**; R01: **29 passed**; Observability MCP: **4 passed**, plus **26**
visibility tests and **2** HTTP visibility tests; RCA MCP: **13 passed**; Runtime MCP:
**9 passed**. Full RCA contracts, analysis, reasoning, Langfuse adapters and PostgreSQL
security regressions also passed in the backend suite. Final focused CERT-01 and FAST
validate the equivalent lint/format corrections; production logic did not change after
the full backend/integration results. `after-final-stack-live.json` proves selection on
the final rebuilt images. Their post-recreation logs contain no unexpected error matches.

Backend and integration use only disposable PostgreSQL
`cert01-postgres-20261017`, database `verification_cert01`; application role
`factory_app` is **NOSUPERUSER, NOBYPASSRLS**. Persistent demo data is not used for test
writes. The six skips are five opt-in KDEP clean/offline deployment tests (Knowledge is
unchanged and this gate is outside CERT-01), and the Windows symlink-creation test
(platform capability unavailable). They are not claimed as passes.

The initial unrestricted `pytest` command also collected an old ignored generated
`evals/results/.../test_trust_proof.py` and failed its import signature. Evidence is
preserved in `backend.log`; the authoritative backend run explicitly targets `tests`.
Initial FAST passed unit/frontend tests but caught a nested conditional in the new test
helper via Ruff. The final equivalent conditional and a production formatting-only wrap
were checked again. No gate timeout, test expectation, or product behavior was weakened.
No frontend changes were made; no browser suite was required for this adapter fix.

## Integrity, remaining limits and conclusion

The historical review report and its local DE counterpart remain byte-identical;
the preexisting staged report is preserved. Changes are limited to the Tempo lookup,
its existing test expectations, the new CERT-01 regression module, ADR-016 and overview
clarification, and this new report. Relevant local DE counterparts are ignored.
External evidence includes the initial versioned-file hash manifest and first failures.
Persistent protected counters are maintenance tickets **100**, maintenance events **5**,
and process parameters **1**, unchanged in the final comparison. The disposable database
container was stopped and removed; project volumes and the healthy stack remain intact.
The initial file manifest confirms exactly four intended existing-file modifications
(adapter, existing adapter test, ADR-016 and overview), and no other existing tracked
file changes. The historical report's staged diff is unchanged. No staging/commit/push
commands were issued by this remediation; the new test is currently partly staged and
its final working-tree version is the tested version. The report is a new file.

Remaining CERT-01 findings: **NONE**. Separate RCA source availability and the existing
singular initial-execution scope remain explicit limits, not hidden completeness claims.
No other historical finding was remediated or comprehensively reviewed.

Finding fixed: **YES**. Ready to commit: **YES**.
Commits/pushes/external deployments: **0/0/0**.
