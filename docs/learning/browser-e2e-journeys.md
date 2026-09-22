# Browser E2E Journeys

The browser E2E suite runs 12 realistic multi-turn user journeys against the local Compose
runtime. It is intentionally separate from deterministic frontend unit tests and
provider-contract tests. It exercises real DOM navigation in German and English,
classification/clearance boundaries, resumable manual execution, persisted investigations,
and PDF/document interactions.

Run it after the local stack is healthy:

```text
cd frontend
npm run test:e2e
```

The baseline runner is interruption-safe and is the preferred command for real-model
measurement. Start one independent browser process per journey, then aggregate the
completed artefacts:

```text
cd frontend
npm run e2e:journey -- --journey s04-investigation
npm run e2e:journey -- --journey station-discovery
npm run e2e:journey -- --resume
npm run e2e:journey -- --aggregate
```

`--journey` may be repeated for an explicit subset. `--resume` skips only journeys with
an atomic `PASS` artefact, including expected `ATTENTION` paths whose assertions pass.
It reruns `FAIL`, `HARNESS_ERROR`, `BLOCKED`, and missing journeys. A `HARNESS_ERROR`
means the browser runner could not complete its measurement lifecycle; it is distinct
from a product `FAIL`. Results
are stored as one file per journey in `evals/results/browser-e2e/`, followed by the
generated `browser-e2e-summary.json`. These files are Git-ignored.

All runner operations that do not intentionally edit model configuration are read-only
with respect to assignments. A browser-observed `PUT /api/v1/model-assignments` stops
the runner with `HARNESS_CONFIGURATION_MUTATION`. At the beginning of each manual
journey the complete assignment matrix is snapshotted read-only; the runner compares it
before each model call and after the journey. A difference stops further model calls as
`CONFIGURATION_DRIFT`; it never restores an assignment automatically.

Install Chromium once on a new developer machine with `npx playwright install chromium`. Before any user journey, the suite verifies that every Agent assignment is `local_quality` (Local Qwen 3.5 9B) and that the catalog resolves it to the local Ollama model. It uses `reasoning_effort="none"`; it must not call any public-cloud provider. The suite does not mutate model assignments.

Each journey interacts with the rendered reference control and its action menu. The test captures the request caused by that click, checks the selected clearance and German response language, reads the returned persisted turn, and validates that the target identifier is semantically present in the rendered result. A journey has at most four follow-up clicks and never revisits an `(identifier, action)` pair.

Results are written to a unique run directory below `evals/results/browser-e2e/`. The generated report records per-step severity and per-journey results, link-category coverage, continuity, context preservation, document opening, and clearance-boundary usability. Provider rate-limit, unavailable, and malformed-provider-response contracts remain deterministic test-double cases rather than browser real-model cases.

## Regression Tiers

Tier A is the fast normal regression gate: `npm test` and deterministic backend tests.
It does not call an LLM or run real-model Playwright journeys. Tier B is the expensive,
operator-triggered real-model suite. It uses the real browser, Agent API, Factory and
Knowledge MCP services, and only Local Qwen 3.5 9B. It is never part of normal CI,
pre-commit, or the normal backend regression gate.

Use Tier B before a milestone or release, and after meaningful changes to orchestration,
evidence, API/frontend contracts, clickable references, classification/security, or a
model/provider adapter. Do not use it for every small implementation change.

```text
cd frontend
npm run e2e:manual:preflight
npm run e2e:manual
npm run e2e:manual -- --resume
npm run e2e:manual -- --journey s04-investigation
npm run e2e:manual:aggregate -- --run-id <run-id>
npm run e2e:journey -- --run-id <run-id> --compare <previous-summary.json>
```

Manual runs use a unique run directory with `preflight.json`, per-journey JSON files,
`summary.json`, `summary.md`, the legacy `browser-e2e-summary.json`, and (when requested)
`comparison.json`. Each report records the product Git revision, safe dirty paths and
their scope, a deterministic effective-harness SHA-256 fingerprint, the local-model
identity, and the read-only assignment snapshot. The comparison uses
stable step outcome, severity, error, language, navigation, and security dimensions;
it does not compare generated answer prose byte-for-byte. A GREEN suite has no P0/P1
finding and all required journeys. YELLOW means only bounded P2/P3 findings. RED means
a security finding, unexpected technical failure, invalid response, internal error, or
broken core navigation.

This Manual Real-Model E2E suite is deliberately not intended for every development
change. The next quality-protection task will formalize the FAST / INTEGRATION /
MANUAL_REAL_MODEL ladder; this document describes the currently implemented workflow.
