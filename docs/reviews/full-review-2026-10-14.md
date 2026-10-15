# Full Architecture / Security / Quality Review — 2026-10-14

## Executive Summary

The final clean local verification passes. The independent review nevertheless reproduces
six findings: **0 CRITICAL, 2 HIGH, 3 MEDIUM, 1 LOW**. A stale human approval can approve
a different action generation, and a failed identity refresh after a successful switch
leaves confidential content in another tab. These require remediation before treating
the demonstrated security guarantees as complete. No review finding was fixed.

Normal demo quick switch, shared classification-based investigations, admin at PUBLIC
and restricted users without MODEL_ADMIN are intentional and are preserved.

## Verified Baseline

Reference: [Full Verification](full-verification-2026-10-14.md).
Branch `main`, HEAD `67c35b91e853cbd334c9be4c7c1dbe480d78ca1a`. Existing tracked
files remain unchanged. Freeze manifest and UTC transition time:
`evals/results/stabilization-2026-10-14/phase-d-frozen-manifest.json` and
`phase-d-start.txt`. Final cycle: seven no-cache image builds, 20 healthy services,
zero restarts, 1,663 Python passes / one platform skip, 123 separate integration passes,
252 frontend passes, 41 Chromium fixtures, 43 runtime and 21 live UI checks.

Review-only additional regressions: **398 passed**, zero failures/skips.
`d-regressions.xml` records C01/C02/C04/C06, C03 controls, embedding and documentation.
These green gates coexist with the new synthetic proofs below.

## Scope

The entire tracked repository is in scope: 441 tracked files; static AST/import/call and
exception inventory for all 280 Python files, including 120 production modules; all
architectural areas, migrations, composition roots, frontend modules, Docker definitions,
dependency manifests, scripts, eval harnesses and current/historical documentation.
Manual inspection concentrates on final enforcement boundaries and their callers;
this is not a claim that every possible state/interleaving has been exhaustively proved.

| Area | Inspection and measured evidence | Conclusion / limits |
| --- | --- | --- |
| Architecture | Domain/Core imports; roots, inner ports, sole LangGraph loop; ADR-003/004/010/019/020 | No forbidden Domain/Infrastructure import direction found; adapter bypass R01 remains |
| Authentication | DemoSessions, server resolver, cookie middleware, Nginx; five live users and disabled-mode fixtures | Random HttpOnly/Strict `/api/` cookies, eight-hour TTL, 4096 capacity; role != clearance; R04 failure branch |
| Authorization/RLS | Read/list/document/PDF adapters; SQL policies and role flags; real DB matrices | RLS-before-load and neutral absence; classification-shared history intentional |
| Discovery | Complete forms, identifier recognition, unknown/mixed text, trusted context; exact seed/MCP subsets | No reproduced discovery downgrade; all five server identities and station/product contracts covered |
| Model egress | MANUAL/AUTO, capability/security filters, wrappers, raw adapter, effective URLs | Wrapped denies, HTTPS cloud and local destination guards work; R01 missing raw classification guard |
| Embedding | Both adapter methods, explicit query/batch labels, conservative Knowledge composition | Missing labels deny; max document label; exact local destination, no proxies/redirects; C03 controls meaningful |
| MCP/tools | Discovery/dispatch permissions, strict schemas, one-tool loop, returned labels, transport bridge | PUBLIC read-only; direct protected calls require persisted claims; compatibility bridge Infrastructure-only |
| HITL | Proposal UUIDs, history/claim/replay/locks, public approval DTO, HTTP resume | Original generation aliasing fixed; human intent is not generation-bound (R03) |
| Frontend | Identity purge, abort/generation, shared tabs, BFCache, model dialog, popovers, language | Successful transitions and late responses pass; post-switch identity-read failure leaks stale tab state (R04) |
| Documents/PDF | RLS catalog lookup, path/checksum checks, safe filename/MIME, CSP, Blob cleanup | Filename fix closed; active MIME inert; saved PDF/read denials pass; no real classified live export created |
| RCA/concurrency | Runtime-before-telemetry, threaded readers, owned reasoning workers, deadline transport | C01 fixed; workers bound actual outstanding work; R02 synchronous ticket write, R05 first-client race |
| Database | Revision 0025, FORCE RLS, checks, unique request IDs, row/advisory locks, legacy generations | App role non-BYPASSRLS; seed idempotency and migration tests pass; crash between claim/write remains explicitly acknowledged |
| API/errors | Role gates, auth, schema validation, sanitized errors, status normalization, deadlines | Existing denial contracts hold; stale approval request can produce valid HTTP 200 for a new action |
| Error handling | Inventory plus targeted broad-except paths, source isolation, retries, timeout behavior | Optional telemetry/reasoning failure remains explicitly unavailable; no verified security fail-open besides findings |
| Test trust | Guard spies/mutation controls, HTTP status, REQUIRED assertions, aggregate/resume provenance | C03/Finding-9/Finding-10 controls trustworthy for their stated scope; new missing scenarios detailed below |
| Docker | 20 services, seven builds, loopback ports, app user, mounts, env key parity, health/readiness | No privileged container/host device mount introduced; component/config-only checks need separate readiness |
| Observability | Allowlisted metadata, collector sanitization, run visibility before MCP telemetry access | No observed secret/prompt/tool payload export; direct local dashboards/backends are a broader trusted-host surface |
| Dependencies | Local pyproject/Docker ranges, npm integrity lock, vendored asset tests, build scripts | Python/base tags not fully locked; no CVE claim or online vulnerability assessment |
| Documentation | AGENTS/README/overview/ADRs/demo/quality/E2E; local pairs/links | Current ADR refinements govern historical text; overview/E2E drift R06 |

