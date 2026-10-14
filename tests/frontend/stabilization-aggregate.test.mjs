import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { JOURNEYS } from "../../frontend/scripts/run-e2e-journey.mjs";
import { assertionPlan } from "../../frontend/scripts/journey-assertions.mjs";

test("actual aggregate CLI requires matching preflight and rejects historical PASS artifacts", async () => {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const runId = `stabilization-synthetic-${randomUUID()}`;
  const directory = path.join(root, "evals/results/browser-e2e", runId);
  await mkdir(directory, { recursive: true });
  const server = createServer((_request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end("[]");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const aggregate = async (mode = "--aggregate") => {
    const exit = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ["frontend/scripts/run-e2e-journey.mjs", mode, "--run-id", runId], {
        cwd: root, stdio: "ignore", env: { ...process.env, E2E_API_URL: `http://127.0.0.1:${server.address().port}`, AGENT_API_MODEL_ADMIN_TOKEN: "synthetic-token" },
      });
      child.once("error", reject); child.once("exit", resolve);
    });
    return { exit, summary: JSON.parse(await readFile(path.join(directory, "summary.json"), "utf8")) };
  };
  try {
    const initial = await aggregate();
    const metadata = initial.summary.metadata;
    for (const [id, definition] of Object.entries(JOURNEYS)) {
      const assertions = assertionPlan(definition).map((item) => item.requirement === "REQUIRED" ? { ...item, executed: true, status: "PASS" } : item);
      await writeFile(path.join(directory, `journey-${id}.json`), JSON.stringify({
        id, journey: definition.name, metadata, status: "PASS", runner_result: "PASS",
        steps: assertions.filter((item) => item.requirement === "REQUIRED").map((item) => ({ assertion_id: item.id, requirement: item.requirement, test_result: "PASS" })),
        assertions, smoke: { model_configuration: "PASS", monitoring: "PASS" },
      }));
    }
    const missing = await aggregate();
    assert.notEqual(missing.exit, 0);
    assert.equal(missing.summary.preflight_status, "BLOCKED");
    assert.notEqual((await aggregate("--resume")).exit, 0);
    await writeFile(path.join(directory, "preflight.json"), JSON.stringify({ metadata, status: "PASS" }));
    const current = await aggregate();
    assert.equal(current.exit, 0);
    assert.equal(current.summary.execution_status, "PASS");
    assert.equal((await aggregate("--resume")).exit, 0);
    const id = Object.keys(JOURNEYS)[0];
    const filename = path.join(directory, `journey-${id}.json`);
    const stale = JSON.parse(await readFile(filename, "utf8"));
    stale.metadata.product_fingerprint = "obsolete-source";
    await writeFile(filename, JSON.stringify(stale));
    const historical = await aggregate();
    assert.notEqual(historical.exit, 0);
    assert.notEqual(historical.summary.execution_status, "PASS");
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
