// Default: synthetic ports behind real frontend/API/graph. Explicit live mode uses no mocks.
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { test, expect } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";
import { referenceCases } from "../../reference_action_contract.mjs";

const live = process.env.REFERENCE_LIVE_URL;
const cases = await referenceCases({ extended: true });
const histories = new Map();
const records = [];
let child;
let origin = live;

test.setTimeout(live ? 240_000 : 25_000);
test.beforeAll(async () => {
  if (live) {
    // Optional real prior results exercise authorized persisted-reference navigation.
    if (process.env.REFERENCE_PRIOR_RESULTS) {
      for (const item of JSON.parse(await readFile(process.env.REFERENCE_PRIOR_RESULTS, "utf8"))) {
        if (item.live && item.outcome?.status === "success" && item.payload?.investigation_id) {
          histories.set(`${item.username}:${item.value}:${item.language}`, item.payload.investigation_id);
        }
      }
    }
    return;
  }
  const listener = createServer();
  await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = process.env.DEMO_E2E_PYTHON ?? fileURLToPath(new URL(
    process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python", import.meta.url,
  ));
  child = spawn(python, [fileURLToPath(new URL("reference-actions-server.py", import.meta.url)), String(port)], { stdio: "ignore" });
  await expect.poll(async () => {
    if (child.exitCode !== null) throw new Error("Reference fixture failed to start");
    try { return (await fetch(`${origin}/health`)).status; } catch { return 0; }
  }, { timeout: 10_000 }).toBe(200);
});

test.afterAll(async () => {
  if (child?.exitCode === null) {
    const stopped = new Promise(resolve => child.once("exit", resolve));
    child.kill(); await stopped;
  }
  if (process.env.REFERENCE_EVIDENCE_DIR) {
    await mkdir(process.env.REFERENCE_EVIDENCE_DIR, { recursive: true });
    const directory = process.env.REFERENCE_EVIDENCE_DIR;
    await writeFile(`${directory}/reference-browser-matrix-worker-${test.info().workerIndex}.json`, JSON.stringify(records, null, 2));
    const workers = (await readdir(directory)).filter(name => /^reference-browser-matrix-worker-\d+\.json$/.test(name));
    const combined = (await Promise.all(workers.map(name => readFile(`${directory}/${name}`, "utf8").then(JSON.parse)))).flat();
    await writeFile(`${directory}/reference-browser-matrix.json`, JSON.stringify(combined, null, 2));
  }
});

async function identity(page, item) {
  await page.goto(origin);
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  if (item.username !== "demo-public") await switchDemoUser(page, item.username);
  await setResponseLanguage(page, item.language);
}

async function initial(page, item) {
  const key = `${item.username}:${item.value}:${item.language}`;
  let id = histories.get(key);
  if (id) {
    // Install after pagehide, which deliberately persists the currently empty UI.
    await page.addInitScript(({ id, item }) => sessionStorage.setItem("industrial-ai-agent.active-investigation",
      JSON.stringify({ investigationId: id, responseLanguage: item.language, username: item.username })), { id, item });
    await page.reload();
  } else {
    const pending = page.waitForResponse(r => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST", { timeout: 230_000 });
    await page.locator("#composer-message").fill(item.prompt);
    await page.locator("#composer-button").click();
    const response = await pending;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.status).toBe("success");
    id = result.investigation_id;
    histories.set(key, id);
  }
  await expect(page.locator(".structured-reference").filter({ hasText: new RegExp(`^${item.value}$`) }).first()).toBeVisible({ timeout: 230_000 });
  return id;
}

