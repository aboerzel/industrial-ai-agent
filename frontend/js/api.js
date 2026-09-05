const API_BASE_URL = "http://localhost:8000";

export class ApiClientError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

export async function createRun(message) {
  return request("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify({ message }),
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
    throw new ApiClientError(
      response.status,
      payload?.code ?? "request_failed",
      errorMessageFor(response.status, payload?.message),
    );
  }
  if (!isRunResponse(payload)) {
    throw new ApiClientError(
      response.status,
      "invalid_response",
      "The agent API returned an invalid run response.",
    );
  }
  return payload;
}

function isRunResponse(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.run_id === "string" &&
    ["running", "waiting_for_approval", "success", "limit_reached", "failed"].includes(value.status) &&
    (value.answer === null || typeof value.answer === "string") &&
    Array.isArray(value.tool_calls) &&
    value.tool_calls.every(
      (call) =>
        call !== null &&
        typeof call === "object" &&
        typeof call.tool === "string" &&
        call.arguments !== null &&
        typeof call.arguments === "object" &&
        !Array.isArray(call.arguments),
    ) &&
    (value.approval_request === null || typeof value.approval_request === "object")
  );
}

function errorMessageFor(status, publicMessage) {
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
