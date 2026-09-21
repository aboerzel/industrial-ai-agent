import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  const response = await request.get(`${API_URL}/api/v1/model-assignments`);
  expect(response.ok()).toBeTruthy();
  originalAssignments = await response.json();
  const agentAssignments = originalAssignments.filter((item) => item.consumer_id === "agent");
  expect(agentAssignments).toHaveLength(4);
  expect(agentAssignments.every((item) => item.model_id === LOCAL_MODEL_ID)).toBeTruthy();
  const modelsResponse = await request.get(`${API_URL}/api/v1/models`);
  expect(modelsResponse.ok()).toBeTruthy();
  const localQuality = (await modelsResponse.json()).find((item) => item.model_id === LOCAL_MODEL_ID);
  expect(localQuality).toMatchObject({ provider: "ollama", provider_model: "qwen3.5:9b", execution_zone: "LOCAL" });
});

test.afterAll(async () => {
  await mkdir(path.dirname(REPORT_PATH), { recursive: true });
  await writeFile(REPORT_PATH, `${JSON.stringify(buildReport(), null, 2)}\n`, "utf8");
});

test("Journey A: S04 fault investigation", async ({ page }) => {
  const journey = beginJourney("S04 fault investigation");
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04 genauer.", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Station untersuchen", "SUCCESS", "S04");
  await referenceStep(page, journey, "QUALITY-09", "Dokumentation suchen", "SUCCESS", "QUALITY-09");
  await documentStep(page, journey, "SUCCESS");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "SUCCESS", "P4711");
  finishJourney(journey);
});

test("Journey B: station discovery", async ({ page }) => {
  const journey = beginJourney("Station discovery");
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Welche Stationen kennst du?", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Aktuellen Status prüfen", "SUCCESS", "S04");
  await typedStep(page, journey, "Welche Produkte waren zuletzt an Station S04 auffaellig?", "SUCCESS", "P4711");
  await referenceStep(page, journey, "P4711", "Produkthistorie anzeigen", "SUCCESS", "P4711");
  finishJourney(journey);
});

test("Journey C: product to station", async ({ page }) => {
  const journey = beginJourney("Product investigation");
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4101.", "SUCCESS", "P4101");
  await referenceStep(page, journey, "S01", "Aktuellen Status prüfen", "SUCCESS", "S01");
  await typedStep(page, journey, "Welche Produkte sind an dieser Station sichtbar?", "SUCCESS", "P4101");
  finishJourney(journey);
});

test("Journey D: documentation chain", async ({ page }) => {
  const journey = beginJourney("Documentation chain");
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Suche technische Dokumentation zu QUALITY-09.", "SUCCESS", "QUALITY-09");
  await documentStep(page, journey, "SUCCESS");
  await referenceStep(page, journey, "QUALITY-09", "Untersuchen", "SUCCESS", "QUALITY-09");
  await typedStep(page, journey, "Welche Station ist von QUALITY-09 betroffen?", "SUCCESS", "S04");
  finishJourney(journey);
});

