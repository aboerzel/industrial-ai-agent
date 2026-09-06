# Industrial AI Agent Demo: Use Cases and Scenarios

This catalog is the manual acceptance script for synthetic `FACTORY-DEMO-01`. Submit
normal questions in the Web UI or to `POST /api/v1/runs`; use authenticated MCP for
direct tool and RCA checks. The UI selector maps to a server-owned `SecurityContext` at
`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `RESTRICTED`.

Visibility follows `user clearance >= data classification`. Factory and knowledge lists
are RLS-filtered before names, relationships, or classifications are returned. They
never reveal hidden entities, hidden counts, or required clearance. Higher user clearance
authorizes lower data but does not raise its run classification: a RESTRICTED P4711
request stays CONFIDENTIAL and remains public-cloud eligible.

Sections 1-6 cover normal agent behavior; section 7 covers read-only RCA. The
deterministic RCA report is authoritative. Optional reasoning may add labelled hypotheses
but cannot confirm a cause. All records and documents are synthetic.

## 1. Factory Discovery

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| Public station discovery | Which stations are available? | PUBLIC | Returns only S01 and S05 and no hidden count or other station name. |
| Internal station discovery | Which stations are available? | INTERNAL | Returns S01, S02, S03, and S05; does not disclose S04 or S07. |
| Restricted station discovery | Which stations are available? | RESTRICTED | Returns all six stations, including S07. |
| Public product discovery | Which products are available? | PUBLIC | Returns only P4101 and P4102, both with final status COMPLETED. |
| Internal product discovery | Which products are available? | INTERNAL | Adds P4900 and P4901 but not confidential/restricted products. |
| Station orientation | What do you know about station S02? | INTERNAL | Returns its visible Positioning overview and current RUNNING state. |
| Product orientation | What do you know about product P4801? | CONFIDENTIAL | Returns its latest completed state and visible path; its warning is not final status. |

## 2. Production Status

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| Available stations | Which stations are currently available? | INTERNAL | Identifies visible running S01, S02, S03, and S05 only. |
| Restricted status | What is the current status of S07? | RESTRICTED | Returns FAULTED and PROTO-COMM-07 in a RESTRICTED run. |
| Recent failures | Which products recently failed? | CONFIDENTIAL | Returns visible failed P4711 and P4811; P9001 is absent. |
| Products at station | Which products passed through S04? | CONFIDENTIAL | The bounded S04 overview returns visible P4811, P4801, and P4711. |
| Successful product | What happened to P4101? | PUBLIC | Shows completed public S01 and S05 trajectory. |
| Explicit product failure | What happened to P4901? | INTERNAL | Shows completed S01 and explicit POSITION-ENC-02 failure at S02. |

## 3. Product Investigation

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| P4711 history | What happened to P4711? | CONFIDENTIAL | Shows S01 completion, S02 POSITION-ENC-02 warning, S03 completion, and S04 QUALITY-09 failure chronologically. |
| Higher user, lower run | Investigate why P4711 failed at S04. | RESTRICTED | Resolves CONFIDENTIAL run/RLS ceiling, not RESTRICTED; public-cloud routing remains possible. |
| Confidential denial | Investigate P4711 at S04. | INTERNAL | Returns neutral `requested_data_unavailable`; no model call or existence disclosure. |
| Warning relevance | Are there warnings in P4711's history relevant to the later failure? | CONFIDENTIAL | Separates S02 warning from S04 failure; any causal link is explicitly an inference. |

## 4. Knowledge & Documentation

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| QUALITY-09 lookup | What does QUALITY-09 mean? | CONFIDENTIAL | Returns eligible documentation with source/chunk provenance. |
| Positioning procedure | How should POSITION-ENC-02 be investigated? | CONFIDENTIAL | Returns eligible troubleshooting material without proving P4711's cause. |
| S04 documents | Which documentation is available for station S04? | CONFIDENTIAL | Returns only matching documents visible at the run ceiling. |
| Restricted denial | Find documentation for P9001 at S07. | CONFIDENTIAL | Neutral unavailable behavior; no restricted title, content, or count leaks. |

## 5. Cross-source Investigations

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| History plus knowledge | Which station did P4711 fail at and what does the error code mean? | CONFIDENTIAL | Combines product history and documentation; evidence and explanation are distinguishable. |
| Warning plus state | Are P4711 warnings relevant, and what is the current state of the station where it failed? | CONFIDENTIAL | Combines product history with S04 status and labels inference. |
| Restricted cross-source | Investigate P9001 at S07 and use available documentation. | RESTRICTED | Combines restricted history, status, and documentation; lower-clearance users cannot discover it. |

## 6. Restricted Data

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| Product non-leakage | What do you know about product P9001? | CONFIDENTIAL | Neutral unavailable/not-found semantics without identifier details, count, or required clearance. |
| Station non-leakage | What do you know about station S07? | CONFIDENTIAL | Neutral unavailable/not-found semantics without restricted state or count. |

## 7. Root-Cause Analysis

RCA MCP exposes `analyze_run(run_id, focus="overview" | "failure" | "performance",
reasoning="none" | "explain")`. It analyzes a persisted agent run, not production
payloads: prompts, answers, tool arguments/results, retrieved documents, and raw
telemetry are intentionally excluded. The current local access policy grants
`codex-development` `READ_RCA` at INTERNAL clearance, so it can analyze only
RLS-visible INTERNAL runs.

| Use Case / Scenario | Query | User Clearance | Expected Result |
|---|---|---|---|
| RCA overview | 1. UI: `What happened to P4901?` at INTERNAL. 2. MCP: `analyze_run(run_id, focus="overview")`. | INTERNAL | Reports observed run lifecycle/tool metadata and source completeness. It does not expose P4901 payloads or emit CONFIRMED_RUN_CAUSE. |
| RCA failure | 1. Create a genuine failed INTERNAL run through an actual bounded service failure. 2. Find it with `runtime_mcp.list_recent_agent_runs(status="failed")`. 3. Call `analyze_run(run_id, focus="failure")`. | INTERNAL | Reports OBSERVED failed runtime/span/tool locations and limitations. A failure location is not a confirmed cause; no telemetry is manufactured. |
| RCA performance | 1. Execute a genuine INTERNAL UI run with Tempo/Langfuse enabled. 2. Call `analyze_run(run_id, focus="performance")`. | INTERNAL | When trace timing can be attributed to components, reports the dominant measured component and its share, never “slow”, abnormal, or a root cause. Missing sources or unattributable timings yield partial/insufficient evidence. |
| Confidential RCA boundary | Analyze a CONFIDENTIAL P4711 run with `codex-development`. | INTERNAL | Runtime RLS returns neutral unavailable before telemetry lookup; a run ID is not authority. |

## 8. Execution Notes

For UI/API acceptance inspect only run classification, selected tool names, and rendered
answer. For the small live verification inspect Tempo/Langfuse metadata only:
classification, model profile/provider/execution zone, tool names, token/cost provenance,
and privacy boundaries. Do not print prompts, responses, tool payloads, retrieved
content, or credentials. The existing message field and clearance selector are sufficient;
no UI redesign is required.