## Methodology

A fresh pass over frozen source, contracts, SQL constraints, measured final Docker runtime
and browser behavior. No subagent or external AI service received repository data.
Proof programs are ignored non-invasive evidence artifacts, not new product tests.
All provider calls in proofs use MockTransport/fakes; all ticket/approval activity is
synthetic in memory. The browser proof runs the shipped UI and real API/session code
against the existing loopback fixture and blocks off-origin requests. No protected live
write, hardware action, cloud LLM, commit, push or external deployment occurred.

## Findings Summary

| ID | Severity | Title | Component | Confidence |
| --- | --- | --- | --- | --- |
| R03 | HIGH | Stale human decision authorizes a different approval generation | HTTP API / run stores / approval UI | HIGH |
| R04 | HIGH | Successful downgrade leaves another tab's confidential DOM after identity-read failure | Demo Auth frontend | HIGH |
| R01 | MEDIUM | Raw provider adapter accepts input without trusted classification authorization | Model adapter boundary | HIGH |
| R02 | MEDIUM | Synchronous ticket persistence blocks the async MCP event loop | Maintenance capability | HIGH |
| R05 | MEDIUM | Concurrent first use loses ownership of a provider client | Shared RCA provider adapter | HIGH |
| R06 | LOW | Current architecture/authentication descriptions retain obsolete gateway behavior | Documentation/diagram | HIGH |

## CRITICAL

None confirmed.

## HIGH

### R03 — Stale human decision authorizes a different approval generation

Severity: HIGH. Category: SECURITY_DEFECT. Confidence: HIGH.

Affected components/files: `infrastructure/api/app.py:594,1426`,
`infrastructure/api/schemas.py:252`, `infrastructure/api/run_store.py:319`,
`infrastructure/api/postgres_run_store.py:307`, `frontend/js/api.js` / approval controls.
Python paths here and below are relative to `src/industrial_ai_agent/`.

Observed behavior: a client views approval A for S04. Another approval/resume advances
that same run to a distinct pending approval B for S02. The old client's unchanged
`POST /runs/{id}/resume` approve request receives HTTP 200 and persists `approve` for B.
The public approval intentionally removes `approval_execution_id`; the resume schema
accepts a decision without an expected generation. PostgreSQL takes a row lock but
decides whichever generation is current, with the same omission as the in-memory store.

Expected behavior: approve/reject must bind the exact proposal the human reviewed;
stale decisions fail without altering B or consuming its authority. ADR-011's exact
run/action/target/generation binding must also cover decision creation, not just execution.

Root cause: execution generation identity stops at the public decision boundary.
The API checks current visibility and resumability, then claims by run ID alone.

Impact: an authorized human can unintentionally approve or reject another station/action.
The final executing guard then sees a valid persisted approval for B, so it cannot recover
the lost human intent. This does not grant higher clearance or bypass MCP permissions.