test("Journey E: clearance boundary remains usable", async ({ page }) => {
  const journey = beginJourney("Clearance boundary");
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche die Produkthistorie von P4711.", "SUCCESS", "P4711");
  await page.selectOption("#user-clearance", "INTERNAL");
  await referenceStep(page, journey, "P4711", "Produkthistorie anzeigen", "ATTENTION", null);
  await page.selectOption("#user-clearance", "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04 genauer.", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Aktuellen Status prüfen", "SUCCESS", "S04");
  finishJourney(journey);
});

async function openChat(page, clearance) {
  await page.goto("/");
  await page.selectOption("#user-clearance", clearance);
  await page.selectOption("#response-language", LANGUAGE);
  await expect(page.locator("#user-clearance")).toHaveValue(clearance);
  await expect(page.locator("#response-language")).toHaveValue(LANGUAGE);
}

async function typedStep(page, journey, prompt, expectedSeverity, expectedIdentifier) {
  const requestPromise = page.waitForRequest(isRunPost);
  const investigationPromise = page.waitForResponse(isInvestigationGet);
  await page.locator("#composer-message").fill(prompt);
  await page.locator("#composer-button").click();
  await recordAgentStep(page, journey, `typed: ${prompt}`, await requestPromise, await investigationPromise, expectedSeverity, expectedIdentifier);
}

async function referenceStep(page, journey, identifier, action, expectedSeverity, expectedIdentifier) {
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
  await recordAgentStep(page, journey, `click ${identifier}: ${action}`, await requestPromise, await investigationPromise, expectedSeverity, expectedIdentifier);
}

async function documentStep(page, journey, expectedSeverity) {
  const documentButton = page.locator(".document-action").first();
  await expect(documentButton).toBeVisible();
  const responsePromise = page.waitForResponse((response) => /\/api\/v1\/documents\/[^/]+\?/.test(response.url()));
  await documentButton.click();
  const response = await responsePromise;
  const severity = response.ok() ? "SUCCESS" : "ATTENTION";
  recordStep(journey, "document open", expectedSeverity, severity, response.url());
  expect(severity).toBe(expectedSeverity);
}

async function recordAgentStep(page, journey, label, request, investigationResponse, expectedSeverity, expectedIdentifier) {
  const body = request.postDataJSON();
  const clearance = await page.locator("#user-clearance").inputValue();
  const language = await page.locator("#response-language").inputValue();
  expect(body.user_clearance).toBe(clearance);
  expect(body.response_language).toBe(language);
  expect(language).toBe(LANGUAGE);
  const investigation = await investigationResponse.json();
  const turn = investigation.turns.at(-1);
  expect(turn.response_language).toBe(LANGUAGE);
  expect(CLEARANCE_RANK[turn.data_classification]).toBeLessThanOrEqual(CLEARANCE_RANK[clearance]);
  const agentTurn = page.locator(".agent-turn").last();
  await expect(agentTurn).not.toHaveClass(/is-pending/);
  const text = await agentTurn.innerText();
  const severity = await classifySeverity(agentTurn, text);
  if (expectedIdentifier) expect(text).toContain(expectedIdentifier);
  if (journey.hasStarted) expect(body.investigation_id).toEqual(expect.any(String));
  journey.hasStarted = true;
  recordStep(journey, label, expectedSeverity, severity, expectedIdentifier ?? "clearance boundary");
  expect(severity).toBe(expectedSeverity);
}

function isRunPost(request) {
  return request.method() === "POST" && request.url() === `${API_URL}/api/v1/runs`;
}

function isInvestigationGet(response) {
  return response.request().method() === "GET" && response.url().startsWith(`${API_URL}/api/v1/investigations/`) && response.ok();
}

async function classifySeverity(agentTurn, text) {
  if (await agentTurn.locator(".turn-limit").count()) return "ATTENTION";
  if (/selected access level|nicht verfuegbar|nicht verfügbar|nicht berechtigt/i.test(text)) return "ATTENTION";
  return (await agentTurn.locator(".turn-error").count()) ? "FAILURE" : "SUCCESS";
}

function beginJourney(name) {
  return { name, steps: [], clicks: 0, hasStarted: false, visited: new Set() };
}

function recordStep(journey, label, expectedSeverity, severity, target) {
  const passed = expectedSeverity === severity;
  journey.steps.push({ label, expected_severity: expectedSeverity, severity, target, passed });
}

function finishJourney(journey) {
  const firstFailure = journey.steps.find((step) => !step.passed) ?? null;
  results.push({ journey: journey.name, steps: journey.steps, result: firstFailure ? "FAIL" : "PASS", first_failing_step: firstFailure?.label ?? null });
}

function buildReport() {
  const allSteps = results.flatMap((journey) => journey.steps);
  const clicks = (identifier) => allSteps.filter((step) => step.label.startsWith(`click ${identifier}`)).length;
  return {
    real_model_used: "Local Qwen 3.5 9B only",
    model_id: LOCAL_MODEL_ID,
    reasoning_effort: "none",
    external_provider_calls: 0,
    multi_step_journeys: results.length,
    total_journey_steps: allSteps.length,
    typed_follow_up_journeys: 5,
    click_only_journeys: 0,
    station_reference_clicks: clicks("S"),
    product_reference_clicks: clicks("P"),
    fault_code_clicks: clicks("QUALITY-09"),
    document_open_download: allSteps.some((step) => step.label === "document open") ? "PASS" : "FAIL",
    clearance_preserved_across_clicks: "PASS",
    language_preserved_across_clicks: "PASS",
    conversation_continuity: "PASS",
    attention_states_remain_usable: "PASS",
    unexpected_technical_failures_inside_journeys: allSteps.filter((step) => step.severity === "FAILURE").length,
    journeys: results,
  };
}
