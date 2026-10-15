# Full Architecture / Security / Quality Review — 2026-10-15

## Executive Summary

Final clean verification: PASS. The fresh review confirms **0 CRITICAL, 0 HIGH,
1 MEDIUM, 0 LOW** new findings. N01 is an availability defect: visible products/events
can reference an RLS-hidden station, and three product projections dereference the
resulting None relationship. No station disclosure was observed. Two disposable
PostgreSQL reproductions confirm it. **No review finding was fixed.** Overall:
PASS_WITH_FINDINGS.

R01–R06 remain CLOSED for their concrete repaired properties. Prior same-day review
F01/F02/F03 were repaired before freeze as S01/S02/S04; S03 repaired the required secret
scanner. Earlier same-day reports are archived in evidence/prior-reports. Historical
2026-10-14 reports remain byte-for-byte unchanged.

## Verified Baseline

Reference: [Full Verification](full-verification-2026-10-15.md).
main, HEAD 5f977d8a6203936599a183d6e64e08247d0d88f3, preserved initial report/index
work plus four stabilization repairs. Two stabilization cycles and a separate Phase C:
seven no-cache application builds, 20/20 ready, zero restarts; backend1777 passed/one
platform skip, integration131, frontend276, browser66; FAST, quality and build PASS.
REAL_MODEL_E2E: NOT_RUN.

Evidence root: `evals/results/stabilization-2026-10-15/run-02/` (evidence/ below).
Phase-D start is recorded in phase-d-start.txt; phase-d-manifest.json freezes 507 files,
including current local German contracts and .env hash without secret values.
Final hash comparison: zero frozen-file changes. Reports/non-invasive evidence exempt.

## Scope

459 versioned/nonignored working-tree paths inventoried. AST/import/call/exception scan
covers 288 Python modules, including all120 production modules. Detailed manual flow
inspection covers implemented trust/lifecycle boundaries, frontend, migrations, Docker,
dependencies and current/historical docs. This is not a line-by-line proof of every
interleaving or a third-party source/model-weight audit.

| Area | Current inspection/evidence | Assessment / boundary |
| --- | --- | --- |
| Architecture | Full import inventory; ADR-003/004/010/019/020, composition roots, sole bounded sequential LangGraph loop | No forbidden inward imports or alternate agent loop |
| Authentication | DemoSessions, cookie middleware/API, UI, Nginx, five live identities/disabled-mode tests | Random HttpOnly/Strict /api/ cookie; local HTTP has no Secure; TTL8h/capacity4096/process-local limits documented |
| Authorization/RLS | FORCE RLS, transaction-local clearance, roles, run/history/document/PDF visibility | No proved data bypass; N01 is related-row availability failure |
| Discovery/classification | Whole-form recognition, maximum known ID/context, unknown text, one-call budget, exact subsets | Seed scenarios pass; mixed relationship classification exposes N01 |
| Model egress | Trusted request-bound decision, concrete model/zone/ceiling guard before credentials/SDK/payload | R01 denial/MockTransport positive controls pass; zero cloud inference |
| Embeddings | Explicit document/query labels, conservative RESTRICTED fallback, local-only endpoint/proxy/redirect guard | Direct and transitive Knowledge controls pass |
| MCP/actions | Principals, permissions, strict schemas, current clearance, persisted generation/action/target/profile claim | Direct unapproved/stale/wrong-bound actions denied |
| HITL | Human DTO/token, atomic expected-generation decision, execution claim/history/idempotency | R03/C06 plus new cross-action/run/target/replay probes pass; S01 now displays actual target/action |
| Frontend | Context generation/abort, DOM/approvals, Blob/download/PDF, dialogs/language/history | Real shared cookies/BroadcastChannel/Chromium BFCache and failed sender/receiver refresh pass |
| Documents/PDF | RLS metadata before bytes, path/checksum, MIME/CSP, server filename, late-response cancellation | Positive/denial/wrong-filename controls pass; exported files cannot be recalled |
| RCA/concurrency | C01 off-loop I/O, C02 capacity/deadline/drain, R05 SDK/HTTPX ownership | No reproduced leak/deadlock/post-close publication; workers drain before adapter close |
| Ticket persistence | Claim before bounded AnyIO dispatch; full worker-local session; cancellation/replay | R02 passes; consumed-without-result crash window intentionally fail-closed |
| API/errors | Auth before load/claim, neutral404/stale409, schemas, broad-exception inventory | No observed authorization fallback; config I/O off-loop; N01 underlying AttributeError remains |
| Database | 25 revisions; fresh head/0021 upgrade; locks/unique keys/constraints/seed | Own-row RLS does not imply related-row visibility, N01 |
| Docker | 20 services/seven custom images, loopback ports, mounts/env/readiness | Zero privileged services; runtime data outside images; volumes preserved |
| Observability | Metadata allowlists/sanitization, run visibility before telemetry | No prompt/secret/session-content export observed; direct local dashboards are trusted-host surfaces |
| Dependencies | Local manifests, npm lock/vendor integrity, Python ranges/base tags/build hooks | Wheel/pip check pass; future reproducibility limited; no CVE claim |
| Test trust | C03 valid guards/positive controls, Finding9 HTTP/auth, Finding10 REQUIRED/resume/aggregation | Bounded valid evidence; N01 demonstrates missing mixed-relationship fixture |
| Documentation | README, overview, ADRs, demo, quality, actual fixture registry; EN/DE | R06 closed, S04 corrected README; current/historical auth explicit |

