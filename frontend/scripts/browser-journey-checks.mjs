import { switchDemoUser } from "./demo-account-controls.mjs";
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
  return readExpectedJson(await page.request.get(new URL(`/api/v1/investigations/${id}`, page.url()).href));
}

export async function checkReload(page, result) {
  const { investigation, turn } = currentEvidence(result);
  assert.equal(await activeInvestigationId(page), investigation.investigation_id);
  assertHttpStatus(await page.reload());
  await page.waitForFunction(({ id, key, answer }) => {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return stored?.investigationId === id && document.querySelector("#conversation-history")?.textContent.includes(answer);
  }, { id: investigation.investigation_id, key: storageKey, answer: renderedMarker(turn) });
  const reloaded = await readInvestigation(page, investigation.investigation_id, (await browserIdentity(page)).clearance);
  assert.ok(reloaded.turns.some((item) => item.run_id === turn.run_id), "Reload lost the required run.");
}

export async function checkPdf(page, result) {
  const { investigation, turn } = currentEvidence(result);
  const id = investigation.investigation_id;
  assert.equal(await activeInvestigationId(page), id);
  const clearance = (await browserIdentity(page)).clearance;
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/api/v1/investigations/${id}/pdf`;
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
  const clearance = (await browserIdentity(page)).clearance;
  const path = `/api/v1/documents/${encodeURIComponent(reference.document_id)}`;
  const matches = (response, suffix) => {
    const url = new URL(response.url());
    return url.pathname === path + suffix;
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

export async function browserIdentity(page) {
  await page.waitForFunction(() => document.querySelector("#current-user")?.textContent.startsWith("demo-"));
  const user = await readExpectedJson(await page.request.get(new URL("/api/v1/auth/me", page.url()).href));
  assert.equal(await page.locator("#current-user").textContent(), user.username);
  return user;
}

export async function checkIdentitySwitch(page, result, username, httpGuard) {
  const { investigation } = currentEvidence(result);
  const id = requireEvidence(await activeInvestigationId(page), "Required pre-transition investigation ID missing.");
  assert.equal(id, investigation.investigation_id);
  const before = await browserIdentity(page);
  assert.notEqual(username, before.username);
  const protectedText = requireEvidence(investigation.turns.find((turn) => turn.answer)?.answer, "Required pre-transition content missing.");
  assert.ok((await page.locator("#conversation-history").innerText()).includes(protectedText.replace(/[#*`]/g, "").trim()));
  await switchDemoUser(page, username);
  await page.waitForFunction((user) => document.querySelector("#current-user")?.textContent.startsWith(user), username);
  const after = await browserIdentity(page);
  assert.equal(after.username, username);
  await page.waitForFunction(({ key, text }) => !JSON.parse(sessionStorage.getItem(key) ?? "null")?.investigationId
    && !document.querySelector("#conversation-history")?.textContent.includes(text)
    && document.querySelectorAll(".agent-turn, .structured-reference, .document-action").length === 0
    && document.querySelector("#export-pdf-button")?.disabled, { key: storageKey, text: protectedText });
  assert.equal(await activeInvestigationId(page), null);
  const allowedTurns = investigation.turns.filter((turn) => rank[turn.data_classification] <= rank[after.clearance]);
  const deniedTurns = investigation.turns.filter((turn) => rank[turn.data_classification] > rank[after.clearance]);
  for (const suffix of ["", "/pdf"]) {
    const pathname = `/api/v1/investigations/${id}${suffix}`;
    const response = await page.request.get(new URL(pathname, page.url()).href);
    assertHttpStatus(response, [allowedTurns.length ? 200 : 404]);
    if (allowedTurns.length && !suffix) {
      const reauthorized = await readExpectedJson(response);
      assert.equal(reauthorized.investigation_id, id);
      assert.deepEqual(reauthorized.turns.map((turn) => turn.run_id), allowedTurns.map((turn) => turn.run_id));
      assert.ok(reauthorized.turns.every((turn) => rank[turn.data_classification] <= rank[after.clearance]));
      for (const turn of deniedTurns) assert.ok(!reauthorized.turns.some((item) => item.run_id === turn.run_id));
    } else if (!allowedTurns.length) {
      const body = await response.text();
      assert.ok(!body.includes(protectedText) && !body.includes(id), "Denied investigation leaked.");
    } else {
      assert.ok(response.headers()["content-type"].startsWith("application/pdf"));
    }
  }
  evidence.delete(result);
}
export async function checkDeniedDocument(page, reference, clearance) {
  requireEvidence(reference?.document_id, "Required protected document reference missing.");
  const response = await page.request.get(new URL(`/api/v1/documents/${encodeURIComponent(reference.document_id)}/download`, page.url()).href);
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
