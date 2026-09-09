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
      [
        "Prüfe den aktuellen Status von Station S07.",
        "Prüfe die Diagnoseinformationen zu Prototyp P9001.",
      ],
      1,
      "DE",
      [
        { step: 1, action: "get_maintenance_ticket", finding: "MT-6EA0DEF5515A is OPEN." },
        { step: 2, action: "get_machine_status", finding: "Station S04 is FAULTED with QUALITY-09." },
      ],
    ),
    turn(
      SECOND_RUN_ID,
      "Prüfe den ersten empfohlenen Schritt genauer.",
      "### Evidence\n\n- PROTO-COMM-07 is documented.",
      [{ tool: "search_documentation", arguments: { query: "isolated interface loopback" } }],
      ["Search technical documentation for PROTO-COMM-07 error codes."],
      2,
      "EN",
      [{ step: 1, action: "search_documentation", finding: "PROTO-COMM-07 is documented." }],
    ),
  ],
};

const STRUCTURED_NEXT_STEPS_INVESTIGATION = {
  investigation_id: INVESTIGATION_ID,
  created_at: "2026-09-08T08:00:00+00:00",
  run_count: 1,
  tool_call_count: 0,
  status: "success",
  turns: [
    turn(
      FIRST_RUN_ID,
      "Untersuche Stationen S04 und S07.",
      "P4711 failed at station S04. QUALITY-09 needs further investigation.",
      [],
      [
        "Prüfe die jüngere Produkthistorie von P4711 auf wiederkehrende Qualitätsprobleme.",
        "Prüfe den aktuellen Fehlerstatus von Station S04 im Vergleich zum beobachteten QUALITY-09-Fehler.",
        "Vergleiche die Inspektionsergebnisse mit der normalen öffentlichen S04-Inspektionsübersicht.",
        "Prüfe Defektrahmen IMG-324 und vergleiche ihn mit normalen S04-Inspektionsdaten.",
      ],
    ),
  ],
};

