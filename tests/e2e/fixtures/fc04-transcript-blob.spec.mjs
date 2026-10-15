import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { test, expect, chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { openAccount, switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";

let server, origin;
test.beforeAll(async () => {
  const listener = createServer();
  await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = process.env.DEMO_E2E_PYTHON ?? fileURLToPath(new URL(process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python", import.meta.url));
  server = spawn(python, [fileURLToPath(new URL("demo-auth-server.py", import.meta.url)), String(port)], { stdio: "ignore" });
  await expect.poll(async () => {
    if (server.exitCode !== null) throw new Error("FC04 synthetic API fixture failed to start");
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

async function track(context) {
  await context.addInitScript(() => {
    window.fc04Created = [];
    window.fc04Revoked = [];
    window.fc04Invalidations = [];
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = blob => {
      const url = create(blob);
      window.fc04Created.push({ url, type: blob.type, at: performance.now() });
      if (window.fc04InvalidateOnCreate) window.fc04Api.invalidateSecurityContext("identity");
      return url;
    };
    URL.revokeObjectURL = url => { window.fc04Revoked.push({ url, at: performance.now() }); revoke(url); };
    window.addEventListener("securitycontextchange", event => {
      window.fc04Invalidations.push({ reason: event.detail.reason, at: performance.now(), revoked: window.fc04Revoked.map(item => item.url) });
    });
    window.addEventListener("pageshow", event => { window.fc04Restored = event.persisted; });
  });
}

async function start(page) {
  await page.goto(origin);
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  await switchDemoUser(page, "demo-confidential");
}

async function transcript(page, suffix) {
  const marker = `FC04-CONFIDENTIAL-MARKER-${suffix}`;
  // Preserve real auth/session requests, but never dispatch the synthetic run.
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (url, options) => String(url) === "/api/v1/runs"
      ? Promise.reject(new TypeError("Synthetic FC04 transport failure")) : original(url, options);
  });
  await page.locator("#composer-message").fill(marker);
  await page.locator("#composer-form").evaluate(form => form.requestSubmit());
  await expect(page.locator("#export-pdf-button")).toBeEnabled();
  const pending = page.waitForEvent("download");
  await page.locator("#export-pdf-button").click();
  const download = await pending;
  expect(download.suggestedFilename()).toBe("investigation-transcript.pdf");
  const bytes = await readFile(await download.path());
  expect(bytes.subarray(0, 8).toString()).toBe("%PDF-1.4");
  expect(bytes.toString()).toContain(marker);
  const { url, type } = await page.evaluate(() => window.fc04Created.at(-1));
  expect(type).toBe("application/pdf");
  expect(await readable(page, url, marker)).toEqual({ readable: true, containsMarker: true });
  return { url, marker };
}

async function readable(page, url, marker) {
  return page.evaluate(async ({ url, marker }) => {
    try { const response = await fetch(url); return { readable: response.ok, containsMarker: (await response.text()).includes(marker) }; }
    catch { return { readable: false, containsMarker: false }; }
  }, { url, marker });
}

async function revoked(page, item, testInfo) {
  await expect(page.locator("#conversation-history")).not.toContainText(item.marker);
  await expect(page.locator("#export-pdf-button")).toBeDisabled();
  const direct = await readable(page, item.url, item.marker);
  const evidence = await page.evaluate(() => ({ created: window.fc04Created, revoked: window.fc04Revoked, invalidations: window.fc04Invalidations }));
  await testInfo.attach("FC04 retained URL", { body: JSON.stringify({ direct, ...evidence }), contentType: "application/json" });
  expect(direct).toEqual({ readable: false, containsMarker: false });
  // Revocation is synchronous inside purge, before securitycontextchange dispatch.
  expect(evidence.invalidations.some(event => event.revoked.includes(item.url))).toBe(true);
  expect(evidence.revoked.filter(entry => entry.url === item.url)).toHaveLength(1);
}

for (const target of ["demo-public", "demo-restricted"]) {
  test(`FC04-B1 same-tab ${target} immediately revokes actual transcript URL`, async ({ page, context }, testInfo) => {
    await track(context);
    await start(page);
    const item = await transcript(page, target);
    await switchDemoUser(page, target);
    await revoked(page, item, testInfo);
  });
}

for (const ambiguous of [false, true]) {
  test(`FC04-B2 ${ambiguous ? "ambiguous" : "normal"} logout revokes actual URL`, async ({ page, context }, testInfo) => {
    await track(context);
    await start(page);
    const item = await transcript(page, `logout-${ambiguous}`);
    if (ambiguous) await page.route("**/api/v1/auth/logout", async route => { await route.fetch(); await route.abort(); });
    await openAccount(page);
    await page.locator("#logout-button").click();
    await revoked(page, item, testInfo);
    expect((await page.request.get(`${origin}/api/v1/auth/me`)).status()).toBe(401);
  });
}

for (const failure of [null, "network", "http", "schema"]) {
  test(`FC04-B3/B4 cross-tab downgrade with ${failure ?? "successful"} identity refresh`, async ({ page, context }, testInfo) => {
    await track(context);
    await start(page);
    const item = await transcript(page, `cross-tab-${failure}`);
    const sender = await context.newPage();
    await sender.goto(origin);
    await expect(sender.locator("#current-user")).toHaveText("demo-confidential");
    if (failure) await page.route("**/api/v1/auth/me", route => failure === "network" ? route.abort() : route.fulfill({ status: failure === "http" ? 503 : 200, contentType: "application/json", body: failure === "schema" ? JSON.stringify({ username: "demo-confidential", clearance: "INVALID", roles: [] }) : "{}" }));
    await switchDemoUser(sender, "demo-public");
    await revoked(page, item, testInfo);
    if (failure) await expect(page.locator("#account-clearance")).toBeEmpty();
  });
}

test("FC04-B5 actual BFCache restore cannot restore the old transcript URL", async ({}, testInfo) => {
  const browser = await chromium.launch({ channel: "chromium", ignoreDefaultArgs: ["--disable-back-forward-cache"] });
  try {
    const context = await browser.newContext({ acceptDownloads: true });
    await track(context);
    const sender = await context.newPage();
    await start(sender);
    const page = await context.newPage();
    await page.goto(origin);
    await expect(page.locator("#current-user")).toHaveText("demo-confidential");
    const item = await transcript(page, "bfcache");
    await page.waitForLoadState("networkidle");
    await page.goto(`${origin}/health`);
    await switchDemoUser(sender, "demo-public");
    await page.goBack({ waitUntil: "commit" });
    expect(await page.evaluate(() => window.fc04Restored)).toBe(true);
    await expect(page.locator("#current-user")).toHaveText("demo-public");
    await revoked(page, item, testInfo);
  } finally { await browser.close(); }
});

test("FC04 pagehide closes notifications but cannot preserve a transcript URL", async ({ page, context }, testInfo) => {
  await track(context);
  await start(page);
  const item = await transcript(page, "pagehide");
  const sender = await context.newPage();
  await sender.goto(origin);
  await expect(sender.locator("#current-user")).toHaveText("demo-confidential");
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
  await revoked(page, item, testInfo);
  await switchDemoUser(sender, "demo-public");
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  await expect(page.locator("#current-user")).toHaveText("demo-public");
  expect(await readable(page, item.url, item.marker)).toEqual({ readable: false, containsMarker: false });
});

test("FC04-B6 deferred old-generation export cannot publish a Blob URL", async ({ page, context }) => {
  await track(context);
  await start(page);
  await page.evaluate(async () => {
    const api = await import("/js/api.js?v=20261013-2");
    const pdf = await import("/js/transcript-pdf.js?v=20261013-1");
    const generation = api.getSecurityContextGeneration();
    window.fc04Pending = new Promise(resolve => { window.fc04Release = resolve; }).then(() => pdf.downloadTranscriptPdf([{ request: "FC04-CONFIDENTIAL-MARKER-LATE" }], generation)).then(() => "published", error => error.name);
  });
  await switchDemoUser(page, "demo-public");
  expect(await page.evaluate(async () => { window.fc04Release(); return window.fc04Pending; })).toBe("SecurityContextChangedError");
  expect(await page.evaluate(() => window.fc04Created)).toHaveLength(0);
});

test("FC04 creation-to-publication race revokes URL and never starts download", async ({ page, context }, testInfo) => {
  await track(context);
  await start(page);
  await page.evaluate(async () => {
    window.fc04Api = await import("/js/api.js?v=20261013-2");
    window.fc04InvalidateOnCreate = true;
  });
  const downloads = [];
  page.on("download", value => downloads.push(value));
  await page.locator("#composer-message").fill("FC04-CONFIDENTIAL-MARKER-RACE");
  await page.locator("#composer-form").evaluate(form => form.requestSubmit());
  // Use the transport-only transcript branch without invoking a real run.
  await page.evaluate(async () => {
    const pdf = await import("/js/transcript-pdf.js?v=20261013-1");
    try { pdf.downloadTranscriptPdf([{ request: "FC04-CONFIDENTIAL-MARKER-RACE" }]); } catch (error) { window.fc04RaceError = error.name; }
  });
  const item = await page.evaluate(() => window.fc04Created.at(-1));
  expect(await page.evaluate(() => window.fc04RaceError)).toBe("SecurityContextChangedError");
  expect(await readable(page, item.url, "FC04-CONFIDENTIAL-MARKER-RACE")).toEqual({ readable: false, containsMarker: false });
  expect(downloads).toHaveLength(0);
});

test("FC04-B7 normal export and language change retain URL until normal cleanup", async ({ page, context }) => {
  await track(context);
  await start(page);
  await page.clock.install();
  const item = await transcript(page, "normal-language");
  await setResponseLanguage(page, "DE");
  expect(await readable(page, item.url, item.marker)).toEqual({ readable: true, containsMarker: true });
  await page.clock.fastForward(60001);
  expect(await readable(page, item.url, item.marker)).toEqual({ readable: false, containsMarker: false });
  await switchDemoUser(page, "demo-public");
  expect(await page.evaluate(url => window.fc04Revoked.filter(entry => entry.url === url).length, item.url)).toBe(1);
});

for (const kind of ["server-pdf", "document"]) {
  test(`FC04-B8/B9 existing ${kind} URL remains context owned`, async ({ page, context }, testInfo) => {
    await track(context);
    await start(page);
    await page.evaluate(async kind => {
      const api = await import("/js/api.js?v=20261013-2");
      if (kind === "document") await api.downloadDocument("CONFIDENTIAL");
      else {
        const result = await api.createRun("Investigate P4711.", "EN");
        await api.downloadInvestigationPdf(result.investigation_id);
      }
    }, kind);
    const { url } = await page.evaluate(() => window.fc04Created.at(-1));
    expect((await readable(page, url, "synthetic")).readable).toBe(true);
    await switchDemoUser(page, "demo-public");
    expect((await readable(page, url, "synthetic")).readable).toBe(false);
  });
}
