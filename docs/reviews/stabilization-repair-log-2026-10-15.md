# Stabilization Repair Log — 2026-10-15

## Run provenance

This is the new post-remediation run (`run-02`). Reports present at entry were archived
under `evals/results/stabilization-2026-10-15/run-02/prior-reports/`. Their staged
contents and the original working-tree manifest are preserved as evidence. No historical
2026-10-14 report has been edited. Branch main; HEAD 5f977d8a6203936599a183d6e64e08247d0d88f3.

## Iteration 1

Baseline: 20/20 services ready, clean seven-image build; backend 1764 passed/1 skipped,
integration 131 passed, browser 65 passed, frontend 273 passed. FAST unit tests passed;
its secret scanner failed. First evidence: `run-02/a-*.log`, `b-red.xml`, `b-ui-red.log`.

### S01

Severity: MEDIUM. Category: SECURITY_DEFECT. Previous independent finding F01.
Evidence: a real public API proposal targeted S02 while the human request named S04;
the shipped card displayed only neutral model summary, omitting actual action/target.
Root cause: renderApproval ignored bounded authoritative action/arguments fields.
Contract: public approval DTO and current browser frontend documentation require action,
arguments, run and status; human decisions remain generation-bound under R03.
Attempt 1: render allowlisted action/target/details with textContent; no raw payload or
hidden arguments. Preserve exact generation-bound decision closure.
Regression: ticket and calibration DOM tests, literal HTML safety, real API/Chromium
synthetic proposal test. Result: focused unit and browser tests PASS; full cycles pending.

### S02

Severity: MEDIUM. Category: PRODUCT_DEFECT. Previous independent finding F02.
Evidence: 200 ms synchronous fake operations delayed a 20 ms heartbeat to 206.11 ms
(configuration) and 201.34 ms (Observability MCP). Safe health completed at 207.51 ms.
Root cause: async handlers invoked synchronous persistence/backend methods inline.
Contract: async service responsiveness, ADR-003 adapter boundary, existing AnyIO bridge.
Attempt 1: FastAPI synchronous endpoints own complete assignment operations in its
bounded AnyIO pool; four async MCP handlers authorize first, then run complete telemetry
operations through anyio.to_thread.run_sync. No executor, timeout, retry or provider
lifecycle changes. Database session creation remains inside each worker operation.
Regression: 3 configuration paths, 4 MCP paths, unauthorized zero-I/O, six requests with
two-token worker capacity, cancellation waits for actual write completion. Cancellation
can suppress the HTTP response after completion; it does not retry the write.
Result: initial focused tests PASS; full cycles pending. Post-fix fake heartbeats 13.4 ms
and 37.46 ms, with both operations confirmed off the event-loop thread.

### S03

Severity: MEDIUM. Category: HARNESS_DEFECT.
Evidence: authoritative FAST secret scan failed decoding staged UTF-8 smart quotes using
Windows CP1252, then raised AttributeError on missing subprocess output (`a-fast.log`).
Root cause: subprocess text decoding inherited the host locale.
Contract: canonical UTF-8 repository text and a functioning fail-closed secret gate.
Attempt 1: explicitly decode both Git outputs as UTF-8; keep strict decoding and all
credential rules. Regression proves Unicode diff decoding and forbidden credential
literal detection, including untracked-file enumeration. Result: focused tests and real
incremental secret scan PASS; complete cycles pending.

### S04

Severity: LOW. Category: DOCUMENTATION. Previous independent finding F03.
Evidence: README described a current browser working-clearance selector and a fixed
download limitation. Attempt 1: label screenshot historical; describe current server
sessions and download assertions. Update local German copy. Regression: cheap current
README semantic check. Result: focused checks PASS; complete cycles pending.

## Repair accounting

Repair-loop MEDIUM defects: 3. Additional LOW correction: 1. Attempts: one per root
cause. Corrected command-path typo and a cancellation test's mistaken HTTP-response
expectation were harness development corrections, not additional product repair attempts.

## Unresolved after 3 attempts

None.

## Iteration 2

Complete cycle restarted from baseline manifest and Compose stop, retaining all twelve
project volumes. Seven no-cache builds PASS; 20/20 services ready, zero restarts.
FAST: 1631 passed / 1 platform skip; frontend 276 passed; full backend 1777 passed /
1 platform skip; separate integration 131 passed; browser 66 passed. Wheel, dependency,
Compose, Ruff/format, JS syntax, secret and documentation/link checks PASS.
S01, S02, S03 and S04: resolved by attempt 1. No new repairable blocker.
Read-only live smoke: 43 API/MCP/auth/visibility checks and 21 shipped-UI checks PASS.

## Phase C

A distinct final clean cycle is now running without source changes. Its measured result
will be recorded in full-verification-2026-10-15.md. No unresolved-after-three blocker.

Phase C result: PASS. Full clean rebuild, 20/20 ready/zero restarts, 1777 backend PASS /
1 platform skip, 131 integration, 276 frontend, 66 browser, FAST and quality PASS.
No source changes in final cycle. No new repairable blocker. Baseline ready for freeze.
