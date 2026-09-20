import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

const DASHBOARD_LINKS = [
  ["System Overview", "http://localhost:3000/d/industrial-ai-agent-system-overview"],
  ["Usage Analytics", "http://localhost:3000/d/industrial-ai-agent-usage-analytics"],
  ["LLM Usage Analytics", "http://localhost:3000/d/industrial-ai-agent-cost-analytics"],
  ["Failure Analytics", "http://localhost:3000/d/industrial-ai-agent-failure-analytics"],
];

test("renders a JavaScript-independent declarative Monitoring menu", async () => {
  const index = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const dom = new JSDOM(index);
  const menu = dom.window.document.querySelector("details.monitoring-menu");
  const summary = menu?.querySelector(":scope > summary");
  const links = [...(menu?.querySelectorAll(":scope > nav a") ?? [])];

  assert.ok(menu);
  assert.ok(summary);
  assert.equal(summary.textContent.trim(), "Monitoring");
  assert.equal(dom.window.document.querySelector("#monitoring-dialog"), null);
  assert.equal(dom.window.document.querySelector(".monitoring-dialog"), null);
  assert.equal(dom.window.document.querySelector("#monitoring-button"), null);
  assert.deepEqual(links.map((link) => [link.textContent, link.href]), DASHBOARD_LINKS);
  assert.deepEqual(links.map((link) => link.target), ["_blank", "_blank", "_blank", "_blank"]);
  assert.deepEqual(links.map((link) => link.rel), ["noopener noreferrer", "noopener noreferrer", "noopener noreferrer", "noopener noreferrer"]);
});

test("keeps the Monitoring menu usable without application JavaScript", async () => {
  const index = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const dom = new JSDOM(index);
  const menu = dom.window.document.querySelector("details.monitoring-menu");
  const summary = menu.querySelector("summary");

  assert.equal(menu.open, false);
  summary.click();
  assert.equal(menu.open, true);
  summary.click();
  assert.equal(menu.open, false);
});
