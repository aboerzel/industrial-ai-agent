import { demoAuthFetch, demoUsers } from "./fixtures/demo-auth-fake.mjs";
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

const LIMIT_REACHED_INVESTIGATION = {
  investigation_id: INVESTIGATION_ID,
  created_at: "2026-09-08T08:00:00+00:00",
  run_count: 1,
  tool_call_count: 0,
  status: "completed_with_attention",
  turns: [{
    ...turn(
      FIRST_RUN_ID,
      "Untersuche P4711.",
      null,
      [],
      [],
      1,
      "DE",
    ),
    status: "failed",
    error: {
      code: "llm_rate_limit",
      message: "Das Sprachmodell ist aufgrund eines Nutzungslimits vorübergehend nicht verfügbar. Bitte versuchen Sie es später erneut.",
    },
  }],
};

test("renders a single-composer investigation workspace", async (t) => {
  await t.test("shows an empty workspace with one enabled composer and disabled PDF export", async () => {
    const { document } = await loadApp();

    assert.equal(document.querySelectorAll("textarea").length, 1);
    assert.equal(document.querySelector("#result-title")?.textContent, "Investigation");
    assert.equal(document.querySelector("#composer-message")?.disabled, false);
    assert.equal(document.querySelector("#composer-button")?.getAttribute("aria-label"), "Send message");
    assert.equal(document.querySelector("#export-pdf-button")?.disabled, true);
    assert.equal(document.querySelector("#account-button").closest(".site-header") !== null, true);
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
      document.querySelector("#composer-message").value = "Zeige mir das Ticket MT-6EA0DEF5515A.";
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#composer-button")?.getAttribute("aria-label"), "Send message");
      assert.equal(document.querySelector("#composer-message")?.disabled, false);
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
      assert.equal(bodies[0].investigation_id, undefined);
      assert.equal(bodies[0].user_clearance, undefined);
      assert.equal(bodies[0].response_language, "EN");
      assert.deepEqual(
        [...document.querySelectorAll(".conversation-message .turn-label")].map((node) => node.textContent),
        ["You", "Agent", "You", "Agent"],
      );

      document.querySelector("#composer-message").value = "Prüfe den ersten empfohlenen Schritt genauer.";
      submit(document, window);
      await settle();

      assert.equal(bodies[1].investigation_id, INVESTIGATION_ID);
      assert.equal(bodies[1].user_clearance, undefined);
      assert.equal(document.querySelectorAll("textarea").length, 1);
      assert.equal(document.querySelector("#result-title")?.textContent, "Investigation");
      assert.equal(document.querySelector("#investigation-metadata"), null);

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
      document.querySelector("#composer-message").value = "Keep this draft.";
      nextStepActions[0].click();
      await settle();
      assert.equal(bodies.length, runCountBeforeAction + 1);
      assert.equal(bodies.at(-1).message, "Prüfe den aktuellen Status von Station S07.");
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

      assert.equal(runRequests, 1);
    } finally {
      restoreFetch();
    }
  });

  await t.test("replaces the composer and submits next-step actions through the normal request path", async () => {
    const bodies = [];
    let resolveFollowUp;
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        bodies.push(JSON.parse(options.body));
        if (bodies.length === 1) return jsonResponse(runResponse());
        return new Promise((resolve) => {
          resolveFollowUp = () => resolve(jsonResponse(runResponse(SECOND_RUN_ID)));
        });
      }
      return jsonResponse(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    });
    try {
      submit(document, window);
      await settle();

      const composer = document.querySelector("#composer-message");
      const actions = [...document.querySelectorAll(".next-step-action")];
      const actionText = "Prüfe die jüngere Produkthistorie von P4711 auf wiederkehrende Qualitätsprobleme.";
      composer.value = "Replace this draft.";
      actions[0].click();
      await settle();

      assert.equal(composer.value, actionText);
      assert.equal(bodies.length, 2);
      assert.equal(bodies[1].message, actionText);
      assert.equal(composer.disabled, true);

      actions[1].click();
      assert.equal(bodies.length, 2);

      resolveFollowUp();
      await settle();
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
      assert.equal(document.querySelector("#result-title")?.textContent, "Investigation");
      assert.equal(document.querySelectorAll(".next-step-action").length, 3);
      assert.equal(document.querySelectorAll(".investigation-summary tbody tr").length, 3);
      assert.equal(document.querySelector("#composer-button")?.getAttribute("aria-label"), "Send message");
    } finally {
      restoreFetch();
    }
  });

  await t.test("restores an LLM limit as an amber warning after reload", async () => {
    const { document, restoreFetch } = await loadApp(
      () => jsonResponse(LIMIT_REACHED_INVESTIGATION),
      { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "DE" },
    );
    try {
      await settle();

      const agentTurn = document.querySelector(".agent-turn");
        assert.equal(agentTurn?.classList.contains("is-attention"), true);
      assert.equal(agentTurn?.classList.contains("is-error"), false);
      assert.match(agentTurn?.textContent ?? "", /LLM-Limit erreicht/);
      assert.match(agentTurn?.textContent ?? "", /Nutzungslimits/);
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

  await t.test("shows a provider limit as a warning and does not retry it", async () => {
    let requests = 0;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (!String(url).includes("/api/v1/runs")) return jsonResponse(INVESTIGATION);
      requests += 1;
      return jsonResponse({
        code: "llm_quota_exceeded",
        message: "The language model is temporarily unavailable because its usage limit has been reached. Please try again later.",
      }, 503);
    });
    try {
      submit(document, window);
      await settle();

      assert.equal(requests, 1);
        assert.equal(document.querySelector(".agent-turn.is-attention") !== null, true);
      assert.equal(document.querySelector(".agent-turn.is-error"), null);
      assert.match(document.querySelector(".agent-turn")?.textContent ?? "", /LLM limit reached/);
      assert.equal(document.querySelector("#run-status")?.dataset.status, "limit_reached");
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
    } finally {
      restoreFetch();
    }
  });

  await t.test("exports a transcript-only PDF for a visible pre-run authorization error", async () => {
    const downloads = [];
    const { document, window, restoreFetch } = await loadApp(() => jsonResponse({
      code: "requested_data_unavailable",
      message: "The requested data is unavailable.",
    }, 404));
    const captureDownload = (event) => {
      if (event.target instanceof window.HTMLAnchorElement) {
        downloads.push({ download: event.target.download, href: event.target.href });
        event.preventDefault();
      }
    };
    document.addEventListener("click", captureDownload);
    try {
      document.querySelector("#composer-message").value = "S07";
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
        assert.match(document.querySelector(".agent-turn.is-attention")?.textContent ?? "", /requested data is unavailable/i);
      document.querySelector("#export-pdf-button").click();
      assert.equal(downloads.length, 1);
      assert.equal(downloads[0]?.download, "investigation-transcript.pdf");
      assert.match(downloads[0]?.href ?? "", /^blob:/);
    } finally {
      document.removeEventListener("click", captureDownload);
      restoreFetch();
    }
  });

  await t.test("retains a persisted investigation identity from an internal HTTP failure", async () => {
    const { document, window, restoreFetch } = await loadApp(() => jsonResponse({
      code: "internal_error",
      message: "The agent run could not be completed.",
      investigation_id: INVESTIGATION_ID,
    }, 500));
    try {
      submit(document, window);
      await settle();

      assert.match(document.querySelector(".agent-turn.is-error")?.textContent ?? "", /could not be completed/);
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
      assert.deepEqual(
        JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")),
        {
          investigationId: INVESTIGATION_ID,
          username: "demo-restricted",
          responseLanguage: "EN",
        },
      );
    } finally {
      restoreFetch();
    }
  });

  await t.test("exports a transcript-only PDF for a transport failure", async () => {
    const downloads = [];
    const { document, window, restoreFetch } = await loadApp(async () => {
      throw new TypeError("Network request failed");
    });
    const captureDownload = (event) => {
      if (event.target instanceof window.HTMLAnchorElement) {
        downloads.push(event.target.download);
        event.preventDefault();
      }
    };
    document.addEventListener("click", captureDownload);
    try {
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
      assert.match(document.querySelector(".agent-turn.is-error")?.textContent ?? "", /local agent API is not reachable/);
      document.querySelector("#export-pdf-button").click();
      assert.deepEqual(downloads, ["investigation-transcript.pdf"]);
    } finally {
      document.removeEventListener("click", captureDownload);
      restoreFetch();
    }
  });

  await t.test("enables PDF export for a persisted failed transcript", async () => {
    const failedInvestigation = {
      ...LIMIT_REACHED_INVESTIGATION,
      status: "failed",
    };
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/runs")) {
        return jsonResponse({
          ...runResponse(),
          status: "failed",
          answer: null,
          error: {
            code: "llm_rate_limit",
            message: "The language model is temporarily unavailable.",
          },
        });
      }
      return jsonResponse(failedInvestigation);
    });
    try {
      submit(document, window);
      await settle();

      assert.equal(document.querySelector("#run-status")?.dataset.status, "failed");
      assert.equal(document.querySelector("#export-pdf-button")?.disabled, false);
      assert.match(document.querySelector(".agent-turn")?.textContent ?? "", /LLM-Limit erreicht/);
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
      document.querySelector("#composer-message").value = "Discard this draft.";
      document.querySelector("#new-investigation-button").click();

      assert.equal(document.querySelector("#result-title")?.textContent, "Investigation");
      assert.equal(document.querySelector("#composer-button")?.getAttribute("aria-label"), "Send message");
      assert.equal(document.querySelector("#composer-message")?.disabled, false);
      assert.equal(document.querySelector("#composer-message")?.value, "");
      assert.equal(document.activeElement?.id, "composer-message");
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

  await t.test("renders declared references, submits actions, and copies into the composer without sending", async () => {
    const referenced = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    referenced.turns[0].answer = "QUALITY-09 affects station S04, product P4711, and ticket MT-S02-20260117. P9999 is not a reference.";
    referenced.turns[0].identifiers = [
      { value: "QUALITY-09", type: "error_code" },
      { value: "S04", type: "station" },
      { value: "P4711", type: "product" },
      { value: "MT-S02-20260117", type: "maintenance_ticket" },
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
    const requests = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) requests.push(JSON.parse(options.body));
      return jsonResponse(referenced);
    }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "DE" });
    try {
      await settle();
      assert.equal(document.querySelectorAll(".identifier-reference").length, 8);
      const documentReferences = [...document.querySelectorAll(".document-title")];
      assert.deepEqual(
        documentReferences.map((reference) => reference.textContent),
        ["S04 QUALITY-09 Troubleshooting Procedure", "Quality Inspection Workflow"],
      );
      assert.equal(documentReferences.some((reference) => reference.textContent === "Document"), false);
      assert.equal(document.querySelectorAll(".structured-reference").length, 8);
      assert.deepEqual(
        [...document.querySelectorAll(".identifier-reference")].map((reference) => reference.textContent),
        ["QUALITY-09", "S04", "P4711", "MT-S02-20260117", "QUALITY-09", "S04", "P4711", "MT-S02-20260117"],
      );
      assert.equal(document.querySelector(".agent-answer")?.textContent.includes("P9999"), true);
      assert.equal(
        [...document.querySelectorAll(".structured-reference")].some((reference) => reference.textContent === "P9999"),
        false,
      );
      assert.deepEqual(
        [...document.querySelectorAll(".document-references h4")].map((node) => node.textContent),
        ["Referenzen", "Dokumente"],
      );

      document.querySelector(".identifier-reference").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      const investigate = [...document.querySelectorAll(".reference-action")].find((button) => button.textContent === "Untersuchen");
      document.querySelector("#composer-message").value = "Replace this draft.";
      investigate.click();
      await settle();
      assert.equal(requests.length, 1);
      assert.equal(requests[0].message, "Untersuche QUALITY-09 genauer.");

      const composer = document.querySelector("#composer-message");
      composer.value = "Replace this copied draft.";
      document.querySelector(".identifier-reference").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      const copy = [...document.querySelectorAll(".reference-action")].find((button) => button.textContent === "Kopieren");
      copy.click();
      await settle();
      assert.equal(composer.value, "QUALITY-09");
      assert.equal(document.activeElement, composer);
      assert.equal(requests.length, 1);

      assert.deepEqual(
        [...document.querySelectorAll(".document-action")].map((button) => [button.textContent, button.disabled]),
        [["Öffnen", false], ["Herunterladen", false], ["Öffnen", false], ["Herunterladen", false]],
      );
    } finally {
      restoreFetch();
    }
  });

  await t.test("renders a terminal reference follow-up in the active investigation", async () => {
    const initial = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    initial.turns[0].identifiers = [{ value: "S04", type: "station" }];
    const completed = structuredClone(initial);
    completed.run_count = 2;
    completed.tool_call_count = 1;
    completed.turns.push({
      ...turn(
        SECOND_RUN_ID,
        "Check the current status of station S04.",
        "Station S04 is FAULTED.",
        [{ tool: "get_machine_status", arguments: { station_id: "S04" } }],
        [],
        2,
        "EN",
      ),
      identifiers: [{ value: "S04", type: "station" }],
    });
    let runRequests = 0;
    const bodies = [];
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) {
        runRequests += 1;
        bodies.push(JSON.parse(options.body));
        return jsonResponse(runResponse(SECOND_RUN_ID));
      }
      return jsonResponse(runRequests ? completed : initial);
    }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "EN" });
    try {
      await settle();
      document.querySelector(".identifier-reference").click();
      [...document.querySelectorAll(".reference-action")]
        .find((button) => button.textContent === "Check current status")
        .click();
      await settle();

      assert.equal(bodies[0].investigation_id, INVESTIGATION_ID);
      assert.equal(document.querySelectorAll(".agent-turn").length, 2);
      assert.equal(document.querySelector(".agent-turn:last-child")?.classList.contains("is-pending"), false);
      assert.match(document.querySelector(".agent-turn:last-child")?.textContent ?? "", /S04 is FAULTED/);
    } finally {
      restoreFetch();
    }
  });

  await t.test("renders a typed continuation from its terminal POST response before a delayed refresh", async () => {
    const initial = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    const completed = structuredClone(initial);
    completed.run_count = 2;
    completed.turns.push(terminalTurn(SECOND_RUN_ID, "Check station S04.", "Station S04 is FAULTED."));
    let getRequests = 0;
    let resolveRefresh;
    const { document, window, restoreFetch } = await loadApp((url, options = {}) => {
      if (String(url).includes("/api/v1/runs")) return jsonResponse(terminalRunResponse(SECOND_RUN_ID));
      getRequests += 1;
      if (getRequests === 1) return jsonResponse(initial);
      return new Promise((resolve) => { resolveRefresh = () => resolve(jsonResponse(completed)); });
    }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "EN" });
    try {
      await settle();
      document.querySelector("#composer-message").value = "Check station S04.";
      submit(document, window);
      await settle();

      assert.equal(document.querySelectorAll(".agent-turn").length, 2);
      assert.equal(document.querySelector(".agent-turn:last-child")?.classList.contains("is-pending"), false);
      assert.match(document.querySelector(".agent-turn:last-child")?.textContent ?? "", /Ticket found/);

      resolveRefresh();
      await settle();
      assert.equal(document.querySelectorAll(".agent-turn").length, 2);
      assert.equal(document.querySelectorAll(".agent-turn.is-pending").length, 0);
      assert.match(document.querySelector(".agent-turn:last-child")?.textContent ?? "", /S04 is FAULTED/);
    } finally {
      restoreFetch();
    }
  });

  await t.test("renders terminal success, attention, and failure continuations without pending turns", async (t) => {
    for (const scenario of [
      { status: "success", answer: "Terminal success.", error: null, className: "" },
        { status: "limit_reached", answer: null, error: { code: "llm_rate_limit", message: "Limit reached." }, className: "is-attention" },
      { status: "failed", answer: null, error: { code: "tool_execution_failed", message: "Tool failed." }, className: "is-error" },
    ]) {
      await t.test(scenario.status, async () => {
        const initial = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
        const { document, window, restoreFetch } = await loadApp((url) => {
          if (String(url).includes("/api/v1/runs")) {
            return jsonResponse(terminalRunResponse(SECOND_RUN_ID, scenario));
          }
          return jsonResponse(initial);
        }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "EN" });
        try {
          await settle();
          document.querySelector("#composer-message").value = "Continue investigation.";
          submit(document, window);
          await settle();

          const terminal = document.querySelector(".agent-turn:last-child");
          assert.equal(document.querySelectorAll(".agent-turn").length, 2);
          assert.equal(terminal?.classList.contains("is-pending"), false);
          assert.equal(scenario.className ? terminal?.classList.contains(scenario.className) : true, true);
        } finally {
          restoreFetch();
        }
      });
    }
  });

  await t.test("renders a typed continuation for controlled backend completion latencies", async (t) => {
    for (const latency of ["immediate", "1s", "5s", "10s", "30s", "60s"]) {
      await t.test(latency, async () => {
        const initial = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
        let resolveRun;
        const { document, window, restoreFetch } = await loadApp((url) => {
          if (String(url).includes("/api/v1/runs")) {
            return new Promise((resolve) => { resolveRun = () => resolve(jsonResponse(terminalRunResponse(SECOND_RUN_ID))); });
          }
          return jsonResponse(initial);
        }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "EN" });
        try {
          await settle();
          document.querySelector("#composer-message").value = "Continue investigation.";
          submit(document, window);
          await settle();
          assert.equal(document.querySelector(".agent-turn:last-child")?.classList.contains("is-pending"), true);

          resolveRun();
          await settle();
          assert.equal(document.querySelectorAll(".agent-turn").length, 2);
          assert.equal(document.querySelectorAll(".agent-turn.is-pending").length, 0);
        } finally {
          restoreFetch();
        }
      });
    }
  });

  await t.test("does not let a stale earlier refresh overwrite a newer continuation", async () => {
    const initial = structuredClone(STRUCTURED_NEXT_STEPS_INVESTIGATION);
    let getRequests = 0;
    const refreshResolvers = [];
    let runRequests = 0;
    const { document, window, restoreFetch } = await loadApp((url) => {
      if (String(url).includes("/api/v1/runs")) {
        runRequests += 1;
        return jsonResponse(terminalRunResponse(runRequests === 1 ? SECOND_RUN_ID : FIRST_RUN_ID, {
          status: "success",
          answer: runRequests === 1 ? "First terminal." : "Second terminal.",
          error: null,
        }));
      }
      getRequests += 1;
      if (getRequests === 1) return jsonResponse(initial);
      return new Promise((resolve) => { refreshResolvers.push(() => resolve(jsonResponse(initial))); });
    }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: "EN" });
    try {
      await settle();
      document.querySelector("#composer-message").value = "First continuation.";
      submit(document, window);
      await settle();
      assert.equal(document.querySelector("#composer-button")?.disabled, false);
      document.querySelector("#composer-message").value = "Second continuation.";
      submit(document, window);
      await settle();
      assert.equal(runRequests, 2);

      refreshResolvers[0]();
      await settle();
      assert.equal(document.querySelectorAll(".agent-turn").length, 3);
      assert.equal(document.querySelectorAll(".agent-turn.is-pending").length, 0);
      assert.match(document.querySelector(".agent-turn:last-child")?.textContent ?? "", /Second terminal/);
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
        "/api/v1/documents/DOC-001",
        "/api/v1/documents/DOC-001/download",
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

test("clearance downgrade immediately removes protected conversation and export state", async () => {
  const protectedInvestigation = structuredClone(INVESTIGATION);
  protectedInvestigation.turns[0].answer = "SYNTHETIC CONFIDENTIAL CONTENT";
  protectedInvestigation.turns[0].data_classification = "CONFIDENTIAL";
  const { document, window, restoreFetch } = await loadApp((url) => {
    if (String(url).includes("user_clearance=PUBLIC")) {
      return jsonResponse({ code: "investigation_not_found", message: "Unavailable" }, 404);
    }
    return jsonResponse(protectedInvestigation);
  }, { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    assert.match(document.querySelector("#conversation-history").textContent, /SYNTHETIC CONFIDENTIAL CONTENT/);
    changeClearance(document, window, "PUBLIC");
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC CONFIDENTIAL CONTENT/);
    assert.equal(document.querySelector("#export-pdf-button").disabled, true);
    await settle();
    assert.equal(document.querySelectorAll(".agent-turn").length, 0);
  } finally {
    restoreFetch();
  }
});

test("identity transitions purge old data without transferring another principal's investigation", async (t) => {
  for (const [previous, next] of [["RESTRICTED", "PUBLIC"], ["RESTRICTED", "CONFIDENTIAL"], ["PUBLIC", "CONFIDENTIAL"]]) {
    await t.test(`${previous} -> ${next}`, async () => {
      const original = structuredClone(INVESTIGATION);
      original.turns[0].answer = "SYNTHETIC OLD CONTEXT";
      original.turns[0].data_classification = previous;
      const fresh = structuredClone(INVESTIGATION);
      fresh.turns[0].answer = "Fresh authorized response";
      fresh.turns[0].data_classification = next;
      const requests = [];
      let resolveReload;
      const { document, window, restoreFetch } = await loadApp((url) => {
        requests.push(String(url));
        if (requests.length === 1) return jsonResponse(original);
        return new Promise((resolve) => { resolveReload = resolve; });
      }, { investigationId: INVESTIGATION_ID, userClearance: previous, responseLanguage: "EN" });
      try {
        await settle();
        document.querySelector("#composer-message").value = "SYNTHETIC OLD DRAFT";
        changeClearance(document, window, next);
        assert.doesNotMatch(document.body.textContent, /SYNTHETIC OLD CONTEXT/);
        assert.equal(document.querySelector("#composer-message").value, "");
        assert.equal(document.querySelector("#export-pdf-button").disabled, true);
        await settle();
        assert.equal(requests.length, 1);
        assert.equal(resolveReload, undefined);
        assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
        assert.match(document.querySelector("#account-clearance").textContent, new RegExp(next));
        assert.doesNotMatch(document.body.textContent, /SYNTHETIC OLD CONTEXT/);
      } finally {
        restoreFetch();
      }
    });
  }
});

test("ignores an old submission even after downgrade and upgrade to its original clearance", async () => {
  let resolveOld;
  let oldSignal;
  const { document, window, restoreFetch } = await loadApp((_url, options) => {
    oldSignal = options.signal;
    return new Promise((resolve) => { resolveOld = resolve; });
  });
  try {
    document.querySelector("#composer-message").value = "SYNTHETIC OLD REQUEST";
    submit(document, window);
    changeClearance(document, window, "PUBLIC");
    changeClearance(document, window, "RESTRICTED");
    assert.equal(oldSignal.aborted, true);
    resolveOld(jsonResponse({ ...runResponse(), answer: "SYNTHETIC LATE SECRET" }));
    await settle();
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC (OLD REQUEST|LATE SECRET)/);
    assert.equal(document.querySelector("#export-pdf-button").disabled, true);
    assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
  } finally {
    restoreFetch();
  }
});

test("late old-context JSON parsing cannot overwrite a new investigation view", async () => {
  let resolveOldBody;
  const fresh = structuredClone(INVESTIGATION);
  fresh.turns[0].answer = "New PUBLIC response";
  fresh.turns[0].data_classification = "PUBLIC";
  let calls = 0;
  const { document, window, restoreFetch } = await loadApp((url) => {
    if (++calls === 1) return { ok: true, status: 200, json: () => new Promise((resolve) => { resolveOldBody = resolve; }) };
    if (String(url).includes("/api/v1/runs")) return jsonResponse({ ...runResponse(), answer: "New PUBLIC response", data_classification: "PUBLIC" });
    return jsonResponse(fresh);
  }, { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    changeClearance(document, window, "PUBLIC");
    await settle();
    document.querySelector("#composer-message").value = "New public query";
    submit(document, window);
    await settle();
    const old = structuredClone(INVESTIGATION);
    old.turns[0].answer = "SYNTHETIC OLD JSON SECRET";
    resolveOldBody(old);
    await settle();
    assert.match(document.body.textContent, /New PUBLIC response/);
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC OLD JSON SECRET/);
  } finally {
    restoreFetch();
  }
});

test("navigation between gateway identities purges old UI and reauthorizes restored references", async () => {
  let identity = "A";
  const original = structuredClone(INVESTIGATION);
  original.turns[0].answer = "SYNTHETIC IDENTITY A SECRET";
  const { document, window, restoreFetch } = await loadApp(() => identity === "A"
    ? jsonResponse(original)
    : jsonResponse({ code: "investigation_not_found", message: "Unavailable" }, 404),
  { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    window.dispatchEvent(new window.PageTransitionEvent("pagehide", { persisted: true }));
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC IDENTITY A SECRET/);
    assert.equal(document.querySelector("#export-pdf-button").disabled, true);
    identity = "B";
    window.dispatchEvent(new window.PageTransitionEvent("pageshow", { persisted: true }));
    await settle();
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC IDENTITY A SECRET/);
    assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
  } finally {
    restoreFetch();
  }
});

