# Full Architecture / Security / Quality Review

## Executive summary

After three stabilization iterations, the local baseline passed the complete safe verification. Phase C independently identified five MEDIUM findings and one LOW finding, with no new CRITICAL or HIGH finding confirmed. Findings remain unchanged. The most security-relevant new issue is C04: effective PUBLIC_CLOUD endpoints may carry credentials over HTTP. C01 and C02 concern blocked request loops and detached provider workers; C03 is a vacuous regression introduced during stabilization. A green baseline is not proof of absence of these defects.

## Verified baseline

Branch `main`, HEAD `7bd09dc73204774e885b5dca9d589819a2ced0b1`, DIRTY with explicit stabilization changes and reports, no staging. [Verification](full-stack-verification-2026-10-13.md) and [stabilization protocol](full-stack-stabilization-2026-10-13.md). Frozen iteration 3: seven no-cache rebuilds, 20 healthy services / zero restarts, 1,443 backend passes / one platform skip, 107 INTEGRATION passes, 231 frontend passes, 15 Chromium fixture passes, FAST/Ruff/format/build/syntax/link/diff checks passed. Source/test hashes remained identical throughout Phase C.

## Methodology

The scope was the repository as a system: domain/application/agent/tools/infrastructure, transport/composition roots, frontend, all supported services/configuration, SQL migrations, tests/evals/harness, dependencies and current documentation. Code/configuration were inspected directly, not accepted from prose claims or green tests alone. Repository-wide AST inventory covered 265 Python files / 63,993 lines (118 source, 95 test, 12 scripts, 15 eval, 25 migration files); focused flow inspection and code search traced every implemented trust boundary. This is an engineering review, not a formal proof or a claim that every third-party line was audited.

Data/attack flow considered: untrusted browser -> verified gateway identity -> fixed API principal -> trusted classification -> RLS-visible state/evidence -> model capability/assignment/security policy -> final adapter destination; model tool proposal -> trusted execution policy -> authoritative action-bound approval -> atomic claim -> simulator/domain capability -> deterministic post-action verification. Diagnostic flow gates runtime/RLS before trace/log/metric projections and optional safe RCA explanation. Tests used actual boundaries with fixtures/fakes and isolated databases; Phase-C proofs are read-only process-local fixtures/MockTransport, never retained-stack writes, external models or real hardware.

Historical findings were cross-checked only after the independent inspection. Unsafe real-model/action smoke paths and external vulnerability services were not executed. Ambiguities were resolved conservatively: shared demo clearance is not labelled per-user ownership; unavailable original finding text is PARTIAL; config-only health is not readiness; public HTTP transport requires configuration influence and is not reported as anonymous compromise. Phase C changed reports/evidence only, no product/test remediation.

