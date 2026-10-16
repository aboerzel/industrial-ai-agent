import { openAccount, switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";
import { createApiStatusGuard, establishBrowserDemoSession } from "../../../frontend/scripts/e2e-http.mjs";
// DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { test, expect, chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { demoUsers } from "../../frontend/fixtures/demo-auth-fake.mjs";

let process;
let origin;

test.beforeAll(async () => {
  const listener = createServer();
  await new Promise((resolve) => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise((resolve) => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = globalThis.process.env.DEMO_E2E_PYTHON ?? fileURLToPath(new URL(
    globalThis.process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python", import.meta.url,
  ));
  process = spawn(python, [fileURLToPath(new URL("demo-auth-server.py", import.meta.url)), String(port)], { stdio: "ignore" });
  await expect.poll(async () => {
    if (process.exitCode !== null) throw new Error("Synthetic API fixture failed to start.");
    try { return (await fetch(`${origin}/health`)).status; } catch { return 0; }
  }, { timeout: 10_000 }).toBe(200);
});

test.afterAll(async () => {
  if (process?.exitCode === null) {
    const stopped = new Promise((resolve) => process.once("exit", resolve));
    process.kill();
    await stopped;
  }
});

test.beforeEach(async ({ page, context }) => {
  await context.route("**/*", (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await page.goto(origin);
  await expect(page.locator("#current-user")).toHaveText("demo-public");
});

async function select(page, username) {
  await switchDemoUser(page, username);
  await expect(page.locator("#current-user")).toContainText(username);
}

test("real-model harness bootstrap shares the server session cookie before page startup", async ({ browser }) => {
  const context = await browser.newContext();
  try {
    await context.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const user = await establishBrowserDemoSession(context, origin);
    expect(user.username).toBe("demo-public");
    const cookie = (await context.cookies(origin + "/api/v1/auth/me")).find(item => item.name === "industrial_demo_session");
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/api/" });
    const guard = createApiStatusGuard(context);
    const page = await context.newPage();
    await page.goto(origin);
    await expect(page.locator("#current-user")).toHaveText("demo-public");
    guard.assertSuccessful();
  } finally { await context.close(); }
});

test("header account menu shows authoritative permissions, active user and keyboard dismissal", async ({ page }) => {
  await openAccount(page);
  await expect(page.locator("#account-clearance")).toHaveText("PUBLIC");
  await expect(page.locator("#account-roles")).toHaveText("None");
  await page.locator("#switch-user-button").click();
  await expect(page.locator("[data-demo-username]")).toHaveCount(5);
  await expect(page.locator('[data-demo-username="demo-public"]')).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("Escape");
  await expect(page.locator("#account-panel")).toBeHidden();
  await expect(page.locator("#account-button")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#account-panel")).toBeVisible();
  await page.locator("#result-title").click();
  await expect(page.locator("#account-panel")).toBeHidden();
  const toolbar = page.locator(".toolbar-controls");
  await expect(toolbar.locator("button, summary")).toHaveText(["PDF", "New Chat"]);
  expect(await toolbar.locator(".monitoring-menu, #logout-button, #response-language, #model-configuration-button, #account-button, select").count()).toBe(0);
  expect(await page.locator(".header-actions").evaluate(node => [...node.children].map(child => child.className))).toEqual(["monitoring-menu", "configuration-control", "account-area"]);
});

test("language in account menu preserves investigation and server identity across refresh", async ({ page }) => {
  await select(page, "demo-confidential");
  await page.locator("#composer-message").fill("Investigate P4711.");
  await page.locator("#composer-form").evaluate(form => form.requestSubmit());
  await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  const before = await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")));
  await setResponseLanguage(page, "DE");
  await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  expect((await (await page.request.get(`${origin}/api/v1/auth/me`)).json()).username).toBe("demo-confidential");
  expect((await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")))).investigationId).toBe(before.investigationId);
  await page.reload();
  await openAccount(page);
  await expect(page.locator("#response-language")).toHaveValue("DE");
  await expect(page.locator("#switch-user-button")).toHaveText("Benutzer wechseln");
  await expect(page.locator("#current-user")).toHaveText("demo-confidential");
});

test("compact header remains usable on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await select(page, "demo-restricted");
  await openAccount(page);
  await expect(page.locator("#account-clearance")).toHaveText("RESTRICTED");
  await page.locator("#switch-user-button").click();
  await expect(page.locator("[data-demo-username]")).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const panel = await page.locator("#account-panel").boundingBox();
  expect(panel.x).toBeGreaterThanOrEqual(0);
  expect(panel.x + panel.width).toBeLessThanOrEqual(390);
  expect(panel.y + panel.height).toBeLessThanOrEqual(844);
});

test("header Monitoring keeps its links and mouse/keyboard behavior on desktop and mobile", async ({ page }) => {
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const summary = page.locator(".header-actions .monitoring-menu summary");
    await summary.click();
    const panel = page.locator(".monitoring-menu-panel");
    await expect(panel).toBeVisible();
    await expect(panel.locator("a")).toHaveText(["System Overview", "Usage Analytics", "LLM Usage Analytics", "Failure Analytics"]);
    const bounds = await panel.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await summary.press("Enter");
    await expect(panel).toBeHidden();
    await summary.press("Space");
    await expect(panel).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(panel.locator("a").first()).toBeFocused();
    await summary.press("Enter");
    await expect(panel).toBeHidden();
  }
});

for (const user of demoUsers) {
  test(`${user.username}: exact station discovery succeeds with only authorized IDs`, async ({ page }) => {
    await select(page, user.username);
    const levels = [["S01", "S05"], ["S02", "S03"], ["S04", "S06"], ["S07", "S08"]];
    const rank = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].indexOf(user.clearance);
    const expected = levels.slice(0, rank + 1).flat().sort();
    const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/v1/runs") && response.request().method() === "POST");
    await page.locator("#composer-message").fill("welche stationen kennst du");
    await page.locator("#composer-form").evaluate(form => form.requestSubmit());
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const run = await response.json();
    expect(run.status).toBe("success");
    expect(run.tool_calls.map(call => call.tool)).toEqual(["list_stations"]);
    expect(run.identifiers.filter(item => item.type === "station").map(item => item.value).sort()).toEqual(expected);
    expect([...new Set((await page.locator(".agent-answer").last().innerText()).match(/\bS\d{2}\b/g) ?? [])].sort()).toEqual(expected);
    for (const hidden of levels.flat().filter(id => !expected.includes(id))) await expect(page.locator("#conversation-history")).not.toContainText(hidden);
    await expect(page.locator("#conversation-history")).not.toContainText("Die angeforderten Daten sind nicht verfügbar.");
  });

  test(`${user.username}: real server resource matrix and orthogonal model administration`, async ({ page }) => {
    await select(page, user.username);
    const metadata = await (await page.request.get(`${origin}/api/v1/auth/me`)).json();
    expect(metadata).toEqual(user);
    for (const classification of ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]) {
      const allowed = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].indexOf(classification)
        <= ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].indexOf(user.clearance);
      expect((await page.request.get(`${origin}/api/v1/documents/${classification}/download`)).status()).toBe(allowed ? 200 : 404);
    }
    const admin = user.roles.includes("MODEL_ADMIN");
    expect(await page.locator("#model-configuration-button").isDisabled()).toBe(!admin);
    expect((await page.request.get(`${origin}/api/v1/models`)).status()).toBe(admin ? 200 : 403);
    expect((await page.request.put(`${origin}/api/v1/model-assignments`, {
      headers: { "X-Demo-Session": "1" }, data: { consumer_id: "agent", data_classification: "PUBLIC", model_id: "test_local" },
    })).status()).toBe(admin ? 200 : 403);
  });
}

test("fresh PUBLIC startup has no Basic challenge and refresh reflects the session", async ({ page }) => {
  expect((await page.request.get(origin)).headers()["www-authenticate"]).toBeUndefined();
  expect(await page.locator("#user-clearance").count()).toBe(0);
  await select(page, "demo-confidential");
  await page.reload();
  await expect(page.locator("#current-user")).toHaveText("demo-confidential");
});

for (const start of ["demo-confidential", "demo-restricted"]) {
  test(`${start} to PUBLIC purges conversation, exports and server-owned investigation`, async ({ page }) => {
    await select(page, start);
    await page.locator("#composer-message").fill("Investigate P4711.");
    await page.locator("#composer-form").evaluate((form) => form.requestSubmit());
    await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
    await expect(page.locator("#export-pdf-button")).toBeEnabled();
    const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")));
    await select(page, "demo-public");
    await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
    await expect(page.locator("#export-pdf-button")).toBeDisabled();
    expect((await page.request.get(`${origin}/api/v1/investigations/${saved.investigationId}`)).status()).toBe(404);
    expect((await page.request.get(`${origin}/api/v1/investigations/${saved.investigationId}/pdf`)).status()).toBe(404);
    await page.reload();
    await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  });
}

test("restricted to admin to restricted closes model dialog and preserves role/clearance separation", async ({ page }) => {
  await select(page, "demo-restricted");
  await expect(page.locator("#model-configuration-button")).toBeDisabled();
  await select(page, "demo-admin");
  await page.locator("#model-configuration-button").click();
  await expect(page.locator("#model-configuration-dialog")).toBeVisible();
  await page.evaluate(async () => {
    const { invalidateSecurityContext } = await import("/js/api.js?v=20261013-2");
    invalidateSecurityContext("identity");
  });
  await select(page, "demo-restricted");
  await expect(page.locator("#model-configuration-dialog")).not.toBeVisible();
  expect((await page.request.get(`${origin}/api/v1/models`)).status()).toBe(403);
});

test("logout survives refresh and quick selection needs no password", async ({ page }) => {
  await select(page, "demo-confidential");
  await openAccount(page);
  await page.locator("#logout-button").click();
  await expect(page.locator("#demo-user-list")).toBeVisible();
  await page.reload();
  await expect(page.locator("#demo-user-list")).toBeVisible();
  expect(await page.locator("input[type=password]").count()).toBe(0);
  await select(page, "demo-internal");
  expect(await (await page.request.get(origin + "/api/v1/auth/me")).json()).toEqual(demoUsers.find(user => user.username === "demo-internal"));
});

for (const operation of ["json", "download"]) {
  test(`identity switch discards an authorized old ${operation} response even when fetch ignores abort`, async ({ page }) => {
    await select(page, "demo-restricted");
    let resource;
    if (operation === "json") {
      await page.locator("#composer-message").fill("Investigate P4711.");
      await page.locator("#composer-form").evaluate((form) => form.requestSubmit());
      await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
      const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")));
      resource = `/api/v1/investigations/${saved.investigationId}`;
    } else resource = "/api/v1/documents/RESTRICTED/download";
    const downloads = [];
    page.on("download", (download) => downloads.push(download));
    await page.evaluate(async ({ operation, resource }) => {
      const api = await import("/js/api.js?v=20261013-2");
      const originalFetch = window.fetch;
      const originalCreate = URL.createObjectURL;
      window.createdUrls = 0;
      URL.createObjectURL = (...args) => { window.createdUrls++; return originalCreate(...args); };
      window.fetch = async (url, options) => {
        const response = await originalFetch(url, options);
        if (url === resource) {
          if (response.status !== 200) throw new Error("Old response was not authorized.");
          window.oldResponseReady = true;
          // Explicitly ignore abort after a genuine authorized HTTP response.
          await new Promise((resolve) => { window.releaseOldResponse = resolve; });
        }
        return response;
      };
      const pending = operation === "json"
        ? api.getInvestigation(resource.split("/").at(-1))
        : api.downloadDocument("RESTRICTED");
      window.oldResult = null;
      void pending.then(() => { window.oldResult = "unexpected-success"; }, (error) => { window.oldResult = error.name; });
    }, { operation, resource });
    await page.waitForFunction(() => window.oldResponseReady);
    await select(page, "demo-public");
    await page.evaluate(() => window.releaseOldResponse());
    await page.waitForFunction(() => window.oldResult !== null);
    expect(await page.evaluate(() => window.oldResult)).toBe("SecurityContextChangedError");
    expect(await page.evaluate(() => window.createdUrls)).toBe(0);
    expect(downloads).toHaveLength(0);
    await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
    await expect(page.locator("#export-pdf-button")).toBeDisabled();
  });
}

test("logout cannot restore confidential state through browser back navigation", async ({ page }) => {
  await select(page, "demo-confidential");
  await page.locator("#composer-message").fill("Investigate P4711.");
  await page.locator("#composer-form").evaluate((form) => form.requestSubmit());
  await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  await openAccount(page);
  await page.locator("#logout-button").click();
  await expect(page.locator("#current-user")).toHaveText("Select demo user");
  await page.goto("about:blank");
  await page.goBack();
  await expect(page.locator("#current-user")).toHaveText("Select demo user");
  await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  await expect(page.locator("#export-pdf-button")).toBeDisabled();
});

test("switching a shared browser session purges protected state in another open tab", async ({ page, context }) => {
  await select(page, "demo-confidential");
  await page.locator("#composer-message").fill("Investigate P4711.");
  await page.locator("#composer-form").evaluate((form) => form.requestSubmit());
  await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  const second = await context.newPage();
  await second.goto(origin);
  await expect(second.locator("#current-user")).toHaveText("demo-confidential");
  await select(second, "demo-public");
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  await expect(page.locator("#export-pdf-button")).toBeDisabled();
});

test("higher clearance reauthorizes shared investigations while the old UI stays purged", async ({ page }) => {
  await select(page, "demo-confidential");
  await page.locator("#composer-message").fill("Investigate P4711.");
  await page.locator("#composer-form").evaluate((form) => form.requestSubmit());
  await expect(page.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")));
  await select(page, "demo-restricted");
  expect((await page.request.get(`${origin}/api/v1/investigations/${saved.investigationId}`)).status()).toBe(200);
  expect((await page.request.get(`${origin}/api/v1/investigations/${saved.investigationId}/pdf`)).status()).toBe(200);
  await expect(page.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
});

test("manually enabling the model button cannot bypass backend MODEL_ADMIN", async ({ page }) => {
  await page.locator("#model-configuration-button").evaluate((button) => { button.disabled = false; });
  const denied = page.waitForResponse((response) => response.url().endsWith("/api/v1/models"));
  await page.locator("#model-configuration-button").click();
  expect((await denied).status()).toBe(403);
  await expect(page.locator("#model-configuration-content .model-configuration-status.error")).toBeVisible();
  expect(await page.locator(".model-assignment-row").count()).toBe(0);
});

test("R04 successful downgrade purges another tab even when sender identity refresh aborts", async ({ page, context }, testInfo) => {
  await select(page, "demo-confidential");
  const other = await context.newPage();
  await other.goto(origin);
  await expect(other.locator("#current-user")).toHaveText("demo-confidential");
  await other.locator("#composer-message").fill("Investigate P4711.");
  await other.locator("#composer-form").evaluate(form => form.requestSubmit());
  await expect(other.locator("#conversation-history")).toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  await expect(other.locator("#export-pdf-button")).toBeEnabled();
  let failedIdentityRead = false;
  await page.route("**/api/v1/auth/me", route => {
    failedIdentityRead = true;
    return route.abort();
  });
  await openAccount(page);
  await page.locator("#switch-user-button").click();
  const mutation = page.waitForResponse(response => response.url().endsWith("/auth/switch"));
  await page.locator('[data-demo-username="demo-public"]').click();
  expect((await mutation).status()).toBe(200);
  await expect.poll(() => failedIdentityRead).toBe(true);
  await expect(page.locator("#current-user")).not.toHaveText("demo-confidential");
  const server = await (await page.request.get(`${origin}/api/v1/auth/me`)).json();
  expect(server.clearance).toBe("PUBLIC");
  const state = {
    server: server.username,
    sender: await page.locator("#current-user").textContent(),
    receiver: await other.locator("#current-user").textContent(),
    confidentialDomSurvived: (await other.locator("#conversation-history").textContent()).includes("SYNTHETIC CONFIDENTIAL CONVERSATION"),
    exportEnabled: await other.locator("#export-pdf-button").isEnabled(),
  };
  await testInfo.attach("R04 observed state", { body: JSON.stringify(state), contentType: "application/json" });
  console.log("R04 observed state", JSON.stringify(state));
  await expect(other.locator("#conversation-history")).not.toContainText("SYNTHETIC CONFIDENTIAL CONVERSATION");
  await expect(other.locator("#export-pdf-button")).toBeDisabled();
});

async function r04Conversation(page, prompt = "Investigate P4711.") {
  const response = page.waitForResponse(r => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST");
  await page.locator("#composer-message").fill(prompt);
  await page.locator("#composer-form").evaluate(form => form.requestSubmit());
  const run = await response;
  expect(run.status()).toBe(200);
  await expect(page.locator("#composer-button")).toBeEnabled();
  await expect(page.locator("#export-pdf-button")).toBeEnabled();
}

async function r04Shared(page, context, username = "demo-confidential") {
  await select(page, username);
  const other = await context.newPage();
  await other.goto(origin);
  await expect(other.locator("#current-user")).toHaveText(username);
  const prompt = username === "demo-public" ? "welche stationen kennst du" : username === "demo-restricted" ? "Investigate S07." : "Investigate P4711.";
  await r04Conversation(page, prompt);
  await r04Conversation(other, prompt);
  return other;
}

async function r04Purged(page) {
  await expect(page.locator("#conversation-history article")).toHaveCount(0);
  await expect(page.locator("#conversation-history")).not.toContainText(/SYNTHETIC|R04 references/);
  await expect(page.locator(".approval-card, .reference-popover, .reference-action")).toHaveCount(0);
  await expect(page.locator("#export-pdf-button")).toBeDisabled();
  await expect(page.locator("#model-configuration-button")).toBeDisabled();
  expect((await page.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")))).investigationId).toBe(null);
}

async function r04Switch(page, username = "demo-public") {
  await openAccount(page);
  if (await page.locator("#demo-user-list").isHidden()) await page.locator("#switch-user-button").click();
  const response = page.waitForResponse(r => r.url().endsWith("/auth/switch"));
  await page.locator(`[data-demo-username="${username}"]`).click();
  expect((await response).status()).toBe(200);
}

for (const failure of ["http", "json", "schema", "receiver"]) {
  test(`R04 all tabs purge with ${failure} identity refresh failure`, async ({ page, context }) => {
    const other = await r04Shared(page, context);
    let reads = 0;
    const fail = route => {
      reads++;
      if (failure === "receiver") return route.abort();
      return route.fulfill({ status: failure === "http" ? 503 : 200, contentType: "application/json",
        body: failure === "json" ? "{" : failure === "schema" ? JSON.stringify({ username: "demo-confidential", clearance: "INVALID", roles: [] }) : "{}" });
    };
    await page.route("**/api/v1/auth/me", fail);
    if (failure === "receiver") await other.route("**/api/v1/auth/me", fail);
    await r04Switch(page);
    expect((await (await page.request.get(`${origin}/api/v1/auth/me`)).json()).clearance).toBe("PUBLIC");
    await expect.poll(() => reads).toBeGreaterThan(0);
    await r04Purged(page);
    await r04Purged(other);
    await expect(page.locator("#account-clearance")).toBeEmpty();
    if (failure === "receiver") await expect(other.locator("#account-clearance")).toBeEmpty();
    else await expect(other.locator("#current-user")).toHaveText("demo-public");
  });
}

for (const [before, after] of [["demo-confidential", "demo-public"], ["demo-public", "demo-restricted"], ["demo-restricted", "demo-public"]]) {
  test(`R04 normal shared switch ${before} to ${after} purges both contexts`, async ({ page, context }) => {
    const other = await r04Shared(page, context, before);
    await setResponseLanguage(other, "DE");
    await r04Switch(page, after);
    await expect(page.locator("#current-user")).toHaveText(after);
    await expect(other.locator("#current-user")).toHaveText(after);
    await r04Purged(page);
    await r04Purged(other);
    expect(await other.locator("#response-language").inputValue()).toBe("DE");
  });
}

for (const ambiguous of [false, true]) {
  test(`R04 logout purges both tabs despite ${ambiguous ? "ambiguous mutation response" : "receiver identity failure"}`, async ({ page, context }) => {
    const other = await r04Shared(page, context);
    await other.route("**/api/v1/auth/me", route => route.abort());
    if (ambiguous) await page.route("**/api/v1/auth/logout", async route => {
      await route.fetch(); // Real server revocation, then deliberately lose its response.
      await route.abort();
    });
    await openAccount(page);
    await page.locator("#logout-button").click();
    await r04Purged(page);
    await r04Purged(other);
    await expect.poll(async () => (await page.request.get(`${origin}/api/v1/auth/me`)).status()).toBe(401);
    await expect(other.locator("#account-clearance")).toBeEmpty();
  });
}

for (const operation of ["json", "error", "document", "pdf"]) {
  test(`R04 cross-tab invalidation discards late ${operation} after failed sender identity refresh`, async ({ page, context }) => {
    const other = await r04Shared(page, context);
    const saved = await other.evaluate(() => JSON.parse(sessionStorage.getItem("industrial-ai-agent.active-investigation")));
    const resource = ["json", "error"].includes(operation) ? `/api/v1/investigations/${saved.investigationId}`
      : operation === "pdf" ? `/api/v1/investigations/${saved.investigationId}/pdf` : "/api/v1/documents/CONFIDENTIAL/download";
    const downloads = [];
    other.on("download", download => downloads.push(download));
    await other.evaluate(async ({ resource, operation, id }) => {
      const api = await import("/js/api.js?v=20261013-2");
      const original = window.fetch;
      const create = URL.createObjectURL;
      window.createdUrls = 0;
      URL.createObjectURL = (...args) => { window.createdUrls++; return create(...args); };
      window.fetch = async (url, options) => {
        const response = await original(url, options);
        if (url === resource) {
          if (response.status !== 200) throw new Error("Synthetic protected request must be authorized before downgrade");
          window.responseReady = true;
          await new Promise(resolve => { window.releaseR04 = resolve; });
          if (operation === "error") return new Response(JSON.stringify({ code: "synthetic_error", message: "SYNTHETIC CONFIDENTIAL ERROR", documents: [{ title: "SYNTHETIC SECRET" }] }), { status: 500 });
        }
        return response;
      };
      const pending = operation === "pdf" ? api.downloadInvestigationPdf(id) : operation === "document" ? api.downloadDocument("CONFIDENTIAL") : api.getInvestigation(id);
      void pending.then(() => { window.oldOutcome = "unexpected-success"; }, error => { window.oldOutcome = error.name; });
    }, { resource, operation, id: saved.investigationId });
    await other.waitForFunction(() => window.responseReady);
    await page.route("**/api/v1/auth/me", route => route.abort());
    await r04Switch(page);
    await r04Purged(other);
    await other.evaluate(() => window.releaseR04());
    await other.waitForFunction(() => window.oldOutcome);
    expect(await other.evaluate(() => window.oldOutcome)).toBe("SecurityContextChangedError");
    expect(await other.evaluate(() => window.createdUrls)).toBe(0);
    expect(downloads).toHaveLength(0);
    await r04Purged(other);
  });
}

test("R04 cross-tab failure purge removes pending approval controls and their generation", async ({ page, context }) => {
  await select(page, "demo-confidential");
  const other = await context.newPage();
  await other.goto(origin);
  const pending = other.waitForResponse(r => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST");
  await r04Conversation(other, "Investigate S04.");
  const run = await (await pending).json();
  await expect(other.locator(".approval-card")).toContainText("SYNTHETIC CONFIDENTIAL PENDING APPROVAL");
  expect(run.approval_request.approval_execution_id).toMatch(/^[0-9a-f-]{36}$/);
  await page.route("**/api/v1/auth/me", route => route.abort());
  await r04Switch(page);
  await r04Purged(other);
  const denied = await other.request.post(`${origin}/api/v1/runs/${run.run_id}/resume`, { headers: { "X-Demo-Session": "1", Origin: origin },
    data: { decision: "approve", approval_execution_id: run.approval_request.approval_execution_id } });
  expect(denied.status()).toBe(404);
});

for (const failure of ["network", "json"]) {
  test(`R04 ${failure} mutation response still purges peers and revokes active document URLs`, async ({ page, context }) => {
    const other = await r04Shared(page, context);
    await other.evaluate(async () => {
      const api = await import("/js/api.js?v=20261013-2");
      const revoke = URL.revokeObjectURL;
      window.revokedR04Urls = [];
      URL.revokeObjectURL = url => { window.revokedR04Urls.push(url); return revoke(url); };
      window.open = url => { window.openR04Url = url; };
      await api.openDocument("CONFIDENTIAL");
    });
    expect(await other.evaluate(() => window.openR04Url)).toMatch(/^blob:/);
    let mutated = false;
    await page.route("**/api/v1/auth/switch", async route => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      mutated = true;
      if (failure === "network") await route.abort();
      else await route.fulfill({ response, body: "{" });
    });
    await openAccount(page);
    await page.locator("#switch-user-button").click();
    await page.locator('[data-demo-username="demo-public"]').click();
    await expect.poll(() => mutated).toBe(true);
    expect((await (await page.request.get(`${origin}/api/v1/auth/me`)).json()).clearance).toBe("PUBLIC");
    await r04Purged(page);
    await r04Purged(other);
    expect(await other.evaluate(() => window.revokedR04Urls.includes(window.openR04Url))).toBe(true);
    expect(await other.evaluate(async () => { try { await fetch(window.openR04Url); return "accessible"; } catch { return "revoked"; } })).toBe("revoked");
  });
}

test("R04 new tab during delayed sender refresh reads the authoritative new identity", async ({ page, context }) => {
  const other = await r04Shared(page, context);
  let release;
  let started = false;
  await page.route("**/api/v1/auth/me", async route => {
    started = true;
    await new Promise(resolve => { release = resolve; });
    await route.abort();
  });
  await r04Switch(page);
  await expect.poll(() => started).toBe(true);
  const fresh = await context.newPage();
  await fresh.goto(origin);
  await expect(fresh.locator("#current-user")).toHaveText("demo-public");
  await r04Purged(fresh);
  await r04Purged(other);
  release();
});

test("R04 rapid confidential to public to internal ignores an old delayed identity", async ({ page, context }) => {
  const other = await r04Shared(page, context);
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (url, options) => original(url, String(url).endsWith("/auth/me") ? { ...options, signal: undefined } : options);
  });
  let release;
  let held = false;
  await page.route("**/api/v1/auth/me", async route => {
    const response = await route.fetch();
    if (!held) {
      held = true;
      await new Promise(resolve => { release = resolve; });
    }
    await route.fulfill({ response });
  });
  await r04Switch(page);
  await expect.poll(() => held).toBe(true);
  await page.locator('[data-demo-username="demo-internal"]').click();
  await expect(page.locator("#current-user")).toHaveText("demo-internal");
  release();
  await expect(other.locator("#current-user")).toHaveText("demo-internal");
  await r04Purged(page);
  await r04Purged(other);
  expect((await (await page.request.get(`${origin}/api/v1/auth/me`)).json()).username).toBe("demo-internal");
  await expect(page.locator("#current-user")).toHaveText("demo-internal");
});

test("R04 real BFCache restores only purged context after a shared downgrade", async () => {
  const browser = await chromium.launch({ channel: "chromium", ignoreDefaultArgs: ["--disable-back-forward-cache"] });
  try {
    const context = await browser.newContext();
    await context.addInitScript(() => window.addEventListener("pageshow", event => { window.r04BFCache = event.persisted; }));
    const sender = await context.newPage();
    await sender.goto(origin);
    await expect(sender.locator("#current-user")).toHaveText("demo-public");
    const other = await r04Shared(sender, context);
    await other.waitForLoadState("networkidle");
    await other.goto(`${origin}/health`);
    await r04Switch(sender);
    await other.goBack({ waitUntil: "commit" });
    expect(await other.evaluate(() => window.r04BFCache)).toBe(true);
    await r04Purged(other);
    await expect(other.locator("#current-user")).toHaveText("demo-public");
  } finally { await browser.close(); }
});
