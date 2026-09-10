# Industrial AI Agent Demo: Use Cases and Scenarios

This catalog is the manual acceptance script for synthetic `FACTORY-DEMO-01`. Submit
normal questions in the Web UI or to `POST /api/v1/runs`; use authenticated MCP for
direct tool and RCA checks. The UI selector maps to a server-owned `SecurityContext` at
`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `RESTRICTED`.

The selector simulates an already authenticated user's clearance only for this local
demo. It is not a production identity interface; production clearance must come from a
trusted server-side identity.

Visibility follows `user clearance >= data classification`. Factory and knowledge lists
are RLS-filtered before names, relationships, or classifications are returned. They
never reveal hidden entities, hidden counts, or required clearance. Higher user clearance
authorizes lower data but does not raise its run classification: a RESTRICTED P4711
request stays CONFIDENTIAL and remains public-cloud eligible.

Sections 1-6 cover normal agent behavior; section 7 covers read-only RCA. The
deterministic RCA report is authoritative. Optional reasoning may add labelled hypotheses
but cannot confirm a cause. All records and documents are synthetic.

## 1. Factory Discovery

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| Public station discovery | List the production stations available to me in this demo. | PUBLIC | Returns only S01 and S05 and no hidden count or other station name. |
| Internal station discovery | Provide a complete overview of the production stations available to me. | INTERNAL | Returns S01, S02, S03, and S05; does not disclose S04 or S07. |
| Restricted station discovery | List all production stations available to me, including their station IDs. | RESTRICTED | Returns all six stations, including S07. |
| Public product discovery | List the products available to me and summarize their final status. | PUBLIC | Returns only P4101 and P4102, both with final status COMPLETED. |
| Internal product discovery | Provide an overview of the products available to me and their final status. | INTERNAL | Adds P4900 and P4901 but not confidential/restricted products. |
| Station orientation | Provide an overview of station S02, including its current status and role in production. | INTERNAL | Returns its visible Positioning overview and current RUNNING state. |
| Product orientation | Investigate product P4801 and summarize its visible production path and latest status. | CONFIDENTIAL | Returns its latest completed state and visible path; its warning is not final status. |

## 2. Production Status

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| Available stations | Identify the production stations currently available and report their operational status. | INTERNAL | Identifies visible running S01, S02, S03, and S05 only. |
| Restricted status | Check the current status of station S07 and explain any reported fault or error code. | RESTRICTED | Returns FAULTED and PROTO-COMM-07 in a RESTRICTED run. |
| Recent failures | Identify recently failed products and summarize their visible failure status. | CONFIDENTIAL | Returns visible failed P4711 and P4811; P9001 is absent. |
| Products at station | List the products that passed through station S04 and summarize their visible processing status. | CONFIDENTIAL | The bounded S04 overview returns visible P4811, P4801, and P4711. |
| Successful product | Investigate the production history of P4101 and summarize its completed path. | PUBLIC | Shows completed public S01 and S05 trajectory. |
| Explicit product failure | Investigate what happened to product P4901 and explain its final processing status and any error. | INTERNAL | Shows completed S01 and explicit POSITION-ENC-02 failure at S02. |

## 3. Product Investigation

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| P4711 history | Investigate the complete production history of P4711. Summarize its station sequence, warnings, and final error. | CONFIDENTIAL | Shows S01 completion, S02 POSITION-ENC-02 warning, S03 completion, and S04 QUALITY-09 failure chronologically. |
| Higher user, lower run | Investigate why product P4711 failed at station S04. Check the relevant product history, inspection results, and error codes, and use the available documentation if needed. | RESTRICTED | Resolves CONFIDENTIAL run/RLS ceiling, not RESTRICTED; public-cloud routing remains possible. |
| Confidential denial | Investigate the available history and failure details for product P4711 at station S04. | INTERNAL | Returns neutral `requested_data_unavailable`; no model call or existence disclosure. |
| Warning relevance | Review P4711's production history and assess whether earlier warnings are relevant to its later failure at station S04. | CONFIDENTIAL | Separates S02 warning from S04 failure; any causal link is explicitly an inference. |

## 4. Knowledge & Documentation

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| QUALITY-09 lookup | Explain QUALITY-09 using the available technical documentation, and summarize what the error means. | CONFIDENTIAL | Returns eligible documentation with source/chunk provenance. |
| Positioning procedure | Explain how to investigate POSITION-ENC-02 using the available technical documentation. | CONFIDENTIAL | Returns eligible troubleshooting material without proving P4711's cause. |
| S04 documents | Find the technical documentation available for station S04 and summarize the relevant troubleshooting guidance. | CONFIDENTIAL | Returns only matching documents visible at the run ceiling. |
| Restricted denial | Search the available documentation for product P9001 at station S07 and summarize any accessible guidance. | CONFIDENTIAL | Neutral unavailable behavior; no restricted title, content, or count leaks. |

## 5. Cross-source Investigations

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| History plus knowledge | Investigate where P4711 failed and explain the reported error code. Use the relevant product history and documentation. | CONFIDENTIAL | Combines product history and documentation; evidence and explanation are distinguishable. |
| Warning plus state | Review P4711's previous warnings and the current state of the station where it failed. Clearly distinguish observations from inferences. | CONFIDENTIAL | Combines product history with S04 status and labels inference. |
| Restricted cross-source | Investigate product P9001 at station S07. Review its production history, current station status, and available documentation, then summarize the findings. | RESTRICTED | Combines restricted history, status, and documentation; lower-clearance users cannot discover it. |

## 6. Restricted Data

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| Product non-leakage | Provide the information available to me about product P9001, including its current or final status if accessible. | CONFIDENTIAL | Neutral unavailable/not-found semantics without identifier details, count, or required clearance. |
| Station non-leakage | Provide the information available to me about station S07, including its current status if accessible. | CONFIDENTIAL | Neutral unavailable/not-found semantics without restricted state or count. |
| Ticket lookup | Show the available details for maintenance ticket MT-S02-20260117 and summarize its visible status and affected equipment. | CONFIDENTIAL | Uses `get_maintenance_ticket` to return only the visible projection of the deterministically seeded CONFIDENTIAL ticket. User-facing text remains English even when structured ticket values use technical English. |
| Ticket non-leakage | Show the available details for maintenance ticket MT-S02-20260117 and summarize its visible status and affected equipment. | INTERNAL | An unknown or RLS-hidden ticket produces the same neutral unavailable result, without summary, station, status, classification, or required-clearance disclosure. User-facing text remains English. |

## 7. Root-Cause Analysis

RCA MCP exposes `analyze_run(run_id, focus="overview" | "failure" | "performance",
reasoning="none" | "explain")`. It analyzes a persisted agent run, not production
payloads: prompts, answers, tool arguments/results, retrieved documents, and raw
telemetry are intentionally excluded. The current local access policy grants
`codex-development` `READ_RCA` at INTERNAL clearance, so it can analyze only
RLS-visible INTERNAL runs.

| Use Case / Scenario | Prompt | User Clearance | Expected Result |
|---|---|---|---|
| RCA overview | Create an INTERNAL investigation for product P4901, then analyze the resulting run with an RCA overview and summarize the observed run lifecycle, tool usage, and source completeness. | INTERNAL | Reports observed run lifecycle/tool metadata and source completeness. It does not expose P4901 payloads or emit CONFIRMED_RUN_CAUSE. |
| RCA failure focus without a failed run | Create a successful INTERNAL investigation for product P4901, then analyze the resulting run with an RCA failure focus. | INTERNAL | The deterministic report contains no invented failure location or confirmed cause. It returns only genuinely observed failure findings, or an empty failure projection with limitations. A failed-run scenario is accepted only after a deterministic fixture or supported bounded failure scenario exists. |
| RCA performance | Run an INTERNAL investigation with tracing enabled. Analyze the resulting run with an RCA performance focus and summarize measured component timing if available. | INTERNAL | When trace timing can be attributed to components, reports the dominant measured component and its share, never “slow”, abnormal, or a root cause. Missing sources or unattributable timings yield partial/insufficient evidence. |
| Confidential RCA boundary | Attempt to analyze a CONFIDENTIAL P4711 investigation run using codex-development access and report only the information available to you. | INTERNAL | Runtime RLS returns neutral unavailable before telemetry lookup; a run ID is not authority. |

## 8. LLM Provider Limits

Provider limits are external execution blocks, not functional agent failures. A known
OpenAI-compatible provider rate limit persists `llm_rate_limit`; an explicit known
quota code persists `llm_quota_exceeded`; known provider connection or maintenance
failures persist `llm_provider_unavailable`. These cases produce a sanitized,
response-language-specific message and are rendered as an amber **Limit reached** state
after a history reload. Their acceptance outcome is `BLOCKED_BY_PROVIDER`, while
`internal_error` remains `FAIL`. Provider messages, account metadata, token quotas,
request IDs, and retry headers are not displayed or included in the acceptance evidence.

## 9. Execution Notes

## 10. Investigation History and PDF Export

Start a `CONFIDENTIAL` ticket investigation, continue it twice, and verify that distinct
run IDs share one investigation ID, remain ordered, and preserve individual languages.
Use **Export as PDF** and confirm `investigation-<id>.pdf` contains only visible turns.
With lower demo clearance, both confidential history and PDF must be unavailable.

For UI/API acceptance inspect only run classification, selected tool names, and rendered
answer. For the small live verification inspect Tempo/Langfuse metadata only:
classification, model profile/provider/execution zone, tool names, token/cost provenance,
and privacy boundaries. Do not print prompts, responses, tool payloads, retrieved
content, or credentials. The existing message field and clearance selector are sufficient;
no UI redesign is required.

The response language is selected once from the original free-text request: German
requests receive German user-facing text and English requests receive English user-facing
text across all tool loops and an approval resume. Ambiguous or identifier-only requests
use the deterministic English fallback; technical IDs and structured tool values remain
unchanged.
