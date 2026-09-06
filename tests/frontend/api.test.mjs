import assert from "node:assert/strict";
import test from "node:test";

import { ApiClientError, createRun, getRun } from "../../frontend/js/api.js";

const RUN_ID = "0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8";

test("accepts OpenAPI-valid run responses with omitted default fields", async () => {
  const result = await requestRun({
    run_id: RUN_ID,
    status: "success",
    data_classification: "PUBLIC",
  });

  assert.deepEqual(result, {
    run_id: RUN_ID,
    status: "success",
    data_classification: "PUBLIC",
    answer: null,
    tool_calls: [],
    approval_request: null,
  });
});

test("renders every public terminal and approval lifecycle state", async (t) => {
  for (const payload of [
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
        model_profile: "local_quality",
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
      error.message === "The requested data is not available with the selected access level.",
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
      error.message === "The requested run was not found.",
  );
});

async function requestRun(payload) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  try {
    return await createRun("Investigate P4711.");
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function requestError(path, payload, request) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.equal(url, `http://localhost:8000${path}`);
    return new Response(JSON.stringify(payload), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    return await request();
  } finally {
    globalThis.fetch = originalFetch;
  }
}
