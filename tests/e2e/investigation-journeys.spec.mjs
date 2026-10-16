import { setResponseLanguage } from "../../frontend/scripts/demo-account-controls.mjs";
import { selectDemoIdentity } from "../../frontend/scripts/run-e2e-journey.mjs";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { assertHttpStatus, createApiStatusGuard, getModelAdminJson, readExpectedJson } from "../../frontend/scripts/e2e-http.mjs";
import { assertionPlan, assertPersistedTurn, assertStationReferenceEvidence, assertToolEvidence, recordAssertion, requiredAssertionsStatus } from "../../frontend/scripts/journey-assertions.mjs";
import { activeInvestigationId, browserIdentity, checkIdentitySwitch, checkDocument, checkPdf, checkReload, readInvestigation, rememberDenial, rememberInvestigation } from "../../frontend/scripts/browser-journey-checks.mjs";
import { assertNeutralDenial, bootstrapLegacySession, finishLegacyJourney, safeLegacyEvidence, verifyDemoIdentity } from "../../frontend/scripts/legacy-browser-contract.mjs";

const requireFrontendPackage = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);
const { expect, test } = requireFrontendPackage("@playwright/test");

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const LOCAL_MODEL_ID = "local_quality";
const LANGUAGE = "DE";
const CLEARANCE_RANK = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };
const results = [];
let originalAssignments = [];
const httpGuards = new WeakMap();

test.describe.configure({ mode: "default" });

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
  let guardFailure;
  try { httpGuards.get(context)?.assertSuccessful(); }
  catch (error) { guardFailure = error; }
  const journey = results.at(-1);
  if (journey) {
    finishLegacyJourney(journey, guardFailure ? "failed" : testInfo.status);
    await testInfo.attach("legacy-journey", { body: JSON.stringify(safeLegacyEvidence(journey)), contentType: "application/json" });
  }
  if (guardFailure) throw guardFailure;
});