function changeClearance(document, window, clearance) {
  const username = demoUsers.find((user) => user.clearance === clearance && !user.roles.length).username;
  document.querySelector(`[data-demo-username="${username}"]`).click();
}

test("authentication rejection purges previously visible data", async () => {
  let rejectSession = false;
  const original = structuredClone(INVESTIGATION);
  original.turns[0].answer = "SYNTHETIC EXPIRED SESSION SECRET";
  const { document, window, restoreFetch } = await loadApp(() => rejectSession
    ? jsonResponse({ code: "authentication_required", message: "Authentication required" }, 401)
    : jsonResponse(original),
  { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    rejectSession = true;
    submit(document, window);
    await settle();
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC EXPIRED SESSION SECRET/);
    assert.equal(document.querySelector("#export-pdf-button").disabled, true);
    assert.equal(JSON.parse(window.sessionStorage.getItem("industrial-ai-agent.active-investigation")).investigationId, null);
  } finally {
    restoreFetch();
  }
});

test("same-identity back navigation restores only freshly authorized data", async () => {
  const original = structuredClone(INVESTIGATION);
  original.turns[0].answer = "SYNTHETIC NAVIGATION SECRET";
  const fresh = structuredClone(original);
  fresh.turns[0].answer = "Fresh navigation response";
  let calls = 0;
  const { document, window, restoreFetch } = await loadApp(() => jsonResponse(++calls === 1 ? original : fresh),
    { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    window.dispatchEvent(new window.PageTransitionEvent("pagehide", { persisted: true }));
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC NAVIGATION SECRET/);
    window.dispatchEvent(new window.PageTransitionEvent("pageshow", { persisted: true }));
    await settle();
    assert.match(document.body.textContent, /Fresh navigation response/);
    assert.equal(calls, 2);
  } finally {
    restoreFetch();
  }
});