## Methodology

Fresh review pass after Phase-C freeze, independent of repair decisions. Static ownership
and boundary inspection, runtime evidence, real DB constraints and safe synthetic
falsification. No external AI/subagent/provider received repository data; no real ticket
or hardware operation. Phase-D measurements:

- d-regressions.xml: 478 passed, no failures/skips; C01/C02/C04/C06, R01/R02/R03/R05,
  embedding, documentation and new async-boundary tests.
- d-auth-approval-browser.log: 50 passed; actual shared-cookie sessions, BroadcastChannel,
  Chromium BFCache and generation-bound stale decisions.
- d-fixture-registry.log: 66 registered tests/four files; compared with package scripts,
  Playwright discovery and current docs. Registration alone is not runtime PASS.
- review-boundaries.json: 44 new mixed-input and wrong-action/run/target/summary/clearance/
  replay checks; reused model correlation does not alias generations.
- Independent S01 UI proof: generic summary, actual S02/action visible, decision carries
  displayed generation; fake resume/no execution.
- Independent 200ms I/O proofs: 20ms heartbeat observed at20.64ms (configuration) and9.62ms
  (MCP, Windows scheduling variation), both operations confirmed off-loop.
- N01 real PostgreSQL proof below. Proof-test PASS means defect reproduced, not product success.

An incorrect embedding filename, PowerShell pipeline/command-length invocation errors and
proof-fixture expectations (S01 was not latest; S05 was; CONFIDENTIAL sees nine products)
were corrected only in evidence invocations. First observations retained. These are not
product repairs, flaky gate reruns or hidden product failures.

## Findings Summary

| ID | Severity | Title | Component | Confidence |
| --- | --- | --- | --- | --- |
| N01 | MEDIUM | RLS-hidden station breaks visible product projections | PostgreSQL product/discovery adapters | HIGH |

## CRITICAL

None confirmed.

## HIGH

None confirmed.

## MEDIUM

### N01 — RLS-hidden station breaks visible product projections

Severity: MEDIUM

Category: PRODUCT_DEFECT / AVAILABILITY

Affected files/components: src/industrial_ai_agent/infrastructure/persistence/postgres.py,
get_product_history (line113), get_product_overview (line209), _product_discovery
(line262), _product_events (line269), and their product list/overview/history consumers.

Observed behavior: in a fresh migrated/seeded disposable DB, PUBLIC first sees two
products. Raise only station S05 to CONFIDENTIAL through the isolated admin connection,
leaving independently classified PUBLIC products/events intact. The DB accepts this
state. PUBLIC still sees two products/four events but zero S05 station rows.
list_products, get_product_overview(P4101) and get_product_history(P4101) each raise
AttributeError: 'NoneType' object has no attribute 'code'. CONFIDENTIAL positive control
returns nine products. The live seed remains unchanged.

Expected behavior: authorized reads safely handle a related row hidden by RLS. Return
visible relationships, omit unavailable optional latest-station information, or apply a
documented neutral denial to the affected projection. One hidden relation must not crash
generic discovery for otherwise visible products. Preserve RLS and hidden identifiers;
ADR-014 makes its authorized subset authoritative.

Root cause: joinedload(ProductEventRecord.station) can materialize station=None under
RLS despite a physically valid non-null FK. Mappers conflate existence with visibility
and access event.station.code unconditionally. Own-row policies/constraints do not
enforce cross-row classification ordering or cascading labels.

