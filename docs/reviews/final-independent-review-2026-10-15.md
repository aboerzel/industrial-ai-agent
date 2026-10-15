# Final Independent Architecture / Security / Quality Review — 2026-10-15

## Executive Summary

**Certification FAIL.** The clean rebuild, complete backend, integration, frontend,
FAST and all 66 registered safe browser fixtures passed. The independent review found
**0 CRITICAL, 0 HIGH, 3 MEDIUM and 1 LOW** confirmed defects. Two required live product
discovery checks failed despite successful API statuses.

N01 is CLOSED by executed independent real-RLS controls. Its approach has not been
applied consistently to other related entities. R01, R02, R03 and R05 withstand the
reviewed bypass/concurrency controls. R04 is PARTIAL because transcript-only PDF Blob
URLs bypass the otherwise effective context invalidation lifecycle.

No findings were fixed. This report reviews the frozen implementation, not a repaired
successor. [Verification](final-verification-2026-10-15.md) records commands/counts;
[summary](final-certification-summary-2026-10-15.md) records the certification decision.

## Verified Baseline

Repository `D:\Freelance\industrial-ai-agent`, branch `main`, HEAD
`c1c434b167bdbd0207e29e287cea1ff0dec98b07`. Initial Git state was clean.
SHA-256 manifests cover all 460 original tracked files. The verified freeze at
16:27:19 Europe/Berlin matched the initial manifest byte-for-byte. The final comparison
also matches. Existing tests, production/frontend source, configuration, scripts, ADRs,
architecture documents and historical reports remain unchanged.

The rebuilt stack contains 20 healthy project services with zero restarts; local Ollama
is separately reachable. The review used new, ignored local evidence under
`evals/results/final-certification-2026-10-15/`. No commits or external deployments.

## Scope

All tracked files were inventoried. Automated static checks covered tracked source
imports, JS syntax, Markdown path references and secret candidates. Fresh targeted
source review covered domain/application ports, orchestration and composition roots,
API/session/authentication, MCP permissions, RLS relationships, protected execution,
approval generations, provider/embedding guards, worker ownership, ticket persistence,
frontend generations/exports, migrations, Docker and observability.

This is a single-reviewer independent pass after the verification freeze. It is not a
claim of exhaustive proof or line-by-line formal verification of every dependency.

## Methodology

Treat green suites as evidence and construct different boundary combinations. After
freeze, new probes exercised independently classified ticket/state/document relations,
raw provider authorization, invalid embedding labels/destinations, mixed discovery
phrases, deterministic reference truncation, and an actual browser transcript-only PDF
across a clearance downgrade. Synthetic database rows were confined to disposable
PostgreSQL; application reads used a nonsuperuser NOBYPASSRLS role. No protected runtime
action or cloud inference was invoked.

Earlier reports supplied historical finding IDs only. New findings below derive from
current code and new measurements. Reproducers are evidence programs, not changes to
the repository test suite. They intentionally record observed defects rather than
repair them.

## Findings Summary

| ID | Severity | Title | Component | Confidence |
| --- | --- | --- | --- | --- |
| FC01 | MEDIUM | Visible maintenance ticket crashes when its related station is RLS-hidden | PostgreSQL ticket projection / Factory MCP | HIGH |
| FC02 | MEDIUM | Related station identifiers escape with an understated projection classification | Machine, ticket and document catalog adapters | HIGH |
| FC03 | MEDIUM | Complete product discovery loses authorized products in the result projection | Agent reference budget / final narrative | HIGH |
| FC04 | LOW | Transcript-only PDF Blob survives an identity downgrade | Frontend transcript PDF lifecycle | HIGH |

## CRITICAL

No confirmed finding.

## HIGH

No confirmed finding. No live cloud disclosure, approval bypass or unauthorized
physical/maintenance execution was demonstrated.

## MEDIUM

### FC01 — Visible maintenance ticket crashes when its related station is RLS-hidden

**Category:** authorization-aware persistence projection / availability.