test("post-downgrade submissions use the narrowed clearance and no denied investigation", async () => {
  const bodies = [];
  const { document, window, restoreFetch } = await loadApp((url, options) => {
    if (String(url).includes("/api/v1/runs")) {
      bodies.push(JSON.parse(options.body));
      return jsonResponse({ ...runResponse(), data_classification: "PUBLIC", answer: "Public result" });
    }
    if (bodies.length) return jsonResponse({ code: "investigation_not_found", message: "Unavailable" }, 404);
    return jsonResponse(INVESTIGATION);
  }, { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    changeClearance(document, window, "PUBLIC");
    await settle();
    document.querySelector("#composer-message").value = "Public query";
    submit(document, window);
    await settle();
    assert.equal(bodies[0].user_clearance, undefined);
    assert.equal(bodies[0].investigation_id, undefined);
    assert.match(document.body.textContent, /Public result/);
  } finally {
    restoreFetch();
  }
});

test("unavailable session storage cannot prevent clearing protected content", async () => {
  const original = structuredClone(INVESTIGATION);
  original.turns[0].answer = "SYNTHETIC STORAGE SECRET";
  const { document, window, restoreFetch } = await loadApp((url) => String(url).includes("user_clearance=PUBLIC")
    ? jsonResponse({ code: "investigation_not_found", message: "Unavailable" }, 404)
    : jsonResponse(original),
  { investigationId: INVESTIGATION_ID, userClearance: "CONFIDENTIAL", responseLanguage: "EN" });
  try {
    await settle();
    window.Storage.prototype.setItem = () => { throw new Error("storage unavailable"); };
    changeClearance(document, window, "PUBLIC");
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC STORAGE SECRET/);
    assert.equal(document.querySelector("#export-pdf-button").disabled, true);
    await settle();
    assert.equal(document.querySelectorAll(".agent-turn").length, 0);
  } finally {
    restoreFetch();
  }
});

