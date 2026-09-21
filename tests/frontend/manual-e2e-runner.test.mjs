import assert from "node:assert/strict";
import test from "node:test";

import {
  CONFIGURATION_DRIFT,
  HARNESS_CONFIGURATION_MUTATION,
  HARNESS_ERROR,
  assertAssignmentSnapshot,
  assignmentSnapshot,
  awaitTriggeredResponses,
  calculateHarnessFingerprint,
  classifyReferenceMeasurement,
  classifySubmissionObservation,
  createRunMetadata,
  createReadOnlyConfigurationGuard,
  isModelAssignmentPut,
  renderSummaryMarkdown,
  isRunRequestMetadata,
  runnerFailure,
  shouldResume,
} from "../../frontend/scripts/manual-e2e-runner-core.mjs";

test("awaitTriggeredResponses returns both correlated successful waiters", async () => {
  const result = await awaitTriggeredResponses({
    requestPromise: Promise.resolve("request"),
    responsePromise: Promise.resolve("response"),
    trigger: async () => undefined,
  });

  assert.deepEqual(result, ["request", "response"]);
});

test("page-close response rejection is observed and becomes a harness error", async () => {
  const closeError = new Error("Target page, context or browser has been closed");
  const result = await awaitTriggeredResponses({
    requestPromise: new Promise(() => {}),
    responsePromise: Promise.reject(closeError),
    trigger: async () => undefined,
  }).then(() => null, (error) => runnerFailure(error, "typed submit", { page_closed: true }));

  assert.equal(result.runner_result, HARNESS_ERROR);
  assert.equal(result.operation, "typed submit");
  assert.equal(result.browser_state.page_closed, true);
});

test("response timeout is represented as a harness error", async () => {
  const result = await awaitTriggeredResponses({
    requestPromise: Promise.resolve("request"),
    responsePromise: Promise.reject(new Error("Timeout 100000ms exceeded")),
    trigger: async () => undefined,
  }).then(() => null, (error) => runnerFailure(error, "typed submit"));

  assert.equal(result.runner_result, HARNESS_ERROR);
  assert.match(result.message, /Timeout/);
});

test("resume retries only unmeasured or harness-error artifacts", () => {
  assert.equal(shouldResume("PASS"), false);
  assert.equal(shouldResume(HARNESS_ERROR), true);
  assert.equal(shouldResume("FAIL"), false);
  assert.equal(shouldResume("PRODUCT_FAIL"), false);
  assert.equal(shouldResume("BLOCKED"), false);
  assert.equal(shouldResume("MISSING"), true);
  assert.equal(shouldResume("NOT_REACHED"), true);
});

test("valid product failures remain terminal measurements", () => {
  assert.notEqual("FAIL", HARNESS_ERROR);
  assert.equal(shouldResume("FAIL"), false);
});

test("sanitized harness messages do not retain bearer credentials", () => {
  const failure = runnerFailure(new Error("Bearer secret-token failed"), "typed submit");
  assert.equal(failure.message, "Bearer [REDACTED] failed");
});

test("semantic run matcher accepts a localhost API origin", () => {
  assert.equal(isRunRequestMetadata({ method: "POST", url: "http://localhost:8000/api/v1/runs" }), true);
  assert.equal(isRunRequestMetadata({ method: "POST", url: "http://127.0.0.1:8000/api/v1/runs" }), true);
  assert.equal(isRunRequestMetadata({ method: "GET", url: "http://localhost:8000/api/v1/runs" }), false);
});

test("submission observation distinguishes an untriggered DOM click", () => {
  assert.equal(classifySubmissionObservation({ submissionStarted: false, matchingRequest: false, apiRequest: false, terminalResult: false }), "SUBMIT_NOT_TRIGGERED");
});

test("submission observation distinguishes an unobservable request after visible loading", () => {
  assert.equal(classifySubmissionObservation({ submissionStarted: true, matchingRequest: false, apiRequest: false, terminalResult: false }), "REQUEST_NOT_OBSERVED");
});

test("submission observation reports a request contract mismatch", () => {
  assert.equal(classifySubmissionObservation({ submissionStarted: true, matchingRequest: false, apiRequest: true, terminalResult: false }), "REQUEST_CONTRACT_MISMATCH");
});

test("a matching request with a slow model is not a request-start failure", () => {
  assert.equal(classifySubmissionObservation({ submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: false }), "PRODUCT_RESULT_NOT_RENDERED");
});

test("a rendered operational failure remains a product result", () => {
  assert.equal(classifySubmissionObservation({ submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: true }), "PRODUCT_OPERATIONAL_RESULT");
});

test("recognizes only PUT model-assignment requests as configuration mutations", () => {
  assert.equal(isModelAssignmentPut({ method: "PUT", url: "http://127.0.0.1:8000/api/v1/model-assignments" }), true);
  assert.equal(isModelAssignmentPut({ method: "GET", url: "http://127.0.0.1:8000/api/v1/model-assignments" }), false);
  assert.equal(isModelAssignmentPut({ method: "PUT", url: "http://127.0.0.1:8000/api/v1/runs" }), false);
  assert.equal(HARNESS_CONFIGURATION_MUTATION, "HARNESS_CONFIGURATION_MUTATION");
});

test("retains the configuration-mutation category in the runner result", () => {
  const error = new Error("Unexpected configuration write");
  error.name = HARNESS_CONFIGURATION_MUTATION;
  assert.equal(
    runnerFailure(error, "smoke controls").runner_result,
    HARNESS_CONFIGURATION_MUTATION,
  );
});

