# Quality Gates

Development tiers remain FAST, INTEGRATION and MANUAL_REAL_MODEL. Release verification
has two independent outcomes under [ADR-021](../decisions/ADR-021-release-software-verification-and-local-runtime-qualification.md).

## Release commands and outcomes

```powershell
.\scripts\run-quality-gate.ps1 SOFTWARE
.\scripts\run-quality-gate.ps1 LOCAL_RUNTIME
.\scripts\run-quality-gate.ps1 FULL
```

`SOFTWARE` produces mandatory `SOFTWARE_VERIFICATION: PASS/FAIL`. It rebuilds every
Compose application image without cache, preserves volumes, and restores the supported
stack. Real-model-dependent startup health is recorded separately; the isolated
deployment proof verifies the built application independently of real chat speed.
It provisions labelled disposable PostgreSQL with a non-superuser/non-BYPASSRLS role,
runs the complete backend and integration suites, FAST, frontend, all safe browser
fixtures, the five legacy journeys and the same twelve release journeys / 59 REQUIRED
assertions. All 16 original and 30 extended reference actions use actual browser,
application, MCP, RLS and durable persistence paths. Historical regressions remain
mandatory. Missing test infrastructure fails this gate.

The test-only composition uses the production API/service, graph, catalog assignments,
egress/authorization guards, OpenAI-compatible SDK and real MCP/SQL boundaries. Only
provider HTTP responses are scripted; final API responses are never mocked. Knowledge
retrieval uses a deterministic lexical test implementation over the RLS-visible catalog.
The separate SOFTWARE KDEP deployment proof runs the production image and cached
OCR/layout/reranking pipeline offline with a deterministic embedding HTTP transport on
an internal network. It does not qualify real embedding inference. Production providers,
models, assignments, prompts, deadlines and configuration are unchanged.

`LOCAL_RUNTIME` produces separate `LOCAL_RUNTIME_QUALIFICATION`. Its read-only
configuration/auth/readiness and model-placement preflight uses the real production
Ollama / qwen3.5:9b / Q4_K_M / context 4096 and CPU embeddings. One warmup is permitted
only if needed, followed by two measured warm calls. HEALTHY requires **both** calls
to finish in <20 s **and** generate >=20 native tokens/s. A provider-unhealthy skip
requires valid LOCAL configuration, successful application/auth checks, verified
GPU-chat / CPU-embedding placement, actual local provider-boundary evidence and failed
health criteria, without an application/security error. The exact reason code is
`EXTERNAL_LOCAL_PROVIDER_UNHEALTHY`, outcome `SKIPPED_EXTERNAL_RUNTIME_UNHEALTHY`.
Missing metrics, invalid configuration, authorization/RLS failures and generic exceptions
cannot produce this skip. A correlated SDK timeout requires matching unique Ollama
execution/cancellation evidence; a timeout string or unrelated HTTP 500 is insufficient.

Healthy preflight permits the unchanged real twelve-journey browser gate: real Agent,
real Factory/Knowledge MCP, real Ollama and real embeddings, no mocks. A later proven
provider deadline is `BLOCKED_BY_LOCAL_PROVIDER`, producing `NOT_QUALIFIED`.
Wrong tools/targets, missing required evidence without provider proof, persistence,
response-contract, lifecycle, authorization or security defects remain `FAIL_PRODUCT`.
Independent defects take precedence even when a provider timeout also occurred.
Neither blocked assertions nor environmental skips become PASS. No release command
uses resume or automatic retry; first evidence and later independent outcomes remain.

`FULL` runs SOFTWARE then LOCAL_RUNTIME and writes independent sections to
`evals/results/release-verification/<unique-run>/release.json` and `release.md`.
Software correctness is YES only after every deterministic gate passes. Runtime is
YES only for QUALIFIED, NO for NOT_QUALIFIED, or NOT_TESTED for the strict preflight
skip. A software PASS with runtime skipped/unqualified is **not** a fully qualified
deployment. Process exits distinguish software failure (1), runtime product/harness
failure (2), unqualified provider runtime (3), and explicit runtime skip (4).

### Machine-wide local-chat exclusivity

