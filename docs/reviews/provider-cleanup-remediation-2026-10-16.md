# Provider Cleanup Remediation — 2026-10-16

## Result

**Finding fixed: YES. Severity: MEDIUM. Ready to commit: YES.** No commit or push was performed.

Finding: **Provider cleanup blocks event loop during run cancellation**.
The authoritative review names M02 **“Provider cleanup blocks the event loop when a run is cancelled”**:
[original finding](final-comprehensive-verification-and-review-2026-10-16-run-120936.md#m02--provider-cleanup-blocks-the-event-loop-when-a-run-is-cancelled).
This remediation addresses that deterministic concurrency defect only. It does not certify or change the separate provider-quality finding M01 or browser-harness finding L01.

Baseline: `main`, HEAD `0e55a379fc6b710d4dfdb78d3e1174ee39c32718`, Python 3.12.10 from the configured project virtual environment. The existing untracked final-review report was preserved. Initial tracked-file hashes and review hash were retained outside the repository.

## Reproduction and Measurements

The retained review proof was copied to the new external evidence directory and executed **before changing source**. It exercises the actual RunService, production factory, LangGraph, authorization wrappers and OpenAI SDK. Only resolution, empty MCP tools and HTTP MockTransport are synthetic. No network model call is made.

| Measurement | Non-cancelled control | 350 ms residual request | 750 ms residual request |
| --- | ---: | ---: | ---: |
| Original proof before source edits: maximum heartbeat gap | 16 ms | 360 ms | 750 ms |
| Comparable instrumented frozen-HEAD service: maximum gap, 22 ms pulse | 32 ms | 359 ms | 750 ms |
| Instrumented fixed service: maximum gap, 22 ms pulse | 32 ms | 32 ms | 32 ms |
| Independent API request dispatched during baseline drain: queue + response | below clock resolution | 297 ms | 687 ms |
| Same independent request during fixed drain | below clock resolution | below clock resolution | below clock resolution |
| Final permanent regression: maximum gap | separate control above | 32 ms | 32 ms |
| Final permanent regression: cancellation to cleanup completion | — | 375 ms | 750 ms |

The original review measured approximately 31 / 375 / 765 ms; the fresh measurements reproduce the same delay-scaled failure. Windows `time.monotonic()` has approximately 16 ms resolution here: a recorded zero is not zero physical latency. Permanent tests pulse every 22 ms and enforce **150 ms maximum**, comfortably below either original stall. Health requests are also checked while close has started and the provider remains active.

The enhanced comparison loads an external, immutable copy of the original service from HEAD; it does not revert repository source. Both normal controls produce the same normalized result, `The authorized check is complete.`, with three SDK requests reusing one client. Cancelled controls make one request, with no retry. All scenarios end with active-call count zero and exactly one adapter/SDK/HTTPX closure. Event traces retain cancellation/control timestamps, request completion, active-count decrement, close start/completion and thread IDs. Baseline close executes on the loop thread; fixed close executes on an AnyIO worker.

Evidence directory: `D:\Freelance\provider-cleanup-evidence-2026-10-16`.
Key artifacts: `pre-fix-proof.py`, `pre-fix.json`, `baseline-service.py`, `instrumented-proof.py`, `baseline-instrumented.json`, `post-instrumented.json`, `post-350.json`, `post-750.json`, test XML and command logs.

## Ownership, Root Cause and Change

Before the fix:

1. Async `TroubleshootingRunService.run_with_policy`, `start` or `resume` enters the synchronous production `open_agent` context on the loop thread.
2. The factory owns a per-context `OpenAICompatibleLLMClient`. Its per-model SDK and HTTPX clients initialize lazily under R05's `Condition(Lock())`; requests increment the active count under that lock.
3. LangGraph runs the synchronous model node in its existing executor. Cancelling the awaiting graph cannot terminate an already-running synchronous SDK request.
4. Synchronous context exit invokes `adapter.__exit__ → close()` on the event-loop thread. **Exact blocking call: `self._lifecycle.wait_for(lambda: self._active_requests == 0)` in `OpenAICompatibleLLMClient.close()`.**
5. The SDK worker decrements the count in `_client_for_request`'s `finally` and notifies the condition. Only then can close finish. The ownership synchronization is correct; its async caller integration was wrong.

The service now wraps the existing synchronous factory port in `_owned_agent_context`. An `ExitStack` acquires ownership inside a worker, so cancellation during acquisition still leaves the completed acquisition owned and subsequently closed. Context acquisition and exit use `anyio.to_thread.run_sync(..., abandon_on_cancel=False)` with the **existing shared bounded default limiter**, following R02's owned ticket-I/O pattern. The helper observes the worker task to completion, shields AnyIO cancellation scopes and tolerates repeated native `Task.cancel()` before propagating cancellation. Cleanup waiting for capacity remains mandatory. It is neither detached nor fire-and-forget.

R05 is unchanged: final close stops new admissions, drains active calls, closes each SDK and its owned HTTPX transport, clears caches, marks closed and notifies waiters. Active calls decrement exactly once in their existing `finally`. SDK construction failure still closes its transport. Concurrent cold initialization, no duplicate publication, idempotent/final close and no publish-after-close retain their original synchronization. Shutdown ownership is per agent context; there is no newly introduced application-wide provider singleton. Cancellation from an async lifecycle uses the same owned boundary; start/resume release their checkpointer only after provider drain.

No provider-call execution handoff, executor, dependency, routing rule, egress authorization, credential guard, timeout, retry, model assignment, Ollama setting, frontend or harness was changed. The small lifecycle bridge preserves the existing inward factory port; no new architecture decision or Mermaid responsibility/flow change is required. The architecture overview and its ignored German counterpart describe the lifecycle correction.

## Permanent Regression Matrix

Tests: [test_provider_cleanup_async.py](../../tests/unit/test_provider_cleanup_async.py), **14 passed**. PCLEAN-01/02 remain the preserved pre-edit acceptance evidence; permanent regressions exercise the corrected implementation.

| Case | Evidence | Result |
| --- | --- | --- |
| PCLEAN-01 | Original retained proof, 350 ms residual, before edits | Reproduced |
| PCLEAN-02 | Original retained proof, 750 ms residual, before edits | Reproduced |
| PCLEAN-03 | Production graph/real SDK/MockTransport, 350 ms, heartbeat and thread checks | PASS |
| PCLEAN-04 | Same, 750 ms | PASS |
| PCLEAN-05 | Actual FastAPI `/health` during active provider drain; timer-dispatched comparison includes queue delay | PASS |
| PCLEAN-06 | Normal production graph: same result and one reused SDK/HTTPX pair | PASS |
| PCLEAN-07 | Direct timeout and actual API timeout: sanitized terminal failure, no late result overwrite | PASS |
| PCLEAN-08 | Provider exception plus construction failure: resources closed and failure propagated | PASS |
| PCLEAN-09 | Repeated native cancellations and AnyIO scope cancellation: owned completion, single close, no orphan task | PASS |
| PCLEAN-10 | Two simultaneous actual adapter calls for run/start/resume: drain both, deny new admission, no premature close | PASS |
| PCLEAN-11 | Final/idempotent close, no publication after close; cancelled acquisition remains owned; R05 neighbors | PASS |
| PCLEAN-12 | Eight cancelled contexts with shared capacity reduced to two: only two drains admitted, loop responsive, all clients closed and tokens returned | PASS |

## Gates and Safety

| Gate | Result |
| --- | --- |
| Full backend, `python -m pytest tests -q -ra` | **2,058 passed, 0 failed, 6 skipped** |
| Repository INTEGRATION gate | **279 passed, 0 failed, 5 skipped** |
| Repository FAST gate | **PASS:** 1,764 unit passed, 1 skipped; 328 frontend passed; Ruff, format, secret scan passed |
| Focused lifecycle/security/API neighbors | **310 passed**, including 14 PCLEAN cases; final strengthened instrumentation/checkpointer assertions separately rerun: **14 passed** |
| C01 / C02 / R01 / R02 / R05 unit neighbors | **18 / 19 / 29 / 25 / 19 passed** |
| R02 actual PostgreSQL ownership/replay cases | **2 passed**, in backend and INTEGRATION |
| Focused safe browser sanity | **2 passed, no retry**: session bootstrap and authoritative account menu |
| Offline wheel build, external source copy, no dependency resolution | **PASS** |
| Dependency consistency, `pip check` | **PASS** |
| Ruff / format / secret scan / `git diff --check` | **PASS** |

Five skips are KDEP tests requiring an explicitly selected clean image and isolated offline model/container deployment; those are outside this fix and must not call real model infrastructure. The sixth backend skip is unavailable Windows symlink creation. Existing deprecation and JUnit `record_property` warnings are not failures.

The first broad run used a disposable database whose name lacked the fixture-required `verification_` prefix: **1,915 passed, 60 failed, 89 skipped**. Failures explicitly rejected that verifier setup; fixtures skipped unsafe-to-assume database names. The complete backend and INTEGRATION gates were then run against correctly prefixed, separately seeded disposable databases. The failed setup log/XML remain preserved, not relabeled PASS. Initial PCLEAN fixture failures (missing reasoning capability, counting denied admissions, overly literal normalized result) and their diagnostic logs also remain preserved.

PostgreSQL used loopback port 55433 in a uniquely named disposable container, with tmpfs data and no persistent volume. Application proofs use `factory_app`, verified `rolsuper=false`, `rolbypassrls=false`; admin credentials are confined to synthetic setup/migrations. All disposable databases are removed with that container after verification. Persistent demo data and the running project stack remain unchanged.

## Final Protocol

| Required field | Value |
| --- | --- |
| Original finding reproduced | YES |
| Uses bounded existing worker infrastructure | YES |
| New executor introduced | NO |
| Fire-and-forget cleanup introduced | NO |
| Independent async request during cleanup | PASS |
| Normal provider call / timeout cancellation / exception cleanup | PASS / PASS / PASS |
| Multiple active calls / duplicate cleanup / worker capacity | PASS / PASS / PASS |
| R05 / C02 / R01 / R02 / C01 | PASS / PASS / PASS / PASS / PASS |
| External model calls | 0 |
| Real protected side effects | 0 |
| Historical review reports modified | NO |
| Unexpected repository changes | NONE |
| Finding fixed / Ready to commit | YES / YES |
| Commits / pushes / deployments | 0 / 0 / 0 |

Changed files: `src/industrial_ai_agent/agent/troubleshooting_run_service.py`, new `tests/unit/test_provider_cleanup_async.py`, `docs/architecture/overview.md` and its local ignored `.de.md`, this new report and its local ignored `.de.md`. Hash comparison finds only the two intentionally modified existing tracked files. The historical review hash is unchanged; the original untracked review remains untracked. New reports/tests are not staged by this task.

Residual limitation: cancellation still waits for in-flight synchronous provider work and bounded worker capacity, as ownership requires. That wait is now asynchronous and does not freeze unrelated API work. Provider reliability, the existing 45-second SDK/90-second default application budgets and the other review findings are unchanged and were not investigated here.
