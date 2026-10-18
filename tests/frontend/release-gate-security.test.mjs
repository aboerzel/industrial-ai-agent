import assert from "node:assert/strict";
import test from "node:test";
import { classifyJourneyFailure } from "../../frontend/scripts/journey-execution.mjs";

test("security evidence takes precedence over a provider failure and a prior harness label", () => {
  const error = new Error("Protected document leaked");
  error.result_category = "HARNESS_ERROR";
  assert.equal(classifyJourneyFailure(error, { error_code: "llm_provider_unavailable" }), "SECURITY_DEFECT");
});