`FULL` waits for SOFTWARE, including KDEP teardown, deterministic journeys, legacy and
safe browser completion and fixture-process/database cleanup, before LOCAL_RUNTIME.
Only the real local-chat phase reserves the machine's loopback TCP port `46233`.
The OS reservation is shared across checkouts, Python release controllers, direct/manual
real-model Node commands, legacy Playwright and live reference fixtures. A controller
holds it from before inference preflight through qualification evidence collection;
an inherited lease permits exactly one active chat worker, never parallel children.
Real-model Playwright requires `workers=1` and `retries=0`, including CLI overrides.

A competing start returns `LOCAL_RUNTIME_BUSY` immediately. Release/manual CLI exit is
5; Playwright reports the same explicit setup error with its nonzero exit. Preflight
is NOT_TESTED, runtime is not qualified, and the software result is unchanged. This
is neither a provider-unhealthy skip nor PASS. Read-only legacy configuration checks,
aggregation/comparison and already-complete resume evaluations need no reservation.

OS sockets avoid stale PID files and unsafe lock-file deletion. Normal completion
releases the reservation after workers finish. Controller cancellation cannot free a
still-connected worker's slot. Abrupt worker loss or exceptional worker exit retains
a bounded 90 s drain for possible API work under the existing Agent deadline, then
releases automatically; competing starts remain BUSY during that drain. No production
deadline changes. An idle dead controller leaves no stale reservation.

SOFTWARE, CPU-only KDEP and synthetic fixtures do not reserve the GPU. The test-only
API composition proves deterministic-provider provenance through a loopback fixture
endpoint and per-run token before bypassing the real-chat guard; an environment mode
flag alone cannot unlock real qualification. Lock regression tests use isolated ports
and never require the machine's GPU slot. This coordinates repository qualification
entry points; ordinary user chat, unrelated GPU applications and raw ad hoc Ollama
clients are outside this harness reservation.

Software requires zero unexplained skips. Windows symlink capability may be explicitly
excluded. The five opt-in KDEP skips in backend/integration are discharged only by the
separate successful deployment gate. Protected MANUAL_ONLY actions remain NOT_RUN and
are never counted as automatic successes. Existing deterministic HITL, approvals,
replay/idempotency and action-bound authorization tests still run.

## Commands

Run from the repository root on PowerShell:

Before the manual E2E command, configure the existing API/MCP tokens and explicit browser demo mode as described in [Browser E2E Journeys](../learning/browser-e2e-journeys.md).
The API on port 8000 requires Bearer authentication; the browser gateway on port 8080
uses server-managed demo sessions in explicit Demo Auth Mode. Missing credentials, unexpected HTTP statuses, runner errors and
incomplete aggregates return non-zero exits. FAST uses fakes and requires no E2E secrets.

```powershell
.\scripts\run-quality-gate.ps1 FAST
.\scripts\run-quality-gate.ps1 INTEGRATION
cd frontend
npm run e2e:manual
```

`FAST` runs deterministic backend unit and conformance tests, frontend state/contract
tests, Ruff lint, and Ruff format checking. It must not start Docker, call Ollama or an
external LLM provider, change model assignments, or launch browser journeys.

`INTEGRATION` runs deterministic real-boundary tests only. With
`FACTORY_DATABASE_ADMIN_URL`, this includes PostgreSQL migration upgrade from 0021 to
HEAD, fresh-install assignment bootstrap, real MCP HTTP boundaries, and persistence/API
integration tests. Without that variable it prints `SKIPPED / INFRASTRUCTURE_UNAVAILABLE`;
that is not a passing integration validation. It never calls a real or external LLM.

`MANUAL_REAL_MODEL` remains an explicit human-triggered raw measurement. Release
qualification wraps it through LOCAL_RUNTIME's strict preflight. `npm run e2e:manual`
first performs its read-only assignment/configuration preflight, is resumable and
fingerprinted, then exercises the existing 12 browser DOM journeys with Local Qwen 3.5
9B and MCP. It makes no external provider calls and remains outside FAST and ordinary CI.
It covers German and English, PUBLIC, INTERNAL, CONFIDENTIAL, and RESTRICTED requested clearances,
real reference navigation and multi-turn behavior, with required persisted-result,
reload, context-transition and PDF-content assertions where declared. PASS certifies
only the complete current required assertion plan, never optional/manual-only claims.
The separate `npm run test:e2e:fixtures` command runs the shipped UI against synthetic
loopback HTTP fixtures without models; it validates the assertion paths and is not part
of FAST or a live gateway/MCP certification. Document-download assertions require the
browser filename to match the authoritative response metadata; a synthetic wrong-filename
control verifies that mismatches fail rather than silently pass. Baseline reports in
ignored `evals/results/browser-e2e/` are compared as release evidence, not committed test
artifacts.

