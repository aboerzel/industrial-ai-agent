import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { EventEmitter } from "node:events";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import { JOURNEYS } from "../../frontend/scripts/run-e2e-journey.mjs";
import { assertionPlan } from "../../frontend/scripts/journey-assertions.mjs";
import {
  assertHttpStatus, checkDemoSession, completedJourneyStatus, createApiStatusGuard,
  executionStatus, exitCodeForStatuses, fetchExpected, getModelAdminJson, modelAdminHeaders, readExpectedJson,
} from "../../frontend/scripts/e2e-http.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const execute = promisify(execFile);

async function runFixture(t, arguments_, environment = {}, prepare = async () => {}, npmCommand = false) {
  const runId = `finding9-${randomUUID()}`;
  const directory = path.join(root, "evals/results/browser-e2e", runId);
  t.after(() => rm(directory, { recursive: true, force: true }));
  const childArguments = npmCommand ? [
    path.join(path.dirname(process.execPath), "node_modules/npm/bin/npm-cli.js"),
    "run", "e2e:manual:preflight", "--", "--run-id", runId,
  ] : [
    "--import", "../tests/frontend/fixtures/e2e-http-fake.mjs",
    "scripts/run-e2e-journey.mjs", ...arguments_, "--run-id", runId,
  ];
  const childOptions = {
    cwd: path.join(root, "frontend"),
    env: { ...process.env, E2E_API_URL: "http://127.0.0.1:8000", E2E_FRONTEND_URL: "http://127.0.0.1:8080",
      ...(npmCommand ? { NODE_OPTIONS: `--import=${pathToFileURL(path.join(root, "tests/frontend/fixtures/e2e-http-fake.mjs")).href}`,
        npm_config_offline: "true", npm_config_update_notifier: "false" } : {}),
      AGENT_API_MODEL_ADMIN_TOKEN: "fixture-admin-token",
      MCP_INDUSTRIAL_AGENT_TOKEN: "fixture-mcp-token", ...environment },
  };
  let fixturePreflight = null;
  if (arguments_.some((argument) => ["--aggregate", "--resume"].includes(argument))) {
    fixturePreflight = await execute(process.execPath, ["--import", "../tests/frontend/fixtures/e2e-http-fake.mjs", "scripts/run-e2e-journey.mjs", "--preflight", "--run-id", runId], childOptions)
      .then((output) => ({ ...output, code: 0 }), (error) => ({ stdout: error.stdout, stderr: error.stderr, code: error.code }));
  }
  await prepare(directory);
  const result = await execute(process.execPath, childArguments, childOptions).then((output) => ({ ...output, code: 0 }), (error) => ({ stdout: error.stdout, stderr: error.stderr, code: error.code }));
  return { ...result, directory, fixturePreflight };
}

test("documented preflight sends model-admin bearer credentials and passes with fake services", async (t) => {
  const result = await runFixture(t, ["--preflight"]);
  assert.equal(result.code, 0, result.stdout + result.stderr);
  const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
  assert.equal(report.status, "PASS");
  assert.equal(report.checks.find((check) => check.name === "agent-api").status, "PASS");
  assert.doesNotMatch(result.stdout + result.stderr + JSON.stringify(report), /fixture-admin-token|fixture-browser-password|fixture-mcp-token/);
});

test("documented npm preflight command authenticates with synthetic configuration and no network", async (t) => {
  const result = await runFixture(t, [], {}, undefined, true);
  assert.equal(result.code, 0, result.stdout + result.stderr);
  const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
  assert.equal(report.status, "PASS");
  assert.doesNotMatch(result.stdout + result.stderr + JSON.stringify(report), /fixture-admin-token|fixture-browser-password|fixture-admin-password/);
});

test("unexpected unauthorized preflight response cannot be marked PASS", async (t) => {
  const result = await runFixture(t, ["--preflight"], { FINDING9_API_STATUS: "401" });
  assert.notEqual(result.code, 0);
  const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
  assert.notEqual(report.checks.find((check) => check.name === "agent-api").status, "PASS");
});

test("journey startup HTTP failure gives a non-zero process exit without launching a browser", async (t) => {
  const result = await runFixture(t, ["--journey", "s04-investigation"], { FINDING9_API_STATUS: "500" });
  assert.notEqual(result.code, 0);
});

for (const status of [403, 404, 500, 201, 302]) {
  test(`unexpected preflight HTTP ${status} fails the check and overall CLI`, async (t) => {
    const result = await runFixture(t, ["--preflight"], { FINDING9_API_STATUS: String(status) });
    assert.notEqual(result.code, 0);
    const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
    assert.notEqual(report.status, "PASS");
    assert.notEqual(report.checks.find((check) => check.name === "agent-api").status, "PASS");
    assert.match(result.stdout, new RegExp(`Unexpected HTTP status ${status}`));
  });
}

