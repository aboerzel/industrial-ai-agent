// DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { demoAuthFetch } from "./fixtures/demo-auth-fake.mjs";

const { JSDOM } = createRequire(new URL("../../frontend/package.json", import.meta.url))("jsdom");
const index = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");

async function app(t, username = "demo-public") {
  const dom = new JSDOM(index, { url: "http://localhost:8080" });
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { document: dom.window.document, window: dom.window });
  globalThis.fetch = demoAuthFetch(() => { throw new Error("Unexpected API request"); }, username);
  await import(`../../frontend/js/app.js?demo-auth=${Math.random()}`);
  t.after(() => { globalThis.fetch = originalFetch; dom.window.close(); });
  await settle();
  return { document: dom.window.document, window: dom.window };
}

async function settle() {
  for (let i = 0; i < 8; i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

async function switchUser(document, window, username) {
  document.querySelector(`[data-demo-username="${username}"]`).click();
  await settle();
}

test("header owns account and configuration; investigation toolbar contains only its three actions", async (t) => {
  const { document } = await app(t);
  const header = document.querySelector(".site-header");
  assert.ok(header.querySelector("#account-button"));
  assert.ok(header.querySelector("#model-configuration-button"));
  const toolbar = document.querySelector(".toolbar-controls");
  assert.deepEqual([...toolbar.querySelectorAll("button, summary")].map(node => node.textContent.trim()), ["Monitoring", "PDF", "New Chat"]);
  for (const id of ["current-user", "logout-button", "response-language", "model-configuration-button", "demo-user-list", "user-clearance"]) {
    assert.equal(toolbar.querySelector(`#${id}`), null);
  }
  assert.doesNotMatch(toolbar.textContent, /Logout|Logged out|Language|Configuration|Clearance/);
});

test("account menu exposes identity, language and actions and marks the active server identity", async (t) => {
  const { document } = await app(t);
  document.querySelector("#account-button").click();
  assert.equal(document.querySelector("#account-button").getAttribute("aria-expanded"), "true");
  const panel = document.querySelector("#account-panel");
  assert.equal(panel.hidden, false);
  for (const text of ["demo-public", "PUBLIC", "Roles", "None", "Language", "Switch user", "Logout"]) assert.ok(panel.textContent.includes(text));
  document.querySelector("#switch-user-button").click();
  assert.equal(document.querySelector("#demo-user-list").hidden, false);
  assert.equal(document.querySelectorAll("[data-demo-username]").length, 5);
  assert.equal(document.querySelector('[data-demo-username="demo-public"]').getAttribute("aria-current"), "true");
  assert.equal(document.querySelectorAll('[data-demo-username][aria-current="true"]').length, 1);
});

test("account closes on outside click and Escape; keyboard opens it and restores focus", async (t) => {
  const { document, window } = await app(t);
  const button = document.querySelector("#account-button");
  button.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  assert.equal(document.querySelector("#account-panel").hidden, false);
  assert.equal(document.activeElement.id, "switch-user-button");
  document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(document.querySelector("#account-panel").hidden, true);
  assert.equal(document.activeElement, button);
  button.click();
  document.querySelector("#result-title").click();
  assert.equal(document.querySelector("#account-panel").hidden, true);
});

test("language changes localize account labels without identity mutation, context invalidation or draft loss", async (t) => {
  const { document, window } = await app(t, "demo-confidential");
  let invalidations = 0;
  window.addEventListener("securitycontextchange", () => invalidations++);
  document.querySelector("#composer-message").value = "Keep the current draft";
  const language = document.querySelector("#response-language");
  language.value = "DE";
  language.dispatchEvent(new window.Event("change"));
  assert.equal(document.querySelector("#current-user").textContent, "demo-confidential");
  assert.equal(document.querySelector("#composer-message").value, "Keep the current draft");
  assert.equal(invalidations, 0);
  assert.equal(document.querySelector("#switch-user-button").textContent, "Benutzer wechseln");
  assert.equal(document.querySelector("#logout-button").textContent, "Abmelden");
  assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).responseLanguage, "DE");
});