**Affected files:**
`src/industrial_ai_agent/infrastructure/persistence/postgres.py:337` and `:359`;
`MaintenanceTicketRecord.station` in `infrastructure/persistence/models.py`;
`tools/maintenance_ticket.py`; Factory MCP ticket lookup.

**Observed behavior:** A valid PUBLIC ticket referring to a CONFIDENTIAL station is
visible to PUBLIC/INTERNAL under real RLS, while the joined station is absent. Both
`get_maintenance_ticket` and `get_maintenance_ticket_by_request_id` raise
`AttributeError: 'NoneType' object has no attribute 'code'`. The MCP call returns an
`UnexpectedToolError`; the unknown-ticket control returns normal absence. Higher
clearance succeeds. The application role had no superuser/BYPASSRLS attribute.

**Expected behavior:** An independently visible row must not assume a visible related
station. Apply an explicit safe relationship projection or neutral unavailable result,
preserving RLS and avoiding protected station identifiers.

**Root cause:** Ticket projections dereference `record.station.code` unconditionally.
The non-null physical FK is confused with visibility of the referenced ORM object.
N01 corrected this assumption for product events, not ticket relations.

**Impact:** Read-only ticket requests can fail for valid persisted classifications;
replay/result lookup also has an unsafe relation assumption. No hidden station value
was disclosed by the measured low-clearance error, and no write was attempted.

**Safe reproduction:** `independent-relation-review.py` inserts a synthetic PUBLIC
ticket `MT-S86-20261015` linked to CONFIDENTIAL S86 in the disposable DB, reads it through
the real nonprivileged repository/MCP paths at all clearances, compares unknown lookup,
and removes only its fixture rows. `independent-relation-review.json` preserves results.

**Why current tests missed it:** Ticket fixtures align station/ticket classifications;
N01 regression coverage exercises product-event relationships. A valid FK with a
separately hidden ticket station was not covered.

**Recommended remediation:** Define the ticket relationship visibility contract, treat
the ORM relation as visibility-optional, and enforce the projection within the same
caller RLS transaction. Do not add privileged loads.

**Recommended regression tests:** Real-RLS ticket/request lookups and MCP output at
each clearance; hidden/unknown neutrality, station reclassification, higher-clearance
control, valid physical FK and authorized consumed-generation retry behavior.

**Confidence:** HIGH; direct repository and MCP reproduction.

### FC02 — Related station identifiers escape with an understated projection classification

**Category:** classification propagation / egress defense in depth.

**Affected files:** `infrastructure/persistence/postgres.py:136`, `:139`, `:340`,
`:362`, `:460`, `:463`; machine-status, ticket and catalog DTO projections.

**Observed behavior:** At CONFIDENTIAL/RESTRICTED clearance, a PUBLIC machine-state,
ticket or document row related to CONFIDENTIAL S86 returns `station_id` or
`station_code` S86 while retaining classification `0` (PUBLIC). The ticket MCP output
likewise has `station_id: S86, classification: 0`. The higher station classification
does not participate in the emitted label. A PUBLIC caller cannot load the station;
machine status denies it and the catalog omits its relationship, confirming real RLS.

**Expected behavior:** The projection's label must be at least the maximum authoritative
classification of all emitted related data. Viewing higher-classified data does not
declassify its identifiers. Alternatively omit the relationship from the lower label.

**Root cause:** These adapters copy only `record.classification`; unlike the corrected
product projection, they do not combine the related station's classification.

**Impact:** Downstream consumers receive misleading authoritative labels and can
underestimate sensitivity. The current graph's monotonic trusted request scope remains
an additional defense; this review did not demonstrate an actual cloud disclosure or
lower-clearance station read. The violated adapter contract is independently material.

**Safe reproduction:** The same isolated `independent-relation-review.py` creates
PUBLIC state/ticket/catalog rows with a valid CONFIDENTIAL station FK. No document
content is parsed or transmitted. Compare returned labels and station visibility at
all four clearances. All synthetic rows are cleaned up.