| Review area | Actual implementation/contract inspected | Assessment |
| --- | --- | --- |
| Architecture/composition | 118 source modules structurally indexed; domain/core import checks; composition roots; ADR-003/010/020 | No forbidden inward imports found; C01 exposes async boundary drift |
| Authentication/identity | Nginx verified remote_user map, server tokens, demo_security, mcp_access_control | Fixed authority and separate admin; no anonymous privileged injection observed |
| Authorization/ownership/RLS | PostgreSQL transaction-local clearance, FORCE RLS, run visibility, list/read/download/PDF, approvals | Shared clearance-based demo; no claim of per-user tenancy; current negative boundaries pass |
| Classification/egress | run_classification_policy, EvidenceLedger/observations, model_selection/egress, final provider wrapper | Monotonic labels, capability/security hard filters, no provider-error reselection; C04 TLS gap |
| Embeddings/retrieval | embedding_egress, Ollama client, scoped knowledge factory, ingestion/catalog/content paths | Explicit trusted labels, max batches, local 11434 destinations, no proxies/redirects; RLS before file/chunk loading |
| MCP/tools/HITL | Discovery adapter, MCP permissions, capability guards, persisted claims, graph boundaries, hardware preparation/execution | Permission is not approval; exact run/action/target/profile/clearance, atomic claim; synthetic replay/concurrency tests pass |
| Frontend | api.js generation checks, context purge, app.js navigation/BFCache, model dialog, URLs, storage/export | Aborted/ignored old responses rejected; stored reference only; known filename bug retained |
| Persistence/concurrency | 24 migrations, constraints/indexes/FKs, models, Postgres/in-memory stores, sequence lock, checkpoint lifecycle | RLS application records; framework checkpoints deliberately separate/no RLS; app authorization required |
| API/errors | Auth before protected data; strict schemas; normalized failures; bounded diagnostics; documents/PDF | No raw exception payload in public diagnostics; C01 blocking reader/PDF concerns |
| Error isolation | Broad catches in RCA, readiness, telemetry, orchestration | Optional telemetry/source failures degrade explicitly; authorization/runtime evidence fail closed; no proven fail-open protected execution |
| E2E/test trust | Required plans and step binding; status/auth guard; provenance/resume/aggregation; fixtures/fakes | No skipped required claim promoted to PASS; C03 three vacuous endpoint cases; manual/live limits explicit |
| RCA/AI robustness | Deterministic analyzer, optional projection/schema/semantic validation, finish reason/budgets/fallback | Generative explanation cannot override deterministic verdict; C01/C02 concurrency lifecycle |
| Observability/logging | Safe allowlists, diagnostic flattening, run-to-trace visibility, OTel/Langfuse adapters, raw logs | Payload-free structured projection; known raw query logging retained; startup export warnings |
| Docker/deployment | Seven Dockerfiles, full 20-service Compose, mounts/ports/health/dependencies/secrets | Loopback exposed ports, application nonroot, read-only runtime data, no privileged/Docker-socket mount; readiness limitations documented |
| Dependencies/supply chain | pyproject ranges, installed metadata, npm lock/vendor sync, base/third-party tags | Local pip consistency passes; Python/base tags not fully locked; no external vulnerability scan or CVE claim |
| Documentation | AGENTS, README, quality/E2E/runtime docs, architecture diagrams and all ADR status/index metadata | Current vs superseded text distinguished; current ADR-020 index omission C05; no diagram remediation performed |


## Overall assessment

PASS_WITH_FINDINGS for the authorized local demo verification/review. Not production, multi-tenant, real-model release or hardware certification. Five MEDIUM assessment issues warrant remediation in a separate task. No new unrestricted protected execution, auth bypass or sensitive cloud-inference route was safely demonstrated.

## Findings summary

| ID | Severity | Title | Confidence |
| --- | --- | --- | --- |
| C01 | MEDIUM | Synchronous evidence and document I/O blocks asynchronous request loops | HIGH |
| C02 | MEDIUM | Timed-out optional model calls leave uncapped detached provider workers | HIGH |
| C03 | MEDIUM | Three endpoint-security regressions pass before exercising the adapter | HIGH |
| C04 | MEDIUM | Public provider configuration permits plaintext HTTP credentials | HIGH |
| C06 | MEDIUM | Reused action ID aliases distinct approval generations within one run | HIGH |
| C05 | LOW | Current architecture-decision index omits accepted ADR-020 | HIGH |

## CRITICAL

None confirmed.

## HIGH

None confirmed.

## MEDIUM

### C01 — Synchronous evidence and document I/O blocks asynchronous request loops

Severity: MEDIUM. Category: Architecture / concurrency / availability. Confidence: HIGH.

Affected files/components: `src/industrial_ai_agent/application/rca_analysis.py:136; infrastructure/rca_evidence.py:317; infrastructure/observability_backends.py:462; infrastructure/api/app.py:546,870; infrastructure/persistence/postgres.py:455`.

Observed behavior: RcaEvidenceCollector.collect calls synchronous Tempo/Loki/Prometheus/Langfuse ports directly after its async authorization gate. Async document open/download handlers likewise call a synchronous database/file reader directly. A 150 ms fake trace delays a 10 ms heartbeat to 172 ms; a 200 ms fake document reader delays an independent /health response to 203 ms.

Expected behavior: Authorized slow evidence/file operations should not stall unrelated requests, healthchecks or timeout/cancellation handling on the service event loop.

Root cause: An async outer signature is used with blocking lower-level ports/adapters and no offloading. S07 fixed only optional explanation; deterministic evidence acquisition and API document I/O retain the separate problem.

Security/correctness impact: An authenticated slow evidence/download request stalls its service's event loop; backend outages or large files can amplify delay. No auth bypass or actual service exhaustion was demonstrated.

