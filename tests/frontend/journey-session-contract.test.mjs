import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { completedJourneyStatus, establishBrowserDemoSession } from "../../frontend/scripts/e2e-http.mjs";
import { classifyJourneyFailure, evaluateJourneyStep, journeyResultCategory } from "../../frontend/scripts/journey-execution.mjs";
import { classifyHttpResponse, createJourneyHttpTrace, sanitizedHttpBody } from "../../frontend/scripts/journey-http-trace.mjs";
import { assertionPlan, assertionSummary, MissingEvidence, recordAssertion } from "../../frontend/scripts/journey-assertions.mjs";

test("bootstrap establishes the browser cookie jar without bearer or caller clearance", async () => {
  let observed;
  const user = { username: "demo-public", clearance: "PUBLIC", roles: [] };
  const context = { request: { post: async (url, options) => { observed = { url, options }; return { status: () => 200, json: async () => user }; } } };
  assert.deepEqual(await establishBrowserDemoSession(context, "http://127.0.0.1:8080"), user);
  assert.equal(observed.url, "http://127.0.0.1:8080/api/v1/auth/bootstrap");
  assert.deepEqual(observed.options.headers, { "X-Demo-Session": "1" });
  assert.deepEqual(observed.options.data, {});
  assert.equal(observed.options.maxRedirects, 0);
  context.request.post = async () => ({ status: () => 401 });
  await assert.rejects(establishBrowserDemoSession(context, "http://127.0.0.1:8080"), /HTTP status 401/);
});

test("neutral 404, missing resource and authentication failure remain separate", () => {
  assert.equal(classifyHttpResponse(401), "AUTHENTICATION_FAILURE");
  assert.equal(classifyHttpResponse(404, "requested_data_unavailable"), "AUTHORIZATION_NEUTRAL_DENIAL");
  assert.equal(classifyHttpResponse(404, "not_found"), "MISSING_RESOURCE");
  assert.equal(classifyHttpResponse(200), null);
  assert.deepEqual(sanitizedHttpBody({ code: "requested_data_unavailable", message: "SECRET", cookie: "SECRET", password: "synthetic-redaction-secret", answer: "SECRET", username: "demo-admin" }), {
    error_code: "requested_data_unavailable", terminal_status: null, data_classification: null, username: "demo-admin",
  });
});

test("failed model assertion cannot abort or silently pass later planned evaluations", async () => {
  const definition = { steps: [{ kind: "typed", expected: "SUCCESS" }, { kind: "typed", expected: "SUCCESS" }] };
  const result = { assertions: assertionPlan(definition), steps: [] };
  const guard = { assertSuccessful() {}, takeFailures() {} };
  await evaluateJourneyStep(result, definition.steps[0], 0, async () => { throw new MissingEvidence("Required tool call missing."); }, guard);
  await evaluateJourneyStep(result, definition.steps[1], 1, async () => recordAssertion(result, result.current_assertion_id, "PASS"), guard);
  await evaluateJourneyStep(result, { kind: "reload" }, 2, async () => recordAssertion(result, result.current_assertion_id, "PASS"), guard);
  assert.equal(result.assertions[0].status, "BLOCKED");
  assert.equal(result.assertions[1].status, "PASS");
  assert.equal(assertionSummary(result.assertions).required_evaluated, 3);
  assert.equal(assertionSummary(result.assertions).required_passed, 2);
  assert.equal(journeyResultCategory(result), "MODEL_VARIANCE");
  assert.ok(result.assertions.filter(item => item.requirement === "MANUAL_ONLY").every(item => !item.executed));
});

test("provider, model, product and harness failures are not conflated", () => {
  assert.equal(classifyJourneyFailure(new MissingEvidence("Required document reference missing.")), "MODEL_VARIANCE");
  assert.equal(classifyJourneyFailure(new Error("provider"), { error_code: "llm_provider_unavailable" }), "BLOCKED_BY_PROVIDER");
  assert.equal(classifyJourneyFailure(Object.assign(new Error("401"), { status: 401 })), "HARNESS_ERROR");
  assert.equal(classifyJourneyFailure(Object.assign(new Error("reference 404"), { result_category: "PRODUCT_DEFECT" })), "PRODUCT_DEFECT");
  assert.equal(classifyJourneyFailure(Object.assign(new Error("Export belongs to a different investigation."), { name: "AssertionError" }), {}, { kind: "pdf" }), "PRODUCT_DEFECT");
  assert.equal(classifyJourneyFailure(new Error("Protected identifier leaked in access denial.")), "SECURITY_DEFECT");
});

test("HTTP trajectory records cookies only as presence and excludes response payloads", async () => {
  const context = new EventEmitter();
  context.cookies = async () => [{ name: "industrial_demo_session", value: "SECRET" }];
  context.request = { fetch: async url => ({ status: () => 404, url: () => url, json: async () => ({ code: "requested_data_unavailable", message: "SECRET" }) }) };
  const trace = createJourneyHttpTrace(context);
  await context.request.fetch("http://127.0.0.1:8080/api/v1/runs", { method: "POST", headers: { Authorization: "Bearer SECRET" } });
  await trace.flush();
  assert.equal(trace.rows[0].cookies_present, true);
  assert.equal(trace.rows[0].authorization_present, true);
  assert.equal(trace.rows[0].classification, "AUTHORIZATION_NEUTRAL_DENIAL");
  assert.doesNotMatch(JSON.stringify(trace.rows), /SECRET/);
  trace.close();
});

test("declared live inventory smoke cannot be silently omitted from a passing journey", () => {
  const result = { status: "RUNNING", steps: [{ test_result: "PASS" }], required_smoke: ["model_configuration", "monitoring", "discovery_inventory"], smoke: { model_configuration: "PASS", monitoring: "PASS" } };
  assert.equal(completedJourneyStatus(result), "FAIL");
  result.smoke.discovery_inventory = "PASS";
  assert.equal(completedJourneyStatus(result), "PASS");
});
