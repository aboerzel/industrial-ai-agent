import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  timeout: 180_000,
  expect: { timeout: 180_000 },
  use: {
    baseURL: process.env.E2E_FRONTEND_URL ?? "http://127.0.0.1:8080",
    trace: "retain-on-failure",
  },
  reporter: [["list"], ["json", { outputFile: "../evals/results/browser-e2e-results.json" }]],
});
