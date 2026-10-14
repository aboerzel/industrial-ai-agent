import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { executeStep, startResult } from "../../../frontend/scripts/run-e2e-journey.mjs";
import { assertionSummary, evaluatedJourneyStatus, plannedSteps, requireEvidence } from "../../../frontend/scripts/journey-assertions.mjs";
import { createApiStatusGuard } from "../../../frontend/scripts/e2e-http.mjs";
import { checkDeniedDocument, checkDocument, checkPdf } from "../../../frontend/scripts/browser-journey-checks.mjs";

const { test, expect } = createRequire(new URL("../../../frontend/package.json", import.meta.url))("@playwright/test");
const frontend = fileURLToPath(new URL("../../../frontend/", import.meta.url));
const id = "123e4567-e89b-42d3-a456-426614174000";
const runId = "123e4567-e89b-42d3-a456-426614174001";
const rank = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };
let server;
let origin;
let scenario;
let investigation;
let requests;

test.beforeAll(async () => {
  server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url, origin);
      if (url.pathname.startsWith("/api/")) {
        requests.push({ path: url.pathname, clearance: url.searchParams.get("user_clearance") });
        if (url.pathname === "/api/v1/runs" && request.method === "POST") {
          let raw = "";
          for await (const chunk of request) raw += chunk;
          const body = JSON.parse(raw);
          requests.at(-1).body = body;
          const denied = rank[body.user_clearance] < rank[scenario.classification];
          const turn = {
            run_id: runId, sequence: 1, status: denied ? "failed" : "success",
            data_classification: denied ? body.user_clearance : scenario.classification,
            response_language: body.response_language, request: body.message,
            answer: denied ? null : "The product P4711 has a protected finding at station S04.",
            identifiers: denied ? [] : [{ type: "product", value: "P4711" }, { type: "station", value: "S04" }],
            documents: scenario.document && !denied ? [{ document_id: "synthetic-doc", title: "Synthetic protected document", format: "markdown" }] : [],
            tool_calls: scenario.missingTool || denied ? [] : [{ tool: "get_product_history", arguments: { product_id: "P4711" } }],
            investigation_steps: scenario.missingTool || denied ? [] : [{ step: 1, action: "get_product_history", finding: "P4711 has a recorded fault." }],
            next_steps: [], error: denied ? { code: "requested_data_unavailable", message: "The requested data is not available." } : null,
          };
          investigation = { investigation_id: id, created_at: "2026-10-13T12:00:00Z", run_count: 1, tool_call_count: turn.tool_calls.length, status: turn.status, turns: [turn] };
          return json(response, { run_id: runId, investigation_id: scenario.missingId ? undefined : id, investigation_sequence: 1, ...Object.fromEntries(["status", "data_classification", "answer", "identifiers", "documents", "tool_calls", "investigation_steps", "next_steps", "error"].map((key) => [key, turn[key]])) });
        }
        const clearance = url.searchParams.get("user_clearance");
        if (!investigation || rank[clearance] < rank[investigation.turns[0].data_classification]) return json(response, { code: "investigation_not_found", message: "The requested resource does not exist." }, 404);
        if (url.pathname === `/api/v1/investigations/${id}`) return json(response, investigation);
        if (url.pathname === `/api/v1/investigations/${id}/pdf`) {
          const turn = investigation.turns[0];
          const bytes = syntheticPdf([`Investigation ID: ${scenario.wrongPdfId ? "other-investigation" : id}`, turn.data_classification, turn.request, "P4711 S04 get_product_history"]);
          response.writeHead(200, { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="investigation.pdf"' });
          return response.end(bytes);
        }
        if (url.pathname.startsWith("/api/v1/documents/synthetic-doc")) {
          response.writeHead(200, { "Content-Type": "text/markdown", "Content-Disposition": 'attachment; filename="synthetic-document.md"' });
          return response.end("# Synthetic protected document\nP4711 at S04\n");
        }
        return json(response, { code: "not_found", message: "Unknown fixture route." }, 404);
      }
      const relative = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
      const target = path.resolve(frontend, relative);
      if (!target.startsWith(frontend) || !/^(index\.html|js\/|css\/)/.test(relative)) throw new Error("Unknown fixture asset");
      response.writeHead(200, { "Content-Type": relative.endsWith(".html") ? "text/html" : relative.endsWith(".css") ? "text/css" : "text/javascript" });
      response.end(await readFile(target));
    } catch {
      response.writeHead(500);
      response.end("Fixture request rejected.");
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
});

test.afterAll(async () => { await new Promise((resolve) => server.close(resolve)); });

test.beforeEach(async ({ context, page }) => {
  scenario = { classification: "CONFIDENTIAL" };
  investigation = null;
  requests = [];
  await context.route("**/*", (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await page.goto(origin);
  await page.selectOption("#user-clearance", "CONFIDENTIAL");
  await page.selectOption("#response-language", "EN");
});

function definition(extra = [], pdf = false) {
  return { name: "Synthetic journey", language: "EN", clearance: "CONFIDENTIAL", tags: { pdf_export: pdf ? "yes" : "no" },
    steps: [{ kind: "typed", prompt: "Show the product history for P4711.", expected: "SUCCESS", target: "P4711", tool: "get_product_history" }, ...extra] };
}

async function step(page, context, result, item, index, guard) {
  result.current_assertion_id = `step-${index + 1}:${item.kind}`;
  await executeStep(page, context, result, item, [], [], guard);
  guard.assertSuccessful();
}

test("real DOM submit, bound persisted tool result, reload and actual PDF download execute all requirements", async ({ page, context }) => {
  const plan = definition([], true);
  const result = startResult("fixture", plan, {});
  const guard = createApiStatusGuard(context);
  for (const [index, item] of plannedSteps(plan).entries()) await step(page, context, result, item, index, guard);
  assert.equal(assertionSummary(result.assertions).required_passed, 3);
  assert.ok(requests.some((request) => request.path.endsWith("/pdf") && request.clearance === "CONFIDENTIAL"));
  assert.ok(result.steps.every((item) => item.test_result === "PASS"));
  // Capability smoke is independently tested by Finding 9; this fixture measures assertion coverage.
  result.smoke = { model_configuration: "PASS", monitoring: "PASS" };
  assert.equal(evaluatedJourneyStatus(result), "PASS");
});

for (const classification of ["CONFIDENTIAL", "RESTRICTED"]) {
  for (const clearance of ["PUBLIC", "INTERNAL"]) {
    test(`${classification} -> ${clearance} verifies protected pre-state, purged UI, saved-ID denial and new-context request`, async ({ page, context }) => {
      scenario.classification = classification;
      await page.selectOption("#user-clearance", classification);
      const plan = definition([{ kind: "select", clearance }, { kind: "typed", prompt: "Show the product history for P4711.", expected: "ATTENTION", target: "P4711" }]);
      const result = startResult("fixture", plan, {});
      const guard = createApiStatusGuard(context);
      for (const [index, item] of plan.steps.entries()) await step(page, context, result, item, index, guard);
      await expect(page.locator("#conversation-history")).not.toContainText("protected finding");
      assert.ok(requests.some((request) => request.path === `/api/v1/investigations/${id}/pdf` && request.clearance === clearance));
      assert.equal(requests.filter((request) => request.body).at(-1).body.user_clearance, clearance);
      assert.equal(requests.filter((request) => request.body).at(-1).body.investigation_id, undefined);
    });
  }
}

test("missing investigation ID cannot become a passed measured agent result", async ({ page, context }) => {
  scenario.missingId = true;
  const plan = definition();
  const result = startResult("fixture", plan, {});
  await assert.rejects(step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context)), /Required investigation ID missing/);
  assert.notEqual(evaluatedJourneyStatus(result), "PASS");
});

test("missing recorded tool call fails even when the UI renders a successful answer", async ({ page, context }) => {
  scenario.missingTool = true;
  const plan = definition();
  const result = startResult("fixture", plan, {});
  await assert.rejects(step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context)), /Required tool call missing/);
  assert.notEqual(evaluatedJourneyStatus(result), "PASS");
});

