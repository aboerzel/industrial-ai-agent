import assert from "node:assert/strict";
import { completedJourneyStatus } from "./e2e-http.mjs";

export class MissingEvidence extends Error {}

export function requireEvidence(value, message) {
  if (!value) throw new MissingEvidence(message);
  return value;
}

export function plannedSteps(definition) {
  return [...definition.steps, { kind: "reload" },
    ...(definition.tags?.pdf_export === "yes" ? [{ kind: "pdf" }] : [])];
}

export function assertionPlan(definition) {
  return [...plannedSteps(definition).map((step, index) => ({
    id: `step-${index + 1}:${step.kind}`,
    claim: step.kind,
    expectations: { language: definition.language ?? null, initial_clearance: definition.clearance ?? null,
      clearance: step.clearance ?? null, target: step.target ?? null, tool: step.tool ?? null, severity: step.expected ?? null },
    checks: {
      typed: ["run/investigation IDs", "persisted terminal run and nonempty result", "request context and continuation", "rendered severity and target", ...(step.tool ? ["executed tool, arguments and recorded finding"] : [])],
      reference: ["rendered reference and target action triggered", "run/investigation binding", "persisted tool, arguments and finding", "authorized rendered result"],
      document: ["persisted document reference", "open blob content", "download artifact and response", "matching content, type and filename"],
      select: ["protected pre-transition state for downgrade", "effective selection changed", "saved-ID backend read", "UI and export purge", "protected PDF denial on downgrade"],
      "new-chat": ["investigation reference cleared", "rendered turns cleared", "export disabled"],
      reload: ["same investigation restored", "persisted run retained", "result rendered under selected context"],
      pdf: ["UI export triggered", "bound investigation and clearance", "successful binary download", "PDF type/signature", "investigation ID and relevant contents"],
    }[step.kind] ?? [],
    requirement: step.optional ? "OPTIONAL" : "REQUIRED",
    status: "NOT_RUN",
    executed: false,
  })), ...[
    ["gateway_identity_switch", "Live gateway principal switching is outside these journeys."],
    ["mcp_transport", "Persisted tool evidence does not prove the live MCP transport or physical side effects."],
    ["hitl_execution", "These read journeys do not propose or approve protected actions."],
  ].map(([id, note]) => ({ id, requirement: "MANUAL_ONLY", status: "NOT_RUN", executed: false, note }))];
}

export function assertionSummary(assertions = []) {
  const required = assertions.filter((item) => item.requirement === "REQUIRED");
  return {
    required_total: required.length,
    required_executed: required.filter((item) => item.executed === true).length,
    required_passed: required.filter((item) => item.executed === true && item.status === "PASS").length,
    required_failed: required.filter((item) => item.status === "FAIL").length,
    required_blocked_not_run: required.filter((item) => !item.executed || !["PASS", "FAIL"].includes(item.status)).length,
    optional: assertions.filter((item) => item.requirement === "OPTIONAL"),
    manual_only: assertions.filter((item) => item.requirement === "MANUAL_ONLY"),
  };
}

export function recordAssertion(result, id, status, note = null, executed = true) {
  const item = requireEvidence(result.assertions?.find((entry) => entry.id === id), "Assertion is not in the journey plan.");
  assert.notEqual(item.requirement, "MANUAL_ONLY", "Automatic execution cannot certify a manual-only claim.");
  assert.equal(item.status, "NOT_RUN", "Assertion was recorded more than once.");
  Object.assign(item, { status, executed, note });
}

export function evaluatedJourneyStatus(result) {
  if (["FAIL", "BLOCKED", "HARNESS_ERROR"].includes(result.status)) return result.status;
  const status = requiredAssertionsStatus(result.assertions);
  if (status !== "PASS") return status;
  for (const assertion of result.assertions.filter((item) => item.requirement === "REQUIRED")) {
    const observations = result.steps.filter((step) => step.assertion_id === assertion.id);
    if (observations.length !== 1 || observations[0].test_result !== "PASS") return "BLOCKED";
  }
  // Optional observations remain explicit, and are never disguised as passed steps.
  return completedJourneyStatus({ ...result, steps: result.steps.filter((step) => step.requirement !== "OPTIONAL") });
}

