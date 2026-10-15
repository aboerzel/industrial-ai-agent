# Final Certification Summary — 2026-10-15

## Verification

Baseline: `main`, `c1c434b167bdbd0207e29e287cea1ff0dec98b07`; 460 original tracked
file hashes unchanged before verification, at freeze and after review.

Docker: PASS — complete scoped stop and seven no-cache application rebuilds; volumes preserved.

Stack: 20/20 healthy; all restart counts 0; independent readiness checks confirmed recovery of initial Loki/OTel startup conditions. Stack left running.

Backend: 1,798 passed, 0 failed, 1 Windows symlink skip; includes unit, integration and 15 golden-scorer tests.

Integration: 152 passed, 0 failed, 0 skipped; disposable real PostgreSQL/RLS, fully cleaned up.

Frontend: 276 passed, 0 failed, 0 skipped.

Browser: 66 registered safe fixtures; 66 passed, 0 failed/skipped/flaky. Separate live discovery: 8/10 passed; CONFIDENTIAL and RESTRICTED product completeness failed.

FAST: PASS — 1,631 unit passed, 1 skipped; frontend/Ruff/format/credential gates passed.

Quality: PASS for configured checks; Ruff, 248 format checks, 40 JS syntax files, documentation conformance, technical EN/DE companions/diagram counts, local path links, ADR references, secret checks, wheel, Compose, diff check. JS lint/static typecheck NOT_CONFIGURED.

Real-model E2E: NOT_RUN. Separate requested live read-only inventory smoke used the verified LOCAL assignment; external model calls 0, real protected side effects 0. Ticket count remained 100.

## Security regression status

| Item | Status | Evidence |
| --- | --- | --- |
| C01 | CLOSED | 18 async-I/O cases |
| C02 | CLOSED | 19 capacity/deadline/drain cases |
| C03 | CLOSED | Actual guard spies and positive transport controls |
| C04 | CLOSED | 31 transport-security cases |
| C05 | CLOSED | Current ADR/documentation conformance |
| C06 | CLOSED | 20 unit + 9 PostgreSQL generation cases |
| R01 | CLOSED | 29 dedicated cases plus independent zero-boundary-counter controls |
| R02 | CLOSED | 25 unit + 2 PostgreSQL owned ticket-I/O cases |
| R03 | CLOSED | 18 unit + 6 PostgreSQL and real-browser generation conflicts |
| R04 | PARTIAL | Original scenarios pass; FC04 transcript-only Blob remains readable |
| R05 | CLOSED | 19 ownership/race/drain cases |
| R06 | CLOSED | Current sessions/UI/docs and actual 66-fixture registry agree |
| N01 | CLOSED | 21 real-RLS tests + independent 120 assertions, 24 projections |

Document filename: CLOSED. Demo Auth/UI: PARTIAL because of FC04; five identities,
clearances, roles, configuration and purge behavior otherwise verified. Discovery/
visibility: PARTIAL because of FC03; exact source visibility and all station subsets pass.

## Independent review findings

CRITICAL: 0

HIGH: 0

MEDIUM: 3

LOW: 1

| ID | Severity | Finding |
| --- | --- | --- |
| FC01 | MEDIUM | RLS-hidden station crashes visible ticket projections |
| FC02 | MEDIUM | Related station identifiers retain an understated projection label |
| FC03 | MEDIUM | Complete product discovery drops authorized products under the reference budget |
| FC04 | LOW | Transcript-only PDF Blob remains readable after identity downgrade |

No finding was fixed. No unexpected persistent application runtime error was observed;
startup and optional third-party diagnostics are classified in retained evidence.

## Historical report preservation

2026-10-14: UNCHANGED

earlier 2026-10-15 reports: UNCHANGED

Existing product/test/configuration/script/contract changes: 0.

Commits: 0. Pushes: 0. External deployments: 0. Persistent volumes deleted: 0.

Only new certification reports, ignored German translations and local evidence artifacts
were written. The disposable PostgreSQL container/databases were removed.

## Certification result

**FAIL**

The mandatory live exact-product-subset checks failed for two identities. Green
registered suites do not supersede this observed failure or the new review findings.

See [final verification](final-verification-2026-10-15.md) and
[independent review](final-independent-review-2026-10-15.md) for evidence, limits and
recommended remediation. The healthy local stack remains running.
