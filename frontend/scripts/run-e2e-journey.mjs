import { execFile } from "node:child_process";
import { mkdir, open, readFile, rename, writeFile } from "node:fs/promises";
import { promisify } from "node:util";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import {
  assignmentSnapshot,
  assertAssignmentSnapshot,
  calculateHarnessFingerprint,
  createRunMetadata,
  createReadOnlyConfigurationGuard,
  isRunRequestMetadata,
  renderSummaryMarkdown,
  runnerFailure,
  safeRequestMetadata,
  shouldResume,
} from "./manual-e2e-runner-core.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? "http://127.0.0.1:8080";
const CLEARANCE_RANK = { PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3 };
const LOCAL_MODEL_ID = "local_quality";
const execFileAsync = promisify(execFile);
class PreflightBlockedError extends Error {}
const JOURNEYS = {
  "s04-investigation": {
    name: "S04 fault investigation",
    tags: { clearance: "CONFIDENTIAL", language: "de", domain: ["station", "documentation", "rca"], station_state: "faulted", interaction: ["typed", "fault-click", "document-click", "typed-follow-up"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "yes", new_chat: "no" },
    language: "DE",
    clearance: "CONFIDENTIAL",
    steps: [
      { kind: "typed", prompt: "Untersuche Station S04 genauer.", expected: "SUCCESS", target: "S04" },
      { kind: "reference", type: "error_code", action: "search", expected: "SUCCESS" },
      { kind: "document", expected: "SUCCESS" },
      { kind: "typed", prompt: "Zeige die Produkthistorie des zuletzt genannten Produkts.", expected: "SUCCESS" },
    ],
  },
  "station-discovery": {
    name: "Station discovery",
    tags: { clearance: "INTERNAL", language: "en", domain: ["station", "navigation"], station_state: "healthy", interaction: ["typed", "station-click", "typed-follow-up", "product-click"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "EN",
    clearance: "INTERNAL",
    steps: [
      { kind: "typed", prompt: "Which stations are available to me?", expected: "SUCCESS" },
      { kind: "reference", type: "station", action: "status", expected: "SUCCESS" },
      { kind: "typed", prompt: "Which products are visible for that station?", expected: "SUCCESS" },
      { kind: "reference", type: "product", action: "history", expected: "SUCCESS", optional: true },
    ],
  },
  "product-history": {
    name: "Product history",
    tags: { clearance: "PUBLIC", language: "de", domain: ["product", "station"], station_state: "healthy", interaction: ["typed", "station-click", "typed-follow-up"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "DE",
    clearance: "PUBLIC",
    steps: [
      { kind: "typed", prompt: "Zeige die Produkthistorie von P4101.", expected: "SUCCESS", target: "P4101" },
      { kind: "reference", type: "station", action: "status", expected: "SUCCESS" },
      { kind: "typed", prompt: "Welche Produkte sind an dieser Station sichtbar?", expected: "SUCCESS" },
    ],
  },
  documentation: {
    name: "Documentation chain",
    tags: { clearance: "CONFIDENTIAL", language: "en", domain: ["documentation", "station"], station_state: "n/a", interaction: ["typed", "document-click", "fault-click", "typed-follow-up"], expected_user_severity: ["SUCCESS", "ATTENTION"], security_boundary: "yes", multi_turn: "yes", pdf_export: "yes", new_chat: "no" },
    language: "EN",
    clearance: "CONFIDENTIAL",
    steps: [
      { kind: "typed", prompt: "Search technical documentation for QUALITY-09.", expected: "SUCCESS", target: "QUALITY-09" },
      { kind: "document", expected: "SUCCESS" },
      { kind: "select", clearance: "PUBLIC" },
      { kind: "reference", type: "error_code", action: "investigate", expected: "ATTENTION" },
      { kind: "select", clearance: "CONFIDENTIAL" },
      { kind: "typed", prompt: "Which station is affected by this error code?", expected: "SUCCESS" },
    ],
  },
  "clearance-boundary": {
    name: "Clearance boundary and continuation",
    tags: { clearance: "CONFIDENTIAL", language: "de", domain: ["product", "station", "navigation"], station_state: "faulted", interaction: ["typed", "product-click", "typed-follow-up"], expected_user_severity: ["SUCCESS", "ATTENTION"], security_boundary: "yes", multi_turn: "yes", pdf_export: "yes", new_chat: "yes" },
    language: "DE",
    clearance: "CONFIDENTIAL",
    steps: [
      { kind: "typed", prompt: "Untersuche die Produkthistorie von P4711.", expected: "SUCCESS", target: "P4711" },
      { kind: "select", clearance: "INTERNAL" },
      { kind: "reference", type: "product", action: "history", expected: "ATTENTION" },
      { kind: "select", clearance: "CONFIDENTIAL" },
      { kind: "typed", prompt: "Untersuche Station S04 genauer.", expected: "SUCCESS", target: "S04" },
      { kind: "new-chat" },
      { kind: "typed", prompt: "Welche Stationen kennst du?", expected: "SUCCESS" },
    ],
  },
  "station-discovery-de": {
    name: "Station discovery DE",
    tags: { clearance: "RESTRICTED", language: "de", domain: ["station", "navigation"], station_state: "healthy", interaction: ["typed", "station-click", "typed-follow-up"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "DE", clearance: "RESTRICTED",
    steps: [{ kind: "typed", prompt: "Welche Stationen kennst du?", expected: "SUCCESS" }, { kind: "reference", type: "station", action: "status", expected: "SUCCESS" }, { kind: "typed", prompt: "Welche Produkte sind an dieser Station sichtbar?", expected: "SUCCESS" }],
  },
  "healthy-station-de": {
    name: "Healthy station investigation DE",
    tags: { clearance: "PUBLIC", language: "de", domain: ["station", "product"], station_state: "healthy", interaction: ["typed", "station-click", "product-click"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "DE", clearance: "PUBLIC",
    steps: [{ kind: "typed", prompt: "Untersuche Station S01 genauer.", expected: "SUCCESS" }, { kind: "reference", type: "station", action: "status", expected: "SUCCESS" }, { kind: "reference", type: "product", action: "history", expected: "SUCCESS", optional: true }],
  },
  "healthy-station-en": {
    name: "Healthy station investigation EN",
    tags: { clearance: "PUBLIC", language: "en", domain: ["station", "product"], station_state: "healthy", interaction: ["typed", "typed-follow-up", "station-click"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "EN", clearance: "PUBLIC",
    steps: [{ kind: "typed", prompt: "Investigate station S01.", expected: "SUCCESS" }, { kind: "typed", prompt: "What is its current operating status?", expected: "SUCCESS" }, { kind: "reference", type: "station", action: "status", expected: "SUCCESS" }],
  },
  "s04-investigation-en": {
    name: "S04 fault investigation EN",
    tags: { clearance: "CONFIDENTIAL", language: "en", domain: ["station", "documentation", "rca"], station_state: "faulted", interaction: ["typed", "typed-follow-up", "fault-click"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "EN", clearance: "CONFIDENTIAL",
    steps: [{ kind: "typed", prompt: "Investigate station S04 in detail.", expected: "SUCCESS" }, { kind: "typed", prompt: "What does the active fault mean?", expected: "SUCCESS" }, { kind: "reference", type: "error_code", action: "search", expected: "SUCCESS" }],
  },
  "product-centric-en": {
    name: "Product-centric EN",
    tags: { clearance: "INTERNAL", language: "en", domain: ["product", "station"], station_state: "healthy", interaction: ["typed", "product-click", "station-click"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no" },
    language: "EN", clearance: "INTERNAL",
    steps: [{ kind: "typed", prompt: "Show the product history for P4901.", expected: "SUCCESS" }, { kind: "reference", type: "product", action: "history", expected: "SUCCESS" }, { kind: "reference", type: "station", action: "status", expected: "SUCCESS", optional: true }],
  },
  "clearance-boundary-en": {
    name: "Clearance boundary EN",
    tags: { clearance: "INTERNAL", language: "en", domain: ["documentation", "navigation"], station_state: "n/a", interaction: ["typed", "fault-click", "typed-follow-up"], expected_user_severity: ["SUCCESS", "ATTENTION"], security_boundary: "yes", multi_turn: "yes", pdf_export: "yes", new_chat: "yes" },
    language: "EN", clearance: "INTERNAL",
    steps: [{ kind: "typed", prompt: "Which stations are available to me?", expected: "SUCCESS" }, { kind: "typed", prompt: "Search technical documentation for QUALITY-09.", expected: "ATTENTION" }, { kind: "new-chat" }, { kind: "typed", prompt: "Show the current status of station S02.", expected: "SUCCESS" }],
  },
  "restricted-boundary": {
    name: "Restricted information path",
    tags: { clearance: "RESTRICTED", language: "en", domain: ["station", "documentation"], station_state: "faulted", interaction: ["typed", "station-click", "typed-follow-up"], expected_user_severity: ["SUCCESS"], security_boundary: "no", multi_turn: "yes", pdf_export: "no", new_chat: "no", attention_reason: "NOT_APPLICABLE: no fixture above RESTRICTED clearance" },
    language: "EN", clearance: "RESTRICTED",
    steps: [{ kind: "typed", prompt: "Show the current status of station S07.", expected: "SUCCESS" }, { kind: "reference", type: "station", action: "status", expected: "SUCCESS" }, { kind: "typed", prompt: "What documentation is available for this station?", expected: "SUCCESS" }],
  },
};

const command = parseArguments(process.argv.slice(2));
const RUN_ID = command.runId ?? process.env.E2E_RUN_ID ?? "manual-current";
const RESULTS_DIRECTORY = path.join(ROOT, "evals", "results", "browser-e2e", RUN_ID);
const RUN_STARTED_AT = new Date().toISOString();
const RUN_METADATA_BASE = await collectRunMetadata();
let latestAssignmentSnapshot = [];
if (command.preflight) {
  await runPreflight();
} else if (command.comparePath) {
  await compareReports(command.comparePath);
} else if (command.aggregate) {
  await aggregateResults();
} else {
  const requested = command.all ? Object.keys(JOURNEYS) : command.journeys;
  const identifiers = command.resume ? await incompleteJourneys(requested) : requested;
  const outcomes = [];
  for (const id of identifiers) outcomes.push(await runJourney(id));
  process.exitCode = outcomes.includes("FAIL") ? 1 : 0;
}

function parseArguments(arguments_) {
  const journeys = [];
  let aggregate = false;
  let all = false;
  let resume = false;
  let preflight = false;
  let runId = null;
  let comparePath = null;
  for (let index = 0; index < arguments_.length; index += 1) {
    if (arguments_[index] === "--journey") journeys.push(arguments_[++index]);
    else if (arguments_[index] === "--aggregate") aggregate = true;
    else if (arguments_[index] === "--all") all = true;
    else if (arguments_[index] === "--resume") resume = true;
    else if (arguments_[index] === "--preflight") preflight = true;
    else if (arguments_[index] === "--run-id") runId = arguments_[++index];
    else if (arguments_[index] === "--compare") comparePath = arguments_[++index];
    else throw new Error(`Unknown argument: ${arguments_[index]}`);
  }
  if (!preflight && !aggregate && !comparePath && !all && !resume && !journeys.length) throw new Error("Use --journey <id>, --resume, --aggregate, or --compare.");
  for (const journey of journeys) if (!JOURNEYS[journey]) throw new Error(`Unknown journey: ${journey}`);
  return { all, aggregate, comparePath, journeys, preflight, resume, runId };
}

async function collectRunMetadata() {
  const gitHead = (await runGit(["rev-parse", "HEAD"])).trim();
  const dirtyPaths = parseDirtyPaths(await runGit(["status", "--porcelain=v1", "-z", "--untracked-files=all"]));
  return {
    git_head: gitHead,
    dirty_paths: dirtyPaths,
    harness_fingerprint: await effectiveHarnessFingerprint(),
  };
}

async function runGit(arguments_) {
  const { stdout } = await execFileAsync("git", arguments_, { cwd: ROOT, encoding: "buffer" });
  return Buffer.isBuffer(stdout) ? stdout.toString("utf8") : stdout;
}

function parseDirtyPaths(statusOutput) {
  const entries = statusOutput.split("\0").filter(Boolean);
  const paths = new Set();
  for (const entry of entries) {
    const candidate = entry.length >= 4 && /^[ MADRCU?!]{2} /.test(entry)
      ? entry.slice(3)
      : entry;
    const normalized = candidate.replaceAll("\\", "/");
    if (normalized && !normalized.startsWith("../") && !path.isAbsolute(normalized)) paths.add(normalized);
  }
  return [...paths].sort();
}

async function effectiveHarnessFingerprint() {
  const sourcePaths = [
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/playwright.config.mjs",
    "frontend/scripts/manual-e2e-runner-core.mjs",
    "frontend/scripts/run-e2e-journey.mjs",
    "frontend/scripts/run-manual-e2e.mjs",
    "tests/e2e/investigation-journeys.spec.mjs",
  ];
  const entries = await Promise.all(sourcePaths.map(async (relativePath) => ({
    path: relativePath,
    content: await readFile(path.join(ROOT, relativePath)),
  })));
  return calculateHarnessFingerprint(entries);
}

function currentRunMetadata(finishedAt = null) {
  return createRunMetadata({
    runId: RUN_ID,
    startedAt: RUN_STARTED_AT,
    finishedAt,
    gitHead: RUN_METADATA_BASE.git_head,
    dirtyPaths: RUN_METADATA_BASE.dirty_paths,
    dirtyScope: classifyDirtyScope(RUN_METADATA_BASE.dirty_paths),
    harnessFingerprint: RUN_METADATA_BASE.harness_fingerprint,
    assignmentSnapshot: latestAssignmentSnapshot,
  });
}

function classifyDirtyScope(paths) {
  const harnessPaths = new Set([
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/playwright.config.mjs",
    "frontend/scripts/manual-e2e-runner-core.mjs",
    "frontend/scripts/run-e2e-journey.mjs",
    "frontend/scripts/run-manual-e2e.mjs",
    "tests/e2e/investigation-journeys.spec.mjs",
    "tests/frontend/manual-e2e-runner.test.mjs",
    "docs/learning/browser-e2e-journeys.md",
  ]);
  const harnessGenerated = ["frontend/test-results/", "evals/results/browser-e2e/"];
  return paths.every((entry) => harnessPaths.has(entry) || harnessGenerated.some((prefix) => entry.startsWith(prefix)))
    ? "HARNESS_ONLY"
    : "MIXED_OR_UNKNOWN";
}

async function runPreflight() {
  const checks = [];
  const check = async (name, operation) => {
    try { checks.push({ name, status: "PASS", detail: await operation() }); }
    catch (error) { checks.push({ name, status: "BLOCKED", detail: error.message }); }
  };
  await check("frontend", async () => `${(await fetch(FRONTEND_URL)).status}`);
  await check("agent-api", async () => `${(await fetch(`${API_URL}/api/v1/models`)).status}`);
  await check("factory-mcp", async () => probeMcpReadiness("http://127.0.0.1:8001/mcp", ["get_machine_status", "get_product_history"]));
  await check("knowledge-mcp", async () => probeMcpReadiness("http://127.0.0.1:8002/mcp", ["search_documentation"]));
  await check("ollama", async () => {
    const tags = await fetchJson("http://127.0.0.1:11434/api/tags");
    if (!tags.models?.some((model) => model.name === "qwen3.5:9b")) throw new Error("qwen3.5:9b is not installed in local Ollama");
    return "qwen3.5:9b";
  });
  await check("playwright", async () => {
    const executable = chromium.executablePath();
    if (!executable) throw new Error("Chromium executable unavailable");
    return executable;
  });
  await check("model-assignments", async () => {
    const assignments = await fetchJson(`${API_URL}/api/v1/model-assignments`);
    latestAssignmentSnapshot = assignmentSnapshot(assignments);
    const rows = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].map((classification) => {
      const assignment = assignments.find((item) => item.consumer_id === "agent" && item.data_classification === classification);
      return `${classification} ${assignment?.model_id ?? `${assignment?.selection_mode}/${assignment?.selection_policy}`} ${assignment?.model_id === LOCAL_MODEL_ID ? "PASS" : "BLOCKED"}`;
    });
    if (rows.some((row) => row.endsWith("BLOCKED"))) throw new Error(rows.join(" | "));
    return rows.join(" | ");
  });
  await check("local-quality", async () => {
    const models = await fetchJson(`${API_URL}/api/v1/models`);
    const model = models.find((item) => item.model_id === LOCAL_MODEL_ID);
    if (!model || model.provider !== "ollama" || model.provider_model !== "qwen3.5:9b" || model.execution_zone !== "LOCAL") throw new Error("local_quality is not Local Qwen 3.5 9B in LOCAL zone");
    return "Local Qwen 3.5 9B";
  });
  await check("result-directory", async () => { await mkdir(RESULTS_DIRECTORY, { recursive: true }); return RESULTS_DIRECTORY; });
  const blocked = checks.some((check_) => check_.status !== "PASS");
  const finishedAt = new Date().toISOString();
  const report = {
    metadata: currentRunMetadata(finishedAt),
    run_id: RUN_ID,
    started_at: RUN_STARTED_AT,
    finished_at: finishedAt,
    checks,
    status: blocked ? "BLOCKED" : "PASS",
  };
  await writeAtomically(path.join(RESULTS_DIRECTORY, "preflight.json"), report);
  for (const check_ of checks) console.log(`${check_.name.padEnd(18)} ${check_.status.padEnd(7)} ${check_.detail}`);
  if (blocked) process.exitCode = 1;
}

async function runJourney(id) {
  const definition = JOURNEYS[id];
  const result = startResult(id, definition, currentRunMetadata());
  let browser;
  let context;
  let page;
  let configurationGuard;
  let configurationSnapshot;
  let operation = "startup";
  try {
    await assertLocalOnlyPreflight();
    configurationSnapshot = assignmentSnapshot(
      await fetchJson(`${API_URL}/api/v1/model-assignments`),
    );
    latestAssignmentSnapshot = configurationSnapshot;
    result.metadata = currentRunMetadata();
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ acceptDownloads: true });
    configurationGuard = createReadOnlyConfigurationGuard(context);
    page = await context.newPage();
    const clientErrors = [];
    const failedFetches = [];
    page.on("pageerror", (error) => clientErrors.push(error.message));
    page.on("requestfailed", (request) => {
      if (!request.url().endsWith("/favicon.ico")) failedFetches.push(request.url());
    });
    operation = "prepare page";
    await preparePage(page, definition);
    configurationGuard.assertUnchanged(operation);
    for (const step of definition.steps) {
      operation = step.kind;
      await assertConfigurationSnapshot(configurationSnapshot, `before ${operation}`);
      await executeStep(page, context, result, step, clientErrors, failedFetches);
      configurationGuard.assertUnchanged(operation);
    }
    operation = "smoke controls";
    await smokeControls(page, result);
    configurationGuard.assertUnchanged(operation);
  } catch (error) {
    if (error instanceof PreflightBlockedError) {
      result.runner_error = { name: error.name, message: error.message };
      result.status = "BLOCKED";
      result.runner_result = "BLOCKED";
    } else {
      result.runner_error = runnerFailure(error, operation, await browserPageState(page, context, browser));
      result.status = "HARNESS_ERROR";
    }
  } finally {
    try {
      configurationGuard?.assertUnchanged(operation);
      if (configurationSnapshot) {
        await assertConfigurationSnapshot(configurationSnapshot, "after journey");
      }
    } catch (error) {
      result.runner_error ??= runnerFailure(error, operation, await browserPageState(page, context, browser));
      result.status = "HARNESS_ERROR";
      result.runner_result = "HARNESS_ERROR";
    }
    result.completed_at = new Date().toISOString();
    result.metadata = currentRunMetadata(result.completed_at);
    result.browser_cleanup = true;
    if (!["FAIL", "BLOCKED", "HARNESS_ERROR"].includes(result.status)) result.status = result.steps.every((step) => step.test_result === "PASS") ? "PASS" : "FAIL";
    if (result.runner_result === "RUNNING") result.runner_result = result.status === "FAIL" ? "PRODUCT_FAIL" : result.status;
    await writeAtomically(journeyResultPath(id), result);
    await context?.close();
    await browser?.close();
  }
  return result.status;
}

async function incompleteJourneys(requested) {
  const candidates = requested.length ? requested : Object.keys(JOURNEYS);
  const pending = [];
  for (const id of candidates) {
    try {
      const result = JSON.parse(await readFile(journeyResultPath(id), "utf8"));
      if (shouldResume(result.status)) pending.push(id);
    } catch {
      pending.push(id);
    }
  }
  return pending;
}

async function assertLocalOnlyPreflight() {
  const assignments = await fetchJson(`${API_URL}/api/v1/model-assignments`);
  const agentAssignments = assignments.filter((item) => item.consumer_id === "agent");
  if (agentAssignments.length !== 4 || agentAssignments.some((item) => item.model_id !== LOCAL_MODEL_ID)) {
    throw new PreflightBlockedError("E2E requires every agent assignment to use local_quality.");
  }
  const models = await fetchJson(`${API_URL}/api/v1/models`);
  const model = models.find((item) => item.model_id === LOCAL_MODEL_ID);
  if (!model || model.provider !== "ollama" || model.provider_model !== "qwen3.5:9b" || model.execution_zone !== "LOCAL") {
    throw new PreflightBlockedError("local_quality does not resolve to Local Qwen 3.5 9B in the LOCAL zone.");
  }
}

async function assertConfigurationSnapshot(snapshot, operation) {
  assertAssignmentSnapshot(
    snapshot,
    await fetchJson(`${API_URL}/api/v1/model-assignments`),
    operation,
  );
}

async function preparePage(page, definition) {
  await page.goto(FRONTEND_URL, { waitUntil: "domcontentloaded" });
  await page.selectOption("#user-clearance", definition.clearance);
  await page.selectOption("#response-language", definition.language);
}

async function executeStep(page, context, result, step, clientErrors, failedFetches) {
  if (step.kind === "select") {
    await page.selectOption("#user-clearance", step.clearance);
    record(result, { label: `select clearance ${step.clearance}`, ...await pageContext(page), expected_severity: "SUCCESS", actual_severity: "SUCCESS", test_result: "PASS", note: "User explicitly changed clearance." });
    return;
  }
  if (step.kind === "new-chat") {
    await page.locator("#new-investigation-button").click();
    record(result, { label: "New Chat", clearance: await value(page, "#user-clearance"), language: await value(page, "#response-language"), expected_severity: "SUCCESS", actual_severity: "SUCCESS", test_result: "PASS", note: "Conversation reset through UI." });
    return;
  }
  if (step.kind === "typed") return submitTyped(page, context, result, step, clientErrors, failedFetches);
  if (step.kind === "reference") return clickReference(page, context, result, step, clientErrors, failedFetches);
  if (step.kind === "document") return openDocument(page, context, result, step, clientErrors, failedFetches);
  throw new Error(`Unsupported step kind: ${step.kind}`);
}

async function submitTyped(page, context, result, step, clientErrors, failedFetches) {
  const observation = observeNetwork(page, context);
  const before = await submitState(page);
  const initialTurns = await page.locator(".agent-turn").count();
  await page.locator("#composer-message").fill(step.prompt);
  await page.locator("#composer-button").click();
  const started = await waitForSubmissionStart(page, initialTurns);
  const afterTrigger = await submitState(page);
  result.network_observations = observation.metadata;
  result.submit_diagnostics ??= [];
  result.submit_diagnostics.push({ before, after_trigger: afterTrigger });
  if (!started) throw harnessSignal("SUBMIT_NOT_TRIGGERED", "Visible submit state did not start after the DOM click.");
  const terminal = await waitForTerminalAgentTurn(page, initialTurns);
  const runRequest = observation.requests.find(({ request }) => isRunPost(request));
  if (!runRequest) {
    const apiRequest = observation.requests.find(({ metadata }) => metadata.path.startsWith("/api/"));
    if (apiRequest) throw harnessSignal("REQUEST_CONTRACT_MISMATCH", "A UI API request was observed but did not match POST /api/v1/runs.");
    throw harnessSignal("REQUEST_NOT_OBSERVED", "The UI entered submission state but no API request was observed.");
  }
  const requestContext = safeRunRequestContext(runRequest.request);
  if (!requestContext || requestContext.clearance !== afterTrigger.clearance || requestContext.language !== afterTrigger.language) {
    throw harnessSignal("REQUEST_CONTRACT_MISMATCH", "The observed run request did not preserve selected clearance or language.");
  }
  if (!terminal) {
    record(result, { label: `typed: ${step.prompt}`, ...afterTrigger, expected_severity: step.expected, actual_severity: "FAILURE", test_result: "FAIL", note: "No terminal user-visible result after an observed run request.", request_context: requestContext });
    return;
  }
  const investigation = observation.responses.find(({ response }) => isInvestigationGet(response))?.response;
  await recordAgentResult(page, result, `typed: ${step.prompt}`, step, runRequest.request, investigation, clientErrors, failedFetches, null, requestContext);
}

async function clickReference(page, context, result, step, clientErrors, failedFetches) {
  const reference = await findReference(page, step.type, await value(page, "#response-language"));
  if (!reference) {
    record(result, {
      ...failedStep(`click ${step.type}`, step.expected, await pageContext(page), "No matching rendered reference was available.", step.optional),
      error_code: "REFERENCE_MISSING",
      failure_origin: "PRODUCT_UI",
    });
    return;
  }
  const referenceText = await reference.innerText();
  const action = actionFor(step.type, step.action, await value(page, "#response-language"));
  const visited = `${step.type}:${referenceText}:${action}`;
  if (result.visited.includes(visited) || result.click_depth >= 4) {
    record(result, failedStep(`click ${referenceText}`, step.expected, await pageContext(page), "Click graph bound rejected this reference.", false));
    return;
  }
  result.visited.push(visited);
  result.click_depth += 1;
  const observation = observeNetwork(page, context);
  const initialTurns = await page.locator(".agent-turn").count();
  await page.locator(".reference-popover .reference-action", { hasText: action }).click();
  if (!await waitForSubmissionStart(page, initialTurns)) throw harnessSignal("SUBMIT_NOT_TRIGGERED", "Visible reference action did not start submission.");
  const terminal = await waitForTerminalAgentTurn(page, initialTurns);
  const runRequest = observation.requests.find(({ request }) => isRunPost(request));
  if (!runRequest) throw harnessSignal("REQUEST_NOT_OBSERVED", "Reference action entered submission state but no run request was observed.");
  const requestContext = safeRunRequestContext(runRequest.request);
  const contextNow = await pageContext(page);
  if (!requestContext || requestContext.clearance !== contextNow.clearance || requestContext.language !== contextNow.language) throw harnessSignal("REQUEST_CONTRACT_MISMATCH", "Reference run request did not preserve selected context.");
  if (!terminal) {
    record(result, { label: `click ${step.type}: ${referenceText} / ${action}`, ...contextNow, expected_severity: step.expected, actual_severity: "FAILURE", test_result: "FAIL", note: "No terminal user-visible result after observed reference request.", request_context: requestContext, clicked_reference_type: step.type });
    return;
  }
  const investigation = observation.responses.find(({ response }) => isInvestigationGet(response))?.response;
  await recordAgentResult(page, result, `click ${step.type}: ${referenceText} / ${action}`, step, runRequest.request, investigation, clientErrors, failedFetches, referenceText, requestContext);
}

async function openDocument(page, context, result, step, clientErrors, failedFetches) {
  const button = page.locator(".document-action").first();
  if (!await button.count()) {
    record(result, failedStep("document open", step.expected, await pageContext(page), "No rendered document action was available.", false));
    return;
  }
  const responsePromise = page.waitForResponse((response) => /\/api\/v1\/documents\/[^/]+\?/.test(response.url()), { timeout: 20_000 });
  await button.click();
  const response = await responsePromise;
  const actual = response.ok() ? "SUCCESS" : "ATTENTION";
  record(result, { label: "document open", ...await pageContext(page), expected_severity: step.expected, actual_severity: actual, test_result: actual === step.expected ? "PASS" : "FAIL", note: response.url(), clicked_reference_type: "document" });
}

async function recordAgentResult(page, result, label, step, request, investigationResponse, clientErrors, failedFetches, clickedIdentifier = null, observedRequestContext = null) {
  const context = await pageContext(page);
  const body = request.postDataJSON();
  let turn = null;
  if (investigationResponse) {
    let investigation;
    try { investigation = await investigationResponse.json(); }
    catch {
      record(result, { label, ...context, expected_severity: step.expected, actual_severity: "FAILURE", test_result: "FAIL", note: "invalid investigation response", clicked_reference_type: clickedIdentifier ? step.type : null, context_preserved: false, language_preserved: false, semantic_target: clickedIdentifier, run_status: null, error_code: "invalid_investigation_response", failure_origin: "product_response_invalid", request_context: observedRequestContext, investigation_response_observed: true });
      return;
    }
    if (!Array.isArray(investigation.turns)) {
      record(result, { label, ...context, expected_severity: step.expected, actual_severity: "FAILURE", test_result: "FAIL", note: "invalid investigation response", clicked_reference_type: clickedIdentifier ? step.type : null, context_preserved: false, language_preserved: false, semantic_target: clickedIdentifier, run_status: null, error_code: "invalid_investigation_response", failure_origin: "product_response_invalid", request_context: observedRequestContext, investigation_response_observed: true });
      return;
    }
    turn = investigation.turns.at(-1);
  }
  const agentTurn = page.locator(".agent-turn").last();
  await agentTurn.waitFor({ state: "visible" });
  const text = await agentTurn.innerText();
  const actual = await userSeverity(agentTurn, text);
  const faults = [...clientErrors, ...failedFetches, ...technicalFaults(text)];
  const contextOk = body.user_clearance === context.clearance && body.response_language === context.language && (!turn || (turn.response_language === context.language && CLEARANCE_RANK[turn.data_classification] <= CLEARANCE_RANK[context.clearance]));
  const semanticOk = !clickedIdentifier || step.expected === "ATTENTION" || text.includes(clickedIdentifier);
  const leakFree = step.expected !== "ATTENTION" || !text.includes(clickedIdentifier);
  const languageOk = hasLanguageSignal(text, context.language, actual);
  const testResult = actual === step.expected && contextOk && semanticOk && leakFree && languageOk && !faults.length ? "PASS" : "FAIL";
  record(result, { label, ...context, expected_severity: step.expected, actual_severity: actual, test_result: testResult, note: faults.join("; ") || (!leakFree ? "Protected identifier leaked in access denial." : null), clicked_reference_type: clickedIdentifier ? step.type : null, context_preserved: contextOk, language_preserved: languageOk, semantic_target: clickedIdentifier, run_status: turn?.status ?? null, error_code: turn?.error?.code ?? null, failure_origin: turn?.error?.failure_origin ?? null, request_context: observedRequestContext, investigation_response_observed: Boolean(investigationResponse) });
}

async function smokeControls(page, result) {
  await page.locator("#model-configuration-button").click();
  const dialogOpen = await page.locator("#model-configuration-dialog").evaluate((dialog) => dialog.open);
  if (dialogOpen) await page.locator("#model-configuration-close").click();
  const monitoring = page.locator(".monitoring-menu");
  await monitoring.locator("summary").click();
  const dashboard = monitoring.locator("a").first();
  result.smoke = { model_configuration: dialogOpen ? "PASS" : "FAIL", monitoring: await dashboard.getAttribute("href") ? "PASS" : "FAIL" };
}

async function findReference(page, type, language) {
  const references = page.locator(".structured-reference");
  const expectedAction = actionFor(type, type === "error_code" ? "search" : "status", language);
  for (let index = await references.count() - 1; index >= 0; index -= 1) {
    const reference = references.nth(index);
    await reference.click();
    const action = page.locator(".reference-popover .reference-action");
    const labels = await action.allInnerTexts();
    if (labels.includes(expectedAction) || (type === "error_code" && labels.includes(actionFor(type, "investigate", language)))) {
      return reference;
    }
  }
  return null;
}

function actionFor(type, action, language) {
  const german = language === "DE";
  const labels = {
    station: german ? "Aktuellen Status prüfen" : "Check current status",
    product: german ? "Produkthistorie anzeigen" : "Show product history",
    error_code: action === "search" ? (german ? "Dokumentation suchen" : "Search documentation") : (german ? "Untersuchen" : "Investigate"),
  };
  return labels[type];
}

function isRunPost(request) { return isRunRequestMetadata({ method: request.method(), url: request.url() }); }
function isInvestigationGet(response) { return response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/investigations/") && response.ok(); }
function observeNetwork(page, context) {
  const requests = [];
  const responses = [];
  const metadata = [];
  const observeRequest = (scope) => (request) => {
    const item = { request, metadata: safeRequestMetadata(request, scope) };
    requests.push(item);
    metadata.push(item.metadata);
  };
  page.on("request", observeRequest("page"));
  context.on("request", observeRequest("context"));
  page.on("response", (response) => responses.push({ response }));
  context.on("response", (response) => responses.push({ response }));
  return { requests, responses, metadata };
}
async function submitState(page) {
  const input = page.locator("#composer-message");
  const button = page.locator("#composer-button");
  const form = page.locator("#composer-form");
  return {
    url: page.url(),
    input_exists: await input.count() > 0,
    input_visible: await input.isVisible(),
    input_enabled: await input.isEnabled(),
    input_value_length: (await input.inputValue()).length,
    submit_exists: await button.count() > 0,
    submit_visible: await button.isVisible(),
    submit_enabled: await button.isEnabled(),
    form_exists: await form.count() > 0,
    loading: await page.locator("#run-status[data-status='running'], .agent-turn.is-pending").count() > 0,
    clearance: await value(page, "#user-clearance"),
    language: await value(page, "#response-language"),
  };
}
async function waitForSubmissionStart(page, initialTurns) {
  try {
    await page.waitForFunction((before) => document.querySelector("#composer-button")?.disabled || document.querySelector("#run-status")?.dataset.status === "running" || document.querySelectorAll(".agent-turn").length > before, initialTurns, { timeout: 10_000 });
    return true;
  } catch { return false; }
}
async function waitForTerminalAgentTurn(page, initialTurns) {
  try {
    await page.waitForFunction((before) => {
      const turns = document.querySelectorAll(".agent-turn");
      const latest = turns[turns.length - 1];
      return turns.length > before && latest && !latest.classList.contains("is-pending");
    }, initialTurns, { timeout: 100_000 });
    return true;
  } catch { return false; }
}
function safeRunRequestContext(request) {
  try {
    const body = request.postDataJSON();
    if (!body || typeof body !== "object") return null;
    return { clearance: body.user_clearance, language: body.response_language, has_investigation_id: typeof body.investigation_id === "string" };
  } catch { return null; }
}
function harnessSignal(category, message) { const error = new Error(message); error.name = category; return error; }
async function value(page, selector) { return page.locator(selector).inputValue(); }
async function browserPageState(page, context, browser) {
  const safely = (operation) => { try { return operation(); } catch { return null; } };
  return { page_closed: safely(() => page?.isClosed()) ?? null, context_closed: safely(() => !context || context.pages().length === 0) ?? null, browser_connected: safely(() => browser?.isConnected()) ?? null };
}
async function pageContext(page) { return { clearance: await value(page, "#user-clearance"), language: await value(page, "#response-language") }; }
async function userSeverity(agentTurn, text) {
  if (await agentTurn.locator(".turn-attention").count()) return "ATTENTION";
  return (await agentTurn.locator(".turn-error").count()) ? "FAILURE" : "SUCCESS";
}
function hasLanguageSignal(text, language, severity) {
  if (severity === "ATTENTION") return language === "DE" ? /nicht|verfuegbar|verfügbar|zugriff/i.test(text) : /not|available|access/i.test(text);
  return language === "DE" ? /der|die|das|und|Station|Produkt/i.test(text) : /the|station|product|available|is/i.test(text);
}
function technicalFaults(text) { return /invalid run response|internal_error|model_output_invalid|mcp.*(failed|unavailable)/i.test(text) ? ["user-facing technical failure"] : []; }
function failedStep(label, expected, context, note, optional) { return { label, ...context, expected_severity: expected, actual_severity: optional ? "ATTENTION" : "FAILURE", test_result: optional ? "PASS" : "FAIL", note, clicked_reference_type: null }; }
function startResult(id, definition, metadata) { return { id, journey: definition.name, tags: definition.tags, metadata, planned_language: definition.language, planned_clearance: definition.clearance, started_at: new Date().toISOString(), real_model: "Local Qwen 3.5 9B", model_id: LOCAL_MODEL_ID, reasoning_effort: "none", external_provider_calls: 0, status: "RUNNING", runner_result: "RUNNING", steps: [], visited: [], click_depth: 0 }; }
function record(result, step) { result.steps.push(step); }
function journeyResultPath(id) { return path.join(RESULTS_DIRECTORY, `journey-${id}.json`); }
async function fetchJson(url) { const response = await fetch(url); if (!response.ok) throw new Error(`Preflight request failed: ${response.status}`); return response.json(); }
async function probeMcpReadiness(url, requiredTools) {
  const token = await localEnvironmentValue("MCP_INDUSTRIAL_AGENT_TOKEN");
  if (!token) throw new Error("MCP_INDUSTRIAL_AGENT_TOKEN is unavailable for protocol readiness.");
  const init = await mcpRequest(url, {
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "manual-e2e-preflight", version: "1.0" } },
  }, token);
  if (!mcpPayload(init).result) throw new Error("MCP initialize did not return a protocol result.");
  const sessionId = init.headers.get("mcp-session-id");
  if (!sessionId) throw new Error("MCP initialize did not provide a session id.");
  await mcpRequest(url, { jsonrpc: "2.0", method: "notifications/initialized", params: {} }, token, sessionId, false);
  const tools = await mcpRequest(url, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }, token, sessionId);
  const names = mcpPayload(tools).result?.tools?.map((tool) => tool.name) ?? [];
  const missing = requiredTools.filter((tool) => !names.includes(tool));
  if (missing.length) throw new Error(`MCP required tools unavailable: ${missing.join(", ")}`);
  return `protocol ready; tools: ${requiredTools.join(", ")}`;
}
async function mcpRequest(url, payload, token, sessionId = null, requiresResponse = true) {
  const headers = { Authorization: `Bearer ${token}`, Accept: "application/json, text/event-stream", "Content-Type": "application/json" };
  if (sessionId) headers["Mcp-Session-Id"] = sessionId;
  const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(payload) });
  if (!response.ok) throw new Error(`MCP protocol request failed: ${response.status}`);
  if (requiresResponse) await response.text().then((text) => { response.mcpBody = text; });
  return response;
}
function mcpPayload(response) {
  const body = response.mcpBody ?? "";
  const data = body.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).at(-1) ?? body;
  try { return JSON.parse(data); } catch { throw new Error("MCP protocol response was not valid JSON-RPC."); }
}
async function localEnvironmentValue(key) {
  if (process.env[key]) return process.env[key];
  try {
    const content = await readFile(path.join(ROOT, ".env"), "utf8");
    const line = content.split(/\r?\n/).find((entry) => entry.startsWith(`${key}=`));
    return line?.slice(key.length + 1).trim().replace(/^['"]|['"]$/g, "") ?? null;
  } catch { return null; }
}
async function writeAtomically(target, value) { await mkdir(path.dirname(target), { recursive: true }); const temporary = `${target}.${process.pid}.${Date.now()}.tmp`; const handle = await open(temporary, "w"); try { await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf8"); await handle.sync(); } finally { await handle.close(); } await rename(temporary, target); }
async function writeTextAtomically(target, value) { await mkdir(path.dirname(target), { recursive: true }); const temporary = `${target}.${process.pid}.${Date.now()}.tmp`; const handle = await open(temporary, "w"); try { await handle.writeFile(value, "utf8"); await handle.sync(); } finally { await handle.close(); } await rename(temporary, target); }

async function aggregateResults() {
  try {
    latestAssignmentSnapshot = assignmentSnapshot(
      await fetchJson(`${API_URL}/api/v1/model-assignments`),
    );
  } catch {
    // The aggregate remains useful for a blocked run even if the API is unavailable.
  }
  const journeys = [];
  for (const id of Object.keys(JOURNEYS)) {
    try { journeys.push(JSON.parse(await readFile(journeyResultPath(id), "utf8"))); } catch { journeys.push({ id, journey: JOURNEYS[id].name, status: "MISSING", steps: [] }); }
  }
  const steps = journeys.flatMap((journey) => journey.steps.map((step) => ({ journey: journey.id, ...step })));
  const count = (predicate) => steps.filter(predicate).length;
  const finishedAt = new Date().toISOString();
  const journeySummary = journeys.map((journey) => ({ journey: journey.journey, steps: journey.steps.length, success: journey.steps.filter((step) => step.actual_severity === "SUCCESS").length, attention: journey.steps.filter((step) => step.actual_severity === "ATTENTION").length, failure: journey.steps.filter((step) => step.actual_severity === "FAILURE").length, result: journey.status }));
  const executionStatus = journeys.some((journey) => journey.status === "HARNESS_ERROR") ? "HARNESS_ERROR"
    : journeys.some((journey) => journey.status === "BLOCKED") ? "BLOCKED"
      : journeys.some((journey) => journey.status === "MISSING") ? "INCOMPLETE"
        : journeys.some((journey) => journey.status === "FAIL") ? "FAIL"
          : "PASS";
  const summary = {
    metadata: currentRunMetadata(finishedAt),
    run_id: RUN_ID,
    started_at: RUN_STARTED_AT,
    finished_at: finishedAt,
    execution_status: executionStatus,
    product_quality_gate: journeys.some((journey) => journey.status === "FAIL") ? "FAIL" : "PASS",
    generated_at: new Date().toISOString(), real_model: "Local Qwen 3.5 9B", external_provider_calls: 0,
    planned_journeys: Object.keys(JOURNEYS).length, completed_journeys: journeys.filter((journey) => !["MISSING", "BLOCKED"].includes(journey.status)).length,
    journeys,
    table: steps.map((step) => ({ id: step.journey, journey: journeys.find((item) => item.id === step.journey)?.journey ?? step.journey, step: step.label, clearance: step.clearance, language: step.language, expected_severity: step.expected_severity, actual_severity: step.actual_severity, test_result: step.test_result, error_code: step.error_code ?? null, failure_origin: step.failure_origin ?? null, error_or_note: step.note })),
    journey_summary: journeySummary,
    coverage: coverageReport(journeys, steps),
    totals: { steps: steps.length, pass: count((step) => step.test_result === "PASS"), attention: count((step) => step.actual_severity === "ATTENTION"), failure: count((step) => step.actual_severity === "FAILURE") },
    by_clearance: groupBy(steps, "clearance"), by_language: groupBy(steps, "language"), by_scenario: groupBy(steps, "journey"), by_error_code: groupBy(steps, "error_code"), by_failure_origin: groupBy(steps, "failure_origin"), by_clicked_reference_type: groupBy(steps, "clicked_reference_type"),
  };
  await writeAtomically(path.join(RESULTS_DIRECTORY, "summary.json"), summary);
  await writeTextAtomically(path.join(RESULTS_DIRECTORY, "summary.md"), renderSummaryMarkdown(summary));
  await writeAtomically(path.join(RESULTS_DIRECTORY, "browser-e2e-summary.json"), summary);
}

async function compareReports(previousPath) {
  const previous = JSON.parse(await readFile(path.resolve(process.cwd(), previousPath), "utf8"));
  const current = JSON.parse(await readFile(path.join(RESULTS_DIRECTORY, "browser-e2e-summary.json"), "utf8"));
  const index = (report) => new Map(report.table.map((step) => [`${step.id}:${step.step}`, `${step.actual_severity}:${step.test_result}:${step.error_code ?? "NONE"}:${step.failure_origin ?? "NONE"}`]));
  const oldSteps = index(previous);
  const newSteps = index(current);
  const changes = { new_pass: [], new_attention: [], new_fail: [], fixed_fail: [], regressions: [], unchanged_fail: [] };
  for (const [key, value] of newSteps) {
    const old = oldSteps.get(key);
    const failure = value.includes(":FAIL:");
    const oldFailure = old?.includes(":FAIL:");
    if (!old) changes[failure ? "new_fail" : value.startsWith("ATTENTION") ? "new_attention" : "new_pass"].push(key);
    else if (oldFailure && !failure) changes.fixed_fail.push(key);
    else if (!oldFailure && failure) changes.regressions.push(key);
    else if (oldFailure && failure) changes.unchanged_fail.push(key);
  }
  await writeAtomically(path.join(RESULTS_DIRECTORY, "comparison.json"), { previous: previousPath, current_run: RUN_ID, changes });
}

function groupBy(steps, field) { return Object.fromEntries(Object.entries(steps.reduce((groups, step) => { const key = step[field] ?? "NONE"; groups[key] ??= { steps: 0, pass: 0, attention: 0, failure: 0 }; groups[key].steps += 1; groups[key].pass += Number(step.test_result === "PASS"); groups[key].attention += Number(step.actual_severity === "ATTENTION"); groups[key].failure += Number(step.actual_severity === "FAILURE"); return groups; }, {}))); }

function coverageReport(journeys, steps) {
  const tags = journeys.map((journey) => journey.tags).filter(Boolean);
  const values = (field) => [...new Set(tags.flatMap((tag) => Array.isArray(tag[field]) ? tag[field] : [tag[field]]).filter(Boolean))];
  const clearance = Object.fromEntries(["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].map((level) => [level, { planned: tags.some((tag) => tag.clearance === level), success: steps.some((step) => step.clearance === level && step.actual_severity === "SUCCESS"), attention: steps.some((step) => step.clearance === level && step.actual_severity === "ATTENTION"), attention_not_applicable: tags.some((tag) => tag.clearance === level && tag.attention_reason) ? tags.find((tag) => tag.clearance === level && tag.attention_reason).attention_reason : null }]));
  return { clearances: clearance, languages: values("language"), domains: values("domain"), interactions: values("interaction"), expected_user_severities: values("expected_user_severity"), multi_turn_journeys: tags.filter((tag) => tag.multi_turn === "yes").length, mixed_typed_follow_up_and_click: tags.filter((tag) => tag.interaction.includes("typed-follow-up") && tag.interaction.some((item) => item.endsWith("-click"))).length };
}
