const API_BASE_URL = "http://localhost:8000";

export class ApiClientError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

export async function createRun(message, userClearance, investigationId = null) {
  return request("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify({
      message,
      user_clearance: userClearance,
      ...(investigationId ? { investigation_id: investigationId } : {}),
    }),
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

export async function getInvestigation(investigationId, userClearance) {
  const suffix = new URLSearchParams({ user_clearance: userClearance });
  return request(`/api/v1/investigations/${encodeURIComponent(investigationId)}?${suffix}`,
    {}, isInvestigationResponse);
}

export function downloadInvestigationPdf(investigationId, userClearance) {
  const suffix = new URLSearchParams({ user_clearance: userClearance });
  window.location.assign(
    `${API_BASE_URL}/api/v1/investigations/${encodeURIComponent(investigationId)}/pdf?${suffix}`,
  );
}

async function request(path, options = {}, validator = isRunResponse) {
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
  if (!validator(payload)) {
    throw new ApiClientError(
      response.status,
      "invalid_response",
      "The agent API returned an invalid run response.",
    );
  }
  return validator === isRunResponse ? {
    ...payload,
    investigation_id: payload.investigation_id ?? payload.run_id,
    investigation_sequence: payload.investigation_sequence ?? 1,
    answer: payload.answer ?? null,
    investigation_steps: payload.investigation_steps ?? [],
    next_steps: payload.next_steps ?? [],
    tool_calls: payload.tool_calls ?? [],
    approval_request: payload.approval_request ?? null,
  } : payload;
}

function isRunResponse(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["run_id", "investigation_id", "investigation_sequence", "status", "data_classification", "answer", "investigation_steps", "next_steps", "tool_calls", "approval_request"]) &&
    isUuid(value.run_id) &&
    (value.investigation_id === undefined || isUuid(value.investigation_id)) &&
    (value.investigation_sequence === undefined || (Number.isInteger(value.investigation_sequence) && value.investigation_sequence > 0)) &&
    ["running", "waiting_for_approval", "success", "limit_reached", "failed"].includes(value.status) &&
    ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].includes(value.data_classification) &&
    (value.answer === undefined || value.answer === null || isBoundedString(value.answer, 8_000)) &&
    (value.investigation_steps === undefined || isInvestigationSteps(value.investigation_steps)) &&
    (value.next_steps === undefined || isNextSteps(value.next_steps)) &&
    (value.tool_calls === undefined ||
      (Array.isArray(value.tool_calls) && value.tool_calls.every(isToolCall))) &&
    (value.approval_request === undefined ||
      value.approval_request === null ||
      isApprovalRequest(value.approval_request))
  );
}

function isInvestigationResponse(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["investigation_id", "created_at", "run_count", "tool_call_count", "status", "turns"]) &&
    isUuid(value.investigation_id) &&
    Number.isInteger(value.run_count) && value.run_count >= 0 &&
    Number.isInteger(value.tool_call_count) && value.tool_call_count >= 0 &&
    typeof value.status === "string" &&
    Array.isArray(value.turns) && value.turns.every(isInvestigationTurn)
  );
}

function isInvestigationTurn(value) {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["run_id", "sequence", "status", "data_classification", "response_language", "request", "answer", "investigation_steps", "next_steps", "tool_calls", "created_at", "updated_at", "approval_request"]) &&
    isUuid(value.run_id) && Number.isInteger(value.sequence) && value.sequence > 0 &&
    ["running", "waiting_for_approval", "success", "limit_reached", "failed"].includes(value.status) &&
    ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].includes(value.data_classification) &&
    ["DE", "EN"].includes(value.response_language) &&
    isBoundedString(value.request, 4_000) &&
    (value.answer === null || value.answer === undefined || isBoundedString(value.answer, 8_000)) &&
    (value.investigation_steps === undefined || isInvestigationSteps(value.investigation_steps)) &&
    (value.next_steps === undefined || isNextSteps(value.next_steps)) &&
    Array.isArray(value.tool_calls) && value.tool_calls.every(isToolCall) &&
    (value.approval_request === null || value.approval_request === undefined || isApprovalRequest(value.approval_request))
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

function isNextSteps(value) {
  return (
    Array.isArray(value) &&
    value.length <= 5 &&
    value.every((step) => isBoundedString(step, 500, true))
  );
}

function isInvestigationSteps(value) {
  return (
    Array.isArray(value) &&
    value.length <= 4 &&
    value.every((step, index) =>
      isRecord(step) &&
      hasOnlyKeys(step, ["step", "action", "finding"]) &&
      step.step === index + 1 &&
      isPublicToolName(step.action) &&
      isBoundedString(step.finding, 1_000, true),
    )
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
    "list_stations",
    "get_station_overview",
    "list_products",
    "get_product_overview",
    "get_product_history",
    "get_machine_status",
    "search_documentation",
    "create_maintenance_ticket",
    "get_maintenance_ticket",
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
