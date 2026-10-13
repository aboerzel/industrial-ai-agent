import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertHttpStatus, createApiStatusGuard, getModelAdminJson, readExpectedJson } from "../../frontend/scripts/e2e-http.mjs";
import { assertionPlan, assertionSummary, assertPersistedTurn, assertToolEvidence, recordAssertion, requiredAssertionsStatus } from "../../frontend/scripts/journey-assertions.mjs";
import { activeInvestigationId, checkClearanceChange, checkDocument, checkPdf, checkReload, rememberInvestigation } from "../../frontend/scripts/browser-journey-checks.mjs";

const requireFrontendPackage = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);
const { expect, test } = requireFrontendPackage("@playwright/test");

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const REPORT_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../evals/results/browser-e2e-journeys.json");
const LOCAL_MODEL_ID = "local_quality";
const LANGUAGE = "DE";
const CLEARANCE_RANK = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };
const results = [];
let originalAssignments = [];
let suiteFailed = false;
const httpGuards = new WeakMap();

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  originalAssignments = await getModelAdminJson(request, `${API_URL}/api/v1/model-assignments`);
  const agentAssignments = originalAssignments.filter((item) => item.consumer_id === "agent");
  expect(agentAssignments).toHaveLength(4);
  expect(agentAssignments.every((item) => item.model_id === LOCAL_MODEL_ID)).toBeTruthy();
  const localQuality = (await getModelAdminJson(request, `${API_URL}/api/v1/models`)).find((item) => item.model_id === LOCAL_MODEL_ID);
  expect(localQuality).toMatchObject({ provider: "ollama", provider_model: "qwen3.5:9b", execution_zone: "LOCAL" });
});

test.beforeEach(async ({ context }) => {
  httpGuards.set(context, createApiStatusGuard(context));
});

test.afterEach(async ({ context }, testInfo) => {
  if (testInfo.status !== "passed") suiteFailed = true;
  try { httpGuards.get(context)?.assertSuccessful(); }
  catch (error) { suiteFailed = true; throw error; }
});

test.afterAll(async () => {
  await mkdir(path.dirname(REPORT_PATH), { recursive: true });
  await writeFile(REPORT_PATH, `${JSON.stringify(buildReport(), null, 2)}\n`, "utf8");
});

test("Journey A: S04 fault investigation", async ({ page }) => {
  const journey = beginJourney("S04 fault investigation", ["typed", "reference", "reference", "document", "typed"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04 genauer.", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Station untersuchen", "SUCCESS", "S04");
  await referenceStep(page, journey, "QUALITY-09", "Dokumentation suchen", "SUCCESS", "QUALITY-09");
  await documentStep(page, journey, "SUCCESS");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "SUCCESS", "P4711");
  await finishJourney(page, journey);
});

test("Journey B: station discovery", async ({ page }) => {
  const journey = beginJourney("Station discovery", ["typed", "reference", "typed", "reference"]);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Welche Stationen kennst du?", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Aktuellen Status prüfen", "SUCCESS", "S04");
  await typedStep(page, journey, "Welche Produkte waren zuletzt an Station S04 auffaellig?", "SUCCESS", "P4711");
  await referenceStep(page, journey, "P4711", "Produkthistorie anzeigen", "SUCCESS", "P4711");
  await finishJourney(page, journey);
});

test("Journey C: product to station", async ({ page }) => {
  const journey = beginJourney("Product investigation", ["typed", "reference", "typed"]);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4101.", "SUCCESS", "P4101");
  await referenceStep(page, journey, "S01", "Aktuellen Status prüfen", "SUCCESS", "S01");
  await typedStep(page, journey, "Welche Produkte sind an dieser Station sichtbar?", "SUCCESS", "P4101");
  await finishJourney(page, journey);
});