**Why current tests missed it:** Seed classifications are aligned for these relations;
the product-specific monotonic-label tests do not exercise other projection adapters.

**Recommended remediation:** Propagate the maximum of each emitted record/relationship
label at adapter boundaries; retain independent RLS authorization and existing final
egress checks.

**Recommended regression tests:** Cross-classification matrices for state/station,
ticket/station and catalog/station; same-label and higher-clearance positive controls;
no hidden relationship markers; downstream classification/egress boundary assertions.

**Confidence:** HIGH; real database measurements, including wire ticket projection.

### FC03 — Complete product discovery loses authorized products in the result projection

**Category:** user-facing completeness / success semantics / test coverage.

**Affected files:**
`agent/langgraph_troubleshooting_agent.py:2466`, `:2517`, `:2525`, `:3020`;
the bounded final result and API/frontend projection.

**Observed behavior:** On the freshly rebuilt gateway, asking `Welche Produkte kennst
du?` as demo-confidential or demo-restricted returns `status: success` and the generic
answer `The authorized check is complete.` Product references contain only P4101,
P4102, P4711, P4801, P4802 and P4805. The authoritative MCP list contains nine or eleven
products respectively. Missing at CONFIDENTIAL: P4811, P4900, P4901. RESTRICTED also
loses P9001 and P9002. Public/internal/admin product discovery and all five station
discovery checks pass.

**Expected behavior:** A complete inventory request must present the complete authorized
product subset, or explicitly communicate a bounded/partial result. The documented
exact-visibility smoke must not be reported as successful completeness when products
are absent.

**Root cause:** Product discovery interleaves product, latest-station and error-code
references, then truncates the combined list at 12. Later product IDs lose their slots.
When narrative sanitization replaces the model answer with a generic success sentence,
the structured projection provides no complete alternative inventory.

**Impact:** Users cannot discover all permitted demo products; success status obscures
the incomplete answer. No above-clearance inventory was disclosed.

**Safe reproduction:** See `live-demo-smoke-confirmation.json` (8/10 inventory checks
pass; two fail), `live-confidential-products-response.json`, and
`independent-discovery-review.json`. The latter deterministically feeds actual seeded
RLS lists into the production reference extraction/deduplication helpers and reproduces
six product references without invoking any model.

**Why current tests missed it:** Discovery tests validate source visibility, tool
dispatch and subsets on small fixtures. They do not assert complete final nine/eleven
product presentation when secondary references consume the shared budget and the safe
narrative fallback runs. The 66 safe browser fixtures do not cover this current live
product cardinality/fallback combination.

**Recommended remediation:** Preserve primary inventory completeness in a bounded
typed result or clearly expose truncation; keep classification and sequential tool
constraints. Do not solve this by weakening the exact inventory assertion.

**Recommended regression tests:** Deterministic complete inventory through final API
and DOM for all five seed identities, including the generic narrative fallback and
mixed station/fault references; expected primary product sets and explicit partialness.

**Confidence:** HIGH; live and deterministic reproductions agree.

## LOW

### FC04 — Transcript-only PDF Blob survives an identity downgrade

**Category:** frontend context invalidation / resource lifetime.

**Affected files:** `frontend/js/transcript-pdf.js:11`, `:19`;
`frontend/js/api.js:25`; transcript-only export branch in `frontend/js/app.js`.

**Observed behavior:** A synthetic pre-run transport failure creates a transcript-only
PDF under demo-confidential. After switching to demo-public, `/auth/me` confirms PUBLIC,
the transcript DOM is purged and export is disabled. Nevertheless the previously
created Blob URL still returns HTTP 200 and contains the synthetic confidential marker.

**Expected behavior:** Identity invalidation immediately revokes generated document/PDF
URLs, including transcript-only exports, as required by the repository's frontend rule.

**Root cause:** Transcript PDF creation uses its own `URL.createObjectURL` and a
60-second delayed revocation. It never registers with the API module's context-owned
`documentUrls` set, so switch/logout invalidation does not revoke it.