test("keeps a full-width workspace and responsive toolbar contract in CSS", async () => {
  const css = await readFile(new URL("../../frontend/css/app.css", import.meta.url), "utf8");

  assert.match(css, /model-assignment-grid-header/);
  assert.match(css, /grid-template-columns:/);
  assert.match(css, /\.toolbar-controls/);
  assert.match(css, /overflow-y: auto/);
  assert.match(css, /@media \(max-width: 520px\)/);
  assert.match(css, /\.shell \{[\s\S]*?width: 100%;[\s\S]*?max-width: none;/);
  assert.doesNotMatch(css, /max-width: 1440px/);
  assert.match(css, /\.header-actions/);
  assert.match(css, /\.toolbar-actions/);
  assert.match(css, /data-status="completed_with_attention"/);
  assert.match(css, /data-status="failed"/);
  assert.match(css, /data-status="limit_reached"[^}]*#fff7df/);
  assert.match(css, /data-status="running"/);
  assert.match(css, /min-width: 76px/);
  assert.match(css, /--color-turn-agent: #2f6b5b;/);
  assert.match(css, /--color-turn-running: #28576e;/);
  assert.match(css, /--color-turn-error: #7c302d;/);
  assert.match(css, /--color-turn-limit: #7b5a13;/);
  assert.match(css, /\.agent-turn \{ border-left: 3px solid var\(--color-turn-agent\)/);
  assert.match(css, /\.agent-turn\.is-pending \{ border-left-color: var\(--color-turn-running-border\)/);
  assert.match(css, /\.agent-turn\.is-error \{ border-left-color: var\(--color-turn-error-border\)/);
  assert.match(css, /\.agent-turn\.is-attention \{ border-left-color: var\(--color-turn-limit-border\)/);
  assert.doesNotMatch(css, /\.agent-turn \{[^}]*#b55a29/);
});

test("uses one workspace heading and accessible compact actions in the shipped page", async () => {
  const index = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");

  assert.match(index, /<h2 id="result-title">Investigation<\/h2>/);
  assert.doesNotMatch(index, />CHAT</);
  assert.doesNotMatch(index, />Chat</);
  assert.doesNotMatch(index, /Active investigation/);
  assert.doesNotMatch(index, /investigation-metadata|investigation-runs|investigation-tools/);
  assert.match(index, /class="header-actions"/);
  assert.doesNotMatch(index, /api-access-token|Access token/);
  assert.match(index, /class="toolbar-actions"/);
  assert.match(index, /id="composer-button" type="submit" aria-label="Send message" title="Send message"/);
  assert.match(index, /id="model-configuration-button"[^>]*aria-label="Model configuration"/);
  assert.match(index, /id="model-configuration-button"[\s\S]*?<svg class="settings-icon"[^>]*width="18" height="18"[^>]*fill="none"/);
  assert.doesNotMatch(index, /id="model-configuration-button"[^>]*>\s*Settings\s*</);
  assert.match(index, /<details class="monitoring-menu">[\s\S]*<summary[^>]*>[\s\S]*Monitoring[\s\S]*<\/summary>/);
  assert.doesNotMatch(index, /id="monitoring-dialog"|monitoring\.js|showModal/);
  assert.doesNotMatch(index, /id="grafana-dashboard-link"/);
  assert.doesNotMatch(index, /<p class="eyebrow">SETTINGS<\/p>/);
  assert.match(index, /class="model-configuration-title-group"/);
});

for (const decision of ["approve", "reject"]) {
  for (const language of ["EN", "DE"]) {
    test(`stale ${decision} retains the displayed token and reloads without retry (${language})`, async () => {
      const a = "68a6b31c-244b-4422-8f24-a3f1d89f9a5c";
      const b = "a9c3b4fb-9a97-45de-a09a-a4e8d91bf7d2";
      const approval = (token, station) => ({
        approval_execution_id: token, action: "create_maintenance_ticket", summary: `Synthetic ${station}`,
        arguments: { station_id: station }, classification: "RESTRICTED", model_id: "local_quality",
        status: "waiting_for_approval", created_at: "2026-10-15T10:00:00Z",
      });
      const investigation = token => ({
        investigation_id: INVESTIGATION_ID, created_at: "2026-10-15T10:00:00Z",
        run_count: 1, tool_call_count: 0, status: "waiting_for_approval",
        turns: [{ ...turn(FIRST_RUN_ID, "Synthetic request", null, [], [], 1, language),
          status: "waiting_for_approval", approval_request: approval(token, token === a ? "S04" : "S02") }],
      });
      let reads = 0;
      const decisions = [];
      const { document, restoreFetch } = await loadApp((url, options) => {
        if (url.endsWith("/resume")) {
          decisions.push(JSON.parse(options.body));
          return jsonResponse({ code: "run_not_waiting_for_approval", message: "Neutral conflict" }, 409);
        }
        if (url.endsWith(INVESTIGATION_ID)) return jsonResponse(investigation(reads++ === 0 ? a : b));
        throw new Error(`Unexpected fixture request: ${url}`);
      }, { investigationId: INVESTIGATION_ID, userClearance: "RESTRICTED", responseLanguage: language });
      try {
        assert.match(document.querySelector(".approval-card").textContent, /S04/);
        document.querySelectorAll(".approval-card button")[decision === "approve" ? 0 : 1].click();
        await settle();
        assert.deepEqual(decisions, [{ decision, approval_execution_id: a }]);
        assert.match(document.querySelector(".approval-card").textContent, /S02/);
        assert.equal(document.querySelector("#error-message").textContent, language === "DE"
          ? "Die Freigabeanforderung hat sich geändert. Bitte prüfen Sie die aktuelle Aktion erneut."
          : "The approval request changed. Please review the current action.");
      } finally { restoreFetch(); }
    });
  }
}

async function loadApp(fetchImplementation = null, activeInvestigation = null) {
  const dom = new JSDOM(await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8"), { url: "http://localhost:8080" });
  dom.window.document.querySelector("#composer-message").value = "Investigate P4711 at S04.";
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { document: dom.window.document, window: dom.window });
  if (activeInvestigation) {
    dom.window.sessionStorage.setItem(
      "industrial-ai-agent.active-investigation",
      JSON.stringify({ ...activeInvestigation, username: demoUsers.find((user) => user.clearance === activeInvestigation.userClearance && !user.roles.length)?.username }),
    );
  }
  const identity = demoUsers.find((user) => user.clearance === (activeInvestigation?.userClearance ?? "RESTRICTED") && !user.roles.length);
  globalThis.fetch = demoAuthFetch(fetchImplementation ?? (() => { throw new Error("Unexpected fixture request"); }), identity.username);
  await import(`../../frontend/js/app.js?workspace=${Date.now()}-${Math.random()}`);
  await settle();
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

function terminalRunResponse(runId, scenario = { status: "success", answer: "Ticket found.", error: null }) {
  return {
    ...runResponse(runId),
    investigation_sequence: 2,
    status: scenario.status,
    answer: scenario.answer,
    error: scenario.error,
  };
}

function terminalTurn(runId, request, answer) {
  return turn(runId, request, answer, [], [], 2, "EN");
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
