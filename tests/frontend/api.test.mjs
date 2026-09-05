import assert from "node:assert/strict";
import test from "node:test";

import { ApiClientError, createRun } from "../../frontend/js/api.js";

const RUN_ID = "0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8";

test("accepts OpenAPI-valid run responses with omitted default fields", async () => {
  const result = await requestRun({ run_id: RUN_ID, status: "success" });

  assert.deepEqual(result, {
    run_id: RUN_ID,
    status: "success",
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
      answer: "P4711 failed at S04.",
      tool_calls: [
        { tool: "get_product_history", arguments: { product_id: "P4711" } },
      ],
      approval_request: null,
    },
    {
      run_id: RUN_ID,
      status: "waiting_for_approval",
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
    { run_id: RUN_ID, status: "failed", answer: null, tool_calls: [], approval_request: null },
    { run_id: RUN_ID, status: "limit_reached", answer: null, tool_calls: [], approval_request: null },
  ]) {
    await t.test(payload.status, async () => {
      assert.deepEqual(await requestRun(payload), payload);
    });
  }
});

test("rejects malformed approval data instead of accepting an arbitrary object", async () => {
  await assert.rejects(
    requestRun({
      run_id: RUN_ID,
      status: "waiting_for_approval",
      approval_request: {},
    }),
    (error) =>
      error instanceof ApiClientError && error.code === "invalid_response",
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
