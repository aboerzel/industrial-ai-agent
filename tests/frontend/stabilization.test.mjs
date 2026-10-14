import assert from "node:assert/strict";
import test from "node:test";
import { assertArtifactProvenance } from "../../frontend/scripts/manual-e2e-runner-core.mjs";
import { openDocument, invalidateSecurityContext } from "../../frontend/js/api.js";

const metadata = {
  run_id: "synthetic", git_head: "head", product_revision: "head", product_fingerprint: "source",
  harness_fingerprint: "harness", real_model_id: "local_quality", assignment_snapshot: [],
};

test("historical or mismatched E2E measurements cannot certify the current baseline", () => {
  assert.doesNotThrow(() => assertArtifactProvenance(metadata, metadata));
  for (const key of ["run_id", "git_head", "product_revision", "product_fingerprint", "harness_fingerprint", "real_model_id"]) {
    assert.throws(() => assertArtifactProvenance({ ...metadata, [key]: "obsolete" }, metadata));
  }
  assert.throws(() => assertArtifactProvenance(undefined, metadata));
  assert.throws(() => assertArtifactProvenance({ ...metadata, assignment_snapshot: [{ consumer_id: "agent", data_classification: "PUBLIC", model_id: "different" }] }, metadata));
});

test("active document contents lose their executable MIME type before Blob publication", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const types = [];
  globalThis.fetch = async () => new Response("<script>synthetic()</script>", { headers: { "Content-Type": "text/html" } });
  globalThis.window = { open: () => undefined, CustomEvent: class {}, dispatchEvent: () => true };
  URL.createObjectURL = (blob) => { types.push(blob.type); return "blob:synthetic"; };
  URL.revokeObjectURL = () => undefined;
  try {
    await openDocument("synthetic", "CONFIDENTIAL");
    assert.deepEqual(types, ["application/octet-stream"]);
    invalidateSecurityContext();
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  }
});