Impact: valid per-row classification/reclassification can break lower-clearance product
list/overview/history. The aligned current demo seed is not broken. No disclosure,
RLS bypass, real industrial side effect or global outage was demonstrated.

Safe reproduction: evidence/d_mixed_parent_test.py via run_isolated.py creates a unique
local DB, migrates/seeds, changes only synthetic metadata, uses the real nonprivileged
repository/RLS transaction, then drops only that DB. Initial S01 proof showed history/
overview errors; S05 also exercises the latest-event list mapper. Final and independent
repeat proof tests pass, confirming three failed product reads. Evidence:
d-mixed-parent-initial.log/json, d-mixed-parent.log/xml, d-mixed-parent-repeat.log/xml,
d-mixed-parent.json. Final read-only DB inventory confirms no test DB remains and live
station classifications are unchanged. No model or maintenance write.

Why current tests missed it: fixtures use aligned seed labels, hidden root rows and
authorized subsets. None creates a visible event with a valid but RLS-hidden station FK.
FK and own-row label checks do not establish relationship visibility.

Recommended remediation: load/map only relationships visible in the same RLS transaction;
define safe omission or bounded unavailable fields consistently across list/overview/
history. If classification ordering is intended, explicitly enforce it through migration,
import and reclassification rather than assume it in ORM mapping. Preserve neutral
absence and no hidden identifiers/counts.

Recommended regression tests: real app-role PostgreSQL with visible product/event and
higher-classified station; unrelated visible products still list, affected history/
overview follow the safe documented contract, hidden station IDs never appear, and a
higher-clearance positive control sees the relationship. Include latest/earlier events
and a station-reclassification transition.

Confidence: HIGH

Disposition: NOT_FIXED — discovered after freeze. No existing product/test/config/doc
contract changed during Phase D.

## LOW

None confirmed. Retained Tempo WAL warning is an operational note, not a new confirmed
repository defect without further isolated causality evidence.

## Unconfirmed Risks

- Process-local sessions, local HTTP/no Secure cookie and password-free predefined
  switching are documented demo limitations. Production identity/TLS/multi-worker session
  storage is outside this certification, not a demonstrated demo bypass.
- Crash after claim but before result can leave consumed-without-result; intentionally
  fail-closed/no automatic retry, not transactional exactly-once-under-crash.
- Raw embedding/backend resources merit future lifecycle review when runtime recreation
  is supported; current secure Knowledge composition initializes serially/eagerly. No
  reproduced production-path leak is claimed.
- Trusted local observability surfaces exceed demo-user visibility; Tempo old-WAL metadata
  warning limits historical trace completeness. No volume reset performed.
- Mutable Python ranges/image tags limit future reproducibility; no online CVE audit or
  invented vulnerabilities. No model-quality/hardware certification from fakes.
- Already exported files cannot be recalled; unmeasured browser/network interleavings
  remain residual risks, not speculative findings.
- Complete original Findings1–8/11 wording is unavailable; thematic current evidence
  cannot certify all historical scope.

## Previous remediation status

Current 2026-10-15 evidence only. CLOSED refers to the concrete repaired property.

