import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { test, expect } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { switchDemoUser, setResponseLanguage } from "../../../frontend/scripts/demo-account-controls.mjs";

const levels = [["P4101", "P4102"], ["P4900", "P4901"], ["P4711", "P4801", "P4802", "P4805", "P4811"], ["P9001", "P9002"]];
const users = ["demo-public", "demo-internal", "demo-confidential", "demo-restricted", "demo-admin"];
const ids = text => [...new Set(text.match(/\bP\d{4}\b/g) ?? [])].sort();
let server, origin;

test.beforeAll(async () => {
  if (!process.env.FACTORY_DATABASE_URL) return;
  const listener = createServer();
  await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  origin = `http://127.0.0.1:${port}`;
  const python = process.env.DEMO_E2E_PYTHON ?? fileURLToPath(new URL(process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python", import.meta.url));
  server = spawn(python, [fileURLToPath(new URL("fc03-discovery-server.py", import.meta.url)), String(port)], { stdio: "ignore" });
  await expect.poll(async () => {
    if (server.exitCode !== null) throw new Error("FC03 real API fixture failed to start");
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

for (const language of ["DE", "EN"]) {
  for (const [index, username] of users.entries()) {
    test(`FC03 complete authorized product inventory ${username} ${language}`, async ({ page }, testInfo) => {
      test.skip(!process.env.FACTORY_DATABASE_URL, "Requires a disposable seeded PostgreSQL database; no model provider.");
      await page.route("**/*", route => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
      const expected = levels.slice(0, (index === 4 ? 0 : index) + 1).flat().sort();
      await page.goto(origin);
      await expect(page.locator("#current-user")).toHaveText("demo-public");
      await switchDemoUser(page, username);
      await setResponseLanguage(page, language);
      const prompt = language === "DE" ? "Welche Produkte kennst du?" : "Which products do you know?";
      await page.locator("#composer-message").fill(prompt);
      const response = page.waitForResponse(r => r.url() === `${origin}/api/v1/runs` && r.request().method() === "POST");
      await page.locator("#composer-form").evaluate(form => form.requestSubmit());
      const api = await (await response).json();
      const answer = page.locator(".agent-answer").last();
      await expect(answer).toBeVisible();
      const dom = await page.locator("#conversation-history").innerText();
      const all = await (await page.request.get(`${origin}/fixture-evidence`)).json();
      const trace = all.at(-1);
      const detail = await (await page.request.get(`${origin}/api/v1/runs/${api.run_id}`)).json();
      await testInfo.attach("FC03 pipeline", { body: JSON.stringify({ username, language, expected, trace, api, persisted: detail, browser_ids: ids(dom), browser_answer_ids: ids(await answer.innerText()) }), contentType: "application/json" });
      expect(api.status).toBe("success");
      expect(trace.factory_mcp_ids).toEqual(expected);
      expect(trace.model_input_ids).toEqual(expected);
      const presented = [...new Set([...ids(api.answer), ...api.identifiers.filter(r => r.type === "product").map(r => r.value)])].sort();
      expect(presented).toEqual(expected);
      expect(ids(dom)).toEqual(expected);
      expect(ids(await answer.innerText())).toEqual(expected);
      expect(ids(detail.answer)).toEqual(expected);
      expect(api.identifiers.length).toBeLessThanOrEqual(12);
    });
  }
}
