import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiClientError,
  createRun,
  downloadInvestigationPdf,
  getRun,
  getInvestigation,
  saveModelAssignment,
} from "../../frontend/js/api.js";

const RUN_ID = "0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8";

test("accepts OpenAPI-valid run responses with omitted default fields", async () => {
  const result = await requestRun({
    run_id: RUN_ID,
    status: "success",
    data_classification: "PUBLIC",
  });

  assert.deepEqual(result, {
    run_id: RUN_ID,
    investigation_id: RUN_ID,
    investigation_sequence: 1,
    status: "success",
    data_classification: "PUBLIC",
    answer: null,
    investigation_steps: [],
    next_steps: [],
    tool_calls: [],
    approval_request: null,
  });
});

test("rejects a run response without required investigation identity fields", async () => {
  await assert.rejects(
    requestRawRun({
      run_id: RUN_ID,
      status: "success",
      data_classification: "PUBLIC",
    }),
    (error) => error instanceof ApiClientError && error.code === "invalid_response",
  );
});

test("renders every public terminal and approval lifecycle state", async (t) => {
  for (const payload of [
    {
      run_id: RUN_ID,
      status: "running",
      data_classification: "CONFIDENTIAL",
      answer: null,
      tool_calls: [],
      approval_request: null,
    },
    {
      run_id: RUN_ID,
      status: "success",
      data_classification: "CONFIDENTIAL",
      answer: "P4711 failed at S04.",
      tool_calls: [
        { tool: "get_product_history", arguments: { product_id: "P4711" } },
      ],
      approval_request: null,
    },
    {
      run_id: RUN_ID,
      status: "waiting_for_approval",
      data_classification: "CONFIDENTIAL",
      answer: null,
      tool_calls: [],
      approval_request: {
        action: "create_maintenance_ticket",
        summary: "Inspect S04.",
        arguments: { station_id: "S04" },
        classification: "CONFIDENTIAL",
        model_id: "local_quality",
        status: "waiting_for_approval",
        created_at: "2026-09-05T10:14:59.834855+00:00",
      },
    },
    { run_id: RUN_ID, status: "failed", data_classification: "CONFIDENTIAL", answer: null, tool_calls: [], approval_request: null },
    { run_id: RUN_ID, status: "limit_reached", data_classification: "CONFIDENTIAL", answer: null, tool_calls: [], approval_request: null },
  ]) {
    await t.test(payload.status, async () => {
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("accepts the bounded S04 recovery approval response contract", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "waiting_for_approval",
    data_classification: "CONFIDENTIAL",
    answer: null,
    tool_calls: [],
    approval_request: {
      action: "execute_reference_calibration",
      summary: "Reference calibration is ready for approval.",
      arguments: {
        station_id: "S04",
        device_id: "POSITION-ENC-02",
        operation_type: "reference_calibration",
      },
      classification: "CONFIDENTIAL",
      model_id: "nvidia_quality",
      status: "waiting_for_approval",
      created_at: "2026-09-11T11:53:47+00:00",
    },
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts bounded hardware recovery tool calls in the run result contract", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "success",
    data_classification: "CONFIDENTIAL",
    answer: "Recovery completed.",
    tool_calls: [
      { tool: "get_position_reference_status", arguments: { station_id: "S04" } },
      { tool: "prepare_reference_calibration", arguments: { station_id: "S04" } },
      { tool: "execute_reference_calibration", arguments: { station_id: "S04" } },
    ],
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts the explicit no-action recovery outcome", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "success",
    data_classification: "CONFIDENTIAL",
    answer: "No recovery is required.",
    recovery_outcome: "NOT_REQUIRED",
    tool_calls: [
      { tool: "get_position_reference_status", arguments: { station_id: "S04" } },
    ],
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts a bounded incomplete S04 recovery result as failed", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "failed",
    data_classification: "CONFIDENTIAL",
    answer: "The requested recovery was not completed.",
    tool_calls: [
      { tool: "get_position_reference_status", arguments: { station_id: "S04" } },
    ],
    error: {
      code: "recovery_incomplete",
      message: "The requested recovery was not completed.",
    },
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts the persisted QUALITY-09 operational failure response", async () => {
  const payload = {
    run_id: RUN_ID,
    investigation_id: RUN_ID,
    investigation_sequence: 1,
    status: "failed",
    data_classification: "CONFIDENTIAL",
    answer: null,
    recovery_outcome: null,
    investigation_steps: [],
    next_steps: [],
    identifiers: [],
    documents: [],
    tool_calls: [],
    error: {
      code: "tool_execution_failed",
      message: "The requested investigation step could not be completed.",
      failure_origin: "TOOL_EXECUTION",
    },
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("rejects an operational failure with an unknown failure origin", async () => {
  await assert.rejects(
    requestRun({
      run_id: RUN_ID,
      status: "failed",
      data_classification: "CONFIDENTIAL",
      error: {
        code: "tool_execution_failed",
        message: "The requested investigation step could not be completed.",
        failure_origin: "UNTRUSTED_ORIGIN",
      },
    }),
    (error) => error instanceof ApiClientError && error.code === "invalid_response",
  );
});

test("accepts every current normalized operational failure origin", async (t) => {
  const failures = [
    ["llm_rate_limit", "PROVIDER_RATE_LIMIT"],
    ["llm_provider_unavailable", "PROVIDER_CONNECTION"],
    ["llm_provider_request_invalid", "PROVIDER_REQUEST"],
    ["model_capability_mismatch", "CAPABILITY_VALIDATION"],
    ["model_not_configured", "MODEL_SELECTION"],
    ["model_runtime_unavailable", "MODEL_AVAILABILITY"],
    ["model_egress_denied", "SECURITY_POLICY"],
    ["mcp_service_unavailable", "MCP"],
    ["tool_execution_failed", "TOOL_EXECUTION"],
    ["evidence_requirements_unsatisfied", "ORCHESTRATION"],
    ["evidence_source_unavailable", "ORCHESTRATION"],
    ["model_output_invalid", "MODEL_OUTPUT_VALIDATION"],
    ["persistence_failure", "PERSISTENCE"],
  ];

  for (const [code, failureOrigin] of failures) {
    await t.test(code, async () => {
      const payload = {
        status: "failed",
        data_classification: "CONFIDENTIAL",
        error: {
          code,
          message: "The request could not be completed.",
          failure_origin: failureOrigin,
        },
      };
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("accepts nullable optional ApiErrorResponse fields", async () => {
  const payload = {
    status: "failed",
    data_classification: "CONFIDENTIAL",
    error: {
      code: "tool_execution_failed",
      message: "The requested investigation step could not be completed.",
      investigation_id: null,
      failure_origin: null,
    },
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts a successful documentation response with optional empty fields", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "success",
    data_classification: "CONFIDENTIAL",
    answer: "QUALITY-09 documentation is available.",
    investigation_steps: [],
    next_steps: [],
    identifiers: [],
    documents: [{
      document_id: "DOC-QUALITY-09",
      title: "QUALITY-09 procedure",
      format: "markdown",
    }],
    tool_calls: [{ tool: "search_documentation", arguments: { query: "QUALITY-09" } }],
    error: null,
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts every current recovery outcome", async (t) => {
  for (const recoveryOutcome of ["SUCCEEDED", "NOT_REQUIRED", "FAILED", "BLOCKED"]) {
    await t.test(recoveryOutcome, async () => {
      const payload = {
        status: "success",
        data_classification: "CONFIDENTIAL",
        recovery_outcome: recoveryOutcome,
      };
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("accepts Pydantic-valid non-sequential investigation step numbers", async () => {
  const payload = {
    status: "success",
    data_classification: "CONFIDENTIAL",
    investigation_steps: [{
      step: 4,
      action: "search_documentation",
      finding: "Documentation was retrieved.",
    }],
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts every current public tool enum value", async (t) => {
  const tools = [
    "list_stations",
    "get_station_overview",
    "list_products",
    "get_product_overview",
    "get_product_history",
    "get_machine_status",
    "get_position_reference_status",
    "get_maintenance_ticket",
    "prepare_reference_calibration",
    "search_documentation",
    "create_maintenance_ticket",
    "execute_reference_calibration",
  ];

  for (const tool of tools) {
    await t.test(tool, async () => {
      const payload = {
        status: "success",
        data_classification: "CONFIDENTIAL",
        tool_calls: [{ tool, arguments: {} }],
      };
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("accepts every current identifier type enum value", async (t) => {
  for (const type of ["error_code", "station", "product", "maintenance_ticket"]) {
    await t.test(type, async () => {
      const payload = {
        status: "success",
        data_classification: "CONFIDENTIAL",
        identifiers: [{ value: "REF-01", type }],
      };
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("accepts a current investigation response with optional turn defaults", async () => {
  const payload = {
    investigation_id: RUN_ID,
    created_at: null,
    run_count: 1,
    tool_call_count: 0,
    status: "failed",
    turns: [{
      run_id: RUN_ID,
      sequence: 1,
      status: "failed",
      data_classification: "CONFIDENTIAL",
      response_language: "DE",
      request: "QUALITY-09",
      error: {
        code: "tool_execution_failed",
        message: "The request could not be completed.",
        failure_origin: "TOOL_EXECUTION",
      },
    }],
  };

  assert.deepEqual(await requestInvestigation(payload), payload);
});

test("accepts discovery tool calls in the existing run result contract", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "success",
    data_classification: "INTERNAL",
    answer: "Visible stations are S01, S02, S03, and S05.",
    tool_calls: [{ tool: "list_stations", arguments: {} }],
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("accepts bounded maintenance-ticket retrieval in the run result contract", async () => {
  const payload = {
    run_id: RUN_ID,
    status: "success",
    data_classification: "RESTRICTED",
    answer: "Das Ticket MT-6EA0DEF5515A ist offen.",
    tool_calls: [
      { tool: "get_maintenance_ticket", arguments: { ticket_id: "MT-6EA0DEF5515A" } },
    ],
    approval_request: null,
  };

  assert.deepEqual(await requestRun(payload), payload);
});

test("rejects malformed approval data instead of accepting an arbitrary object", async () => {
  await assert.rejects(
    requestRun({
      run_id: RUN_ID,
      status: "waiting_for_approval",
      data_classification: "CONFIDENTIAL",
      approval_request: {},
    }),
    (error) =>
      error instanceof ApiClientError && error.code === "invalid_response",
  );
});

test("renders neutral access unavailability separately from a missing run", async () => {
  await assert.rejects(
    requestError(
      "/api/v1/runs",
      { code: "requested_data_unavailable", message: "The requested data is unavailable." },
      createRun,
    ),
    (error) =>
      error instanceof ApiClientError &&
      error.code === "requested_data_unavailable" &&
      error.investigationId === null &&
      error.message === "The requested data is unavailable.",
  );
  await assert.rejects(
    requestError(
      "/api/v1/runs/00000000-0000-4000-8000-000000000000",
      { code: "run_not_found", message: "The requested run does not exist." },
      () => getRun("00000000-0000-4000-8000-000000000000"),
    ),
    (error) =>
      error instanceof ApiClientError &&
      error.code === "run_not_found" &&
      error.message === "The requested run does not exist.",
  );
});

test("retains a persisted investigation identity from a sanitized HTTP 500", async () => {
  await assert.rejects(
    requestError(
      "/api/v1/runs",
      {
        code: "internal_error",
        message: "The agent run could not be completed.",
        investigation_id: RUN_ID,
      },
      createRun,
      500,
    ),
    (error) =>
      error instanceof ApiClientError &&
      error.status === 500 &&
      error.code === "internal_error" &&
      error.investigationId === RUN_ID &&
      error.message === "The agent run could not be completed.",
  );
});

test("accepts a current HTTP error envelope with failure origin", async () => {
  await assert.rejects(
    requestError(
      "/api/v1/runs",
      {
        code: "llm_rate_limit",
        message: "The language model is temporarily unavailable.",
        failure_origin: "PROVIDER_RATE_LIMIT",
      },
      createRun,
      503,
    ),
    (error) =>
      error instanceof ApiClientError &&
      error.code === "llm_rate_limit" &&
      error.message === "The language model is temporarily unavailable.",
  );
});

test("uses the existing server PDF route for persisted investigations", () => {
  const originalWindow = globalThis.window;
  let assignedUrl = null;
  globalThis.window = { location: { assign: (url) => { assignedUrl = url; } } };
  try {
    downloadInvestigationPdf(RUN_ID, "CONFIDENTIAL");
  } finally {
    globalThis.window = originalWindow;
  }

  assert.equal(
    assignedUrl,
    `http://localhost:8000/api/v1/investigations/${RUN_ID}/pdf?user_clearance=CONFIDENTIAL`,
  );
});

test("persists model configuration with stable model_id values", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "http://localhost:8000/api/v1/model-assignments");
    assert.equal(options.method, "PUT");
    assert.deepEqual(JSON.parse(options.body), {
      consumer_id: "agent",
      data_classification: "RESTRICTED",
      model_id: "local_quality",
      selection_mode: "MANUAL",
      selection_policy: null,
    });
    return new Response(JSON.stringify({
      consumer_id: "agent", data_classification: "RESTRICTED", model_id: "local_quality",
      selection_mode: "MANUAL", selection_policy: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const saved = await saveModelAssignment("agent", "RESTRICTED", "local_quality");
    assert.equal(saved.model_id, "local_quality");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

async function requestRun(payload) {
  if (payload.run_id === undefined) payload.run_id = RUN_ID;
  if (payload.investigation_id === undefined) payload.investigation_id = RUN_ID;
  if (payload.investigation_sequence === undefined) payload.investigation_sequence = 1;
  if (payload.answer === undefined) payload.answer = null;
  if (payload.investigation_steps === undefined) payload.investigation_steps = [];
  if (payload.next_steps === undefined) payload.next_steps = [];
  if (payload.tool_calls === undefined) payload.tool_calls = [];
  if (payload.approval_request === undefined) payload.approval_request = null;
  return requestPayload(payload);
}

async function requestRawRun(payload) {
  return requestPayload(payload);
}

async function requestInvestigation(payload) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  try {
    return await getInvestigation(RUN_ID, "CONFIDENTIAL");
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function requestPayload(payload) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  try {
    const result = await createRun("Investigate P4711.");
    return result;
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function requestError(path, payload, request, status = 404) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.equal(url, `http://localhost:8000${path}`);
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    return await request();
  } finally {
    globalThis.fetch = originalFetch;
  }
}
