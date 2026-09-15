import assert from "node:assert/strict";
import test from "node:test";

import { createTranscriptPdf } from "../../frontend/js/transcript-pdf.js";

test("creates a transcript-only PDF from visible pre-run API errors", () => {
  const pdf = text(createTranscriptPdf([{
    request: "S07",
    answer: null,
    error: {
      code: "requested_data_unavailable",
      message: "The requested data is not available with the selected access level.",
    },
  }]));

  assert.match(pdf, /%PDF-1\.4/);
  assert.match(pdf, /No persisted Investigation ID/);
  assert.match(pdf, /S07/);
  assert.match(pdf, /requested_data_unavailable/);
  assert.match(pdf, /selected access level/);
  assert.doesNotMatch(pdf, /RESTRICTED/);
});

test("creates a transcript-only PDF from the public transport failure", () => {
  const pdf = text(createTranscriptPdf([{
    request: "Investigate P4711.",
    answer: null,
    error: {
      code: "backend_unreachable",
      message: "The local agent API is not reachable. Start the FastAPI server and try again.",
    },
  }]));

  assert.match(pdf, /backend_unreachable/);
  assert.match(pdf, /local agent API is not reachable/);
});

test("does not place non-visible metadata into a transcript-only PDF", () => {
  const pdf = text(createTranscriptPdf([{
    request: "Visible request",
    answer: "Visible response",
    error: null,
    classification: "RESTRICTED",
    tool_calls: [{ tool: "get_machine_status" }],
  }]));

  assert.match(pdf, /Visible request/);
  assert.match(pdf, /Visible response/);
  assert.doesNotMatch(pdf, /RESTRICTED|get_machine_status/);
});

function text(bytes) {
  return String.fromCharCode(...bytes);
}
