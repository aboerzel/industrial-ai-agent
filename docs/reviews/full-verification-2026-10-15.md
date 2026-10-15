# Full Verification — 2026-10-15

## Baseline

Repository: D:/Freelance/industrial-ai-agent. Branch: main.
HEAD: 5f977d8a6203936599a183d6e64e08247d0d88f3.
Python 3.12.10 (configured .venv); Node 24.19.0; npm 11.17.0;
Docker 29.8.2; Compose 5.6.0. Compose project: industrial-ai-agent.

The working tree was already dirty: four 2026-10-15 English reports were staged and
one had further unstaged work. Their previous contents and index patch were archived
before this new run. No user changes were discarded. This run adds the four diagnosed
repairs below; it makes no commit. Initial/current manifests, status, image IDs,
container inventory and all command logs are under
`evals/results/stabilization-2026-10-15/run-02/` (called `evidence/` below).
All eight historical 2026-10-14 EN/DE report files remain byte-identical to initial hashes.
The historical repair log's Git CRLF/stat indicator has no byte/content change.

## Stabilization iterations

2 complete stabilization cycles, followed by a distinct authoritative Phase C cycle.
All seven custom images were built without cache in each cycle. Twelve project volumes
were retained, including factory-db-data, postgres-data, hf-cache, telemetry and all
Langfuse data/log volumes. Local Ollama and unrelated Docker resources were preserved.
No prune, persistent volume deletion, hard reset or destructive clean was used.

## Repairs performed

| ID | Severity | Root cause | Fix | Regression | Status |
| --- | --- | --- | --- | --- | --- |
| S01 | MEDIUM | Approval card omitted authoritative action/target (prior F01) | Bounded text-only action/target/details | Ticket/calibration DOM, literal HTML, real API/Chromium | RESOLVED, attempt 1 |
| S02 | MEDIUM | Sync configuration and Observability I/O ran inline in async handlers (prior F02) | Existing bounded AnyIO worker dispatch after authorization | Allowed-path progress, denial, capacity, owned cancellation | RESOLVED, attempt 1 |
| S03 | MEDIUM | Windows CP1252 decoding broke required secret scanner | Explicit strict UTF-8 Git output decoding | Unicode diff plus forbidden credential positive control | RESOLVED, attempt 1 |
| S04 | LOW | README still described removed selector/download limitation (prior F03) | Current description and historical screenshot label, EN/DE | README semantic conformance | RESOLVED, attempt 1 |

See [Repair Log](stabilization-repair-log-2026-10-15.md). First failures and initial
200 ms fake blocking proofs were preserved before changes. A command-path typo and a
new cancellation test's incorrect response expectation were corrected harness invocations,
not additional product repair attempts. No test was weakened to hide a product failure.

## Unresolved defects

None. UNRESOLVED_AFTER_3_ATTEMPTS: 0. No unexplained flaky authoritative gate.

## Docker rebuild

Authoritative command: docker compose --progress plain build --no-cache.

| Service | Rebuild | Result |
| --- | --- | --- |
| agent-api | no-cache, own image | PASS |
| factory-mcp | no-cache, own image | PASS |
| knowledge-mcp | no-cache, own image | PASS |
| hardware-mcp | no-cache, own image | PASS |
| runtime-mcp | no-cache, own image | PASS |
| observability-mcp | no-cache, own image | PASS |
| rca-mcp | no-cache, own image | PASS |
| frontend and third-party services | supported existing images; static frontend mount | PASS, no third-party rebuild required |

Exact image IDs: evidence/c-images.json and c-stack.json. No-cache logs: c-build.log.
The frontend has no production compilation step, configured lint/typecheck/formatter;
its shipped static assets, syntax, vendor integrity and contracts are tested instead.

## Stack

Started with docker compose up -d --no-build --pull never --wait --wait-timeout 600.
HTTP readiness supplements Compose checks; Loki needed nine polls before /ready=200.
API/MCP protocol readiness and read-only live calls also pass.

