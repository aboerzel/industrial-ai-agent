# Browser E2E Journeys

The manual runner registers 12 multi-turn journeys against the local Compose runtime.
The older `npm run test:e2e` specification contains five German journeys. Neither command
is part of FAST, and a green historical report is not proof of the current assertions.
Both use explicit assertion plans; model behavior still requires a deliberate local
real-model measurement. Separate synthetic browser fixtures exercise the same assertion
functions with the shipped UI and a local fake HTTP server, without Compose, MCP or models.

Run it after the local stack is healthy:

Configure credentials in the Git-ignored root `.env` or the runner process environment
before using the commands below. Explicit process values take precedence; an empty
value fails closed rather than falling back to `.env`. Use the existing
`AGENT_API_MODEL_ADMIN_TOKEN` for runner-only catalog/assignment reads and
`MCP_INDUSTRIAL_AGENT_TOKEN` for MCP readiness. Browser login uses
`E2E_FRONTEND_USERNAME` (default `restricted`) and `E2E_FRONTEND_PASSWORD`, matching
an identity/password provisioned in the external `FRONTEND_AUTH_FILE`. Manual-runner
model-configuration smoke uses a separate `model-admin` browser context with
`E2E_MODEL_ADMIN_PASSWORD`. These passwords must be provisioned locally; placeholders
from `.env.example` are rejected. No token or password is committed or written to
normal reports. Authenticated Playwright traces are disabled to avoid credential capture.

The default URLs are `E2E_API_URL=http://127.0.0.1:8000` and
`E2E_FRONTEND_URL=http://127.0.0.1:8080`. Direct API reads send the model-admin Bearer
header; browser requests authenticate with origin-scoped HTTP Basic, and Nginx maps
the verified identity to its server-held API token. Bearer tokens are never injected
into page JavaScript or storage. The clearance selector only narrows the authenticated
identity's ceiling; it does not switch identity. The `restricted` default permits all
requested clearance levels in the existing registry without granting model-admin to
the investigation context. A lower-ceiling identity requires a compatible journey subset.

Missing required credentials block preflight before network access and return a non-zero
exit. HTTP success is explicitly 200 (MCP notifications require 202); redirects and
unexpected 401/403/4xx/5xx fail. Expected negative responses must declare the exact status
or a bounded allowed set: a context-change reload accepts 200 or neutral 404 only for its
specific investigation and new clearance. Status is checked before JSON parsing, and
error bodies/headers are not recorded. `FAIL`, `BLOCKED`, `HARNESS_ERROR`, failed critical
smoke checks, and incomplete aggregates all produce non-zero exits. Aggregate API failures
remain visible; an unevaluated product gate is `NOT_EVALUATED`, never PASS. Aggregation
expects the complete existing registry, so a partial subset remains INCOMPLETE.

Deterministic auth/status/exit regressions run without browsers, services or models:

```text
node --test tests/frontend/e2e-http-security.test.mjs tests/frontend/manual-e2e-runner.test.mjs
node --test tests/frontend/journey-assertions.test.mjs
```

Run that command from the repository root. It substitutes HTTP and child processes;
it does not replace the separate real-model milestone gate.

Run the safe browser assertion regressions independently (Chromium must already be installed):

```text
cd frontend
npm run test:e2e:fixtures
```

The fixture configuration is separate from the live E2E configuration, needs no secrets,
and denies browser requests outside its ephemeral loopback server. Synthetic responses
prove the assertion and UI paths, not real-model choices, live authorization or MCP behavior.

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
an atomic `PASS` artefact and the current complete assertion plan, including expected
`ATTENTION` paths whose assertions pass. Legacy PASS artifacts without that plan are
BLOCKED and require an explicit fresh `--journey` measurement.
It retries `HARNESS_ERROR`, missing and unmeasured journeys. Measured `FAIL` and `BLOCKED`
artifacts are retained and still cause a non-zero exit; invoke their `--journey` explicitly
to retry them. A `HARNESS_ERROR`
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

Reference steps capture the actual run request, validate the selected clearance and DE/EN
language, require run/investigation IDs and a matching persisted terminal turn, check the
target in the result, and require the relevant executed-tool name, target arguments and
recorded finding. `tool_calls` is the API projection of server-recorded `executed_tool_calls`;
it is not inferred from a button or prose. This projection does not expose raw MCP results
or prove the transport independently. A journey has at most four follow-up clicks and
never revisits an `(identifier, action)` pair. Typed steps with an explicit required tool
apply the same evidence check; other follow-ups may use earlier evidence.