Safe reproduction: `review_proofs.py` / `review-proofs.json`, R03. Real FastAPI/TestClient,
real in-memory store, distinct server generations, fake resume service. Viewed S04,
approved S02, HTTP 200, B decision `approve`; zero real side effects.

Why current tests did not catch/prevent it: C06 tests bind execution claims and retries to
UUIDs, but do not submit a stale human HTTP decision after another generation becomes
pending. Simultaneous claims of one waiting generation do not cover this later-generation race.

Recommended remediation: return an opaque proposal revision/generation reference and require
it on approve/reject; compare it atomically with the waiting generation in both stores.
Reject stale decisions with 409. Keep authoritative lookup and final capability claims;
the reference must never itself grant authorization.

Recommended regression tests: two clients viewing A; one advances to B; stale approve and
reject for A must leave B undecided; same checks on PostgreSQL, browser and same-generation
concurrent submissions. Disposition: NOT_FIXED.

### R04 — Successful downgrade leaves another tab's confidential DOM after identity-read failure

Severity: HIGH. Category: SECURITY_DEFECT. Confidence: HIGH.

Affected components/files: `frontend/js/demo-auth.js:112,121`, shared-tab context lifecycle;
`tests/e2e/fixtures/demo-auth.spec.mjs` and auth-state tests lack this failure branch.

Observed behavior: two tabs share demo-confidential; tab B shows synthetic confidential
conversation. Tab A successfully switches the server session to demo-public, then its
follow-up `/auth/me` fetch fails. Tab B still displays demo-confidential and confidential
conversation, while a fresh server identity read confirms demo-public.

Expected behavior: all tabs purge protected state whenever the shared session might have
changed, even if metadata refresh fails. The current Demo Auth contract requires switch/
logout invalidation, not only successful refresh invalidation.

Root cause: BroadcastChannel notification is after the awaited `/auth/me` read. That
read throwing skips notification; local tab A purges, other tabs remain unaware.

Impact: lower-clearance shared browser context retains protected DOM/export state in
another tab; requests may be server-denied but existing visible data remains. This is a
failure-path disclosure, not the intentionally permitted demo quick switch itself.

Safe reproduction: `review-tabs.mjs`, `review-tabs.json`, `d-tabs.log`. Existing real
API/session fixture, shipped UI, two Chromium tabs, fake conversation, local route abort
only for tab A's identity read. Recorded server user PUBLIC, other tab CONFIDENTIAL and
confidential DOM retained; zero cloud/model/live-data calls.

Why current tests did not catch/prevent it: successful shared-tab switching and late
JSON/download cancellation are covered; no test fails metadata refresh after the cookie
mutation has succeeded. They therefore exercise the notification's success path only.

Recommended remediation: notify/invalidate other tabs independently of metadata refresh,
including ambiguous mutation outcomes; separate purge notification from subsequent
identity loading. Preserve generation checks and fail-closed local UI.

Recommended regression tests: switch success + identity-read network/JSON/HTTP failure;
logout ambiguous result; second-tab protected DOM, pending JSON, Blob/PDF/export state
must purge even when refresh fails. Include positive successful-switch controls.
Disposition: NOT_FIXED.

## MEDIUM

### R01 — Raw provider adapter accepts input without trusted classification authorization

Severity: MEDIUM. Category: SECURITY_DEFECT / architecture boundary. Confidence: HIGH.

Affected components/files: `infrastructure/llm/openai_compatible.py:84,185`,
`agent/llm.py` request port, `agent/model_egress.py`, adapter composition roots.

Observed behavior: a valid direct `OpenAICompatibleLLMClient.chat()` call sends synthetic
unclassified input to a PUBLIC_CLOUD MockTransport endpoint whose maximum is PUBLIC.
The raw adapter has no trusted request classification and cannot reject missing labels.
Wrapping the same adapter with EgressCheckedLLMClient rejects both missing classification
and RESTRICTED classification without another transport request.

Expected behavior: ADR-019 describes classification authorization repeated at the provider
boundary before protected serialization; missing classification denies, including direct
calls and future transitive consumers. HTTPS validation alone does not authorize data.

Root cause: transport destination is guarded inside the raw adapter, but classification
authorization exists only in an optional outer decorator. LLMRequest carries no trusted
classification, and raw construction is publicly callable.

