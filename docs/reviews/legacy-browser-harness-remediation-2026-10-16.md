# Legacy Browser Harness Remediation — 2026-10-16

Finding: **Legacy registered browser harness uses outdated session/request assumptions**  
Severity: **LOW**  
Result: **FIXED — ready to commit; no commit performed.**

The source review names this L01: “Older registered browser gate is incompatible with
current sessions/requests.” The affected executable paths were
`tests/e2e/investigation-journeys.spec.mjs` (`openChat`, `typedStep`, serial mode),
`frontend/playwright.config.mjs`, and the browser-journey command documentation.
This is a harness correction. Product authentication, frontend/backend code, routing,
provider behavior and security enforcement remain unchanged.

## Baseline and preserved evidence

- Repository: `D:\Freelance\industrial-ai-agent`.
- Branch: `main`.
- HEAD: `2e8c1d7f2418c4b6f00bf3a252dfc782896c6c5c`.
- Initial working tree and index: clean.
- Source of truth: [comprehensive review](final-comprehensive-verification-and-review-2026-10-16-run-120936.md), L01.
- Evidence directory outside the repository:
  `D:\Freelance\legacy-browser-harness-remediation-evidence-2026-10-16`.
- Starting versioned-file SHA-256 manifest, initial stack, original legacy outputs,
  first-run log, API access-log sequence, fresh-browser control and corrected results
  are retained there. Previous legacy JSON outputs were copied before reproduction;
  the original reproduction's browser artifacts were subsequently moved there.
- All 20 Compose services were healthy. API `/ready` returned 200.

## Original failure reproduced before changes

Command, from `frontend`:

```text
npm run test:e2e -- --retries=0
```

Registration was enumerated first with `--list --retries=0`:

| Journey | Original result |
| --- | --- |
| A: S04 fault investigation | FAIL after 180 seconds |
| B: station discovery | NOT_RUN due to serial abort |
| C: product to station | NOT_RUN due to serial abort |
| D: documentation chain | NOT_RUN due to serial abort |
| E: clearance boundary remains usable | NOT_RUN due to serial abort |

`pre-fix-gate.log`, `pre-fix-results.json`, `pre-fix-journeys.json` and
`pre-fix-http.log` preserve that first measurement. The API timeline was:

| UTC | Request | HTTP |
| --- | --- | --- |
| 16:14:19.175 | GET `/api/v1/auth/config` | 200 |
| 16:14:19.204 | GET `/api/v1/auth/me` | 401 |
| 16:14:19.219 | POST `/api/v1/auth/bootstrap` | 200 |
| 16:14:19.229 | GET `/api/v1/auth/me` | 200 |
| 16:14:19.391 | POST `/api/v1/auth/switch` | 200 |
| 16:14:19.407 | GET `/api/v1/auth/me` | 200 |
| 16:14:19.575 | POST `/api/v1/runs` | 404 |

The old guard expected 200 for the initial unauthenticated identity read. Separately,
`Untersuche Station S04 genauer.` is not an admitted neutral form and is classified
RESTRICTED, so this CONFIDENTIAL journey correctly received a neutral pre-allocation
denial. No investigation GET followed. The unconditional waiter exhausted the
180-second test budget, and `mode: "serial"` suppressed the remaining four tests.
These are harness assumptions; the product correctly failed closed.

## Verified current authentication contract

Reviewed the shipped `frontend/js/demo-auth.js`, API client, Demo Sessions routes and
resolver, Nginx configuration, Demo Authentication documentation, current E2E helpers,
R04 tests and safe fixtures. A separate fresh Chromium context confirmed the live flow:

```text
auth/config 200 → auth/me 401 → auth/bootstrap 200
→ auth/config 200 → auth/me 200 demo-public
```

The cookie is server-issued, HttpOnly, SameSite=Strict, scoped to `/api/`. The browser
does not supply clearance, roles or a service bearer token. Quick switching uses the
visible account controls and real `/auth/switch` endpoint. Logout revokes the session
and sets a `logged-out` marker. Subsequent `auth/me` and automatic bootstrap return
401 until explicit login/quick selection creates a new session. The marker is retained.

All five live identities were independently checked against `/auth/me`:

| Identity | Clearance | Roles |
| --- | --- | --- |
| demo-public | PUBLIC | none |
| demo-internal | INTERNAL | none |
| demo-confidential | CONFIDENTIAL | none |
| demo-restricted | RESTRICTED | none |
| demo-admin | PUBLIC | MODEL_ADMIN |

The live control also checked logout followed by supported quick selection. Protected
state purge, cross-tab invalidation and binary lifecycle behavior were verified by the
complete synthetic browser suite, not inferred from these identity reads alone.

## Remediation

1. Each journey retains its own Playwright browser context. A narrow fresh-context
   probe requires the initial `auth/me` 401, then calls the unchanged shared
   `establishBrowserDemoSession` helper and independently verifies username, clearance
   and roles. UI startup therefore has an established server session. Post-authentication
   identity reads and ordinary API requests still require 200.
2. Replaced unsupported free-form legacy prompts with canonical admitted station,
   error-code and explicit product-history requests. The station/product/document
   chains, exact expected identifiers, reference actions, persistence, reload and PDF
   assertions remain required. Station reference evidence accepts the two capabilities
   supported by the current contract through the existing shared assertion helper.