**Impact:** A holder of the already-created same-origin URL retains access for the
remaining timer interval. No stale DOM or newly enabled export remains. Severity is LOW
because normal UI links are removed and reproduction retains the URL through a test
instrumentation hook; it is not evidence of a general cross-user DOM disclosure.

**Safe reproduction:** `independent-transcript-blob-review.mjs` instruments URL creation,
fulfills only the run request with a local synthetic 503, exports the actual shipped
frontend transcript PDF, switches to PUBLIC, and fetches the retained URL. It makes no
model or protected-action call. JSON records successful pre/post-switch marker access,
purged DOM and disabled export. Browser teardown disposes the context.

**Why current tests missed it:** R04 tests cover server-backed PDF/document responses
and generation checks. Transcript PDF tests cover bytes/visible fields, without
combining its separately owned Blob lifetime with identity invalidation.

**Recommended remediation:** Register transcript-only export URLs with the same
context-owned lifecycle, or explicitly revoke them on all invalidation/navigation events.

**Recommended regression tests:** Actual browser retained-URL fetch must fail after
switch, logout, pagehide and BFCache transitions; retain positive export/content checks.

**Confidence:** HIGH; actual browser reproduction on shipped frontend.

## Unconfirmed Risks

No other suspected issue is promoted to a confirmed finding. Specific review limits:
Windows symlink escape control is skipped; full real-model journeys were NOT_RUN;
historical Tempo WAL completeness is unknown. Configuration-only Loki/collector
healthchecks can precede functional readiness, as the initial recovered Loki 503
demonstrated. Certification therefore used independent HTTP/telemetry evidence.

Session storage is deliberately single-process/in-memory demo authentication, with
8-hour TTL and bounded capacity; production OIDC, HA, HTTPS/cookie hardening, retention
and infrastructure rate limits are outside the advertised demo guarantee. Crash after
approval consumption and before ticket persistence remains the documented fail-closed
availability window, not a new authorization bypass.

## Previous remediation status

| Item | Status | Fresh evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 controlled async-I/O regressions and source ownership review |
| C02 | CLOSED | 19 actual SDK/transport deadline/capacity/cancellation/drain cases |
| C03 | CLOSED | Actual destination guard spies and authorized MockTransport controls; valid request construction |
| C04 | CLOSED | 31 transport cases; HTTP denied before credentials; HTTPS alone never authorizes |
| C05 | CLOSED | 20-ADR index/contracts, supersession and architecture/documentation checks |
| C06 | CLOSED | 20 unit + 9 PostgreSQL; generation identity, replay, concurrency and legacy fail-closed |
| R01 | CLOSED | 29 dedicated regressions plus new raw/copy/model/zone/ceiling controls, zero denied-call boundary counters |
| R02 | CLOSED | 25 unit + 2 PostgreSQL slow persistence cases; claimed action precedes owned worker; no unsafe retry |
| R03 | CLOSED | 18 unit + 6 PostgreSQL and browser stale approve/reject, generations, restart and BFCache controls |
| R04 | PARTIAL | Original cross-tab/late-response regressions pass; FC04 uncovers a separate unrevoked transcript Blob |
| R05 | CLOSED | 19 cold2/cold8, cleanup, close-race, warm-overlap and RCA drain-before-close cases |
| R06 | CLOSED | Current docs vs Nginx/session/UI source; executed fixture registry is 66 |
| N01 | CLOSED | 21 real-RLS regression tests plus 120 independent assertions/24 projection cases; no hidden relation leakage or AttributeError |
| Document download filename | CLOSED | Browser actual filename/bytes assertions and deliberately wrong-name negative control executed |
| Demo Auth/UI | PARTIAL | Five live identities, roles/clearances/configuration/context purge and browser layout pass; FC04 violates complete Blob revocation |
| Discovery/visibility | PARTIAL | Exact MCP/RLS and five station subsets pass; FC03 fails live final product completeness |
| Earlier same-day F01/S01 action display | CLOSED | Registered real-browser action/target rendering despite generic summary; request generation binding |
| Earlier same-day F02/S02 async preparation | CLOSED | Full async capability/worker regressions and preparation boundary inspection |
| Earlier same-day F03/S04 obsolete docs | CLOSED | Current screenshot marked historical; current session/download/fixture docs inspected |
| S03 credential gate | CLOSED | Actual FAST credential gate; UTF-8 and forbidden-literal deterministic controls; supplementary tracked scan |

