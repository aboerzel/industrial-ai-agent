import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

const INVESTIGATION_ID = "1e5d0e24-92a5-4cb5-9d5d-0f4d7d183ef4";
const FIRST_RUN_ID = "0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8";
const SECOND_RUN_ID = "9b00bbd4-cc3f-4afd-aeee-bcee4edc9b4e";

const INVESTIGATION = {
  investigation_id: INVESTIGATION_ID,
  created_at: "2026-09-08T08:00:00+00:00",
  run_count: 2,
  tool_call_count: 3,
  status: "success",
  turns: [
    turn(
      FIRST_RUN_ID,
      "Zeige mir das Ticket MT-6EA0DEF5515A für Produkt P4711 an Station S04.",
      "### Ticket summary\n\n| Status | Value |\n| --- | --- |\n| State | OPEN |",
      [
        { tool: "get_maintenance_ticket", arguments: { ticket_id: "MT-6EA0DEF5515A" } },
        { tool: "get_machine_status", arguments: { station_id: "S04" } },
      ],
    ),
    turn(
      SECOND_RUN_ID,
      "Prüfe den ersten empfohlenen Schritt genauer.",
      "### Recommended action\n\nInspect the isolated interface loopback.",
      [{ tool: "search_documentation", arguments: { query: "isolated interface loopback" } }],
      2,
    ),
  ],
};

test("renders a single-composer investigation workspace", async (t) => {
  await t.test("shows an empty workspace with one enabled composer and disabled PDF export", async () => {
    const { document } = await loadApp();

    assert.equal(document.querySelectorAll("textarea").length, 1);
    assert.equal(document.querySelector("#result-title")?.textContent, "No active investigation");
    assert.equal(document.querySelector("#composer-message")?.disabled, false);
    assert.equal(document.querySelector("#composer-button")?.textContent, "Start Investigation");
    assert.equal(document.querySelector("#export-pdf-button")?.disabled, true);
    assert.equal(document.querySelector("#user-clearance")?.closest(".toolbar-controls") !== null, true);
    assert.equal(document.querySelector("#run-status")?.hidden, true);
  });

  await t.test("uses the same composer for start and follow-up turns", async () => {
    const bodies = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        bodies.push(JSON.parse(options.body));
        return jsonResponse(runResponse(bodies.length === 1 ? FIRST_RUN_ID : SECOND_RUN_ID));
      }
      return jsonResponse(INVESTIGATION);
    });
    try {
      document.querySelector("#user-clearance").value = "RESTRICTED";
      document.querySelector("#composer-message").value = "Zeige mir das Ticket MT-6EA0DEF5515A.";
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#composer-button")?.textContent, "Send");
      assert.equal(document.querySelector("#composer-message")?.disabled, false);
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
      assert.equal(bodies[0].investigation_id, undefined);
      assert.equal(bodies[0].user_clearance, "RESTRICTED");
      assert.deepEqual(
        [...document.querySelectorAll(".conversation-message .turn-label")].map((node) => node.textContent),
        ["You", "Agent", "You", "Agent"],
      );

      document.querySelector("#user-clearance").value = "INTERNAL";
      document.querySelector("#composer-message").value = "Prüfe den ersten empfohlenen Schritt genauer.";
      submit(document, window);
      await settle();

      assert.equal(bodies[1].investigation_id, INVESTIGATION_ID);
      assert.equal(bodies[1].user_clearance, "INTERNAL");
      assert.equal(document.querySelectorAll("textarea").length, 1);
      assert.equal(document.querySelector("#investigation-context")?.textContent, "P4711 / S04");
      assert.equal(document.querySelector("#investigation-runs")?.textContent, "2");
      assert.equal(document.querySelector("#investigation-tools")?.textContent, "3");

      const details = [...document.querySelectorAll(".agent-turn .tool-details")];
      assert.equal(details[0].open, false);
      assert.deepEqual(
        [...details[0].querySelectorAll(".tool-name")].map((node) => node.textContent),
        ["get_maintenance_ticket", "get_machine_status"],
      );
      assert.deepEqual(
        [...details[1].querySelectorAll(".tool-name")].map((node) => node.textContent),
        ["search_documentation"],
      );
      assert.equal(document.querySelector(".agent-turn .markdown-table-scroll table")?.tagName, "TABLE");
    } finally {
      restoreFetch();
    }
  });

  await t.test("shows pending and failed follow-ups inline without losing history", async () => {
    let runRequests = 0;
    let resolveFollowUp;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (!String(url).includes("/api/v1/runs")) return jsonResponse(INVESTIGATION);
      runRequests += 1;
      if (runRequests === 1) return jsonResponse(runResponse());
      if (runRequests === 2) {
        return new Promise((resolve) => {
          resolveFollowUp = resolve;
        });
      }
      return jsonResponse({ code: "internal_error", message: "Run failed." }, 500);
    });
    try {
      submit(document, window);
      await settle();
      document.querySelector("#composer-message").value = "Check the first recommended action.";
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#run-status")?.textContent, "Investigating");
      assert.equal(document.querySelector("#composer-message")?.disabled, true);
      assert.equal(document.querySelectorAll(".user-turn").length, 3);
      assert.match(document.querySelector(".agent-turn.is-pending")?.textContent ?? "", /Investigating/);

      resolveFollowUp(jsonResponse(runResponse(SECOND_RUN_ID)));
      await settle();
      document.querySelector("#composer-message").value = "One more check.";
      submit(document, window);
      await settle();

      assert.match(document.querySelector(".agent-turn.is-error")?.textContent ?? "", /Investigation step failed/);
      assert.equal(document.querySelector("#run-status")?.textContent, "Failed");
      assert.equal(document.querySelector("#composer-message")?.disabled, false);
    } finally {
      restoreFetch();
    }
  });

  await t.test("clears only active UI context when starting a new investigation", async () => {
    let getRequests = 0;
    const submittedRuns = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        submittedRuns.push(JSON.parse(options.body));
        return jsonResponse(runResponse());
      }
      getRequests += 1;
      return jsonResponse(INVESTIGATION);
    });
    try {
      submit(document, window);
      await settle();
      const requestsBeforeReset = getRequests;
      document.querySelector("#new-investigation-button").click();

      assert.equal(document.querySelector("#result-title")?.textContent, "No active investigation");
      assert.equal(document.querySelector("#composer-button")?.textContent, "Start Investigation");
      assert.equal(document.querySelector("#composer-message")?.disabled, false);
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, true);
      assert.equal(document.querySelectorAll(".conversation-message").length, 0);
      assert.equal(getRequests, requestsBeforeReset);

      document.querySelector("#composer-message").value = "Start a separate investigation.";
      submit(document, window);
      await settle();

      assert.equal(submittedRuns.length, 2);
      assert.equal(submittedRuns[1].investigation_id, undefined);
    } finally {
      restoreFetch();
    }
  });
});

