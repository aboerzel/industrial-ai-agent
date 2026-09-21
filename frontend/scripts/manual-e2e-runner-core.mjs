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
  return status !== "PASS";
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
