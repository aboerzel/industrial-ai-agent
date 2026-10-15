import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { demoAuthFetch } from "./fixtures/demo-auth-fake.mjs";
import { getSecurityContextGeneration, invalidateSecurityContext, SecurityContextChangedError } from "../../frontend/js/api.js?v=20261013-2";
import { downloadTranscriptPdf } from "../../frontend/js/transcript-pdf.js";
import { mountDemoAuth } from "../../frontend/js/demo-auth.js";

const transcript = [{ request: "FC04-CONFIDENTIAL-MARKER-UNIT", error: { code: "backend_unreachable", message: "Synthetic transport error" } }];

function harness(t) {
  const original = { window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch, create: URL.createObjectURL, revoke: URL.revokeObjectURL, timeout: globalThis.setTimeout };
  globalThis.window = undefined;
  invalidateSecurityContext();
  const calls = { created: [], revoked: [], downloads: [], timers: [], removed: 0 };
  URL.createObjectURL = blob => {
    const url = `blob:fc04-${calls.created.length + 1}`;
    calls.created.push({ url, blob });
    calls.onCreate?.();
    return url;
  };
  URL.revokeObjectURL = url => calls.revoked.push(url);
  globalThis.setTimeout = (callback, delay) => { calls.timers.push({ callback, delay }); return { unref() {} }; };
  globalThis.document = { body: { append() { calls.onAppend?.(); } }, createElement: () => ({ click() { calls.downloads.push({ url: this.href, filename: this.download }); }, remove() { calls.removed++; } }) };
  t.after(() => {
    invalidateSecurityContext();
    calls.dom?.window.close();
    globalThis.window = original.window;
    globalThis.document = original.document;
    globalThis.fetch = original.fetch;
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
    globalThis.setTimeout = original.timeout;
  });
  return calls;
}

test("FC04-U1 transcript PDF registers with the existing protected URL owner", async t => {
  const calls = harness(t);
  downloadTranscriptPdf(transcript);
  assert.equal(calls.created[0].blob.type, "application/pdf");
  assert.match(await calls.created[0].blob.text(), /FC04-CONFIDENTIAL-MARKER-UNIT/);
  assert.deepEqual(calls.downloads, [{ url: "blob:fc04-1", filename: "investigation-transcript.pdf" }]);
  assert.deepEqual(calls.revoked, []);
  invalidateSecurityContext();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04-U2 identity purge immediately revokes every owned transcript URL", t => {
  const calls = harness(t);
  downloadTranscriptPdf(transcript);
  downloadTranscriptPdf(transcript);
  invalidateSecurityContext("identity");
  assert.deepEqual(calls.revoked, ["blob:fc04-1", "blob:fc04-2"]);
});

test("FC04-U3 duplicate purge and late delayed cleanup never revoke twice", t => {
  const calls = harness(t);
  downloadTranscriptPdf(transcript);
  invalidateSecurityContext("identity");
  invalidateSecurityContext("identity");
  calls.timers.forEach(timer => { timer.callback(); timer.callback(); });
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04-U4 same-context download retains the existing 60-second cleanup", t => {
  const calls = harness(t);
  downloadTranscriptPdf(transcript);
  assert.deepEqual(calls.revoked, []);
  assert.equal(calls.timers[0].delay, 60_000);
  calls.timers[0].callback();
  invalidateSecurityContext();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04-U5 deferred old-generation completion cannot create or publish a URL", async t => {
  const calls = harness(t);
  const generation = getSecurityContextGeneration();
  let release;
  const pending = new Promise(resolve => { release = resolve; }).then(() => downloadTranscriptPdf(transcript, generation));
  const rejection = assert.rejects(pending, SecurityContextChangedError);
  invalidateSecurityContext("identity");
  release();
  await rejection;
  assert.deepEqual(calls.created, []);
  assert.deepEqual(calls.downloads, []);
});