| Service | Running | Healthy | Ready | Restarts |
| --- | --- | --- | --- | --- |
| agent-api | YES | YES | YES | 0 |
| factory-db | YES | YES | YES | 0 |
| factory-mcp | YES | YES | YES | 0 |
| frontend | YES | YES | YES | 0 |
| grafana | YES | YES | YES | 0 |
| hardware-mcp | YES | YES | YES | 0 |
| knowledge-mcp | YES | YES | YES | 0 |
| langfuse-clickhouse | YES | YES | YES | 0 |
| langfuse-minio | YES | YES | YES | 0 |
| langfuse-postgres | YES | YES | YES | 0 |
| langfuse-redis | YES | YES | YES | 0 |
| langfuse-web | YES | YES | YES | 0 |
| langfuse-worker | YES | YES | YES | 0 |
| loki | YES | YES | YES | 0 |
| observability-mcp | YES | YES | YES | 0 |
| otel-collector | YES | YES | YES | 0 |
| prometheus | YES | YES | YES | 0 |
| rca-mcp | YES | YES | YES | 0 |
| runtime-mcp | YES | YES | YES | 0 |
| tempo | YES | YES | YES | 0 |

## Gates

Complete commands/dependencies/safety matrix: evidence/gate-matrix.md. FAST is not the
complete suite. Full backend and INTEGRATION each use their own migrated, seeded,
disposable PostgreSQL database; cleanup confirms none remain.

| Gate | Passed | Failed | Skipped | Blocked | Result |
| --- | --- | --- | --- | --- | --- |
| FAST backend unit | 1631 | 0 | 1 | 0 | PASS |
| Full backend (all tests, including deterministic evals) | 1777 | 0 | 1 | 0 | PASS |
| Separate INTEGRATION | 131 | 0 | 0 | 0 | PASS |
| Frontend (also in FAST) | 276 | 0 | 0 | 0 | PASS |
| Safe registered Chromium fixtures | 66 | 0 | 0 | 0 | PASS |
| RLS/Auth | 189 | 0 | 0 | 0 | PASS |
| MCP | 154 | 0 | 0 | 0 | PASS |
| HITL/protected actions | 168 | 0 | 0 | 0 | PASS |
| Model/embedding/routing/transport egress | 428 | 0 | 0 | 0 | PASS |
| RCA/async/provider lifecycle | 151 | 0 | 0 | 0 | PASS |
| Migration upgrade/fresh bootstrap named tests | 3 | 0 | 0 | 0 | PASS |
| Documentation/import conformance | 21 | 0 | 0 | 0 | PASS |
| Golden deterministic evals | 15 | 0 | 0 | 0 | PASS |
| Live API/MCP/auth/visibility checks | 43 | 0 | 0 | 0 | PASS |
| Live shipped UI checks | 21 | 0 | 0 | 0 | PASS |
| Ruff, format (247 files), JS syntax (38 files) | — | 0 | 0 | 0 | PASS |
| Secret scans, links/EN-DE pairs/ADR refs | — | 0 | 0 | 0 | PASS |
| Offline wheel, pip check, Compose config, diff check | — | 0 | 0 | 0 | PASS |

Named groups overlap; do not add their counts to the totals. See c-*.xml/log and
gate-summary.json for exact cases. Embedding direct boundary coverage is included in
the egress group. Real isolated migrations include 0021→HEAD and fresh installation.
The only skip is Windows symlink-creation capability in test_document_content_storage;
it is not a passing test. Library deprecation/Torch padding warnings are non-failing.
Documentation checks validate local links and ignored EN/DE pairs, current facts and
ADR references; semantic EN/DE alignment was also inspected for changed documents.
Secret checks combine credential/high-signal detection and actual local secret-value
search without printing secrets. Local third-party CVE audit is not claimed.

## R01–R06 regression status

