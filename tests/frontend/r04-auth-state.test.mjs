import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";
import { demoAuthFetch } from "./fixtures/demo-auth-fake.mjs";

const ID = "4189aa79-1d5e-43b5-933b-f45e3b74c33d";
const G = "c536e99a-486e-4b28-950a-1c0e4bd6e912";
const MARKER = "SYNTHETIC CONFIDENTIAL R04 CONTENT";
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const identity = username => ({ username, clearance: username.split("-")[1].toUpperCase(), roles: [] });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
async function settle() { for (let i = 0; i < 10; i++) await new Promise(r => setTimeout(r, 0)); }

async function load(t, hook = async (_path, _options, original) => original()) {
  const dom = new JSDOM(await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8"), { url: "http://localhost:8080" });
  const { window } = dom;
  const { document } = window;
  Object.assign(globalThis, { window, document });
  window.sessionStorage.setItem("industrial-ai-agent.active-investigation", JSON.stringify({ investigationId: ID, username: "demo-confidential", responseLanguage: "DE" }));
  const turn = {
    run_id: ID, sequence: 1, status: "waiting_for_approval", data_classification: "CONFIDENTIAL",
    response_language: "DE", request: MARKER, answer: MARKER, tool_calls: [],
    next_steps: ["Investigate S04."], identifiers: [{ type: "station", value: "S04" }],
    documents: [{ document_id: "CONFIDENTIAL", title: MARKER, format: "text" }],
    approval_request: { approval_execution_id: G, action: "create_maintenance_ticket", summary: MARKER,
      arguments: { station_id: "S04" }, classification: "CONFIDENTIAL", model_id: "local_quality",
      status: "waiting_for_approval", created_at: "2026-10-15T10:00:00Z" },
  };
  const trace = [];
  const channels = [];
  window.BroadcastChannel = class {
    constructor(name) { this.name = name; channels.push(this); }
    postMessage(data) { assert.equal(this.closed, undefined); trace.push({ message: data }); }
    deliver(data) { if (!this.closed) this.onmessage({ data }); }
    close() { this.closed = true; }
  };
  const originalFetch = globalThis.fetch;
  const real = demoAuthFetch(url => {
    assert.equal(url, `/api/v1/investigations/${ID}`);
    return json({ investigation_id: ID, run_count: 1, tool_call_count: 0, status: "waiting_for_approval", turns: [turn] });
  }, "demo-confidential");
  globalThis.fetch = (url, options = {}) => {
    const path = String(url).split("/").at(-1);
    trace.push({ path });
    return hook(path, options, () => real(url, options));
  };
  await import(`../../frontend/js/app.js?r04=${Math.random()}`);
  await settle();
  assert.ok(document.querySelector("#conversation-history").textContent.includes(MARKER));
  assert.ok(document.querySelector(".approval-card"));
  t.after(() => { globalThis.fetch = originalFetch; dom.window.close(); });
  return { window, document, trace, channels, channel: channels[0], click(username) { document.querySelector(`[data-demo-username="${username}"]`).click(); } };
}

function purged({ document, window }) {
  assert.ok(!document.querySelector("#conversation-history").textContent.includes(MARKER));
  assert.equal(document.querySelector(".approval-card"), null);
  assert.equal(document.querySelector(".reference-popover"), null);
  assert.equal(document.querySelector("#export-pdf-button").disabled, true);
  assert.equal(document.querySelector("#model-configuration-button").disabled, true);
  assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
}

for (const failure of ["network", "http", "json", "schema"]) {
  test(`R04 sender broadcasts independently of ${failure} identity failure`, async t => {
    let fail = false;
    const ui = await load(t, async (path, _options, original) => {
      if (path === "me" && fail) {
        if (failure === "network") throw new TypeError("Synthetic network failure");
        if (failure === "http") return json({}, 503);
        if (failure === "json") return new Response("{");
        return json({ username: "demo-public", clearance: "INVALID", roles: [] });
      }
      return original();
    });
    fail = true;
    ui.trace.length = 0;
    ui.click("demo-public");
    purged(ui);
    await settle();
    const phases = ui.trace.filter(x => x.message).map(x => x.message.phase);
    assert.deepEqual(phases, ["pending", "settled"]);
    assert.equal(ui.trace[0].message.type, "SESSION_INVALIDATED");
    assert.equal(ui.trace[1].path, "switch");
    assert.ok(ui.trace.findIndex(x => x.message?.phase === "settled") < ui.trace.findIndex(x => x.path === "me"));
    purged(ui);
    assert.notEqual(ui.document.querySelector("#current-user").textContent, "demo-confidential");
    assert.equal(ui.document.querySelector("#account-clearance").textContent, "");
    assert.equal(ui.document.querySelector("#response-language").value, "DE");
  });
}

test("R04 successful switch broadcasts before refresh and installs only fresh capabilities", async t => {
  const ui = await load(t);
  ui.trace.length = 0;
  ui.click("demo-public");
  await settle();
  assert.equal(ui.document.querySelector("#current-user").textContent, "demo-public");
  assert.ok(ui.trace.findIndex(x => x.message?.phase === "settled") < ui.trace.findIndex(x => x.path === "me"));
  purged(ui);
});

test("R04 selecting the already active principal dispatches no mutation or invalidation", async t => {
  const ui = await load(t);
  ui.trace.length = 0;
  ui.click("demo-confidential");
  await settle();
  assert.equal(ui.trace.length, 0);
  assert.ok(ui.document.querySelector("#conversation-history").textContent.includes(MARKER));
});

test("R04 receiver purges synchronously and remains empty when its refresh fails", async t => {
  let fail = false;
  const ui = await load(t, async (path, _options, original) => {
    if (path === "me" && fail) throw new TypeError("Synthetic receiver failure");
    return original();
  });
  const pending = { type: "SESSION_INVALIDATED", operation_id: "synthetic-other-tab", phase: "pending" };
  const settled = { ...pending, phase: "settled" };
  fail = true;
  ui.trace.length = 0;
  ui.channel.deliver(pending);
  purged(ui);
  assert.equal(ui.trace.length, 0, "must not reload identity during a pending mutation");
  ui.channel.deliver(settled);
  await settle();
  purged(ui);
  const reads = ui.trace.length;
  ui.channel.deliver(pending);
  ui.channel.deliver(settled);
  await settle();
  assert.equal(ui.trace.length, reads, "duplicate/out-of-order messages must be idempotent");
  assert.equal(ui.document.querySelector("#account-clearance").textContent, "");
});

for (const oldResult of ["success", "failure"]) {
  test(`R04 rapid switch ignores a late old identity ${oldResult}`, async t => {
    const first = deferred();
    let mutations = 0;
    let firstRead = false;
    const ui = await load(t, async (path, _options, original) => {
      if (path === "switch") mutations++;
      if (path === "me" && mutations === 1) { firstRead = true; return first.promise; }
      return original();
    });
    ui.click("demo-public");
    await settle();
    assert.equal(firstRead, true);
    ui.click("demo-internal");
    await settle();
    assert.equal(ui.document.querySelector("#current-user").textContent, "demo-internal");
    first.resolve(oldResult === "success" ? json(identity("demo-public")) : json({}, 503));
    await settle();
    assert.equal(ui.document.querySelector("#current-user").textContent, "demo-internal");
    purged(ui);
  });
}

for (const outcome of ["success", "ambiguous-network", "malformed-response", "explicit-rejection"]) {
  test(`R04 logout ${outcome} sends invalidation and cannot restore protected state`, async t => {
    const ui = await load(t, async (path, _options, original) => {
      if (path === "logout") {
        if (outcome === "explicit-rejection") return json({}, 403);
        const result = await original();
        if (outcome === "ambiguous-network") throw new TypeError("Response lost after synthetic mutation");
        if (outcome === "malformed-response") return new Response("{");
        return result;
      }
      return original();
    });
    ui.document.querySelector("#logout-button").click();
    await settle();
    purged(ui);
    assert.deepEqual(ui.trace.filter(x => x.message).map(x => x.message.phase), ["pending", "settled"]);
    assert.equal(ui.document.querySelector("#composer-button").disabled, true);
  });
}

test("R04 overlapping remote mutations wait for both settlements, then reopen the channel after navigation", async t => {
  const ui = await load(t);
  ui.trace.length = 0;
  const message = (id, phase) => ({ type: "SESSION_INVALIDATED", operation_id: id, phase });
  ui.channel.deliver(message("one", "pending"));
  ui.channel.deliver(message("two", "pending"));
  ui.channel.deliver(message("one", "settled"));
  await settle();
  assert.equal(ui.trace.length, 0);
  purged(ui);
  ui.channel.deliver(message("two", "settled"));
  await settle();
  assert.equal(ui.document.querySelector("#current-user").textContent, "demo-confidential");
  purged(ui);
  ui.window.dispatchEvent(new ui.window.PageTransitionEvent("pagehide"));
  assert.equal(ui.channel.closed, true);
  ui.window.dispatchEvent(new ui.window.PageTransitionEvent("pageshow", { persisted: true }));
  await settle();
  assert.equal(ui.channels.length, 2);
  purged(ui);
});

test("R04 a mutation settling after pagehide still notifies peers through a short-lived channel", async t => {
  const gate = deferred();
  const ui = await load(t, async (path, _options, original) => {
    const response = await original();
    if (path === "switch") await gate.promise;
    return response;
  });
  ui.click("demo-public");
  await settle();
  ui.window.dispatchEvent(new ui.window.PageTransitionEvent("pagehide"));
  gate.resolve();
  await settle();
  assert.deepEqual(ui.trace.filter(x => x.message).map(x => x.message.phase), ["pending", "settled"]);
  assert.equal(ui.channels[1].closed, true);
  purged(ui);
});