test("required security reference cannot be skipped when pre-transition evidence is missing", async ({ page, context }) => {
  const plan = definition([{ kind: "select", clearance: "PUBLIC" }]);
  const result = startResult("fixture", plan, {});
  await assert.rejects(step(page, context, result, plan.steps[1], 1, createApiStatusGuard(context)), /Required investigation evidence missing/);
  assert.notEqual(evaluatedJourneyStatus(result), "PASS");
});

test("optional missing reference is NOT_RUN in a passing required-assertion report", async ({ page, context }) => {
  const plan = definition([{ kind: "reference", type: "maintenance_ticket", action: "status", expected: "SUCCESS", optional: true }]);
  const result = startResult("fixture", plan, {});
  const guard = createApiStatusGuard(context);
  for (const [index, item] of plannedSteps(plan).entries()) await step(page, context, result, item, index, guard);
  result.smoke = { model_configuration: "PASS", monitoring: "PASS" };
  assert.equal(evaluatedJourneyStatus(result), "PASS");
  assert.equal(assertionSummary(result.assertions).optional[0].status, "NOT_RUN");
  assert.equal(assertionSummary(result.assertions).optional[0].executed, false);
});

test("upgrade reloads under the new selected context", async ({ page, context }) => {
  scenario.classification = "PUBLIC";
  await page.selectOption("#user-clearance", "PUBLIC");
  const plan = definition([{ kind: "select", clearance: "CONFIDENTIAL" }]);
  const result = startResult("fixture", plan, {});
  const guard = createApiStatusGuard(context);
  for (const [index, item] of plannedSteps(plan).entries()) await step(page, context, result, item, index, guard);
  assert.ok(requests.some((request) => request.path === `/api/v1/investigations/${id}` && request.clearance === "CONFIDENTIAL"));
  await expect(page.locator("#conversation-history")).toContainText("P4711");
});

