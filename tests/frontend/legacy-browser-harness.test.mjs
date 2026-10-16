import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import { assertNeutralDenial, bootstrapLegacySession, finishLegacyJourney, legacyJourneyNames, safeLegacyEvidence, verifyDemoIdentity } from "../../frontend/scripts/legacy-browser-contract.mjs";
import { createApiStatusGuard } from "../../frontend/scripts/e2e-http.mjs";
import { assertionPlan } from "../../frontend/scripts/journey-assertions.mjs";

const publicUser = { username: "demo-public", clearance: "PUBLIC", roles: [] };
const response = (status, user = publicUser) => ({ status: () => status, json: async () => user });
function sessionFixture({ initial = 401, bootstrap = 200, identity = publicUser, verified = 200 } = {}) {
  const calls = []; let admitted = false;
  return { calls, request: {
    async get(url) { calls.push({ method: "GET", url }); return response(admitted ? verified : initial, identity); },
    async post(url, options) { calls.push({ method: "POST", url, options }); admitted = true; return response(bootstrap); },
  } };
}

test("LH-01: a fresh unauthenticated auth/me is expected only before bootstrap", async () => {
  assert.equal((await bootstrapLegacySession(sessionFixture(), "http://127.0.0.1:8080")).initial_auth_status, 401);
  await assert.rejects(bootstrapLegacySession(sessionFixture({ initial: 403 }), "http://127.0.0.1:8080"), /Unexpected HTTP status 403/);
});
test("LH-02: bootstrap uses the shared supported mutation helper, without browser authority", async () => {
  const context = sessionFixture(); await bootstrapLegacySession(context, "http://127.0.0.1:8080");
  assert.deepEqual(context.calls[1], { method: "POST", url: "http://127.0.0.1:8080/api/v1/auth/bootstrap", options: { headers: { "X-Demo-Session": "1" }, data: {}, maxRedirects: 0 } });
  await assert.rejects(bootstrapLegacySession(sessionFixture({ bootstrap: 401 }), "http://127.0.0.1:8080"));
});
test("LH-03: bootstrap identity is independently verified, including clearance and roles", async () => {
  const context = sessionFixture();
  assert.deepEqual((await bootstrapLegacySession(context, "http://127.0.0.1:8080")).identity, publicUser);
  assert.equal(context.calls.length, 3);
  await assert.rejects(bootstrapLegacySession(sessionFixture({ identity: { ...publicUser, roles: ["MODEL_ADMIN"] } }), "http://127.0.0.1:8080"));
});
test("LH-07: unexpected post-auth 401 remains an HTTP failure", async () => {
  await assert.rejects(bootstrapLegacySession(sessionFixture({ verified: 401 }), "http://127.0.0.1:8080"), /Unexpected HTTP status 401/);
  const context = new EventEmitter(); const guard = createApiStatusGuard(context);
  const request = { method: () => "GET", url: () => "http://127.0.0.1/api/v1/auth/me" };
  context.emit("request", request); context.emit("response", { ...response(401), url: request.url, request: () => request });
  assert.throws(() => guard.assertSuccessful(), /401/);
});
test("LH-08: neutral pre-allocation denial requires exact code and no protected identifiers", () => {
  assertNeutralDenial(404, { code: "requested_data_unavailable" }, "P4711", "Nicht verfügbar");
  assert.throws(() => assertNeutralDenial(404, { code: "requested_data_unavailable", run_id: "invented" }, null, ""));
  assert.throws(() => assertNeutralDenial(404, { code: "requested_data_unavailable" }, "P4711", "P4711 unavailable"));
});
test("LH-09: unexpected missing resources and authorized action 404s remain failures", () => {
  assert.throws(() => assertNeutralDenial(404, { code: "not_found" }, null, ""));
  const context = new EventEmitter(); const guard = createApiStatusGuard(context);
  const request = { method: () => "POST", url: () => "http://127.0.0.1/api/v1/runs" };
  context.emit("request", request); context.emit("response", { ...response(404), url: request.url, request: () => request });
  assert.throws(() => guard.assertSuccessful(), /404/);
});
test("LH-10: real Playwright worker restart preserves failure and executes all five independent journeys", async t => {
  const directory = await mkdtemp(path.join(tmpdir(), "legacy-contract-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const frontend = fileURLToPath(new URL("../../frontend/", import.meta.url));
  const playwright = pathToFileURL(path.join(frontend, "node_modules/@playwright/test/index.mjs")).href;
  const reporter = path.join(frontend, "scripts/legacy-browser-reporter.mjs");
  await writeFile(path.join(directory, "playwright.config.mjs"), `export default ${JSON.stringify({ testDir: directory, testMatch: "*.spec.mjs", workers: 1, retries: 0, reporter: [[reporter, { directory }]] })};`);
  await writeFile(path.join(directory, "continue.spec.mjs"), `import {test,expect} from ${JSON.stringify(playwright)};\n` + legacyJourneyNames.map((title, index) => `test(${JSON.stringify(title)}, async ({}, info) => { await info.attach("legacy-journey", { body: JSON.stringify({journey:${JSON.stringify(title)},result:${JSON.stringify(index ? "PASS" : "FAIL")},assertions:[],steps:[]}), contentType:"application/json" }); expect(${index}).not.toBe(0); });`).join("\n"));
  const output = await promisify(execFile)(process.execPath, [path.join(frontend, "node_modules/@playwright/test/cli.js"), "test", "-c", path.join(directory, "playwright.config.mjs")], { cwd: directory }).then(() => 0, error => error.code);
  assert.equal(output, 1);
  const report = JSON.parse(await readFile(path.join(directory, "journeys.json"), "utf8"));
  assert.deepEqual(report.counts, { PASS: 4, FAIL: 1, BLOCKED: 0, HARNESS_ERROR: 0, NOT_RUN: 0 });
  assert.equal(report.execution_status, "FAIL");
});
test("LH-11: failure keeps completed evidence and blocks unexecuted dependent assertions", () => {
  const journey = { assertions: assertionPlan({ steps: [{ kind: "typed" }, { kind: "reference" }, { kind: "document" }] }) };
  Object.assign(journey.assertions[0], { status: "PASS", executed: true });
  finishLegacyJourney(journey, "failed");
  assert.equal(journey.result, "FAIL");
  assert.deepEqual(journey.assertions.slice(0, 4).map(item => item.status), ["PASS", "FAIL", "BLOCKED", "BLOCKED"]);
  assert.equal(journey.assertions[2].executed, false);
});
test("LH-12: retained evidence excludes cookies, tokens, headers and arbitrary error bodies", () => {
  const evidence = safeLegacyEvidence({ journey: "test", result: "FAIL", session_setup: { initial_auth_status: 401, identity: publicUser, cookie: "SECRET" }, steps: [{ label: "typed", passed: false, headers: { authorization: "Bearer SECRET" }, cookie: "SECRET" }], assertions: [{ id: "step-1", status: "FAIL", error: "SECRET" }], cookies: ["SECRET"], token: "SECRET", error: "SECRET" });
  assert.doesNotMatch(JSON.stringify(evidence), /SECRET|Bearer|cookie|token|headers/);
});
test("all five server identities preserve the admin/clearance separation", () => {
  for (const [username, clearance, roles] of [["demo-public", "PUBLIC", []], ["demo-internal", "INTERNAL", []], ["demo-confidential", "CONFIDENTIAL", []], ["demo-restricted", "RESTRICTED", []], ["demo-admin", "PUBLIC", ["MODEL_ADMIN"]]]) verifyDemoIdentity({ username, clearance, roles }, username);
  assert.throws(() => verifyDemoIdentity({ username: "demo-restricted", clearance: "RESTRICTED", roles: ["MODEL_ADMIN"] }, "demo-restricted"));
});
