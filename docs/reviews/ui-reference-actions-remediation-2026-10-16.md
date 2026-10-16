# UI Reference Actions Remediation — 2026-10-16

**PASS. Finding fixed; ready to commit. No commit was created.**

## Scope and baseline

This report addresses only MEDIUM **V02 — Reference buttons submit unsupported request forms** from the [comprehensive review](final-comprehensive-verification-and-review-2026-10-16-run-081632.md). The observed defect was: “13 of 16 tested UI reference actions generate requests that are rejected by the real API contract.” It was functional navigation failure, not an authorization bypass.

Review-affected paths: `frontend/js/app.js:662` (`identifierActions`), `src/industrial_ai_agent/agent/run_classification_policy.py:159` and API request admission. The classifier and API admission implementation remain byte-identical to the starting manifest.

The [targeted remediation](targeted-remediation-2026-10-15.md) and [Knowledge remediation](knowledge-mcp-dependency-remediation-2026-10-16.md) were read as context. Before work, the prerequisite passed: 20/20 project services healthy, zero restarts, API readiness HTTP 200 and authenticated Knowledge MCP protocol readiness. Repository: `D:\Freelance\industrial-ai-agent`; branch `main`; HEAD `16c8979ada676513271168a8adfab37553f8e01f`; initial working tree clean. No dependency or Knowledge deployment change belongs to this remediation.

External evidence directory: `D:\Freelance\industrial-ui-reference-fix-20261016-101338`. Baseline, file hashes, commands, build logs, failed development trials and final results are retained there. This is a scoped remediation protocol, not another overall review.

## Original reproduction

All 16 original prompts match the frozen HEAD's actual `identifierActions` renderer. Before editing, the review's real FastAPI admission/session/classification reproduction was repeated with only execution replaced by a fixture: **13 neutral 404 `requested_data_unavailable`, three HTTP 200 controls**. This isolates admission failure; the three fixture successes are not claimed as real tool-execution evidence. The final browser proof uses the delivered frontend, real API, current Demo Sessions, PostgreSQL/RLS, MCP services and local model, without API or model mocks.

Failure groups: station 6/8; product 3/4; fault code 4/4. Extra prose (`genauer`, `in more detail`), unsupported EN status/history forms and separate documentation templates did not match the existing complete neutral forms. Investigation ID and response language were transmitted; the defect was not missing continuation context. Ticket inspect templates had the same mismatch and are covered additionally. Documents already used authorized Open/Download endpoints and retain them.

The old UI tests verified rendering and generated text against fixtures without crossing real request admission. The new shared case helper extracts current prompts from the actual frontend function; tests cross classification and the bounded graph instead of duplicating replacement strings.

The [frozen review cases](../../tests/fixtures/reference-actions-review.json) retain every original string. `original-16-admission-enriched.json` records identity/clearance, language, endpoint, exact payload, classification and admission outcome. `current-16-classification.json` and final live browser JSON record the replacement scope and actual selected tools/persisted runs.

## Reference contract and implementation

There is no existing structured public reference-action API. The internal two-entity diagnostic endpoint is a different use case; `next_steps` are text. The smallest compatible fix retains ordinary `POST /api/v1/runs` with `message`, `response_language`, `investigation_id` and canonical already-admitted DE/EN forms. See [UI reference actions](../learning/ui-reference-actions.md).

An exact Core parser binds the first authorized read and target before model invocation. It uses the existing sequential guarded tool node and normal tool budget. Later model calls remain within relevant read capabilities and retain the primary target; replacement IDs, discovery detours and protected writes are rejected before dispatch. No UI-origin flag, new authority, classifier relaxation, role/RLS change or model-egress bypass is added. Fake models that omit the identifier or paraphrase it as P9999 cannot change the actual read or create a trusted replacement reference.

Self-contained reference reads retain investigation ownership and monotonic server context classification while using fresh authorized observations rather than replaying earlier conversational prose into the model. Station buttons request bounded current status/overview, with proportional status evidence; full typed station RCA retains its existing machine/fault/documentation requirements. ADR-004, its diagram, overview and local German counterparts describe this bounded first-read exception.