Safe reproduction/evidence: phase-c/concurrency-proofs.json and api-blocking-proof.json; actual collector/API with injected fixtures, zero runtime stack requests or models.

Why existing tests did not catch/prevent it: Existing fake evidence/readers return immediately; their correctness assertions do not run a simultaneous unrelated request. The new explanation-concurrency regression covers a different stage.

Recommended remediation: Use async adapters or bounded worker offloading at the synchronous I/O boundaries, preserving authorization before data access and resource lifecycle.

Recommended regression tests: Deterministic event/barrier slow evidence and document fixtures; prove unrelated health/read operations progress and cancellation/deadlines remain responsive.

Disposition: NOT_FIXED (Phase C).

### C02 — Timed-out optional model calls leave uncapped detached provider workers

Severity: MEDIUM. Category: Lifecycle / concurrency / robustness. Confidence: HIGH.

Affected files/components: `src/industrial_ai_agent/application/rca_reasoning.py:263; infrastructure/rca_mcp_server.py:297,427`.

Observed behavior: Each _chat_with_timeout creates a new single-worker executor. On timeout, cancel() cannot stop an already running call and shutdown(wait=False) detaches it. Three synthetic deadlines returned while all three provider workers remained alive; the proof then released and joined them.

Expected behavior: Returning deterministic fallback should bound total provider concurrency/resources, including operations that outlive the client-visible deadline.

Root cause: The limit is per newly allocated executor, with no shared capacity or permit retained until the underlying provider job actually ends.

Security/correctness impact: Stalled/non-cooperative calls can accumulate workers and retained requests despite completed fallback responses. Normal SDK timeouts often limit duration, but they are not an aggregate capacity bound; resource exhaustion itself was not attempted.

Safe reproduction/evidence: phase-c/concurrency-proofs.json: three timeouts, three running workers. Only three event-controlled fake calls, all released/joined; no inference or stress test.

Why existing tests did not catch/prevent it: Timeout tests assert an individual unavailable explanation and deterministic fallback, not outstanding worker capacity across repeated/concurrent calls.

Recommended remediation: Use a shared bounded executor/admission limit whose capacity remains held until the actual provider call completes; preserve fallback and explicit provider deadlines without unsafe thread cancellation.

Recommended regression tests: Block fake provider calls behind events, issue repeated/concurrent deadlines and assert a fixed active+queued limit; verify recovery and cleanup after release.

Disposition: NOT_FIXED (Phase C).

### C03 — Three endpoint-security regressions pass before exercising the adapter

Severity: MEDIUM. Category: Test trust / false-positive coverage. Confidence: HIGH.

Affected files/components: `tests/unit/test_stabilization_regressions.py:test_effective_local_destination_is_checked_before_sdk_creation; src/industrial_ai_agent/agent/llm.py:LLMRequest`.

Observed behavior: The new three-case regression constructs LLMRequest(messages=()) inside pytest.raises(ValueError/PermissionError). Pydantic rejects the empty tuple before adapter.chat executes. Replacing the adapter with a spy still lets all three test functions succeed with zero chat calls.

Expected behavior: The regression must supply a valid request, reach the endpoint guard, and specifically assert denial before SDK creation.

Root cause: Overbroad expected exception matches unrelated input-schema validation during argument evaluation. This mistake was introduced by this task's stabilization test, and discovered only in Phase C.

Security/correctness impact: Three green cases falsely claim security-boundary coverage and would not catch removal of the endpoint check. Independent valid-request proofs confirm the actual guard currently denies all three destinations; no product egress bypass is claimed.

Safe reproduction/evidence: phase-c/test-trust-proof.json: three test functions pass, zero adapter calls, three real guard denials with valid synthetic requests. No repository test modified in Phase C.

Why existing tests did not catch/prevent it: The failing input constructor itself supplies the expected exception; no call counter asserts that the authorization boundary was exercised.

Recommended remediation: Replace the empty message tuple with a valid synthetic request; assert the intended denial reason and explicit guard/SDK invocation counters.

Recommended regression tests: Temporarily bypass the guard in an isolated monkeypatch/fake process and ensure the regression fails; valid denied calls must reach the guard but never SDK/network.

Disposition: NOT_FIXED (Phase C).