3. The actual run response determines whether a persisted investigation exists.
   Successful runs read the bound investigation with the existing shared API helper;
   no unconditional browser investigation-GET waiter remains. A planned ATTENTION
   step may receive 404 only with the exact neutral code, absent allocation IDs and
   absent protected target in response/UI. Unexpected 401/404 still fail.
4. Removed serial fail-fast while retaining sequential execution and zero retries.
   A controller-side reporter collects attachments across worker restarts, preregisters
   all five journeys and reports PASS/FAIL/BLOCKED/HARNESS_ERROR/NOT_RUN. A failed
   prerequisite ends its journey; later dependent assertions are BLOCKED. Independent
   journeys continue and the overall exit remains nonzero after failure.
5. Every gate invocation writes a unique ignored `legacy-<timestamp>` result directory.
   Retained journey attachments allowlist metadata and exclude cookies, tokens, headers
   and arbitrary error bodies. Browser traces remain disabled. No historical report is
   overwritten. Parent-directory creation was also checked in an isolated cold config.

The preferred 12-journey runner and all its existing shared helpers are byte-for-byte
unchanged. This task ran its focused contract tests, rather than repeating its live
12-journey gate. New legacy helpers are not used by that runner.

## Deterministic harness regression coverage

| ID | Evidence |
| --- | --- |
| LH-01 | Fresh-context 401 accepted only before bootstrap; other initial statuses rejected |
| LH-02 | Existing shared bootstrap helper, exact endpoint/header/body; no caller authority |
| LH-03 | Independent post-bootstrap `auth/me` verification, including roles |
| LH-04 | Real synthetic API quick switches through UI; exact session request and all five identities |
| LH-05 | Real synthetic logout, subsequent 401, protected DOM/export purge |
| LH-06 | Post-logout bootstrap remains denied; explicit visible selection establishes a fresh session |
| LH-07 | Unexpected post-bootstrap 401 and ordinary browser 401 remain failures |
| LH-08 | Exact neutral 404; no fabricated run or protected identifier |
| LH-09 | Arbitrary/missing-resource 404 and authorized-success 404 remain failures |
| LH-10 | Actual synthetic Playwright worker failure: first FAIL retained, next four PASS, NOT_RUN 0 |
| LH-11 | Completed assertion remains PASS; failing assertion FAIL; dependent assertions BLOCKED |
| LH-12 | Cookie/token/header/error fields excluded; actual retained gate files checked for private tokens |

During test development, LH-06 initially assumed automatic bootstrap after logout.
The unchanged server rejected it. The test was corrected to assert the actual logout
marker and explicit re-login contract; the original focused failure log is preserved.
This was not retried unchanged or counted as a green first run. The complete fixture
gate below passed its first complete run without retries.

## Validation results

| Gate | Result |
| --- | --- |
| Focused legacy Node tests | 10 PASS, 0 FAIL, 0 skipped |
| Focused LH browser tests, corrected contract | 4 PASS, 0 FAIL, 0 skipped |
| Full legacy live gate, exactly once after remediation | 5 PASS, 0 FAIL, 0 BLOCKED, 0 HARNESS_ERROR, 0 NOT_RUN; 0 flaky |
| Required legacy assertions | 30/30 PASS |
| All safe browser fixtures, enumerated first | 144 PASS, 0 FAIL, 0 skipped; retries 0 |
| R04 / FC04 browser coverage | 20 / 15 cases PASS, including cross-tab, failed refresh, BFCache/pagehide and actual Blob URL revocation |
| Preferred current runner's focused Node contracts | 90 PASS, 0 FAIL, 0 skipped |
| Real-model journey Python contract | 1 PASS |
| FAST backend/unit | 1764 PASS, 0 FAIL, 1 explicit Windows symlink-creation skip |
| FAST frontend | 338 PASS, 0 FAIL, 0 skipped |
| Ruff / format / incremental secret scan | PASS / PASS / PASS |
| JS syntax for all six changed/new executable JS files | PASS |
| `git diff --check` | PASS |

The full legacy gate took approximately 5.1 minutes. Its new retained output is
`evals/results/browser-e2e/legacy-2026-10-16T16-21-02-976Z/`.
The two manual-only assertions per journey remain explicitly unexecuted; they do not
contribute to the 30 required assertions or the zero NOT_RUN journey count.

FC03 browser fixtures used a separate tmpfs PostgreSQL container, seeded disposable
`verification_legacy_browser` database and `factory_app` role with
`rolsuper=false`, `rolbypassrls=false`. All fixtures executed; no persistent demo data
was changed. That container was stopped and removed after verification, without volume
deletion or Docker cleanup. The 20 project services remain healthy with restarts 0;
API readiness remains HTTP 200.

## File integrity and scope

Starting hashes identify changes only to the intended pre-existing harness/config,
fixture and browser-journey documentation files. New files are the legacy helper,
reporter, focused tests and this report. English browser documentation and this report
have synchronized local ignored `.de.md` counterparts. No production frontend/backend,
provider, auth, timeout, model, routing, RLS or Compose file changed. Historical reviews
and preferred runner/shared helper hashes are unchanged.

External model calls: **0**. Real protected side effects: **0**. Commits: **0**.
Pushes: **0**. Deployments: **0**.

## Conclusion

L01 is fixed. The registered legacy command now measures the supported server-session
and request contract without weakening product authentication. It executed all five
journeys successfully, preserves failures across independent journeys, and leaves
the current auth/R04/FC04 security behavior intact. Ready to commit: **YES**.
