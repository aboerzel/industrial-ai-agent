# Quality Gates

This repository uses three deliberately separate quality tiers. They protect different
risks without turning ordinary development into a real-model release exercise.

## Commands

Run from the repository root on PowerShell:

Before the manual E2E command, configure the existing API/MCP tokens and local browser
credentials as described in [Browser E2E Journeys](../learning/browser-e2e-journeys.md).
The API on port 8000 requires Bearer authentication; the browser gateway on port 8080
requires HTTP Basic. Missing credentials, unexpected HTTP statuses, runner errors and
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

`MANUAL_REAL_MODEL` is an explicit human milestone or release gate. `npm run e2e:manual`
first performs its read-only assignment/configuration preflight, is resumable and
fingerprinted, then exercises the existing 12 browser DOM journeys with Local Qwen 3.5
9B and MCP. It makes no external provider calls and remains outside FAST and ordinary CI.
It covers German and English, PUBLIC, INTERNAL, CONFIDENTIAL, and RESTRICTED requested clearances,
real reference navigation and multi-turn behavior, with required persisted-result,
reload, context-transition and PDF-content assertions where declared. PASS certifies
only the complete current required assertion plan, never optional/manual-only claims.
The separate `npm run test:e2e:fixtures` command runs the shipped UI against synthetic
loopback HTTP fixtures without models; it validates the assertion paths and is not part
of FAST or a live gateway/MCP certification. The current document-download filename
defect makes affected live document journeys fail rather than silently pass. Baseline reports in
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
| Major release/milestone | FAST, INTEGRATION, and MANUAL_REAL_MODEL |

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