### C04 — Public provider configuration permits plaintext HTTP credentials

Severity: MEDIUM. Category: Security / endpoint configuration / credential transport. Confidence: HIGH.

Affected files/components: `src/industrial_ai_agent/infrastructure/llm/configuration.py:ModelConfig.base_url; infrastructure/llm/openai_compatible.py:_validate_destination`.

Observed behavior: A PUBLIC_CLOUD model with api_key authentication and http://provider.invalid/v1 validates and passes the final PUBLIC egress policy. Actual OpenAI SDK MockTransport observes an HTTP request carrying the synthetic Authorization credential. The deployed catalogs currently use HTTPS for public providers; this was not a runtime secret exposure.

Expected behavior: Resolved external public-provider destinations should require HTTPS before credentials or model input are submitted, including environment overrides.

Root cause: AnyHttpUrl and _validate_destination accept both HTTP and HTTPS; only LOCAL adds a zone-specific host restriction. There is no external credential-transport TLS invariant.

Security/correctness impact: An operator catalog/override mistake can transmit API credentials and PUBLIC payload without encryption. Requires deployment configuration influence, not an unauthenticated request; no actual key or external network was used.

Safe reproduction/evidence: phase-c/plaintext-provider-proof.json: scheme=http, synthetic credential present, real network calls=0, real credentials=0.

Why existing tests did not catch/prevent it: Public-provider fixtures normally use HTTPS; endpoint tests concentrate on local egress and redirect/proxy controls, not TLS for public credentials.

Recommended remediation: Require HTTPS for PUBLIC_CLOUD at effective endpoint resolution before SDK access, retaining explicitly approved local HTTP behavior.

Recommended regression tests: Catalog and environment-override HTTP public destinations must deny before factory/network; HTTPS public and bounded local HTTP positive cases remain valid.

Disposition: NOT_FIXED (Phase C).


### C06 — Reused action ID aliases distinct approval generations within one run

Severity: MEDIUM. Category: Protected-action identity / idempotency / correctness. Confidence: HIGH.

Affected files/components: `src/industrial_ai_agent/tools/maintenance_ticket.py:96`; `infrastructure/api/run_store.py:wait_for_approval`; `infrastructure/api/postgres_run_store.py:_wait_for_approval`; `agent/langgraph_troubleshooting_agent.py:_prepare_mcp_action_node`.

Observed behavior: Two separately persisted and approved actions in the same run use the same model call/action ID, first for S04 and then S02. Both authoritative claims succeed and are consumed. The second operation returns the first S04 ticket and first summary, with only one ticket stored. It never performs the second approved operation.

Expected behavior: Each newly approved operation must have an immutable, unique execution identity. Reusing an identifier for a different target must be rejected before claim consumption, or receive a new server-owned approval-generation identity; idempotent retry must remain bound to the same operation.

Root cause: S04's stabilization repair scopes repository idempotency to run_id + model action_id. The action ID is still reusable across multiple approval cycles in that run, and the stores replace the current approval payload without a unique generation or consumed-action registry. Current exact-target lookup authorizes each current payload but does not distinguish its business execution identity from the prior generation.

Security/correctness impact: A later approved maintenance action is silently lost and acknowledged with an earlier ticket for a different station/summary. This is a meaningful correctness/action-binding gap, not unauthorized execution or cross-user disclosure. The executing principal still requires an authoritative approval.

Safe reproduction/evidence: `evals/results/stabilization-2026-10-13/phase-c/action-generation-proof.json`: two approved cycles, same run/action ID, requested S04 then S02, same ticket returned, second station S04, ticket count one. Real InMemoryAgentRunStore, AgentRunStoreActionApprovalPort and capability; zero runtime database writes/hardware/models.

Why existing tests did not catch/prevent it: Replay tests consume one approval, and S04's new regression uses two distinct run IDs. No regression creates two new approved generations in one run with a reused model action ID and different targets.

Recommended remediation: Assign and persist a trusted unique approval-generation/action identity, enforce its immutable run/target/profile binding and use it for idempotency. Deny reused identities that conflict with prior execution before consuming the new claim. Do not weaken replay or clearance checks.

Recommended regression tests: Two approved generations in one run with reused model IDs and differing target/summary must produce two correctly bound operations or reject the second without consuming its approval. Keep exact-operation retry, cross-run collision, replay and concurrent claim tests.