test("read-only configuration guard fails on an observed assignment PUT", () => {
  let onRequest;
  const guard = createReadOnlyConfigurationGuard({
    on(event, callback) {
      assert.equal(event, "request");
      onRequest = callback;
    },
  });
  onRequest({
    method: () => "PUT",
    url: () => "http://127.0.0.1:8000/api/v1/model-assignments",
    resourceType: () => "fetch",
  });
  assert.equal(guard.count(), 1);
  assert.throws(
    () => guard.assertUnchanged("Model Configuration smoke"),
    (error) => error.name === HARNESS_CONFIGURATION_MUTATION,
  );
});

test("compares the complete assignment matrix and reports configuration drift", () => {
  const snapshot = assignmentSnapshot([
    { consumer_id: "agent", data_classification: "PUBLIC", selection_mode: "MANUAL", model_id: "local_quality", selection_policy: null },
    { consumer_id: "agent", data_classification: "RESTRICTED", selection_mode: "MANUAL", model_id: "local_quality", selection_policy: null },
  ]);
  assert.doesNotThrow(() => assertAssignmentSnapshot(snapshot, [...snapshot].reverse(), "before model call"));
  assert.throws(
    () => assertAssignmentSnapshot(snapshot, [{ ...snapshot[1], selection_mode: "AUTO", model_id: null, selection_policy: "QUALITY_FIRST" }, snapshot[0]], "before model call"),
    (error) => error.name === CONFIGURATION_DRIFT,
  );
});

test("reference POST plus terminal DOM without a secondary response remains measurable", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: true, submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: true, expectedSeverity: "SUCCESS", actualSeverity: "SUCCESS" }),
    { category: "PRODUCT_RESULT", runner_result: "PRODUCT_RESULT", test_result: "PASS" },
  );
});

test("reference terminal attention is a passing measured result", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: true, submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: true, expectedSeverity: "ATTENTION", actualSeverity: "ATTENTION" }),
    { category: "PRODUCT_RESULT", runner_result: "PRODUCT_RESULT", test_result: "PASS" },
  );
});

test("reference terminal technical failure remains a product failure", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: true, submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: true, expectedSeverity: "SUCCESS", actualSeverity: "FAILURE" }),
    { category: "PRODUCT_RESULT", runner_result: "PRODUCT_FAIL", test_result: "FAIL" },
  );
});

test("missing rendered reference remains a product finding", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: false, submissionStarted: false, matchingRequest: false, apiRequest: false, terminalResult: false }),
    { category: "REFERENCE_MISSING", runner_result: "PRODUCT_FAIL" },
  );
});

test("reference click without a POST or UI transition is a harness submit error", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: true, submissionStarted: false, matchingRequest: false, apiRequest: false, terminalResult: false }),
    { category: "SUBMIT_NOT_TRIGGERED", runner_result: HARNESS_ERROR },
  );
});

test("reference POST without a terminal DOM result is a bounded product timeout", () => {
  assert.deepEqual(
    classifyReferenceMeasurement({ referenceFound: true, submissionStarted: true, matchingRequest: true, apiRequest: true, terminalResult: false }),
    { category: "PRODUCT_TIMEOUT", runner_result: "PRODUCT_FAIL" },
  );
});

test("run metadata records the frozen git head and dirty harness paths", () => {
  const metadata = createRunMetadata({
    runId: "baseline-20260921-01",
    startedAt: "2026-09-21T10:00:00.000Z",
    gitHead: "21e0f46",
    dirtyPaths: ["frontend/scripts/run-e2e-journey.mjs"],
    dirtyScope: "HARNESS_ONLY",
    harnessFingerprint: "a".repeat(64),
    assignmentSnapshot: [{ consumer_id: "agent", data_classification: "PUBLIC", selection_mode: "MANUAL", model_id: "local_quality", selection_policy: null }],
  });

  assert.equal(metadata.git_head, "21e0f46");
  assert.equal(metadata.product_revision, "21e0f46");
  assert.equal(metadata.working_tree_dirty, true);
  assert.deepEqual(metadata.dirty_paths, ["frontend/scripts/run-e2e-journey.mjs"]);
  assert.equal(metadata.dirty_scope, "HARNESS_ONLY");
});

test("harness fingerprint is stable for deterministic path and content ordering", () => {
  const entries = [{ path: "b.mjs", content: Buffer.from("two") }, { path: "a.mjs", content: Buffer.from("one") }];
  assert.equal(calculateHarnessFingerprint(entries), calculateHarnessFingerprint([...entries].reverse()));
  assert.notEqual(calculateHarnessFingerprint(entries), calculateHarnessFingerprint([{ ...entries[0], content: Buffer.from("changed") }, entries[1]]));
});

test("JSON and Markdown summaries agree on core metadata", () => {
  const metadata = createRunMetadata({
    runId: "baseline-20260921-01",
    startedAt: "2026-09-21T10:00:00.000Z",
    finishedAt: "2026-09-21T10:01:00.000Z",
    gitHead: "21e0f46",
    dirtyPaths: [],
    dirtyScope: "CLEAN",
    harnessFingerprint: "b".repeat(64),
    assignmentSnapshot: [],
  });
  const summary = {
    metadata,
    execution_status: "PASS",
    product_quality_gate: "PASS",
    journey_summary: [{ journey: "Documentation chain", result: "PASS", steps: 4 }],
  };
  const markdown = renderSummaryMarkdown(summary);

  assert.match(markdown, /Run ID: baseline-20260921-01/);
  assert.match(markdown, /Product Git HEAD: 21e0f46/);
  assert.match(markdown, new RegExp(`Harness fingerprint: ${metadata.harness_fingerprint}`));
  assert.match(markdown, /Execution status: PASS/);
});