for (const key of ["AGENT_API_MODEL_ADMIN_TOKEN", "MCP_INDUSTRIAL_AGENT_TOKEN"]) {
  test(`missing ${key} fails before HTTP requests and does not leak other credentials`, async (t) => {
    const result = await runFixture(t, ["--preflight"], { [key]: "" });
    assert.notEqual(result.code, 0);
    assert.match(result.stdout, new RegExp(`${key} is required`));
    const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
    assert.deepEqual(report.checks.map((check) => check.name), ["authentication"]);
    assert.doesNotMatch(result.stdout + result.stderr + JSON.stringify(report), /fixture-.*(?:token|password)/);
  });
}

test("disabled or rejected demo session blocks preflight instead of accepting 401", async (t) => {
  const result = await runFixture(t, ["--preflight"], { FINDING9_DEMO_AUTH_STATUS: "401" });
  assert.notEqual(result.code, 0);
  const report = JSON.parse(await readFile(path.join(result.directory, "preflight.json"), "utf8"));
  assert.equal(report.checks.find((check) => check.name === "authentication").status, "BLOCKED");
  assert.doesNotMatch(result.stdout + JSON.stringify(report), /wrong-fixture-password/);
});

async function successfulArtifacts(directory, firstStatus = "PASS") {
  await mkdir(directory, { recursive: true });
  const metadata = JSON.parse(await readFile(path.join(directory, "preflight.json"), "utf8")).metadata;
  const source = await readFile(path.join(root, "frontend/scripts/run-e2e-journey.mjs"), "utf8");
  const ids = [...source.split("const command =")[0].matchAll(/^  (?:"([^"]+)"|([a-z][a-z-]*)): \{/gm)].map((match) => match[1] ?? match[2]);
  for (const [index, id] of ids.entries()) {
    const assertions = assertionPlan(JOURNEYS[id]).map((item) => item.requirement === "MANUAL_ONLY" ? item : { ...item, status: "PASS", executed: true });
    await writeFile(path.join(directory, `journey-${id}.json`), JSON.stringify({ id, journey: id, metadata,
      status: index === 0 ? firstStatus : "PASS", steps: assertions.filter((item) => item.executed).map((item) => ({ assertion_id: item.id, requirement: item.requirement, test_result: "PASS", actual_severity: "SUCCESS" })), assertions,
      smoke: { model_configuration: "PASS", monitoring: "PASS" } }));
  }
}

test("aggregation authentication failure cannot make previously passing artifacts green", async (t) => {
  const result = await runFixture(t, ["--aggregate"], { FINDING9_API_STATUS: "403" }, successfulArtifacts);
  assert.notEqual(result.code, 0);
  const report = JSON.parse(await readFile(path.join(result.directory, "summary.json"), "utf8"));
  assert.equal(report.execution_status, "HARNESS_ERROR");
  assert.notEqual(report.product_quality_gate, "PASS");
});

test("blocked preflight cannot be overwritten by previously passing journey artifacts", async (t) => {
  const result = await runFixture(t, ["--aggregate"], {}, async (directory) => {
    await successfulArtifacts(directory);
    const preflight = JSON.parse(await readFile(path.join(directory, "preflight.json"), "utf8"));
    await writeFile(path.join(directory, "preflight.json"), JSON.stringify({ ...preflight, status: "BLOCKED" }));
  });
  assert.notEqual(result.code, 0);
  const report = JSON.parse(await readFile(path.join(result.directory, "summary.json"), "utf8"));
  assert.equal(report.execution_status, "BLOCKED");
  assert.notEqual(report.product_quality_gate, "PASS");
});

test("manual wrapper propagates aggregation failure after successful child steps", async (t) => {
  const latestFile = path.join(root, "evals/results/browser-e2e/latest-run.txt");
  const saved = await readFile(latestFile).catch(() => null);
  t.after(() => saved ? writeFile(latestFile, saved) : rm(latestFile, { force: true }));
  const code = await execute(process.execPath, [
    "--import", "../tests/frontend/fixtures/e2e-child-exit-fake.mjs",
    "scripts/run-manual-e2e.mjs", "--run-id", `finding9-${randomUUID()}`,
  ], { cwd: path.join(root, "frontend") }).then(() => 0, (error) => error.code);
  assert.equal(code, 1);
});

for (const status of ["PASS", "FAIL", "HARNESS_ERROR", "BLOCKED", "MISSING"]) {
  test(`aggregation propagates ${status} artifacts to report and exit code`, async (t) => {
    const result = await runFixture(t, ["--aggregate"], {}, (directory) => successfulArtifacts(directory, status));
    assert.equal(result.code, status === "PASS" ? 0 : 1);
    const report = JSON.parse(await readFile(path.join(result.directory, "summary.json"), "utf8"));
    assert.equal(report.execution_status, status === "MISSING" ? "INCOMPLETE" : status);
    assert.equal(report.product_quality_gate === "PASS", status === "PASS");
  });
}

test("explicit negative HTTP assertion accepts only the expected 403", () => {
  assertHttpStatus({ status: 403 }, [403]);
  for (const status of [200, 401, 404, 500]) assert.throws(() => assertHttpStatus({ status }, [403]));
});

test("HTTP assertion rejects status before parsing a body which could echo credentials", async () => {
  let parsed = 0;
  const response = { status: 401, json: () => { parsed += 1; throw new Error("fixture-secret"); } };
  await assert.rejects(readExpectedJson(response), /Unexpected HTTP status 401/);
  assert.equal(parsed, 0);
  await assert.rejects(readExpectedJson({ ...response, status: 200 }), (error) => !error.message.includes("fixture-secret"));
});

test("authenticated helpers separate secret API bearer credentials from public demo sessions", async (t) => {
  const previous = globalThis.fetch;
  const saved = { ...process.env };
  t.after(() => { process.env = saved; globalThis.fetch = previous; });
  process.env.AGENT_API_MODEL_ADMIN_TOKEN = "fixture-admin-token";
  assert.deepEqual(await modelAdminHeaders(), { Authorization: "Bearer fixture-admin-token" });
  let username;
  globalThis.fetch = async (url, options) => {
    assert.equal(new URL(url).origin, "http://127.0.0.1:8080");
    assert.equal(options.headers?.Authorization, undefined);
    if (String(url).endsWith("/switch")) {
      username = JSON.parse(options.body).username;
      return Response.json({ username }, { headers: { "set-cookie": "industrial_demo_session=synthetic; HttpOnly" } });
    }
    if (String(url).endsWith("/logout")) return Response.json({ logged_out: true });
    return Response.json({ username, clearance: "PUBLIC", roles: [] });
  };
  assert.equal((await checkDemoSession("http://127.0.0.1:8080", "demo-public")).username, "demo-public");
});
test("fetch helper disables redirects and reports bounded errors without credentials", async (t) => {
  const previous = globalThis.fetch;
  t.after(() => { globalThis.fetch = previous; });
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.redirect, "error");
    throw new Error("Bearer fixture-secret Basic fixture-password");
  };
  await assert.rejects(fetchExpected("http://127.0.0.1:8000"), (error) => !error.message.includes("fixture"));
});

