const API_BASE_URL = "http://localhost:8000";

export class ApiClientError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

export async function createRun(message, userClearance) {
  return request("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify({ message, user_clearance: userClearance }),
  });
}

export async function getRun(runId) {
  return request(`/api/v1/runs/${encodeURIComponent(runId)}`);
}

export async function resumeRun(runId, decision) {
  return request(`/api/v1/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiClientError(
      0,
      "backend_unreachable",
      "The local agent API is not reachable. Start the FastAPI server and try again.",
    );
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const publicError = isApiErrorResponse(payload) ? payload : null;
    throw new ApiClientError(
      response.status,
      publicError?.code ?? "request_failed",
      errorMessageFor(response.status, publicError?.code, publicError?.message),
    );
  }
  if (!isRunResponse(payload)) {
    throw new ApiClientError(
      response.status,
      "invalid_response",
      "The agent API returned an invalid run response.",
    );
  }
  return {
    ...payload,
    answer: payload.answer ?? null,
    tool_calls: payload.tool_calls ?? [],
    approval_request: payload.approval_request ?? null,
  };
}

function isRunResponse(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["run_id", "status", "data_classification", "answer", "tool_calls", "approval_request"]) &&
    isUuid(value.run_id) &&
    ["running", "waiting_for_approval", "success", "limit_reached", "failed"].includes(value.status) &&
    ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].includes(value.data_classification) &&
    (value.answer === undefined || value.answer === null || isBoundedString(value.answer, 8_000)) &&
    (value.tool_calls === undefined ||
      (Array.isArray(value.tool_calls) && value.tool_calls.every(isToolCall))) &&
    (value.approval_request === undefined ||
      value.approval_request === null ||
      isApprovalRequest(value.approval_request))
  );
}

function isApiErrorResponse(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["code", "message"]) &&
    typeof value.code === "string" &&
    typeof value.message === "string"
  );
}

function isToolCall(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["tool", "arguments"]) &&
    isPublicToolName(value.tool) &&
    isRecord(value.arguments)
  );
}

function isApprovalRequest(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "action",
      "summary",
      "arguments",
      "classification",
      "model_profile",
      "status",
      "created_at",
    ]) &&
    isPublicToolName(value.action) &&
    isBoundedString(value.summary, 500, true) &&
    isRecord(value.arguments) &&
    isBoundedString(value.classification, 32, true) &&
    isBoundedString(value.model_profile, 128, true) &&
    ["running", "waiting_for_approval", "success", "limit_reached", "failed"].includes(value.status) &&
    typeof value.created_at === "string"
  );
}

function isPublicToolName(value) {
  return [
    "get_product_history",
    "get_machine_status",
    "search_documentation",
    "create_maintenance_ticket",
  ].includes(value);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOnlyKeys(value, allowedKeys) {
  return Object.keys(value).every((key) => allowedKeys.includes(key));
}

function isBoundedString(value, maxLength, requireContent = false) {
  return (
    typeof value === "string" &&
    value.length <= maxLength &&
    (!requireContent || value.length > 0)
  );
}

function isUuid(value) {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  );
}

function errorMessageFor(status, code, publicMessage) {
  if (code === "requested_data_unavailable") {
    return "The requested data is not available with the selected access level.";
  }
  const defaults = {
    403: "This request is not permitted by the server security policy.",
    404: "The requested run was not found.",
    422: "Check the troubleshooting request and submit it again.",
    500: "The agent run could not be completed. Try again later.",
    503: "A required local model or MCP service is unavailable.",
    409: "This run is no longer waiting for approval.",
  };
  return defaults[status] ?? publicMessage ?? "The request could not be completed.";
}
