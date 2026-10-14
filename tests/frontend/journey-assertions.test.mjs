import assert from "node:assert/strict";
import test from "node:test";
import { assertionPlan, assertionSummary, assertCurrentPlan, assertPersistedTurn, assertToolEvidence, assertBinaryContent, evaluatedJourneyStatus, recordAssertion } from "../../frontend/scripts/journey-assertions.mjs";
import { JOURNEYS } from "../../frontend/scripts/run-e2e-journey.mjs";

const result = (assertions) => ({
  status: "RUNNING", steps: assertions?.filter((item) => item.executed && item.status === "PASS")
    .map((item) => ({ assertion_id: item.id, test_result: "PASS", requirement: item.requirement })) ?? [{ test_result: "PASS" }],
  smoke: { model_configuration: "PASS", monitoring: "PASS" }, assertions,
});

for (const kind of ["typed", "pdf", "reference", "select"]) {
  test(`required ${kind} observation missing cannot yield PASS`, () => {
    const assertions = assertionPlan({ steps: [{ kind }] }).map((item) => item.id === `step-1:${kind}` || item.requirement === "MANUAL_ONLY" ? item : { ...item, status: "PASS", executed: true });
    assert.notEqual(evaluatedJourneyStatus(result(assertions)), "PASS");
  });
}

test("legacy PASS artifact without a planned assertion ledger is not evidence", () => {
  assert.notEqual(evaluatedJourneyStatus({ ...result(undefined), status: "PASS" }), "PASS");
});

test("assertion ledger claiming execution without correlated observations cannot yield PASS", () => {
  const assertions = [{ id: "required", requirement: "REQUIRED", status: "PASS", executed: true }];
  assert.equal(evaluatedJourneyStatus({ ...result(assertions), steps: [{ test_result: "PASS" }] }), "BLOCKED");
});

test("optional NOT_RUN is explicit and does not block passed requirements", () => {
  const assertions = [
    { id: "lifecycle", requirement: "REQUIRED", status: "PASS", executed: true },
    { id: "product", requirement: "OPTIONAL", status: "NOT_RUN", executed: false },
  ];
  assert.equal(evaluatedJourneyStatus(result(assertions)), "PASS");
});

test("manual-only claim is never counted as an executed automatic assertion", () => {
  const assertions = [
    { id: "lifecycle", requirement: "REQUIRED", status: "PASS", executed: true },
    { id: "identity", requirement: "MANUAL_ONLY", status: "NOT_RUN", executed: false },
  ];
  assert.equal(evaluatedJourneyStatus(result(assertions)), "PASS");
  assert.deepEqual(assertionSummary(assertions), {
    required_total: 1, required_executed: 1, required_passed: 1, required_failed: 0, required_blocked_not_run: 0,
    optional: [], manual_only: [assertions[1]],
  });
});

test("PASS without execution, blocked requirements and empty plans cannot yield PASS", () => {
  for (const assertions of [[], [{ requirement: "REQUIRED", status: "PASS", executed: false }], [{ requirement: "REQUIRED", status: "BLOCKED", executed: false }]]) {
    assert.notEqual(evaluatedJourneyStatus(result(assertions)), "PASS");
  }
});

test("every advertised PDF and lifecycle journey has a required execution plan", () => {
  for (const definition of Object.values(JOURNEYS)) {
    const plan = assertionPlan(definition);
    assert.ok(plan.some((item) => item.claim === "reload" && item.requirement === "REQUIRED"));
    assert.equal(plan.some((item) => item.claim === "pdf" && item.requirement === "REQUIRED"), definition.tags.pdf_export === "yes");
    assertCurrentPlan({ assertions: plan }, definition);
    assert.throws(() => assertCurrentPlan({ assertions: plan.slice(1) }, definition));
  }
});

test("assertions are recorded only if planned and cannot be counted twice", () => {
  const journey = result(assertionPlan({ steps: [{ kind: "pdf" }] }));
  recordAssertion(journey, "step-1:pdf", "PASS");
  assert.throws(() => recordAssertion(journey, "step-1:pdf", "PASS"));
  assert.throws(() => recordAssertion(journey, "unknown", "PASS"));
  assert.throws(() => recordAssertion(journey, "gateway_identity_switch", "PASS"));
});

const run = { run_id: "run-1", investigation_id: "investigation-1", investigation_sequence: 1, status: "success" };
const turn = { run_id: "run-1", sequence: 1, status: "success", data_classification: "CONFIDENTIAL", response_language: "EN", answer: "S04 is faulted.", tool_calls: [{ tool: "get_machine_status", arguments: { station_id: "S04" } }], investigation_steps: [{ action: "get_machine_status", finding: "S04 faulted" }] };
const observation = { run, investigation: { investigation_id: "investigation-1", turns: [turn] }, request: { response_language: "EN" }, clearance: "CONFIDENTIAL", language: "EN" };

test("lifecycle requires actual IDs, matching persisted run, terminal result, context and continuity", () => {
  assert.equal(assertPersistedTurn(observation), turn);
  for (const mutation of [
    { run: { ...run, investigation_id: undefined } }, { investigation: undefined },
    { investigation: { investigation_id: "other", turns: [turn] } },
    { investigation: { investigation_id: "investigation-1", turns: [{ ...turn, run_id: "other" }] } },
    { investigation: { investigation_id: "investigation-1", turns: [{ ...turn, status: "running" }] } },
    { investigation: { investigation_id: "investigation-1", turns: [{ ...turn, answer: "" }] } },
    { previousId: "different" }, { clearance: "PUBLIC" }, { language: "DE" },
  ]) assert.throws(() => assertPersistedTurn({ ...observation, ...mutation }));
});

test("tool evidence requires call, target arguments and recorded finding", () => {
  assertToolEvidence(turn, "get_machine_status", "S04");
  for (const value of [{}, { ...turn, tool_calls: [] }, { ...turn, investigation_steps: [] }]) {
    assert.throws(() => assertToolEvidence(value, "get_machine_status", "S04"));
  }
  assert.throws(() => assertToolEvidence(turn, "get_machine_status", "S07"));
  assert.throws(() => assertToolEvidence({ ...turn, tool_calls: [{ tool: "get_machine_status", arguments: { station_id: "S07", irrelevant_note: "S04" } }] }, "get_machine_status", "S04"));
});

test("missing PDF blocks a journey even if every other planned requirement passed", () => {
  const assertions = assertionPlan({ steps: [{ kind: "typed" }], tags: { pdf_export: "yes" } }).map((item) => item.claim === "pdf" || item.requirement === "MANUAL_ONLY" ? item : { ...item, status: "PASS", executed: true });
  assert.equal(evaluatedJourneyStatus(result(assertions)), "BLOCKED");
  assert.equal(assertionSummary(assertions).required_blocked_not_run, 1);
});

test("PDF evidence requires binary format, investigation binding, content and exclusions", () => {
  const binary = { content: Buffer.from("%PDF-1.4\ninvestigation-1 S04 PUBLIC\n%%EOF\n"), contentType: "application/pdf", filename: "report.pdf", expectedFormat: "pdf", expectedId: "investigation-1", expectedText: ["S04"], forbiddenText: ["SECRET"] };
  assertBinaryContent(binary);
  for (const mutation of [{ content: [] }, { content: Buffer.from("200 received") }, { expectedId: "other" }, { expectedText: ["missing"] }, { forbiddenText: ["S04"] }, { filename: "undefined" }, { contentType: "text/html" }]) {
    assert.throws(() => assertBinaryContent({ ...binary, ...mutation }));
  }
});