test("wrong investigation PDF fails the real download assertion", async ({ page, context }) => {
  const plan = definition([], true);
  const result = startResult("fixture", plan, {});
  await step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context));
  scenario.wrongPdfId = true;
  await assert.rejects(checkPdf(page, result), /different investigation/);
});

test("missing document reference is BLOCKED rather than silently skipped", async ({ page, context }) => {
  const plan = definition();
  const result = startResult("fixture", plan, {});
  await step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context));
  await assert.rejects(checkDocument(page, result), /Required document reference missing/);
});

test("document open and download preserve bytes and the authoritative response filename", async ({ page, context }) => {
  scenario.document = true;
  const plan = definition();
  const result = startResult("fixture", plan, {});
  await step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context));
  await checkDocument(page, result);
  assert.ok(requests.some((request) => request.path.endsWith("synthetic-doc/download")));
});

test("an incorrect browser filename still fails the document download assertion", async ({ page, context }) => {
  scenario.document = true;
  const plan = definition();
  const result = startResult("fixture", plan, {});
  await step(page, context, result, plan.steps[0], 0, createApiStatusGuard(context));
  await page.evaluate(() => {
    const originalClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      this.download = "stale-name.pdf";
      return originalClick.call(this);
    };
  });
  await assert.rejects(checkDocument(page, result), /filename does not match metadata/);
  assert.ok(requests.some((request) => request.path.endsWith("synthetic-doc/download")));
});

test("explicit protected fixture document download is denied under the lower context", async ({ page, context }) => {
  scenario.document = true;
  const plan = definition([{ kind: "select", clearance: "PUBLIC" }]);
  const result = startResult("fixture", plan, {});
  const guard = createApiStatusGuard(context);
  for (const [index, item] of plan.steps.entries()) await step(page, context, result, item, index, guard);
  await checkDeniedDocument(page, { document_id: "synthetic-doc", title: "Synthetic protected document" }, "PUBLIC");
  assert.ok(requests.some((request) => request.path === "/api/v1/documents/synthetic-doc/download" && request.clearance === "PUBLIC"));
});

function json(response, payload, status = 200) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(payload));
}

function syntheticPdf(lines) {
  const content = `BT /F1 10 Tf 30 750 Td ${lines.map((line) => `(${line.replace(/[\\()]/g, "\\$&")}) Tj 0 -15 Td`).join(" ")} ET`;
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${content.length} >>\nstream\n${content}\nendstream`];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; }
  const xref = pdf.length;
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(requireEvidence(pdf));
}