test("FC04-U6 new generation owns only its new URLs and leaves unrelated URLs alone", t => {
  const calls = harness(t);
  downloadTranscriptPdf(transcript);
  invalidateSecurityContext();
  downloadTranscriptPdf(transcript);
  calls.timers[0].callback();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
  invalidateSecurityContext();
  calls.timers[1].callback();
  assert.deepEqual(calls.revoked, ["blob:fc04-1", "blob:fc04-2"]);
  assert.equal(calls.revoked.includes("blob:unrelated-ui-resource"), false);
});

test("FC04-U7 logout purges transcript URLs without waiting for a response", async t => {
  const calls = harness(t);
  const auth = await authHarness(calls);
  downloadTranscriptPdf(transcript);
  calls.dom.window.document.querySelector("#logout-button").click();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
  await settle();
  assert.equal(calls.dom.window.document.querySelector("#account-clearance").textContent, "");
  assert.ok(auth);
});

test("FC04-U8 cross-tab pending invalidation invokes the local protected URL purge", async t => {
  const calls = harness(t);
  await authHarness(calls);
  downloadTranscriptPdf(transcript);
  calls.channel.onmessage({ data: { type: "SESSION_INVALIDATED", operation_id: "synthetic-fc04-peer", phase: "pending" } });
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04-U9 failed receiver identity refresh cannot undo immediate URL revocation", async t => {
  const calls = harness(t);
  await authHarness(calls);
  downloadTranscriptPdf(transcript);
  const normal = globalThis.fetch;
  globalThis.fetch = (url, options) => String(url).endsWith("/auth/me") ? Promise.reject(new TypeError("Synthetic identity failure")) : normal(url, options);
  calls.channel.onmessage({ data: { type: "SESSION_INVALIDATED", operation_id: "synthetic-fc04-failed-refresh", phase: "settled" } });
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
  await settle();
  assert.equal(calls.dom.window.document.querySelector("#account-clearance").textContent, "");
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04-U10 language-only preference change preserves the resource owner", async t => {
  const calls = harness(t);
  await authHarness(calls);
  downloadTranscriptPdf(transcript);
  const generation = getSecurityContextGeneration();
  const language = calls.dom.window.document.querySelector("#response-language");
  language.value = "DE";
  language.dispatchEvent(new calls.dom.window.Event("change"));
  assert.equal(getSecurityContextGeneration(), generation);
  assert.deepEqual(calls.revoked, []);
});

test("FC04 publication race during URL creation revokes before returning ownership", t => {
  const calls = harness(t);
  calls.onCreate = () => invalidateSecurityContext("identity");
  assert.throws(() => downloadTranscriptPdf(transcript), SecurityContextChangedError);
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
  assert.deepEqual(calls.downloads, []);
  invalidateSecurityContext();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

test("FC04 purge after registration but before click suppresses publication", t => {
  const calls = harness(t);
  calls.onAppend = () => invalidateSecurityContext("identity");
  downloadTranscriptPdf(transcript);
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
  assert.deepEqual(calls.downloads, []);
  calls.timers[0].callback();
  assert.deepEqual(calls.revoked, ["blob:fc04-1"]);
});

async function settle() {
  for (let index = 0; index < 12; index++) await new Promise(resolve => setImmediate(resolve));
}

async function authHarness(calls) {
  const dom = new JSDOM(await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8"), { url: "http://localhost:8080" });
  calls.dom = dom;
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  dom.window.HTMLAnchorElement.prototype.click = function () { calls.downloads.push({ url: this.href, filename: this.download }); };
  dom.window.BroadcastChannel = class {
    constructor() { calls.channel = this; }
    postMessage() {}
    close() {}
  };
  globalThis.fetch = demoAuthFetch(() => { throw new Error("Unexpected fixture request"); }, "demo-confidential");
  const auth = mountDemoAuth({ onChanged() {}, onError() {} });
  await auth.initialize();
  return auth;
}
