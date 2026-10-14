import { openAccount, switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";
// DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { test, expect } from "../../../frontend/node_modules/@playwright/test/index.mjs";
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
