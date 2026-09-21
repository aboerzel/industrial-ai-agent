import { mkdir, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const RESULTS_ROOT = path.join(ROOT, "evals", "results", "browser-e2e");
const arguments_ = process.argv.slice(2);
const resume = arguments_.includes("--resume");
const requested = valuesAfter(arguments_, "--journey");
const runId = valueAfter(arguments_, "--run-id") ?? (resume ? await latestRunId() : createRunId());

await mkdir(RESULTS_ROOT, { recursive: true });
await writeFile(path.join(RESULTS_ROOT, "latest-run.txt"), `${runId}\n`, "utf8");
const preflightResult = await runChild(["scripts/run-e2e-journey.mjs", "--preflight", "--run-id", runId]);
const journeys = requested.length ? requested : [];
const common = ["scripts/run-e2e-journey.mjs", "--run-id", runId];
if (preflightResult !== 0) {
  await runChild([...common, "--aggregate"]);
  process.exitCode = preflightResult;
} else {
  const runArguments = journeys.length ? journeys.flatMap((journey) => ["--journey", journey]) : ["--all"];
  if (resume) runArguments.push("--resume");
  const result = await runChild([...common, ...runArguments]);
  await runChild([...common, "--aggregate"]);
  process.exitCode = result;
}

function createRunId() {
  return `run-${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

async function latestRunId() {
  try { return (await readFile(path.join(RESULTS_ROOT, "latest-run.txt"), "utf8")).trim(); }
  catch { return createRunId(); }
}

function valueAfter(values, flag) {
  const index = values.indexOf(flag);
  return index >= 0 ? values[index + 1] : null;
}

function valuesAfter(values, flag) {
  return values.flatMap((value, index) => value === flag && values[index + 1] ? [values[index + 1]] : []);
}

function runChild(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, { cwd: path.join(ROOT, "frontend"), stdio: "inherit" });
    child.on("exit", (code) => resolve(code ?? 1));
  });
}
