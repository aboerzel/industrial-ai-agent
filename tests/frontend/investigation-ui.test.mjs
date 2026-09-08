import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

const dom = new JSDOM(`<!doctype html><html><body>
  <form id="investigation-form"><textarea id="message">Investigate P4711.</textarea><select id="user-clearance"><option value="CONFIDENTIAL" selected>CONFIDENTIAL</option></select><button id="run-button" type="submit">New Investigation</button></form>
  <form id="follow-up-form"><textarea id="follow-up-message"></textarea><button id="follow-up-button" type="submit" disabled>Continue Investigation</button></form>
  <div id="conversation-history"></div><span id="run-status"></span><dd id="investigation-id"></dd><dd id="investigation-summary"></dd><h2 id="result-title"></h2><button id="export-pdf-button"></button><p id="error-message" hidden></p>
</body></html>`, { url: "http://localhost:8080" });

Object.assign(globalThis, { document: dom.window.document, window: dom.window });

test("marks a failed create request as failed instead of leaving the UI running", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({ code: "internal_error", message: "Run failed." }),
    { status: 500, headers: { "Content-Type": "application/json" } },
  );
  try {
    await import(`../../frontend/js/app.js?failure-state=${Date.now()}`);
    document.querySelector("#investigation-form").dispatchEvent(
      new dom.window.Event("submit", { bubbles: true, cancelable: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(document.querySelector("#run-status").dataset.status, "failed");
    assert.equal(document.querySelector("#run-status").textContent, "Failed");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
