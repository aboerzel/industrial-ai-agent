import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const environmentFile = fileURLToPath(new URL("../../.env", import.meta.url));

export async function localEnvironmentValue(key) {
  if (Object.hasOwn(process.env, key)) return process.env[key].trim();
  try {
    const content = await readFile(environmentFile, "utf8");
    const line = content.split(/\r?\n/).find((entry) => entry.startsWith(`${key}=`));
    return line?.slice(key.length + 1).trim().replace(/^['"]|['"]$/g, "") ?? null;
  } catch { return null; }
}

export async function requiredEnvironmentValue(key) {
  const value = await localEnvironmentValue(key);
  if (!value || /[\r\n]/.test(value) || value.startsWith("replace-with-")) {
    throw new Error(`${key} is required for authenticated E2E requests.`);
  }
  return value;
}

export async function modelAdminHeaders() {
  return { Authorization: `Bearer ${await requiredEnvironmentValue("AGENT_API_MODEL_ADMIN_TOKEN")}` };
}

export async function establishBrowserDemoSession(context, frontendUrl) {
  // Playwright's request context shares the browser's cookie jar.
  const response = await context.request.post(new URL("/api/v1/auth/bootstrap", frontendUrl).href, {
    headers: { "X-Demo-Session": "1" }, data: {}, maxRedirects: 0,
  });
  const user = await readExpectedJson(response);
  if (user.username !== "demo-public" || user.clearance !== "PUBLIC" || user.roles.length) {
    throw new Error("Fresh bootstrap did not establish the public demo identity.");
  }
  return user;
}

export async function checkDemoSession(frontendUrl, username) {
  const session = await fetchExpected(new URL("/api/v1/auth/switch", frontendUrl), {
    method: "POST", headers: { "Content-Type": "application/json", "X-Demo-Session": "1" },
    body: JSON.stringify({ username }),
  });
  const cookie = session.headers.get("set-cookie")?.split(";", 1)[0];
  if (!cookie) throw new Error("Demo session cookie missing.");
  try {
    const user = await readExpectedJson(await fetchExpected(new URL("/api/v1/auth/me", frontendUrl), { headers: { Cookie: cookie } }));
    if (user.username !== username) throw new Error("Demo identity mismatch.");
    return user;
  } finally {
    await fetchExpected(new URL("/api/v1/auth/logout", frontendUrl), {
      method: "POST", headers: { Cookie: cookie, "X-Demo-Session": "1" },
    });
  }
}

export function assertHttpStatus(response, allowedStatuses = [200]) {
  const status = typeof response.status === "function" ? response.status() : response.status;
  if (!allowedStatuses.length || !allowedStatuses.includes(status)) {
    throw new Error(`Unexpected HTTP status ${status}; expected ${allowedStatuses.join(" or ")}.`);
  }
  return response;
}

export async function fetchExpected(url, options = {}, allowedStatuses = [200]) {
  let response;
  try { response = await fetch(url, { ...options, redirect: "error" }); }
  catch { throw new Error("E2E HTTP request failed before an expected response was received."); }
  return assertHttpStatus(response, allowedStatuses);
}

export async function readExpectedJson(response) {
  assertHttpStatus(response);
  try { return await response.json(); }
  catch { throw new Error("E2E HTTP response was not valid JSON."); }
}

export async function getModelAdminJson(request, url) {
  const headers = await modelAdminHeaders();
  let response;
  try { response = await request.get(url, { headers, maxRedirects: 0 }); }
  catch { throw new Error("E2E model configuration request failed before an expected response was received."); }
  return readExpectedJson(response);
}

// The observer never stores headers, response bodies, or credentials.
export function createApiStatusGuard(context) {
  const expectations = [];
  const requestStatuses = new WeakMap();
  const failures = [];
  context.on("request", (request) => {
    const url = new URL(request.url());
    const index = expectations.findIndex((expected) => expected.method === request.method()
      && expected.pathname === url.pathname
      && Object.entries(expected.query ?? {}).every(([key, value]) => url.searchParams.get(key) === value));
    requestStatuses.set(request, index < 0 ? [200] : expectations.splice(index, 1)[0].allowedStatuses);
  });
  context.on("response", (response) => {
    if (!new URL(response.url()).pathname.startsWith("/api/v1/")) return;
    try { assertHttpStatus(response, requestStatuses.get(response.request()) ?? [200]); }
    catch (error) { failures.push(error.message); }
  });
  return {
    expectResponse(expectation) { expectations.push(expectation); },
    assertSuccessful() { if (failures.length) throw new Error(failures[0]); },
    takeFailures() { return failures.splice(0); },
  };
}

export function executionStatus(statuses) {
  if (!statuses.length) return "INCOMPLETE";
  for (const status of ["HARNESS_ERROR", "BLOCKED", "FAIL"]) {
    if (statuses.includes(status)) return status;
  }
  return statuses.every((status) => status === "PASS") ? "PASS" : "INCOMPLETE";
}

export function exitCodeForStatuses(statuses) {
  return executionStatus(statuses) === "PASS" ? 0 : 1;
}

export function completedJourneyStatus(result) {
  if (["FAIL", "BLOCKED", "HARNESS_ERROR"].includes(result.status)) return result.status;
  return result.steps.length > 0 && result.steps.every((step) => step.test_result === "PASS")
    && (result.required_smoke ?? ["model_configuration", "monitoring"]).every(key => result.smoke?.[key] === "PASS") ? "PASS" : "FAIL";
}