These statuses are scoped to the described defects. FC01/FC02 identify additional
relationship contracts; they do not erase N01's verified product fix. R04's original
HIGH scenario did not recur; PARTIAL describes the broader lifecycle requirement.

## Runtime observations

All 20 services remain healthy, zero restarts. Sanitized logs were collected for every
project service. Final reviewed keyword classifications: 67 EXPECTED_STARTUP_WARNING,
1,536 BENIGN_WARNING, 5 EXPECTED_NEGATIVE_TEST. No unexpected persistent application
error was found. OTel DNS/deadline startup failures recovered; current collector scrape,
LLM/MCP metrics and trace search succeed. Loki's initial 503 recovered without changes.
Grafana optional plugin/provisioning/usage-stat diagnostics are benign for the configured
local datasource paths. Tempo current tracing works; the recovered orphan WAL warning
limits historical telemetry completeness claims.

No cloud inference or real protected side effect occurred. Persistent ticket count
stayed 100. All synthetic review/test databases and their isolated container were
removed; project volumes and unrelated Ollama were preserved.

## Test trust

The full backend gate passed 1,798 with one explicit Windows skip; FAST passed 1,631
unit and 276 frontend tests. INTEGRATION passed all 152 without skips. All 66 registered
safe browser fixtures executed with zero failures/flakes/skips. Golden scorer tests
exercise scoring logic; they do not constitute real-model behavior measurements.

Guard tests use valid schemas and positive controls, including real SDK MockTransport.
R05 covers two/eight concurrent cold callers and the close/initialization race. Approval
tests combine repeated model action IDs with distinct authoritative execution UUIDs.
Browser fixtures exercise actual session code but mostly synthetic application data;
the missing mixed relations and full live product cardinality explain the new gaps.

The first new live-smoke harness had two implementation mistakes. Its artifacts remain
preserved and are distinguished from product failures. The separately corrected harness
passed identity/station checks but still failed two product checks. No product fixture
or existing assertion was changed to obtain a green result. New independent probes
record the observed defects even when the evidence program itself exits successfully.

## Documentation conformance

Current README, architecture overview, ADR-013, demo authentication and browser fixture
documentation match the implemented session/role model. Admin is PUBLIC + MODEL_ADMIN;
restricted has no admin role. Current Basic Auth mentions are negated or historical.
The actual fixture registry is 66 and agrees with the documented registered files.

Technical EN/DE companions exist with matching diagram counts; missing companions are
synthetic corpus inputs. No local Markdown path candidates remained unresolved. The
visibility matrix is authoritative and accurately exposes FC03's implementation defect;
it was not altered to accommodate the failure. Existing architecture diagrams were not
changed, as this read-only run changes no architecture or behavior.

## Residual risks

The green suites do not certify real-model semantic correctness, complete PDF layout,
production identity/TLS/HA, arbitrary malicious in-process Python reflection, historical
WAL retention, or the skipped Windows symlink case. No packet capture or external
dependency vulnerability service was used. Dependency/model asset downloads occurred;
repository inputs were not deliberately sent to external services.

## Recommended remediation order

1. FC02: preserve classification on every emitted related identifier.
2. FC01: define and implement visibility-safe ticket relation projection.
3. FC03: preserve complete authorized primary inventories through final API/DOM output.
4. FC04: unify transcript PDF URL ownership with context invalidation.

Add the recommended deterministic regressions at the affected boundary, then repeat
certification against a new baseline. **No remediation was performed in this run.**
