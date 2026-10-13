import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { assertHttpStatus, readExpectedJson } from "./e2e-http.mjs";
import { assertBinaryContent, requireEvidence } from "./journey-assertions.mjs";

const evidence = new WeakMap();
const rank = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };
const storageKey = "industrial-ai-agent.active-investigation";

export async function activeInvestigationId(page) {
  return page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? "null")?.investigationId ?? null, storageKey);
}

export function rememberInvestigation(result, investigation, turn) {
  evidence.set(result, { investigation, turn });
}

export function currentEvidence(result) {
  return requireEvidence(evidence.get(result), "Required investigation evidence missing.");
}

function renderedMarker(turn) {
  return requireEvidence(turn.identifiers?.[0]?.value ?? turn.error?.code
    ?? turn.answer?.replace(/[#*`]/g, "").trim().split("\n")[0], "Required rendered result marker missing.");
}

export async function readInvestigation(page, id, clearance) {
  requireEvidence(id, "Required investigation ID missing.");
  return readExpectedJson(await page.request.get(new URL(`/api/v1/investigations/${id}?user_clearance=${clearance}`, page.url()).href));
}

export async function checkReload(page, result) {
  const { investigation, turn } = currentEvidence(result);
  assert.equal(await activeInvestigationId(page), investigation.investigation_id);
  assertHttpStatus(await page.reload());
  await page.waitForFunction(({ id, key, answer }) => {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return stored?.investigationId === id && document.querySelector("#conversation-history")?.textContent.includes(answer);
  }, { id: investigation.investigation_id, key: storageKey, answer: renderedMarker(turn) });
  const reloaded = await readInvestigation(page, investigation.investigation_id, await page.locator("#user-clearance").inputValue());
  assert.ok(reloaded.turns.some((item) => item.run_id === turn.run_id), "Reload lost the required run.");
}

export async function checkPdf(page, result) {
  const { investigation, turn } = currentEvidence(result);
  const id = investigation.investigation_id;
  assert.equal(await activeInvestigationId(page), id);
  const clearance = await page.locator("#user-clearance").inputValue();
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/api/v1/investigations/${id}/pdf` && url.searchParams.get("user_clearance") === clearance;
  });
  const downloadPromise = page.waitForEvent("download");
  const [response, download] = await Promise.all([responsePromise, downloadPromise, page.locator("#export-pdf-button").click()]);
  assertHttpStatus(response);
  assert.equal(await download.failure(), null, "PDF download failed.");
  const bytes = await readFile(requireEvidence(await download.path(), "PDF download artifact missing."));
  // Current ReportLab export deliberately uses uncompressed content streams.
  const relevant = turn.identifiers?.map((item) => item.value) ?? [];
  assertBinaryContent({ content: bytes, contentType: response.headers()["content-type"], filename: download.suggestedFilename(), expectedFormat: "pdf", expectedId: id,
    expectedText: [turn.data_classification, ...relevant, ...((turn.tool_calls ?? []).map((call) => call.tool))] });
  assert.ok(relevant.length || turn.request?.trim(), "No meaningful export content expectation.");
  if (!relevant.length) {
    // A stable ASCII request fragment also proves content for reference-free turns.
    const fragment = turn.request.match(/[A-Za-z][A-Za-z ]{8,40}/)?.[0]?.trim();
    requireEvidence(fragment, "No supported request fragment for PDF content verification.");
    assertBinaryContent({ content: bytes, contentType: response.headers()["content-type"], filename: download.suggestedFilename(), expectedFormat: "pdf", expectedText: [fragment] });
  }
}

export async function checkDocument(page, result) {
  const { turn } = currentEvidence(result);
  const reference = requireEvidence(turn.documents?.[0], "Required document reference missing.");
  const row = page.locator(".document-references li").filter({ hasText: reference.title }).first();
  const clearance = await page.locator("#user-clearance").inputValue();
  const path = `/api/v1/documents/${encodeURIComponent(reference.document_id)}`;
  const matches = (response, suffix) => {
    const url = new URL(response.url());
    return url.pathname === path + suffix && url.searchParams.get("user_clearance") === clearance;
  };
  const [opened, popup] = await Promise.all([
    page.waitForResponse((response) => matches(response, "")),
    page.waitForEvent("popup"), row.locator("button[title='Open'], button[title='Öffnen']").click(),
  ]);
  assertHttpStatus(opened);
  await popup.waitForURL(/^blob:/);
  const original = Buffer.from(await popup.evaluate(async () => [...new Uint8Array(await (await fetch(location.href)).arrayBuffer())]));
  requireEvidence(original.length, "Opened document content is empty.");
  const [response, download] = await Promise.all([
    page.waitForResponse((response) => matches(response, "/download")),
    page.waitForEvent("download"), row.locator("button[title='Download'], button[title='Herunterladen']").click(),
  ]);
  assertHttpStatus(response);
  assert.equal(await download.failure(), null);
  const bytes = await readFile(requireEvidence(await download.path(), "Document download artifact missing."));
  assert.deepEqual(bytes, original, "Opened and downloaded document content differ.");
  const disposition = response.headers()["content-disposition"];
  const filename = requireEvidence(/filename="([^"\\]+)"/.exec(disposition ?? "")?.[1], "Document filename metadata missing.");
  assert.equal(download.suggestedFilename(), filename, "Document download filename does not match metadata.");
  assertBinaryContent({ content: bytes, contentType: response.headers()["content-type"], filename,
    expectedFormat: reference.format.toLowerCase() === "pdf" ? "pdf" : "document" });
}

export async function checkClearanceChange(page, result, clearance, httpGuard) {
  const { investigation, turn } = currentEvidence(result);
  const id = requireEvidence(await activeInvestigationId(page), "Required pre-transition investigation ID missing.");
  assert.equal(id, investigation.investigation_id);
  const previousClearance = await page.locator("#user-clearance").inputValue();
  assert.notEqual(clearance, previousClearance, "Clearance transition did not change the context.");
  const protectedTurn = investigation.turns.find((item) => rank[item.data_classification] > rank[clearance]);
  if (rank[clearance] < rank[previousClearance]) requireEvidence(protectedTurn?.answer || protectedTurn?.error?.message, "Required visible higher-classification fixture missing.");
  const protectedText = protectedTurn?.identifiers?.[0]?.value ?? protectedTurn?.answer?.replace(/[#*`]/g, "").trim().split("\n")[0] ?? protectedTurn?.error?.message;
  if (protectedText) assert.ok((await page.locator("#conversation-history").innerText()).includes(protectedText), "Protected content was not visible before downgrade.");
  httpGuard.expectResponse({ method: "GET", pathname: `/api/v1/investigations/${id}`, query: { user_clearance: clearance }, allowedStatuses: [200, 404] });
  const [response] = await Promise.all([
    page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/api/v1/investigations/${id}` && url.searchParams.get("user_clearance") === clearance;
    }), page.selectOption("#user-clearance", clearance),
  ]);
  assert.equal(await page.locator("#user-clearance").inputValue(), clearance);
  if (protectedTurn) {
    assertHttpStatus(response, [404]);
    await page.waitForFunction(({ key, text }) => !JSON.parse(sessionStorage.getItem(key) ?? "null")?.investigationId
      && !document.querySelector("#conversation-history")?.textContent.includes(text)
      && document.querySelectorAll(".agent-turn, .structured-reference, .document-action").length === 0
      && document.querySelector("#export-pdf-button")?.disabled, { key: storageKey, text: protectedText });
    assert.equal(await activeInvestigationId(page), null);
    // Use the saved ID, never a purged reference or a privileged runner token.
    const deniedPdf = await page.request.get(new URL(`/api/v1/investigations/${id}/pdf?user_clearance=${clearance}`, page.url()).href);
    assertHttpStatus(deniedPdf, [404]);
    const deniedBody = await deniedPdf.text();
    assert.ok(!deniedBody.includes(protectedText) && !deniedBody.includes(id), "Protected context leaked in export denial.");
    evidence.delete(result);
  } else {
    assertHttpStatus(response);
    const reloaded = await readExpectedJson(response);
    assert.equal(reloaded.investigation_id, id);
    assert.ok(reloaded.turns.every((item) => rank[item.data_classification] <= rank[clearance]));
    rememberInvestigation(result, reloaded, requireEvidence(reloaded.turns.find((item) => item.run_id === turn.run_id), "Transition lost current run."));
  }
}

export async function checkDeniedDocument(page, reference, clearance) {
  requireEvidence(reference?.document_id, "Required protected document reference missing.");
  const response = await page.request.get(new URL(`/api/v1/documents/${encodeURIComponent(reference.document_id)}/download?user_clearance=${clearance}`, page.url()).href);
  assertHttpStatus(response, [404]);
  const body = await response.text();
  assert.ok(!body.includes(reference.document_id) && !body.includes(reference.title), "Protected document leaked in denial.");
}

export async function checkNewChat(page, result) {
  await page.locator("#new-investigation-button").click();
  assert.equal(await activeInvestigationId(page), null);
  assert.equal(await page.locator(".agent-turn").count(), 0);
  assert.equal(await page.locator("#export-pdf-button").isDisabled(), true);
  evidence.delete(result);
}