for (const item of cases) {
  test(`reference ${item.index}: ${item.username} ${item.type} ${item.language} ${item.label}`, async ({ page }) => {
    await identity(page, item);
    const id = await initial(page, item);
    await page.locator(".structured-reference").filter({ hasText: new RegExp(`^${item.value}$`) }).first().click();
    const pending = page.waitForResponse(r => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST", { timeout: 230_000 });
    await page.getByRole("button", { name: item.label, exact: true }).click();
    const response = await pending;
    const payload = response.request().postDataJSON();
    const result = await response.json();
    records.push({ ...item, endpoint: "/api/v1/runs", payload, http_status: response.status(), outcome: result,
      rendered_type: item.type, rendered_id: item.value, live: Boolean(live) });
    expect(response.status()).toBe(200);
    expect(payload).toEqual({ message: item.prompt, response_language: item.language, investigation_id: id });
    expect(result.status).toBe("success");
    expect(result.tool_calls[0].tool).toBe(item.tool);
    expect(result.tool_calls[0].arguments[item.argument]).toBe(item.value);
    const stored = await page.request.get(`${origin}/api/v1/investigations/${id}`);
    expect(stored.status()).toBe(200);
    const history = await stored.json();
    expect(history.turns.at(-1).run_id).toBe(result.run_id);
    await expect(page.locator("#composer-button")).toBeEnabled();
    await expect(page.locator(".structured-reference").filter({ hasText: new RegExp(`^${item.value}$`) }).last()).toBeVisible();
  });
}

test("reference targets and unknown IDs retain neutral PUBLIC denial", async ({ page }) => {
  await identity(page, { username: "demo-public", language: "EN" });
  let neutral;
  for (const message of ["Investigate station S04.", "Investigate station S99.", "Investigate product P4711.", "Investigate product P9999.", "Investigate QUALITY-09.", "Investigate UNKNOWN-99.", "Show ticket MT-S02-20260117.", "Show ticket MT-FFFFFFFFFFFF."]) {
    const response = await page.request.post(`${origin}/api/v1/runs`, { headers: { "X-Demo-Session": "1", Origin: origin }, data: { message, response_language: "EN" } });
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.code).toBe("requested_data_unavailable");
    const safe = { code: body.code, message: body.message };
    neutral ??= safe;
    expect(safe).toEqual(neutral);
    expect(JSON.stringify(body)).not.toMatch(/required.clearance|CONFIDENTIAL|RESTRICTED|hidden.count/i);
  }
  for (const language of ["DE", "EN"]) {
    let denied;
    for (const item of cases.filter(c => c.language === language && c.username !== "demo-public")) {
      const response = await page.request.post(`${origin}/api/v1/runs`, {
        headers: { "X-Demo-Session": "1", Origin: origin },
        data: { message: item.prompt, response_language: language },
      });
      expect(response.status()).toBe(404);
      const body = await response.json();
      const safe = { code: body.code, message: body.message };
      denied ??= safe;
      expect(safe).toEqual(denied);
      expect(body.code).toBe("requested_data_unavailable");
      expect(JSON.stringify(body)).not.toMatch(/required.clearance|CONFIDENTIAL|RESTRICTED|hidden.count/i);
    }
  }
});

for (const language of ["DE", "EN"]) {
  test(`document references ${language} retain Open/Download endpoints and server filename`, async ({ page }) => {
    const item = cases.find(c => c.type === "error_code" && c.language === language);
    await identity(page, item);
    await initial(page, item);
    let runs = 0;
    page.on("request", request => { if (request.method() === "POST" && request.url().endsWith("/api/v1/runs")) runs++; });
    const openResponse = page.waitForResponse(r => r.url().includes("/api/v1/documents/") && !r.url().endsWith("/download"));
    await page.getByRole("button", { name: language === "DE" ? "Öffnen" : "Open", exact: true }).first().click();
    const opened = await openResponse;
    expect(opened.status()).toBe(200);
    expect(opened.headers()["content-disposition"]).toMatch(/^inline;/);
    const responsePending = page.waitForResponse(r => r.url().includes("/api/v1/documents/") && r.url().endsWith("/download"));
    const downloadPending = page.waitForEvent("download");
    await page.getByRole("button", { name: language === "DE" ? "Herunterladen" : "Download", exact: true }).first().click();
    const response = await responsePending;
    expect(response.status()).toBe(200);
    const filename = response.headers()["content-disposition"].match(/filename="([^"]+)"/)[1];
    expect((await downloadPending).suggestedFilename()).toBe(filename);
    expect(runs).toBe(0);
  });
}

test("reference persists through reload and language-only change", async ({ page }) => {
  const item = cases.find(c => c.value === "S01" && c.language === "DE");
  await identity(page, item);
  await initial(page, item);
  await page.reload();
  await setResponseLanguage(page, "EN");
  await page.locator(".structured-reference").filter({ hasText: /^S01$/ }).first().click();
  const pending = page.waitForResponse(r => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST", { timeout: 230_000 });
  await page.getByRole("button", { name: "Station untersuchen", exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().response_language).toBe("EN");
  expect((await response.json()).tool_calls[0].arguments.station_id).toBe("S01");
});

test("cross-tab identity invalidation removes old protected references and menus", async ({ page, context }) => {
  const item = cases.find(c => c.value === "S04" && c.language === "EN");
  await identity(page, item);
  const id = await initial(page, item);
  const other = await context.newPage();
  await other.goto(origin);
  await expect(other.locator("#current-user")).toHaveText(item.username);
  await page.locator(".structured-reference").filter({ hasText: /^S04$/ }).first().click();
  await expect(page.locator(".reference-popover")).toBeVisible();
  await switchDemoUser(other, "demo-public");
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  await expect(page.locator(".structured-reference, .reference-popover")).toHaveCount(0);
  expect((await page.request.get(`${origin}/api/v1/investigations/${id}`)).status()).toBe(404);
});
