# Final Stabilization / Verification / Review Summary

Date: 2026-10-15. New post-remediation run: run-02.

## Stabilization

Iterations: 2 complete cycles, plus a separate final clean Phase C.
Defects found: 4 (3 MEDIUM, 1 LOW). Defects fixed: 4, one attempt per root cause.
Unresolved after three attempts: 0.

- S01: approval UI now displays authoritative action/target/details as text; exact
  approval_execution_id decisions remain unchanged.
- S02: configuration persistence and async Observability handlers use existing bounded
  AnyIO worker dispatch after authorization; complete synchronous operation stays off-loop.
- S03: required secret scanner decodes Git output as strict UTF-8 on Windows.
- S04: README labels the old screenshot historical and describes current session/download behavior.

First failure proofs, repairs and regressions:
[Repair log](stabilization-repair-log-2026-10-15.md).

## Final Verification

[Protocol](full-verification-2026-10-15.md).

| Gate | Final measured result |
| --- | --- |
| Docker | PASS, seven project images rebuilt with no cache |
| Stack | 20/20 running, healthy and ready; zero restarts; left running |
| Backend | 1777 passed, 0 failed, 1 Windows symlink-capability skip |
| Integration | 131 passed, 0 skipped, separate disposable PostgreSQL |
| Frontend | 276 passed |
| Browser | 66 registered safe Chromium fixtures passed |
| FAST | PASS, unit 1631 passed/1 skip plus frontend/Ruff/format/secrets |
| RLS/Auth | 189 overlapping backend cases passed plus live identities/subsets |
| MCP/HITL | 154 MCP and 168 HITL overlapping cases passed |
| Model/embedding egress | 428 overlapping routing/transport/egress cases passed |
| Quality | Ruff/format, JS, docs/links/EN-DE, secret scans, offline wheel/pip/Compose/diff PASS |
| Real-model E2E | NOT_RUN; local model readiness is not inference certification |

Counts overlap; do not add subgroup counts. All test databases removed; all twelve
project volumes preserved. No real protected live writes or hardware actions.

## R01–R06

| Finding | Status |
| --- | --- |
| R01 | CLOSED |
| R02 | CLOSED |
| R03 | CLOSED |
| R04 | CLOSED |
| R05 | CLOSED |
| R06 | CLOSED |

Independent Phase-D falsification: 478 focused tests, 50 real-session Chromium cases,
44 additional classification/action-binding probes, new slow-I/O and proposal-display
controls. Closed applies to the concrete repaired properties, not all possible defects.

## Demo Auth

All five principals verified. Fresh default PUBLIC; demo-admin has PUBLIC + MODEL_ADMIN;
demo-restricted has RESTRICTED without MODEL_ADMIN. Header/toolbar/account, language,
quick switch, logout/reselect, context purge, failed cross-tab refresh and BFCache pass.

## Demo Visibility

Station/product SQL seed, read-only live MCP and all-five real API/graph/PostgreSQL
questions with fake final model match the canonical matrix. Exact station question uses
one intended list call. Admin remains PUBLIC; unknown/mixed sensitive inputs never
downgrade. General mixed related-row robustness is separately limited by N01 below.

## Independent Review

[Full review](full-review-2026-10-15.md).

CRITICAL: 0

HIGH: 0

MEDIUM: 1

LOW: 0

## Highest-priority findings

1. N01 MEDIUM: an RLS-hidden station becomes None in otherwise visible product/event
   projections. Product list, overview and history raise AttributeError after valid
   related-station reclassification. Twice reproduced with real isolated PostgreSQL;
   higher-clearance positive control succeeds. Current live seed remains unchanged.
   NOT_FIXED because discovered after Phase-D freeze.

No other confirmed finding. Tempo retained-WAL warning, process-local/local-HTTP demo
limits, consumed/no-result crash window and mutable dependency tags/ranges remain explicit
operational or unconfirmed risks. Exact original Findings1–8/11 scope is unavailable;
those historical closures are qualified PARTIAL rather than invented.

## Review freeze

Existing product/test/config/migration/Docker/current-contract changes after Phase D: 0.
507 frozen hashes compared, including local German contracts. Review findings modified: 0.
Only new dated reports and non-invasive evidence were written during review.
Historical 2026-10-14 reports modified: NO, eight EN/DE files byte-identical.
Initial same-day reports/index work archived; no user work discarded.

External model calls: 0. Repository data sent to external AI services: 0.
Real protected live/hardware effects: 0. Commits/pushes/deployments: 0.

## Overall

PASS_WITH_FINDINGS. Phase-C verification PASS; independent review leaves N01 MEDIUM
unfixed. Healthy final Docker stack remains running.