The manual wrapper creates a unique run directory below `evals/results/browser-e2e/`;
individual commands use their explicit run ID or `manual-current`. Reports list each
planned assertion, its REQUIRED/OPTIONAL/MANUAL_ONLY requirement, executed flag and
PASS/FAIL/BLOCKED/NOT_RUN status. Required totals, executed, passed, failed and blocked/not-run
counts appear in JSON and Markdown. PASS requires every REQUIRED assertion to have executed
and passed, plus the existing critical smoke checks. Missing IDs, documents, tool evidence
or pre-transition security state cannot silently pass. Optional missing reference clicks
remain explicitly NOT_RUN and contribute no passed observation. Planned tags and actually
asserted coverage are reported separately. An incomplete required plan cannot be resumed
or aggregated as PASS. Provider failure contracts remain deterministic test-double cases.

## Assertion coverage and limits

Each agent step requires a bound persisted terminal result and nonempty answer/error;
severity, basic language signals and target presence are checked, rather than general
semantic correctness of generated prose. Every journey reloads its current investigation
under the selected context. PDF-tagged journeys trigger the UI download and require HTTP
200, a completed file, PDF content type/signature/trailer, the investigation ID, classification
and relevant identifiers/tool names or a stable request fragment. The current server export
uses uncompressed ReportLab streams; unsupported output encoding fails the content check.
These checks are not a complete visual/layout or PDF-text semantic evaluation.

| Manual-runner journey | AUTOMATED AND ASSERTED when measured | OPTIONAL |
| --- | --- | --- |
| `s04-investigation` | S04 result/tool binding, fault-reference search, document open/download, follow-up, reload, PDF | None |
| `station-discovery` | Station-list tool, station-reference status, follow-up, reload | Product-reference click |
| `product-history` | P4101 history/tool binding, station-reference status, follow-up, reload | None |
| `documentation` | QUALITY-09 search/tool, document open/download, PUBLIC downgrade purge/read/PDF denial, explicit denied query, upgrade/continuation, reload, PDF | None |
| `clearance-boundary` | P4711 history/tool, INTERNAL downgrade purge/read/PDF denial, explicit denied query, upgrade/continuation, new-chat reset, reload, PDF | None |
| `station-discovery-de` | Typed result, station-reference status/tool, follow-up, reload | None |
| `healthy-station-de` | S01 result, station-reference status/tool, reload | Product-reference click |
| `healthy-station-en` | S01 result, follow-up, station-reference status/tool, reload | None |
| `s04-investigation-en` | S04 result, follow-up, fault-reference search/tool, reload | None |
| `product-centric-en` | P4901 result, product-reference history/tool, reload | Station-reference click |
| `clearance-boundary-en` | Station result, explicit unavailable-documentation outcome, new-chat reset, public station result, reload, PDF | None |
| `restricted-boundary` | S07 result, station-reference status/tool, documentation follow-up, reload | None |

The five older Playwright journeys apply the same persisted-result, document, reload and
context helpers; A, D and E also require PDF export. Journey E saves the ID before the
downgrade and submits an explicit denied query after the frontend purges old references.
Compound report flags derive from complete measured assertions instead of constant PASS values.

Downgrades require previously visible higher-classification data, a changed selector,
the saved investigation's neutral 404, purged rendered/export state and a direct PDF 404
under the lower context. A later request uses the new selection. Upgrades reload under
the new context; they do not switch gateway identity. Individual document classifications
are independent of the enclosing run. A protected synthetic document download is explicitly
denied in the fixture suite; the live registry does not claim a per-document authorization matrix.

Document steps require a persisted document reference, an actual opened blob with nonempty
content, an actual download, matching bytes, appropriate type and matching server filename.
**Known separate product defect:** `frontend/js/api.js` currently assigns the document
download filename from `document.filename` rather than the response document. The assertion
detects this and the affected live document journeys fail; this test-quality change does
not repair that product code or retain a green acceptance claim.

MANUAL_ONLY / NOT_RUN claims in each report explicitly separate live gateway identity
switching, independent MCP transport/result inspection and protected HITL execution.
The read journeys never propose or approve a write. Existing deterministic backend and
boundary tests cover those contracts separately; these browser reports do not certify them.
Real-model answer correctness, full PDF layout/content semantics and physical recovery
are NOT COVERED by the synthetic suite. Credentials are not available for a second ordinary
identity in the current journey configuration, so identity switching is not an automated claim.

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
it does not compare generated answer prose byte-for-byte. Execution reports use
PASS/FAIL/BLOCKED/HARNESS_ERROR/INCOMPLETE; no P0/P1 or GREEN/YELLOW/RED scoring is
implemented by this runner. A PASS applies only to its listed executed assertions.

This Manual Real-Model E2E suite is deliberately not intended for every development
change. The implemented FAST / INTEGRATION / MANUAL_REAL_MODEL ladder and its commands
are defined in [Quality Gates](../quality/quality-gates.md). Authenticated calls, explicit
expected statuses, fail-closed aggregation/exit codes, and complete REQUIRED assertions
govern the current runner; OPTIONAL and MANUAL_ONLY claims remain separate.