Disposition: NOT_FIXED (Phase C). This is a newly reproduced intra-run approval-generation invariant, distinct from the cross-run collision repaired as S04. S04's scoped verification remains valid; its repair does not certify this broader lifecycle case.

## LOW

### C05 — Current architecture-decision index omits accepted ADR-020

Severity: LOW. Category: Documentation / architecture conformance. Confidence: HIGH.

Affected files/components: `AGENTS.md:762-786; docs/decisions/ADR-020-deterministic-investigation-evidence-requirements.md; docs/architecture/overview.md:906`.

Observed behavior: AGENTS' Current Architecture Decisions index stops at ADR-019. ADR-020 is Accepted and already governs the implemented deterministic evidence ledger; the architecture overview references it.

Expected behavior: The current agent-facing architecture index should identify the accepted decision governing active evidence enforcement.

Root cause: The decision/implementation was added without synchronizing the central AGENTS index.

Security/correctness impact: A maintainer following the index can overlook a current contract during orchestration/evidence changes. Limited documentation/maintenance impact; no runtime bypass.

Safe reproduction/evidence: Actual AGENTS index, accepted ADR-020 status and current overview reference; phase-c/adr-status-inventory.json. This is a current index omission, not harmless superseded historical wording.

Why existing tests did not catch/prevent it: Conformance tests check selected architecture statements and links, not that the current decision index covers all applicable accepted ADRs.

Recommended remediation: Add the current ADR-020 entry/reference to AGENTS; preserve its English-only exception. No architecture change is required.

Recommended regression tests: A lightweight documentation check comparing applicable accepted ADR IDs with the maintained current index.

Disposition: NOT_FIXED (Phase C).


## Known baseline issues

Document download uses document.filename instead of the API filename; known pre-existing issue, not a new finding. Four known LOW groups remain: raw API query logs, config/component-only Loki/Collector healthchecks, transient startup telemetry ordering, optional Grafana provisioning directories. S01-S13 fixes and historical earlier review issues are not counted again. C01 is materially broader/separate lower-boundary I/O from S07's optional explanation fix; C02 is provider worker lifecycle; C04 is public TLS rather than S01's local destination/redirect boundary. C03 was introduced by this task and explicitly retained after discovery under the Phase-C no-fix rule. C06 identifies a separate intra-run approval-generation limitation remaining after S04's cross-run repair; it is not counted as another automatically fixed defect.

## Unconfirmed risks

- Shared clearance subjects and no tenant owner field are an explicit demo contract (ADR-013/README), not an invented isolation guarantee. Production tenant identity/ownership remains unverified.
- Framework checkpoints deliberately have no RLS; API authorization and server-owned run/thread binding are the boundary. Independent DB credentials/least-privilege isolation remain deployment risks, not a reproduced bypass here.
- Cloud model failures, actual local model judgment, gateway identity switches, hardware/vendor failure behavior and live manual release journeys were not measured. REAL_MODEL_E2E is NOT_RUN.
- Cold OCR/reranker artifact downloads create availability/supply-chain network dependence; Python ranges and mutable base/service tags prevent byte-identical dependency rebuild guarantees. No CVE is claimed.
- Model assignment snapshot checks cannot by themselves attest running server image provenance or rule out external admin ABA changes. No material product false-pass through this route was reproduced; local source/client provenance is what the harness binds.
- Authorized downloads/opened documents cannot be retroactively erased outside owned UI state. Blob revocation is not a claim to erase an already downloaded file.
- Approval consumption precedes a side effect; a provider/device/database failure after claim may lose execution liveness. Exactly-once claim is not a distributed transactional hardware guarantee; no real hardware was invoked.

## Previous Findings 1-12

The original complete report is unavailable. Commits f432fa8, 2057d53, 4374898, 92deec6, 324fa4e, 0d250ca, 848921e, 6561523, 46083f4 and 7bd09dc identify available repaired areas. Mapping 2-8 is provisional. No measured regression is asserted; FULL/CLOSED below applies to the concrete available property, not undocumented original scope. All-twelve closure: NOT_CERTIFIED.