Live implementation checks also exposed and corrected two concrete composition problems. Documentation reads now supply the Core's explicit `top_k=3`; the MCP bridge otherwise materializes the omitted optional field as `None`, which the real Knowledge handler rejects. A regression crosses the advertised MCP schema and real handler. Ticket ID `MT-S02-20260117` previously caused the station evidence extractor to initialize a full S02 RCA ledger. Exact non-station reads now create no station ledger from embedded ID fragments. Both unit and safe browser fixtures now use the real run classification/evidence profile, so this failure cannot hide behind a shallow graph fixture.

## Original matrix after remediation

Every row below is HTTP 200, terminal success, correct first tool and exact ID after the change. Original HTTP 200 rows were admission controls as explained above. The full payload, emitted classification and persisted investigation readback are in the external JSON evidence.
| # | User | Reference / action | Before | Current message | First capability | After |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | demo-public | S01 / Station untersuchen (DE) | 404 | `Prüfe den aktuellen Status von Station S01.` | `get_station_overview` | 200 / success |
| 2 | demo-public | S01 / Aktuellen Status prüfen (DE) | 200 | `Prüfe den aktuellen Status von Station S01.` | `get_station_overview` | 200 / success |
| 3 | demo-public | S01 / Investigate station (EN) | 404 | `What is the current status of station S01?` | `get_station_overview` | 200 / success |
| 4 | demo-public | S01 / Check current status (EN) | 404 | `What is the current status of station S01?` | `get_station_overview` | 200 / success |
| 5 | demo-confidential | S04 / Station untersuchen (DE) | 404 | `Prüfe den aktuellen Status von Station S04.` | `get_machine_status` | 200 / success |
| 6 | demo-confidential | S04 / Aktuellen Status prüfen (DE) | 200 | `Prüfe den aktuellen Status von Station S04.` | `get_machine_status` | 200 / success |
| 7 | demo-confidential | S04 / Investigate station (EN) | 404 | `What is the current status of station S04?` | `get_machine_status` | 200 / success |
| 8 | demo-confidential | S04 / Check current status (EN) | 404 | `What is the current status of station S04?` | `get_machine_status` | 200 / success |
| 9 | demo-internal | P4901 / Produkt untersuchen (DE) | 404 | `Untersuche Produkt P4901.` | `get_product_overview` | 200 / success |
| 10 | demo-internal | P4901 / Produkthistorie anzeigen (DE) | 200 | `Zeige die Produkthistorie von P4901.` | `get_product_history` | 200 / success |
| 11 | demo-internal | P4901 / Investigate product (EN) | 404 | `Investigate product P4901.` | `get_product_overview` | 200 / success |
| 12 | demo-internal | P4901 / Show product history (EN) | 404 | `Show me the production history for P4901.` | `get_product_history` | 200 / success |
| 13 | demo-confidential | QUALITY-09 / Untersuchen (DE) | 404 | `Untersuche QUALITY-09.` | `search_documentation` | 200 / success |
| 14 | demo-confidential | QUALITY-09 / Dokumentation suchen (DE) | 404 | `Untersuche QUALITY-09.` | `search_documentation` | 200 / success |
| 15 | demo-confidential | QUALITY-09 / Investigate (EN) | 404 | `Investigate QUALITY-09.` | `search_documentation` | 200 / success |
| 16 | demo-confidential | QUALITY-09 / Search documentation (EN) | 404 | `Investigate QUALITY-09.` | `search_documentation` | 200 / success |

## Deterministic regressions

| Gate | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Full backend (`pytest tests`) | 2044 | 0 | 6 |
| INTEGRATION | 279 | 0 | 5 |
| FAST unit | 1750 | 0 | 1 |
| Full frontend (also FAST) | 328 | 0 | 0 |
| All safe browser fixtures, retries 0 | 140 | 0 | 0 |
| Focused reference/MCP-handler tests | 85 | 0 | 0 |
| Real stack reference browser suite, retries 0 | 35 | 0 | 0 |

The five integration skips are the explicitly opt-in KDEP container deployment proofs, already belonging to the prior Knowledge remediation; this task verifies the live prerequisite and real document retrieval. The other backend/unit skip is unavailable Windows symlink creation. They are not counted as passes. Integration and browser database mutations use disposable PostgreSQL 18.6, database `verification_reference`, a nonsuperuser/NOBYPASSRLS application role, real FK/RLS and tmpfs storage; persistent demo factory records are not altered.