test("fresh UI shows automatic PUBLIC identity with no clearance selector", async (t) => {
  const { document } = await app(t);
  assert.equal(document.querySelector("#current-user").textContent, "demo-public");
  assert.equal(document.querySelector("#account-clearance").textContent, "PUBLIC");
  assert.equal(document.querySelector("#user-clearance"), null);
  assert.equal(document.querySelector("#model-configuration-button").disabled, true);
  assert.equal(document.querySelector("input[type=password]"), null);
});

test("quick switch uses server metadata and keeps roles orthogonal to clearance", async (t) => {
  const { document, window } = await app(t);
  await switchUser(document, window, "demo-restricted");
  assert.equal(document.querySelector("#current-user").textContent, "demo-restricted");
  assert.equal(document.querySelector("#account-clearance").textContent, "RESTRICTED");
  assert.equal(document.querySelector("#account-roles").textContent, "None");
  assert.equal(document.querySelector("#model-configuration-button").disabled, true);
  assert.equal(document.querySelector("#model-configuration-button").title, "Requires MODEL_ADMIN permission.");
  await switchUser(document, window, "demo-admin");
  assert.equal(document.querySelector("#current-user").textContent, "demo-admin");
  assert.equal(document.querySelector("#account-clearance").textContent, "PUBLIC");
  assert.equal(document.querySelector("#account-roles").textContent, "MODEL_ADMIN");
  assert.equal(document.querySelector("#model-configuration-button").disabled, false);
});

test("logout purges draft, export and session reference; quick selection logs in without passwords", async (t) => {
  const { document, window } = await app(t, "demo-confidential");
  document.querySelector("#composer-message").value = "SYNTHETIC OLD DRAFT";
  document.querySelector("#logout-button").click();
  await settle();
  assert.equal(document.querySelector("#current-user").textContent, "Select demo user");
  assert.equal(document.querySelector("#composer-message").value, "");
  assert.equal(document.querySelector("#composer-button").disabled, true);
  assert.equal(document.querySelector("#export-pdf-button").disabled, true);
  assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
  assert.equal(document.querySelector("#demo-user-list").hidden, false);
  assert.equal(document.querySelectorAll("[data-demo-username]").length, 5);
  assert.equal(document.querySelector("input[type=password]"), null);
  await switchUser(document, window, "demo-internal");
  assert.equal(document.querySelector("#current-user").textContent, "demo-internal");
  assert.equal(document.querySelector("#account-clearance").textContent, "INTERNAL");
});

test("changing identity closes the model dialog and discards its sensitive contents", async (t) => {
  const { document, window } = await app(t, "demo-admin");
  const dialog = document.querySelector("#model-configuration-dialog");
  dialog.setAttribute("open", "");
  dialog.close = () => dialog.removeAttribute("open");
  document.querySelector("#model-configuration-content").textContent = "SYNTHETIC OLD CONFIGURATION";
  await switchUser(document, window, "demo-restricted");
  assert.equal(dialog.open, false);
  assert.equal(document.querySelector("#model-configuration-content").textContent, "");
  assert.equal(document.querySelector("#model-configuration-button").disabled, true);
});

test("disabled demo mode hides all login and quick-switch controls", async (t) => {
  const dom = new JSDOM(index, { url: "http://localhost:8080" });
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { document: dom.window.document, window: dom.window });
  globalThis.fetch = async () => new Response(JSON.stringify({ demo_mode: false, users: [] }));
  await import(`../../frontend/js/app.js?demo-disabled=${Math.random()}`);
  t.after(() => { globalThis.fetch = originalFetch; dom.window.close(); });
  await settle();
  assert.equal(document.querySelector("#account-button").disabled, true);
  assert.equal(document.querySelector("#demo-user-list").hidden, true);
  assert.equal(document.querySelector("#logout-button").hidden, true);
  assert.equal(document.querySelector("#composer-button").disabled, true);
});