| Finding | Verification | Status |
| --- | --- | --- |
| R01 | 29 tests; raw missing/forged/mismatched request/model/zone/ceiling authorization denies before credentials/SDK/serialization/transport; positive MockTransport | CLOSED |
| R02 | 27 unit/integration cases; off-loop ticket I/O, claim order, capacity, cancellation ownership, PostgreSQL replay/uniqueness | CLOSED |
| R03 | 24 unit/PostgreSQL cases plus Chromium stale approve/reject, BFCache, identity switch; exact generation retained | CLOSED |
| R04 | Full real-session browser failure matrix and frontend lifecycle tests; independent cross-tab purge, late JSON/binary/PDF/approval, pagehide/BFCache | CLOSED |
| R05 | 19 tests; two/eight callers, per-model ownership, failed construction, close/init race, concurrent warm calls, RCA drain before close | CLOSED |
| R06 | Current docs compared with Nginx/session/API/UI and executed 66-fixture registry; README remaining drift separately repaired S04 | CLOSED |

## Demo Auth

| Identity | Clearance | Roles | Configuration |
| --- | --- | --- | --- |
| demo-public | PUBLIC | none | denied |
| demo-internal | INTERNAL | none | denied |
| demo-confidential | CONFIDENTIAL | none | denied |
| demo-restricted | RESTRICTED | none | denied |
| demo-admin | PUBLIC | MODEL_ADMIN | allowed |

Fresh browser defaults PUBLIC. Header order Monitoring → Configuration → Account;
investigation toolbar PDF → New Chat. No clearance selector or Basic challenge.
Quick switch, logout/reselect, language, capability reset and protected-state purge pass.
Password-free predefined user selection is intentional only in explicit Demo Auth Mode.
Disabled-mode endpoints, neutral invisible-run denial, session TTL/logout and forged
identity/clearance attempts are covered. Role never raises data clearance.

## Demo Visibility

Actual SQL seed and live read-only MCP lists match the canonical
[Demo User Visibility](../demo/demo-user-visibility.md) matrix.

| Identity | Stations | Product subset |
| --- | --- | --- |
| demo-public | S01 S05 | P4101 P4102 |
| demo-internal | S01 S02 S03 S05 | PUBLIC + P4900 P4901 |
| demo-confidential | S01 S02 S03 S04 S05 S06 | INTERNAL + P4711 P4801 P4802 P4805 P4811 |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | CONFIDENTIAL + P9001 P9002 |
| demo-admin | S01 S05 | P4101 P4102 |

The exact question "welche stationen kennst du" and analogous product discovery run for
all five users through real session/API/policy/graph/capability/PostgreSQL with a fake
final model. Tests assert exactly one list call, filtering before model exposure and no
forbidden IDs. Unknown/mixed sensitive input remains conservative. Live smoke separately
certifies actual rebuilt gateway/session/MCP/RLS layers, without live model inference.

## Runtime observations

All 20 service logs are captured with credential/URL redaction. EXPECTED_NEGATIVE_TEST:
disposable DB check/unique constraint violations and intentional auth denials.
EXPECTED_STARTUP_WARNING: OTel collector DNS/export retries and Loki ring readiness;
they recover. The final 60-second stable window has no unexpected error/export failure.
BENIGN_WARNING: absent optional Grafana provisioning/plugin directories, library warnings.
LOW operational note: retained Tempo WAL fragment lacks metadata during startup replay;
no persistent volume was modified/reset, and historical telemetry completeness is not
certified. No unclassified operational blocker, restart or worker leak observed.

## Real-model E2E

NOT_RUN. Manual live-model journeys are not guaranteed deterministic and free of
protected writes. Local Ollama readiness is not real-model E2E PASS. Live protected
maintenance-ticket smoke: NOT_RUN; fakes and isolated PostgreSQL tests provide coverage.

## External model calls

0. Repository data sent to external AI services: 0. Build/package/model artifact downloads
are distinct from inference. Real protected live/hardware side effects: 0.
Commits/pushes/external deployments: 0.

## Final result

PASS. No source changes during Phase C; repaired-cycle and final-cycle source hashes
match. Four root causes resolved, none unresolved after three attempts.

## Ready for independent review

YES. Phase D starts only after this complete clean verification and a recorded freeze.
Green tests are bounded evidence, not proof of absence of defects.