test("Playwright API reads send the admin token and never expose SDK call logs on network failure", async (t) => {
  const previous = process.env.AGENT_API_MODEL_ADMIN_TOKEN;
  t.after(() => {
    if (previous === undefined) delete process.env.AGENT_API_MODEL_ADMIN_TOKEN;
    else process.env.AGENT_API_MODEL_ADMIN_TOKEN = previous;
  });
  process.env.AGENT_API_MODEL_ADMIN_TOKEN = "fixture-admin-token";
  const request = { get: async (_url, options) => {
    assert.equal(options.headers.Authorization, "Bearer fixture-admin-token");
    assert.equal(options.maxRedirects, 0);
    return { status: () => 200, json: async () => ["fixture"] };
  } };
  assert.deepEqual(await getModelAdminJson(request, "http://fixture/api/v1/models"), ["fixture"]);
  request.get = async () => { throw new Error("SDK call log: Authorization Bearer fixture-admin-token"); };
  await assert.rejects(getModelAdminJson(request, "http://fixture/api/v1/models"), (error) => !error.message.includes("fixture-admin-token"));
});

function browserResponse(context, status, pathname = "/api/v1/runs", method = "POST") {
  const request = { url: () => `http://127.0.0.1:8080${pathname}`, method: () => method };
  context.emit("request", request);
  context.emit("response", { status: () => status, request: () => request, url: request.url });
}

for (const status of [401, 403, 404, 500, 204]) {
  test(`browser API guard rejects HTTP ${status} even if the UI presents ATTENTION or SUCCESS`, () => {
    const context = new EventEmitter();
    const guard = createApiStatusGuard(context);
    browserResponse(context, status);
    assert.throws(() => guard.assertSuccessful(), new RegExp(`HTTP status ${status}`));
  });
}

