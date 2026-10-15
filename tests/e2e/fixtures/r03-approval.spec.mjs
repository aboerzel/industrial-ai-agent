import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { test, expect, chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";

let server;
let origin;
test.beforeAll(async () => {
  const listener = createServer();
  await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = process.env.DEMO_E2E_PYTHON ?? fileURLToPath(new URL(process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python", import.meta.url));
  server = spawn(python, [fileURLToPath(new URL("r03-approval-server.py", import.meta.url)), String(port)], { stdio: "ignore" });
  await expect.poll(async () => {
    if (server.exitCode !== null) throw new Error("Synthetic R03 API failed to start");
    try { return (await fetch(`${origin}/health`)).status; } catch { return 0; }
  }, { timeout: 10000 }).toBe(200);
});
test.afterAll(async () => {
  if (server?.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill();
    await stopped;
  }
});

async function start(page) {
  await page.goto(origin);
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  await switchDemoUser(page, "demo-confidential");
  await page.locator("#composer-message").fill("Investigate S04.");
  const response = page.waitForResponse(r => r.url() === `${origin}/api/v1/runs` && r.request().method() === "POST");
  await page.locator("#composer-form").evaluate(form => form.requestSubmit());
  const a = await (await response).json();
  await expect(page.locator(".approval-card")).toContainText("S04");
  expect(a.approval_request.approval_execution_id).toMatch(/^[0-9a-f-]{36}$/);
  return a;
}
async function advance(request, a) {
  const result = await request.post(`${origin}/api/v1/runs/${a.run_id}/resume`, { headers: { "X-Demo-Session": "1", Origin: origin }, data: { decision: "approve", approval_execution_id: a.approval_request.approval_execution_id } });
  expect(result.status()).toBe(200);
  const b = await result.json();
  expect(b.status).toBe("waiting_for_approval");
  expect(b.approval_request.arguments.station_id).toBe("S02");
  expect(b.approval_request.approval_execution_id).not.toBe(a.approval_request.approval_execution_id);
  return b;
}
async function staleClick(page, a, b, decision, language = "EN") {
  const decisions = [];
  page.on("request", request => { if (request.url().endsWith("/resume")) decisions.push(request.postDataJSON()); });
  const rejected = page.waitForResponse(r => r.url().endsWith("/resume") && r.request().method() === "POST");
  await page.getByRole("button", { name: decision === "approve" ? "Approve" : "Reject", exact: true }).click();
  expect((await rejected).status()).toBe(409);
  await expect(page.locator(".approval-card")).toContainText("S02");
  await expect(page.locator("#error-message")).toHaveText(language === "DE"
    ? "Die Freigabeanforderung hat sich geändert. Bitte prüfen Sie die aktuelle Aktion erneut."
    : "The approval request changed. Please review the current action.");
  expect(decisions).toEqual([{ decision, approval_execution_id: a.approval_request.approval_execution_id }]);
  const current = await (await page.request.get(`${origin}/api/v1/runs/${a.run_id}`)).json();
  expect(current.status).toBe("waiting_for_approval");
  expect(current.approval_request.approval_execution_id).toBe(b.approval_request.approval_execution_id);
}

for (const decision of ["approve", "reject"]) {
  test(`multi-tab stale ${decision} refreshes the proposal and requires a new decision`, async ({ page, context }) => {
    const a = await start(page);
    if (decision === "reject") await setResponseLanguage(page, "DE");
    const tabB = await context.newPage();
    await tabB.goto(origin);
    const b = await advance(tabB.request, a);
    await staleClick(page, a, b, decision, decision === "reject" ? "DE" : "EN");
    const fresh = page.waitForResponse(r => r.url().endsWith("/resume"));
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    const response = await fresh;
    expect(response.request().postDataJSON().approval_execution_id).toBe(b.approval_request.approval_execution_id);
    expect(response.status()).toBe(200);
  });
}

test("BFCache restored old DOM remains generation-bound even without navigation cleanup", async () => {
  const browser = await chromium.launch({ channel: "chromium", timeout: 5000, ignoreDefaultArgs: ["--disable-back-forward-cache"] });
  try {
    const context = await browser.newContext();
    await context.addInitScript(() => {
      // Deliberately retain old controls to exercise the authoritative server guard.
      const add = window.addEventListener.bind(window);
      add("pageshow", event => { window.wasRestoredFromBFCache = event.persisted; });
      window.addEventListener = (name, ...args) => {
        if (!["pagehide", "pageshow"].includes(name)) add(name, ...args);
      };
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const a = await start(page);
    await page.waitForLoadState("networkidle");
    const cdp = await context.newCDPSession(page);
    const cacheMisses = [];
    await cdp.send("Page.enable");
    cdp.on("Page.backForwardCacheNotUsed", event => cacheMisses.push(event));
    await page.goto(`${origin}/away`);
    const b = await advance(context.request, a);
    await page.goBack({ waitUntil: "commit", timeout: 5000 });
    expect(await page.evaluate(() => window.wasRestoredFromBFCache), JSON.stringify(cacheMisses)).toBe(true);
    await expect(page.locator(".approval-card")).toContainText("S04");
    await staleClick(page, a, b, "approve");
  } finally { await browser.close(); }
});

test("identity switch rejects a preserved old request under current authority", async ({ page }) => {
  const a = await start(page);
  const b = await advance(page.request, a);
  const oldRequest = { decision: "approve", approval_execution_id: a.approval_request.approval_execution_id };
  await switchDemoUser(page, "demo-public");
  await expect(page.locator(".approval-card")).toHaveCount(0);
  expect((await page.request.post(`${origin}/api/v1/runs/${a.run_id}/resume`, { headers: { "X-Demo-Session": "1", Origin: origin }, data: oldRequest })).status()).toBe(404);
  await switchDemoUser(page, "demo-restricted");
  expect((await page.request.post(`${origin}/api/v1/runs/${a.run_id}/resume`, { headers: { "X-Demo-Session": "1", Origin: origin }, data: oldRequest })).status()).toBe(409);
  const current = await (await page.request.get(`${origin}/api/v1/runs/${a.run_id}`)).json();
  expect(current.status).toBe("waiting_for_approval");
  expect(current.approval_request.approval_execution_id).toBe(b.approval_request.approval_execution_id);
});