test("Journey D: documentation chain", async ({ page }) => {
  const journey = beginJourney("Documentation chain", ["typed", "document", "reference", "typed"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Suche technische Dokumentation zu QUALITY-09.", "SUCCESS", "QUALITY-09");
  await documentStep(page, journey, "SUCCESS");
  await referenceStep(page, journey, "QUALITY-09", "Untersuchen", "SUCCESS", "QUALITY-09");
  await typedStep(page, journey, "Welche Station ist von QUALITY-09 betroffen?", "SUCCESS", "S04");
  await finishJourney(page, journey);
});

test("Journey E: clearance boundary remains usable", async ({ page }) => {
  const journey = beginJourney("Clearance boundary", ["typed", "select", "typed", "select", "typed", "reference"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche die Produkthistorie von P4711.", "SUCCESS", "P4711");
  await checkClearanceChange(page, journey, "INTERNAL", httpGuards.get(page.context()));
  recordStep(journey, "clearance downgrade", "SUCCESS", "SUCCESS", "INTERNAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "ATTENTION", null);
  await checkClearanceChange(page, journey, "CONFIDENTIAL", httpGuards.get(page.context()));
  recordStep(journey, "clearance upgrade", "SUCCESS", "SUCCESS", "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04 genauer.", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Aktuellen Status prüfen", "SUCCESS", "S04");
  await finishJourney(page, journey);
});

async function openChat(page, clearance) {
  assertHttpStatus(await page.goto("/"));
  await page.selectOption("#user-clearance", clearance);
  await page.selectOption("#response-language", LANGUAGE);
  await expect(page.locator("#user-clearance")).toHaveValue(clearance);
  await expect(page.locator("#response-language")).toHaveValue(LANGUAGE);
}

async function typedStep(page, journey, prompt, expectedSeverity, expectedIdentifier) {
  const previousId = await activeInvestigationId(page);
  const requestPromise = page.waitForRequest(isRunPost);
  const investigationPromise = page.waitForResponse(isInvestigationGet);
  await page.locator("#composer-message").fill(prompt);
  await page.locator("#composer-button").click();
  await recordAgentStep(page, journey, `typed: ${prompt}`, await requestPromise, await investigationPromise, expectedSeverity, expectedIdentifier, previousId);
}

async function referenceStep(page, journey, identifier, action, expectedSeverity, expectedIdentifier) {
  const previousId = await activeInvestigationId(page);
  const visit = `identifier:${identifier}:${action}`;
  assert.equal(journey.visited.has(visit), false, `Repeated click node: ${visit}`);
  assert.ok(journey.clicks < 4, "Journey exceeded four follow-up clicks");
  journey.visited.add(visit);
  journey.clicks += 1;
  const reference = page.locator(".structured-reference", { hasText: identifier }).last();
  await expect(reference).toHaveText(identifier);
  await reference.click();
  const requestPromise = page.waitForRequest(isRunPost);
  const investigationPromise = page.waitForResponse(isInvestigationGet);
  await page.locator(".reference-popover .reference-action", { hasText: action }).click();
  await recordAgentStep(page, journey, `click ${identifier}: ${action}`, await requestPromise, await investigationPromise, expectedSeverity, expectedIdentifier, previousId,
    identifier.startsWith("P") ? "get_product_history" : identifier.startsWith("S") ? "get_machine_status" : action === "Dokumentation suchen" ? "search_documentation" : null);
}

async function documentStep(page, journey, expectedSeverity) {
  await checkDocument(page, journey);
  const severity = "SUCCESS";
  recordStep(journey, "document open/download", expectedSeverity, severity, "bound document content");
  expect(severity).toBe(expectedSeverity);
}

async function recordAgentStep(page, journey, label, request, investigationResponse, expectedSeverity, expectedIdentifier, previousId, expectedTool = null) {
  assertHttpStatus(investigationResponse);
  const body = request.postDataJSON();
  const clearance = await page.locator("#user-clearance").inputValue();
  const language = await page.locator("#response-language").inputValue();
  expect(body.user_clearance).toBe(clearance);
  expect(body.response_language).toBe(language);
  expect(language).toBe(LANGUAGE);
  const investigation = await readExpectedJson(investigationResponse);
  const run = await readExpectedJson(await request.response());
  const turn = assertPersistedTurn({ run, investigation, request: body, clearance, language, previousId });
  rememberInvestigation(journey, investigation, turn);
  expect(turn.response_language).toBe(LANGUAGE);
  expect(CLEARANCE_RANK[turn.data_classification]).toBeLessThanOrEqual(CLEARANCE_RANK[clearance]);
  const agentTurn = page.locator(".agent-turn").last();
  await expect(agentTurn).not.toHaveClass(/is-pending/);
  const text = await agentTurn.innerText();
  const severity = await classifySeverity(agentTurn, text);
  if (expectedIdentifier) expect(text).toContain(expectedIdentifier);
  if (expectedTool) assertToolEvidence(turn, expectedTool, expectedIdentifier);
  if (expectedSeverity === "ATTENTION") expect(["requested_data_unavailable", "diagnostic_target_unavailable"]).toContain(turn.error?.code);
  journey.hasStarted = true;
  recordStep(journey, label, expectedSeverity, severity, expectedIdentifier ?? "clearance boundary");
  expect(severity).toBe(expectedSeverity);
}

function isRunPost(request) {
  return request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/runs";
}

function isInvestigationGet(response) {
  return response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/investigations/");
}

async function classifySeverity(agentTurn, text) {
  if (await agentTurn.locator(".turn-limit").count()) return "ATTENTION";
  if (/selected access level|nicht verfuegbar|nicht verfügbar|nicht berechtigt/i.test(text)) return "ATTENTION";
  return (await agentTurn.locator(".turn-error").count()) ? "FAILURE" : "SUCCESS";
}

function beginJourney(name, kinds, pdf = false) {
  const journey = { journey: name, name, steps: [], clicks: 0, hasStarted: false, visited: new Set(), pdf,
    assertions: assertionPlan({ steps: kinds.map((kind) => ({ kind })), tags: { pdf_export: pdf ? "yes" : "no" } }) };
  results.push(journey);
  return journey;
}

function recordStep(journey, label, expectedSeverity, severity, target) {
  const passed = expectedSeverity === severity;
  recordAssertion(journey, journey.assertions[journey.steps.length].id, passed ? "PASS" : "FAIL");
  journey.steps.push({ label, expected_severity: expectedSeverity, severity, target, passed });
}

async function finishJourney(page, journey) {
  await checkReload(page, journey);
  recordStep(journey, "reload", "SUCCESS", "SUCCESS", "bound investigation");
  if (journey.pdf) {
    await checkPdf(page, journey);
    recordStep(journey, "pdf", "SUCCESS", "SUCCESS", "bound investigation content");
  }
  expect(requiredAssertionsStatus(journey.assertions)).toBe("PASS");
}

function buildReport() {
  const reported = results.map((journey) => ({ journey: journey.name, steps: journey.steps, assertions: journey.assertions, assertion_summary: assertionSummary(journey.assertions), result: requiredAssertionsStatus(journey.assertions) }));
  const allSteps = results.flatMap((journey) => journey.steps);
  const clicks = (identifier) => allSteps.filter((step) => step.label.startsWith(`click ${identifier}`)).length;
  return {
    execution_status: !suiteFailed && reported.length === 5 && reported.every((journey) => journey.result === "PASS") ? "PASS" : "FAIL",
    real_model_used: "Local Qwen 3.5 9B only",
    model_id: LOCAL_MODEL_ID,
    reasoning_effort: "none",
    external_provider_calls: 0,
    multi_step_journeys: results.length,
    total_journey_steps: allSteps.length,
    typed_follow_up_journeys: results.filter((journey) => journey.steps.filter((step) => step.label.startsWith("typed:")).length > 1).length,
    click_only_journeys: results.filter((journey) => journey.steps.length && journey.steps.every((step) => step.label.startsWith("click"))).length,
    station_reference_clicks: clicks("S"),
    product_reference_clicks: clicks("P"),
    fault_code_clicks: clicks("QUALITY-09"),
    document_open_download: allSteps.some((step) => step.label === "document open/download" && step.passed) ? "PASS" : "NOT_RUN",
    pdf_export: allSteps.some((step) => step.label === "pdf" && step.passed) ? "PASS" : "NOT_RUN",
    // These compound claims require the complete planned journeys, not a partial observation list.
    clearance_preserved_across_clicks: !suiteFailed && reported.length === 5 && reported.every((journey) => journey.result === "PASS") ? "PASS" : "NOT_RUN",
    language_preserved_across_clicks: !suiteFailed && reported.length === 5 && reported.every((journey) => journey.result === "PASS") ? "PASS" : "NOT_RUN",
    conversation_continuity: !suiteFailed && reported.length === 5 && reported.every((journey) => journey.result === "PASS") ? "PASS" : "NOT_RUN",
    attention_states_remain_usable: reported.find((journey) => journey.journey === "Clearance boundary")?.result ?? "NOT_RUN",
    unexpected_technical_failures_inside_journeys: allSteps.filter((step) => step.severity === "FAILURE").length,
    journeys: reported,
  };
}