test("renders a single-composer investigation workspace", async (t) => {
  await t.test("shows an empty workspace with one enabled composer and disabled PDF export", async () => {
    const { document } = await loadApp();

    assert.equal(document.querySelectorAll("textarea").length, 1);
    assert.equal(document.querySelector("#result-title")?.textContent, "No active chat");
    assert.equal(document.querySelector("#composer-message")?.disabled, false);
    assert.equal(document.querySelector("#composer-button")?.textContent, "Send");
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
      assert.equal(bodies[0].response_language, "EN");
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
      const summaryRows = [...document.querySelectorAll(".investigation-summary tbody tr")];
      assert.equal(summaryRows.length, 3);
      assert.deepEqual(
        summaryRows.map((row) => row.children[1]?.textContent),
        ["get_maintenance_ticket", "get_machine_status", "search_documentation"],
      );
      assert.match(summaryRows[1]?.children[2]?.textContent ?? "", /QUALITY-09/);

      const nextStepActions = [...document.querySelectorAll(".next-step-action")];
      assert.equal(nextStepActions.length, 3);
      assert.equal(nextStepActions[0].getAttribute("aria-label"), "Als Folgefrage übernehmen");
      assert.equal(nextStepActions[2].getAttribute("aria-label"), "Use as follow-up");
      assert.match(nextStepActions[0].parentElement?.textContent ?? "", /Prüfe den aktuellen Status/);

      const runCountBeforeAction = bodies.length;
      nextStepActions[0].click();
      assert.equal(document.querySelector("#composer-message")?.value, "Prüfe den aktuellen Status von Station S07.");
      assert.equal(document.activeElement?.id, "composer-message");
      assert.equal(bodies.length, runCountBeforeAction);

      document.querySelector("#composer-message").value = "Keep this draft.";
      nextStepActions[2].click();
      assert.equal(
        document.querySelector("#composer-message")?.value,
        "Keep this draft.\nSearch technical documentation for PROTO-COMM-07 error codes.",
      );
      assert.equal(bodies.length, runCountBeforeAction);
    } finally {
      restoreFetch();
    }
  });

  await t.test("renders structured historical next steps without inspecting Markdown lists", async () => {
    let runRequests = 0;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/runs")) {
        runRequests += 1;
        return jsonResponse(runResponse());
      }
      return jsonResponse(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    });
    try {
      submit(document, window);
      await settle();

      assert.equal(document.querySelectorAll(".agent-answer .next-step-action").length, 0);
      assert.equal(document.querySelectorAll(".investigation-summary").length, 0);
      assert.equal(document.querySelectorAll(".next-step-section").length, 1);
      const actions = [...document.querySelectorAll(".next-step-action")];
      assert.equal(actions.length, 4);
      assert.equal(document.querySelector(".agent-answer")?.textContent.includes("Recommended Actions"), false);
      assert.match(document.querySelector(".next-step-text")?.textContent ?? "", /Produkthistorie/);

      document.querySelector("#composer-message").value = "Keep this draft.";
      actions[0].click();

      assert.equal(
        document.querySelector("#composer-message").value,
        "Keep this draft.\nPrüfe die jüngere Produkthistorie von P4711 auf wiederkehrende Qualitätsprobleme.",
      );
      assert.equal(document.activeElement?.id, "composer-message");
      assert.equal(runRequests, 1);
    } finally {
      restoreFetch();
    }
  });

  await t.test("does not convert malformed Markdown tables into investigation summaries", async () => {
    const markdownOnlyInvestigation = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    markdownOnlyInvestigation.turns[0].answer = [
      "### Investigation Summary",
      "",
      "\\| Step | Action | Findings / Notes |",
      "\\| 1 | get_machine_status | Station S04 is FAULTED. |",
    ].join("\\n");
    const { document, restoreFetch } = await loadApp(
      () => jsonResponse(markdownOnlyInvestigation),
      { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED" },
    );
    try {
      await settle();

      assert.equal(document.querySelectorAll(".investigation-summary").length, 0);
      assert.match(
        document.querySelector(".agent-answer")?.textContent ?? "",
        /get_machine_status/,
      );
      assert.equal(document.querySelectorAll(".next-step-action").length, 4);
    } finally {
      restoreFetch();
    }
  });

  await t.test("restores persisted structured next steps through the normal history path after reload", async () => {
    let historyRequests = 0;
    const { document, restoreFetch } = await loadApp(
      (url) => {
        assert.match(String(url), new RegExp(`/api/v1/investigations/${INVESTIGATION_ID}`));
        historyRequests += 1;
        return jsonResponse(INVESTIGATION);
      },
      { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED" },
    );
    try {
      await settle();

      assert.equal(historyRequests, 1);
      assert.equal(document.querySelector("#result-title")?.textContent, "Chat");
      assert.equal(document.querySelectorAll(".next-step-action").length, 3);
      assert.equal(document.querySelectorAll(".investigation-summary tbody tr").length, 3);
      assert.equal(document.querySelector("#composer-button")?.textContent, "Send");
    } finally {
      restoreFetch();
    }
  });

  await t.test("keeps legacy turns without next_steps free of action sections", async () => {
    let runRequests = 0;
    const legacyInvestigation = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    delete legacyInvestigation.turns[0].next_steps;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/runs")) {
        runRequests += 1;
        return jsonResponse(runResponse());
      }
      return jsonResponse(legacyInvestigation);
    });
    try {
      submit(document, window);
      await settle();

      assert.equal(runRequests, 1);
      assert.equal(document.querySelectorAll(".next-step-section").length, 0);
      assert.equal(document.querySelectorAll(".next-step-action").length, 0);
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

      assert.equal(document.querySelector("#result-title")?.textContent, "No active chat");
      assert.equal(document.querySelector("#composer-button")?.textContent, "Send");
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

  await t.test("uses the selected response language only for the newly submitted run and restores it", async () => {
    const bodies = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        bodies.push(JSON.parse(options.body));
        return jsonResponse(runResponse());
      }
      return jsonResponse(INVESTIGATION);
    });
    try {
      document.querySelector("#response-language").value = "DE";
      document.querySelector("#response-language").dispatchEvent(new window.Event("change"));
      submit(document, window);
      await settle();
      assert.equal(bodies[0].response_language, "DE");
      assert.equal(
        JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).responseLanguage,
        "DE",
      );
    } finally {
      restoreFetch();
    }
  });

  await t.test("sends with Enter, preserves Shift+Enter, and does not send while composing", async () => {
    const bodies = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        bodies.push(JSON.parse(options.body));
        return jsonResponse(runResponse());
      }
      return jsonResponse(INVESTIGATION);
    });
    try {
      const composer = document.querySelector("#composer-message");
      composer.value = "Investigate P4711.";
      composer.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await settle();
      assert.equal(bodies.length, 1);

      composer.value = "Keep editing";
      composer.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }));
      assert.equal(bodies.length, 1);
      assert.equal(composer.value, "Keep editing");

      composer.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true }));
      assert.equal(bodies.length, 1);
      composer.value = "   ";
      composer.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      assert.equal(bodies.length, 1);
    } finally {
      restoreFetch();
    }
  });

  await t.test("renders only declared references and inserts identifier follow-ups without sending", async () => {
    const referenced = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    referenced.turns[0].answer = "QUALITY-09 affects station S04. Untrusted-99 is not a reference.";
    referenced.turns[0].identifiers = [
      { value: "QUALITY-09", type: "error_code" },
      { value: "S04", type: "station" },
    ];
    referenced.turns[0].documents = [
      {
        document_id: "DOC-001",
        title: "S04 QUALITY-09 Troubleshooting Procedure",
        format: "application/pdf",
      },
      {
        document_id: "DOC-002",
        title: "Quality Inspection Workflow",
        format: "markdown",
      },
    ];
    let requests = 0;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/runs")) requests += 1;
      return jsonResponse(referenced);
    }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "DE" });
    try {
      await settle();
      assert.equal(document.querySelectorAll(".identifier-reference").length, 4);
      const documentReferences = [...document.querySelectorAll(".document-title")];
      assert.deepEqual(
        documentReferences.map((reference) => reference.textContent),
        ["S04 QUALITY-09 Troubleshooting Procedure", "Quality Inspection Workflow"],
      );
      assert.equal(documentReferences.some((reference) => reference.textContent === "Document"), false);
      assert.equal(document.querySelectorAll(".structured-reference").length, 4);
      assert.equal(document.querySelector(".agent-answer")?.textContent.includes("Untrusted-99"), true);
      assert.deepEqual(
        [...document.querySelectorAll(".document-references h4")].map((node) => node.textContent),
        ["Referenzen", "Dokumente"],
      );

      document.querySelector(".identifier-reference").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      const investigate = [...document.querySelectorAll(".reference-action")].find((button) => button.textContent === "Untersuchen");
      investigate.click();
      assert.equal(
        document.querySelector("#composer-message").value,
        "Investigate P4711 at S04.\nUntersuche QUALITY-09 genauer.",
      );
      assert.equal(requests, 0);

      assert.deepEqual(
        [...document.querySelectorAll(".document-action")].map((button) => [button.textContent, button.disabled]),
        [["Öffnen", false], ["Herunterladen", false], ["Öffnen", false], ["Herunterladen", false]],
      );
    } finally {
      restoreFetch();
    }
  });

  await t.test("uses only the secure API document endpoints for Open and Download", async () => {
    const referenced = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    referenced.turns[0].identifiers = [{ value: "QUALITY-09", type: "error_code" }];
    referenced.turns[0].documents = [
      {
        document_id: "DOC-001",
        title: "S04 QUALITY-09 Troubleshooting Procedure",
        format: "application/pdf",
      },
    ];
    const documentRequests = [];
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/documents/")) {
        documentRequests.push(String(url));
        return new Response("authorized document", {
          status: 200,
          headers: {
            "Content-Type": "text/markdown",
            "Content-Disposition": 'attachment; filename="Quality-Procedure.md"',
          },
        });
      }
      return jsonResponse(referenced);
    }, { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    const originalClick = window.HTMLAnchorElement.prototype.click;
    try {
      URL.createObjectURL = () => "blob:authorized-document";
      URL.revokeObjectURL = () => {};
      window.open = () => null;
      window.HTMLAnchorElement.prototype.click = () => {};
      await settle();

      const actions = [...document.querySelectorAll(".document-action")];
      assert.deepEqual(actions.map((button) => button.textContent), ["Open", "Download"]);
      actions[0].click();
      await settle();
      actions[1].click();
      await settle();

      assert.deepEqual(documentRequests, [
        "http://localhost:8000/api/v1/documents/DOC-001?user_clearance=CONFIDENTIAL",
        "http://localhost:8000/api/v1/documents/DOC-001/download?user_clearance=CONFIDENTIAL",
      ]);
      assert.equal(document.querySelector("#composer-message")?.value, "Investigate P4711 at S04.");
      assert.equal(document.querySelector("#error-message")?.hidden, true);
    } finally {
      URL.createObjectURL = originalCreateObjectUrl;
      URL.revokeObjectURL = originalRevokeObjectUrl;
      window.HTMLAnchorElement.prototype.click = originalClick;
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
  assert.match(css, /\.shell \{\n  width: 100%;\n  max-width: none;/);
  assert.doesNotMatch(css, /max-width: 1440px/);
});

async function loadApp(fetchImplementation = null, activeInvestigation = null) {
  const dom = new JSDOM(`<!doctype html><html><body>
    <section class="result-panel"><h2 id="result-title"></h2><p id="investigation-context"></p><div class="toolbar-controls"><label class="clearance-control"><select id="user-clearance"><option value="PUBLIC">PUBLIC</option><option value="INTERNAL">INTERNAL</option><option value="CONFIDENTIAL">CONFIDENTIAL</option><option value="RESTRICTED" selected>RESTRICTED</option></select></label><label class="clearance-control"><select id="response-language"><option value="DE">Deutsch</option><option value="EN" selected>English</option></select></label><span id="run-status" hidden></span><button id="export-pdf-button" type="button"></button><button id="new-investigation-button" type="button"></button></div><dl id="investigation-metadata"><dd id="investigation-runs"></dd><dd id="investigation-tools"></dd></dl><div id="conversation-history"></div><form id="composer-form"><textarea id="composer-message">Investigate P4711 at S04.</textarea><button id="composer-button" type="submit">Send</button></form><p id="error-message" hidden></p></section>
  </body></html>`, { url: "http://localhost:8080" });
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { document: dom.window.document, window: dom.window });
  if (activeInvestigation) {
    dom.window.sessionStorage.setItem(
      "industrial-ai-agent.active-investigation",
      JSON.stringify(activeInvestigation),
    );
  }
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

function turn(
  runId,
  request,
  answer,
  toolCalls,
  nextSteps = [],
  sequence = 1,
  responseLanguage = "DE",
  investigationSteps = [],
) {
  return {
    run_id: runId,
    sequence,
    status: "success",
    data_classification: "RESTRICTED",
    response_language: responseLanguage,
    request,
    answer,
    investigation_steps: investigationSteps,
    next_steps: nextSteps,
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