C01–C06 and R01–R06 named regression invariants pass in the full suites. Specific current backend evidence includes C01 18, C02 19, C04 31, documentation conformance 14, C06 29, R01 29, R02 27, R03 24, R05 19, N01 21, FC01 29, FC02 37 and FC03 44 cases, without failures/skips in those groups. R04/FC04 lifecycle, R03 browser approval generation, document/download/PDF and Demo Auth are covered by the full browser/frontend runs. These are regression results, not a new global certification.

## Final live reference proof

**PASS, 35/35, zero skips/retries.** Run directory: `live-reference-final-v5`. All cases use real delivered frontend/API/Demo Sessions and local model infrastructure. Previously successful real investigations seed persisted-reference navigation; no synthetic API/model response is injected. Every action submits anew to the final image and proves first tool/target, terminal UI and persisted continuation. Fresh ticket investigations test the corrected production evidence composition. DE/EN document Open/Download, hidden/unknown neutral denial, reload/language change and cross-tab purge are included. Counts: product 16/16, station 8/8, fault code 4/4, ticket 2/2; document Open/Download 4/4 across two language tests. Original review matrix: 16/16 accepted and correct. Positive-action HTTP 500 and unexpected neutral 404: zero. The four actual fault-read checkpoints retain the correct document IDs, source paths, fault provenance and classifications at or below CONFIDENTIAL.

Development evidence remains retained: the first live trial exposed status/RCA and MCP-default issues; the next complete extended trial passed 33/35 and exposed both ticket cases. These were code defects corrected before the final run, not relabeled as model variance or hidden through automatic retries. Safe fixtures were rerun after substantive changes with retries disabled.

Four additional direct real-API controls replay the actual protected document Open/Download URLs under a fresh PUBLIC Demo Session and compare unknown IDs. Both endpoints return the same neutral 404/code/message without document ID, title or required clearance. Evidence: `real-document-neutral-controls.json`.

A separate authenticated real Knowledge MCP call confirms document ID, source, chunk ID, fault metadata and classification for all three returned hits (`real-knowledge-mcp-chunk-provenance-final.json`). The checkpoint's intentionally compact model projection preserves document/source/fault provenance; the original MCP result additionally retains chunk provenance. A diagnostic probe initially assumed raw chunk fields in that compact projection; its failed assertion is retained and was corrected at the proper transport boundary, without a product change.

## Local Real-Model product quality

**PASS: 12/12 journeys, 59/59 required assertions; PRODUCT_DEFECT 0, MODEL_VARIANCE 0, HARNESS_ERROR 0, SECURITY_DEFECT 0.** Final runner execution and product-quality aggregation both report PASS. Its 724 recorded HTTP observations contain zero HTTP 500 and seven expected neutral denials. The 24 declared MANUAL_ONLY transport/protected-HITL assertions remain NOT_RUN and are excluded from the automatic pass count; no physical or protected execution is claimed.

An initial diagnostic trial exposed an incorrect harness expectation: station reference checks always required `get_machine_status`, despite successful, target-bound `get_station_overview` results for the documented safe scope. Its raw `MODEL_VARIANCE` labels for station discovery/product history are preserved but are diagnosed as harness errors, not genuine model variance. That trial was stopped; artifacts remain under `ui-reference-remediation-20261016-101338`.

The corrected helper accepts exactly the two documented station reads and requires the first call's exact clicked ID plus its recorded finding. Missing evidence, wrong IDs, unrelated capabilities and protected writes still fail. Three new frontend regressions cover both positive paths and those negative controls (18 focused assertion tests total). No production routing or security policy changed for this harness correction. A fresh preflight/fingerprint and complete 12-journey run passed under `ui-reference-remediation-final-20261016-101338`; no earlier trial was promoted to PASS. Preflight and before/after assignment snapshots verify `local_quality` for all four classifications. External providers and protected execution remain forbidden.