export function requiredAssertionsStatus(assertions) {
  const summary = assertionSummary(assertions);
  if (summary.required_failed) return "FAIL";
  if (!summary.required_total || summary.required_blocked_not_run || summary.required_passed !== summary.required_total) return "BLOCKED";
  return "PASS";
}

export function assertCurrentPlan(result, definition) {
  const shape = ({ id, requirement, claim, checks, expectations }) => ({ id, requirement, claim, checks, expectations });
  const expected = assertionPlan(definition).map(shape);
  const actual = result.assertions?.map(shape);
  assert.deepEqual(actual, expected, "Artifact does not contain the current complete assertion plan.");
  assert.ok(result.assertions.filter((item) => item.requirement === "MANUAL_ONLY").every((item) => item.status === "NOT_RUN" && item.executed === false), "Automatic artifact claims manual-only execution.");
}

const rank = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };

export function assertPersistedTurn({ run, investigation, request, clearance, language, previousId = null }) {
  requireEvidence(typeof run?.investigation_id === "string" && run.investigation_id.trim() && typeof run?.run_id === "string" && run.run_id.trim(), "Required run/investigation ID missing.");
  requireEvidence(investigation?.investigation_id && investigation?.turns?.length, "Required persisted investigation/turn missing.");
  assert.equal(investigation.investigation_id, run.investigation_id);
  if (previousId) assert.equal(request.investigation_id, previousId, "Follow-up was not bound to the current investigation.");
  else assert.ok(!request.investigation_id, "A new context reused an unexpected investigation reference.");
  assert.equal(request.user_clearance, clearance);
  assert.equal(request.response_language, language);
  const turn = requireEvidence(investigation.turns.find((item) => item.run_id === run.run_id), "Required matching persisted run missing.");
  assert.equal(turn.sequence, run.investigation_sequence);
  assert.ok(["success", "failed", "limit_reached"].includes(turn.status), "Run did not reach the expected terminal lifecycle.");
  if (run.status !== "running") assert.equal(turn.status, run.status);
  assert.equal(turn.response_language, language);
  assert.ok(rank[turn.data_classification] !== undefined && rank[turn.data_classification] <= rank[clearance]);
  requireEvidence(turn.answer?.trim() || turn.error?.code, "Persisted terminal result is empty.");
  return turn;
}

export function assertToolEvidence(turn, tool, target) {
  const calls = turn?.tool_calls?.filter((call) => call.tool === tool) ?? [];
  requireEvidence(calls.length, "Required tool call missing.");
  const argument = { get_machine_status: "station_id", get_product_history: "product_id", search_documentation: "query" }[tool];
  assert.ok(calls.some((call) => !target || (typeof call.arguments?.[argument] === "string"
    && (argument === "query" ? call.arguments[argument].includes(target) : call.arguments[argument] === target))), "Tool arguments are not bound to the required target.");
  requireEvidence(turn.investigation_steps?.some((step) => step.action === tool && step.finding?.trim()), "Required recorded tool finding missing.");
}

export function assertBinaryContent({ content, contentType, filename, expectedFormat, expectedId, expectedText = [], forbiddenText = [] }) {
  const bytes = Buffer.from(content);
  requireEvidence(bytes.length, "Required downloaded content missing.");
  assert.ok(filename && filename !== "undefined", "Download filename is missing or invalid.");
  const text = bytes.toString("latin1");
  if (expectedFormat === "pdf") {
    assert.match(contentType, /^application\/pdf(?:;|$)/i);
    assert.ok(filename.toLowerCase().endsWith(".pdf"));
    assert.ok(text.startsWith("%PDF-") && text.trimEnd().endsWith("%%EOF"), "Invalid PDF signature/trailer.");
  } else {
    assert.ok(contentType && !/text\/html|application\/json/i.test(contentType), "Unexpected document response type.");
  }
  if (expectedId) assert.ok(text.includes(expectedId), "Export belongs to a different investigation.");
  for (const value of expectedText) assert.ok(text.includes(value), "Required export/document content missing.");
  for (const value of forbiddenText) assert.ok(!text.includes(value), "Protected content present in export/document.");
}