| Item | Status | Evidence / qualification |
| --- | --- | --- |
| Original Finding 1 | PARTIAL | Session/gateway checks pass; exact original scope unavailable |
| Original Finding 2 | PARTIAL | Server principal/role/clearance matrices pass; original mapping unavailable |
| Original Finding 3 | PARTIAL | FORCE RLS/shared-classification runs/PDF pass; N01 separate related-row availability |
| Original Finding 4 | PARTIAL | Monotonic labels/discovery/egress pass; full wording unavailable |
| Original Finding 5 | PARTIAL | MCP permission/action/target denials pass; exact scope unavailable |
| Original Finding 6 | PARTIAL | Decision/execution generation/replay/actual proposal display pass; wording unavailable |
| Original Finding 7 | PARTIAL | Direct/transitive embedding controls pass; exact scope unavailable |
| Original Finding 8 | PARTIAL | Stale JSON/binary/session/BFCache purge pass; complete wording unavailable |
| Original Finding 9 | CLOSED | Unexpected HTTP/auth/missing credentials cannot yield PASS |
| Original Finding 10 | CLOSED | REQUIRED/negative filename/PDF/missing evidence/resume/aggregation controls pass |
| Original Finding 11 | PARTIAL | Current docs/links/README pass; exact original scope unavailable |
| Original Finding 12 | CLOSED | Optional RCA failure preserves deterministic evidence without invented success |
| C01 | CLOSED | 18 current async evidence/document regressions; fresh boundary inspection |
| C02 | CLOSED | 19 worker capacity/deadline/cancellation/drain cases; RCA ordering inspected |
| C03 | CLOSED | Valid-input spies/MockTransport positive controls reach actual guard |
| C04 | CLOSED | 31 HTTP/HTTPS/userinfo/scheme/proxy/redirect cases |
| C05 | CLOSED | Current ADR-020 index, architecture/budget/import/doc facts pass |
| C06 | CLOSED | 20 unit +9 PostgreSQL generation cases; 44 additional binding probes |
| R01 | CLOSED | 29 Phase-D cases: raw/forged/copied/wrong-model/zone/ceiling denies before credentials/SDK/serialization/transport; positive control |
| R02 | CLOSED | 25 Phase-D unit +2 final PostgreSQL cases; slow create, owned cancellation/capacity, claim-before-write/replay |
| R03 | CLOSED | 18 Phase-D unit +6 final PostgreSQL; actual multi-tab/BFCache stale approve/reject, reused model action ID, identity switch |
| R04 | CLOSED | Sender/receiver network/HTTP/JSON/schema failures, ambiguous logout, late JSON/download/PDF/approval, rapid switch/new tab/BFCache in 50-case browser group |
| R05 | CLOSED | 19 Phase-D cold2/cold8/different-model/failure/close-init/warm-use/worker-drain ownership cases |
| R06 | CLOSED | Current gateway/session prose/Mermaid vs Nginx/API/UI/ADR-013; executed66-fixture registry/automated-switch docs agree |
| Download filename | CLOSED | Server filename/bytes/sanitization and wrong-name negative control |
| Demo Auth/UI redesign | CLOSED | Five identities, header/toolbar/account/language/logout, PUBLIC admin/no restricted admin, cross-tab purge |
| Discovery/visibility | PARTIAL | Five seeded subsets/exactly-one-call pass; N01 breaks mixed-related-classification product reads |
| Prior same-day F01 / S01 | CLOSED | Actual action/target visible despite generic summary; safe HTML/token binding |
| Prior same-day F02 / S02 | CLOSED | Independent200ms probes off-loop; allowed paths, bounded capacity, owned scoped cancellation |
| Prior same-day F03 / S04 | CLOSED | README screenshot historical, current sessions/download assertions, EN/DE |
| S03 | CLOSED | UTF-8 and forbidden-credential control; real FAST secret gate PASS |

## Runtime observations

20/20 healthy, zero restarts. Startup OTel DNS/export retries/Loki ring recover; final
stable window has no unexpected errors. Disposable DB constraints are expected negatives;
optional Grafana directories benign. Retained Tempo WAL metadata warning is a LOW
operational note with uncertain old trace completeness. No observed worker/provider leak
in tested lifecycle scenarios; no persistent data reset.

## Test trust assessment

Green suites and guard controls provide bounded evidence. Proof PASS is distinct from
product success. N01 was found by varying related labels beyond aligned fixtures.
Historical aggregates/unexecuted assertions, platform skip and real-model NOT_RUN never
become PASS. No test weakened or source fixed during review; freeze includes current EN/DE.

## Documentation conformance

Current session/cookie diagrams, Nginx stripping/no injection, Demo Auth gating and role
!= clearance agree with code. Cookie HttpOnly/Strict /api/, process-local TTL and local
HTTP limitations are accurate. Executed registry proves automated switching/R03/R04,
separate from manual real-model journeys. README is corrected; historical Basic-auth ADR
material clearly superseded. Local links/pairs/ADR checks pass. N01 documents a new
implementation gap without silently rewriting the architecture contract.

## Residual risk

N01 remains unfixed by instruction. Seeded demo and R01–R06 verified; future mixed related
labels can fail product reads. No inference-quality, external-provider, hardware or
production certification. Crash-window/local-trust/session/old-telemetry limits explicit.

## Recommended remediation order

1. N01: safe relationship-aware RLS product projections and PostgreSQL mixed-label/
   reclassification regressions across list/overview/history.
2. Separately evaluate unconfirmed lifecycle/reproducibility/production notes when
   concrete requirements justify them; they are not confirmed findings.

Review-phase existing product/test/config/migration/Docker/current-contract changes:0.
Commits/pushes/deployments:0. External model/real protected live effects:0.