| Journey | Result | Required assertions | Material issue |
| --- | --- | ---: | --- |
| clearance-boundary-en | PASS | 6/6 | None |
| clearance-boundary | PASS | 9/9 | None |
| documentation | PASS | 8/8 | None |
| healthy-station-de | PASS | 3/3 | None |
| healthy-station-en | PASS | 4/4 | None |
| product-centric-en | PASS | 3/3 | None |
| product-history | PASS | 4/4 | None |
| restricted-boundary | PASS | 4/4 | None |
| s04-investigation-en | PASS | 4/4 | None |
| s04-investigation | PASS | 6/6 | None |
| station-discovery-de | PASS | 4/4 | None |
| station-discovery | PASS | 4/4 | None |

The station-discovery journey additionally passed all ten live inventory checks (five identities × two inventories); API answer, persisted answer and browser IDs equal the complete authorized seed sets. Reference budgets remain separate.

| User | Exact station IDs | Exact product IDs |
| --- | --- | --- |
| demo-public | S01 S05 | P4101 P4102 |
| demo-internal | S01 S02 S03 S05 | P4101 P4102 P4900 P4901 |
| demo-confidential | S01 S02 S03 S04 S05 S06 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 |
| demo-restricted | S01 S02 S03 S04 S05 S06 S07 S08 | P4101 P4102 P4711 P4801 P4802 P4805 P4811 P4900 P4901 P9001 P9002 |
| demo-admin | S01 S05 | P4101 P4102 |

## Quality, runtime and integrity

FAST Ruff, format and secret scan pass. JS syntax, current documentation conformance, EN/DE pairing/local links, Compose config and `git diff --check` pass. There is no configured frontend compilation, JS lint or typecheck script beyond the repository's current checks.

Final runtime: **20/20 healthy, zero restarts; API `/ready` HTTP 200**. Agent API and Knowledge logs from the final Agent image's startup through completion contain no unexpected ERROR/CRITICAL/FATAL/traceback/import/runtime failures or HTTP 500. Expected auth/bootstrap/hidden/unknown denials and ordinary protocol session termination are not defects. Both labelled disposable tmpfs database containers were stopped and removed after their tests, with no project volume deletion. The healthy project stack remains running.

Final Agent image: `sha256:fde095c20a6caabec7eef07fee49d2238b2111c8cc4ae5f4b8528302f917d4f4`; unchanged Knowledge image: `sha256:2ba2d648aa6c4309f2ca8b583f270e0f5223d2e033e596f33342d02e69eae6e6`.

No public API schema, classifier, authorization, RLS, browser lifecycle or dependency file changed. Historical review hashes remain unchanged; new English report and local ignored German translation are additional files. Initial baseline had no user modifications; only the scoped implementation, tests and accompanying current documentation changed. No reset, clean, prune, volume deletion, commit, push or external deployment ran.

## Changed files

- `AGENTS.md`
- `docs/architecture/overview.md`
- `docs/decisions/ADR-004-agent-orchestration-strategy.md`
- `docs/learning/ui-reference-actions.md`
- `docs/reviews/ui-reference-actions-remediation-2026-10-16.md`
- `frontend/js/app.js`
- `frontend/scripts/journey-assertions.mjs`
- `frontend/scripts/run-e2e-journey.mjs`
- `src/industrial_ai_agent/agent/langgraph_troubleshooting_agent.py`
- `src/industrial_ai_agent/agent/reference_requests.py`
- `tests/e2e/fixtures/reference-actions-server.py`
- `tests/e2e/fixtures/reference-actions.spec.mjs`
- `tests/fixtures/reference-actions-review.json`
- `tests/frontend/investigation-ui.test.mjs`
- `tests/frontend/journey-assertions.test.mjs`
- `tests/integration/test_deterministic_s04_acceptance.py`
- `tests/integration/test_knowledge_mcp.py`
- `tests/reference_action_contract.mjs`
- `tests/unit/test_reference_action_contract.py`

Four ignored local German counterparts accompany the current overview, ADR-004, reference guide and this report. None is added to the Git index.

## Conclusion

V02 is fixed: supported reference navigation is admitted, retains its exact trusted target and reaches the intended bounded read through current server authority. Original matrix 16/16; extended live suite 35/35; full deterministic gates and all 12 local model journeys pass. No unsupported actionable control remains in the tested current reference types. External model calls: 0. Real protected side effects: 0. **Ready to commit: YES.** No commit was created.