Impact: alternate/current future callers can bypass classification policy by omitting
the wrapper. The inspected live agent/RCA roots do wrap it; no actual cloud disclosure
in the current HTTP path was reproduced. Severity reflects this narrower boundary defect.

Safe reproduction: `review_proofs.py`, R01: real adapter/SDK with HTTPS `.invalid`
MockTransport, one synthetic request; wrapped negative controls deny. No external network.

Why current tests did not catch/prevent it: classification tests target the wrapper;
direct adapter tests verify URL/TLS guards and successful SDK mappings, not missing
classification at that final concrete boundary.

Recommended remediation: require trusted classification/authorization at concrete adapter
invocation or construction, using the existing policy; make unsupported raw invocation
fail closed. Keep provider independence and avoid a duplicate policy implementation.

Recommended regression tests: direct missing/malformed classification and RESTRICTED
cloud deny before credential lookup, serialization, SDK and transport; authorized PUBLIC
positive control; all composition and transitive callers. Disposition: NOT_FIXED.

### R02 — Synchronous ticket persistence blocks the async MCP event loop

Severity: MEDIUM. Category: PRODUCT_DEFECT / availability. Confidence: HIGH.

Affected components/files: `tools/maintenance_ticket.py:99`, async Factory handler,
`infrastructure/persistence/postgres.py` synchronous ticket repository.

Observed behavior: after the awaited authoritative claim, the async capability calls
the synchronous create repository directly. A 200 ms synthetic repository delay moves
a scheduled 20 ms heartbeat to approximately 203 ms. The consumed-result read already
uses `asyncio.to_thread`, but the write branch does not.

Expected behavior: synchronous database I/O must not block the owning async server loop;
approval still precedes every side effect and operation lifetime remains owned.

Root cause: only the idempotent lookup branch received an async/sync boundary.

Impact: DB latency/lock waits in approved ticket creation stall other MCP requests,
health/readiness and cancellation processing. This is distinct from the repaired C01
RCA/document reader paths. It does not reproduce duplicate writes or a real hardware action.

Safe reproduction: `review_proofs.py`, R02; real capability and persisted in-memory
approval port, slow fake in-memory repository. Exactly one synthetic ticket; no real write.

Why current tests did not catch/prevent it: write/idempotency tests use immediate fake
repositories or assert eventual DB correctness; heartbeat/cancellation tests cover readers.

Recommended remediation: offload/await blocking creation with explicit lifecycle and
capacity semantics; preserve claim-before-write and unique request ID. Do not detach
non-idempotent work merely to return timeout early.

Recommended regression tests: event-controlled slow create keeps loop responsive;
concurrent reads/health; cancellation and late completion with one side effect; existing
generation replay/idempotency controls. Disposition: NOT_FIXED.

### R05 — Concurrent first use loses ownership of a provider client

Severity: MEDIUM. Category: PRODUCT_DEFECT / lifecycle. Confidence: HIGH.

Affected components/files: `infrastructure/llm/openai_compatible.py:185`,
`infrastructure/rca_mcp_server.py` shared adapter and reasoning workers.

Observed behavior: two concurrent first calls both see a missing model client. Two
factories run; the dictionary retains one client, and adapter.close closes one.
The overwritten client is outside explicit ownership. RCA shares the adapter across
its admitted reasoning workers, so the sequential troubleshooting loop does not prevent it.

Expected behavior: single owned client per stable model or complete ownership/cleanup of
every created client. C02's worker ownership does not substitute for SDK client ownership.

Root cause: check/create/assign in `_get_client` has no synchronization. Custom HTTPX
clients are supplied to OpenAI; its default wrapper destructor is not a guaranteed cleanup
mechanism for these injected clients.

Impact: duplicate startup initialization and unowned connection/transport resources on
concurrent cold use. This is bounded by cold first-use races/model count, not evidence of
an unlimited per-request leak. Actual socket exhaustion was not attempted.

Safe reproduction: `review-provider-race.py` / JSON: two threads, factory barrier,
synthetic SDK clients; created=2, cached=1, closed-by-adapter=1. The proof explicitly
closes both fake clients afterward. No provider or network operation.

Why current tests did not catch/prevent it: C02 measures owned workers, total transport
deadlines and individual transport close; no barrier forces concurrent `_get_client`
initialization and checks every created client's ownership.

