import assert from "node:assert/strict";
import { assertHttpStatus, establishBrowserDemoSession, readExpectedJson } from "./e2e-http.mjs";

export const legacyJourneyNames = [
  "Journey A: S04 fault investigation", "Journey B: station discovery",
  "Journey C: product to station", "Journey D: documentation chain",
  "Journey E: clearance boundary remains usable",
];

export function verifyDemoIdentity(user, username) {
  const clearance = username === "demo-admin" ? "PUBLIC" : username.slice(5).toUpperCase();
  assert.deepEqual(user, { username, clearance, roles: username === "demo-admin" ? ["MODEL_ADMIN"] : [] });
  return user;
}

export async function bootstrapLegacySession(context, origin) {
  // This probe belongs only to a fresh journey's cookie jar. Post-auth 401s still fail.
  const initial = await context.request.get(new URL("/api/v1/auth/me", origin).href);
  assertHttpStatus(initial, [401]);
  await establishBrowserDemoSession(context, origin);
  const identity = await readExpectedJson(await context.request.get(new URL("/api/v1/auth/me", origin).href));
  return { initial_auth_status: initial.status(), identity: verifyDemoIdentity(identity, "demo-public") };
}

export function assertNeutralDenial(status, body, target, visible) {
  assert.equal(status, 404);
  assert.ok(["requested_data_unavailable", "diagnostic_target_unavailable"].includes(body?.code));
  assert.equal(body.run_id, undefined);
  assert.equal(body.investigation_id, undefined);
  assert.ok(!target || (!JSON.stringify(body).includes(target) && !visible.includes(target)), "Protected identifier leaked in access denial.");
}

export function finishLegacyJourney(journey, testStatus) {
  const required = journey.assertions.filter(item => item.requirement === "REQUIRED");
  const pending = required.filter(item => item.status === "NOT_RUN");
  const failed = required.some(item => item.status === "FAIL");
  if (testStatus === "passed" && !pending.length && !failed) journey.result = "PASS";
  else {
    journey.result = testStatus === "skipped" ? "BLOCKED" : "FAIL";
    if (!failed && pending.length && testStatus !== "skipped") {
      Object.assign(pending.shift(), { status: "FAIL", executed: true, note: "Journey prerequisite or assertion failed; see Playwright result." });
    }
    for (const assertion of pending) Object.assign(assertion, {
      status: "BLOCKED", executed: false, note: "A required earlier journey step failed.",
    });
  }
  return journey;
}

export function summarizeLegacyJourneys(journeys) {
  const counts = Object.fromEntries(["PASS", "FAIL", "BLOCKED", "HARNESS_ERROR", "NOT_RUN"].map(status => [status, journeys.filter(item => item.result === status).length]));
  return { execution_status: journeys.length > 0 && counts.PASS === journeys.length ? "PASS" : "FAIL", counts, journeys };
}

export function safeLegacyEvidence(journey) {
  // Explicit metadata allowlist: never serialize request bodies, headers, cookies, errors or answers.
  return {
    journey: journey.journey, result: journey.result,
    session_setup: journey.session_setup ? {
      initial_auth_status: journey.session_setup.initial_auth_status,
      identity: verifyDemoIdentity(journey.session_setup.identity, "demo-public"),
    } : null,
    steps: journey.steps.map(({ label, expected_severity, severity, target, passed }) => ({ label, expected_severity, severity, target, passed })),
    assertions: journey.assertions.map(({ id, requirement, status, executed }) => ({ id, requirement, status, executed })),
  };
}