test("keeps a full-width workspace and responsive toolbar contract in CSS", async () => {
  const css = await readFile(new URL("../../frontend/css/app.css", import.meta.url), "utf8");

  assert.doesNotMatch(css, /grid-template-columns/);
  assert.match(css, /\.toolbar-controls/);
  assert.match(css, /overflow-y: auto/);
  assert.match(css, /@media \(max-width: 520px\)/);
  assert.match(css, /width: min\(calc\(100% - 24px\), 760px\);/);
});

async function loadApp(fetchImplementation = null) {
  const dom = new JSDOM(`<!doctype html><html><body>
    <section class="result-panel"><h2 id="result-title"></h2><p id="investigation-context"></p><div class="toolbar-controls"><label class="clearance-control"><select id="user-clearance"><option value="PUBLIC">PUBLIC</option><option value="INTERNAL">INTERNAL</option><option value="RESTRICTED" selected>RESTRICTED</option></select></label><span id="run-status" hidden></span><button id="export-pdf-button" type="button"></button><button id="new-investigation-button" type="button"></button></div><dl id="investigation-metadata"><dd id="investigation-runs"></dd><dd id="investigation-tools"></dd></dl><div id="conversation-history"></div><form id="composer-form"><textarea id="composer-message">Investigate P4711 at S04.</textarea><button id="composer-button" type="submit">Start Investigation</button></form><p id="error-message" hidden></p></section>
  </body></html>`, { url: "http://localhost:8080" });
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { document: dom.window.document, window: dom.window });
  if (fetchImplementation) globalThis.fetch = fetchImplementation;
  await import(`../../frontend/js/app.js?workspace=${Date.now()}-${Math.random()}`);
  return {
    document: dom.window.document,
    window: dom.window,
    restoreFetch: () => {
      globalThis.fetch = originalFetch;
    },
  };
}

function submit(document, window) {
  document.querySelector("#composer-form").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );
}

function turn(runId, request, answer, toolCalls, sequence = 1) {
  return {
    run_id: runId,
    sequence,
    status: "success",
    data_classification: "RESTRICTED",
    response_language: "DE",
    request,
    answer,
    tool_calls: toolCalls,
    created_at: "2026-09-08T08:00:00+00:00",
    updated_at: "2026-09-08T08:00:01+00:00",
    approval_request: null,
  };
}

function runResponse(runId = FIRST_RUN_ID) {
  return {
    run_id: runId,
    investigation_id: INVESTIGATION_ID,
    investigation_sequence: 1,
    status: "success",
    data_classification: "RESTRICTED",
    answer: "Ticket found.",
    tool_calls: [],
    approval_request: null,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}