Recommended remediation: synchronize lazy construction or initialize owned clients before
worker admission; explicitly close losing clients if a race remains. Bind adapter shutdown
to its service lifetime. Keep request context/deadline propagation unchanged.

Recommended regression tests: concurrent cold same-model and distinct-model use; count
factories and closure; failed construction; shutdown while workers finish. Disposition: NOT_FIXED.

## LOW

### R06 — Current architecture/authentication descriptions retain obsolete gateway behavior

Severity: LOW. Category: DOCUMENTATION. Confidence: HIGH.

Affected components/files: `docs/architecture/overview.md:39,471`, local German counterpart;
`docs/learning/browser-e2e-journeys.md` and its local German counterpart.

Observed behavior: the current overview Mermaid gateway label still says authenticated
demo user -> API token, and current prose describes username/password authentication and
token mapping. Actual Nginx strips Authorization and proxies session cookies. Current
E2E documentation says identity switching is automatically asserted, then says a second
ordinary identity is unavailable and identity switching is not an automated claim.

Expected behavior: canonical current docs/diagrams match ADR-013's current session
refinement and the shipped UI/fixture/runner behavior. Historical Basic-auth sections
explicitly superseded by ADR-013 may remain historical.

Root cause: some derived overview/coverage prose was not synchronized with the refactor.

Impact: misleading mental model for composition/security review and acceptance coverage;
no observed executable authentication bypass follows from the text itself.

Safe reproduction: compare named current paragraphs/diagram with `frontend/nginx.conf`,
DemoSessions and the 41 passing browser fixtures. Read-only local inspection.

Why current tests did not catch/prevent it: documentation checks assert selected facts,
routes and commands; they do not verify every Mermaid label or contradictory coverage
sentence. Link/translation-presence checks do not prove semantic consistency.

Recommended remediation: update the canonical overview label/prose and E2E coverage claim,
with matching ignored German changes; retain historical explanations explicitly as history.

Recommended regression tests: current auth fact/diagram label conformance and selected
coverage claims against the fixture/runner registry. Disposition: NOT_FIXED.

## Unconfirmed Risks

- No cloud, real-model, hardware, remote TLS/OIDC, multi-worker session or production
  identity certification. Session process locality and HTTP-only demo cookies are
  documented scope, not standalone findings.
- Direct loopback telemetry backends and anonymous Grafana are available to trusted local
  host users, independently of demo clearance. Raw Uvicorn request URLs and retained
  historical telemetry require a separate production exposure/retention design; no secret
  extraction or cross-clearance live content dump was performed.
- Collector component/Loki config checks alone can report healthy before useful readiness;
  both final cycles measured actual HTTP readiness and recovery. Startup OTel ordering and
  optional Grafana directory warnings remain known LOW operational notes.
- Python dependency ranges and mutable Docker tags make later clean builds potentially
  different. npm has an integrity lock and vendored asset checks. No offline evidence
  establishes CVEs, and none are invented.
- Persisted approval claim and side-effect creation are separate transactions. Crash
  recovery can leave consumed-without-result; ADR-011 acknowledges fail-closed behavior.
  This review makes no transactional exactly-once-under-crash claim.
- Original complete Findings 1–12 statements are unavailable locally; earlier provisional
  mappings cannot establish exact historical closure.

## Previous remediations regression status

