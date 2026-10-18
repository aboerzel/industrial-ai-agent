import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { once } from "node:events";
import { createServer } from "node:http";
import {
  startBroker, withRuntimeWorker, LocalRuntimeBusy,
  REAL_MODEL_WORKERS, REAL_MODEL_RETRIES,
} from "../../frontend/scripts/local-runtime-lock.mjs";
import runtimeSetup from "../../frontend/scripts/runtime-global-setup.mjs";

const exec = promisify(execFile);
const moduleUrl = new URL("../../frontend/scripts/local-runtime-lock.mjs", import.meta.url).href;

test("first reservation excludes a second OS process, independent of checkout", async () => {
  const broker = await startBroker({ port: 0 });
  try {
    const code = `import {startBroker} from ${JSON.stringify(moduleUrl)};
      try {await startBroker({port:${broker.lease.port}}); process.exit(99);}
      catch(error) {console.log(error.code);}`;
    const { stdout } = await exec(process.execPath, ["--input-type=module", "-e", code]);
    assert.equal(stdout.trim(), "LOCAL_RUNTIME_BUSY");
  } finally { broker.release(); await broker.closed; }
});

for (const outcome of ["PASS", "FAIL", "EXCEPTION"]) {
  test(`reservation and worker released after ${outcome}`, async () => {
    const broker = await startBroker({ port: 0, drainMs: 40 });
    const port = broker.lease.port;
    const operation = () => withRuntimeWorker(async () => {
      if (outcome === "EXCEPTION") throw new Error("Synthetic harness error");
      return outcome;
    }, { port, env: { LOCAL_RUNTIME_LEASE: JSON.stringify(broker.lease) } });
    if (outcome === "EXCEPTION") await assert.rejects(operation, /Synthetic harness error/);
    else assert.equal(await operation(), outcome);
    broker.release(); await broker.closed;
    const replacement = await startBroker({ port });
    replacement.release(); await replacement.closed;
  });
}

test("a shared controller lease grants only one chat worker at a time", async () => {
  const broker = await startBroker({ port: 0 });
  const options = { env: { LOCAL_RUNTIME_LEASE: JSON.stringify(broker.lease) }, port: broker.lease.port };
  let release, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const active = withRuntimeWorker(async () => { entered(); await new Promise(resolve => { release = resolve; }); }, options);
  try {
    await ready;
    await assert.rejects(() => withRuntimeWorker(() => assert.fail("must not execute"), options), LocalRuntimeBusy);
  } finally { release(); await active; broker.release(); await broker.closed; }
});

test("cancelled worker retains bounded drain then releases without a stale lock file", async () => {
  const broker = await startBroker({ port: 0, drainMs: 40 });
  const socket = net.createConnection({ host: "127.0.0.1", port: broker.lease.port });
  await once(socket, "connect");
  socket.write(JSON.stringify({ token: broker.lease.token }) + "\n");
  await once(socket, "data");
  const gone = once(socket, "close"); socket.destroy(); await gone;
  broker.release();
  await assert.rejects(() => startBroker({ port: broker.lease.port }), LocalRuntimeBusy);
  await broker.closed;
  const next = await startBroker({ port: broker.lease.port }); next.release(); await next.closed;
});

test("controller loss cannot free a still-active inherited worker", async () => {
  const broker = await startBroker({ port: 0 });
  let release, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const active = withRuntimeWorker(async () => { entered(); await new Promise(resolve => { release = resolve; }); },
    { env: { LOCAL_RUNTIME_LEASE: JSON.stringify(broker.lease) }, port: broker.lease.port });
  await ready; broker.release();
  await assert.rejects(() => startBroker({ port: broker.lease.port }), LocalRuntimeBusy);
  release(); await active; await broker.closed;
});

test("terminated worker process releases the OS reservation after bounded residual drain", async () => {
  const broker = await startBroker({ port: 0, drainMs: 200 });
  const code = `import {withRuntimeWorker} from ${JSON.stringify(moduleUrl)};
    await withRuntimeWorker(async()=>{console.log('ACTIVE'); await new Promise(()=>{});}, {port:${broker.lease.port}});`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", code], {
    env: { ...process.env, LOCAL_RUNTIME_LEASE: JSON.stringify(broker.lease) }, stdio: ["ignore", "pipe", "inherit"],
  });
  try {
    await once(child.stdout, "data");
    await assert.rejects(() => startBroker({ port: broker.lease.port }), LocalRuntimeBusy);
  } finally {
    const exit = once(child, "exit"); child.kill(); await exit;
    broker.release(); await broker.closed;
  }
  const next = await startBroker({ port: broker.lease.port }); next.release(); await next.closed;
});

test("deterministic provider bypass requires a real test-only backend attestation", async () => {
  const fake = createServer((request, response) => {
    assert.equal(request.url, "/__release_fixture__");
    assert.equal(request.headers["x-release-fixture"], "test-only");
    response.end(JSON.stringify({ mode: "SOFTWARE_DETERMINISTIC" }));
  });
  fake.listen(0, "127.0.0.1"); await once(fake, "listening");
  const env = { E2E_EXECUTION_MODE: "SOFTWARE_DETERMINISTIC", E2E_FRONTEND_URL: `http://127.0.0.1:${fake.address().port}`, RELEASE_SOFTWARE_TOKEN: "test-only" };
  const held = await startBroker({ port: 0 });
  try {
    assert.equal(await withRuntimeWorker(() => "SOFTWARE_PASS", { env, port: held.lease.port }), "SOFTWARE_PASS");
    await assert.rejects(() => withRuntimeWorker(() => assert.fail(), { env: { ...env, RELEASE_SOFTWARE_TOKEN: "" } }), /Unverified software fixture/);
  } finally { held.release(); await held.closed; fake.close(); }
});

test("legacy/live-reference qualification rejects worker or retry overrides", async () => {
  assert.equal(REAL_MODEL_WORKERS, 1); assert.equal(REAL_MODEL_RETRIES, 0);
  for (const [workers, retries] of [[2, 0], [1, 1]]) {
    await assert.rejects(() => runtimeSetup({ configFile: "playwright.config.mjs", workers, projects: [{ retries }] }), /workers=1 and retries=0/);
  }
  // Pure synthetic browser fixtures neither reserve the GPU nor verify credentials.
  await runtimeSetup({ configFile: "playwright.fixtures.config.mjs", workers: 1, projects: [{ retries: 0 }] });
});

test("stale inherited tokens cannot authorize a new reservation's worker", async () => {
  const broker = await startBroker({ port: 0 });
  try {
    await assert.rejects(() => withRuntimeWorker(() => assert.fail(), {
      env: { LOCAL_RUNTIME_LEASE: JSON.stringify({ ...broker.lease, token: "stale" }) }, port: broker.lease.port,
    }), LocalRuntimeBusy);
  } finally { broker.release(); await broker.closed; }
});
