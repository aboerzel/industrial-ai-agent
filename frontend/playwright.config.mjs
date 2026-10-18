import { defineConfig } from "@playwright/test";
import { modelAdminHeaders } from "./scripts/e2e-http.mjs";
import { mkdir } from "node:fs/promises";
import path from "node:path";

await modelAdminHeaders();
const frontendUrl = process.env.E2E_FRONTEND_URL ?? "http://127.0.0.1:8080";
const runDirectory = path.resolve(import.meta.dirname, "../evals/results/browser-e2e", `legacy-${new Date().toISOString().replace(/[:.]/g, "-")}`);
await mkdir(path.dirname(runDirectory), { recursive: true });
await mkdir(runDirectory, { recursive: false });

export default defineConfig({
  globalSetup: "./scripts/runtime-global-setup.mjs",
  testDir: "../tests/e2e",
  testIgnore: "**/fixtures/**",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 180_000 },
  use: {
    baseURL: frontendUrl,
    trace: "off",
  },
  outputDir: path.join(runDirectory, "artifacts"),
  reporter: [["list"], ["json", { outputFile: path.join(runDirectory, "playwright.json") }],
    ["./scripts/legacy-browser-reporter.mjs", { directory: runDirectory }]],
});