| Item | Status | Current evidence / qualification |
| --- | --- | --- |
| Original Finding 1 | PARTIAL | Server demo-auth/live Nginx behavior verified; original exact statement unavailable; Basic removal intentional |
| Original Finding 2 | PARTIAL | Server-owned principals/clearance and role mapping pass; historical ID mapping incomplete |
| Original Finding 3 | PARTIAL | FORCE RLS and shared-classification visibility pass; no personal-tenancy contract assumed |
| Original Finding 4 | PARTIAL | Monotonic classification/discovery tests pass; R01 raw-boundary gap is independently reproduced |
| Original Finding 5 | PARTIAL | Direct MCP permission/profile/target claim denials pass; original scope unavailable |
| Original Finding 6 | PARTIAL | Atomic execution/replay/generation tests pass; new stale human-decision R03 remains |
| Original Finding 7 | PARTIAL | Embedding destination/label and C03 mutation controls pass; no original full statement |
| Original Finding 8 | PARTIAL | Late-response and ordinary transition purge passes; R04 adds a failed-refresh shared-tab gap |
| Original Finding 9 | CLOSED | Authenticated HTTP/status controls, exact expected denials and CLI exit regressions pass |
| Original Finding 10 | CLOSED | REQUIRED assertion execution, wrong PDF/filename, incomplete aggregation/resume controls pass |
| Original Finding 11 | PARTIAL | Current facts/links/ADR index checks pass; current overview/coverage drift R06 |
| Original Finding 12 | CLOSED | Optional RCA failures remain unavailable while deterministic evidence/report stays intact |
| C01 async evidence/document I/O | CLOSED | Existing heartbeat/read tests pass; R02 is the distinct ticket-write branch |
| C02 provider lifecycle | PARTIAL | Original detached-worker/capacity/deadline defect closed; cold-client ownership race R05 remains |
| C03 endpoint-test trust | CLOSED | Exact guard reach, valid request, positive endpoint and guard-bypass/earlier-denial mutation controls pass |
| C04 PUBLIC_CLOUD TLS | CLOSED | Direct/wrapped HTTP cloud denies before credential/SDK; HTTPS control and redirect/proxy regressions pass |
| C05 ADR conformance/index | CLOSED | ADR-020 listed in AGENTS and current refinements used; R06 is separate derived-doc drift |
| C06 approval-generation aliasing | PARTIAL | Original repeated model IDs/targets create distinct execution UUIDs; execution replay fixed; decision boundary R03 remains |
| Download filename | CLOSED | Actual browser filename/bytes match response; deliberately wrong filename control fails |
| Demo Auth/UI redesign | PARTIAL | Five-user/live header/toolbar/language/logout contracts pass; R04 failure-path notification gap |
| Discovery/visibility fix | CLOSED | Exact station/product seed/RLS subsets and one-tool synthetic graph flow; mixed sensitive input denies |

CLOSED means the available concrete property passed, not proof of unavailable historical
wording. No missing measurement is called PASS. The original all-twelve closure is
NOT_CERTIFIED. Broad lifecycle/approval statuses are PARTIAL without claiming the original
specific repair has reverted.

## Runtime observations

All final-stack services remain healthy without restarts. Startup Factory/RCA collector
export errors stop after readiness; Loki's initial 503/empty ring recovers after nine
polls. PostgreSQL error lines match intentional isolated negative tests plus one
read-only evidence-helper table-name typo; they are not live product failures. Optional
Grafana provisioning messages remain LOW. Retained Tempo WAL recovery is historical
data-integrity uncertainty. No new persistent provider/export/migration failure observed.

## Test trust assessment

The executable gates measure real invariants with fakes and real local boundary fixtures;
they are not dismissed merely because this review found gaps. In particular C03 reaches
the guard rather than passing on empty messages, and browser assertion failures cannot
be aggregated as PASS. The review proves missing coverage at independent boundaries:
human-intent generation, failed metadata refresh notification, raw adapter classification,
slow approved writes and concurrent cold client ownership. Synthetic fixtures do not
certify real-model answer correctness, protected live side effects or independent live
MCP browser evidence. REAL_MODEL_E2E remains NOT_RUN.

## Documentation conformance

AGENTS, README, demo-user visibility, quality gates and ADR-013's latest refinement match
the tested intended baseline. ADR-008 is superseded by ADR-019; original Basic-auth/
initial migration prose is not current authorization. R06 concerns text/diagram presented
as current. Existing EN/DE files are present and ignored correctly; this review introduces
only its report pairs, no contract or diagram change.

## Residual risk

Green stabilization gates support a healthy local demo, but the two HIGH findings prevent
a complete claim about action-bound human intent and cross-tab confidentiality under
failure. No external egress, real industrial effect or secret exposure occurred in these
reproductions. Findings are intentionally left in the frozen baseline for a separate repair.

## Recommended remediation order

1. R03: bind human decisions atomically to the viewed proposal generation.
2. R04: invalidate every shared tab independently of identity-refresh success.
3. R01: make classification authorization mandatory at the concrete provider boundary.
4. R02 and R05: correct blocking write and shared-client ownership lifecycles.
5. R06: synchronize current docs/diagram and local German counterparts.

Review-phase source/test/configuration/migration/Docker/contract changes: **0**.
Commits: 0. Deployments: 0. Findings fixed in Phase D: 0.
