# Local Runtime GPU Exclusivity — 2026-10-18

Result: **PASS**. Ready to commit: **YES**. Nothing committed or pushed.

This focused harness hardening preserves the accepted release-gate separation. No
production application, timeout, model, assignment, Ollama or Docker configuration
changed. The existing working tree already contained the accepted gate implementation
and earlier reports; those changes are not new findings.

## Execution order and observed serialization

`run_release_gate.main()` calls SOFTWARE synchronously before LOCAL_RUNTIME. SOFTWARE
awaits backend/integration, FAST, frontend and KDEP including offline restart and teardown.
It then awaits deterministic Agent journeys, legacy, safe browser and references. The
software fixture context terminates and waits for its four API/MCP processes and removes
its disposable database before returning. KDEP's owned containers/network are likewise
removed before its gate returns. These paths use deterministic transports, not local chat.
There is no test-owned real chat process left behind by SOFTWARE.

The accepted FULL run `release-20261018-130803-f8ba2d33` provides actual timing evidence:

| Completed software evidence | Last write, UTC |
|---|---|
| KDEP offline restart | 13:26:02.870776 |
| Deterministic Agent | 13:26:15.276449 |
| Legacy browser | 13:27:06.174573 |
| Safe browser | 13:29:29.518427 |
| Final software gate result | 13:29:30.003503 |
| First real provider request | **13:29:31.893898** |

An interval sweep over **97 actual Agent `llm.call` spans plus 3 preflight requests**
finds maximum concurrent chat calls **1**. A separate sweep of **100 deduplicated native
Ollama HTTP intervals** also finds **1**. Minimum provider interval gap: 1.660 ms. This
proves sequential preflight, journeys and their reference/inventory follow-ups in that
run, independently of worker configuration. No fresh real-model qualification or rebuild
was needed for this review. Standalone live reference qualification now shares the same
reservation, as does the five-journey legacy gate.

## Cross-process reservation

Before this change there was no machine-wide qualification lock. Python release entry
points, direct/manual Node journeys, legacy Playwright and live reference fixtures now
share an OS-exclusive loopback TCP reservation on port `46233`, across repository
checkouts. Only LOCAL_RUNTIME acquires it, before inference preflight, and retains it
through qualification/evidence completion. A random inherited controller lease allows
exactly one active worker connection; parallel children cannot share the GPU slot.

Contention returns **LOCAL_RUNTIME_BUSY** before model work, with preflight NOT_TESTED
and runtime NOT_TESTED/unqualified. Release/manual commands exit **5**; native Playwright
reports explicit LOCAL_RUNTIME_BUSY as a failing setup, exit **1**. SOFTWARE stays
independent. This is neither provider-unhealthy skip nor PASS. Real-model Playwright
enforces **workers=1, retries=0**, rejecting CLI overrides before execution. Direct Node
journeys retain their awaited sequential loop; no retry was added.

Normal success/failure releases ownership when work ends. Controller loss cannot free
an active inherited worker. Abrupt worker termination or exceptional worker exit retains
a bounded **90 s** residual drain, matching the existing Agent deadline, then releases.
The broker handles console cancellation without immediately dropping active ownership.
OS lifetime and controller EOF eliminate stale PID-file deletion races; no persistent
lock file exists. Tests shorten only their isolated broker's drain to exercise cleanup.

Read-only legacy configuration preflight, aggregation, comparison and fully completed
resume evaluation need no GPU reservation. SOFTWARE's test-only API attests its scripted
provider through a loopback endpoint and per-run token; a mode environment flag alone
does not bypass the guard. CPU KDEP and synthetic browser fixtures stay outside the lock.
Lock regressions use isolated ports, including subprocess CLI checks, so the deterministic
test suite itself does not need the production reservation to be available.

The reservation coordinates repository qualification entry points. Ordinary user chat,
unrelated workstation GPU consumers, direct ad hoc Ollama clients and forced termination
of the reservation broker are outside this cooperating harness boundary.

## Verification

| Check | Result |
|---|---|
| Python lock and existing release-gate tests | **69 passed**, 0 failed/skipped |
| Focused Node lock tests | **11 passed**, 0 failed/skipped |
| Full frontend suite with production reservation already held | **350 passed**, 0 failed/skipped |
| Python harness suite with production reservation already held | **69 passed**, 0 failed/skipped |
| Actual deterministic Agent/browser control with reservation held | **PASS**, healthy-station-en |
| Actual deterministic legacy gate with reservation held | **5/5 PASS**, one worker, zero retries |
| Actual deterministic reference browser gate with reservation held | **35/35 PASS**, original 16 and extended 30 action matrix |
| Ruff / formatting / incremental secret scan / git diff --check | **PASS** |

Coverage includes first acquisition, second-process rejection, Python/Node shared worker
exclusion, PASS/FAIL/exception cleanup, KeyboardInterrupt, actual worker-process termination,
controller death with and without active work, stale lease rejection, SOFTWARE independence,
FULL ordering, explicit busy report/exit, and worker/retry override rejection. Initial
development failures exposed an overly broad guard around read-only preflight and a
missing unit-fixture import; both were corrected and first logs retained.

Evidence: `D:/Freelance/local-runtime-gpu-exclusivity-20261018/`:
`accepted-concurrency-proof.json`, `focused-complete.xml`, `focused-confirmed-under-lock.xml`,
`lock-final.log`, `frontend-confirmed.log`, `software-under-lock/`, `integrity.json`.
Original trace/HTTP intervals remain under
`D:/Freelance/release-gate-separation-20261018-1010/full-final/local-runtime/`.

## Integrity and scope

Compared with the accepted release manifest, **174 production files** are unchanged,
including application source, assignments, timeouts, environment and deployment config.
Earlier reports and the release-gate-separation implementation report remain unchanged.
Current stack: **20/20 healthy**, API `/ready` **200**, owned test containers remaining **0**.
This task made no real model calls or protected production writes. Synthetic writes used
only disposable test PostgreSQL. No production remediation or additional broad review.

Changed harness files: `scripts/local_runtime_lock.py`, `release_runtime.py`,
`release_contract.py`, `run_release_gate.py`, `release_support.py`;
`frontend/scripts/local-runtime-lock.mjs`, `runtime-global-setup.mjs`,
`run-e2e-journey.mjs`, `run-manual-e2e.mjs`; both Playwright configurations;
`tests/e2e/software-server.py`, `tests/unit/test_local_runtime_lock.py`,
`tests/frontend/local-runtime-lock.test.mjs`, `tests/frontend/e2e-http-security.test.mjs`,
`tests/frontend/fixtures/runtime-port-isolation.mjs`; quality-gate documentation and this
new report with ignored German counterparts. Architecture and product contracts are
unchanged.