test("expected downgrade reload denial is bound to the exact request and consumed once", () => {
  const context = new EventEmitter();
  const guard = createApiStatusGuard(context);
  guard.expectResponse({ method: "GET", pathname: "/api/v1/investigations/fixture-id", query: { context: "PUBLIC" }, allowedStatuses: [200, 404] });
  browserResponse(context, 404, "/api/v1/investigations/fixture-id?context=PUBLIC", "GET");
  guard.assertSuccessful();
  browserResponse(context, 404, "/api/v1/investigations/fixture-id?context=PUBLIC", "GET");
  assert.throws(() => guard.assertSuccessful(), /HTTP status 404/);
});

test("expected negative browser status never authorizes a different run or clearance", () => {
  for (const pathname of ["/api/v1/investigations/other-id?context=PUBLIC", "/api/v1/investigations/fixture-id?context=RESTRICTED"]) {
    const context = new EventEmitter();
    const guard = createApiStatusGuard(context);
    guard.expectResponse({ method: "GET", pathname: "/api/v1/investigations/fixture-id", query: { context: "PUBLIC" }, allowedStatuses: [404] });
    browserResponse(context, 404, pathname, "GET");
    assert.throws(() => guard.assertSuccessful(), /HTTP status 404/);
  }
});

test("critical smoke failure makes a journey fail and all non-pass outcomes fail the process", () => {
  const result = { status: "RUNNING", steps: [{ test_result: "PASS" }], smoke: { model_configuration: "PASS", monitoring: "FAIL" } };
  assert.equal(completedJourneyStatus(result), "FAIL");
  assert.equal(completedJourneyStatus({ ...result, smoke: { model_configuration: "PASS", monitoring: "PASS" } }), "PASS");
  assert.equal(completedJourneyStatus({ ...result, smoke: {} }), "FAIL");
  for (const status of ["FAIL", "BLOCKED", "HARNESS_ERROR", "MISSING", "RUNNING", "NOT_REACHED"]) {
    assert.notEqual(executionStatus(["PASS", status]), "PASS");
    assert.equal(exitCodeForStatuses(["PASS", status]), 1);
  }
  assert.equal(exitCodeForStatuses(["PASS"]), 0);
  assert.equal(exitCodeForStatuses([]), 1);
});

for (const status of ["PASS", "FAIL", "BLOCKED"]) {
  test(`resume retains the exit outcome of already measured ${status} journeys`, async (t) => {
    const result = await runFixture(t, ["--resume"], {}, (directory) => successfulArtifacts(directory, status));
    assert.equal(result.code, status === "PASS" ? 0 : 1);
  });
}

test("aggregation rejects legacy PASS artifacts with failed critical smoke checks", async (t) => {
  const result = await runFixture(t, ["--aggregate"], {}, async (directory) => {
    await successfulArtifacts(directory);
    const artifact = path.join(directory, "journey-s04-investigation.json");
    const report = JSON.parse(await readFile(artifact, "utf8"));
    report.smoke.monitoring = "FAIL";
    await writeFile(artifact, JSON.stringify(report));
  });
  assert.equal(result.code, 1);
  const report = JSON.parse(await readFile(path.join(result.directory, "summary.json"), "utf8"));
  assert.equal(report.execution_status, "FAIL");
});

for (const fault of ["missing-plan", "pdf-not-run", "missing-reference", "security-not-run"]) {
  test(`aggregation rejects false PASS artifact: ${fault}`, async (t) => {
    const result = await runFixture(t, ["--aggregate"], {}, async (directory) => {
      await successfulArtifacts(directory);
      const id = fault === "security-not-run" ? "clearance-boundary" : "s04-investigation";
      const artifact = path.join(directory, `journey-${id}.json`);
      const report = JSON.parse(await readFile(artifact, "utf8"));
      if (fault === "missing-plan") delete report.assertions;
      else {
        const claim = fault === "pdf-not-run" ? "pdf" : fault === "security-not-run" ? "switch-user" : "reference";
        Object.assign(report.assertions.find((item) => item.claim === claim), { status: "NOT_RUN", executed: false });
      }
      await writeFile(artifact, JSON.stringify(report));
    });
    assert.equal(result.code, 1);
    const summary = JSON.parse(await readFile(path.join(result.directory, "summary.json"), "utf8"));
    assert.equal(summary.execution_status, "BLOCKED");
    assert.notEqual(summary.product_quality_gate, "PASS");
    assert.match(await readFile(path.join(result.directory, "summary.md"), "utf8"), /Required.*Executed.*Passed.*Failed.*Blocked/);
  });
}
