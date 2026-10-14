import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiClientError,
  downloadDocument,
  invalidateSecurityContext,
  SecurityContextChangedError,
} from "../../frontend/js/api.js";

const CONTENT = "synthetic document bytes";

function response(filename) {
  return new Response(CONTENT, {
    headers: {
      "Content-Type": "application/pdf",
      ...(filename ? { "Content-Disposition": `attachment; filename="${filename}"` } : {}),
    },
  });
}

function harness(t, fetchResponse, oldFilename = "stale-name.pdf") {
  const original = {
    fetch: globalThis.fetch,
    document: globalThis.document,
    create: URL.createObjectURL,
    revoke: URL.revokeObjectURL,
    setTimeout: globalThis.setTimeout,
  };
  invalidateSecurityContext();
  const calls = { blobs: [], downloads: [], revoked: [], timers: [], requests: [], removed: 0 };
  globalThis.fetch = async (url, options) => {
    calls.requests.push({ url, options });
    return fetchResponse();
  };
  globalThis.document = {
    // Even a legacy filename on the DOM document must not override API metadata.
    filename: oldFilename,
    body: { append() {} },
    createElement: () => ({
      click() { calls.downloads.push({ filename: this.download, href: this.href }); },
      remove() { calls.removed += 1; },
    }),
  };
  URL.createObjectURL = (blob) => {
    calls.blobs.push(blob);
    return "blob:synthetic-document";
  };
  URL.revokeObjectURL = (url) => calls.revoked.push(url);
  globalThis.setTimeout = (callback, delay) => {
    calls.timers.push({ callback, delay });
    return { unref() {} };
  };
  t.after(() => {
    invalidateSecurityContext();
    globalThis.fetch = original.fetch;
    globalThis.document = original.document;
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
    globalThis.setTimeout = original.setTimeout;
  });
  return calls;
}

for (const [oldFilename, apiFilename] of [
  ["stale-name.pdf", "correct-name.pdf"],
  ["same-name.pdf", "same-name.pdf"],
  ["document.txt", "document.pdf"],
  ["stale-name.pdf", "Service Bericht 01.pdf"],
  ["stale-name.pdf", "Prüfbericht 01.pdf"],
]) {
  test(`document download uses API filename ${apiFilename} instead of ${oldFilename}`, async (t) => {
    const reference = { document_id: "synthetic", filename: oldFilename };
    const calls = harness(t, () => response(apiFilename), reference.filename);
    await downloadDocument(reference.document_id);
    assert.deepEqual(calls.downloads, [{ filename: apiFilename, href: "blob:synthetic-document" }]);
    assert.equal(await calls.blobs[0].text(), CONTENT);
    assert.equal(calls.blobs[0].type, "application/pdf");
    assert.equal(calls.requests[0].url, "/api/v1/documents/synthetic/download");
    assert.equal(calls.requests[0].options.cache, "no-store");
    assert.equal(calls.requests[0].options.headers.Authorization, undefined);
    assert.equal(calls.removed, 1);
  });
}

test("document download retains the existing fallback when API filename is absent", async (t) => {
  const calls = harness(t, () => response(null));
  await downloadDocument("synthetic");
  assert.equal(calls.downloads[0].filename, "document");
});

for (const status of [401, 403, 404, 500]) {
  test(`document download denial/error ${status} never publishes a Blob or filename`, async (t) => {
    const calls = harness(t, () => new Response(JSON.stringify({
      code: "document_not_found", message: "The requested resource does not exist.",
    }), { status, headers: { "Content-Type": "application/json" } }));
    await assert.rejects(downloadDocument("synthetic"), (error) =>
      error instanceof ApiClientError && error.status === status);
    assert.deepEqual(calls.blobs, []);
    assert.deepEqual(calls.downloads, []);
    assert.deepEqual(calls.timers, []);
  });
}

test("document download rejects a stale response even when fetch ignores abort", async (t) => {
  let release;
  const calls = harness(t, () => new Promise((resolve) => { release = resolve; }));
  const pending = downloadDocument("synthetic");
  const rejected = assert.rejects(pending, SecurityContextChangedError);
  invalidateSecurityContext();
  assert.equal(calls.requests[0].options.signal.aborted, true);
  release(response("protected.pdf"));
  await rejected;
  assert.deepEqual(calls.blobs, []);
  assert.deepEqual(calls.downloads, []);
});

test("document download rejects a body completed after a security context change", async (t) => {
  let release;
  let started;
  const bodyStarted = new Promise((resolve) => { started = resolve; });
  const calls = harness(t, () => ({
    ok: true, status: 200, headers: new Headers({ "Content-Disposition": 'attachment; filename="protected.pdf"' }),
    blob: () => new Promise((resolve) => { release = resolve; started(); }),
  }));
  const pending = downloadDocument("synthetic");
  const rejected = assert.rejects(pending, SecurityContextChangedError);
  await bodyStarted;
  invalidateSecurityContext();
  release(new Blob([CONTENT], { type: "application/pdf" }));
  await rejected;
  assert.deepEqual(calls.blobs, []);
  assert.deepEqual(calls.downloads, []);
});

test("successful document download revokes its URL at the existing cleanup deadline", async (t) => {
  const calls = harness(t, () => response("document.pdf"));
  await downloadDocument("synthetic");
  assert.equal(calls.timers.length, 1);
  assert.equal(calls.timers[0].delay, 60_000);
  calls.timers[0].callback();
  invalidateSecurityContext();
  assert.deepEqual(calls.revoked, ["blob:synthetic-document"]);
});

test("security invalidation revokes a downloaded URL without duplicate timer cleanup", async (t) => {
  const calls = harness(t, () => response("document.pdf"));
  await downloadDocument("synthetic");
  invalidateSecurityContext();
  calls.timers[0].callback();
  assert.deepEqual(calls.revoked, ["blob:synthetic-document"]);
});
