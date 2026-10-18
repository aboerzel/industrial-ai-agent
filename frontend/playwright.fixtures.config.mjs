import { defineConfig } from "@playwright/test";

// Synthetic local HTTP fixture only; no credentials, Compose, MCP or models.
export default defineConfig({
  globalSetup: "./scripts/runtime-global-setup.mjs",
  retries: 0,
  testDir: "../tests/e2e/fixtures",
  fullyParallel: false,
  workers: 1,
  timeout: 20_000,
  expect: { timeout: 3_000 },
  use: { acceptDownloads: true, trace: "off" },
  reporter: "list",
  outputDir: "../evals/results/browser-e2e/fixtures",
});