## Invariant Matrix

| Area | Invariants | Cheapest valid tier | Status |
| --- | --- | --- | --- |
| Security/classification | Direct run, investigation, and PDF visibility; monotonic contextual classification; invisible context cannot carry over; explicit escalation and conservative unknown context; assignment is not authorization | FAST | COVERED |
| HITL | Authorization precedes claim; denied caller cannot consume claim; authorized claim is atomic; protected action/profile contract | FAST | COVERED |
| Model configuration | Missing compatible default; explicit assignment persistence; incompatible assignment fails closed; row isolation; no live assignment writes from tests; AUTO retains security/capability guards | FAST | COVERED |
| Persistence/migrations | MANUAL, AUTO/QUALITY_FIRST, AUTO/COST_FIRST and attribution survive 0021-to-HEAD; fresh bootstrap; no duplicates | INTEGRATION | COVERED |
| Evidence/agent | Healthy state needs no invented fault; faulted RCA requires trusted evidence; model cannot self-declare it; bounded documentation retains trusted evidence; authorized station discovery; invalid final output normalization | FAST | COVERED |
| API/frontend | Terminal backend result creates one terminal UI turn; no stale refresh overwrite or duplicate terminal turn; strict RunResponse boundary; malformed response rejection | FAST | COVERED |
| References | Station/product/fault/document references survive structured flow, are not prose-only, and cannot leak without authorization | FAST | COVERED |
| Language/severity | DE/EN, SUCCESS/ATTENTION/FAILURE mappings, and turn-local ATTENTION-to-SUCCESS continuation | FAST | COVERED |
| PDF | Language and turn severity, authorized-only view, no pending/duplicate turns, sanitized exceptions | FAST | COVERED |
| MCP/operations | Initialize/list-tools failure and missing required tool are unhealthy; deployed MCP healthchecks are protocol-aware | FAST plus INTEGRATION boundary coverage | COVERED |
| Documentation | Current API routes, Compose services, E2E scripts, three quality tiers; no legacy router presented as current | FAST | COVERED |
| Real model/browser | Declared required assertions for real tool choices, model behavior and DOM journeys; gateway identity switching, independent MCP transport and HITL writes are manual-only in browser reports | MANUAL_REAL_MODEL | NOT_RUN until a current complete measurement; synthetic assertions validated separately |

## When To Run

| Change | Required gate |
| --- | --- |
| Documentation only | FAST documentation/conformance subset |
| Small backend or unit change | FAST |
| Frontend state or API contract | FAST |
| Security/classification | FAST; add INTEGRATION for persistence/boundary changes; MANUAL after substantial redesign |
| Migration/schema | FAST and INTEGRATION |
| MCP server/tool schema | FAST contract and INTEGRATION readiness; MANUAL when agent-visible behavior changes |
| LangGraph/evidence/orchestration | FAST and INTEGRATION; MANUAL after substantial behavior change |
| Model/provider/catalog | FAST and INTEGRATION; MANUAL after meaningful execution-policy change |
| Major release/milestone | SOFTWARE and separate LOCAL_RUNTIME (or FULL); retain both outcomes |

## Result Interpretation

`PASS` means the requested gate completed successfully. `FAIL` blocks the relevant
change. `SKIPPED / INFRASTRUCTURE_UNAVAILABLE` means integration infrastructure was not
present and must be run later; it is never evidence that the integration gate passed.
Manual real-model evaluation is intentionally human-triggered because it consumes local
inference time and validates behavior deterministic tests cannot guarantee.
Journey reports expose planned/executed/passed/failed/blocked assertion counts. Required
BLOCKED or NOT_RUN cannot yield PASS. Historical reports without the current assertion
plan require fresh measurement. See the journey coverage table and remaining limits in
[Browser E2E Journeys](../learning/browser-e2e-journeys.md).

FAST also runs `scripts/check-demo-secrets.py`: an incremental high-signal and credential-
literal check over tracked changes and nonignored new files. The predefined canonical
browser passwords are narrowly recognized; infrastructure keys and realistic provider
secret patterns remain rejected, including in test files. This local check supplements
review and does not claim exhaustive third-party secret-scanner coverage.
