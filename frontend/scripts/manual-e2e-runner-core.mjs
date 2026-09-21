export const HARNESS_ERROR = "HARNESS_ERROR";
export const HARNESS_CONFIGURATION_MUTATION = "HARNESS_CONFIGURATION_MUTATION";
export const CONFIGURATION_DRIFT = "CONFIGURATION_DRIFT";

const MODEL_ASSIGNMENTS_PATH = "/api/v1/model-assignments";

export async function awaitTriggeredResponses({ requestPromise, responsePromise, trigger }) {
  // Promise.all observes both waiters immediately, including a page-close rejection.
  const observed = Promise.all([requestPromise, responsePromise]);
  try {
    await trigger();
    return await observed;
  } finally {
    await observed.catch(() => undefined);
  }
}

export function runnerFailure(error, operation, browserState = {}) {
  return {
    runner_result: error?.name === HARNESS_CONFIGURATION_MUTATION
      ? HARNESS_CONFIGURATION_MUTATION
      : HARNESS_ERROR,
    operation,
    exception_category: error?.name ?? "Error",
    message: sanitizeMessage(error?.message ?? String(error)),
    browser_state: browserState,
  };
}

export function shouldResume(status) {
  return [HARNESS_ERROR, "MISSING", "NOT_REACHED"].includes(status);
}

export function sanitizeMessage(message) {
  return String(message).replace(/Bearer\s+[^\s]+/gi, "Bearer [REDACTED]").slice(0, 500);
}

export function isRunRequestMetadata({ method, url }) {
  const parsed = new URL(url);
  return method === "POST" && parsed.pathname === "/api/v1/runs";
}

export function safeRequestMetadata(request, scope) {
  const parsed = new URL(request.url());
  return {
    method: request.method(),
    path: parsed.pathname,
    resource_type: request.resourceType(),
    scope,
    timestamp: new Date().toISOString(),
  };
}

export function isModelAssignmentPut({ method, url }) {
  const parsed = new URL(url);
  return method === "PUT" && parsed.pathname === MODEL_ASSIGNMENTS_PATH;
}

export function createReadOnlyConfigurationGuard(context) {
  const mutations = [];
  context.on("request", (request) => {
    if (isModelAssignmentPut({ method: request.method(), url: request.url() })) {
      mutations.push(safeRequestMetadata(request, "configuration-guard"));
    }
  });
  return {
    assertUnchanged(operation) {
      if (!mutations.length) return;
      const error = new Error(
        `Read-only operation '${operation}' attempted ${mutations.length} model-assignment PUT request(s).`,
      );
      error.name = HARNESS_CONFIGURATION_MUTATION;
      error.mutations = [...mutations];
      throw error;
    },
    count() {
      return mutations.length;
    },
  };
}

export function assignmentSnapshot(assignments) {
  return assignments
    .map((assignment) => ({
      consumer_id: assignment.consumer_id,
      data_classification: assignment.data_classification,
      selection_mode: assignment.selection_mode,
      model_id: assignment.model_id,
      selection_policy: assignment.selection_policy,
    }))
    .sort((left, right) =>
      `${left.consumer_id}:${left.data_classification}`.localeCompare(
        `${right.consumer_id}:${right.data_classification}`,
      ),
    );
}

export function assertAssignmentSnapshot(snapshot, current, operation) {
  if (JSON.stringify(snapshot) === JSON.stringify(assignmentSnapshot(current))) return;
  const error = new Error(
    `Model assignments changed during '${operation}'; no further model call is permitted.`,
  );
  error.name = CONFIGURATION_DRIFT;
  throw error;
}

export function classifySubmissionObservation({ submissionStarted, matchingRequest, apiRequest, terminalResult }) {
  if (!submissionStarted) return "SUBMIT_NOT_TRIGGERED";
  if (!matchingRequest && apiRequest) return "REQUEST_CONTRACT_MISMATCH";
  if (!matchingRequest) return "REQUEST_NOT_OBSERVED";
  return terminalResult ? "PRODUCT_OPERATIONAL_RESULT" : "PRODUCT_RESULT_NOT_RENDERED";
}

export function classifyReferenceObservation({
  referenceFound,
  submissionStarted,
  matchingRequest,
  apiRequest,
  terminalResult,
}) {
  if (!referenceFound) return "REFERENCE_MISSING";
  return classifySubmissionObservation({
    submissionStarted,
    matchingRequest,
    apiRequest,
    terminalResult,
  });
}

export function classifyReferenceMeasurement({
  referenceFound,
  submissionStarted,
  matchingRequest,
  apiRequest,
  terminalResult,
  expectedSeverity = null,
  actualSeverity = null,
}) {
  const observation = classifyReferenceObservation({
    referenceFound,
    submissionStarted,
    matchingRequest,
    apiRequest,
    terminalResult,
  });
  if (observation === "REFERENCE_MISSING") return { category: observation, runner_result: "PRODUCT_FAIL" };
  if (observation === "PRODUCT_RESULT_NOT_RENDERED") return { category: "PRODUCT_TIMEOUT", runner_result: "PRODUCT_FAIL" };
  if (observation !== "PRODUCT_OPERATIONAL_RESULT") return { category: observation, runner_result: HARNESS_ERROR };
  return {
    category: "PRODUCT_RESULT",
    runner_result: actualSeverity === "FAILURE" ? "PRODUCT_FAIL" : "PRODUCT_RESULT",
    test_result: actualSeverity === expectedSeverity ? "PASS" : "FAIL",
  };
}

export function createRunMetadata({
  runId,
  startedAt,
  finishedAt = null,
  gitHead,
  dirtyPaths,
  dirtyScope,
  harnessFingerprint,
  assignmentSnapshot: assignments,
}) {
  const workingTreeDirty = dirtyPaths.length > 0;
  return {
    run_id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    git_head: gitHead,
    product_revision: gitHead,
    working_tree_dirty: workingTreeDirty,
    dirty_paths: dirtyPaths,
    dirty_scope: workingTreeDirty ? dirtyScope : "CLEAN",
    harness_fingerprint: harnessFingerprint,
    real_model_id: "local_quality",
    real_model_display_name: "Local Qwen 3.5 9B",
    external_provider_calls_expected: 0,
    assignment_snapshot: assignments,
  };
}

export function renderSummaryMarkdown(summary) {
  const metadata = summary.metadata;
  return [
    "# Manual E2E Summary",
    "",
    `Run ID: ${metadata.run_id}`,
    `Product Git HEAD: ${metadata.product_revision}`,
    `Working tree dirty: ${metadata.working_tree_dirty}`,
    `Harness fingerprint: ${metadata.harness_fingerprint}`,
    `Real model: ${metadata.real_model_id} (${metadata.real_model_display_name})`,
    `External providers: ${metadata.external_provider_calls_expected}`,
    `Execution status: ${summary.execution_status}`,
    `Product quality gate: ${summary.product_quality_gate}`,
    "",
    "## Journey Results",
    "",
    "| Journey | Result | Steps |",
    "| --- | --- | ---: |",
    ...summary.journey_summary.map((journey) => `| ${journey.journey} | ${journey.result} | ${journey.steps} |`),
    "",
  ].join("\n");
}

export function calculateHarnessFingerprint(entries) {
  const hash = createHash("sha256");
  for (const { path, content } of [...entries].sort((left, right) => left.path.localeCompare(right.path))) {
    hash.update(path, "utf8");
    hash.update("\0", "utf8");
    hash.update(content);
    hash.update("\0", "utf8");
  }
  return hash.digest("hex");
}
import { createHash } from "node:crypto";