| Finding | Status | Evidence |
| --- | --- | --- |
| 1 | PARTIAL | Gateway: 19 isolated Nginx/API tests; anonymous denial, authenticated Basic 200, admin separation; original full statement absent |
| 2 | PARTIAL | Server-owned API/MCP principals and clearance ceilings; API/gateway auth tests; original ID mapping unavailable |
| 3 | PARTIAL | PostgreSQL FORCE RLS; 14 factory and 14 runtime integration cases; hidden/unknown append denial; shared demo, no tenant-ownership certification |
| 4 | PARTIAL | Monotonic request/evidence classification and model-egress tests; original ID mapping unavailable |
| 5 | PARTIAL | Direct protected MCP permission/profile/approval denials, action/run/target binding, public read-only surface |
| 6 | PARTIAL | Persisted single-use approval, replay and concurrent exactly-once tests; cross-run ticket regression |
| 7 | PARTIAL | 278 embedding-egress cases plus model-egress cases; local retrieval smoke; three endpoint regression cases qualified by C03 |
| 8 | PARTIAL | Frontend generation purge, ignored abort/stale responses, Blob revocation, downgrade/upgrade and model-dialog tests |
| 9 | CLOSED | Authenticated actual CLI fixtures and unexpected HTTP-status regressions; live safe denial/read smoke |
| 10 | CLOSED | Required assertion/step binding, missing IDs/tools/security evidence, wrong PDF, NOT_RUN rejection; actual CLI aggregate/resume provenance |
| 11 | PARTIAL | Documentation conformance, 56 existing local links, ADR status/implementation comparison; C05 index drift |
| 12 | CLOSED | Deterministic RCA remains available on optional timeout/provider/schema/semantic/finish-reason failure; complete-suite diagnostic logging passes |

## Test/quality observations

All final configured safe gates pass, one explicit platform skip. C03 demonstrates why green output does not establish claimed boundary coverage; independent valid-request proof currently confirms actual local destination denial. Earlier 20 full-suite failures and seven iteration-2 frontend failures remain preserved with diagnosis and justified code/fixture changes. No retry-to-green flakiness masking. Fifteen browser fixtures validate real DOM/evidence/assertion behavior using synthetic HTTP; they do not certify live model choices or manual identity/HITL claims. Syntax/link/build tooling gaps are NOT_CONFIGURED/NOT_RUN, not invented PASS.

## Runtime/Docker observations

20 healthy project services, zero restarts, eleven active volumes and an older unused project volume retained. Images rebuilt three times; unrelated Ollama untouched. Existing application data preserved. Startup telemetry failures and readiness lag are explicitly recorded; none remained a MEDIUM/HIGH/CRITICAL baseline blocker. Constraint/auth errors match expected negative tests. Image/tag and selective service/environment-key inventory are retained without secret values.

## Documentation conformance

ADR-008 historical/superseded routing is not treated as a current violation; ADR-019 controls selection. ADR-020 is accepted/current (C05). README/ADR-013 explicitly describe shared-secret, loopback, no logout/federated identity/TLS limitations; they are not production promises. Existing contracts now match the restored execution-boundary approval, embedding egress, monotonic classification and four-call loop. Synchronous evidence/I/O drift is C01. Reports have faithful local German counterparts; AGENTS remains English only. No architecture diagram was changed to conceal a review finding.

## Residual risk

Safe verified local behavior, limited to exercised contracts. No live/cloud model quality, original all-twelve finding text, remote production hardening or real hardware safety certification. New review findings remain in the frozen baseline by explicit instruction. Zero external LLM calls, hardware actions, commits and deployments.

## Recommended remediation order

1. C04: enforce HTTPS for external credential transport.
2. C01: remove blocking I/O from async service loops with bounded execution.
3. C03: make endpoint regressions reach the intended guard and prove they fail when it is absent.
4. C02: bound provider workers beyond returned optional timeouts.
5. C06: persist unique approval-generation identity and target-bound idempotency.
6. C05: synchronize the current architecture-decision index.

Review findings fixed: 0.

## Final artifact validation

Four report language pairs, 16 local report links, explicit finding fields, secret scans and frozen source/test hashes were checked. No staging or Phase-C remediation. Initial local artifact-check errors (regex capture and status wildcard handling) are preserved as TEST_DEFECT evidence; only generated checker code was corrected.