test("Journey A: S04 fault investigation", async ({ page }) => {
  const journey = beginJourney("S04 fault investigation", ["typed", "reference", "reference", "document", "typed"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04.", "SUCCESS", "S04");
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
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "SUCCESS", "P4711");
  await referenceStep(page, journey, "P4711", "Produkthistorie anzeigen", "SUCCESS", "P4711");
  await finishJourney(page, journey);
});

test("Journey C: product to station", async ({ page }) => {
  const journey = beginJourney("Product investigation", ["typed", "reference", "typed"]);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4101.", "SUCCESS", "P4101");
  await referenceStep(page, journey, "S01", "Aktuellen Status prüfen", "SUCCESS", "S01");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4101.", "SUCCESS", "P4101");
  await finishJourney(page, journey);
});

test("Journey D: documentation chain", async ({ page }) => {
  const journey = beginJourney("Documentation chain", ["typed", "document", "reference", "typed"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche QUALITY-09.", "SUCCESS", "QUALITY-09");
  await documentStep(page, journey, "SUCCESS");
  await referenceStep(page, journey, "QUALITY-09", "Untersuchen", "SUCCESS", "QUALITY-09");
  await typedStep(page, journey, "Untersuche Station S04.", "SUCCESS", "S04");
  await finishJourney(page, journey);
});

test("Journey E: clearance boundary remains usable", async ({ page }) => {
  const journey = beginJourney("Clearance boundary", ["typed", "select", "typed", "select", "typed", "reference"], true);
  await openChat(page, "CONFIDENTIAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "SUCCESS", "P4711");
  await checkIdentitySwitch(page, journey, "demo-internal", httpGuards.get(page.context()));
  recordStep(journey, "clearance downgrade", "SUCCESS", "SUCCESS", "INTERNAL");
  await typedStep(page, journey, "Zeige die Produkthistorie von P4711.", "ATTENTION", "P4711");
  await checkIdentitySwitch(page, journey, "demo-confidential", httpGuards.get(page.context()));
  recordStep(journey, "clearance upgrade", "SUCCESS", "SUCCESS", "CONFIDENTIAL");
  await typedStep(page, journey, "Untersuche Station S04.", "SUCCESS", "S04");
  await referenceStep(page, journey, "S04", "Aktuellen Status prüfen", "SUCCESS", "S04");
  await finishJourney(page, journey);
});

async function openChat(page, clearance) {
  results.at(-1).session_setup = await bootstrapLegacySession(page.context(), test.info().project.use.baseURL);
  assertHttpStatus(await page.goto("/"));
  await selectDemoIdentity(page, clearance);
  await setResponseLanguage(page, LANGUAGE);
  verifyDemoIdentity(await browserIdentity(page), `demo-${clearance.toLowerCase()}`);
  await expect(page.locator("#response-language")).toHaveValue(LANGUAGE);
}

async function typedStep(page, journey, prompt, expectedSeverity, expectedIdentifier) {
  const previousId = await activeInvestigationId(page);
  const requestPromise = page.waitForRequest(isRunPost);
  if (expectedSeverity === "ATTENTION") httpGuards.get(page.context()).expectResponse({ method: "POST", pathname: "/api/v1/runs", allowedStatuses: [404, 200] });
  await page.locator("#composer-message").fill(prompt);
  await page.locator("#composer-button").click();
  await recordAgentStep(page, journey, `typed: ${prompt}`, await requestPromise, expectedSeverity, expectedIdentifier, previousId);
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
  await page.locator(".reference-popover .reference-action", { hasText: action }).click();
  await recordAgentStep(page, journey, `click ${identifier}: ${action}`, await requestPromise, expectedSeverity, expectedIdentifier, previousId,
    identifier.startsWith("P") ? "get_product_history" : identifier.startsWith("S") ? "get_machine_status" : action === "Dokumentation suchen" ? "search_documentation" : null);
}

async function documentStep(page, journey, expectedSeverity) {
  await checkDocument(page, journey);
  const severity = "SUCCESS";
  recordStep(journey, "document open/download", expectedSeverity, severity, "bound document content");
  expect(severity).toBe(expectedSeverity);
}

async function recordAgentStep(page, journey, label, request, expectedSeverity, expectedIdentifier, previousId, expectedTool = null) {
  const body = request.postDataJSON();
  const clearance = (await browserIdentity(page)).clearance;
  const language = await page.locator("#response-language").inputValue();
  expect(body.user_clearance).toBeUndefined();
  expect(body.response_language).toBe(language);
  expect(language).toBe(LANGUAGE);
  const response = await request.response();
  assert.ok(response, "Required run response missing.");
  const agentTurn = page.locator(".agent-turn").last();
  await expect(agentTurn).not.toHaveClass(/is-pending/);
  if (expectedSeverity === "ATTENTION" && response.status() === 404) {
    const denial = await response.json();
    assertNeutralDenial(response.status(), denial, expectedIdentifier, await agentTurn.innerText());
    expect(await classifySeverity(agentTurn, await agentTurn.innerText())).toBe("ATTENTION");
    expect(await activeInvestigationId(page)).toBeNull();
    rememberDenial(journey, denial.code);
    recordStep(journey, label, "ATTENTION", "ATTENTION", "neutral denial before allocation");
    return;
  }
  const run = await readExpectedJson(response);
  const investigation = await readInvestigation(page, run.investigation_id, clearance);
  const turn = assertPersistedTurn({ run, investigation, request: body, clearance, language, previousId });
  rememberInvestigation(journey, investigation, turn);
  expect(turn.response_language).toBe(LANGUAGE);
  expect(CLEARANCE_RANK[turn.data_classification]).toBeLessThanOrEqual(CLEARANCE_RANK[clearance]);
  const text = await agentTurn.innerText();
  const severity = await classifySeverity(agentTurn, text);
  if (expectedIdentifier && expectedSeverity === "SUCCESS") expect(text).toContain(expectedIdentifier);
  if (expectedTool === "get_machine_status") assertStationReferenceEvidence(turn, expectedIdentifier);
  else if (expectedTool) assertToolEvidence(turn, expectedTool, expectedIdentifier);
  if (expectedSeverity === "ATTENTION") {
    expect(["requested_data_unavailable", "diagnostic_target_unavailable"]).toContain(turn.error?.code);
    if (expectedIdentifier) expect(text).not.toContain(expectedIdentifier);
  }
  journey.hasStarted = true;
  recordStep(journey, label, expectedSeverity, severity, expectedIdentifier ?? "clearance boundary");
  expect(severity).toBe(expectedSeverity);
}

function isRunPost(request) {
  return request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/runs";
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
